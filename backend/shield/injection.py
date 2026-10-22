"""Prompt-injection detection, rule layer (master prompt section 4.4, layer 1).

Rules live in config/patterns.yml and are matched against normalised text (see
textnorm.normalize_for_match), so lookalike letters, invisible characters and Unicode Tags do
not hide a phrase from them. The LLM classifier (layer 2) is added in Phase 2 through
quarantine.py; results are merged with max severity winning.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from shield import settings
from shield.schemas import SEVERITY_RANK, AttemptedAction, RuleHit
from shield.textnorm import normalize_for_match

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"https?://[^\s\"'<>)]+", re.IGNORECASE)
# Tool names that injected text commonly asks for, mapped to the policy action they amount to.
_TOOL_NAMES = {
    "delete_email": "delete_email",
    "open_link": "open_link",
    "download_attachment": "download_attachment",
    "send_reply": "send_reply",
    "send_email": "send_reply",
    "forward_email": "forward_email",
    "share_data": "share_data",
}


@dataclass(frozen=True)
class Rule:
    id: str
    category: str
    severity: str
    patterns: tuple[re.Pattern[str], ...]


@lru_cache
def rules() -> tuple[Rule, ...]:
    """Injection rules from config/patterns.yml, compiled once."""
    out = []
    for r in settings.load("patterns")["injection_rules"]:
        if r["severity"] not in SEVERITY_RANK:
            raise ValueError(f"{r['id']}: unknown severity {r['severity']!r}")
        out.append(Rule(r["id"], r["category"], r["severity"], tuple(settings.compiled(p) for p in r["patterns"])))
    return tuple(out)


def _snippet(text: str, m: re.Match[str], pad: int = 30) -> str:
    start, end = max(0, m.start() - pad), min(len(text), m.end() + pad)
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def scan_text(text: str, location: str = "body") -> list[RuleHit]:
    """Return one RuleHit per injection rule that matches `text` (first matching pattern only)."""
    if not text or not text.strip():
        return []
    norm = normalize_for_match(text)
    # Hard-wrapped email breaks sentences across lines, and a line break would otherwise end every
    # "same sentence" span; so each rule is tried with line breaks kept (for line-start rules such
    # as '### System') and with them flattened to spaces.
    variants = (norm, norm.replace("\n", " "))
    hits: list[RuleHit] = []
    for rule in rules():
        m, matched_in = None, norm
        for pattern in rule.patterns:
            for variant in variants:
                m = pattern.search(variant)
                if m:
                    matched_in = variant
                    break
            if m:
                break
        if m:
            hits.append(RuleHit(id=rule.id, category=rule.category, severity=rule.severity,
                                evidence=_snippet(matched_in, m), location=location))
    return hits


def is_instruction_like(text: str) -> bool:
    """True when the text matches an injection rule of medium severity or above."""
    return any(SEVERITY_RANK[h.severity] >= SEVERITY_RANK["medium"] for h in scan_text(text))


def attempted_actions(text: str, hits: list[RuleHit] | None = None) -> list[AttemptedAction]:
    """Best-effort, deterministic reading of what injected text asked an AI to do.

    Used only to warn the user and pre-fill approval screens. Never executed.
    """
    hits = scan_text(text) if hits is None else hits
    categories = {h.category for h in hits}
    if not categories & {"exfiltration", "tool_invocation", "instruction_override", "role_hijack"}:
        return []
    norm = normalize_for_match(text)
    targets = list(dict.fromkeys(_EMAIL.findall(norm) + _URL.findall(norm)))[:3]
    out: list[AttemptedAction] = []
    if "exfiltration" in categories:
        verb_forward = re.search(r"\b(forward|bcc|e-?mail|send)\b", norm)
        action = "forward_email" if verb_forward else "share_data"
        out += [AttemptedAction(action=action, target=t) for t in targets] or [AttemptedAction(action=action)]
    if "tool_invocation" in categories:
        for name, action in _TOOL_NAMES.items():
            if name in norm:
                out.append(AttemptedAction(action=action, target=targets[0] if targets else None))
    if not out:
        out.append(AttemptedAction(action="execute_instruction_from_content"))
    seen, unique = set(), []
    for a in out:
        key = (a.action, a.target)
        if key not in seen:
            seen.add(key)
            unique.append(a)
    return unique
