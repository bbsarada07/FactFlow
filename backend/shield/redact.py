"""PII redaction to typed placeholders (master prompt section 4.7).

Runs before any text is sent to an external LLM and before edge-to-cloud escalation, and on every
audit-log payload. Checksums are used where they exist (Verhoeff for Aadhaar, Luhn for cards) so
that random digit runs are not mistaken for identifiers.

This is separate from services/text_utils.redact_pii, which the verdict registry depends on for
repeat matching and must not change.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 2, 3, 4, 0, 6, 7, 8, 9, 5), (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7), (4, 0, 1, 2, 3, 9, 5, 6, 7, 8), (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2), (7, 6, 5, 9, 8, 2, 1, 0, 4, 3), (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9), (1, 5, 7, 6, 2, 8, 3, 0, 9, 4), (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7), (9, 4, 5, 3, 1, 2, 6, 8, 7, 0), (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5), (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def verhoeff_valid(number: str) -> bool:
    """Verhoeff checksum, used by Aadhaar numbers."""
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
    return c == 0


def luhn_valid(number: str) -> bool:
    """Luhn checksum, used by payment cards."""
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


@dataclass(frozen=True)
class _Rule:
    kind: str
    pattern: re.Pattern[str]
    group: int = 0
    check: Callable[[str], bool] | None = None


_RULES: tuple[_Rule, ...] = (
    _Rule("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")),
    _Rule("UPI_ID", re.compile(r"(?<![\w.@-])[A-Za-z0-9._-]{2,256}@[A-Za-z][A-Za-z0-9]{1,63}(?![\w.@-])")),
    _Rule("AADHAAR", re.compile(r"(?<![\d\w])[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?![\d\w])"),
          check=lambda s: verhoeff_valid(_digits(s))),
    _Rule("CARD", re.compile(r"(?<![\d\w])[2-6](?:[ -]?\d){12,18}(?![\d\w])"),
          check=lambda s: 13 <= len(_digits(s)) <= 19 and luhn_valid(_digits(s))),
    _Rule("ACCOUNT_NO", re.compile(r"(?i)\b(?:a/c|acct|account)(?:\s*(?:no\.?|number|#))?\s*[:.\-]?\s*(\d{9,18})(?!\d)"),
          group=1),
    _Rule("OTP", re.compile(r"(?i)(?<![^\W\d_])(?:otp|one[- ]time password|verification code|security code|passcode|ओटीपी|ఓటీపీ)"
                            r"[^\d\n]{0,20}?(\d{4,8})(?!\d)"), group=1),
    _Rule("PHONE", re.compile(r"(?<![\w+])(?:(?:\+|00)\s?91[\s-]?|0)?[6-9]\d{4}[\s-]?\d{5}(?!\d)")),
    _Rule("PAN", re.compile(r"(?<![A-Za-z0-9])[A-Z]{3}[PCHABGJLFT][A-Z]\d{4}[A-Z](?![A-Za-z0-9])")),
    _Rule("IFSC", re.compile(r"(?<![A-Za-z0-9])[A-Z]{4}0[A-Z0-9]{6}(?![A-Za-z0-9])")),
)
KINDS = tuple(r.kind for r in _RULES)


@dataclass
class Redactor:
    """Redacts one request's text. With numbered=True placeholders are unique ([PHONE_1]) and
    `restore` can put the originals back; the map lives only in this object (never persisted)."""

    numbered: bool = False
    _map: dict[str, str] = field(default_factory=dict, repr=False)
    _counts: dict[str, int] = field(default_factory=dict, repr=False)

    def _placeholder(self, kind: str, original: str) -> str:
        if not self.numbered:
            return f"[{kind}]"
        for ph, orig in self._map.items():
            if orig == original and ph.startswith(f"[{kind}_"):
                return ph
        self._counts[kind] = self._counts.get(kind, 0) + 1
        ph = f"[{kind}_{self._counts[kind]}]"
        self._map[ph] = original
        return ph

    def redact(self, text: str) -> str:
        """Replace every recognised identifier in `text` with its typed placeholder."""
        if not text:
            return text or ""
        for rule in _RULES:
            def sub(m: re.Match[str], rule: _Rule = rule) -> str:
                value = m.group(rule.group)
                if rule.check and not rule.check(value):
                    return m.group(0)
                ph = self._placeholder(rule.kind, value)
                if rule.group == 0:
                    return ph
                start, end = m.start(rule.group) - m.start(), m.end(rule.group) - m.start()
                whole = m.group(0)
                return whole[:start] + ph + whole[end:]

            text = rule.pattern.sub(sub, text)
        return text

    def restore(self, text: str) -> str:
        """Put original values back for numbered placeholders created by this Redactor."""
        for ph, orig in self._map.items():
            text = text.replace(ph, orig)
        return text


def redact(text: str) -> str:
    """Redact `text` with plain typed placeholders such as [AADHAAR]."""
    return Redactor().redact(text)


def redact_obj(obj):
    """Redact every string inside a JSON-like structure (dict keys are left as they are)."""
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {k: redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact_obj(v) for v in obj]
    return obj


def find(text: str) -> list[str]:
    """Kinds of identifier present in `text` (used by policy checks; values are not returned)."""
    kinds = []
    for rule in _RULES:
        for m in rule.pattern.finditer(text or ""):
            if not rule.check or rule.check(m.group(rule.group)):
                kinds.append(rule.kind)
                break
    return kinds
