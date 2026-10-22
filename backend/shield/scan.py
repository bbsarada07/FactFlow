"""Deterministic scan of one message, and assembly of the unified verdict (prompt section 4.6).

`rules_scan` runs every deterministic detector. `finalize` merges in the quarantined reader's
output and claim verdicts when the full pipeline has them, scores, works out harm and the input
type, and runs every proposed action through the policy engine. The rules-only verdict (also the
default benchmark mode) is simply `finalize(rules_scan(...))`.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from shield import hidden_content as hc
from shield import injection, phishing, policy, qr, scam_patterns, scoring, settings, views
from shield.email_parser import ParsedEmail, parse_input
from shield.hidden_content import HtmlScan
from shield.quarantine import QReading
from shield.schemas import (
    SEVERITY_RANK,
    AttemptedAction,
    AuthenticityComponent,
    ClaimItem,
    ClaimsComponent,
    Components,
    Explanation,
    Harm,
    HiddenContentComponent,
    HiddenFinding,
    InjectionComponent,
    Latency,
    LinkItem,
    LinksComponent,
    MessageSummary,
    ProposedAction,
    RuleHit,
    ScamComponent,
    ScamHit,
    UnifiedVerdict,
    VisibleVsRaw,
)
from shield.textnorm import normalize_for_match

PIPELINE_VERSION = "inbox-2"
FINANCIAL_SCAMS = {"SC-01", "SC-02", "SC-03", "SC-04", "SC-05", "SC-06", "SC-07", "SC-08", "SC-09"}
CREDENTIAL_SCAMS = {"SC-10", "SC-11"}


@dataclass
class RulesScan:
    """Everything the deterministic detectors found in one message."""

    parsed: ParsedEmail
    html: HtmlScan | None
    view: VisibleVsRaw
    findings: list[HiddenFinding]
    rule_hits: list[RuleHit]
    attempted: list[AttemptedAction]
    auth: AuthenticityComponent
    links: list[LinkItem]
    scam_hits: list[ScamHit]
    qr_links: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    unscanned: bool = False
    stages: dict[str, int] = field(default_factory=dict)

    @property
    def hidden_text(self) -> str:
        """Text an AI would read but a person would not (input for the quarantined reader)."""
        return "\n".join(d.text for d in self.view.diff)


def _dedupe(findings: list[HiddenFinding]) -> list[HiddenFinding]:
    seen, out = set(), []
    for f in findings:
        key = (f.id, f.location, f.hidden_text)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def _auth_component(pe: ParsedEmail) -> tuple[AuthenticityComponent, list[HiddenFinding], list[str]]:
    sev = settings.load("policy")["scoring"]["auth_signals"]
    comp = AuthenticityComponent(score=0)
    severities: list[str] = []
    if not pe.has_headers:
        return comp, [], severities
    auth = phishing.parse_auth(pe.authentication_results, pe.received_spf, pe.dkim_signature_present)
    comp.spf, comp.dkim, comp.dmarc = auth.spf, auth.dkim, auth.dmarc
    for name in ("spf", "dkim", "dmarc"):
        value = getattr(auth, name)
        key = f"{name}_{value}"
        if key in sev:
            comp.signals.append(f"{name.upper()} {value}")
            severities.append(sev[key])
    sender = phishing.check_sender(pe.from_addr, pe.from_display, pe.reply_to, pe.return_path)
    if sender.reply_to_mismatch:
        comp.reply_to_mismatch = True
        comp.signals.append(f"replies go to {pe.reply_to}, a different domain from the sender {pe.from_addr}")
        severities.append(sev["reply_to_mismatch"])
    if sender.return_path_mismatch:
        comp.return_path_mismatch = True
        comp.signals.append(f"bounce address {pe.return_path} is a different domain from the sender")
        severities.append(sev["return_path_mismatch"])
    if sender.display_name_impersonation:
        comp.display_name_impersonation = sender.display_name_impersonation
        comp.signals.append(sender.display_name_impersonation)
        severities.append(sev["display_name_impersonation"])
    comp.lookalikes = sender.lookalikes
    severities += [lk.severity for lk in sender.lookalikes]
    comp.score = scoring.severity_score(severities)
    return comp, sender.homoglyphs, severities


def _images(pe: ParsedEmail, html_scan: HtmlScan | None) -> list[tuple[str, bytes]]:
    images = [(a.filename, a.data) for a in pe.attachments if a.content_type.startswith("image/") and a.data]
    for i, src in enumerate(html_scan.image_srcs if html_scan else []):
        data = qr.data_uri_bytes(src)
        if data:
            images.append((f"inline image {i + 1}", data))
    return images


def rules_scan(pe: ParsedEmail) -> RulesScan:
    """Run every deterministic detector over a parsed message."""
    stages: dict[str, int] = {}
    t = time.perf_counter()

    def lap(name: str) -> None:
        nonlocal t
        now = time.perf_counter()
        stages[name] = round((now - t) * 1000, 1)
        t = now

    html_scan = hc.scan_html(pe.text_html) if pe.text_html else None
    findings: list[HiddenFinding] = list(html_scan.findings) if html_scan else []
    lap("hidden_html")

    alt = None
    if html_scan is not None and pe.text_plain and pe.has_alternative:
        alt = hc.alternative_mismatch(pe.text_plain, html_scan.visible_text)
        if alt:
            findings.append(alt)
    view = views.build(html_scan, pe.text_plain, plain_differs=alt is not None)
    if pe.text_plain:
        findings += hc.unicode_findings(pe.text_plain, "text/plain body")
        if html_scan is None:
            findings += hc.homoglyph_findings(pe.text_plain, "body")
    if pe.subject:
        findings += hc.unicode_findings(pe.subject, "subject")
        findings += hc.homoglyph_findings(pe.subject, "subject")
    if pe.from_display:
        findings += hc.unicode_findings(pe.from_display, "sender display name")
    findings += hc.encoded_findings(view.raw_text, "message")
    attachment_text = []
    for att in pe.attachments:
        findings += hc.attachment_findings(att.filename, att.text or "", att.metadata)
        if att.text:
            attachment_text.append(att.text)
    lap("hidden_other")

    rule_hits = injection.scan_text(f"{pe.subject}\n{view.raw_text}", "message")
    for att in pe.attachments:
        if att.text:
            rule_hits += injection.scan_text(att.text, f"attachment {att.filename}")
    attempted = injection.attempted_actions(view.raw_text, [h for h in rule_hits if h.location == "message"])
    lap("injection_rules")

    qr_found = qr.scan_images(_images(pe, html_scan))
    qr_links = [text for _name, text in qr_found]
    lap("qr")

    auth, sender_findings, _ = _auth_component(pe)
    findings += sender_findings
    text_for_links = view.visible_text if html_scan else (pe.text_plain or "")
    links, _ = phishing.analyze_links(html_scan.links if html_scan else [], text_for_links)
    qr_items, _ = phishing.analyze_links([], "\n".join(qr_links))
    for item in qr_items:
        item.flags.insert(0, "from_qr_code")
        item.severity = item.severity or "medium"  # a link hidden in a picture is itself a signal
        if SEVERITY_RANK[item.severity] < SEVERITY_RANK["medium"]:
            item.severity = "medium"
    links += qr_items
    lap("authenticity_links")

    scam_hits = scam_patterns.scan("\n".join([pe.subject, view.visible_text, *attachment_text]))
    lap("scam_rules")

    failures = []
    if pe.body_truncated:
        failures.append("message body was longer than 200,000 characters; only the first part was scanned")
    failures += [f"attachment {a.filename}: {a.scan_note}" for a in pe.attachments if a.scan_note]
    return RulesScan(
        parsed=pe, html=html_scan, view=view, findings=_dedupe(findings), rule_hits=rule_hits, attempted=attempted,
        auth=auth, links=links, scam_hits=scam_hits, qr_links=qr_links, failures=failures,
        unscanned=pe.body_truncated or any(a.scan_note for a in pe.attachments), stages=stages,
    )


# ------------------------------------------------------------------------- merge + verdict


def _llm_severity(confidence: float) -> str | None:
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.5:
        return "medium"
    return None


def _mark_hidden_quotes(findings: list[HiddenFinding], quotes: list[str]) -> list[HiddenFinding]:
    """Hidden text that the quarantined reader quoted as an instruction counts as a hidden injection."""
    norm_quotes = [normalize_for_match(q) for q in quotes if len(q.strip()) >= 12]
    out = []
    for f in findings:
        text = normalize_for_match(f.hidden_text)
        if norm_quotes and not f.instruction_like and any(q in text for q in norm_quotes):
            f = f.model_copy(update={"instruction_like": True, "severity": "critical"})
        out.append(f)
    return out


def _merge_attempts(a: list[AttemptedAction], b: list[AttemptedAction]) -> list[AttemptedAction]:
    seen, out = set(), []
    for x in [*a, *b]:
        key = (x.action, (x.target or "").lower())
        if key not in seen:
            seen.add(key)
            out.append(x)
    return out


def assess_harm(c: Components, label: str) -> Harm:
    """Agent 5 (scam/fraud extension), deterministic: what acting on this message could cost."""
    types: list[str] = []
    reasons: list[str] = []
    ids = {d.id for d in c.scam.detectors}
    if ids & FINANCIAL_SCAMS:
        types.append("FINANCIAL_FRAUD")
        reasons.append("it follows a known pattern for taking people's money")
    flagged_lookalike = any("lookalike_domain" in i.flags for i in c.links.items) or c.authenticity.lookalikes
    if ids & CREDENTIAL_SCAMS or flagged_lookalike:
        types.append("CREDENTIAL_THEFT")
        reasons.append("it asks for codes or passwords, or points to an imitation website")
    exfil = any(h.category == "exfiltration" for h in c.injection.rule_hits) or any(
        a.action in ("forward_email", "share_data", "send_reply") for a in c.injection.attempted_actions)
    if exfil:
        types.append("DATA_EXFILTRATION")
        reasons.append("it tries to get an AI assistant to send your messages or data elsewhere")
    if any(i.verdict in ("FALSE", "MISLEADING") for i in c.claims.items):
        types.append("MISINFORMATION")
        reasons.append("it spreads a claim that fact-checking found false or misleading")
    if c.authenticity.display_name_impersonation or c.authenticity.lookalikes:
        types.append("IMPERSONATION")
        reasons.append("the sender pretends to be someone else")
    critical = any(d.severity == "critical" for d in c.scam.detectors) or any(
        f.instruction_like for f in c.hidden_content.findings)
    if not types:
        level = "NONE" if label == "SAFE" else "LOW"
    elif label == "DANGEROUS":
        level = "CRITICAL" if critical else "HIGH"
    elif label == "SUSPICIOUS":
        level = "MEDIUM"
    else:
        level = "LOW"
    return Harm(types=types, level=level, reasons=reasons)


def triage(rs: RulesScan, c: Components) -> str:
    """Agent 1 (extension), deterministic: what kind of input this is."""
    if c.injection.rule_hits or (c.injection.llm or {}).get("is_injection"):
        return "injection_attempt"
    if c.scam.detectors or c.authenticity.lookalikes or any("lookalike_domain" in i.flags for i in c.links.items):
        return "phishing_or_scam"
    if rs.qr_links:
        return "qr"
    return "email" if rs.parsed.has_headers else "claim"


def explain_en(v: UnifiedVerdict) -> str:
    """Plain English listing of the evidence behind each component (no model involved)."""
    c = v.components
    lines = [f"{v.overall.label} (score {v.overall.score}/100)."]
    if c.hidden_content.findings:
        kinds = sorted({f.id for f in c.hidden_content.findings})
        lines.append(f"Hidden content: {len(c.hidden_content.findings)} finding(s) ({', '.join(kinds)}).")
    if c.injection.rule_hits or (c.injection.llm or {}).get("is_injection"):
        cats = sorted({h.category.replace('_', ' ') for h in c.injection.rule_hits}
                      | {x.replace('_', ' ') for x in (c.injection.llm or {}).get("categories", [])})
        lines.append(f"Instructions aimed at an AI: {', '.join(cats) or 'yes'}.")
    if c.injection.attempted_actions:
        acts = "; ".join(f"{a.action.replace('_', ' ')}" + (f" to {a.target}" if a.target else "")
                         for a in c.injection.attempted_actions)
        lines.append(f"It tried to make an assistant: {acts}. FactFlow never carries these out.")
    if c.authenticity.signals or c.authenticity.lookalikes:
        items = c.authenticity.signals + [lk.reason for lk in c.authenticity.lookalikes]
        lines.append("Sender: " + "; ".join(items) + ".")
    flagged = [i for i in c.links.items if i.flags]
    if flagged:
        lines.append(f"Links: {len(flagged)} flagged ({', '.join(sorted({f for i in flagged for f in i.flags}))}).")
    if c.scam.detectors:
        lines.append("Scam patterns: " + "; ".join(d.name for d in c.scam.detectors) + ".")
    bad_claims = [i for i in c.claims.items if i.verdict in ("FALSE", "MISLEADING")]
    if bad_claims:
        lines.append("Claims: " + "; ".join(f"'{i.claim}' is {i.verdict}" for i in bad_claims) + ".")
    if v.analysis_failures:
        lines.append("Parts of the analysis failed: " + "; ".join(v.analysis_failures) + ".")
    if len(lines) == 1:
        lines.append("No warning signs were found. These checks are heuristic and can miss things.")
    return " ".join(lines)


def finalize(rs: RulesScan, email_id: str | None = None, *, mode: str | None = None,
             reading: QReading | None = None, claims: list[ClaimItem] | None = None,
             extra_failures: list[str] | None = None, run_mode: str = "rules",
             source: str | None = None, allowed_domains: tuple[str, ...] = ()) -> UnifiedVerdict:
    """Build the unified verdict from the rules scan plus, in the full pipeline, the quarantined
    reader's output and the claim verdicts."""
    t0 = time.perf_counter()
    findings, rule_severities = list(rs.findings), [h.severity for h in rs.rule_hits]
    attempted, llm_dict, scam_hits = list(rs.attempted), None, list(rs.scam_hits)
    if reading is not None:
        inj = reading.injection
        llm_dict = inj.model_dump(mode="json")
        sev = _llm_severity(inj.confidence) if inj.is_injection else None
        if sev:
            rule_severities.append(sev)
            findings = _mark_hidden_quotes(findings, inj.quoted_evidence)
            attempted = _merge_attempts(attempted, inj.attempted_actions)
        if reading.scam.is_scam_or_phishing and reading.scam.confidence >= 0.7:
            scam_hits.append(ScamHit(id="SC-LLM", name="The AI reading also judged this a scam or phishing attempt",
                                     matched_evidence=reading.scam.reasons or ["(no reason given)"], severity="medium"))
    claim_items = list(claims or [])
    components = Components(
        hidden_content=HiddenContentComponent(score=scoring.severity_score([f.severity for f in findings]),
                                              findings=findings),
        injection=InjectionComponent(score=scoring.severity_score(rule_severities), rule_hits=rs.rule_hits,
                                     llm=llm_dict, attempted_actions=attempted),
        authenticity=rs.auth,
        links=LinksComponent(score=scoring.severity_score([i.severity for i in rs.links if i.severity]),
                             items=rs.links),
        scam=ScamComponent(score=scoring.severity_score([d.severity for d in scam_hits]), detectors=scam_hits),
        claims=ClaimsComponent(score=scoring.claim_score([i.verdict for i in claim_items]), items=claim_items),
    )
    failures = [*rs.failures, *(extra_failures or [])]
    pe = rs.parsed
    verdict = UnifiedVerdict(
        email_id=email_id or uuid.uuid4().hex,
        overall=scoring.overall(components, failures, unscanned=rs.unscanned),
        components=components,
        visible_vs_raw=rs.view,
        analysis_failures=failures,
        mode=run_mode,
        pipeline_version=PIPELINE_VERSION,
        message=MessageSummary(source=source or pe.source, has_headers=pe.has_headers, subject=pe.subject,
                               from_addr=pe.from_addr, from_display=pe.from_display, reply_to=pe.reply_to,
                               to=pe.to, date=pe.date, attachments=[a.summary() for a in pe.attachments]),
    )
    verdict.input_type = triage(rs, components)
    verdict.harm = assess_harm(components, verdict.overall.label)
    signals = policy.Signals.from_verdict(verdict)
    ctx = policy.UserContext(allowed_domains=tuple(allowed_domains))
    proposals = [(a.action, a.target, "untrusted_content") for a in attempted]
    if verdict.overall.label == "DANGEROUS":
        proposals += [("report_phishing", None, "user"), ("quarantine_email", None, "user")]
    verdict.proposed_actions = [
        ProposedAction(action=action, target=target, origin=origin,
                       policy=policy.decide(action, target, origin, verdict.overall.label, ctx, mode=mode,
                                            signals=signals))
        for action, target, origin in proposals
    ]
    text = explain_en(verdict)
    verdict.explanation = Explanation(en=text, user_language="en", text=text)
    stages = dict(rs.stages)
    stages["score_policy"] = round((time.perf_counter() - t0) * 1000, 1)
    verdict.latency_ms = Latency(total=int(round(sum(stages.values()))), per_stage=stages)
    return verdict


def scan_message(pe: ParsedEmail, email_id: str | None = None, *, mode: str | None = None,
                 analysis_failures: list[str] | None = None) -> UnifiedVerdict:
    """Rules-only verdict for a parsed message (no model calls)."""
    return finalize(rules_scan(pe), email_id, mode=mode, extra_failures=analysis_failures)


def scan_raw(data: bytes | str, source: str = "paste", email_id: str | None = None, *,
             mode: str | None = None) -> UnifiedVerdict:
    """Parse raw email source or plain text and return the rules-only verdict."""
    t0 = time.perf_counter()
    pe = parse_input(data, source)
    parse_ms = round((time.perf_counter() - t0) * 1000, 1)
    v = scan_message(pe, email_id, mode=mode)
    v.latency_ms.per_stage = {"parse": parse_ms, **v.latency_ms.per_stage}
    v.latency_ms.total = int(round(v.latency_ms.total + parse_ms))
    return v
