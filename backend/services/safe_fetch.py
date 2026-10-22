"""The one way FactFlow fetches anything from a URL it did not choose (SSRF guard).

Every outbound request to a user- or content-supplied URL goes through `safe_request`:
  * only http and https;
  * the host is resolved first, and every resolved address must be public (no private, loopback,
    link-local, cloud-metadata, carrier-grade NAT, multicast or reserved ranges);
  * the connection goes to the address that was checked (so a DNS answer cannot change between
    the check and the connection), with the original host name sent for TLS (SNI) and in Host;
  * redirects are followed by hand, at most `max_redirects`, and every hop is checked again;
  * no cookies, no proxy settings from the environment, a total time limit and a body size cap.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

USER_AGENT = "Mozilla/5.0 (compatible; FactFlow/1.0; +https://github.com/bbsarada07/FactFlow)"
REDIRECT_CODES = {301, 302, 303, 307, 308}
DEFAULT_PORTS = {"http": 80, "https": 443}

Resolver = Callable[[str, int], Awaitable[list[str]]]


class FetchBlocked(Exception):
    """The request was refused before or during sending (unsafe address, scheme, too many redirects)."""


class FetchError(Exception):
    """The request was allowed but failed (timeout, connection error, bad response)."""


@dataclass
class SafeResponse:
    url: str  # final URL after redirects
    status: int
    headers: dict[str, str]
    body: bytes = b""
    truncated: bool = False
    redirects: list[str] = field(default_factory=list)

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "")


def ip_allowed(ip: str) -> bool:
    """True only for globally routable unicast addresses."""
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


async def system_resolver(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return list(dict.fromkeys(info[4][0] for info in infos))


def _check_url(url: str) -> tuple[str, str, int]:
    parts = urlsplit(url)
    scheme = (parts.scheme or "").lower()
    if scheme not in DEFAULT_PORTS:
        raise FetchBlocked(f"only http and https URLs can be fetched (got {scheme or 'none'!r})")
    try:
        host, port = parts.hostname, parts.port or DEFAULT_PORTS[scheme]
    except ValueError as exc:
        raise FetchBlocked("the URL has an invalid port") from exc
    if not host:
        raise FetchBlocked("the URL has no host")
    return scheme, host, port


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


async def safe_request(
    url: str,
    method: str = "GET",
    *,
    max_bytes: int = 2_000_000,
    timeout: float = 10.0,
    max_redirects: int = 5,
    accept: str = "*/*",
    resolver: Resolver = system_resolver,
    transport: httpx.AsyncBaseTransport | None = None,
) -> SafeResponse:
    """Fetch `url` under the SSRF rules above. Raises FetchBlocked or FetchError."""
    deadline = time.monotonic() + timeout
    redirects: list[str] = []
    for _hop in range(max_redirects + 1):
        scheme, host, port = _check_url(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FetchError("timed out")
        if _is_ip_literal(host):
            ips = [host]
        else:
            try:
                ips = await asyncio.wait_for(resolver(host, port), timeout=remaining)
            except (OSError, asyncio.TimeoutError) as exc:
                raise FetchError(f"could not resolve {host}") from exc
        if not ips or not all(ip_allowed(ip) for ip in ips):
            raise FetchBlocked(f"{host} points to a private or reserved network address")
        ip = ips[0]
        parts = urlsplit(url)
        netloc_ip = f"[{ip}]" if ":" in ip else ip
        if parts.port:
            netloc_ip += f":{parts.port}"
        target = urlunsplit((scheme, netloc_ip, parts.path or "/", parts.query, ""))
        host_header = host if port == DEFAULT_PORTS[scheme] else f"{host}:{port}"
        headers = {"Host": host_header, "User-Agent": USER_AGENT, "Accept": accept}
        extensions = {"sni_hostname": host} if scheme == "https" and not _is_ip_literal(host) else {}
        try:
            async with httpx.AsyncClient(transport=transport, timeout=max(0.1, deadline - time.monotonic()),
                                         follow_redirects=False, trust_env=False) as client:
                request = client.build_request(method, target, headers=headers, extensions=extensions)
                response = await client.send(request, stream=True)
                try:
                    if response.status_code in REDIRECT_CODES and response.headers.get("location"):
                        url = urljoin(url, response.headers["location"])
                        redirects.append(url)
                        if response.status_code == 303 and method != "HEAD":
                            method = "GET"
                        continue
                    body, truncated = b"", False
                    if method != "HEAD":
                        chunks, size = [], 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > max_bytes:
                                chunks.append(chunk[: max_bytes - (size - len(chunk))])
                                truncated = True
                                break
                            chunks.append(chunk)
                        body = b"".join(chunks)
                    return SafeResponse(url=url, status=response.status_code,
                                        headers={k.lower(): v for k, v in response.headers.items()},
                                        body=body, truncated=truncated, redirects=redirects)
                finally:
                    await response.aclose()
        except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
            raise FetchError("timed out") from exc
        except httpx.HTTPError as exc:
            raise FetchError(f"request failed: {type(exc).__name__}") from exc
    raise FetchBlocked(f"more than {max_redirects} redirects")


async def expand_link(url: str, *, timeout: float = 3.0, max_redirects: int = 5,
                      resolver: Resolver = system_resolver,
                      transport: httpx.AsyncBaseTransport | None = None) -> SafeResponse:
    """Follow a (shortened) link to where it ends up without downloading any page body.

    HEAD first; if the server refuses HEAD, GET with a 1-byte body cap.
    """
    resp = await safe_request(url, "HEAD", timeout=timeout, max_redirects=max_redirects, resolver=resolver,
                              transport=transport)
    if resp.status in (403, 405, 501):
        resp = await safe_request(url, "GET", max_bytes=1, timeout=timeout, max_redirects=max_redirects,
                                  resolver=resolver, transport=transport)
    return resp
