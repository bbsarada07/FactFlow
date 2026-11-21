import { useInView } from "framer-motion";
import { ChevronLeft, ChevronRight, Pause, Play } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

/*
 * Three flows, each described as data: boxes on a column/row grid, connectors between them, and the
 * ordered steps that light the flow up with a caption. Positions are computed from the grid, so boxes
 * never overlap and connectors are right-angled lines that share a trunk when they fan out or join.
 */

// Colours per kind of box: [accent, subtitle tint, fill]
const KINDS = {
  io: ["#F0F0F5", "#8888A0", "#111118"],
  nano: ["#2979FF", "#6EA2FF", "#0D1220"],
  ultra: ["#FF2D2D", "#FF6B6B", "#1A0709"],
  gate: ["#E8B400", "#F2CF5B", "#17130A"],
  src: ["#8888A0", "#A8A8BC", "#111118"],
  shield: ["#B04FD0", "#D08BE8", "#150A1A"],
  ok: ["#00E676", "#5CF0A6", "#07160E"],
  wait: ["#FF6B00", "#FF9A4D", "#1A0F06"],
  block: ["#FF2D2D", "#FF6B6B", "#1A0709"],
  agent: ["#FF2D2D", "#FF6B6B", "#1A0709"],
};
const IDLE = "#34344A";

const FLOWS = {
  truth: {
    tab: "Fact-check",
    heading: "How a claim becomes a verdict",
    gap: 40,
    rowH: 118,
    legend: [
      ["nano", "Fast model (Nano)"],
      ["ultra", "Large model (Ultra)"],
      ["gate", "Guardrail"],
      ["dashed", "Only when needed"],
    ],
    nodes: [
      { id: "in", col: 0, row: 1, title: "YOUR CLAIM", sub: "text · url · image", kind: "io" },
      { id: "orch", col: 1, row: 1, title: "ORCHESTRATOR", sub: "agent 0 · router", kind: "nano" },
      { id: "intake", col: 2, row: 1, title: "INTAKE", sub: "agent 1 · Nano", kind: "nano" },
      { id: "tracer", col: 3, row: 1, title: "SOURCE TRACER", sub: "agent 2 · Nano", kind: "nano" },
      { id: "evidence", col: 3, row: 2.2, title: "LIVE EVIDENCE", items: ["Google Fact Check", "NewsAPI · GDELT", "DuckDuckGo web"], kind: "src", w: 156 },
      { id: "deep", col: 4, row: 0, title: "DEEP REASONING", sub: "agent 3 · Ultra", note: "only if needed", kind: "ultra", conditional: true, w: 152 },
      { id: "gate", col: 5, row: 1, title: "HONESTY GATE", sub: "2+ strong sources", kind: "gate" },
      { id: "explain", col: 6, row: 0.45, title: "EXPLAINER", sub: "agent 4 · Nano", kind: "nano" },
      { id: "harm", col: 6, row: 1.55, title: "HARM ASSESSOR", sub: "agent 5 · Nano", kind: "nano" },
      { id: "out", col: 7, row: 1, title: "VERDICT", sub: "with sources", kind: "io" },
    ],
    edges: [
      ["in", "orch"],
      ["orch", "intake"],
      ["intake", "tracer"],
      ["tracer", "evidence", { dashed: true, both: true }],
      ["tracer", "deep", { dashed: true }],
      ["deep", "gate", { dashed: true }],
      ["tracer", "gate"],
      ["gate", "explain"],
      ["gate", "harm"],
      ["explain", "out"],
      ["harm", "out"],
    ],
    steps: [
      { nodes: ["in"], edges: [], title: "You submit a claim",
        text: "Paste a forward, a link or a screenshot on the website, or send it from the browser extension or WhatsApp." },
      { nodes: ["orch"], edges: [["in>orch"]], title: "The Orchestrator routes it",
        text: "It reads the text out of screenshots, opens links, matches known rumour patterns, and withholds claims about private people." },
      { nodes: ["intake"], edges: [["orch>intake"]], title: "Intake finds the claim",
        text: "A fast model pulls out the one checkable claim, its language and how urgent it is." },
      { nodes: ["tracer", "evidence"], edges: [["intake>tracer"], ["tracer>evidence"]], title: "Source Tracer gathers evidence",
        text: "It searches Google Fact Check, NewsAPI, GDELT and the open web, then ranks every source on a fixed credibility list, never on the model's opinion." },
      { nodes: ["deep"], edges: [["tracer>deep"]], badge: "only if needed", title: "Deep Reasoning, only when needed",
        text: "If confidence is below 85% or the claim is CRITICAL, a large model breaks it into sub-claims and hunts for contradictions. Otherwise this step is skipped." },
      { nodes: ["gate"], edges: [["deep>gate", "tracer>gate"]], title: "The honesty gate",
        text: "Without at least two high-credibility sources the answer is UNVERIFIED, and every reason has to point to a source. No guessing." },
      { nodes: ["explain", "harm"], edges: [["gate>explain", "gate>harm"]], badge: "in parallel", title: "Explain and assess harm, in parallel",
        text: "The Explainer writes a plain-language correction in your language while the Harm Assessor scores the risk, both at the same time." },
      { nodes: ["out"], edges: [["explain>out", "harm>out"]], title: "Your verdict",
        text: "TRUE, FALSE, MISLEADING or UNVERIFIED, with its sources, a confidence band and a correction you can forward." },
    ],
  },

  mail: {
    tab: "Mail agent + Shield",
    heading: "How every email is handled",
    gap: 34,
    rowH: 112,
    legend: [
      ["shield", "Shield checks"],
      ["gate", "Guardrail"],
      ["ok", "Done by the agent"],
      ["wait", "Waits for you"],
      ["block", "Blocked"],
    ],
    nodes: [
      { id: "in", col: 0, row: 1, title: "NEW EMAIL", sub: "your Gmail", kind: "io" },
      { id: "parse", col: 1, row: 1, title: "TWO VIEWS", items: ["What you see", "What an AI reads", "Files & QR codes"], kind: "shield", w: 150 },
      { id: "scan", col: 2, row: 1, title: "SHIELD SCAN",
        items: ["Hidden text", "Prompt injection", "Sender authenticity", "Links & QR codes", "Scam patterns", "Claims → fact-check"], kind: "shield", w: 176 },
      { id: "verdict", col: 3, row: 1, title: "RISK VERDICT",
        items: [["SAFE", "#00E676"], ["SUSPICIOUS", "#FF6B00"], ["DANGEROUS", "#FF2D2D"]], kind: "shield" },
      { id: "plan", col: 4, row: 1, title: "PLANNER", sub: "uses verdict only", kind: "gate" },
      { id: "policy", col: 5, row: 1, title: "POLICY ENGINE", sub: "every step checked", kind: "gate" },
      { id: "ok", col: 6, row: 0, title: "DONE BY AGENT", sub: "routine & safe", kind: "ok", w: 156 },
      { id: "wait", col: 6, row: 1, title: "NEEDS YOU", sub: "waits for you", kind: "wait", w: 156 },
      { id: "block", col: 6, row: 2, title: "BLOCKED", sub: "never carried out", kind: "block", w: 156 },
      { id: "audit", col: 7, row: 1, title: "AUDIT LOG", sub: "tamper-evident", kind: "io" },
    ],
    edges: [
      ["in", "parse"],
      ["parse", "scan"],
      ["scan", "verdict"],
      ["verdict", "plan"],
      ["plan", "policy"],
      ["policy", "ok"],
      ["policy", "wait"],
      ["policy", "block"],
      ["ok", "audit"],
      ["wait", "audit"],
      ["block", "audit"],
    ],
    steps: [
      { nodes: ["in"], edges: [], title: "A new email arrives",
        text: "FactFlow checks your connected Gmail for new mail about every 45 seconds. You never paste anything." },
      { nodes: ["parse"], edges: [["in>parse"]], title: "What you see vs. what an AI reads",
        text: "Two views of the same email are built and compared, so text hidden with CSS, tiny fonts, comments or invisible characters is exposed. Attachments and QR codes are opened too." },
      { nodes: ["scan"], edges: [["parse>scan"]], badge: "in parallel", title: "Six detectors, in parallel",
        text: "Hidden text, prompt injection, sender authenticity (SPF, DKIM, DMARC and lookalike domains), links and QR codes, Indian scam patterns, and a fact-check of any claims inside." },
      { nodes: ["verdict"], edges: [["scan>verdict"]], title: "One risk verdict",
        text: "The scores combine into SAFE, SUSPICIOUS or DANGEROUS. Hidden text that tries to instruct an AI is always DANGEROUS." },
      { nodes: ["plan"], edges: [["verdict>plan"]], title: "The planner never reads the email",
        text: "Steps come from the verdict's structured fields only, so nothing written in an email can add or change one. A reply, if one is needed, is drafted from the visible text alone by a model with no tools and nothing else to read." },
      { nodes: ["policy"], edges: [["plan>policy"]], title: "Every step meets the policy engine",
        text: "Fixed rules decide each step, in strict or balanced mode. Any error fails closed: the step is blocked, never allowed." },
      { nodes: ["ok", "wait", "block"], edges: [["policy>ok", "policy>wait", "policy>block"]], badge: "one of three", title: "Act, ask you, or block",
        text: "Routine replies to people you write to, and files you marked OK to send, go out on their own, with a couple of minutes to undo. Money, first-time senders, invitations and anything unusual wait for you. Dangerous mail is quarantined, and instructions hidden in an email are never carried out." },
      { nodes: ["audit"], edges: [["ok>audit", "wait>audit", "block>audit"]], title: "Everything is on the record",
        text: "Each decision is written to a tamper-evident audit log, so you can see exactly what your agent did and why." },
    ],
  },

  everywhere: {
    tab: "Everywhere you are",
    heading: "One agent, wherever the message reaches you",
    gap: 90,
    rowH: 92,
    legend: [
      ["io", "Where you are"],
      ["agent", "Your FactFlow agent"],
    ],
    nodes: [
      { id: "web", col: 0, row: 0, title: "WEBSITE", sub: "paste text, link, image", kind: "io", w: 196 },
      { id: "ext", col: 0, row: 1, title: "BROWSER EXTENSION", sub: "right-click any text", kind: "io", w: 196 },
      { id: "wa", col: 0, row: 2, title: "WHATSAPP", sub: "forward to FactFlow", kind: "io", w: 196 },
      { id: "gm", col: 0, row: 3, title: "GMAIL", sub: "every new email", kind: "io", w: 196 },
      { id: "agent", col: 1, row: 1.5, title: "FACTFLOW AGENT",
        items: ["Truth: is it true?", "Shield: is it safe?", "You approve risky steps"], kind: "agent", w: 214 },
      { id: "r-web", col: 2, row: 0, title: "VERDICT PAGE", sub: "sources & correction", kind: "io", w: 196 },
      { id: "r-ext", col: 2, row: 1, title: "ON THE SAME PAGE", sub: "verdict where you are", kind: "io", w: 196 },
      { id: "r-wa", col: 2, row: 2, title: "WHATSAPP REPLY", sub: "answer in the chat", kind: "io", w: 196 },
      { id: "r-gm", col: 2, row: 3, title: "INBOX + NEEDS YOU", sub: "handled, or asks you", kind: "io", w: 196 },
    ],
    edges: [
      ["web", "agent"], ["ext", "agent"], ["wa", "agent"], ["gm", "agent"],
      ["agent", "r-web"], ["agent", "r-ext"], ["agent", "r-wa"], ["agent", "r-gm"],
    ],
    steps: [
      { nodes: ["web", "agent", "r-web"], edges: [["web>agent"], ["agent>r-web"]], title: "On the website",
        text: "Paste a message, a link or a screenshot and watch the agents work live, step by step." },
      { nodes: ["ext", "agent", "r-ext"], edges: [["ext>agent"], ["agent>r-ext"]], title: "With the browser extension",
        text: "Select text on any page, including WhatsApp Web, right-click Verify with FactFlow, and get the verdict without leaving the page." },
      { nodes: ["wa", "agent", "r-wa"], edges: [["wa>agent"], ["agent>r-wa"]], title: "On your phone",
        text: "Forward a WhatsApp message to the FactFlow number and the verdict comes back as a reply in the same chat." },
      { nodes: ["gm", "agent", "r-gm"], edges: [["gm>agent"], ["agent>r-gm"]], title: "In your inbox",
        text: "Connect Gmail and every new email is checked automatically. Routine work is handled; anything risky waits for you in Needs you." },
    ],
  },
};

const NODE_W = 136;
const PAD_X = 20;
const PAD_Y = 30;

function nodeHeight(n) {
  if (n.items) return 44 + n.items.length * 20 + (n.sub ? 16 : 0);
  return 62 + (n.note ? 18 : 0);
}

/** Grid -> pixel positions, connector routes and the canvas size for one flow. */
function computeLayout(flow) {
  const colW = [];
  flow.nodes.forEach((n) => {
    colW[n.col] = Math.max(colW[n.col] || 0, n.w || NODE_W);
  });
  const colX = [];
  let x = PAD_X;
  colW.forEach((w, i) => {
    colX[i] = x;
    x += w + flow.gap;
  });
  const width = x - flow.gap + PAD_X;

  const nodes = {};
  let minY = Infinity;
  let maxY = -Infinity;
  flow.nodes.forEach((n) => {
    const w = n.w || NODE_W;
    const h = nodeHeight(n);
    const cy = n.row * flow.rowH;
    nodes[n.id] = { ...n, w, h, cx: colX[n.col] + colW[n.col] / 2, cy };
    minY = Math.min(minY, cy - h / 2);
    maxY = Math.max(maxY, cy + h / 2);
  });
  const shift = PAD_Y - minY;
  Object.values(nodes).forEach((n) => {
    n.cy += shift;
  });

  const edges = flow.edges.map(([from, to, opts = {}]) => {
    const a = nodes[from];
    const b = nodes[to];
    let pts;
    if (a.col === b.col) {
      const down = b.cy > a.cy;
      pts = [
        [a.cx, a.cy + (down ? a.h / 2 : -a.h / 2)],
        [b.cx, b.cy + (down ? -b.h / 2 : b.h / 2)],
      ];
    } else {
      const x1 = a.cx + a.w / 2;
      const x2 = b.cx - b.w / 2;
      if (Math.abs(a.cy - b.cy) < 1) {
        pts = [[x1, a.cy], [x2, b.cy]];
      } else {
        // Turn in the middle of the gap right after the source column, so fan-outs share a trunk.
        const mx = colX[a.col] + colW[a.col] + flow.gap / 2;
        pts = [[x1, a.cy], [mx, a.cy], [mx, b.cy], [x2, b.cy]];
      }
    }
    return { key: `${from}>${to}`, from, to, pts, d: roundedPath(pts, 10), ...opts };
  });

  return { width, height: maxY - minY + PAD_Y * 2, nodes, edges };
}

function roundedPath(pts, r) {
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const [px, py] = pts[i - 1];
    const [cx, cy] = pts[i];
    const [nx, ny] = pts[i + 1];
    const inLen = Math.hypot(cx - px, cy - py);
    const outLen = Math.hypot(nx - cx, ny - cy);
    const k = Math.min(r, inLen / 2, outLen / 2);
    const ax = cx - ((cx - px) / inLen) * k;
    const ay = cy - ((cy - py) / inLen) * k;
    const bx = cx + ((nx - cx) / outLen) * k;
    const by = cy + ((ny - cy) / outLen) * k;
    d += ` L${ax},${ay} Q${cx},${cy} ${bx},${by}`;
  }
  const [lx, ly] = pts[pts.length - 1];
  return `${d} L${lx},${ly}`;
}

function pointAt(pts, t) {
  const segs = [];
  let total = 0;
  for (let i = 1; i < pts.length; i++) {
    const len = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
    segs.push(len);
    total += len;
  }
  let dist = t * total;
  for (let i = 0; i < segs.length; i++) {
    if (dist <= segs[i] || i === segs.length - 1) {
      const f = segs[i] ? Math.min(1, dist / segs[i]) : 1;
      return [pts[i][0] + (pts[i + 1][0] - pts[i][0]) * f, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * f];
    }
    dist -= segs[i];
  }
  return pts[pts.length - 1];
}

/** A dot that travels once along a connector. Driven by requestAnimationFrame, so it restarts reliably. */
function Pulse({ pts, color, delay }) {
  const ref = useRef(null);
  useEffect(() => {
    let frame;
    const start = performance.now() + delay;
    const duration = 850;
    const tick = (now) => {
      const el = ref.current;
      if (!el) return;
      const t = Math.min(1, Math.max(0, (now - start) / duration));
      const eased = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
      const [x, y] = pointAt(pts, eased);
      el.setAttribute("cx", x);
      el.setAttribute("cy", y);
      el.setAttribute("opacity", now < start || t >= 1 ? 0 : 1);
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [pts, delay]);
  return <circle ref={ref} r="4.5" fill={color} opacity="0" style={{ filter: `drop-shadow(0 0 6px ${color})` }} />;
}

function Box({ n, on, dim, onSelect }) {
  const [accent, tint, fill] = KINDS[n.kind];
  const x = n.cx - n.w / 2;
  const y = n.cy - n.h / 2;
  const top = n.items ? y + 22 : n.cy - (n.note ? 9 : 3);
  return (
    <g
      role="button"
      tabIndex={0}
      aria-label={`${n.title}: show this step`}
      onClick={onSelect}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect())}
      style={{ cursor: "pointer", opacity: dim ? 0.8 : 1, transition: "opacity 0.35s" }}
    >
      {on && <rect x={x - 3} y={y - 3} width={n.w + 6} height={n.h + 6} rx={14} fill={accent} opacity={0.16} />}
      <rect
        x={x}
        y={y}
        width={n.w}
        height={n.h}
        rx={12}
        fill={fill}
        stroke={on ? accent : n.kind === "io" || n.kind === "src" ? "#3A3A50" : `${accent}80`}
        strokeWidth={on ? 2 : 1.2}
        strokeDasharray={n.conditional ? "5 4" : undefined}
        style={{ transition: "stroke 0.35s" }}
      />
      <text x={n.cx} y={top} fill="#F0F0F5" fontSize="14" fontWeight="600" fontFamily="Space Grotesk, sans-serif" textAnchor="middle" letterSpacing="0.4">
        {n.title}
      </text>
      {n.sub && (
        <text x={n.cx} y={top + 18} fill={tint} fontSize="11.5" fontFamily="JetBrains Mono, monospace" textAnchor="middle">
          {n.sub}
        </text>
      )}
      {n.note && (
        <text x={n.cx} y={top + 35} fill={accent} fontSize="11" fontStyle="italic" fontFamily="Inter, sans-serif" textAnchor="middle">
          {n.note}
        </text>
      )}
      {n.items &&
        n.items.map((item, i) => {
          const [label, color] = Array.isArray(item) ? item : [item, tint];
          const iy = top + (n.sub ? 16 : 0) + 22 + i * 20;
          return (
            <g key={label}>
              <circle cx={x + 16} cy={iy - 4} r="2.6" fill={color} />
              <text x={x + 26} y={iy} fill={Array.isArray(item) ? color : "#C8C8D6"} fontSize="11.5" fontFamily="JetBrains Mono, monospace">
                {label}
              </text>
            </g>
          );
        })}
    </g>
  );
}

function Diagram({ flow, layout, step, onSelectNode, animate }) {
  const current = flow.steps[step];
  const hotNodes = new Set(current.nodes);
  const groups = current.edges.map((g) => (Array.isArray(g) ? g : [g]));
  const hotEdges = new Map();
  groups.forEach((group, gi) => group.forEach((key) => hotEdges.set(key, gi)));
  const markerColors = [...new Set([IDLE, ...Object.values(KINDS).map((k) => k[0])])];
  const markerId = (c) => `ff-arrow-${c.slice(1)}`;

  return (
    <svg
      viewBox={`0 0 ${layout.width} ${layout.height}`}
      className="mx-auto block h-auto w-full"
      style={{ maxWidth: layout.width * 1.05 }}
    >
      <title>{`${flow.heading}: ${flow.steps.map((s) => s.title).join(", then ")}`}</title>
      <defs>
        {markerColors.map((c) => (
          <marker key={c} id={markerId(c)} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,1 L9,5 L0,9 z" fill={c} />
          </marker>
        ))}
      </defs>

      {/* idle connectors first, active ones on top so shared trunks light up cleanly */}
      {[false, true].map((layer) =>
        layout.edges
          .filter((e) => hotEdges.has(e.key) === layer)
          .map((e) => {
            const color = layer ? KINDS[layout.nodes[e.to].kind][0] : IDLE;
            return (
              <path
                key={`${layer}-${e.key}`}
                d={e.d}
                fill="none"
                stroke={color}
                strokeWidth={layer ? 2.2 : 1.5}
                strokeDasharray={e.dashed ? "6 5" : undefined}
                markerEnd={`url(#${markerId(color)})`}
                markerStart={e.both ? `url(#${markerId(color)})` : undefined}
                style={{ transition: "stroke 0.35s" }}
              />
            );
          }),
      )}

      {animate &&
        layout.edges
          .filter((e) => hotEdges.has(e.key))
          .map((e) => (
            <Pulse
              key={`${step}-${e.key}`}
              pts={e.pts}
              color={KINDS[layout.nodes[e.to].kind][0]}
              delay={hotEdges.get(e.key) * 750}
            />
          ))}

      {Object.values(layout.nodes).map((n) => (
        <Box key={n.id} n={n} on={hotNodes.has(n.id)} dim={!hotNodes.has(n.id)} onSelect={() => onSelectNode(n.id)} />
      ))}
    </svg>
  );
}

function Legend({ items }) {
  return (
    <div className="mono flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-[11px] text-secondary">
      {items.map(([kind, label]) => (
        <span key={label} className="flex items-center gap-2">
          {kind === "dashed" ? (
            <svg width="22" height="8" aria-hidden="true">
              <line x1="0" y1="4" x2="22" y2="4" stroke="#8888A0" strokeWidth="1.6" strokeDasharray="5 4" />
            </svg>
          ) : (
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: KINDS[kind][0] }} />
          )}
          {label}
        </span>
      ))}
    </div>
  );
}

/** Phones and tablets: the same steps as a vertical flow, one card per step. */
function StepList({ flow, step, onSelect }) {
  return (
    <ol className="relative m-0 list-none p-0">
      {flow.steps.map((s, i) => {
        const active = i === step;
        const kinds = s.nodes.map((id) => flow.nodes.find((n) => n.id === id));
        const accent = KINDS[kinds[0].kind][0];
        return (
          <li key={s.title} className="relative pb-3 pl-10 last:pb-0">
            {i < flow.steps.length - 1 && (
              <span className="absolute left-[13px] top-7 bottom-0 w-px" style={{ background: active ? accent : "#2A2A3A" }} aria-hidden="true" />
            )}
            <span
              className="mono absolute left-0 top-1 flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-semibold"
              style={{ background: active ? accent : "#16161F", color: active ? "#040407" : "#8888A0", border: `1px solid ${active ? accent : "#2A2A3A"}` }}
            >
              {i + 1}
            </span>
            <button
              type="button"
              onClick={() => onSelect(i)}
              className="w-full rounded-md border p-3 text-left transition-colors"
              style={{ borderColor: active ? `${accent}99` : "var(--border-subtle)", background: active ? `${accent}12` : "transparent" }}
              aria-current={active ? "step" : undefined}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-display text-[15px] font-semibold text-primary">{s.title}</span>
                {s.badge && (
                  <span className="mono rounded-sm border px-1.5 text-[10px]" style={{ borderColor: `${accent}66`, color: accent }}>
                    {s.badge}
                  </span>
                )}
              </div>
              <div className="mono mt-1 text-[10.5px] tracking-[1px] text-muted">{kinds.map((n) => n.title).join(" · ")}</div>
              {active && <p className="m-0 mt-2 text-[14px] leading-relaxed text-secondary">{s.text}</p>}
            </button>
          </li>
        );
      })}
    </ol>
  );
}

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const q = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(q.matches);
    const on = (e) => setReduced(e.matches);
    q.addEventListener("change", on);
    return () => q.removeEventListener("change", on);
  }, []);
  return reduced;
}

const STEP_MS = 3600;

export default function ArchitectureDiagram() {
  const [flowKey, setFlowKey] = useState("truth");
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(true);
  const reduced = usePrefersReducedMotion();
  const root = useRef(null);
  const inView = useInView(root, { amount: 0.3 });

  const flow = FLOWS[flowKey];
  const layout = useMemo(() => computeLayout(flow), [flow]);
  const total = flow.steps.length;
  const running = playing && inView;

  useEffect(() => {
    if (reduced) setPlaying(false);
  }, [reduced]);

  useEffect(() => {
    if (!running) return undefined;
    const id = setTimeout(() => setStep((s) => (s + 1) % total), STEP_MS);
    return () => clearTimeout(id);
  }, [running, step, total]);

  const chooseFlow = (key) => {
    setFlowKey(key);
    setStep(0);
  };
  const goTo = (i) => {
    setStep(((i % total) + total) % total);
    setPlaying(false);
  };
  // functional update, so quick repeated clicks never read a stale step
  const move = (delta) => {
    setStep((s) => (s + delta + total) % total);
    setPlaying(false);
  };
  const selectNode = (id) => {
    const i = flow.steps.findIndex((s) => s.nodes.includes(id));
    if (i >= 0) goTo(i);
  };

  const current = flow.steps[step];
  const accent = KINDS[flow.nodes.find((n) => n.id === current.nodes[0]).kind][0];

  return (
    <div ref={root}>
      <div role="tablist" aria-label="Choose a flow" className="mb-6 flex flex-wrap justify-center gap-2">
        {Object.entries(FLOWS).map(([key, f]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={key === flowKey}
            onClick={() => chooseFlow(key)}
            className={`mono rounded-full border px-4 py-2 text-[11.5px] tracking-[1px] transition-colors ${
              key === flowKey ? "text-primary" : "border-subtle text-secondary hover:text-primary"
            }`}
            style={key === flowKey ? { borderColor: "#FF2D2D", background: "rgba(255,45,45,0.1)" } : undefined}
          >
            {f.tab.toUpperCase()}
          </button>
        ))}
      </div>

      <h3 className="m-0 mb-5 text-center font-display text-[20px] font-semibold text-primary">{flow.heading}</h3>

      {/* Desktop: the full diagram with a caption under it */}
      <div className="hidden xl:block">
        <Diagram flow={flow} layout={layout} step={step} onSelectNode={selectNode} animate={!reduced} />
        <div className="mt-5">
          <Legend items={flow.legend} />
        </div>
        <div className="mx-auto mt-6 flex max-w-3xl items-start gap-4 rounded-md border bg-card p-4" style={{ borderColor: `${accent}55` }} aria-live="polite">
          <div className="mono shrink-0 pt-0.5 text-[11px] tracking-[1.5px]" style={{ color: accent }}>
            STEP {step + 1}/{total}
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-display text-[16px] font-semibold text-primary">{current.title}</span>
              {current.badge && (
                <span className="mono rounded-sm border px-1.5 text-[10px]" style={{ borderColor: `${accent}66`, color: accent }}>
                  {current.badge}
                </span>
              )}
            </div>
            <p className="m-0 mt-1 text-[14px] leading-relaxed text-secondary">{current.text}</p>
          </div>
        </div>
      </div>

      {/* Phones and tablets: a vertical flow of the same steps */}
      <div className="mx-auto max-w-xl xl:hidden">
        <StepList flow={flow} step={step} onSelect={goTo} />
      </div>

      <div className="mt-5 flex items-center justify-center gap-3">
        <button type="button" onClick={() => move(-1)} className="btn-ghost !p-2" aria-label="Previous step">
          <ChevronLeft size={16} />
        </button>
        <button
          type="button"
          onClick={() => setPlaying((p) => !p)}
          className="btn-ghost mono !px-4 !py-2 text-[11px] tracking-[1px]"
          aria-label={playing ? "Pause" : "Play"}
        >
          <span className="flex items-center gap-2">
            {playing ? <Pause size={14} /> : <Play size={14} />}
            {playing ? "PAUSE" : "PLAY"}
          </span>
        </button>
        <button type="button" onClick={() => move(1)} className="btn-ghost !p-2" aria-label="Next step">
          <ChevronRight size={16} />
        </button>
        <div className="ml-2 hidden gap-1.5 sm:flex" aria-hidden="true">
          {flow.steps.map((s, i) => (
            <button
              key={s.title}
              type="button"
              tabIndex={-1}
              onClick={() => goTo(i)}
              className="h-1.5 rounded-full transition-all"
              style={{ width: i === step ? 18 : 6, background: i === step ? accent : "#2A2A3A" }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
