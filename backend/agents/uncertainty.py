"""Deterministic honest-uncertainty helpers: evidence gaps and next-step checks.

Nothing here is model-generated. Every URL comes from the allow-list in config.py
(Google search built from the claim text, Google Lens, PIB Fact Check).
"""
import re
from urllib.parse import quote_plus, urlparse

from config import settings

STRONG_TIERS = (1, 2)
FACT_CHECKERS = {
    "altnews.in", "boomlive.in", "factly.in", "newschecker.in", "vishvasnews.com", "newsmobile.in",
    "factcrescendo.com", "thequint.com", "factcheck.afp.com", "snopes.com", "politifact.com", "fullfact.org",
    "factcheck.org", "leadstories.com", "logicallyfacts.com", "africacheck.org", "misbar.com", "pib.gov.in",
}

_MEDIA = re.compile(
    r"\b(photo|photos|image|images|picture|pic|pics|video|videos|clip|footage|reel|screenshot|viral video)\b"
    r"|फोटो|तस्वीर|वीडियो|చిత్రం|వీడియో",
    re.IGNORECASE,
)
_GOVERNMENT = re.compile(
    r"\b(government|govt|ministry|minister|scheme|yojana|prime minister|chief minister|pm modi|rbi|reserve bank"
    r"|election commission|parliament|cabinet|police advisory|circular|notification|aadhaar|ration card|tax)\b"
    r"|सरकार|योजना|मंत्री|ప్రభుత్వ|పథకం",
    re.IGNORECASE,
)
_DATE = re.compile(
    r"\b(19|20)\d{2}\b|\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b"
    r"|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b"
    r"|\b\d{1,2}\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b"
    r"|\b(today|tomorrow|yesterday|tonight|last night|this morning|next week|this week|next month"
    r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b"
    r"|आज|कल",
    re.IGNORECASE,
)


def is_fact_check(item: dict) -> bool:
    """True for Fact Check API hits and for pages on known fact-checking sites."""
    if item.get("origin") == "factcheck" or item.get("rating"):
        return True
    host = urlparse(item.get("url", "")).netloc.lower().removeprefix("www.")
    return any(host == d or host.endswith("." + d) for d in FACT_CHECKERS)


def strong_source_count(evidence: list[dict]) -> int:
    """Number of evidence items from credibility tier 1 or 2."""
    return sum(1 for e in evidence if e.get("tier") in STRONG_TIERS)


def build_checks(claim: str, raw_text: str, input_type: str, claim_type: str) -> list[dict]:
    """Next steps a reader can take themselves, as {label, url, why}. url is None for manual checks."""
    text = f"{claim}\n{raw_text}"
    query = (claim or raw_text).strip()[:200]
    checks = [
        {
            "label": "Search the claim on Google",
            "url": settings.GOOGLE_SEARCH_URL + quote_plus(query),
            "why": "See who else is reporting it and whether a fact-checker has already covered it.",
        }
    ]
    if input_type == "image" or _MEDIA.search(text):
        checks.append(
            {
                "label": "Reverse image search",
                "url": settings.REVERSE_IMAGE_SEARCH_URL,
                "why": "Find where the photo or video first appeared; old or foreign media is often re-shared as new.",
            }
        )
    if claim_type in ("POLITICAL", "ELECTORAL", "FINANCIAL") or _GOVERNMENT.search(text):
        checks.append(
            {
                "label": "Check PIB Fact Check",
                "url": settings.PIB_FACTCHECK_URL,
                "why": "The Government of India's fact-check unit reviews claims about schemes, notices and policies.",
            }
        )
    if _DATE.search(text):
        checks.append(
            {
                "label": "Check the original post date",
                "url": None,
                "why": "Open the original post and compare its date with the events it describes.",
            }
        )
    return checks


def evidence_gaps(evidence: list[dict], model_gaps: list[str], input_type: str,
                  provider_errors: list[str] | None = None) -> list[str]:
    """Combine detected gaps, search-provider failures and the model's stated gaps.

    Provider failures come first and are never truncated away: a search that could not run
    is the most important thing a reader needs to know about missing evidence.
    """
    failures = list(dict.fromkeys(provider_errors or []))
    gaps: list[str] = []
    if not evidence:
        gaps.append("No relevant source found")
    elif strong_source_count(evidence) == 0:
        gaps.append("No high-credibility (tier 1–2) source found")
    if not any(is_fact_check(e) for e in evidence):
        gaps.append("No published fact-check found")
    if input_type == "image":
        gaps.append("Image origin unknown")
    gaps.extend(g.strip() for g in model_gaps if g and g.strip())

    seen: set[str] = set()
    unique = []
    for g in gaps:
        key = g.lower().rstrip(".")
        if key not in seen:
            seen.add(key)
            text = g.rstrip(".")
            unique.append(text[:1].upper() + text[1:])
    return failures + unique[: max(0, 6 - len(failures))]
