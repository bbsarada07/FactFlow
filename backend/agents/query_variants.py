"""Deterministic search-query variants: spelling, transliteration and synonym alternatives.

News outlets spell Indian terms inconsistently ("Nimarjan", "Nimajjanam", "immersion"), so
a single literal query often misses the reports that exist. Each group below lists terms
that a search engine should treat as equivalent.
"""
import re

# Different spellings / transliterations of the SAME thing. For search, every member is first
# rewritten to the group's first (canonical) term, so "Ganesh Nimarjan" and "Ganesh Nimajjanam"
# generate identical queries. The claim text the user typed is never changed.
SPELLING_GROUPS: list[tuple[str, ...]] = [
    ("immersion", "nimajjanam", "nimarjan", "visarjan", "nimajjan"),
    ("chaturthi", "chavithi", "chathurthi"),
    ("cow urine", "gaumutra", "gomutra"),
]
# Rarer spellings that are only rewritten to the canonical term (not searched separately).
SPELLING_ALIASES: dict[str, str] = {"nimajanam": "immersion", "nimarjanam": "immersion"}
# Related but distinct words: used to widen searches, never merged into one spelling.
SYNONYM_GROUPS: list[tuple[str, ...]] = [
    ("holiday", "closed", "closure", "shut"),
    ("coronavirus", "covid", "corona"),
    ("kidnappers", "child lifters", "bachcha chor"),
    ("rbi", "reserve bank"),
    ("lynching", "mob attack"),
    ("vaccine", "vaccination", "jab"),
    ("evm", "voting machine"),
]
VARIANT_GROUPS: list[tuple[str, ...]] = SPELLING_GROUPS + SYNONYM_GROUPS
_SPELLING_RE = [
    (re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE), group[0])
    for group in SPELLING_GROUPS
    for term in group[1:]
] + [(re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE), canonical) for alias, canonical in SPELLING_ALIASES.items()]


def canonical_spelling(text: str) -> str:
    """Rewrite spelling/transliteration variants to one canonical term, for search only."""
    for pattern, canonical in _SPELLING_RE:
        text = pattern.sub(canonical, text)
    return text


_STOPWORDS = {
    "the", "and", "for", "are", "was", "were", "with", "that", "this", "from", "has", "have", "been", "will",
    "on", "of", "in", "to", "a", "an", "is", "by", "at", "as", "or", "be", "it", "its", "their", "they",
    "fact", "check", "news", "official", "authority", "statement", "because", "single", "day", "one",
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
    "november", "december", "two", "three", "who", "what", "said", "says", "video", "shows",
}
_YEARLIKE = re.compile(r"^(19|20)\d{2}$")
_WORD = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")


def _group_for(term: str) -> tuple[str, ...] | None:
    for group in VARIANT_GROUPS:
        if term in group:
            return group
    return None


def _find_terms(text: str) -> list[tuple[str, tuple[str, ...]]]:
    """Variant-group terms present in text (multi-word terms included), in group order."""
    low = f" {text.lower()} "
    found = []
    for group in VARIANT_GROUPS:
        for term in group:
            if f" {term} " in low:
                found.append((term, group))
                break
    return found


def variant_queries(query: str, limit: int = 2) -> list[str]:
    """Alternative spellings of `query`: each matched term swapped for its group alternatives.

    The query is first put in canonical spelling, so any two spellings of the same term yield
    the same variants.
    """
    canonical = canonical_spelling(query)
    out: list[str] = [canonical] if canonical.lower() != query.lower() else []
    if len(out) >= limit:
        return out
    query = canonical
    words = set(query.lower().split())
    for term, group in _find_terms(query):
        for alt in group:
            # Skip alternatives that would repeat a word already in the query ("mob mob attack").
            if alt == term or set(alt.split()) & (words - set(term.split())):
                continue
            candidate = re.sub(rf"\b{re.escape(term)}\b", alt, query, flags=re.IGNORECASE)
            if candidate.lower() != query.lower() and candidate.lower() not in (q.lower() for q in out):
                out.append(candidate)
            if len(out) >= limit:
                return out
    return out


def expand_queries(queries: list[str], claim: str, minimum: int = 3) -> list[str]:
    """Deduplicated queries, padded with variants (and the claim itself) to at least `minimum`."""
    seen: set[str] = set()
    out: list[str] = []

    def add(q: str) -> None:
        key = " ".join(q.lower().split())
        if key and key not in seen:
            seen.add(key)
            out.append(q.strip())

    for q in queries:
        add(canonical_spelling(q))
    for q in list(out):
        for v in variant_queries(q, limit=1):
            add(v)
    if len(out) < minimum and claim:
        add(canonical_spelling(claim[:120]))
        for v in variant_queries(claim[:120], limit=minimum):
            add(v)
    return out


def keyword_query(text: str, max_terms: int = 4) -> str:
    """Bare content keywords (no stopwords, months, years or short words), for databases such as
    Google Fact Check that match best on a few distinctive terms."""
    picked: list[str] = []
    for word in _WORD.findall((text or "").lower()):
        if len(word) >= 4 and word not in _STOPWORDS and not _YEARLIKE.match(word) and word not in picked:
            picked.append(word)
        if len(picked) >= max_terms:
            break
    return " ".join(picked)


def gdelt_query(query: str, max_terms: int = 4) -> str:
    """GDELT DOC syntax: keywords ANDed, variant groups as quoted OR-groups in parentheses."""
    low = query.lower().replace("fact check", " ")
    terms: list[str] = []
    used_groups: set[tuple[str, ...]] = set()
    for term, group in _find_terms(low):
        if group not in used_groups:
            used_groups.add(group)
            alts = " OR ".join(f'"{t}"' if " " in t else t for t in group)
            terms.append(f"({alts})")
            low = low.replace(term, " ")
    for word in _WORD.findall(low):
        if len(terms) >= max_terms:
            break
        if len(word) >= 3 and word not in _STOPWORDS and not _group_for(word) and not _YEARLIKE.match(word):
            terms.append(word)
    return " ".join(terms[:max_terms])
