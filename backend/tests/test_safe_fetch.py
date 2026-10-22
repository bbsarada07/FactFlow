"""SSRF guard: address checks, redirect re-validation, pinning to the checked IP, size and redirect caps."""
import asyncio

import httpx
import pytest

from services.safe_fetch import FetchBlocked, expand_link, ip_allowed, safe_request

PUBLIC = "93.184.216.34"


def resolver(table: dict[str, list[str]]):
    async def resolve(host, port):
        return table[host]
    return resolve


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("ip, allowed", [
    ("127.0.0.1", False), ("10.1.2.3", False), ("172.16.0.1", False), ("192.168.1.1", False),
    ("169.254.169.254", False), ("100.64.0.1", False), ("0.0.0.0", False), ("224.0.0.1", False),
    ("::1", False), ("fc00::1", False), ("fe80::1", False), ("::ffff:127.0.0.1", False), ("not-an-ip", False),
    ("8.8.8.8", True), (PUBLIC, True), ("2606:4700:4700::1111", True),
])
def test_ip_allowed(ip, allowed):
    assert ip_allowed(ip) is allowed


def test_fetches_public_host_by_its_checked_address():
    seen = {}

    def handler(request: httpx.Request):
        seen.update(host=request.url.host, header=request.headers["host"], sni=request.extensions.get("sni_hostname"))
        return httpx.Response(200, text="hello", headers={"content-type": "text/html"})

    r = run(safe_request("https://news.example/a", resolver=resolver({"news.example": [PUBLIC]}),
                         transport=httpx.MockTransport(handler)))
    assert r.status == 200 and r.body == b"hello"
    assert seen == {"host": PUBLIC, "header": "news.example", "sni": "news.example"}


@pytest.mark.parametrize("addresses", [["127.0.0.1"], ["10.0.0.7"], [PUBLIC, "192.168.0.10"], []])
def test_private_or_mixed_answers_are_blocked(addresses):
    with pytest.raises(FetchBlocked):
        run(safe_request("http://evil.example/", resolver=resolver({"evil.example": addresses}),
                         transport=httpx.MockTransport(lambda r: httpx.Response(200))))


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.org/x", "gopher://x/", "http:///nohost"])
def test_non_http_urls_are_blocked(url):
    with pytest.raises(FetchBlocked):
        run(safe_request(url))


def test_redirect_to_a_private_address_is_blocked():
    def handler(request):
        return httpx.Response(302, headers={"location": "http://internal.example/admin"})

    with pytest.raises(FetchBlocked):
        run(safe_request("http://short.example/x",
                         resolver=resolver({"short.example": [PUBLIC], "internal.example": ["10.0.0.2"]}),
                         transport=httpx.MockTransport(handler)))


def test_redirect_to_another_scheme_is_blocked():
    with pytest.raises(FetchBlocked):
        run(safe_request("http://short.example/x", resolver=resolver({"short.example": [PUBLIC]}),
                         transport=httpx.MockTransport(lambda r: httpx.Response(301, headers={"location": "file:///etc/hosts"}))))


def test_too_many_redirects():
    with pytest.raises(FetchBlocked):
        run(safe_request("http://loop.example/", resolver=resolver({"loop.example": [PUBLIC]}), max_redirects=3,
                         transport=httpx.MockTransport(lambda r: httpx.Response(302, headers={"location": "/again"}))))


def test_redirects_are_followed_and_recorded_without_cookies():
    cookies_sent = []

    def handler(request):
        cookies_sent.append(request.headers.get("cookie"))
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "https://final.example/page", "set-cookie": "s=1"})
        return httpx.Response(200, text="done")

    r = run(safe_request("https://short.example/start",
                         resolver=resolver({"short.example": [PUBLIC], "final.example": ["8.8.4.4"]}),
                         transport=httpx.MockTransport(handler)))
    assert r.url == "https://final.example/page" and r.redirects == ["https://final.example/page"]
    assert cookies_sent == [None, None]


def test_body_is_capped():
    r = run(safe_request("http://big.example/", max_bytes=10, resolver=resolver({"big.example": [PUBLIC]}),
                         transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 1000))))
    assert r.truncated and len(r.body) == 10


def test_expand_link_falls_back_to_get_when_head_is_refused():
    methods = []

    def handler(request):
        methods.append(request.method)
        if request.method == "HEAD":
            return httpx.Response(405)
        if request.url.path == "/s":
            return httpx.Response(301, headers={"location": "https://landing.example/offer"})
        return httpx.Response(200, content=b"page body that is never fully read")

    r = run(expand_link("https://bit.example/s",
                        resolver=resolver({"bit.example": [PUBLIC], "landing.example": ["8.8.4.4"]}),
                        transport=httpx.MockTransport(handler)))
    assert r.url == "https://landing.example/offer" and methods[0] == "HEAD" and len(r.body) <= 1
