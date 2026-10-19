import { HARM_COLORS, LEVEL_COLORS, TIER_COLORS, verdictStyle } from "@/lib/theme";

export function VerdictBadge({ verdict, size = "sm" }) {
  const s = verdictStyle(verdict);
  const big = size === "lg";
  return (
    <span
      className="inline-flex items-center justify-center rounded-md font-display font-bold tracking-[1px]"
      style={{
        background: s.color,
        color: s.text,
        fontSize: big ? 18 : 10.5,
        padding: big ? "8px 18px" : "3px 8px",
        minWidth: big ? 0 : 92,
        boxShadow: big ? `0 0 30px ${s.soft}` : "none",
      }}
    >
      {s.label}
    </span>
  );
}

export default function HarmBadge({ type, level }) {
  if (!type) return null;
  const color = HARM_COLORS[type] || HARM_COLORS.NONE;
  return (
    <span
      className="pill"
      style={{ color, background: `${color}14`, border: `1px solid ${color}40` }}
      title={level ? `${type} harm · ${level}` : `${type} harm`}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {type === "NONE" ? "NO HARM" : type}
      {level && <span style={{ color: LEVEL_COLORS[level] || color, opacity: 0.85 }}>· {level}</span>}
    </span>
  );
}

export function TierBadge({ tier }) {
  const color = TIER_COLORS[tier] || TIER_COLORS[3];
  return (
    <span
      className="pill font-semibold"
      style={{ color, border: `1px solid ${color}55`, background: `${color}12`, padding: "2px 8px", fontSize: 10 }}
    >
      TIER {tier}
    </span>
  );
}

export function StanceBadge({ stance }) {
  const map = {
    REFUTES: { c: "#FF2D2D", t: "REFUTES CLAIM" },
    SUPPORTS: { c: "#00E676", t: "SUPPORTS CLAIM" },
    NEUTRAL: { c: "#8888A0", t: "CONTEXT" },
  };
  const s = map[stance] || map.NEUTRAL;
  return (
    <span className="mono text-[10px] tracking-[1px]" style={{ color: s.c }}>
      {s.t}
    </span>
  );
}
