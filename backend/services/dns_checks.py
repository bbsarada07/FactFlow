"""Optional DNS checks of the sender's domain (ENABLE_DNS_CHECKS, off by default).

Looks up whether the domain publishes SPF and DMARC records (3 second limit). A missing record is
a weak signal; a lookup that fails or times out gives no signal at all.
"""
from __future__ import annotations

import dns.asyncresolver
import dns.exception
import dns.resolver

TIMEOUT = 3.0


async def _txt(name: str) -> list[str] | None:
    """TXT strings for `name`; [] when there are none; None when the lookup failed."""
    resolver = dns.asyncresolver.Resolver()
    resolver.lifetime = TIMEOUT
    try:
        answer = await resolver.resolve(name, "TXT")
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except (dns.exception.DNSException, OSError):
        return None
    return [b"".join(r.strings).decode("utf-8", "replace") for r in answer]


async def sender_records(domain: str) -> list[tuple[str, str]]:
    """(signal, severity) pairs for a sender domain with no SPF or DMARC record."""
    if not domain:
        return []
    signals = []
    spf = await _txt(domain)
    if spf is not None and not any(t.lower().startswith("v=spf1") for t in spf):
        signals.append((f"{domain} publishes no SPF record", "low"))
    dmarc = await _txt(f"_dmarc.{domain}")
    if dmarc is not None and not any(t.lower().startswith("v=dmarc1") for t in dmarc):
        signals.append((f"{domain} publishes no DMARC record", "low"))
    return signals
