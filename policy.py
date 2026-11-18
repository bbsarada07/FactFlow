"""Deterministic policy engine: the final gate before any action. NO LLM, by design.

Provenance is recomputed here from registries, never taken on trust from the
planner. For each argument value:
    exact match with a value the user typed           -> USER
    exact match with a directory / tool registry value -> SYSTEM_TOOL
    found in, or containing, text from the email       -> UNTRUSTED_EMAIL
                                                          (TRUSTED_CONTACT if the sender is promoted)
    none of the above (LLM-invented)                   -> UNTRUSTED_EMAIL
then lowered further to whatever the planner claimed. LLM-written draft_body is
always UNTRUSTED_EMAIL. Any exception -> BLOCK (P-00).
"""

from __future__ import annotations

import html
import re
import threading
import unicodedata
from typing import Iterable, NamedTuple, Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, field_validator
from pydantic import Field as PField

from schemas import (
    Field,
    IdentityStatus,
    InjectionFinding,
    ParsedEmail,
    PolicyContext,
    PolicyDecision,
    Source,
    Tier,
    least_trusted,
)

DEFAULT_TIERS: dict[str, Tier] = {
    "summarize": Tier.READ_ONLY,
    "label": Tier.READ_ONLY,
    "flag": Tier.READ_ONLY,
    "draft_reply": Tier.REVERSIBLE,
    "schedule_meeting": Tier.REVERSIBLE,
    "add_note": Tier.REVERSIBLE,
    "send_reply": Tier.CONSEQUENTIAL,
    "forward_external": Tier.CONSEQUENTIAL,
    "update_payment_details": Tier.CONSEQUENTIAL,
    "share_document": Tier.CONSEQUENTIAL,
    "reset_credential": Tier.CONSEQUENTIAL,
}
# REVERSIBLE tools: args whose untrusted provenance forces CONFIRM. A tool missing
# from this map treats every arg as critical.
DEFAULT_CRITICAL_ARGS: dict[str, list[str]] = {
    "draft_reply": ["to", "cc", "bcc"],
    "schedule_meeting": ["attendees", "meeting_link", "location"],
    "add_note": [],
}
DEFAULT_ALLOWED_DOMAINS = ["northwindtraders.com"]

BLOCK_PRECEDENCE = ["P-08", "P-02", "P-04", "P-03", "P-05", "P-01"]
INJECTION_BLOCK_SEVERITY = 4
PROMOTION_MAX_INJECTION_SEVERITY = 2
MIN_TAINT_LEN = 6
RECIPIENT_KEYS = {"to", "recipient", "recipients", "cc", "bcc"}
FINANCIAL_KEY_TOKENS = {
    "iban", "bank", "account", "routing", "swift", "bic", "sort", "beneficiary", "payment", "wire",
}

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u200e\u200f\u2060\u2061\u2062\u2063\u2064\ufeff\u00ad"))
_WS_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]*>")
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$")
_TOOL_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_URL_RE = re.compile(
    r"""(?ix)
    \b(?:https?|ftp|wss?|file|javascript|data|vbscript|mailto):[^\s"'<>`]+
    | (?<![\w@.:/])//[^\s"'<>`/]+[^\s"'<>`]*
    | \bwww\.[^\s"'<>`]+
    """
)
_ADDR_RE = re.compile(r"[^\s<>,;\"']+@[^\s<>,;\"']+")
_IBAN_RE = re.compile(r"(?<![A-Z0-9])[A-Z]{2}\d{2}(?:[ -]?[A-Z0-9]){11,30}(?![A-Z0-9])")
_ACCOUNT_RE = re.compile(r"(?i)\b(?:acct|account|a/c|routing|aba|sort\s*code)\b\D{0,20}\d{6,}")
_BIC_RE = re.compile(r"(?i:\b(?:swift|bic)\b)[^A-Za-z0-9]{0,10}[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b")


class PolicyConfig(BaseModel):
    allowed_domains: list[str] = PField(default_factory=lambda: list(DEFAULT_ALLOWED_DOMAINS))
    tiers: dict[str, Tier] = PField(default_factory=lambda: dict(DEFAULT_TIERS))
    critical_args: dict[str, list[str]] = PField(default_factory=lambda: {k: list(v) for k, v in DEFAULT_CRITICAL_ARGS.items()})

    @field_validator("allowed_domains")
    @classmethod
    def _domains(cls, v: list[str]) -> list[str]:
        out = []
        for d in v:
            d = d.strip().lower().rstrip(".")
            if not _DOMAIN_RE.match(d):
                raise ValueError(f"not a valid domain: {d!r}")
            out.append(d)
        return sorted(set(out))

    @field_validator("tiers")
    @classmethod
    def _tools(cls, v: dict[str, Tier]) -> dict[str, Tier]:
        for name in v:
            if not _TOOL_RE.match(name):
                raise ValueError(f"not a valid tool name: {name!r}")
        return v


class PolicyStore:
    """Thread-safe holder for the runtime-editable config. Readers get a snapshot."""

    def __init__(self, config: Optional[PolicyConfig] = None):
        self._lock = threading.Lock()
        self._config = config or PolicyConfig()

    def get(self) -> PolicyConfig:
        with self._lock:
            return self._config.model_copy(deep=True)

    def update(
        self,
        allowed_domains: Optional[list[str]] = None,
        tiers: Optional[dict[str, str]] = None,
    ) -> PolicyConfig:
        with self._lock:
            data = self._config.model_dump()
            if allowed_domains is not None:
                data["allowed_domains"] = allowed_domains
            if tiers is not None:
                data["tiers"] = tiers
            self._config = PolicyConfig.model_validate(data)  # raises on bad input; old config kept
            return self._config.model_copy(deep=True)


# ------------------------------------------------------------- provenance

def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", html.unescape(text)).translate(_ZERO_WIDTH)
    return _WS_RE.sub("", text).casefold()


def promotion_allowed(identity: IdentityStatus, findings: list[InjectionFinding]) -> tuple[bool, str]:
    if not identity.verified:
        return False, "sender identity not verified (" + "; ".join(identity.failures or ["unverified"]) + ")"
    worst = max((f.severity for f in findings), default=0)
    if worst > PROMOTION_MAX_INJECTION_SEVERITY:
        return False, f"injection finding of severity {worst} present; a verified account may be compromised"
    return True, "sender verified and no significant injection findings"


class Promotion(NamedTuple):
    parsed: ParsedEmail
    promoted: bool
    reason: str


def promote_provenance(parsed: ParsedEmail, identity: IdentityStatus, findings: list[InjectionFinding]) -> Promotion:
    """Return a copy with UNTRUSTED_EMAIL fields raised to TRUSTED_CONTACT, if allowed."""
    ok, reason = promotion_allowed(identity, findings)
    if not ok:
        return Promotion(parsed, False, reason)

    def up(f: Field) -> Field:
        return f.model_copy(update={"source": Source.TRUSTED_CONTACT}) if f.source == Source.UNTRUSTED_EMAIL else f

    promoted = ParsedEmail(
        sender=up(parsed.sender),
        subject=up(parsed.subject),
        intent=up(parsed.intent),
        entities={k: up(v) for k, v in parsed.entities.items()},
        requested_action=up(parsed.requested_action) if parsed.requested_action else None,
        links=[up(f) for f in parsed.links],
        attachments=[up(f) for f in parsed.attachments],
    )
    return Promotion(promoted, True, reason)


class _Provenance:
    def __init__(self, ctx: PolicyContext):
        self.content_source = (
            Source.TRUSTED_CONTACT
            if promotion_allowed(ctx.identity, ctx.injection_findings)[0]
            else Source.UNTRUSTED_EMAIL
        )
        self.user = {normalize(v) for v in ctx.user_values if v.strip()}
        self.system = {normalize(v) for v in ctx.system_values if v.strip()}
        corpus: list[str] = []
        for text in ctx.untrusted_corpus:
            corpus.append(normalize(text))
            corpus.append(normalize(_TAG_RE.sub(" ", text)))
        self.corpus = corpus
        self.pieces = [normalize(f.value) for _, f in ctx.parsed.iter_fields()] if ctx.parsed else []
        self.pieces = [p for p in self.pieces if len(p) >= MIN_TAINT_LEN]

    def _in_registry(self, value: str, registry: set[str]) -> bool:
        if not registry:
            return False
        norm = normalize(value)
        if norm in registry:
            return True
        parts = [normalize(p) for p in re.split(r"[,;]", value) if p.strip()]
        return len(parts) > 1 and all(p in registry for p in parts)

    def _from_email(self, value: str) -> bool:
        norm = normalize(value)
        if len(norm) >= MIN_TAINT_LEN and any(norm in c for c in self.corpus):
            return True
        return any(p in norm or (len(norm) >= MIN_TAINT_LEN and norm in p) for p in self.pieces)

    def source_of(self, f: Field) -> Source:
        if self._in_registry(f.value, self.user):
            derived = Source.USER
        elif self._in_registry(f.value, self.system):
            derived = Source.SYSTEM_TOOL
        elif self._from_email(f.value):
            derived = self.content_source
        else:
            derived = Source.UNTRUSTED_EMAIL
        claimed = f.source
        if claimed == Source.TRUSTED_CONTACT and self.content_source != Source.TRUSTED_CONTACT:
            claimed = Source.UNTRUSTED_EMAIL
        return least_trusted(derived, claimed)


# --------------------------------------------------------------- matchers

def _host_allowed(host: str, allowed: Iterable[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in allowed)


def _ascii_host(host: str) -> Optional[str]:
    host = host.strip().lower().rstrip(".")
    if not host:
        return None
    if not host.isascii():
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            return None
    return host


def _url_host(url: str) -> Optional[str]:
    """Host a URL would contact, or None if it cannot be determined safely."""
    url = url.rstrip(".,;:!?)]}'\"")
    lower = url.lower()
    if lower.startswith("mailto:"):
        addr = url[7:].split("?", 1)[0]
        return _ascii_host(addr.rpartition("@")[2]) if "@" in addr else None
    if lower.startswith(("javascript:", "data:", "vbscript:", "file:")):
        return None
    if lower.startswith("www."):
        url = "http://" + url
    elif url.startswith("//"):
        url = "http:" + url
    try:
        parts = urlsplit(url)
        if "\\" in parts.netloc:
            return None
        host = parts.hostname
        _ = parts.port  # raises on a malformed port
    except ValueError:
        return None
    return _ascii_host(host) if host else None


def _clean(text: str) -> str:
    return unicodedata.normalize("NFKC", html.unescape(text)).translate(_ZERO_WIDTH)


def find_disallowed_urls(text: str, allowed: list[str]) -> list[str]:
    bad = []
    for m in _URL_RE.finditer(_clean(text)):
        host = _url_host(m.group(0))
        if host is None or not _host_allowed(host, allowed):
            bad.append(m.group(0))
    return bad


def _is_financial_key(key: str) -> bool:
    tokens = [t[:-1] if t.endswith("s") and len(t) > 3 else t for t in re.split(r"[^a-z0-9]+", key.lower()) if t]
    return any(t in FINANCIAL_KEY_TOKENS for t in tokens) or "iban" in key.lower()


def _is_financial_value(value: str) -> bool:
    text = _clean(value)
    return bool(_IBAN_RE.search(text.upper()) or _ACCOUNT_RE.search(text) or _BIC_RE.search(text))


def _bad_recipients(args: dict[str, Field], allowed: list[str]) -> list[str]:
    keys = [k for k in args if k.lower() in RECIPIENT_KEYS]
    if not keys:
        return ["(no recipient argument)"]
    bad = []
    for k in keys:
        value = _clean(args[k].value)
        addrs = _ADDR_RE.findall(value)
        if not addrs and value.strip():
            bad.append(f"{k}: unparseable recipient {value.strip()!r}")
        for a in addrs:
            host = _ascii_host(a.rpartition("@")[2])
            if host is None or not _host_allowed(host, allowed):
                bad.append(f"{k}: {a}")
    return bad


# ----------------------------------------------------------------- engine

def _evaluate(ctx: PolicyContext, cfg: PolicyConfig) -> PolicyDecision:
    if not isinstance(ctx, PolicyContext) or not isinstance(cfg, PolicyConfig):
        raise TypeError("policy engine requires a PolicyContext and a PolicyConfig")
    action = ctx.action
    tier = cfg.tiers.get(action.tool)
    if tier is None:
        return PolicyDecision(
            verdict="BLOCK",
            rule_id="P-08",
            reason_plain_english=f"'{action.tool}' is not a registered tool. Anything not explicitly allowed is denied.",
            offending_fields=["tool"],
            triggered_rules=["P-08"],
        )

    prov = _Provenance(ctx)
    sources: dict[str, Source] = {name: prov.source_of(f) for name, f in action.args.items()}
    texts: dict[str, str] = {name: f.value for name, f in action.args.items()}
    if action.draft_body is not None:
        sources["draft_body"] = Source.UNTRUSTED_EMAIL
        texts["draft_body"] = action.draft_body
    untrusted = [n for n, s in sources.items() if s == Source.UNTRUSTED_EMAIL]
    allowed = cfg.allowed_domains
    blocks: list[tuple[str, str, list[str]]] = []

    if tier != Tier.READ_ONLY:
        worst = [f for f in ctx.injection_findings if f.severity >= INJECTION_BLOCK_SEVERITY]
        if worst:
            techniques = sorted({f.technique for f in worst})
            blocks.append((
                "P-02",
                f"The email contains an attempt to instruct the assistant (severity {max(f.severity for f in worst)}: "
                f"{', '.join(techniques)}). Only read-only actions are permitted on this email.",
                [f"injection:{t}" for t in techniques],
            ))

    egress = {n: find_disallowed_urls(t, allowed) for n, t in texts.items()}
    egress = {n: urls for n, urls in egress.items() if urls}
    if egress:
        sample = next(iter(egress.values()))[0]
        blocks.append((
            "P-04",
            f"The action would emit a link or image pointing outside the allowed domains (e.g. {sample[:80]}). "
            "Rendering or sending it could leak data to that server.",
            sorted(egress),
        ))

    if action.tool == "forward_external":
        bad = _bad_recipients(action.args, allowed)
        if bad:
            blocks.append((
                "P-03",
                "Forwarding outside the organisation is only permitted to allowed domains. Rejected: " + "; ".join(bad) + ".",
                sorted({b.split(":", 1)[0] for b in bad}),
            ))

    if tier != Tier.READ_ONLY:
        fin = [
            n for n, f in action.args.items()
            if sources[n] == Source.UNTRUSTED_EMAIL and (_is_financial_key(n) or _is_financial_value(f.value))
        ]
        if fin:
            blocks.append((
                "P-05",
                "Bank or payment details in this action came from the email itself. Payment details are never "
                "taken from unverified email content.",
                sorted(fin),
            ))

    if tier == Tier.CONSEQUENTIAL and untrusted:
        blocks.append((
            "P-01",
            f"'{action.tool}' has real-world consequences and these arguments trace back to untrusted email "
            f"content: {', '.join(sorted(untrusted))}. Email content can be data, never instructions.",
            sorted(untrusted),
        ))

    if blocks:
        blocks.sort(key=lambda b: BLOCK_PRECEDENCE.index(b[0]))
        rule, reason, _ = blocks[0]
        fields = sorted({f for b in blocks for f in b[2]})
        if len(blocks) > 1:
            reason += " Also triggered: " + ", ".join(b[0] for b in blocks[1:]) + "."
        return PolicyDecision(
            verdict="BLOCK",
            rule_id=rule,
            reason_plain_english=reason,
            offending_fields=fields,
            triggered_rules=[b[0] for b in blocks],
        )

    if tier == Tier.READ_ONLY:
        return PolicyDecision(
            verdict="ALLOW",
            rule_id="TIER-READ_ONLY",
            reason_plain_english=f"'{action.tool}' is read-only and emits nothing outside the allowed domains.",
        )

    needs_oob = ctx.sensitive_request and not ctx.identity.verified
    oob_note = (
        "Verify with the sender using contact details already on file (phone or directory), never details "
        "from this email. Identity gaps: " + "; ".join(ctx.identity.failures or ["unverified"]) + "."
    ) if needs_oob else None

    if ctx.risk.level == "INSUFFICIENT_EVIDENCE":
        return PolicyDecision(
            verdict="HOLD_FOR_EVIDENCE",
            rule_id="P-06",
            reason_plain_english=(
                "The evidence is insufficient or contradictory, so this is neither allowed nor blocked "
                f"automatically. {len(ctx.risk.open_questions)} open question(s) need answers first."
            ),
            triggered_rules=["P-06"],
            requires_out_of_band_verification=needs_oob,
            verification_note=oob_note,
        )

    if needs_oob:
        return PolicyDecision(
            verdict="CONFIRM",
            rule_id="P-07",
            reason_plain_english=(
                "This is a sensitive request and the sender did not pass identity verification. "
                "A human must confirm after verifying out-of-band."
            ),
            offending_fields=["sender"],
            triggered_rules=["P-07"],
            requires_out_of_band_verification=True,
            verification_note=oob_note,
        )

    if tier == Tier.REVERSIBLE:
        critical = cfg.critical_args.get(action.tool)
        critical = list(action.args) if critical is None else critical
        bad = sorted(n for n in critical if n in action.args and sources[n] == Source.UNTRUSTED_EMAIL)
        if bad:
            return PolicyDecision(
                verdict="CONFIRM",
                rule_id="TIER-REVERSIBLE",
                reason_plain_english=f"Reversible action, but {', '.join(bad)} came from the email. Confirm before it is applied.",
                offending_fields=bad,
            )
        return PolicyDecision(
            verdict="ALLOW",
            rule_id="TIER-REVERSIBLE",
            reason_plain_english=f"'{action.tool}' is reversible and its critical arguments come from trusted sources.",
        )

    sensitive_note = (
        "Sensitive request: even though the sender passed verification, confirm by phone using the number "
        "on file before approving."
    ) if ctx.sensitive_request else None
    return PolicyDecision(
        verdict="CONFIRM",
        rule_id="TIER-CONSEQUENTIAL",
        reason_plain_english=f"'{action.tool}' has real-world consequences. All arguments are traceable to trusted sources; a human must approve.",
        requires_out_of_band_verification=ctx.sensitive_request,
        verification_note=sensitive_note,
    )


def evaluate(ctx: PolicyContext, config: PolicyConfig) -> PolicyDecision:
    """Fail closed: any exception yields BLOCK."""
    try:
        return _evaluate(ctx, config)
    except Exception as exc:  # noqa: BLE001 - fail closed on anything
        return PolicyDecision(
            verdict="BLOCK",
            rule_id="P-00",
            reason_plain_english=f"The policy engine could not evaluate this action ({type(exc).__name__}), so it is blocked.",
            triggered_rules=["P-00"],
        )
