import { motion } from "framer-motion";
import { Check, Copy, ExternalLink, Zap } from "lucide-react";
import { useState } from "react";
import toast from "react-hot-toast";

import Accordion from "@/components/Accordion";
import ConfidenceRing from "@/components/ConfidenceRing";
import { StanceBadge, TierBadge } from "@/components/HarmBadge";
import MythVsFact from "@/components/MythVsFact";
import { HARM_COLORS, LEVEL_COLORS, TIER_COLORS, verdictStyle } from "@/lib/theme";

function VerdictWord({ word, color }) {
  return (
    <h2 className="font-display text-[44px] font-bold leading-none tracking-tight sm:text-[64px]" style={{ color }} aria-label={word}>
      {word.split("").map((ch, i) => (
        <motion.span
          key={i}
          aria-hidden="true"
          className="inline-block"
          initial={{ opacity: 0, y: 18, filter: "blur(6px)" }}
          animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
          transition={{ delay: 0.25 + i * 0.05, duration: 0.4 }}
        >
          {ch}
        </motion.span>
      ))}
    </h2>
  );
}

function Chip({ label, value, color }) {
  return (
    <div className="glass rounded-md px-4 py-3" style={{ borderColor: `${color}40`, boxShadow: "none" }}>
      <div className="mono text-[9.5px] tracking-[2px] text-secondary">{label}</div>
      <div className="mono mt-1 truncate text-[13px] font-medium" style={{ color }}>
        {value}
      </div>
    </div>
  );
}

function SectionLabel({ children }) {
  return <div className="mono mb-3 text-[11px] uppercase tracking-[2px] text-secondary">{children}</div>;
}

function WhatsAppReply({ text }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Clipboard access was blocked by the browser");
    }
  }

  return (
    <div className="rounded-md p-5" style={{ background: "rgba(37,211,102,0.05)", border: "1px solid rgba(37,211,102,0.15)" }}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="#25D366" aria-hidden="true">
            <path d="M17.47 14.38c-.3-.15-1.75-.86-2.02-.96-.27-.1-.47-.15-.67.15-.2.3-.77.96-.94 1.16-.17.2-.35.22-.64.07-.3-.15-1.25-.46-2.38-1.47-.88-.78-1.48-1.75-1.65-2.05-.17-.3-.02-.46.13-.6.13-.14.3-.35.45-.52.15-.18.2-.3.3-.5.1-.2.05-.37-.03-.52-.07-.15-.67-1.6-.92-2.2-.24-.58-.49-.5-.67-.5h-.57c-.2 0-.52.07-.8.37-.27.3-1.04 1.02-1.04 2.48 0 1.46 1.07 2.88 1.21 3.07.15.2 2.1 3.2 5.08 4.49.71.3 1.27.49 1.7.63.72.23 1.37.2 1.88.12.58-.09 1.75-.72 2-1.41.25-.7.25-1.29.17-1.41-.07-.13-.27-.2-.57-.35M12.05 21.5h-.01a9.4 9.4 0 0 1-4.8-1.32l-.34-.2-3.56.94.95-3.48-.23-.36a9.4 9.4 0 0 1-1.44-5.02c0-5.2 4.24-9.44 9.45-9.44a9.4 9.4 0 0 1 6.68 2.77 9.38 9.38 0 0 1 2.76 6.68c0 5.21-4.23 9.44-9.44 9.44M20.08 3.9A11.3 11.3 0 0 0 12.05.58C5.79.58.69 5.68.69 11.94c0 2 .52 3.96 1.52 5.68L.6 23.5l6.02-1.58a11.33 11.33 0 0 0 5.43 1.38h.01c6.26 0 11.36-5.1 11.36-11.36 0-3.03-1.18-5.89-3.33-8.03" />
          </svg>
          <span className="label !text-[#25D366]">Ready to correct this forward?</span>
        </div>
        <button
          type="button"
          onClick={copy}
          className="mono flex shrink-0 items-center gap-1.5 rounded-full px-3.5 py-1.5 text-[11px] font-medium tracking-[1px] transition-all"
          style={{
            background: copied ? "#25D366" : "rgba(37,211,102,0.12)",
            color: copied ? "#04140b" : "#25D366",
            border: "1px solid rgba(37,211,102,0.35)",
          }}
        >
          {copied ? <Check size={13} /> : <Copy size={13} />}
          {copied ? "COPIED ✓" : "COPY"}
        </button>
      </div>
      <p className="mono whitespace-pre-wrap text-[13px] leading-relaxed text-primary">{text}</p>
    </div>
  );
}

function SourceCard({ s }) {
  const tierColor = TIER_COLORS[s.tier] || TIER_COLORS[3];
  return (
    <a
      href={s.url}
      target="_blank"
      rel="noopener noreferrer"
      className="group block rounded-md border border-subtle bg-card p-4 transition-all hover:border-active hover:bg-hover"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate font-semibold text-primary">{s.name}</span>
            <TierBadge tier={s.tier} />
            {s.rating && (
              <span className="mono rounded border border-active px-1.5 py-0.5 text-[10px] text-secondary">RATED: {s.rating}</span>
            )}
          </div>
          <div className="mono mt-1 truncate text-[11.5px] text-muted">{s.url}</div>
        </div>
        <ExternalLink size={14} className="mt-1 shrink-0 text-muted transition-colors group-hover:text-primary" />
      </div>
      {s.title && <p className="mt-2 text-[13.5px] text-primary">{s.title}</p>}
      {s.snippet && <p className="mt-1 line-clamp-2 text-[12.5px] text-secondary">{s.snippet}</p>}
      <div className="mt-3 flex items-center gap-3">
        <div className="h-[3px] flex-1 overflow-hidden rounded-full bg-subtle">
          <motion.div
            className="h-full rounded-full"
            style={{ background: tierColor }}
            initial={{ width: 0 }}
            whileInView={{ width: `${Math.round(s.credibility * 100)}%` }}
            viewport={{ once: true }}
            transition={{ duration: 0.8 }}
          />
        </div>
        <span className="mono text-[10.5px] text-secondary">{Math.round(s.credibility * 100)}% CRED</span>
        <StanceBadge stance={s.stance} />
      </div>
    </a>
  );
}

export default function VerdictCard({ result, compact = false }) {
  const v = verdictStyle(result.verdict);
  const seconds = result.processing_ms != null ? `${(result.processing_ms / 1000).toFixed(1)}s` : "ARCHIVE";
  const showLocal = result.summary_local && result.summary_local !== result.summary;

  return (
    <motion.article
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ type: "spring", stiffness: 120, damping: 18, duration: 0.6 }}
      className={`overflow-hidden rounded-lg border border-subtle bg-card ${compact ? "" : "mt-6"}`}
    >
      {/* Verdict banner */}
      <div
        className="flex min-h-[120px] items-center justify-between gap-4 px-5 py-5 sm:px-8"
        style={{ background: v.gradient, borderLeft: `4px solid ${v.color}` }}
      >
        <div className="min-w-0">
          <div className="mono mb-2 text-[11px] tracking-[3px] text-secondary">VERDICT</div>
          <VerdictWord word={v.label} color={v.color} />
        </div>
        <ConfidenceRing value={result.confidence} color={v.color} />
      </div>

      <div className="flex flex-col gap-6 p-5 sm:p-8">
        <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
          <Chip label="CLAIM TYPE" value={result.claim_type || "—"} color="#6EA2FF" />
          <Chip label="URGENCY" value={result.urgency || "—"} color={LEVEL_COLORS[result.urgency] || "#8888A0"} />
          <Chip
            label="HARM LEVEL"
            value={result.harm_level ? `${result.harm_level}${result.harm_score != null ? ` · ${result.harm_score}/10` : ""}` : "—"}
            color={LEVEL_COLORS[result.harm_level] || "#8888A0"}
          />
          <Chip label="TIME" value={seconds} color="#F0F0F5" />
        </div>

        <div>
          <SectionLabel>Claim analyzed</SectionLabel>
          <blockquote
            className="m-0 text-[15px] leading-relaxed text-secondary"
            style={{
              background: "var(--bg-surface)",
              borderLeft: "3px solid var(--accent-red)",
              padding: "16px 20px",
              borderRadius: "0 var(--radius-md) var(--radius-md) 0",
            }}
          >
            {result.claim}
          </blockquote>
          <div className="mono mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
            {result.language_name && <span>LANG: {result.language_name.toUpperCase()}</span>}
            {result.input_type && <span>INPUT: {result.input_type.toUpperCase()}</span>}
            {result.used_ultra && (
              <span className="flex items-center gap-1 text-red">
                <Zap size={11} /> ESCALATED TO ULTRA
              </span>
            )}
            {result.cached_from && <span>FROM VERDICT CACHE</span>}
            {result.harm_type && (
              <span style={{ color: HARM_COLORS[result.harm_type] }}>HARM: {result.harm_type}</span>
            )}
          </div>
        </div>

        <div>
          <SectionLabel>What we found</SectionLabel>
          <p className="text-[16px] leading-relaxed text-primary">{result.summary}</p>
          {showLocal && (
            <p className="mt-3 rounded-md border border-subtle bg-surface p-4 text-[15px] leading-relaxed text-primary">
              <span className="mono mb-1 block text-[10px] tracking-[2px] text-secondary">
                IN {(result.language_name || "YOUR LANGUAGE").toUpperCase()}
              </span>
              {result.summary_local}
            </p>
          )}
          {result.harm_rationale && <p className="mt-3 text-[13.5px] text-secondary">⚠ {result.harm_rationale}</p>}
        </div>

        {result.reasoning_chain?.length > 0 && (
          <Accordion title="Reasoning chain" count={result.reasoning_chain.length} countLabel="steps" defaultOpen={!compact}>
            <ol className="relative m-0 flex list-none flex-col gap-4 p-0">
              {result.reasoning_chain.map((step, i) => (
                <li key={i} className="relative flex gap-4">
                  {i < result.reasoning_chain.length - 1 && (
                    <span
                      className="absolute left-[13px] top-7 h-[calc(100%-4px)] border-l border-dashed"
                      style={{ borderColor: "rgba(255,45,45,0.45)" }}
                    />
                  )}
                  <span
                    className="mono relative z-[1] flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] text-red"
                    style={{ background: "rgba(255,45,45,0.08)", border: "1px solid rgba(255,45,45,0.4)" }}
                  >
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <p className="mono pt-1 text-[13px] leading-relaxed text-secondary">{step.replace(/^\s*(step\s*)?\d+[.:)]\s*/i, "")}</p>
                </li>
              ))}
            </ol>
            {result.contradictions?.length > 0 && (
              <div className="mt-6">
                <div className="mono mb-2 text-[10.5px] tracking-[2px] text-orange">CONTRADICTIONS &amp; MANIPULATION MARKERS</div>
                <ul className="m-0 flex list-none flex-col gap-2 p-0">
                  {result.contradictions.map((c, i) => (
                    <li key={i} className="flex gap-2 text-[13px] text-secondary">
                      <span className="text-orange">▸</span>
                      {c}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Accordion>
        )}

        {result.sources?.length > 0 && (
          <Accordion title="Sources found" count={result.sources.length} countLabel="sources">
            <div className="flex flex-col gap-2.5">
              {result.sources.map((s) => (
                <SourceCard key={s.url} s={s} />
              ))}
            </div>
          </Accordion>
        )}

        {result.myth && result.fact && (
          <div>
            <SectionLabel>Myth vs fact</SectionLabel>
            <MythVsFact result={result} />
          </div>
        )}

        {result.whatsapp_reply && <WhatsAppReply text={result.whatsapp_reply} />}
      </div>
    </motion.article>
  );
}
