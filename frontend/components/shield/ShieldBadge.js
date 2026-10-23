import { CheckCircle2, AlertTriangle, ShieldAlert, ShieldCheck, Shield } from "lucide-react";

export const SHIELD_COLORS = {
  SAFE: {
    color: "#00E676",
    bg: "rgba(0, 230, 118, 0.12)",
    border: "rgba(0, 230, 118, 0.4)",
    glow: "0 0 16px rgba(0, 230, 118, 0.25)",
    text: "#04140b",
    icon: ShieldCheck,
  },
  SUSPICIOUS: {
    color: "#FF6B00",
    bg: "rgba(255, 107, 0, 0.12)",
    border: "rgba(255, 107, 0, 0.4)",
    glow: "0 0 16px rgba(255, 107, 0, 0.25)",
    text: "#fff",
    icon: AlertTriangle,
  },
  DANGEROUS: {
    color: "#FF2D2D",
    bg: "rgba(255, 45, 45, 0.14)",
    border: "rgba(255, 45, 45, 0.45)",
    glow: "0 0 18px rgba(255, 45, 45, 0.3)",
    text: "#fff",
    icon: ShieldAlert,
  },
  UNKNOWN: {
    color: "#8888A0",
    bg: "rgba(136, 136, 160, 0.12)",
    border: "rgba(136, 136, 160, 0.3)",
    glow: "none",
    text: "#fff",
    icon: Shield,
  },
};

export default function ShieldBadge({ label = "SAFE", size = "md", showIcon = true, pulse = false }) {
  const norm = (label || "UNKNOWN").toUpperCase();
  const theme = SHIELD_COLORS[norm] || SHIELD_COLORS.UNKNOWN;
  const Icon = theme.icon;

  const isLg = size === "lg";
  const isSm = size === "sm";

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-mono font-bold tracking-[1px] rounded-full transition-all ${
        pulse && norm === "DANGEROUS" ? "animate-pulse" : ""
      }`}
      style={{
        background: theme.bg,
        color: theme.color,
        border: `1px solid ${theme.border}`,
        boxShadow: theme.glow,
        fontSize: isLg ? "13px" : isSm ? "10px" : "11px",
        padding: isLg ? "6px 14px" : isSm ? "2px 8px" : "4px 10px",
      }}
    >
      {showIcon && <Icon size={isLg ? 15 : isSm ? 11 : 13} className="shrink-0" />}
      <span>{norm}</span>
    </span>
  );
}

export function ActionBadge({ decision }) {
  const map = {
    ALLOW: { c: "#00E676", bg: "rgba(0,230,118,0.1)", b: "rgba(0,230,118,0.3)" },
    REQUIRE_APPROVAL: { c: "#FF6B00", bg: "rgba(255,107,0,0.1)", b: "rgba(255,107,0,0.3)" },
    BLOCK: { c: "#FF2D2D", bg: "rgba(255,45,45,0.1)", b: "rgba(255,45,45,0.3)" },
  };
  const d = map[decision] || { c: "#8888A0", bg: "rgba(136,136,160,0.1)", b: "rgba(136,136,160,0.2)" };

  return (
    <span
      className="mono inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold tracking-wider uppercase"
      style={{ color: d.c, background: d.bg, border: `1px solid ${d.b}` }}
    >
      {decision}
    </span>
  );
}
