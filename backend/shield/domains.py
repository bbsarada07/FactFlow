"""Domain helpers: hosts from URLs, registrable domains, edit distance and brand lookalikes.

Registrable domains are approximated with the multi-part suffix list in config/brands.yml rather
than the full Public Suffix List; see docs/DECISIONS.md.
"""
from __future__ import annotations

import ipaddress
import re
from functools import lru_cache
from urllib.parse import urlsplit

from shield import settings
from shield.schemas import Lookalike
from shield.textnorm import CONFUSABLES, script_of

_DOMAIN_IN_TEXT = re.compile(r"(?<![\w@.-])((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24})(?![\w-])", re.IGNORECASE)


def host_of(url: str) -> str | None:
    """Lowercase host of an http(s)/mailto URL or bare domain; IDN hosts converted to punycode."""
    url = (url or "").strip()
    if not url:
        return None
    lower = url.lower()
    if lower.startswith("mailto:"):
        addr = url[7:].split("?", 1)[0]
        return normalize_host(addr.rpartition("@")[2]) if "@" in addr else None
    if lower.startswith(("javascript:", "data:", "vbscript:", "file:")):
        return None
    if lower.startswith("//"):
        url = "http:" + url
    elif "://" not in url:
        url = "http://" + url
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return None
    return normalize_host(host) if host else None


def normalize_host(host: str) -> str | None:
    """Lowercase, strip the trailing dot, and convert Unicode labels to punycode."""
    host = (host or "").strip().lower().rstrip(".")
    if not host:
        return None
    if not host.isascii():
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            return host
    return host


def unicode_host(host: str) -> str:
    """Punycode labels decoded back to Unicode (for homoglyph checks); undecodable labels kept."""
    labels = []
    for label in (host or "").split("."):
        if label.startswith("xn--"):
            try:
                label = label.encode("ascii").decode("idna")
            except UnicodeError:
                pass
        labels.append(label)
    return ".".join(labels)


def is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


@lru_cache
def _suffixes() -> frozenset[str]:
    return frozenset(settings.load("brands").get("multi_part_suffixes", []))


def registrable(host: str | None) -> str | None:
    """Approximate registrable domain: 'mail.sbi.co.in' -> 'sbi.co.in', 'a.b.example.com' -> 'example.com'."""
    if not host:
        return None
    host = host.lower().rstrip(".")
    if is_ip(host):
        return host
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    last_two = ".".join(labels[-2:])
    if last_two in _suffixes():
        return ".".join(labels[-3:])
    return last_two


def domains_in_text(text: str) -> list[str]:
    """Bare domain names that appear in visible text (e.g. a link that *shows* 'sbi.co.in')."""
    return [m.group(1).lower() for m in _DOMAIN_IN_TEXT.finditer(text or "")]


def levenshtein(a: str, b: str, limit: int = 3) -> int:
    """Edit distance, stopping early once it exceeds `limit`."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return limit + 1
        prev = cur
    return prev[-1]


@lru_cache
def brands() -> tuple[dict, ...]:
    return tuple(settings.load("brands")["brands"])


@lru_cache
def legit_domains() -> dict[str, str]:
    """Every legitimate registrable domain -> brand name."""
    return {d.lower(): b["name"] for b in brands() for d in b["legit_domains"]}


def is_legit(host: str | None) -> bool:
    """True when the host is, or is a subdomain of, a listed legitimate domain."""
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in legit_domains())


def _parts(name: str) -> list[str]:
    return [p for p in re.split(r"[.\-_0-9]+", name.lower()) if p]


def token_hits(text: str) -> list[tuple[str, str]]:
    """Brand tokens claimed by `text` (a domain or a display name) as (brand, token) pairs.

    Tokens of 3 letters or fewer must be a whole hyphen/dot/space-separated part; longer tokens
    may also appear at the start or end of a part ('sbionline', 'mysbi' does not match 'sbi').
    """
    parts = _parts(re.sub(r"\s+", "-", text or ""))
    hits = []
    for b in brands():
        for tok in b["tokens"]:
            tok = tok.lower()
            if len(tok) <= 3:
                matched = tok in parts
            else:
                matched = any(p == tok or p.startswith(tok) or p.endswith(tok) for p in parts)
            if matched:
                hits.append((b["name"], tok))
                break
    return hits


def _skeleton_host(host: str) -> str:
    return "".join(CONFUSABLES.get(ch, ch) for ch in unicode_host(host)).lower()


def lookalikes(host: str | None) -> list[Lookalike]:
    """Ways in which `host` imitates a known brand domain (empty if legitimate or unrelated)."""
    if not host or is_ip(host) or is_legit(host):
        return []
    cfg = settings.load("brands")
    reg = registrable(host) or host
    out: list[Lookalike] = []
    legit = legit_domains()

    uni = unicode_host(host)
    if "xn--" in host:
        skel = _skeleton_host(host)
        target = next((d for d in legit if skel == d or skel.endswith("." + d)), None)
        mixed = {script_of(c) for c in uni if c.isalpha()} - {None}
        if target:
            out.append(Lookalike(domain=host, brand=legit[target], legit_domain=target,
                                 reason=f"uses lookalike letters to imitate {target} ({uni})", severity="critical"))
        else:
            sev = "high" if len(mixed) > 1 else "medium"
            out.append(Lookalike(domain=host, brand="(unknown)", reason=f"internationalised domain shown as {uni}", severity=sev))

    for d, brand in legit.items():
        # subdomain trick: sbi.co.in.evil.com
        if host != d and (host.startswith(d + ".") or f".{d}." in f".{host}") and not host.endswith("." + d):
            out.append(Lookalike(domain=host, brand=brand, legit_domain=d,
                                 reason=f"starts with {d} but really belongs to {reg}", severity="critical"))
            continue
        d_label, r_label = d.split(".")[0], reg.split(".")[0]
        # TLD swap: sbi.com vs sbi.co.in
        if r_label == d_label and reg != registrable(d) and len(d_label) >= 3:
            out.append(Lookalike(domain=host, brand=brand, legit_domain=d,
                                 reason=f"same name as {d} under a different ending ({reg})", severity="high"))
            continue
        # close spelling: hdfcbenk.com vs hdfcbank.com
        dist_limit = 2 if len(r_label) >= 6 else 1 if len(r_label) >= 4 else 0
        if dist_limit and reg != d:
            dist = levenshtein(reg, d, dist_limit)
            if 0 < dist <= dist_limit:
                out.append(Lookalike(domain=host, brand=brand, legit_domain=d,
                                     reason=f"{reg} is {dist} character(s) away from {d}", severity="high"))

    if not any(lk.legit_domain for lk in out):
        trusted = tuple(cfg.get("trusted_bank_suffixes", []))
        if not any(reg == s or reg.endswith("." + s) for s in trusted):
            for brand, tok in token_hits(host):
                out.append(Lookalike(domain=host, brand=brand,
                                     reason=f"contains '{tok}' but is not a {brand} domain", severity="high"))

    gov = cfg.get("government", {})
    gov_suffixes = tuple(gov.get("suffixes", []))
    if not any(host.endswith("." + s) or host == s for s in gov_suffixes):
        parts = _parts(host)
        claimed = [t for t in gov.get("tokens", []) if (t in parts if len(t) <= 3 else any(t in p for p in parts))]
        if claimed and not any(lk.severity in ("high", "critical") for lk in out):
            out.append(Lookalike(domain=host, brand="Government of India",
                                 reason=f"uses '{claimed[0]}' but is not a .gov.in or .nic.in address", severity="medium"))
    return out
