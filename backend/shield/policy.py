"""Action Guard: the deterministic policy engine (master prompt section 6, Addendum A1.4).

Pure Python, no LLM. Every proposed action passes through `decide`, and nothing an LLM writes can
override the result. Rules are evaluated top to bottom; the first match wins:

  P0  any error while evaluating, or an unknown action           -> BLOCK (fail closed)
  P1  origin is untrusted content and the action is not summarize,
      report_phishing or quarantine_email                         -> BLOCK
  P2  execute_instruction_from_content                            -> BLOCK
  E-EGRESS  outgoing text links or loads content from a domain
            that is not allowed (exfiltration via links/images)   -> BLOCK
  P3  verdict DANGEROUS and a consequential action                -> BLOCK
  E-FINANCIAL  outgoing text carries bank/card/identity numbers   -> REQUIRE_APPROVAL
  P4  send/forward/share to a recipient outside the allowlist     -> REQUIRE_APPROVAL
  P5  verdict SUSPICIOUS and a consequential action               -> REQUIRE_APPROVAL
  P6  delete_email                                                -> REQUIRE_APPROVAL
  P7  summarize, extract_action_items, draft_reply, report_phishing,
      quarantine_email                                            -> ALLOW
  P8  anything else                                               -> REQUIRE_APPROVAL
  S1  strict mode only: any signal turns an ALLOW into REQUIRE_APPROVAL, except the warning
      summary and the protective steps (summarize, report_phishing, quarantine_email), which run
      automatically with a `notice`

P0, P1, P2 and E-EGRESS apply in both modes. Strict mode is never less strict than balanced.
Ported from Sentinel (bbsarada07/CVR, policy.py): origin is recomputed rather than trusted (a
target counts as the user's only if the user typed it), the outgoing-URL check (Sentinel P-04)
and fail-closed evaluation (Sentinel P-00).
"""
from __future__ import annotations

import html
import re
import threading
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

from shield import domains, redact, settings
from shield.schemas import ACTIONS, PolicyDecision, UnifiedVerdict
from shield.textnorm import strip_invisible

P1_EXCEPTIONS = frozenset({"summarize", "report_phishing", "quarantine_email"})
CONSEQUENTIAL = frozenset({"send_reply", "forward_email", "share_data", "open_link", "download_attachment"})
RECIPIENT_ACTIONS = frozenset({"send_reply", "forward_email", "share_data"})
OUTGOING_TEXT_ACTIONS = frozenset({"draft_reply", "send_reply", "forward_email", "share_data"})
P7_ALLOW = frozenset({"summarize", "extract_action_items", "draft_reply", "report_phishing", "quarantine_email"})
# In strict mode these still run on a flagged message: they only read or protect, and send nothing out.
STRICT_AUTOMATIC = frozenset({"summarize", "report_phishing", "quarantine_email"})
FINANCIAL_KINDS = frozenset({"AADHAAR", "CARD", "ACCOUNT_NO", "OTP", "UPI_ID", "PAN", "IFSC"})
_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$")
_ADDR_RE = re.compile(r"[^\s<>,;\"']+@[^\s<>,;\"']+")
# URLs in outgoing text: scheme-prefixed, protocol-relative, www., or bare domain/path (an
# email address's domain is not matched). Adapted from Sentinel's _URL_RE.
_URL_RE = re.compile(
    r"""(?ix)
    \b(?:https?|ftp|wss?|file|javascript|data|vbscript):[^\s"'<>`]+
    | (?<![\w@.:/])//[^\s"'<>`/]+[^\s"'<>`]*
    | \bwww\.[^\s"'<>`]+
    | (?<![:/\w@.])(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,24}(?:/[^\s"'<>]*)?
    """
)


# ------------------------------------------------------------------------------ inputs


@dataclass(frozen=True)
class Signals:
    """Anything strict mode escalates on (Addendum A1.4)."""

    findings: int = 0
    analysis_failures: int = 0
    auth_fail_or_none: bool = False
    flagged_links: int = 0
    false_or_misleading_claims: int = 0
    llm_state: str | None = None  # quota_exhausted / llm_unavailable when the AI part did not run

    def any(self) -> bool:
        return bool(self.findings or self.analysis_failures or self.auth_fail_or_none or self.flagged_links
                    or self.false_or_misleading_claims or self.llm_state in ("quota_exhausted", "llm_unavailable"))

    def describe(self) -> list[str]:
        out = []
        if self.findings:
            out.append(f"{self.findings} detector finding(s)")
        if self.llm_state == "quota_exhausted":
            out.append("the AI part of the check is unavailable (daily model quota used up), so this is a rules-only result")
        elif self.llm_state == "llm_unavailable":
            out.append("the AI part of the check is unavailable, so this is a rules-only result")
        if self.analysis_failures:
            out.append(f"{self.analysis_failures} analysis failure(s)")
        if self.auth_fail_or_none:
            out.append("sender authentication failed or is missing")
        if self.flagged_links:
            out.append(f"{self.flagged_links} flagged link(s)")
        if self.false_or_misleading_claims:
            out.append(f"{self.false_or_misleading_claims} false or misleading claim(s)")
        return out

    @classmethod
    def from_verdict(cls, v: UnifiedVerdict) -> "Signals":
        c = v.components
        findings = (len(c.hidden_content.findings) + len(c.injection.rule_hits) + len(c.scam.detectors)
                    + len(c.authenticity.lookalikes) + len(c.authenticity.signals))
        auth_bad = any(x in ("fail", "none") for x in (c.authenticity.spf, c.authenticity.dkim, c.authenticity.dmarc))
        return cls(
            findings=findings,
            analysis_failures=len(v.analysis_failures),
            auth_fail_or_none=auth_bad,
            flagged_links=sum(1 for item in c.links.items if item.flags),
            false_or_misleading_claims=sum(1 for i in c.claims.items if i.verdict in ("FALSE", "MISLEADING")),
            llm_state=v.llm_status.state,
        )


@dataclass(frozen=True)
class UserContext:
    """What the policy engine knows besides the action itself.

    allowed_domains: recipient domains the user trusts (rule P4, E-EGRESS)
    user_values:     values the user typed themselves (e.g. a recipient address); any other
                     target is treated as coming from the message or a model
    """

    allowed_domains: tuple[str, ...] = ()
    user_values: tuple[str, ...] = ()


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", html.unescape(text or ""))
    return re.sub(r"\s+", "", strip_invisible(text, keep_legit_joiners=False)).casefold()


def resolve_origin(claimed: str, target: str | None, ctx: UserContext | None) -> str:
    """Recompute where an action's target came from. The result can only be less trusted than
    `claimed`: a value the user typed is 'user'; a value found in the message, or one that matches
    nothing the user typed (invented by a model), is 'untrusted_content'. Without a context the
    claimed origin is kept, so callers must pass one whenever a target came from a planner."""
    if claimed != "user":
        return "untrusted_content"
    if target is None or ctx is None:
        return claimed
    norm = _norm(target)
    if norm and norm in {_norm(v) for v in ctx.user_values if v.strip()}:
        return "user"
    return "untrusted_content"


def _host_allowed(host: str | None, allowed: tuple[str, ...]) -> bool:
    return bool(host) and any(host == d or host.endswith("." + d) for d in allowed)


def disallowed_urls(text: str, allowed: tuple[str, ...]) -> list[str]:
    """URLs in `text` whose host is not in the allowed domains (script/data URLs always count)."""
    bad = []
    for m in _URL_RE.finditer(unicodedata.normalize("NFKC", html.unescape(strip_invisible(text or "")))):
        url = m.group(0).rstrip(".,;:!?)]}'\"")
        host = domains.host_of(url)
        if host is None or not _host_allowed(host, allowed):
            bad.append(url)
    return bad


def _recipients_allowed(target: str | None, allowed: tuple[str, ...]) -> bool:
    if not target:
        return False
    addrs = _ADDR_RE.findall(target)
    if addrs:
        return all(_host_allowed(domains.normalize_host(a.rpartition("@")[2]), allowed) for a in addrs)
    return _host_allowed(domains.host_of(target), allowed)


# ----------------------------------------------------------------------------- decision


def _d(decision: str, rule_id: str, reason: str) -> PolicyDecision:
    return PolicyDecision(decision=decision, rule_id=rule_id, reason=reason)


def _balanced(action: str, target: str | None, origin: str, label: str, ctx: UserContext,
              content: str | None) -> PolicyDecision:
    if origin == "untrusted_content" and action not in P1_EXCEPTIONS:
        return _d("BLOCK", "P1", "This action was asked for by the message itself. Text inside a message is "
                                 "treated as information, never as a command.")
    if action == "execute_instruction_from_content":
        return _d("BLOCK", "P2", "Instructions found inside content are never carried out.")
    if action in OUTGOING_TEXT_ACTIONS and content:
        bad = disallowed_urls(content, ctx.allowed_domains)
        if bad:
            return _d("BLOCK", "E-EGRESS", f"The outgoing text links to or loads {bad[0][:80]}, which is not an allowed "
                                           "domain. Links and images can leak data to the server they point at.")
    if label == "DANGEROUS" and action in CONSEQUENTIAL:
        return _d("BLOCK", "P3", "This message was judged dangerous, so actions that send, share, open or "
                                 "download anything are blocked.")
    if action in OUTGOING_TEXT_ACTIONS and content:
        kinds = FINANCIAL_KINDS.intersection(redact.find(content))
        if kinds:
            return _d("REQUIRE_APPROVAL", "E-FINANCIAL", "The outgoing text contains "
                      + ", ".join(sorted(k.lower().replace("_", " ") for k in kinds))
                      + " details. A person must check this before it goes anywhere.")
    if action in RECIPIENT_ACTIONS and not _recipients_allowed(target, ctx.allowed_domains):
        return _d("REQUIRE_APPROVAL", "P4", f"The recipient ({target or 'none given'}) is not on your list of "
                                            "trusted addresses.")
    if label == "SUSPICIOUS" and action in CONSEQUENTIAL:
        return _d("REQUIRE_APPROVAL", "P5", "This message looks suspicious, so a person must approve this action.")
    if action == "delete_email":
        return _d("REQUIRE_APPROVAL", "P6", "Deleting an email always needs your approval.")
    if action in P7_ALLOW:
        return _d("ALLOW", "P7", "This action only reads, drafts or keeps notes inside FactFlow, or protects you.")
    return _d("REQUIRE_APPROVAL", "P8", "No rule allows this action automatically, so a person must decide.")


def decide(
    action: str,
    target: str | None,
    origin: str,
    verdict_label: str,
    user_context: UserContext | None = None,
    *,
    mode: str | None = None,
    signals: Signals | None = None,
    content: str | None = None,
) -> PolicyDecision:
    """Decide one proposed action. Deterministic and side-effect free; any error -> BLOCK (P0).

    mode: 'strict' or 'balanced' (default from policy.yml). signals: strict-mode triggers; when not
    given, any label other than SAFE counts as a signal. content: outgoing text for drafts/replies.
    """
    try:
        if action not in ACTIONS:
            return _d("BLOCK", "P0", f"'{action}' is not a known action. Anything not explicitly allowed is denied.")
        if origin not in ("user", "untrusted_content"):
            raise ValueError(f"unknown origin {origin!r}")
        if verdict_label not in ("SAFE", "SUSPICIOUS", "DANGEROUS"):
            raise ValueError(f"unknown verdict label {verdict_label!r}")
        ctx = user_context or UserContext()
        mode = mode or settings.load("policy").get("policy_mode", "strict")
        if mode not in ("strict", "balanced"):
            raise ValueError(f"unknown policy mode {mode!r}")
        origin = resolve_origin(origin, target, user_context)
        decision = _balanced(action, target, origin, verdict_label, ctx, content)
        if mode == "strict" and decision.decision == "ALLOW":
            triggered = signals.any() if signals is not None else verdict_label != "SAFE"
            if triggered:
                found = signals.describe() if signals is not None else [f"verdict {verdict_label}"]
                if action in STRICT_AUTOMATIC:
                    return PolicyDecision(decision="ALLOW", rule_id=decision.rule_id, reason=decision.reason,
                                          notice="Strict mode: this message raised " + "; ".join(found) + ". This step "
                                          "ran automatically because it only reads or protects you; it is in the audit log.")
                return _d("REQUIRE_APPROVAL", "S1", "Strict mode: this message raised " + "; ".join(found)
                          + ", so this step waits for your approval.")
        return decision
    except Exception as exc:  # noqa: BLE001 - fail closed on anything
        return _d("BLOCK", "P0", f"The policy engine could not evaluate this action ({type(exc).__name__}), so it is blocked.")


# ------------------------------------------------------------------------ configuration


@dataclass(frozen=True)
class PolicyConfig:
    mode: str = "strict"
    allowed_domains: tuple[str, ...] = ()
    approval_ttl_seconds: int = 600


def validate_domain(domain: str) -> str:
    """Normalise a domain for the allowlist; IP addresses and malformed names are rejected."""
    d = (domain or "").strip().lower().rstrip(".")
    if domains.is_ip(d):
        raise ValueError(f"IP addresses cannot be added to the allowlist: {d!r}")
    if not _DOMAIN_RE.match(d):
        raise ValueError(f"not a valid domain: {d!r}")
    return d


def load_config() -> PolicyConfig:
    data = settings.load("policy")
    return PolicyConfig(
        mode=data.get("policy_mode", "strict"),
        allowed_domains=tuple(sorted({validate_domain(d) for d in data.get("allowed_domains") or []})),
        approval_ttl_seconds=int(data.get("approval_ttl_seconds", 600)),
    )


@dataclass
class PolicyStore:
    """Runtime policy settings. Loosening needs confirm=True: switching strict -> balanced, or
    adding a trusted domain. Tightening never does. Every accepted change is passed to `on_change`
    (the audit log) before it takes effect; if recording fails, the change is not applied."""

    config: PolicyConfig = field(default_factory=load_config)
    on_change: Callable[[dict], None] | None = None
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def get(self) -> PolicyConfig:
        with self._lock:
            return self.config

    def _commit(self, new: PolicyConfig, change: dict) -> PolicyConfig:
        change["at"] = datetime.now(timezone.utc).isoformat()
        if self.on_change:
            self.on_change(change)
        self.config = new
        return new

    def plan_mode(self, mode: str, *, confirm: bool = False, actor: str = "human") -> tuple[PolicyConfig, dict | None]:
        """Validate a mode change without applying it: (new config, change record or None)."""
        if mode not in ("strict", "balanced"):
            raise ValueError(f"unknown policy mode {mode!r}")
        old = self.get()
        if mode == old.mode:
            return old, None
        if mode == "balanced" and not confirm:
            raise PermissionError("Switching to balanced mode loosens the policy and needs confirm=True.")
        return replace(old, mode=mode), {"field": "policy_mode", "previous": old.mode, "new": mode, "actor": actor}

    def plan_domains(self, new_domains: list[str], *, confirm: bool = False,
                     actor: str = "human") -> tuple[PolicyConfig, dict | None]:
        """Validate an allowlist change without applying it: (new config, change record or None)."""
        cleaned = tuple(sorted({validate_domain(d) for d in new_domains}))
        old = self.get()
        added = set(cleaned) - set(old.allowed_domains)
        if added and not confirm:
            raise PermissionError(f"Adding trusted domains needs confirm=True: {sorted(added)}")
        if cleaned == old.allowed_domains:
            return old, None
        return replace(old, allowed_domains=cleaned), {"field": "allowed_domains", "previous": list(old.allowed_domains),
                                                       "new": list(cleaned), "actor": actor}

    def apply(self, new: PolicyConfig, expected: PolicyConfig) -> None:
        """Apply a planned config, only if nothing changed since it was planned (the change must
        already be in the audit log)."""
        with self._lock:
            if self.config != expected:
                raise RuntimeError("the policy changed while this change was being recorded; try again")
            self.config = new

    def set_mode(self, mode: str, *, confirm: bool = False, actor: str = "human") -> PolicyConfig:
        with self._lock:
            new, change = self.plan_mode(mode, confirm=confirm, actor=actor)
            return self._commit(new, change) if change else new

    def set_allowed_domains(self, new_domains: list[str], *, confirm: bool = False, actor: str = "human") -> PolicyConfig:
        with self._lock:
            new, change = self.plan_domains(new_domains, confirm=confirm, actor=actor)
            return self._commit(new, change) if change else new
