"""Rules-only scan: every deterministic Shield detector over one parsed message, combined into the
unified verdict (master prompt section 4.6).

This is the Phase 1 core and the default (rules-only) benchmark mode. Phase 2 adds the quarantined
LLM layer, claim extraction and fact-checking on top of it; until then the claims component is
empty and the explanation is a plain listing of the evidence.
"""
from __future__ import annotations

import time
import uuid

from shield import hidden_content as hc
from shield import injection, phishing, policy, scam_patterns, scoring, settings, views
from shield.email_parser import ParsedEmail, parse_input
from shield.schemas import (
    AuthenticityComponent,
    ClaimsComponent,
    Components,
    Explanation,
    HiddenContentComponent,
    HiddenFinding,
    InjectionComponent,
    Latency,
    LinksComponent,
    ProposedAction,
    RuleHit,
    ScamComponent,
    UnifiedVerdict,
)


def _dedupe(findings: list[HiddenFinding]) -> list[HiddenFinding]:
    seen, out = set(), []
    for f in findings:
        key = (f.id, f.location, f.hidden_text)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def _auth_component(pe: ParsedEmail) -> tuple[AuthenticityComponent, list[HiddenFinding]]:
    sev = settings.load("policy")["scoring"]["auth_signals"]
    comp = AuthenticityComponent(score=0)
    severities: list[str] = []
    extra_findings: list[HiddenFinding] = []
    if not pe.has_headers:
        return comp, extra_findings
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
    extra_findings += sender.homoglyphs
    comp.score = scoring.severity_score(severities)
    return comp, extra_findings


def explain_en(v: UnifiedVerdict) -> str:
    """Plain English listing of the evidence behind each component (no model involved)."""
    c = v.components
    lines = [f"{v.overall.label} (score {v.overall.score}/100)."]
    if c.hidden_content.findings:
        kinds = sorted({f.id for f in c.hidden_content.findings})
        lines.append(f"Hidden content: {len(c.hidden_content.findings)} finding(s) ({', '.join(kinds)}).")
    if c.injection.rule_hits:
        cats = sorted({h.category.replace('_', ' ') for h in c.injection.rule_hits})
        lines.append(f"Instructions aimed at an AI: {', '.join(cats)}.")
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
    if v.analysis_failures:
        lines.append("Parts of the analysis failed: " + "; ".join(v.analysis_failures) + ".")
    if len(lines) == 1:
        lines.append("No warning signs were found by the rule-based checks. These checks are heuristic and can miss things.")
    return " ".join(lines)


def scan_message(pe: ParsedEmail, email_id: str | None = None, *, mode: str | None = None,
                 analysis_failures: list[str] | None = None) -> UnifiedVerdict:
    """Run every deterministic detector over a parsed message and build the unified verdict."""
    t0 = time.perf_counter()
    stages: dict[str, int] = {}

    def lap(name: str, start: float) -> float:
        now = time.perf_counter()
        stages[name] = int((now - start) * 1000)
        return now

    t = t0
    html_scan = hc.scan_html(pe.text_html) if pe.text_html else None
    findings: list[HiddenFinding] = list(html_scan.findings) if html_scan else []
    t = lap("hidden_html", t)

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
    t = lap("hidden_other", t)

    rule_hits: list[RuleHit] = injection.scan_text(f"{pe.subject}\n{view.raw_text}", "message")
    for att in pe.attachments:
        if att.text:
            rule_hits += injection.scan_text(att.text, f"attachment {att.filename}")
    attempted = injection.attempted_actions(view.raw_text, [h for h in rule_hits if h.location == "message"])
    t = lap("injection_rules", t)

    auth, sender_findings = _auth_component(pe)
    findings += sender_findings
    link_items, _ = phishing.analyze_links(html_scan.links if html_scan else [], view.visible_text if html_scan
                                           else pe.text_plain or "")
    t = lap("authenticity_links", t)

    scam_hits = scam_patterns.scan("\n".join([pe.subject, view.visible_text, *attachment_text]))
    t = lap("scam_rules", t)

    findings = _dedupe(findings)
    components = Components(
        hidden_content=HiddenContentComponent(score=scoring.severity_score([f.severity for f in findings]),
                                              findings=findings),
        injection=InjectionComponent(score=scoring.severity_score([h.severity for h in rule_hits]),
                                     rule_hits=rule_hits, attempted_actions=attempted),
        authenticity=auth,
        links=LinksComponent(score=scoring.severity_score([i.severity for i in link_items if i.severity]),
                             items=link_items),
        scam=ScamComponent(score=scoring.severity_score([d.severity for d in scam_hits]), detectors=scam_hits),
        claims=ClaimsComponent(score=0),
    )
    failures = list(analysis_failures or [])
    if pe.body_truncated:
        failures.append("message body was longer than 200,000 characters; only the first part was scanned")
    verdict = UnifiedVerdict(
        email_id=email_id or uuid.uuid4().hex,
        overall=scoring.overall(components, failures),
        components=components,
        visible_vs_raw=view,
        analysis_failures=failures,
    )
    signals = policy.Signals.from_verdict(verdict)
    verdict.proposed_actions = [
        ProposedAction(action=a.action, target=a.target, origin="untrusted_content",
                       policy=policy.decide(a.action, a.target, "untrusted_content", verdict.overall.label,
                                            mode=mode, signals=signals))
        for a in attempted
    ]
    verdict.explanation = Explanation(en=explain_en(verdict), user_language="en", text=explain_en(verdict))
    lap("score_policy", t)
    verdict.latency_ms = Latency(total=int((time.perf_counter() - t0) * 1000), per_stage=stages)
    return verdict


def scan_raw(data: bytes | str, source: str = "paste", email_id: str | None = None, *,
             mode: str | None = None) -> UnifiedVerdict:
    """Parse raw email source or plain text and scan it."""
    return scan_message(parse_input(data, source), email_id, mode=mode)
