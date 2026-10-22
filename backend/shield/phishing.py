"""Phishing checks (master prompt section 4.5): authentication headers, sender consistency,
lookalike domains and links.

No URL is fetched and no DNS lookup is made here. Link expansion (ENABLE_LINK_EXPANSION) and DNS
checks (ENABLE_DNS_CHECKS) need the SSRF-guarded fetcher and are added in Phase 2; both default
to off.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from shield import domains, settings
from shield.hidden_content import LinkRef, homoglyph_findings
from shield.schemas import SEVERITY_RANK, HiddenFinding, LinkItem, Lookalike
from shield.textnorm import strip_invisible

_RESULT = {
    "pass": "pass", "fail": "fail", "hardfail": "fail", "permerror": "fail", "softfail": "softfail",
    "neutral": "none", "none": "none", "temperror": "unknown", "policy": "unknown",
}
_AR_METHOD = re.compile(r"\b(spf|dkim|dmarc)\s*=\s*([a-z]+)", re.IGNORECASE)
_TEXT_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"'()\[\]{}]+", re.IGNORECASE)
_EMAIL_IN_TEXT = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
LONG_URL = 200
MANY_SUBDOMAINS = 4


@dataclass
class AuthResult:
    spf: str = "unknown"
    dkim: str = "unknown"
    dmarc: str = "unknown"


def parse_auth(authentication_results: list[str], received_spf: list[str], dkim_present: bool) -> AuthResult:
    """SPF/DKIM/DMARC outcome from the topmost Authentication-Results header (added by the
    receiving server), falling back to Received-SPF. Values: pass, fail, softfail, none, unknown."""
    res = AuthResult()
    if authentication_results:
        for method, value in _AR_METHOD.findall(authentication_results[0]):
            method = method.lower()
            if getattr(res, method) == "unknown":
                setattr(res, method, _RESULT.get(value.lower(), "unknown"))
    if res.spf == "unknown" and received_spf:
        first = received_spf[0].strip().split(None, 1)[0].lower() if received_spf[0].strip() else ""
        res.spf = _RESULT.get(first, "unknown")
    if res.dkim == "unknown" and authentication_results and not dkim_present:
        res.dkim = "none"
    return res


@dataclass
class SenderCheck:
    reply_to_mismatch: bool = False
    return_path_mismatch: bool = False
    display_name_impersonation: str | None = None
    lookalikes: list[Lookalike] = field(default_factory=list)
    homoglyphs: list[HiddenFinding] = field(default_factory=list)


def _reg(addr: str) -> str | None:
    return domains.registrable(domains.normalize_host(addr.rpartition("@")[2])) if "@" in addr else None


def check_sender(from_addr: str, from_display: str, reply_to: str, return_path: str) -> SenderCheck:
    """Reply-To / Return-Path consistency, display-name impersonation and sender-domain lookalikes."""
    out = SenderCheck()
    from_reg = _reg(from_addr)
    if reply_to and from_reg and _reg(reply_to) != from_reg:
        out.reply_to_mismatch = True
    if return_path and from_reg and _reg(return_path) != from_reg:
        out.return_path_mismatch = True
    from_host = domains.normalize_host(from_addr.rpartition("@")[2]) if "@" in from_addr else None
    display = strip_invisible(from_display or "")
    shown = _EMAIL_IN_TEXT.search(display)
    if shown and from_reg and domains.registrable(shown.group(1).lower()) != from_reg:
        out.display_name_impersonation = f"display name shows {shown.group(0)} but the mail is from {from_addr}"
    elif display and from_host and not domains.is_legit(from_host):
        for brand, _tok in domains.token_hits(display):
            out.display_name_impersonation = f"display name says '{display[:60]}' ({brand}) but the mail is from {from_addr}"
            break
    if from_host:
        out.lookalikes = domains.lookalikes(from_host)
    out.homoglyphs = homoglyph_findings(display, "sender display name", severity="high")
    return out


def _flags_for(url: str, host: str | None) -> tuple[list[str], list[Lookalike]]:
    cfg = settings.load("brands")
    flags: list[str] = []
    lower = url.lower()
    if lower.startswith(("javascript:", "data:", "vbscript:")):
        return ["script_or_data_uri"], []
    if not host:
        return ["unparseable"], []
    netloc = re.sub(r"^[a-z][a-z0-9+.-]*://", "", url, flags=re.IGNORECASE).split("/", 1)[0]
    if "@" in netloc:
        flags.append("at_sign_in_url")
    if domains.is_ip(host):
        flags.append("ip_address_host")
    port = re.search(r":(\d+)$", netloc)
    if port and port.group(1) not in ("80", "443"):
        flags.append("non_standard_port")
    if len(url) > LONG_URL:
        flags.append("very_long_url")
    if lower.count("%") >= 10 or re.search(r"[A-Za-z0-9+/]{60,}", url):
        flags.append("obfuscated")
    reg = domains.registrable(host) or host
    if host.count(".") - reg.count(".") >= MANY_SUBDOMAINS:
        flags.append("many_subdomains")
    if any(host == s or host.endswith("." + s) for s in cfg.get("shorteners", [])):
        flags.append("shortener_not_expanded")
    if "xn--" in host:
        flags.append("punycode")
    if lower.startswith("http://"):
        flags.append("no_https")
    lookalikes = domains.lookalikes(host)
    if lookalikes:
        flags.append("lookalike_domain")
    return flags, lookalikes


_FLAG_SEVERITY = {
    "script_or_data_uri": "high", "at_sign_in_url": "high", "ip_address_host": "high", "lookalike_domain": "high",
    "punycode": "medium", "non_standard_port": "medium", "obfuscated": "medium", "many_subdomains": "medium",
    "shortener_not_expanded": "medium", "very_long_url": "low", "no_https": "low", "unparseable": "low",
}


def analyze_links(html_links: list[LinkRef], text: str) -> tuple[list[LinkItem], list[Lookalike]]:
    """Flag every link (HTML hrefs and URLs written in the text). Nothing is fetched."""
    urls: list[str] = [l.href.strip() for l in html_links if not l.href.strip().lower().startswith(("mailto:", "#", "tel:"))]
    urls += [m.group(0).rstrip(".,;:!?") for m in _TEXT_URL.finditer(text or "")]
    items: list[LinkItem] = []
    all_lookalikes: list[Lookalike] = []
    for url in list(dict.fromkeys(urls))[:200]:
        host = domains.host_of(url)
        flags, lks = _flags_for(url, host)
        all_lookalikes.extend(lks)
        sev = max((_FLAG_SEVERITY[f] for f in flags), key=lambda s: SEVERITY_RANK[s], default=None)
        items.append(LinkItem(url=url[:2000], host=host, flags=flags, severity=sev))
    return items, all_lookalikes
