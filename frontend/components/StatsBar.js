import CountUp from "react-countup";

function Stat({ value, suffix = "", label, sub }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center px-2 py-4 text-center sm:py-5">
      <div className="font-display text-[28px] font-bold leading-none text-red sm:text-[40px]" style={{ textShadow: "0 0 30px rgba(255,45,45,0.35)" }}>
        {value == null ? "—" : <CountUp end={value} duration={1.6} separator="," preserveValue />}
        {value != null && suffix}
      </div>
      <div className="mt-2 text-[11px] font-semibold uppercase tracking-[1.5px] text-secondary sm:text-[12px]">{label}</div>
      {sub && <div className="mono mt-0.5 text-[10.5px] text-muted">{sub}</div>}
    </div>
  );
}

export default function StatsBar({ stats }) {
  return (
    <div
      className="sticky z-30 border-b border-subtle bg-surface"
      style={{ top: "var(--nav-height)", background: "rgba(13,13,18,0.92)", backdropFilter: "blur(16px)" }}
    >
      <div className="mx-auto flex max-w-6xl divide-x divide-[var(--border-subtle)]">
        <Stat value={stats?.claims_today} label="Claims today" sub={stats ? `${stats.total_claims.toLocaleString()} all-time` : null} />
        <Stat value={stats?.false_or_misleading_pct} suffix="%" label="False / misleading" sub="share of all verdicts" />
        <Stat value={stats?.critical_threats} label="Critical threats" sub="harm level critical" />
      </div>
    </div>
  );
}
