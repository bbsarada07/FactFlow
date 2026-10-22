import { AnimatePresence, motion } from "framer-motion";
import { ArrowRight, ChevronDown, ImageIcon, Link2, Loader2, RotateCcw, X } from "lucide-react";
import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { useCallback, useEffect, useRef, useState } from "react";

import toast from "react-hot-toast";

import AgentProgress, { AGENT_DEFAULTS } from "@/components/AgentProgress";
import VerdictCard from "@/components/VerdictCard";
import { getIncidents, getResult, getStats, startVerification, streamUrl } from "@/lib/api";
import { EASE, LANGUAGES } from "@/lib/theme";

const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const IMAGE_TYPES = ["image/png", "image/jpeg"];
const SCREENSHOT_RULE = "Only PNG or JPG screenshots up to 5 MB are supported.";

const HEADLINE = [
  { text: "Rumours spread.", color: "var(--text-primary)" },
  { text: "Facts", color: "var(--text-secondary)" },
  { text: "flow.", color: "var(--accent-red)", italic: true },
];

/** Sourced incident line: every figure comes from the incidents table, shown with its source link. */
function IncidentLine() {
  const [incident, setIncident] = useState(null);

  useEffect(() => {
    getIncidents()
      .then((d) => setIncident(d.items.find((i) => i.slug === "palghar-2020") || null))
      .catch(() => setIncident(null));
  }, []);

  if (!incident) return null;
  const when = new Date(incident.date).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
  return (
    <motion.p
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.6 }}
      className="mono mt-8 text-center text-[12px] text-secondary sm:text-[13px]"
    >
      In {when}, <span className="text-primary">{incident.deaths} people</span> were lynched in Palghar after a WhatsApp
      rumour.{" "}
      <a href={incident.source.url} target="_blank" rel="noopener noreferrer" className="text-red hover:underline">
        {incident.source.confirmed ? "Source" : "Find source"}
      </a>
    </motion.p>
  );
}

function LanguagePicker({ value, onChange }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const current = LANGUAGES.find((l) => l.code === value) || LANGUAGES[0];

  useEffect(() => {
    const close = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="btn-ghost"
        data-active={open}
        aria-haspopup="listbox"
        aria-expanded={open}
        title="Language for the explanation and WhatsApp reply"
      >
        {current.label}
        <ChevronDown size={13} />
      </button>
      <AnimatePresence>
        {open && (
          <motion.ul
            role="listbox"
            initial={{ opacity: 0, y: 6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.98 }}
            transition={{ duration: 0.15 }}
            className="glass absolute bottom-full left-1/2 z-20 mb-2 max-h-64 w-40 -translate-x-1/2 overflow-y-auto rounded-md p-1"
            style={{ background: "rgba(17,17,24,0.96)" }}
          >
            {LANGUAGES.map((l) => (
              <li key={l.code}>
                <button
                  type="button"
                  role="option"
                  aria-selected={l.code === value}
                  onClick={() => {
                    onChange(l.code);
                    setOpen(false);
                  }}
                  className="w-full rounded px-3 py-1.5 text-left text-[13px] transition-colors hover:bg-hover"
                  style={{ color: l.code === value ? "var(--accent-red)" : "var(--text-primary)" }}
                >
                  {l.label}
                </button>
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function VerifyPage() {
  const router = useRouter();
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [showUrl, setShowUrl] = useState(false);
  const [image, setImage] = useState(null);
  const [language, setLanguage] = useState("auto");

  const [phase, setPhase] = useState("idle");
  const [agents, setAgents] = useState(AGENT_DEFAULTS);
  const [progress, setProgress] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [avgSeconds, setAvgSeconds] = useState(null);
  const [cachedMatch, setCachedMatch] = useState(null);
  const [withheldMessage, setWithheldMessage] = useState(null);

  const esRef = useRef(null);
  const timerRef = useRef(null);
  const pollRef = useRef(null);
  const startRef = useRef(0);
  const trackerRef = useRef(null);
  const verdictRef = useRef(null);
  const fileRef = useRef(null);
  const autoRan = useRef(false);

  const running = phase === "running";

  useEffect(() => {
    getStats()
      .then((s) => setAvgSeconds(s.avg_seconds))
      .catch(() => {});
  }, [phase]);

  const stopAll = useCallback(() => {
    esRef.current?.close();
    esRef.current = null;
    clearInterval(timerRef.current);
    clearInterval(pollRef.current);
  }, []);

  useEffect(() => stopAll, [stopAll]);

  const fail = useCallback(
    (message) => {
      stopAll();
      setError(message);
      setPhase("error");
    },
    [stopAll]
  );

  // Private-person / self-harm rule: show only the fixed message from the server, no verdict.
  const withhold = useCallback(
    (message) => {
      stopAll();
      setWithheldMessage(message);
      setPhase("withheld");
    },
    [stopAll]
  );

  const finish = useCallback(
    (res) => {
      if (res.status === "failed") {
        if (res.agents?.length) setAgents(res.agents);
        fail(res.error || "Verification failed");
        return;
      }
      stopAll();
      if (res.agents?.length) setAgents(res.agents);
      setProgress(100);
      if (res.processing_ms != null) setElapsed(res.processing_ms);
      setResult(res);
      setPhase("done");
      setTimeout(() => verdictRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 450);
    },
    [fail, stopAll]
  );

  const poll = useCallback(
    (id) => {
      clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const { status, data } = await getResult(id);
          if (status === 200) finish(data);
        } catch (err) {
          fail(err.message);
        }
      }, 2000);
    },
    [fail, finish]
  );

  const listen = useCallback(
    (id) => {
      const es = new EventSource(streamUrl(id));
      esRef.current = es;
      es.addEventListener("agent", (e) => {
        const d = JSON.parse(e.data);
        setAgents((prev) =>
          prev.map((a) =>
            a.index === d.agent
              ? { ...a, status: d.status, preview: d.preview, model: d.model, ms: d.ms, tier: d.tier || a.tier }
              : a
          )
        );
        if (typeof d.progress === "number") setProgress(d.progress);
      });
      es.addEventListener("result", (e) => finish(JSON.parse(e.data).result));
      es.addEventListener("withheld", (e) => withhold(JSON.parse(e.data).message));
      es.addEventListener("error", (e) => {
        if (e.data) {
          fail(JSON.parse(e.data).message);
          return;
        }
        // Connection dropped before a result: fall back to polling.
        if (esRef.current) {
          esRef.current.close();
          esRef.current = null;
          poll(id);
        }
      });
    },
    [fail, finish, poll, withhold]
  );

  const submit = useCallback(
    async (override) => {
      const claimText = (override?.text ?? text).trim();
      const claimUrl = showUrl ? url.trim() : "";
      if (!claimText && !claimUrl && !image) {
        toast.error("Paste a claim, add a URL or attach a screenshot");
        return;
      }
      stopAll();
      setAgents(AGENT_DEFAULTS);
      setProgress(0);
      setElapsed(0);
      setResult(null);
      setCachedMatch(null);
      setError(null);
      setPhase("running");
      startRef.current = Date.now();
      timerRef.current = setInterval(() => setElapsed(Date.now() - startRef.current), 250);
      setTimeout(() => trackerRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 120);

      try {
        const payload = { language, platform: "web" };
        if (claimText) payload.text = claimText;
        if (claimUrl) payload.url = claimUrl;
        if (image) payload.image_base64 = image.dataUrl;
        const started = await startVerification(payload);
        if (started.status === "withheld") {
          withhold(started.message);
        } else if (started.cached) {
          // Repeat claim: answered from the public registry, no new analysis.
          setCachedMatch({ slug: started.matched_slug, at: started.matched_at });
          const { data } = await getResult(started.request_id);
          finish(data);
        } else {
          listen(started.request_id);
        }
      } catch (err) {
        fail(err.message);
      }
    },
    [text, url, showUrl, image, language, listen, fail, finish, stopAll, withhold]
  );

  // Deep link: /?claim=...&auto=true (used by the Incident Library)
  useEffect(() => {
    if (!router.isReady || autoRan.current) return;
    const claim = typeof router.query.claim === "string" ? router.query.claim : "";
    if (!claim) return;
    autoRan.current = true;
    setText(claim);
    const auto = router.query.auto === "true";
    router.replace("/", undefined, { shallow: true });
    if (auto) submit({ text: claim });
  }, [router, submit]);

  function onFile(e) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    if (!IMAGE_TYPES.includes(file.type) || file.size > MAX_IMAGE_BYTES) return toast.error(SCREENSHOT_RULE);
    const reader = new FileReader();
    reader.onload = () => setImage({ dataUrl: reader.result, name: file.name });
    reader.readAsDataURL(file);
  }

  function reset() {
    stopAll();
    setPhase("idle");
    setResult(null);
    setCachedMatch(null);
    setError(null);
    setText("");
    setUrl("");
    setImage(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  return (
    <>
      <Head>
        <title>Verify — FactFlow</title>
      </Head>

      <section className="relative overflow-hidden">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-[-10%]"
          style={{
            background:
              "radial-gradient(ellipse 80% 60% at 50% -20%, rgba(255,45,45,0.08) 0%, transparent 60%), radial-gradient(ellipse 60% 40% at 80% 80%, rgba(41,121,255,0.05) 0%, transparent 50%)",
            animation: "mesh-drift 18s ease-in-out infinite",
          }}
        />
        <div className="relative mx-auto flex min-h-[calc(100vh-var(--nav-height))] max-w-5xl flex-col items-center justify-center px-4 py-16 text-center">
          <motion.div
            initial={{ opacity: 0, y: -16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.6, duration: 0.6, ease: EASE }}
            className="mono mb-8 flex items-center gap-2.5 rounded-full border px-4 py-1.5 text-[10.5px] tracking-[3px] text-red sm:text-[11px]"
            style={{ borderColor: "rgba(255,45,45,0.3)", background: "rgba(255,45,45,0.05)" }}
          >
            <span className="live-dot" />
            REAL-TIME FORENSIC VERIFICATION
          </motion.div>

          <h1 className="m-0 font-display font-bold leading-[0.98] tracking-[-0.03em]" style={{ fontSize: "clamp(42px, 10vw, 88px)" }}>
            {HEADLINE.map((line, i) => (
              <motion.span
                key={line.text}
                className="block"
                initial={{ opacity: 0, y: 28 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.15 + i * 0.15, duration: 0.7, ease: EASE }}
                style={{ color: line.color, fontStyle: line.italic ? "italic" : "normal" }}
              >
                {line.text}
              </motion.span>
            ))}
          </h1>

          <IncidentLine />

          <motion.form
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.75, duration: 0.6, ease: EASE }}
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
            className={`mt-16 w-full max-w-[720px] rounded-xl border border-active bg-card p-5 text-left sm:p-6 ${running ? "glow-pulse" : ""}`}
            style={{ boxShadow: "var(--glow-red)" }}
          >
            <label htmlFor="claim" className="sr-only">
              Claim to verify
            </label>
            <textarea
              id="claim"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
              }}
              maxLength={5000}
              placeholder="Paste any WhatsApp forward, tweet, news headline, or claim..."
              className="block min-h-[100px] w-full resize-none border-none bg-transparent text-[16px] leading-relaxed text-primary outline-none placeholder:text-muted"
              disabled={running}
            />

            <AnimatePresence>
              {showUrl && (
                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}>
                  <input
                    type="url"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    placeholder="https://example.com/article"
                    className="mono mt-2 w-full rounded-md border border-subtle bg-surface px-3 py-2.5 text-[13px] text-primary outline-none placeholder:text-muted focus:border-active"
                    disabled={running}
                  />
                </motion.div>
              )}
            </AnimatePresence>

            {image && (
              <div className="mt-3 flex items-center gap-3 rounded-md border border-subtle bg-surface p-2 pr-3">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={image.dataUrl} alt="Attached screenshot" className="h-12 w-12 rounded object-cover" />
                <span className="mono flex-1 truncate text-[12px] text-secondary">{image.name}</span>
                <button type="button" onClick={() => setImage(null)} className="text-muted hover:text-primary" aria-label="Remove image">
                  <X size={16} />
                </button>
              </div>
            )}

            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-subtle pt-4">
              <div className="flex items-center gap-2">
                <button type="button" className="btn-ghost" data-active={!!image} onClick={() => fileRef.current?.click()} disabled={running}>
                  <ImageIcon size={14} /> Image
                </button>
                <input ref={fileRef} type="file" accept="image/png,image/jpeg" className="hidden" onChange={onFile} />
                <button type="button" className="btn-ghost" data-active={showUrl} onClick={() => setShowUrl((s) => !s)} disabled={running}>
                  <Link2 size={14} /> URL
                </button>
              </div>
              <LanguagePicker value={language} onChange={setLanguage} />
              <button type="submit" className="btn-red w-full sm:w-auto" disabled={running}>
                {running ? (
                  <>
                    <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> VERIFYING
                  </>
                ) : (
                  <>
                    VERIFY NOW <ArrowRight size={16} />
                  </>
                )}
              </button>
            </div>
          </motion.form>

          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 1.1 }}
            className="mono mt-4 text-[12px] text-muted"
          >
            {avgSeconds ? `Average analysis time: ${Math.round(avgSeconds)} seconds` : "Six agents · live evidence"}
            <span className="hidden sm:inline"> · Ctrl+Enter to verify</span>
          </motion.p>
        </div>
      </section>

      {phase === "withheld" && (
        <section className="mx-auto max-w-[880px] px-4 pb-24">
          <motion.div
            ref={trackerRef}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            role="status"
            className="mt-6 rounded-md p-5 text-[15px] leading-relaxed text-primary"
            style={{ background: "rgba(136,136,160,0.06)", border: "1px solid rgba(136,136,160,0.25)", scrollMarginTop: 72 }}
          >
            {withheldMessage}
          </motion.div>
        </section>
      )}

      {phase !== "idle" && phase !== "withheld" && (
        <section className="mx-auto max-w-[880px] px-4 pb-24">
          <div ref={trackerRef} style={{ scrollMarginTop: 72 }}>
            <AgentProgress agents={agents} progress={progress} elapsedMs={elapsed} phase={phase} />
          </div>

          {phase === "error" && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-md p-4 text-[14px]"
              style={{ background: "rgba(255,45,45,0.06)", border: "1px solid rgba(255,45,45,0.3)" }}
            >
              <span className="text-primary">{error}</span>
              <button type="button" className="btn-ghost" onClick={() => submit()}>
                <RotateCcw size={13} /> Retry
              </button>
            </motion.div>
          )}

          {result && cachedMatch && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="mt-6 flex flex-wrap items-center justify-between gap-3 rounded-md border border-active bg-surface p-4 text-[14px]"
            >
              <span className="text-primary">
                <span className="mono mr-2 text-[11px] tracking-[2px] text-green">ALREADY CHECKED</span>
                This claim was verified {cachedMatch.at ? new Date(cachedMatch.at).toLocaleString("en-IN") : "earlier"}; showing that
                verdict instead of re-running the analysis.
              </span>
              <Link href={`/v/${cachedMatch.slug}`} className="btn-ghost">
                View public record
              </Link>
            </motion.div>
          )}

          {result && (
            <div ref={verdictRef} style={{ scrollMarginTop: 72 }}>
              <VerdictCard result={result} />
              <div className="mt-8 flex justify-center">
                <button type="button" className="btn-ghost !px-5 !py-2.5" onClick={reset}>
                  <RotateCcw size={14} /> Verify another claim
                </button>
              </div>
            </div>
          )}
        </section>
      )}
    </>
  );
}
