"""Text normalisation, PII redaction, hashing and lightweight lexical similarity."""
import hashlib
import math
import re
import unicodedata
from collections import Counter

_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)
_WS = re.compile(r"\s+")

# Indian mobile numbers (+91 / 0091 / 0 prefixes, optional 5-5 split) and any run of 10+ digits.
_PHONE_IN = re.compile(r"(?<![\w+])(?:(?:\+|00)\s?91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")
_LONG_DIGITS = re.compile(r"(?<!\d)\d{10,}(?!\d)")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_HANDLE = re.compile(r"(?<![\w@])@[A-Za-z0-9_.]{2,30}\b")


def normalize(text: str) -> str:
    """Canonical form for matching: lowercase, URLs stripped, punctuation/symbols/emoji removed,
    whitespace collapsed. Letters, combining marks (Indic vowel signs) and digits are kept."""
    text = _URL.sub(" ", (text or "").lower())
    kept = []
    for ch in unicodedata.normalize("NFC", text):
        cat = unicodedata.category(ch)
        if cat[0] in ("L", "M", "N"):
            kept.append(ch)
        else:
            kept.append(" ")
    return _WS.sub(" ", "".join(kept)).strip()


def redact_pii(text: str) -> str:
    """Remove phone numbers, e-mail addresses and @account handles before anything is stored."""
    text = _EMAIL.sub("[email]", text or "")
    text = _PHONE_IN.sub("[phone]", text)
    text = _LONG_DIGITS.sub("[phone]", text)
    return _HANDLE.sub("[handle]", text)


def input_hash(text: str) -> str:
    """SHA-256 of the normalised text; identical claims share a hash."""
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def _trigrams(text: str) -> Counter:
    t = f"  {normalize(text)}  "
    return Counter(t[i : i + 3] for i in range(len(t) - 2))


def similarity(a: str, b: str) -> float:
    """Cosine similarity of character-trigram profiles (0..1). Script-agnostic."""
    va, vb = _trigrams(a), _trigrams(b)
    if not va or not vb:
        return 0.0
    dot = sum(c * vb.get(g, 0) for g, c in va.items())
    na = math.sqrt(sum(c * c for c in va.values()))
    nb = math.sqrt(sum(c * c for c in vb.values()))
    return dot / (na * nb) if na and nb else 0.0


def keyword_score(text: str, keywords: list[str]) -> float:
    """Fraction (capped at 1) of up to three keyword hits in the normalised text."""
    norm = normalize(text)
    if not keywords:
        return 0.0
    hits = sum(1 for k in keywords if normalize(k) in norm)
    return min(1.0, hits / 3)


def truncate(text: str, limit: int) -> str:
    """Trim to `limit` characters, ending with an ellipsis when cut."""
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def fit_words(text: str, limit: int) -> str:
    """Trim to `limit` characters at a word boundary, ending with an ellipsis when cut."""
    text = _WS.sub(" ", (text or "").strip())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,;:-") + "…"
