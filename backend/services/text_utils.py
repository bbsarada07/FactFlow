"""Text normalisation, hashing and lightweight lexical similarity."""
import hashlib
import math
import re
from collections import Counter

_WS = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)


def normalize(text: str) -> str:
    return _WS.sub(" ", _NON_WORD.sub(" ", (text or "").lower())).strip()


def input_hash(text: str) -> str:
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
    norm = normalize(text)
    if not keywords:
        return 0.0
    hits = sum(1 for k in keywords if normalize(k) in norm)
    return min(1.0, hits / 3)


def truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
