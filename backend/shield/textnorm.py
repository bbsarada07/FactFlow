"""Unicode helpers shared by the Shield detectors: invisible characters, Unicode Tags decoding,
script detection and a small confusables (homoglyph) map.

Zero-width joiners are legitimate inside Indic scripts, Arabic-script Urdu and emoji sequences,
and tag characters are legitimate inside emoji flag sequences; `invisible_runs` reports only the
occurrences that are not explained by those uses.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

ZERO_WIDTH = {"​", "‌", "‍", "⁠", "﻿", "᠎", "‎", "‏"}
BIDI = {chr(c) for c in range(0x202A, 0x202F)} | {chr(c) for c in range(0x2066, 0x206A)}
TAG_START, TAG_END = 0xE0000, 0xE007F
JOINERS = {"‌", "‍"}

# Scripts where ZWJ/ZWNJ are part of normal spelling.
_JOINER_SCRIPT_RANGES = (
    (0x0600, 0x06FF),  # Arabic (Urdu, Persian)
    (0x0900, 0x0DFF),  # Devanagari .. Sinhala (all major Indic scripts)
)
_WS_KEEP_NL = re.compile(r"[ \t\r\f\v]+")
_MULTI_NL = re.compile(r"\n{3,}")


def is_tag(ch: str) -> bool:
    return TAG_START <= ord(ch) <= TAG_END


def is_invisible(ch: str) -> bool:
    """Zero-width, bidi control or Unicode Tags character."""
    return ch in ZERO_WIDTH or ch in BIDI or is_tag(ch)


def _in_joiner_script(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _JOINER_SCRIPT_RANGES)


def _is_emoji(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x1F000 <= cp <= 0x1FAFF
        or 0x2600 <= cp <= 0x27BF
        or 0x2300 <= cp <= 0x23FF
        or 0x2B00 <= cp <= 0x2BFF
        or cp in (0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139, 0x3030, 0x303D)
    )


def _neighbour(text: str, i: int, step: int) -> str:
    """Nearest neighbour of position i that is not a variation selector or skin-tone modifier."""
    j = i + step
    while 0 <= j < len(text):
        cp = ord(text[j])
        if not (0xFE00 <= cp <= 0xFE0F or 0x1F3FB <= cp <= 0x1F3FF):
            return text[j]
        j += step
    return ""


def joiner_is_legitimate(text: str, i: int) -> bool:
    """True when the ZWJ/ZWNJ at text[i] sits between Indic/Arabic letters or between emoji."""
    prev, nxt = _neighbour(text, i, -1), _neighbour(text, i, 1)
    if not prev or not nxt:
        return False
    if _in_joiner_script(prev) and _in_joiner_script(nxt):
        return True
    return text[i] == "‍" and _is_emoji(prev) and _is_emoji(nxt)


@dataclass(frozen=True)
class InvisibleRun:
    """A contiguous run of suspicious invisible characters."""

    start: int
    end: int
    kinds: frozenset[str]  # zero_width | bidi | tags
    decoded: str  # ASCII text hidden in Unicode Tags characters ("" if none)


def _flag_tag_span(text: str, i: int) -> int:
    """If text[i] starts the tag sequence of an emoji subdivision flag (after U+1F3F4 and ending
    in U+E007F), return the index after it; otherwise -1."""
    if i == 0 or text[i - 1] != "\U0001F3F4":
        return -1
    j = i
    while j < len(text) and is_tag(text[j]):
        if ord(text[j]) == 0xE007F:
            return j + 1
        j += 1
    return -1


def invisible_runs(text: str) -> list[InvisibleRun]:
    """Find runs of invisible characters that are not explained by legitimate use."""
    runs: list[InvisibleRun] = []
    i, n = 0, len(text or "")
    while i < n:
        ch = text[i]
        if not is_invisible(ch):
            i += 1
            continue
        if ch in JOINERS and joiner_is_legitimate(text, i):
            i += 1
            continue
        if ch == "﻿" and i == 0:  # byte-order mark at the very start
            i += 1
            continue
        if is_tag(ch):
            flag_end = _flag_tag_span(text, i)
            if flag_end > 0:
                i = flag_end
                continue
        start, kinds, decoded = i, set(), []
        while i < n and is_invisible(text[i]) and not (text[i] in JOINERS and joiner_is_legitimate(text, i)):
            c = text[i]
            if is_tag(c):
                kinds.add("tags")
                cp = ord(c) - TAG_START
                if 0x20 <= cp <= 0x7E:
                    decoded.append(chr(cp))
            elif c in BIDI:
                kinds.add("bidi")
            else:
                kinds.add("zero_width")
            i += 1
        runs.append(InvisibleRun(start, i, frozenset(kinds), "".join(decoded)))
    return runs


def decode_tags(text: str) -> str:
    """Replace each Unicode Tags character with the ASCII character it encodes."""
    out = []
    for ch in text or "":
        if is_tag(ch):
            cp = ord(ch) - TAG_START
            if 0x20 <= cp <= 0x7E:
                out.append(chr(cp))
        else:
            out.append(ch)
    return "".join(out)


def strip_invisible(text: str, keep_legit_joiners: bool = True) -> str:
    """Remove zero-width, bidi and tag characters (legitimate joiners kept by default)."""
    out = []
    for i, ch in enumerate(text or ""):
        if not is_invisible(ch):
            out.append(ch)
        elif keep_legit_joiners and ch in JOINERS and joiner_is_legitimate(text, i):
            out.append(ch)
    return "".join(out)


# Lookalike letters from Cyrillic and Greek mapped to the Latin letter they imitate.
CONFUSABLES: dict[str, str] = {
    # Cyrillic lowercase
    "а": "a", "в": "b", "е": "e", "ё": "e", "һ": "h", "і": "i", "ї": "i", "ј": "j", "к": "k", "ӏ": "l",
    "м": "m", "н": "h", "о": "o", "р": "p", "с": "c", "т": "t", "у": "y", "х": "x", "ѕ": "s", "ԁ": "d",
    "ԛ": "q", "ԝ": "w", "ɡ": "g", "ь": "b", "п": "n",
    # Cyrillic uppercase
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T",
    "Х": "X", "Ѕ": "S", "І": "I", "Ј": "J", "У": "Y", "Ԁ": "D", "Ԛ": "Q", "Ԝ": "W",
    # Greek lowercase
    "α": "a", "β": "b", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ο": "o", "ρ": "p", "τ": "t", "υ": "u",
    "χ": "x", "γ": "y",
    # Greek uppercase
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O",
    "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
}


def script_of(ch: str) -> str | None:
    """'latin', 'cyrillic', 'greek', 'other' for letters; None for non-letters."""
    if not ch.isalpha():
        return None
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return "other"
    for script in ("LATIN", "CYRILLIC", "GREEK"):
        if name.startswith(script):
            return script.lower()
    return "other"


def skeleton(text: str) -> str:
    """Latin 'skeleton' of a string: confusable letters mapped to Latin, NFKC, casefolded."""
    return "".join(CONFUSABLES.get(ch, ch) for ch in unicodedata.normalize("NFKC", text or "")).casefold()


def normalize_for_match(text: str) -> str:
    """Canonical text for rule matching: tags decoded, NFKC, invisible characters removed,
    confusables mapped to Latin, casefolded, spaces collapsed (newlines kept)."""
    text = decode_tags(text or "")
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if not is_invisible(ch))
    text = "".join(CONFUSABLES.get(ch, ch) for ch in text).casefold()
    text = _WS_KEEP_NL.sub(" ", text)
    return _MULTI_NL.sub("\n\n", text).strip()
