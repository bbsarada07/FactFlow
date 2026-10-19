import { AnimatePresence, motion } from "framer-motion";
import { Check, Minus, X } from "lucide-react";

import { EASE, formatClock } from "@/lib/theme";

export const AGENT_DEFAULTS = [
  { index: 0, name: "ORCHESTRATOR", tier: "NANO", role: "Routes and controls" },
  { index: 1, name: "INTAKE & TRIAGE", tier: "NANO", role: "Extracts core claim" },
  { index: 2, name: "SOURCE TRACER", tier: "NANO", role: "Finds evidence" },
  { index: 3, name: "DEEP REASONING", tier: "ULTRA", role: "Multi-hop analysis" },
  { index: 4, name: "EXPLAINER", tier: "NANO", role: "Translates verdict" },
  { index: 5, name: "HARM ASSESSOR", tier: "NANO", role: "Risk classification" },
].map((a) => ({ ...a, status: "waiting", preview: "", model: null, ms: 0 }));

function StatusIcon({ status }) {
  if (status === "running") {
    return (
      <span className="relative flex h-5 w-5 items-center justify-center">
        <span className="h-2.5 w-2.5 rounded-full bg-red" style={{ animation: "ring-pulse 1.2s ease-out infinite" }} />
      </span>
    );
  }
  if (status === "complete") {
    return (
      <motion.span
        initial={{ scale: 0 }}
        animate={{ scale: [0, 1.25, 1] }}
        transition={{ duration: 0.45, ease: "easeOut" }}
        className="flex h-5 w-5 items-center justify-center rounded-full"
        style={{ background: "rgba(0,230,118,0.15)", border: "1px solid rgba(0,230,118,0.5)" }}
      >
        <Check size={12} strokeWidth={3} className="text-green" />
      </motion.span>
    );
  }
  if (status === "failed") {
    return (
      <span
        className="flex h-5 w-5 items-center justify-center rounded-full"
        style={{ background: "rgba(255,45,45,0.15)", border: "1px solid rgba(255,45,45,0.5)" }}
      >
        <X size={12} strokeWidth={3} className="text-red" />
      </span>
    );
  }
  if (status === "skipped") {
    return (
      <span className="flex h-5 w-5 items-center justify-center rounded-full border border-active">
        <Minus size={12} className="text-muted" />
      </span>
    );
  }
  return <span className="mx-[5px] block h-2.5 w-2.5 rounded-full border border-muted" />;
}

function ModelTag({ tier, model }) {
  const ultra = tier === "ULTRA";
  return (
    <span
      title={model || (ultra ? "Deep model" : "Fast model")}
      className="mono shrink-0 rounded px-1.5 py-0.5 text-[9.5px] font-medium tracking-[1px]"
      style={
        ultra
          ? { background: "#FF2D2D", color: "#fff" }
          : { background: "rgba(41,121,255,0.14)", color: "#6EA2FF", border: "1px solid rgba(41,121,255,0.35)" }
      }
    >
      {ultra ? "⚡ULTRA" : "NANO"}
    </span>
  );
}

function AgentRow({ agent, i }) {
  const ultra = agent.tier === "ULTRA";
  const running = agent.status === "running";
  const dim = agent.status === "waiting" || agent.status === "skipped";

  return (
    <motion.li
      initial={{ opacity: 0, x: -24 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.4, delay: i * 0.1, ease: EASE }}
      className="relative overflow-hidden rounded-md px-3 py-3 sm:px-4"
      style={{
        border: `1px solid ${ultra ? "rgba(255,45,45,0.3)" : running ? "var(--border-active)" : "transparent"}`,
        background: ultra ? "rgba(255,45,45,0.03)" : running ? "var(--bg-hover)" : "transparent",
      }}
    >
      {running && <span className="scanline" />}
      <div className="relative flex flex-wrap items-center gap-x-3 gap-y-1.5 sm:flex-nowrap">
        <StatusIcon status={agent.status} />
        <span className="mono w-3 text-[12px] text-muted">{agent.index}</span>
        <span
          className="w-[132px] shrink-0 font-display text-[13px] font-semibold tracking-[0.5px] sm:w-[150px]"
          style={{ color: dim ? "var(--text-muted)" : "var(--text-primary)" }}
        >
          {agent.name}
        </span>
        <ModelTag tier={agent.tier} model={agent.model} />
        <div className="min-w-0 basis-full pl-[52px] sm:basis-auto sm:flex-1 sm:pl-2">
          <AnimatePresence mode="wait">
            {running ? (
              <motion.div
                key="running"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="flex min-w-0 items-center gap-2"
              >
                <span className="mono shrink-0 text-[11px] tracking-[1px] text-red">PROCESSING</span>
                <span className="truncate text-[12.5px] text-secondary">{agent.preview}</span>
              </motion.div>
            ) : agent.preview ? (
              <motion.p
                key={`done-${agent.status}`}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35 }}
                className="truncate text-[12.5px]"
                title={agent.preview}
                style={{ color: agent.status === "failed" ? "#FF6B6B" : dim ? "var(--text-muted)" : "var(--text-secondary)" }}
              >
                {agent.status === "skipped" ? "SKIPPED — " : ""}
                {agent.preview}
              </motion.p>
            ) : (
              <motion.p key="role" className="truncate text-[12.5px] text-muted">
                {agent.role}
              </motion.p>
            )}
          </AnimatePresence>
        </div>
        {agent.ms > 0 && <span className="mono hidden shrink-0 text-[10.5px] text-muted md:inline">{(agent.ms / 1000).toFixed(1)}s</span>}
      </div>
    </motion.li>
  );
}

export default function AgentProgress({ agents, progress, elapsedMs, phase }) {
  const done = phase === "done";
  const failed = phase === "error";

  return (
    <motion.section
      initial={{ opacity: 0, height: 0, y: -10 }}
      animate={{ opacity: 1, height: "auto", y: 0 }}
      transition={{ duration: 0.5, ease: EASE }}
      className="mt-6 overflow-hidden rounded-lg border border-subtle bg-surface"
      aria-live="polite"
    >
      <div className="p-5 sm:p-6">
        <div className="mb-4 flex items-center justify-between">
          <span className="mono flex items-center gap-2 text-[12px] font-medium tracking-[2px]" style={{ color: done ? "#00E676" : "#FF2D2D" }}>
            {!done && !failed && <span className="live-dot" />}
            {done ? "ANALYSIS COMPLETE" : failed ? "ANALYSIS HALTED" : "ANALYZING CLAIM"}
          </span>
          <span className="mono text-[13px] text-secondary">{formatClock(elapsedMs)}</span>
        </div>

        <div className="relative mb-5 h-[2px] w-full rounded-full bg-subtle">
          <motion.div
            className="absolute inset-y-0 left-0 rounded-full"
            style={{ background: "linear-gradient(90deg, #FF2D2D, #2979FF, #00E676)" }}
            initial={{ width: 0 }}
            animate={{ width: `${Math.max(progress, 2)}%` }}
            transition={{ duration: 0.6, ease: EASE }}
          >
            {!done && (
              <span
                className="absolute -right-1 -top-[3px] h-2 w-2 rounded-full bg-white"
                style={{ boxShadow: "0 0 12px 3px rgba(255,255,255,0.8), 0 0 24px 6px rgba(41,121,255,0.6)" }}
              />
            )}
          </motion.div>
        </div>

        <ol className="flex flex-col gap-1">
          {agents.map((a, i) => (
            <AgentRow key={a.index} agent={a} i={i} />
          ))}
        </ol>
      </div>
    </motion.section>
  );
}
