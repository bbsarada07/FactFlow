import { motion } from "framer-motion";
import { ArrowRight, ExternalLink, Zap } from "lucide-react";
import Link from "next/link";

import HarmBadge, { VerdictBadge } from "@/components/HarmBadge";
import { EASE, HARM_COLORS, formatDate, verdictStyle } from "@/lib/theme";

function Pill({ children }) {
  return <span className="pill glass !shadow-none text-secondary">{children}</span>;
}

export default function IncidentCard({ incident, index }) {
  const accent = HARM_COLORS[incident.harm_type] || "#FF2D2D";
  const v = verdictStyle(incident.verdict);
  const run = incident.latest_run;
  const href = `/?claim=${encodeURIComponent(incident.forward_text)}&auto=true`;

  return (
    <motion.article
      initial={{ opacity: 0, y: 40 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.6, ease: EASE, delay: (index % 2) * 0.05 }}
      className="glass overflow-hidden rounded-lg"
      style={{ borderLeft: `3px solid ${accent}` }}
    >
      <div className="p-5 sm:p-8">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="m-0 font-display text-[24px] font-semibold leading-tight sm:text-[28px]">{incident.name}</h2>
            <div className="mono mt-1 text-[12px] text-secondary">
              {formatDate(incident.date)} · {incident.location}
            </div>
          </div>
          {incident.deaths > 0 ? (
            <span className="rounded-md px-3 py-1.5 font-display text-[14px] font-bold text-white" style={{ background: "#FF2D2D", boxShadow: "0 0 24px rgba(255,45,45,0.35)" }}>
              💀 {incident.deaths} Deaths
            </span>
          ) : (
            <span className="rounded-md px-3 py-1.5 font-display text-[14px] font-bold text-white" style={{ background: "#FF6B00" }}>
              ⚠️ High Impact
            </span>
          )}
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <Pill>Platform: {incident.platform}</Pill>
          {incident.spread_minutes != null && <Pill>Spread: {incident.spread_minutes} min</Pill>}
          {incident.fact_check_days != null && <Pill>Fact-check: {incident.fact_check_days} days</Pill>}
          <HarmBadge type={incident.harm_type} />
        </div>

        <p className="mt-5 text-[15px] leading-relaxed text-secondary">{incident.summary}</p>

        <div className="mt-6">
          <div className="mono mb-2 text-[11px] tracking-[2px] text-secondary">THE FORWARD THAT CAUSED IT</div>
          <div
            className="max-w-[560px] text-[14px] leading-relaxed text-primary"
            style={{ background: "#1A2C1A", borderRadius: "0 12px 12px 12px", borderLeft: "3px solid #25D366", padding: 16 }}
          >
            “{incident.forward_text}”
          </div>
          {incident.forward_is_reconstruction && (
            <div className="mt-1.5 text-[11.5px] italic text-muted">Representative reconstruction of the rumour as it was reported.</div>
          )}
        </div>

        <div className="mt-6 grid gap-4 md:grid-cols-[1fr_auto] md:items-end">
          <div>
            <div className="mono mb-2 text-[11px] tracking-[2px] text-secondary">WHAT WAS ACTUALLY TRUE</div>
            <p className="m-0 text-[14.5px] leading-relaxed text-primary">{incident.what_was_true}</p>
            <a
              href={incident.reference_url}
              target="_blank"
              rel="noopener noreferrer"
              className="mono mt-2 inline-flex items-center gap-1 text-[11.5px] text-muted hover:text-primary"
            >
              Read the record <ExternalLink size={11} />
            </a>
          </div>
          <div className="rounded-md border border-subtle bg-surface p-4 md:min-w-[260px]">
            <div className="mono mb-2 text-[10.5px] tracking-[2px] text-secondary">NEMESISAI VERDICT</div>
            <VerdictBadge verdict={run?.verdict || incident.verdict} size="lg" />
            <div className="mono mt-3 text-[12px] leading-relaxed text-secondary">
              {run ? (
                <>
                  Flagged in <span style={{ color: v.color }}>{run.seconds}s</span>
                  {run.confidence != null && <> · {Math.round(run.confidence * 100)}% confidence</>}
                  {run.used_ultra && (
                    <span className="ml-1 inline-flex items-center gap-0.5 text-red">
                      · <Zap size={10} /> ULTRA
                    </span>
                  )}
                </>
              ) : (
                "Not yet run live — run it to measure response time."
              )}
            </div>
          </div>
        </div>
      </div>

      <Link
        href={href}
        className="flex w-full items-center justify-center gap-2 py-4 font-display text-[15px] font-semibold tracking-[1px] text-white transition-all hover:brightness-110"
        style={{ background: "#FF2D2D" }}
      >
        RUN THIS CLAIM NOW <ArrowRight size={17} />
      </Link>
    </motion.article>
  );
}
