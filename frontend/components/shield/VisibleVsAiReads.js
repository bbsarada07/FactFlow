import { useState } from "react";
import { Eye, Bot, AlertTriangle, ShieldAlert, Info, HelpCircle } from "lucide-react";
import { escapeSuspiciousCharacters } from "@/lib/shieldApi";
import EmailSandboxedIframe from "@/components/shield/EmailSandboxedIframe";

export default function VisibleVsAiReads({ visibleVsRaw, hiddenContent }) {
  const visibleText = visibleVsRaw?.visible_text || "";
  const rawText = visibleVsRaw?.raw_text || "";
  const diffItems = visibleVsRaw?.diff || [];
  const findings = hiddenContent?.findings || [];

  const [activeFindingTooltip, setActiveFindingTooltip] = useState(null);

  // Helper to find explanation by finding ID
  const getFinding = (hcId) => findings.find((f) => f.id === hcId);

  // Build highlighted tokens for the AI raw text view
  const renderHighlightedRawText = () => {
    if (!diffItems.length) {
      return (
        <span className="text-secondary whitespace-pre-wrap">
          {escapeSuspiciousCharacters(rawText || "No text extracted")}
        </span>
      );
    }

    // Match each diff item in rawText
    const renderedParts = [];
    let remaining = rawText;
    let keyIdx = 0;

    for (const diff of diffItems) {
      if (!diff.text) continue;
      const idx = remaining.indexOf(diff.text);
      if (idx === -1) continue;

      if (idx > 0) {
        renderedParts.push(
          <span key={`plain-${keyIdx++}`} className="text-secondary whitespace-pre-wrap">
            {escapeSuspiciousCharacters(remaining.slice(0, idx))}
          </span>
        );
      }

      const matchingFinding = getFinding(diff.hc_id);
      const isCritical = matchingFinding?.severity === "critical" || matchingFinding?.instruction_like;

      renderedParts.push(
        <mark
          key={`diff-${keyIdx++}`}
          onClick={() =>
            setActiveFindingTooltip(
              activeFindingTooltip === diff.hc_id ? null : diff.hc_id
            )
          }
          className={`cursor-pointer rounded px-1.5 py-0.5 mx-0.5 inline-block font-mono font-medium text-[12.5px] transition-all border ${
            isCritical
              ? "bg-red/25 text-red border-red/60 shadow-[0_0_12px_rgba(255,45,45,0.3)]"
              : "bg-orange/20 text-orange border-orange/50"
          }`}
          title={matchingFinding?.explanation_en || `Hidden content finding ${diff.hc_id}`}
        >
          <span className="underline underline-offset-2 decoration-dotted">
            {escapeSuspiciousCharacters(diff.text)}
          </span>
          <span className="ml-1.5 rounded bg-black/50 px-1 py-0.2 text-[9.5px] font-bold uppercase tracking-wider">
            {diff.hc_id}
          </span>
        </mark>
      );

      remaining = remaining.slice(idx + diff.text.length);
    }

    if (remaining.length > 0) {
      renderedParts.push(
        <span key={`plain-${keyIdx++}`} className="text-secondary whitespace-pre-wrap">
          {escapeSuspiciousCharacters(remaining)}
        </span>
      );
    }

    return renderedParts;
  };

  return (
    <div className="rounded-lg border border-subtle bg-surface overflow-hidden">
      <div className="border-b border-subtle bg-card p-4 sm:p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="flex items-center gap-2">
              <ShieldAlert size={18} className="text-red" />
              <h3 className="font-display text-[16px] font-bold text-primary">
                What You See vs What the AI Reads
              </h3>
            </div>
            <p className="mt-1 text-[12.5px] text-secondary">
              Discrepancy inspection: Threat actors hide prompt injections or tracking payloads inside CSS, zero-width characters, comments, and alt text.
            </p>
          </div>
          {diffItems.length > 0 && (
            <span className="pill bg-red/15 border-red/40 text-red text-[10.5px]">
              {diffItems.length} HIDDEN PAYLOAD(S) DETECTED
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-subtle">
        {/* Left Column: What You See */}
        <div className="p-4 sm:p-5 flex flex-col">
          <div className="flex items-center justify-between pb-3 mb-3 border-b border-subtle">
            <div className="flex items-center gap-2">
              <Eye size={16} className="text-green" />
              <span className="mono text-[11.5px] font-bold uppercase tracking-[1.5px] text-primary">
                What You See (Human View)
              </span>
            </div>
            <span className="mono text-[10px] text-muted">RENDERED OUTPUT</span>
          </div>

          <div className="rounded-md border border-subtle bg-card p-4 min-h-[160px] text-[13.5px] leading-relaxed text-primary">
            {visibleText ? (
              <p className="whitespace-pre-wrap">{escapeSuspiciousCharacters(visibleText)}</p>
            ) : (
              <span className="text-muted italic">No visible human text parsed</span>
            )}
          </div>
        </div>

        {/* Right Column: What the AI Reads */}
        <div className="p-4 sm:p-5 flex flex-col bg-card/40">
          <div className="flex items-center justify-between pb-3 mb-3 border-b border-subtle">
            <div className="flex items-center gap-2">
              <Bot size={16} className="text-red" />
              <span className="mono text-[11.5px] font-bold uppercase tracking-[1.5px] text-primary">
                What the AI Reads (Raw Stream)
              </span>
            </div>
            <span className="mono text-[10px] text-red font-semibold">
              {diffItems.length ? "HIGHLIGHTED ANOMALIES" : "CLEAN"}
            </span>
          </div>

          <div className="rounded-md border border-subtle bg-base p-4 min-h-[160px] text-[13.5px] leading-relaxed">
            {renderHighlightedRawText()}
          </div>
        </div>
      </div>

      {/* Findings Breakdown Table / Cards */}
      {findings.length > 0 && (
        <div className="border-t border-subtle bg-card p-4 sm:p-5">
          <div className="flex items-center gap-2 mb-3">
            <Info size={15} className="text-secondary" />
            <span className="mono text-[11px] font-bold tracking-[1.5px] uppercase text-secondary">
              Hidden Content Findings Details
            </span>
          </div>

          <div className="flex flex-col gap-2.5">
            {findings.map((f) => (
              <div
                key={f.id}
                className={`rounded-md border p-3 text-[12.5px] transition-all ${
                  f.severity === "critical"
                    ? "border-red/40 bg-red/5"
                    : "border-orange/40 bg-orange/5"
                }`}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="mono font-bold text-red text-[11px] bg-red/10 border border-red/40 px-1.5 py-0.5 rounded">
                      {f.id}
                    </span>
                    <span className="font-semibold text-primary">{f.type}</span>
                    <span className="mono text-[10.5px] text-muted">@{f.location}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    {f.instruction_like && (
                      <span className="pill text-[9.5px] bg-red/20 border-red/60 text-red font-bold">
                        ⚡ INSTRUCTS AI (EXPLOIT)
                      </span>
                    )}
                    <span
                      className={`mono text-[10px] font-bold px-2 py-0.5 rounded uppercase ${
                        f.severity === "critical"
                          ? "bg-red text-white"
                          : "bg-orange text-white"
                      }`}
                    >
                      {f.severity}
                    </span>
                  </div>
                </div>

                <p className="mt-2 text-primary font-mono text-[12px] bg-base p-2 rounded border border-subtle whitespace-pre-wrap">
                  {escapeSuspiciousCharacters(f.hidden_text)}
                </p>

                <p className="mt-1.5 text-secondary text-[12px] flex items-center gap-1.5">
                  <HelpCircle size={13} className="text-secondary shrink-0" />
                  <span>{f.explanation_en}</span>
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
