import { motion } from "framer-motion";
import { ArrowUpRight, ExternalLink, Zap } from "lucide-react";
import Link from "next/link";

import Accordion from "@/components/Accordion";
import ConfidenceBand from "@/components/ConfidenceBand";
import { StanceBadge, TierBadge } from "@/components/HarmBadge";
import HonestUncertainty from "@/components/HonestUncertainty";
import MythVsFact from "@/components/MythVsFact";
import ShareCorrection from "@/components/ShareCorrection";
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
            {s.ref && <span className="mono text-[11px] font-medium text-red">[{s.ref}]</span>}
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
        <StanceBadge stance={s.stance} />
      </div>
    </a>
  );
}

function DetailRow({ label, children }) {
  return (
    <div className="flex flex-wrap justify-between gap-2 border-b border-subtle py-2 last:border-0">
      <span className="mono text-[11px] tracking-[1px] text-secondary">{label}</span>
      <span className="mono text-[12px] text-primary">{children}</span>
    </div>
  );
}

const pct = (x) => (x == null ? "—" : `${Math.round(x * 100)}%`);

/**
 * Truth Autopsy Report. Banner shows the confidence band only; raw numbers are under Details.
 * UNVERIFIED gets the calm "Honest uncertainty" section; every verdict gets the shareable correction.
 */
export default function VerdictCard({ result, compact = false, showRegistryLink = true }) {
  const v = verdictStyle(result.verdict);
  const unverified = result.verdict === "UNVERIFIED";
  const archive = result.is_seed;
  const seconds = result.processing_ms != null ? `${(result.processing_ms / 1000).toFixed(1)}s` : "ARCHIVE";
  const showLocal = result.summary_local && result.summary_local !== result.summary;
  const models = [...new Set((result.agents || []).map((a) => a.model).filter(Boolean))];
  const gated = unverified && result.model_verdict && result.model_verdict !== "UNVERIFIED";

  return (
    <motion.article
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ type: "spring", stiffness: 120, damping: 18, duration: 0.6 }}
      className={`overflow-hidden rounded-lg border border-subtle bg-card ${compact ? "" : "mt-6"}`}
    >
      <div
        className="flex min-h-[120px] items-center justify-between gap-4 px-5 py-5 sm:px-8"
        style={{ background: v.gradient, borderLeft: `4px solid ${v.color}` }}
      >
        <div className="min-w-0">
          <div className="mono mb-2 text-[11px] tracking-[3px] text-secondary">VERDICT</div>
          <VerdictWord word={v.label} color={v.color} />
        </div>
        <ConfidenceBand band={result.confidence_band || "low"} color={v.color} archive={archive} />
      </div>

      <div className="flex flex-col gap-6 p-5 sm:p-8">
        <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
          <Chip label="CLAIM TYPE" value={result.claim_type || "—"} color="#6EA2FF" />
          <Chip label="URGENCY" value={result.urgency || "—"} color={LEVEL_COLORS[result.urgency] || "#8888A0"} />
          <Chip label="HARM LEVEL" value={result.harm_level || "—"} color={LEVEL_COLORS[result.harm_level] || "#8888A0"} />
          <Chip label="TIME" value={seconds} color="#F0F0F5" />
        </div>

        <div>
          <SectionLabel>Claim analyzed</SectionLabel>
          <blockquote
            className="m-0 text-[15px] leading-relaxed text-secondary"
            style={{
              background: "var(--bg-surface)",
              borderLeft: `3px solid ${unverified ? "#8888A0" : "var(--accent-red)"}`,
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
            {result.harm_type && <span style={{ color: HARM_COLORS[result.harm_type] }}>HARM: {result.harm_type}</span>}
            {result.image_info?.label && (
              <span className="rounded border border-subtle px-1.5 text-secondary">{result.image_info.label.toUpperCase()}</span>
            )}
            {showRegistryLink && result.slug && result.is_public !== false && (
              <Link href={`/v/${result.slug}`} className="flex items-center gap-1 text-secondary hover:text-primary">
                PUBLIC RECORD /v/{result.slug} <ArrowUpRight size={11} />
              </Link>
            )}
          </div>
          {result.image_info?.cues?.length > 0 && (
            <div className="mt-3 text-[12.5px] text-secondary">
              <span className="mono text-[10px] tracking-[2px] text-muted">VISIBLE IN THE SCREENSHOT (NOT USED FOR THE VERDICT)</span>
              <ul className="m-0 mt-1 list-disc pl-5">
                {result.image_info.cues.map((cue) => (
                  <li key={cue}>{cue}</li>
                ))}
              </ul>
            </div>
          )}
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

        {unverified && <HonestUncertainty result={result} prominent />}

        {result.reasoning_chain?.length > 0 && (
          <Accordion title="Reasoning chain" count={result.reasoning_chain.length} countLabel="steps" defaultOpen={!compact && !unverified}>
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

        {!unverified && (result.evidence_gaps?.length > 0 || result.checks_to_do?.length > 0) && (
          <Accordion title="What is still missing" count={result.evidence_gaps?.length || 0} countLabel="gaps">
            <HonestUncertainty result={result} prominent={false} />
          </Accordion>
        )}

        {result.myth && result.fact && (
          <div>
            <SectionLabel>Myth vs fact</SectionLabel>
            <MythVsFact result={result} />
          </div>
        )}

        {result.correction && (
          <ShareCorrection
            correction={result.correction}
            localReply={result.whatsapp_reply}
            localLanguage={result.language_name}
            verdict={result.verdict}
          />
        )}

        {!archive && (
          <Accordion title="Details">
            <DetailRow label="CONFIDENCE">{pct(result.confidence)}</DetailRow>
            <DetailRow label="MODEL VERDICT">
              {result.model_verdict || "—"} {result.model_confidence != null && `(${pct(result.model_confidence)})`}
            </DetailRow>
            {gated && <DetailRow label="GATED TO">UNVERIFIED by the evidence check</DetailRow>}
            {result.harm_score != null && <DetailRow label="HARM SEVERITY">{result.harm_score} / 10</DetailRow>}
            {result.version > 1 && <DetailRow label="VERSION">v{result.version}</DetailRow>}
            {result.view_count != null && <DetailRow label="REGISTRY VIEWS">{result.view_count}</DetailRow>}
            {models.length > 0 && <DetailRow label="MODELS">{models.join(" · ")}</DetailRow>}
          </Accordion>
        )}
      </div>
    </motion.article>
  );
}
