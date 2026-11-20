import { useState, useEffect, useCallback, useRef } from "react";
import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import {
  ArrowLeft,
  Shield,
  ShieldAlert,
  AlertTriangle,
  CheckCircle2,
  Lock,
  Copy,
  Check,
  RotateCw,
  ExternalLink,
  MessageSquare,
  FileText,
  Clock,
  Sparkles,
  Link as LinkIcon,
  HelpCircle,
} from "lucide-react";
import toast from "react-hot-toast";

import ShieldNav from "@/components/shield/ShieldNav";
import SignInAgain from "@/components/SignInAgain";
import ShieldBadge, { ActionBadge } from "@/components/shield/ShieldBadge";
import VisibleVsAiReads from "@/components/shield/VisibleVsAiReads";
import Accordion from "@/components/Accordion";
import ConfidenceRing from "@/components/ConfidenceRing";
import ConfidenceBand from "@/components/ConfidenceBand";
import HarmBadge from "@/components/HarmBadge";
import AgentProgress, { AGENT_DEFAULTS } from "@/components/AgentProgress";
import {
  getInboxEmail,
  rememberCheck,
  subscribeToEmailStream,
  escapeSuspiciousCharacters,
  USE_MOCKS,
} from "@/lib/shieldApi";

const HELPLINE = { phone: "1930", portal: "cybercrime.gov.in" };

/** Plain next steps for the person who received the message. */
function adviceFor(report) {
  const label = report?.overall?.label;
  const c = report?.components || {};
  const steps = [];
  if (label === "SAFE") {
    steps.push("No warning signs were found. Still, never share an OTP, PIN or password with anyone who asks.");
    return steps;
  }
  if (c.injection?.score >= 50 || c.hidden_content?.findings?.some((f) => f.instruction_like)) {
    steps.push("Do not ask an AI assistant to summarise, reply to or act on this email: it contains hidden orders aimed at the assistant.");
  }
  if (c.links?.items?.some((l) => l.severity)) {
    steps.push("Do not open the links or scan any QR code in this message. Type the official website address yourself instead.");
  }
  if (c.authenticity?.lookalikes?.length || c.authenticity?.display_name_impersonation) {
    steps.push("The sender is pretending to be someone else. Contact the organisation through its official app or phone number, not through this email.");
  }
  if (c.scam?.detectors?.length) {
    steps.push("This matches a known fraud pattern. Do not pay, share bank or card details, or install any app it asks for.");
  }
  if (report?.message?.attachments?.length) {
    steps.push("Do not open the attachments.");
  }
  steps.push(
    label === "DANGEROUS"
      ? "Delete the email or mark it as phishing. If you already paid or shared details, call the cyber fraud helpline at once."
      : "Treat this email with care and verify it through another channel before doing anything it asks."
  );
  return steps;
}

export default function EmailTrustReportPage() {
  const router = useRouter();
  const { id } = router.query;

  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [errorStatus, setErrorStatus] = useState(null);
  const [copiedWhatsapp, setCopiedWhatsapp] = useState(false);

  // Streaming progress state
  const [streamActive, setStreamActive] = useState(false);
  const [agents, setAgents] = useState(AGENT_DEFAULTS);
  const [streamProgress, setStreamProgress] = useState(0);
  const streamRetries = useRef(0);

  const fetchVerdict = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    setError(null);
    setErrorStatus(null);

    try {
      const res = await getInboxEmail(id);
      if (res.status === "processing") {
        setStreamActive(true);
      } else if (res.status === "failed" || !res.verdict) {
        setError(res.error || "The analysis of this message failed.");
        setStreamActive(false);
      } else {
        setReport(res.verdict);
        setStreamActive(false);
      }
    } catch (err) {
      console.error("Error fetching verdict:", err);
      setErrorStatus(err.status || null);
      setError(err.message || "Failed to load email trust report.");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchVerdict();
  }, [fetchVerdict]);

  // Hook into live stream if processing
  useEffect(() => {
    if (!id || !streamActive) return;

    const unsubscribe = subscribeToEmailStream(
      id,
      (ev) => {
        if (ev.type === "agent") {
          setAgents((prev) =>
            prev.map((a, i) => (i === ev.agent ? { ...a, ...ev } : a))
          );
          if (ev.progress) setStreamProgress(ev.progress);
        } else if (ev.type === "result") {
          setReport(ev.result);
          setStreamActive(false);
        }
      },
      (err) => {
        console.error("Stream error:", err);
        // The stream can drop (proxy timeout, server restart); the stored result is still there.
        setStreamActive(false);
        if (streamRetries.current < 3) {
          streamRetries.current += 1;
          setTimeout(fetchVerdict, 1500);
        }
      }
    );

    return () => unsubscribe();
  }, [id, streamActive, fetchVerdict]);

  // Keep the session's "My checks" list in step with the finished verdict.
  useEffect(() => {
    if (!id || !report?.overall) return;
    rememberCheck({
      email_id: String(id),
      status: "complete",
      label: report.overall.label,
      score: report.overall.score,
      top_reason: report.overall.reasons?.[0],
      subject: report.message?.subject,
      from_addr: report.message?.from_addr,
    });
  }, [id, report]);

  const downloadReport = () => {
    if (!report) return;
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `shield-report-${String(id).slice(0, 12)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const copyWhatsappText = () => {
    const text = report?.explanation?.whatsapp_warning;
    if (!text) return;
    navigator.clipboard.writeText(text);
    setCopiedWhatsapp(true);
    toast.success("WhatsApp warning copied to clipboard!");
    setTimeout(() => setCopiedWhatsapp(false), 2000);
  };

  const v = report?.overall;
  const components = report?.components;
  const message = report?.message;
  const llmStatus = report?.llm_status;
  const proposedActions = report?.proposed_actions || [];
  const latency = report?.latency_ms;

  return (
    <>
      <Head>
        <title>FactFlow Shield — Email Trust Report</title>
      </Head>

      <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6">
        <ShieldNav />

        {/* Top Back Navigation */}
        <div className="mb-6 flex items-center justify-between">
          <Link
            href="/shield"
            className="btn-ghost !py-1.5 !px-3 !text-[12px] flex items-center gap-1.5"
          >
            <ArrowLeft size={13} />
            <span>Back to Inbox</span>
          </Link>

          <span className="mono text-[11px] text-muted">
            ID: {id ? String(id).slice(0, 12) : "..."}
          </span>
        </div>

        {/* Loading State */}
        {loading && (
          <div className="flex flex-col gap-4">
            <div className="animate-pulse rounded-lg border border-subtle bg-card p-8">
              <div className="h-6 w-48 rounded bg-surface mb-4" />
              <div className="h-4 w-3/4 rounded bg-surface mb-2" />
              <div className="h-4 w-1/2 rounded bg-surface" />
            </div>
          </div>
        )}

        {/* Error State */}
        {!loading && error && (
          <div className="rounded-lg border border-red/40 bg-card p-8 text-center">
            {errorStatus === 401 ? (
              <Lock size={36} className="text-red mx-auto mb-3" />
            ) : (
              <ShieldAlert size={36} className="text-red mx-auto mb-3" />
            )}
            <h3 className="font-display text-[18px] font-bold text-primary">
              {errorStatus === 401 ? "Sign in to open this report" : errorStatus === 404 ? "Report not found" : "Report Generation Error"}
            </h3>
            <p className="mt-2 text-[13px] text-secondary max-w-md mx-auto">
              {errorStatus === 401
                ? "Your session has ended. Each report is visible only to the account that ran the check."
                : errorStatus === 404
                ? "There is no report with this id in your account. Reports are private to whoever ran the check."
                : error}
            </p>
            <div className="mt-5 flex justify-center gap-3">
              {errorStatus === 401 && (
                <SignInAgain />
              )}
              <button
                type="button"
                onClick={fetchVerdict}
                className={errorStatus === 401 ? "btn-ghost" : "btn-red !py-2 !px-5 !text-[13px]"}
              >
                <RotateCw size={13} /> Retry
              </button>
            </div>
          </div>
        )}

        {/* Stream Progress State */}
        {streamActive && (
          <div className="mb-6 rounded-lg border border-subtle bg-card p-6">
            <div className="flex items-center justify-between pb-3 mb-4 border-b border-subtle">
              <div className="flex items-center gap-2">
                <RotateCw className="animate-spin text-red" size={18} />
                <span className="font-display text-[15px] font-bold text-primary">
                  Shield Inspection Pipeline In Progress
                </span>
              </div>
              <span className="mono text-[11px] font-bold text-red">
                {streamProgress}%
              </span>
            </div>
            <AgentProgress agents={agents} progress={streamProgress} />
          </div>
        )}

        {/* Full Verdict Report */}
        {!loading && !error && report && (
          <div className="flex flex-col gap-6">
            {/* Header Details */}
            <div className="rounded-lg border border-subtle bg-surface p-5">
              <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-subtle">
                <div className="min-w-0">
                  <h1 className="font-display text-[20px] sm:text-[24px] font-bold text-primary">
                    {escapeSuspiciousCharacters(message?.subject || "Subject Unavailable")}
                  </h1>
                  <div className="mono mt-1 text-[12px] text-secondary flex flex-wrap gap-x-4 gap-y-1">
                    <span>From: {escapeSuspiciousCharacters(message?.from_addr || "unknown")}</span>
                    {message?.date && <span>Date: {message.date}</span>}
                  </div>
                </div>

                <div className="flex items-center gap-2">
                  <ShieldBadge label={v?.label} size="lg" pulse />
                </div>
              </div>

              {/* LLM Status Alert if not ok */}
              {llmStatus && llmStatus.state !== "ok" && (
                <div className="mt-3 rounded-md border border-orange/40 bg-orange/10 p-3 text-[12.5px] text-orange flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <AlertTriangle size={16} className="shrink-0" />
                    <span>
                      <strong>AI Layer Notice:</strong> {llmStatus.reason || "Operating in deterministic rules-only mode."}
                    </span>
                  </div>
                  <span className="mono text-[10.5px] font-bold uppercase tracking-wider">
                    {llmStatus.state}
                  </span>
                </div>
              )}
            </div>

            {/* Verdict Hero Banner */}
            <div
              className="flex flex-col sm:flex-row items-center justify-between gap-6 rounded-lg border border-subtle bg-card p-6 sm:p-8"
              style={{
                borderLeft: `5px solid ${
                  v?.label === "SAFE"
                    ? "#00E676"
                    : v?.label === "SUSPICIOUS"
                    ? "#FF6B00"
                    : "#FF2D2D"
                }`,
              }}
            >
              <div className="flex-1">
                <div className="mono text-[11px] font-bold uppercase tracking-[2px] text-secondary">
                  SECURITY VERDICT SCORE
                </div>
                <div className="mt-2 flex items-baseline gap-3">
                  <span
                    className="font-display text-[48px] sm:text-[56px] font-bold leading-none"
                    style={{
                      color:
                        v?.label === "SAFE"
                          ? "#00E676"
                          : v?.label === "SUSPICIOUS"
                          ? "#FF6B00"
                          : "#FF2D2D",
                    }}
                  >
                    {v?.score}
                  </span>
                  <span className="mono text-[18px] text-secondary font-medium">/ 100</span>
                </div>

                {v?.reasons?.length > 0 ? (
                  <ul className="mt-3 list-none p-0 flex flex-col gap-1 text-[13px] text-secondary">
                    {v.reasons.map((r, i) => (
                      <li key={i} className="flex items-start gap-1.5">
                        <span className="text-red mt-0.5">•</span>
                        <span>{escapeSuspiciousCharacters(r)}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="mt-2 text-[13px] text-green">No anomalous signals triggered.</p>
                )}
              </div>

              <div className="flex items-center gap-6">
                <ConfidenceRing
                  value={v?.confidence ?? 0.8}
                  color={
                    v?.label === "SAFE"
                      ? "#00E676"
                      : v?.label === "SUSPICIOUS"
                      ? "#FF6B00"
                      : "#FF2D2D"
                  }
                  size={90}
                />
              </div>
            </div>

            {/* What to do now */}
            <div className="rounded-lg border border-subtle bg-surface p-5">
              <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                <h3 className="font-display text-[16px] font-bold text-primary flex items-center gap-2">
                  <HelpCircle size={17} className="text-red" />
                  What you should do
                </h3>
                {report.harm?.level && report.harm.level !== "NONE" && (
                  <span className="mono text-[10.5px] font-bold uppercase tracking-wider rounded border border-red/40 bg-red/10 px-2 py-0.5 text-red">
                    Harm: {report.harm.level}
                    {report.harm.types?.length ? ` · ${report.harm.types.join(", ").replace(/_/g, " ")}` : ""}
                  </span>
                )}
              </div>
              <ol className="list-decimal pl-5 flex flex-col gap-1.5 text-[13px] text-secondary">
                {adviceFor(report).map((step, i) => (
                  <li key={i}>{step}</li>
                ))}
              </ol>
              {v?.label !== "SAFE" && (
                <p className="mt-3 text-[12px] text-muted">
                  Lost money or shared details? In India, call the cyber fraud helpline{" "}
                  <strong className="text-primary">{HELPLINE.phone}</strong> or report at{" "}
                  <strong className="text-primary">{HELPLINE.portal}</strong>.
                </p>
              )}
            </div>

            {/* What you see vs What the AI reads */}
            <VisibleVsAiReads
              visibleVsRaw={report.visible_vs_raw}
              hiddenContent={components?.hidden_content}
            />

            {/* Policy Decisions & Proposed Actions */}
            <Accordion
              title="Agent Action Policies & Guardrails"
              count={proposedActions.length}
              countLabel="actions evaluated"
              defaultOpen={true}
            >
              <div className="flex flex-col gap-3">
                {proposedActions.length === 0 ? (
                  <p className="text-[13px] text-muted italic">No action proposals generated for this email.</p>
                ) : (
                  proposedActions.map((pa, idx) => (
                    <div
                      key={idx}
                      className="rounded-md border border-subtle bg-surface p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-[12.5px]"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <ActionBadge decision={pa.policy?.decision || "ALLOW"} />
                          <span className="font-semibold text-primary font-mono uppercase">
                            {pa.action}
                          </span>
                          <span className="mono text-[10.5px] text-muted">
                            [Rule: {pa.policy?.rule_id || "P0"}]
                          </span>
                          {pa.origin === "untrusted_content" && (
                            <span className="pill text-[9.5px] bg-red/15 border-red/40 text-red font-bold">
                              ORIGIN: UNTRUSTED MESSAGE
                            </span>
                          )}
                        </div>
                        <p className="mt-1.5 text-secondary leading-relaxed">
                          {pa.policy?.reason}
                        </p>
                        {pa.policy?.notice && (
                          <p className="mt-1 text-[11.5px] text-orange">
                            ⚡ {pa.policy.notice}
                          </p>
                        )}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </Accordion>

            {/* Component Inspections */}
            <div className="flex flex-col gap-3">
              {/* 1. Prompt Injection */}
              <Accordion
                title="1. Prompt Injection & AI Hijacking"
                count={components?.injection?.rule_hits?.length || 0}
                countLabel="rule hits"
              >
                <div className="flex flex-col gap-3 text-[13px]">
                  <div className="flex items-center justify-between">
                    <span className="text-secondary">Injection Risk Score:</span>
                    <span className="mono font-bold text-primary">{components?.injection?.score || 0}/100</span>
                  </div>

                  {components?.injection?.rule_hits?.length > 0 ? (
                    <div className="flex flex-col gap-2">
                      {components.injection.rule_hits.map((hit, i) => (
                        <div key={i} className="rounded border border-red/30 bg-red/5 p-3 text-[12.5px]">
                          <div className="flex items-center justify-between font-mono">
                            <span className="text-red font-bold">{hit.id} ({hit.category})</span>
                            <span className="text-red uppercase">{hit.severity}</span>
                          </div>
                          <p className="mt-1 text-primary font-mono text-[12px] whitespace-pre-wrap">
                            Evidence: {escapeSuspiciousCharacters(hit.evidence)}
                          </p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-green text-[12.5px]">No prompt injection signatures matched.</p>
                  )}

                  {components?.injection?.attempted_actions?.length > 0 && (
                    <div className="mt-2 rounded border border-red/40 bg-card p-3">
                      <div className="mono text-[11px] text-red font-bold uppercase mb-1">
                        Attempted AI Commands (BLOCKED)
                      </div>
                      <p className="text-secondary text-[12px]">
                        The message attempted to command the assistant to:{" "}
                        <strong className="text-primary">
                          {components.injection.attempted_actions.map((a) => a.action).join(", ")}
                        </strong>
                      </p>
                    </div>
                  )}
                </div>
              </Accordion>

              {/* 2. Authenticity */}
              <Accordion
                title="2. Sender Authenticity & Domain Signals"
                count={components?.authenticity?.signals?.length || 0}
                countLabel="signals"
              >
                <div className="flex flex-col gap-3 text-[13px]">
                  <div className="grid grid-cols-3 gap-2 text-center font-mono text-[11px]">
                    <div className="rounded border border-subtle bg-card p-2">
                      <div className="text-muted">SPF</div>
                      <div className={components?.authenticity?.spf === "pass" ? "text-green font-bold" : "text-red"}>
                        {components?.authenticity?.spf?.toUpperCase() || "NONE"}
                      </div>
                    </div>
                    <div className="rounded border border-subtle bg-card p-2">
                      <div className="text-muted">DKIM</div>
                      <div className={components?.authenticity?.dkim === "pass" ? "text-green font-bold" : "text-red"}>
                        {components?.authenticity?.dkim?.toUpperCase() || "NONE"}
                      </div>
                    </div>
                    <div className="rounded border border-subtle bg-card p-2">
                      <div className="text-muted">DMARC</div>
                      <div className={components?.authenticity?.dmarc === "pass" ? "text-green font-bold" : "text-red"}>
                        {components?.authenticity?.dmarc?.toUpperCase() || "NONE"}
                      </div>
                    </div>
                  </div>

                  {components?.authenticity?.lookalikes?.length > 0 && (
                    <div className="rounded border border-red/40 bg-red/5 p-3">
                      <span className="mono text-[11px] text-red font-bold uppercase block mb-1">
                        Lookalike Domain Detected
                      </span>
                      {components.authenticity.lookalikes.map((l, i) => (
                        <div key={i} className="text-[12.5px] text-primary">
                          <code className="text-red">{l.domain}</code> imitating{" "}
                          {l.legit_domain ? <code className="text-green">{l.legit_domain}</code> : <span>{l.brand}</span>} ({l.reason})
                        </div>
                      ))}
                    </div>
                  )}

                  {(components?.authenticity?.reply_to_mismatch ||
                    components?.authenticity?.return_path_mismatch ||
                    components?.authenticity?.display_name_impersonation) && (
                    <div className="flex flex-wrap gap-1.5">
                      {components.authenticity.display_name_impersonation && (
                        <span className="pill text-[10px] bg-red/10 border-red/40 text-red">DISPLAY NAME IMPERSONATION</span>
                      )}
                      {components.authenticity.reply_to_mismatch && (
                        <span className="pill text-[10px] bg-orange/10 border-orange/40 text-orange">REPLY-TO MISMATCH</span>
                      )}
                      {components.authenticity.return_path_mismatch && (
                        <span className="pill text-[10px] bg-orange/10 border-orange/40 text-orange">BOUNCE ADDRESS MISMATCH</span>
                      )}
                    </div>
                  )}

                  {components?.authenticity?.signals?.length > 0 ? (
                    <ul className="list-none p-0 flex flex-col gap-1 text-[12.5px] text-secondary">
                      {components.authenticity.signals.map((s, i) => (
                        <li key={i} className="flex items-start gap-1.5">
                          <span className="text-orange mt-0.5">•</span>
                          <span>{escapeSuspiciousCharacters(s)}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    !components?.authenticity?.lookalikes?.length && (
                      <p className="text-green text-[12.5px]">No sender spoofing signals found.</p>
                    )
                  )}

                  {message?.reply_to && (
                    <p className="mono text-[11.5px] text-muted">Reply-To: {escapeSuspiciousCharacters(message.reply_to)}</p>
                  )}
                </div>
              </Accordion>

              {/* 3. Links */}
              <Accordion
                title="3. Link & QR Code Inspection"
                count={components?.links?.items?.length || 0}
                countLabel="links"
              >
                <div className="flex flex-col gap-2.5 text-[12.5px]">
                  {components?.links?.items?.length === 0 ? (
                    <p className="text-muted italic">No hyperlinks found in the message.</p>
                  ) : (
                    components?.links?.items?.map((link, idx) => (
                      <div key={idx} className="rounded-md border border-subtle bg-card p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="mono text-primary font-medium truncate max-w-sm sm:max-w-md">
                            {link.url}
                          </span>
                          {link.severity && (
                            <span className="mono text-[10px] text-orange bg-orange/10 px-2 py-0.5 rounded uppercase font-bold">
                              {link.severity}
                            </span>
                          )}
                        </div>
                        {link.flags?.length > 0 && (
                          <div className="mt-2 flex flex-wrap gap-1">
                            {link.flags.map((f) => (
                              <span key={f} className="pill text-[9.5px] bg-subtle text-secondary">
                                {f}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))
                  )}
                </div>
              </Accordion>

              {/* 4. Scam & Fraud Patterns */}
              <Accordion
                title="4. Scam & Social Engineering Patterns"
                count={components?.scam?.detectors?.length || 0}
                countLabel="detectors"
              >
                <div className="text-[13px]">
                  {components?.scam?.detectors?.length === 0 ? (
                    <p className="text-green">No recognized Indian financial scam or fraud templates triggered.</p>
                  ) : (
                    <div className="flex flex-col gap-2">
                      {components?.scam?.detectors?.map((det, i) => (
                        <div key={i} className="rounded border border-orange/40 bg-orange/5 p-3">
                          <div className="font-semibold text-primary">{det.name} ({det.id})</div>
                          <div className="text-secondary text-[12px] mt-1">
                            Evidence matched: {escapeSuspiciousCharacters(det.matched_evidence?.join(", ") || "")}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                  {components?.scam?.template_hit && (
                    <div className="mt-2 rounded border border-orange/30 bg-card p-3 text-[12px]">
                      <div className="mono text-[11px] text-orange font-bold uppercase mb-1">
                        Closest known scam template ({Math.round((components.scam.template_hit.score || 0) * 100)}% similar)
                      </div>
                      <div className="text-primary font-medium">{components.scam.template_hit.template_name}</div>
                      <p className="text-secondary mt-1">“{escapeSuspiciousCharacters(components.scam.template_hit.excerpt || "")}”</p>
                    </div>
                  )}
                </div>
              </Accordion>

              {/* 5. Attachments */}
              {message?.attachments?.length > 0 && (
                <Accordion title="5. Attachments" count={message.attachments.length} countLabel="files">
                  <div className="flex flex-col gap-2 text-[12.5px]">
                    {message.attachments.map((a, i) => (
                      <div key={i} className="flex flex-wrap items-center justify-between gap-2 rounded border border-subtle bg-card p-2.5">
                        <span className="mono text-primary truncate max-w-xs">
                          <FileText size={12} className="inline mr-1.5 text-secondary" />
                          {escapeSuspiciousCharacters(a.filename || "unnamed")}
                        </span>
                        <span className="mono text-[11px] text-muted">
                          {a.content_type}
                          {a.size != null ? ` · ${Math.max(1, Math.round(a.size / 1024))} KB` : ""}
                        </span>
                      </div>
                    ))}
                  </div>
                </Accordion>
              )}

              {/* 6. Claims */}
              {components?.claims?.items?.length > 0 && (
                <Accordion title="6. Factual Claims" count={components.claims.items.length} countLabel="claims">
                  <div className="flex flex-col gap-2 text-[12.5px]">
                    {components.claims.items.map((cl, i) => (
                      <div key={i} className="rounded border border-subtle bg-card p-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="mono text-[11px] font-bold uppercase text-orange">{cl.verdict}</span>
                          <span className="mono text-[11px] text-muted">
                            credibility {cl.credibility}/100{cl.hidden ? " · hidden from you" : ""}
                          </span>
                        </div>
                        <p className="mt-1 text-primary">{escapeSuspiciousCharacters(cl.claim)}</p>
                      </div>
                    ))}
                  </div>
                </Accordion>
              )}
            </div>

            {/* Explanation & WhatsApp Warning */}
            <div className="rounded-lg border border-subtle bg-surface p-5">
              <h3 className="font-display text-[16px] font-bold text-primary mb-2 flex items-center gap-2">
                <MessageSquare size={17} className="text-red" />
                Plain Language Safety Brief
              </h3>
              <p className="text-[14px] leading-relaxed text-secondary mb-4">
                {report.explanation?.en || "No plain explanation generated."}
              </p>

              {report.explanation?.whatsapp_warning && (
                <div className="rounded-md border border-whatsapp/40 bg-[#25D366]/5 p-4">
                  <div className="flex items-center justify-between pb-2 mb-2 border-b border-whatsapp/20">
                    <span className="mono text-[11px] font-bold text-[#25D366] uppercase tracking-wider flex items-center gap-1.5">
                      <span>📱</span> WhatsApp Alert Copy
                    </span>
                    <button
                      type="button"
                      onClick={copyWhatsappText}
                      className="btn-ghost !py-1 !px-2.5 !text-[11.5px] !border-whatsapp/40 text-primary"
                    >
                      {copiedWhatsapp ? (
                        <>
                          <Check size={12} className="text-[#25D366]" /> Copied!
                        </>
                      ) : (
                        <>
                          <Copy size={12} /> Copy Alert
                        </>
                      )}
                    </button>
                  </div>
                  <p className="font-mono text-[12.5px] text-primary whitespace-pre-wrap leading-relaxed">
                    {escapeSuspiciousCharacters(report.explanation.whatsapp_warning)}
                  </p>
                </div>
              )}
            </div>

            {/* Latency & Audit Metadata */}
            <div className="rounded-md border border-subtle bg-card p-4 text-[11.5px] font-mono text-muted flex flex-wrap justify-between gap-3">
              <div className="flex items-center gap-3">
                <span>PIPELINE: {report.pipeline_version} · MODE: {report.mode}</span>
                <button type="button" onClick={downloadReport} className="btn-ghost !py-1 !px-2.5 !text-[11px]">
                  <FileText size={12} /> Download JSON
                </button>
              </div>
              {latency && (
                <div>
                  LATENCY: {latency.total}ms (Audit: {latency.per_stage?.audit || 0}ms)
                </div>
              )}
              {report.audit_head_hash && (
                <div className="truncate max-w-xs">
                  HASH: {report.audit_head_hash.slice(0, 16)}...
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
