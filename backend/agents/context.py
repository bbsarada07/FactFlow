"""Shared pipeline state and helpers for all agents."""
from dataclasses import dataclass, field
from datetime import date

VERDICTS = ("FALSE", "TRUE", "MISLEADING", "UNVERIFIED", "SATIRE")

# Appended to every prompt that judges a claim.
HONESTY_RULE = (
    "If the evidence is insufficient, say so. Do not guess. Return UNVERIFIED with a reason. "
    "Return ONLY valid JSON, no preamble, no markdown backticks."
)
URGENCY = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
HARM_TYPES = ("VIOLENCE", "HEALTH", "COMMUNAL", "ELECTORAL", "FINANCIAL", "REPUTATIONAL", "NONE")
CLAIM_TYPES = ("HEALTH", "COMMUNAL", "POLITICAL", "ELECTORAL", "VIOLENCE", "SCIENCE", "FINANCIAL", "DISASTER", "OTHER")

LANGUAGE_NAMES = {
    "en": "English", "hi": "Hindi", "mr": "Marathi", "ta": "Tamil", "te": "Telugu", "bn": "Bengali",
    "gu": "Gujarati", "kn": "Kannada", "ml": "Malayalam", "pa": "Punjabi", "ur": "Urdu", "or": "Odia",
    "as": "Assamese",
}

_VERDICT_ALIASES = {
    "FAKE": "FALSE", "MOSTLY FALSE": "FALSE", "INCORRECT": "FALSE", "PANTS ON FIRE": "FALSE",
    "PARTLY FALSE": "MISLEADING", "HALF TRUE": "MISLEADING", "MISSING CONTEXT": "MISLEADING",
    "OUT OF CONTEXT": "MISLEADING", "MIXED": "MISLEADING", "MOSTLY TRUE": "TRUE", "CORRECT": "TRUE",
    "UNPROVEN": "UNVERIFIED", "UNKNOWN": "UNVERIFIED", "INSUFFICIENT EVIDENCE": "UNVERIFIED",
    "SATIRICAL": "SATIRE", "PARODY": "SATIRE",
}


def pick(value, allowed: tuple[str, ...], default: str) -> str:
    v = str(value or "").strip().upper().replace("_", " ")
    if v in allowed:
        return v
    v = v.replace(" ", "_")
    return v if v in allowed else default


def norm_verdict(value) -> str:
    v = str(value or "").strip().upper().replace("_", " ")
    if v in VERDICTS:
        return v
    return _VERDICT_ALIASES.get(v, "UNVERIFIED")


def clamp(value, lo: float = 0.0, hi: float = 1.0, default: float = 0.5) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    if x > 1 and hi == 1.0:
        x = x / 100  # tolerate percentages
    return max(lo, min(hi, x))


def str_list(value, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        if isinstance(item, dict):
            item = item.get("text") or item.get("step") or " ".join(str(v) for v in item.values())
        s = str(item).strip()
        if s:
            out.append(s)
    return out[:limit]


@dataclass
class AgentOutput:
    preview: str
    model: str | None = None
    ms: int = 0


@dataclass
class PipelineContext:
    request_id: str
    raw_text: str
    input_type: str = "text"
    requested_language: str = "auto"
    platform: str = "web"
    today: str = field(default_factory=lambda: date.today().isoformat())

    # Orchestrator
    pattern_matches: list[dict] = field(default_factory=list)

    # Intake
    claim: str = ""
    language: str = "en"
    language_name: str = "English"
    claim_type: str = "OTHER"
    urgency: str = "MEDIUM"
    entities: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    fact_check_query: str = ""
    satire_signals: bool = False

    # Source tracer
    evidence: list[dict] = field(default_factory=list)
    scanned_count: int = 0
    provider_errors: list[str] = field(default_factory=list)
    search_log: list[dict] = field(default_factory=list)

    # Verdict (tracer preliminary, possibly replaced by deep reasoning)
    verdict: str = "UNVERIFIED"
    confidence: float = 0.0
    summary: str = ""
    reasoning_chain: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    fact: str = ""
    key_source: str = ""
    used_ultra: bool = False
    missing_context: list[str] = field(default_factory=list)
    model_gaps: list[str] = field(default_factory=list)
    manipulation_markers: list[str] = field(default_factory=list)

    # Honest-uncertainty gate (orchestrator)
    model_verdict: str | None = None
    model_confidence: float | None = None
    gate_reasons: list[str] = field(default_factory=list)
    evidence_gaps: list[str] = field(default_factory=list)
    checks_to_do: list[dict] = field(default_factory=list)
    slug: str | None = None
    correction: dict | None = None

    # Explainer
    summary_local: str = ""
    myth: str = ""
    fact_source: str = ""
    whatsapp_reply: str = ""

    # Harm
    harm_type: str = "NONE"
    harm_level: str = "LOW"
    harm_score: float = 0.0
    harm_rationale: str = ""

    @property
    def output_language(self) -> str:
        if self.requested_language and self.requested_language != "auto":
            return self.requested_language
        return self.language or "en"

    @property
    def output_language_name(self) -> str:
        code = self.output_language
        if code == self.language and self.language_name:
            return self.language_name
        return LANGUAGE_NAMES.get(code, code)

    def evidence_block(self, with_stance: bool = False) -> str:
        if not self.evidence:
            return "(no external evidence was found)"
        lines = []
        for i, e in enumerate(self.evidence, 1):
            rating = f" | fact-check rating: {e['rating']}" if e.get("rating") else ""
            stance = f" | stance: {e.get('stance', 'NEUTRAL')}" if with_stance else ""
            date_ = f" | date: {e['published_at'][:10]}" if e.get("published_at") else ""
            lines.append(
                f"[{e.get('ref') or i}] {e['name']} (tier {e['tier']}, {e['origin']}{date_}{rating}{stance})\n"
                f"    title: {e.get('title') or ''}\n    snippet: {(e.get('snippet') or '')[:240]}"
            )
        return "\n".join(lines)
