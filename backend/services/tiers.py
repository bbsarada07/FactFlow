"""Source credibility tiers from the fixed allow-lists in config.py (never from the model).

Tier 1: wire services, official bodies and government domains.
Tier 2: established newsrooms and fact-checkers.
Tier 4: social platforms, blogs and user-generated content.
Tier 3: everything else.
"""
from urllib.parse import urlparse

from config import settings

TIER_SCORE = {1: 0.95, 2: 0.8, 3: 0.55, 4: 0.3}


def _parse(csv: str) -> tuple[set[str], tuple[str, ...]]:
    """Split a comma-separated allow-list into exact domains and '.suffix' entries."""
    items = [d.strip().lower() for d in csv.split(",") if d.strip()]
    return {d for d in items if not d.startswith(".")}, tuple(d for d in items if d.startswith("."))


_LISTS = {tier: _parse(csv) for tier, csv in (
    (1, settings.TIER_1_DOMAINS),
    (2, settings.TIER_2_DOMAINS),
    (4, settings.TIER_4_DOMAINS),
)}


def domain_of(url: str) -> str:
    """Host without a leading 'www.'."""
    host = urlparse(url or "").netloc.lower().split(":")[0]
    return host[4:] if host.startswith("www.") else host


def _matches(host: str, exact: set[str], suffixes: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in exact) or host.endswith(suffixes)


def tier_for(url: str) -> int:
    """Credibility tier (1-4) for a URL, decided only by the configured domain lists."""
    host = domain_of(url)
    for tier in (1, 2, 4):
        exact, suffixes = _LISTS[tier]
        if _matches(host, exact, suffixes):
            return tier
    return 3
