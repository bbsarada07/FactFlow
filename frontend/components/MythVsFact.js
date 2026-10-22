import { Download, Loader2 } from "lucide-react";
import { useRef, useState } from "react";
import toast from "react-hot-toast";

import { verdictStyle } from "@/lib/theme";

function labelsFor(verdict) {
  if (verdict === "TRUE") return { left: "CLAIM", right: "✓ CONFIRMED", leftIcon: "" };
  if (verdict === "UNVERIFIED") return { left: "CLAIM", right: "WHAT WE KNOW", leftIcon: "" };
  return { left: "MYTH", right: "✓ FACT", leftIcon: "❌ " };
}

const MYTH = { background: "rgba(255,45,45,0.05)", border: "1px solid rgba(255,45,45,0.2)", color: "#FF2D2D" };
const NEUTRAL = { background: "rgba(136,136,160,0.06)", border: "1px solid rgba(136,136,160,0.25)", color: "#A8A8BC" };
const FACT = { background: "rgba(0,230,118,0.05)", border: "1px solid rgba(0,230,118,0.2)", color: "#00E676" };

/** Fixed 800×450 layout rendered off-screen and captured with html2canvas. */
function ExportCard({ result, innerRef }) {
  const l = labelsFor(result.verdict);
  const v = verdictStyle(result.verdict);
  const left = l.left === "MYTH" ? MYTH : NEUTRAL;
  return (
    <div
      ref={innerRef}
      style={{
        position: "fixed",
        left: -10000,
        top: 0,
        width: 800,
        height: 450,
        padding: 36,
        background: "radial-gradient(ellipse 80% 60% at 50% -20%, rgba(255,45,45,0.14), transparent 60%), #040407",
        color: "#F0F0F5",
        fontFamily: "Inter, sans-serif",
        display: "flex",
        flexDirection: "column",
        gap: 20,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 12, letterSpacing: 3, color: "#8888A0" }}>
          FACT CHECK · {new Date().toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}
        </div>
        <div
          style={{
            background: v.color,
            color: v.text,
            fontFamily: "Space Grotesk, sans-serif",
            fontWeight: 700,
            fontSize: 16,
            letterSpacing: 1,
            padding: "6px 14px",
            borderRadius: 8,
          }}
        >
          {v.label}
        </div>
      </div>
      <div style={{ display: "flex", gap: 18, flex: 1 }}>
        {[
          { s: left, title: `${l.leftIcon}${l.left}`, body: result.myth },
          { s: FACT, title: l.right, body: result.fact, foot: result.fact_source },
        ].map((b) => (
          <div
            key={b.title}
            style={{ ...b.s, color: "#F0F0F5", flex: 1, borderRadius: 16, padding: 24, display: "flex", flexDirection: "column" }}
          >
            <div style={{ fontFamily: "Space Grotesk, sans-serif", fontWeight: 700, fontSize: 18, color: b.s.color, marginBottom: 14 }}>
              {b.title}
            </div>
            <div style={{ fontSize: 19, lineHeight: 1.45, flex: 1 }}>{b.body}</div>
            {b.foot && <div style={{ fontSize: 13, color: "#8888A0", marginTop: 12 }}>Source: {b.foot}</div>}
          </div>
        ))}
      </div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ fontFamily: "Space Grotesk, sans-serif", fontWeight: 700, fontSize: 20 }}>
          <span style={{ color: "#FF2D2D" }}>N</span>emesisAI
        </div>
        <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 12, color: "#8888A0" }}>
          Think before you forward.
        </div>
      </div>
    </div>
  );
}

export default function MythVsFact({ result }) {
  const exportRef = useRef(null);
  const [busy, setBusy] = useState(false);
  const l = labelsFor(result.verdict);
  const left = l.left === "MYTH" ? MYTH : NEUTRAL;

  async function download() {
    if (!exportRef.current) return;
    setBusy(true);
    try {
      const html2canvas = (await import("html2canvas")).default;
      const canvas = await html2canvas(exportRef.current, {
        width: 800,
        height: 450,
        scale: 1,
        backgroundColor: "#040407",
        logging: false,
        windowWidth: 800,
      });
      const a = document.createElement("a");
      a.href = canvas.toDataURL("image/png");
      a.download = `factflow-${result.verdict.toLowerCase()}-${result.request_id.slice(0, 8)}.png`;
      a.click();
      toast.success("Card downloaded");
    } catch (err) {
      toast.error(`Export failed: ${err.message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-md p-5" style={{ background: left.background, border: left.border }}>
          <div className="mb-2 font-display text-[15px] font-bold" style={{ color: left.color }}>
            {l.leftIcon}
            {l.left}
          </div>
          <p className="text-[15px] leading-relaxed text-primary">{result.myth}</p>
        </div>
        <div className="rounded-md p-5" style={{ background: FACT.background, border: FACT.border }}>
          <div className="mb-2 font-display text-[15px] font-bold text-green">{l.right}</div>
          <p className="text-[15px] leading-relaxed text-primary">{result.fact}</p>
          {result.fact_source && <p className="mt-3 text-[12.5px] text-secondary">Source: {result.fact_source}</p>}
        </div>
      </div>
      <button type="button" onClick={download} disabled={busy} className="btn-ghost mt-3">
        {busy ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : <Download size={14} />}
        DOWNLOAD AS IMAGE
      </button>
      <ExportCard result={result} innerRef={exportRef} />
    </div>
  );
}
