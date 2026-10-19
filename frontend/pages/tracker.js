import Head from "next/head";
import { useCallback, useEffect, useState } from "react";
import { Bar, BarChart, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import LiveFeed from "@/components/LiveFeed";
import StatsBar from "@/components/StatsBar";
import VerdictModal from "@/components/VerdictModal";
import { getHistory, getStats } from "@/lib/api";
import { HARM_COLORS, VERDICTS } from "@/lib/theme";

function GlassTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const p = payload[0];
  const color = p.payload.color || p.color;
  return (
    <div className="glass rounded-md px-3 py-2" style={{ background: "rgba(17,17,24,0.92)" }}>
      <div className="mono text-[11px] tracking-[1px]" style={{ color }}>
        {p.payload.name}
      </div>
      <div className="font-display text-[18px] font-bold text-primary">{p.value}</div>
    </div>
  );
}

function ChartCard({ title, children }) {
  return (
    <section className="rounded-lg border border-subtle bg-card p-5">
      <h3 className="mono m-0 mb-4 text-[11.5px] font-medium tracking-[2px] text-secondary">{title}</h3>
      {children}
    </section>
  );
}

function VerdictDonut({ breakdown }) {
  const data = Object.entries(breakdown || {})
    .filter(([, n]) => n > 0)
    .map(([name, value]) => ({ name, value, color: VERDICTS[name]?.color }));
  const total = data.reduce((s, d) => s + d.value, 0);

  return (
    <ChartCard title="VERDICT BREAKDOWN">
      <div className="relative h-[210px]">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={data} dataKey="value" innerRadius={62} outerRadius={92} paddingAngle={3} stroke="none" isAnimationActive>
              {data.map((d) => (
                <Cell key={d.name} fill={d.color} />
              ))}
            </Pie>
            <Tooltip content={<GlassTooltip />} />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="font-display text-[28px] font-bold">{total}</span>
          <span className="mono text-[9.5px] tracking-[2px] text-secondary">VERDICTS</span>
        </div>
      </div>
      <ul className="m-0 mt-4 grid list-none grid-cols-2 gap-2 p-0">
        {data.map((d) => (
          <li key={d.name} className="mono flex items-center gap-2 text-[11.5px] text-secondary">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: d.color }} />
            {d.name}
            <span className="ml-auto text-primary">{total ? Math.round((d.value / total) * 100) : 0}%</span>
          </li>
        ))}
      </ul>
    </ChartCard>
  );
}

function HarmBars({ harms }) {
  const data = Object.entries(harms || {})
    .map(([name, value]) => ({ name, value, color: HARM_COLORS[name] }))
    .sort((a, b) => b.value - a.value);

  return (
    <ChartCard title="HARM CATEGORIES">
      <div className="h-[220px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16, top: 0, bottom: 0 }} barCategoryGap={8}>
            <XAxis type="number" hide allowDecimals={false} />
            <YAxis
              type="category"
              dataKey="name"
              width={100}
              tickLine={false}
              axisLine={false}
              tick={{ fill: "#8888A0", fontSize: 11, fontFamily: "JetBrains Mono, monospace" }}
            />
            <Tooltip content={<GlassTooltip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
            <Bar dataKey="value" radius={[0, 6, 6, 0]} background={{ fill: "rgba(255,255,255,0.025)", radius: 6 }}>
              {data.map((d) => (
                <Cell key={d.name} fill={d.color} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </ChartCard>
  );
}

export default function TrackerPage() {
  const [stats, setStats] = useState(null);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const [h, s] = await Promise.all([getHistory(20), getStats()]);
      setItems(h.items);
      setStats(s);
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, [refresh]);

  const close = useCallback(() => setSelected(null), []);

  return (
    <>
      <Head>
        <title>Live Tracker — NemesisAI</title>
      </Head>
      <StatsBar stats={stats} />

      <div className="mx-auto max-w-6xl px-4 pb-20 pt-8">
        {error && (
          <div className="mb-6 rounded-md p-4 text-[14px]" style={{ background: "rgba(255,45,45,0.06)", border: "1px solid rgba(255,45,45,0.3)" }}>
            {error}
          </div>
        )}
        <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
          <LiveFeed items={items} onSelect={setSelected} loading={loading} />
          <div className="flex flex-col gap-6">
            <VerdictDonut breakdown={stats?.verdict_breakdown} />
            <HarmBars harms={stats?.harm_categories} />
            {stats?.avg_seconds != null && (
              <div className="mono grid grid-cols-2 gap-3 text-center">
                <div className="rounded-md border border-subtle bg-card p-4">
                  <div className="font-display text-[22px] font-bold text-primary">{stats.avg_seconds}s</div>
                  <div className="text-[10px] tracking-[1.5px] text-secondary">AVG ANALYSIS</div>
                </div>
                <div className="rounded-md border border-subtle bg-card p-4">
                  <div className="font-display text-[22px] font-bold text-red">{stats.ultra_rate_pct}%</div>
                  <div className="text-[10px] tracking-[1.5px] text-secondary">ESCALATED TO ULTRA</div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <VerdictModal requestId={selected} onClose={close} />
    </>
  );
}
