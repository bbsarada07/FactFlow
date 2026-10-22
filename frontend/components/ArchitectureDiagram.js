import { useEffect, useState } from "react";

const NODES = {
  in: { label: "INPUT", sub: "text · url · image", kind: "io" },
  0: { label: "ORCHESTRATOR", sub: "0 · router", kind: "nano" },
  1: { label: "INTAKE", sub: "1 · NANO", kind: "nano" },
  2: { label: "SOURCE TRACER", sub: "2 · NANO", kind: "nano" },
  3: { label: "DEEP REASONING", sub: "3 · ⚡ULTRA", kind: "ultra" },
  4: { label: "EXPLAINER", sub: "4 · NANO", kind: "nano" },
  5: { label: "HARM ASSESSOR", sub: "5 · NANO", kind: "nano" },
  out: { label: "VERDICT", sub: "report · reply", kind: "io" },
};

const EDGES = [
  ["in", 0],
  [0, 1],
  [1, 2],
  [2, 3, "ultra"],
  [2, 4, "skip"],
  [2, 5, "skip"],
  [3, 4],
  [3, 5],
  [4, "out"],
  [5, "out"],
];

// Active sequence; 4 and 5 run in parallel.
const SEQUENCE = [["in"], [0], [1], [2], [3], [4, 5], ["out"]];

const LAYOUTS = {
  wide: {
    viewBox: "0 0 1100 420",
    pos: { in: [70, 210], 0: [225, 210], 1: [385, 210], 2: [545, 210], 3: [735, 95], 4: [915, 160], 5: [915, 300], out: [1036, 230] },
    curve: "h",
    evidence: { x: 545, y: 330 },
    condition: { x: 640, y: 128 },
  },
  tall: {
    viewBox: "0 0 360 880",
    pos: { in: [180, 40], 0: [180, 140], 1: [180, 240], 2: [180, 340], 3: [180, 480], 4: [92, 630], 5: [268, 630], out: [180, 790] },
    curve: "v",
    evidence: null,
    condition: { x: 268, y: 415 },
  },
};

function size(kind) {
  if (kind === "ultra") return [170, 70];
  if (kind === "io") return [116, 50];
  return [140, 56];
}

function path(a, b, curve, kind) {
  const [x1, y1] = a;
  const [x2, y2] = b;
  if (curve === "h") {
    const dx = (x2 - x1) * 0.5;
    return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
  }
  if (kind === "skip") {
    const side = x2 < x1 ? -1 : 1;
    return `M${x1},${y1} C${x1 + side * 150},${y1 + 60} ${x2 + side * 40},${y2 - 120} ${x2},${y2}`;
  }
  const dy = (y2 - y1) * 0.5;
  return `M${x1},${y1} C${x1},${y1 + dy} ${x2},${y2 - dy} ${x2},${y2}`;
}

function Diagram({ layout, active }) {
  const L = LAYOUTS[layout];
  const isActive = (id) => active.includes(id) || active.includes(Number(id));

  return (
    <svg viewBox={L.viewBox} className="h-auto w-full" role="img" aria-label="FactFlow six-agent pipeline">
      <defs>
        <filter id={`glow-${layout}`} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="8" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      {EDGES.map(([from, to, kind]) => {
        const hot = isActive(to);
        const color = kind === "ultra" ? "#FF2D2D" : hot ? "#2979FF" : "#2A2A3A";
        return (
          <path
            key={`${from}-${to}`}
            d={path(L.pos[from], L.pos[to], L.curve, kind)}
            fill="none"
            stroke={color}
            strokeOpacity={kind === "skip" && !hot ? 0.55 : 1}
            strokeWidth={hot ? 2 : 1.4}
            strokeDasharray="6 6"
            style={{ animation: "dash-flow 1s linear infinite", transition: "stroke 0.4s" }}
          />
        );
      })}

      {L.condition && (
        <text x={L.condition.x} y={L.condition.y} fill="#FF6B6B" fontSize="11" fontFamily="JetBrains Mono, monospace" textAnchor="middle">
          if conf &lt; 85% or CRITICAL
        </text>
      )}

      {L.evidence && (
        <g>
          <line x1={L.evidence.x} y1={238} x2={L.evidence.x} y2={L.evidence.y - 16} stroke="#2A2A3A" strokeDasharray="3 4" />
          <text x={L.evidence.x} y={L.evidence.y} fill="#8888A0" fontSize="11" fontFamily="JetBrains Mono, monospace" textAnchor="middle">
            Google Fact Check · NewsAPI · DuckDuckGo
          </text>
        </g>
      )}

      {Object.entries(NODES).map(([id, n]) => {
        const [cx, cy] = L.pos[id];
        const [w, h] = size(n.kind);
        const on = isActive(id);
        const accent = n.kind === "ultra" ? "#FF2D2D" : n.kind === "io" ? "#F0F0F5" : "#2979FF";
        return (
          <g key={id} style={{ transition: "opacity 0.4s" }}>
            {on && (
              <rect
                x={cx - w / 2}
                y={cy - h / 2}
                width={w}
                height={h}
                rx={12}
                fill={accent}
                opacity={0.35}
                filter={`url(#glow-${layout})`}
              />
            )}
            <rect
              x={cx - w / 2}
              y={cy - h / 2}
              width={w}
              height={h}
              rx={12}
              fill={n.kind === "ultra" ? "#1A0709" : "#111118"}
              stroke={on ? accent : n.kind === "ultra" ? "rgba(255,45,45,0.45)" : "#2A2A3A"}
              strokeWidth={on ? 1.8 : 1}
              style={{ transition: "stroke 0.4s" }}
            />
            <text x={cx} y={cy - 3} fill="#F0F0F5" fontSize={n.kind === "ultra" ? 14 : 12} fontWeight="600" fontFamily="Space Grotesk, sans-serif" textAnchor="middle">
              {n.label}
            </text>
            <text
              x={cx}
              y={cy + 15}
              fill={n.kind === "ultra" ? "#FF6B6B" : n.kind === "io" ? "#8888A0" : "#6EA2FF"}
              fontSize="10"
              fontFamily="JetBrains Mono, monospace"
              textAnchor="middle"
            >
              {n.sub}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export default function ArchitectureDiagram() {
  const [step, setStep] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setStep((s) => (s + 1) % SEQUENCE.length), 1200);
    return () => clearInterval(id);
  }, []);

  const active = SEQUENCE[step].map(String);

  return (
    <>
      <div className="hidden md:block">
        <Diagram layout="wide" active={active} />
      </div>
      <div className="mx-auto max-w-[360px] md:hidden">
        <Diagram layout="tall" active={active} />
      </div>
    </>
  );
}
