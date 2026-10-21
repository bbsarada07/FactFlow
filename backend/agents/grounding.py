"""Grounding rule: every factual sentence shown to users must cite a retrieved source.

Sources kept by the Source Tracer get IDs S1..Sn. Model output cites them as [S1]. The
post-checks here run in code after the models, so the rule holds even when a model ignores
its prompt:
  * citations to IDs that were not retrieved are removed;
  * a sentence asserting absence ("no official ...", "no announcement", "no evidence")
    is dropped unless it carries a valid citation;
  * in strict mode, any sentence without a valid citation is dropped.
With zero relevant sources the pipeline uses NO_SOURCES_SUMMARY instead of model text.
"""
import re

NO_SOURCES = "No sources found yet."
NO_SOURCES_SUMMARY = (
    "No sources found yet. Our searches returned no relevant reports about this claim, "
    "so it cannot be confirmed or refuted at this time."
)

_CITE = re.compile(r"\[S(\d+)\]")
_CANDIDATE_CITE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
ABSENCE_PATTERN = re.compile(r"\bno\s+(?:official|announcements?|evidence)\b", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")
_SPACES = re.compile(r"[ \t]{2,}")


_LEADING_CITES = re.compile(r"^((?:\[S\d+\]\s*)+)(.*)$", re.DOTALL)


def split_sentences(text: str) -> list[str]:
    """Split text into sentences (English and Devanagari full stops).

    Models often place citations after the full stop ("...on 25 September. [S1][S2] Next...");
    citations at the start of a fragment belong to the sentence before it.
    """
    out: list[str] = []
    for part in (s.strip() for s in _SENTENCE_END.split((text or "").strip())):
        if not part:
            continue
        m = _LEADING_CITES.match(part)
        if out and m:
            out[-1] = f"{out[-1]} {m.group(1).strip()}"
            part = m.group(2).strip()
            if not part:
                continue
        out.append(part)
    return out


def assign_refs(evidence: list[dict]) -> dict[int, str]:
    """Give kept evidence IDs S1..Sn in order; returns {candidate_number: 'S#'} for remapping."""
    mapping = {}
    for i, e in enumerate(evidence, 1):
        e["ref"] = f"S{i}"
        if e.get("candidate") is not None:
            mapping[e["candidate"]] = e["ref"]
    return mapping


def remap_candidate_citations(text: str, mapping: dict[int, str]) -> str:
    """Rewrite [3] / [3, 5] candidate citations as [S#]; citations to dropped items are removed."""

    def repl(m: re.Match) -> str:
        refs = [mapping.get(int(n)) for n in m.group(1).split(",")]
        refs = [r for r in refs if r]
        return "".join(f"[{r}]" for r in refs)

    return _SPACES.sub(" ", _CANDIDATE_CITE.sub(repl, text or "")).strip()


def valid_refs(sentence: str, n_sources: int) -> list[str]:
    """Citation IDs in a sentence that point at a retrieved source."""
    return [f"S{n}" for n in (int(x) for x in _CITE.findall(sentence)) if 1 <= n <= n_sources]


def ground_text(text: str, n_sources: int, strict: bool = True) -> str:
    """Apply the grounding rule to a block of text. Returns only sentences that pass."""
    kept = []
    for sentence in split_sentences(text):
        cleaned = _CITE.sub(lambda m: m.group(0) if 1 <= int(m.group(1)) <= n_sources else "", sentence)
        cleaned = _SPACES.sub(" ", cleaned).strip()
        cited = bool(valid_refs(cleaned, n_sources))
        if not _CITE.sub("", cleaned).strip(" .!?।"):
            continue  # citations with no sentence text carry no information
        if ABSENCE_PATTERN.search(cleaned) and not cited:
            continue
        if strict and not cited:
            continue
        kept.append(cleaned)
    return " ".join(kept)


_REPORTING = re.compile(
    r"\b(?:report(?:ed|s|ing)?|according to|confirmed by|cited by|outlets?|media|publications?"
    r"|news (?:sites?|reports?|organi[sz]ations?))\b",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^a-z0-9]")


def source_aliases(evidence: list[dict]) -> set[str]:
    """Lower-case, space-free names a sentence may use for a retrieved source:
    its listed name (without a leading 'The'), its domain and the domain's first label
    (e.g. 'telanganatoday' matches 'Telangana Today')."""
    from urllib.parse import urlparse

    aliases: set[str] = set()
    for e in evidence:
        name = re.sub(r"^the\s+", "", (e.get("name") or "").lower())
        host = urlparse(e.get("url") or "").netloc.lower().removeprefix("www.")
        for alias in (name, host, host.split(".")[0] if host else ""):
            compact = _NON_ALNUM.sub("", alias)
            if len(compact) >= 4:
                aliases.add(compact)
    return aliases


def names_a_source(sentence: str, evidence: list[dict]) -> bool:
    """True if the sentence names at least one retrieved source."""
    compact = _NON_ALNUM.sub("", sentence.lower())
    return any(alias in compact for alias in source_aliases(evidence))


def require_named_sources(text: str, evidence: list[dict]) -> str:
    """Drop sentences that claim reporting ("reported", "according to", "outlets", ...) unless they
    name a retrieved source AND cite a valid source ID. Other sentences are left unchanged."""
    kept = []
    for sentence in split_sentences(text):
        if _REPORTING.search(sentence) and not (
            names_a_source(sentence, evidence) and valid_refs(sentence, len(evidence))
        ):
            continue
        kept.append(sentence)
    return " ".join(kept)


def ground_list(items: list[str], n_sources: int, strict: bool = True) -> list[str]:
    """Ground each item of a list (reasoning steps, contradictions); drop items left empty."""
    return [g for g in (ground_text(i, n_sources, strict) for i in items) if g]


def uncited_sentences(text: str, n_sources: int) -> list[str]:
    """Sentences lacking a valid citation (used by tests and the verification report)."""
    return [s for s in split_sentences(text) if not valid_refs(s, n_sources)]
