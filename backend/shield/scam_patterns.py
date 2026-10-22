"""India-specific scam detectors (master prompt section 4.5), rules only.

Detectors are defined in config/patterns.yml under `scam_detectors`. A detector fires on any
`strong` pattern, or when at least `min_weak` different `weak` patterns match, in which case its
severity drops to `weak_severity`. An LLM second opinion for low-confidence cases is added in
Phase 2.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from shield import settings
from shield.schemas import ScamHit
from shield.textnorm import normalize_for_match

GUARD_WINDOW = 30


@dataclass(frozen=True)
class Detector:
    id: str
    name: str
    severity: str
    weak_severity: str
    min_weak: int
    strong: tuple[re.Pattern[str], ...]
    weak: tuple[re.Pattern[str], ...]
    guard_before: re.Pattern[str] | None
    guard_after: re.Pattern[str] | None


@lru_cache
def detectors() -> tuple[Detector, ...]:
    out = []
    for d in settings.load("patterns")["scam_detectors"]:
        out.append(Detector(
            id=d["id"], name=d["name"], severity=d["severity"], weak_severity=d.get("weak_severity", d["severity"]),
            min_weak=int(d.get("min_weak", 2)),
            strong=tuple(settings.compiled(p) for p in d.get("strong") or []),
            weak=tuple(settings.compiled(p) for p in d.get("weak") or []),
            guard_before=settings.compiled(d["guard_before"]) if d.get("guard_before") else None,
            guard_after=settings.compiled(d["guard_after"]) if d.get("guard_after") else None,
        ))
    return tuple(out)


def _guarded(det: Detector, text: str, m: re.Match[str]) -> bool:
    """True when a negation/context guard near the match cancels it."""
    if det.guard_before and det.guard_before.search(text[max(0, m.start() - GUARD_WINDOW):m.start()]):
        return True
    if det.guard_after and det.guard_after.search(text[m.end():m.end() + GUARD_WINDOW]):
        return True
    return False


def _strong_matches(det: Detector, text: str) -> list[str]:
    found = []
    for p in det.strong:
        for m in p.finditer(text):
            if not _guarded(det, text, m):
                found.append(m.group(0).strip())
                break
    return found


def scan(text: str) -> list[ScamHit]:
    """Run every scam detector over `text` (subject + visible body + attachment text)."""
    if not text or not text.strip():
        return []
    # Line breaks flattened: hard-wrapped messages split sentences across lines.
    norm = normalize_for_match(text).replace("\n", " ")
    hits: list[ScamHit] = []
    for det in detectors():
        strong = _strong_matches(det, norm)
        if strong:
            hits.append(ScamHit(id=det.id, name=det.name, matched_evidence=strong, severity=det.severity))
            continue
        weak = []
        for p in det.weak:
            m = p.search(norm)
            if m and not _guarded(det, norm, m):
                weak.append(m.group(0).strip())
        if len(weak) >= det.min_weak:
            hits.append(ScamHit(id=det.id, name=det.name, matched_evidence=weak, severity=det.weak_severity))
    return hits
