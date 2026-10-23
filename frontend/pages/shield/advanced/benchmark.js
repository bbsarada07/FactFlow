import { useState, useEffect, useCallback } from "react";
import Head from "next/head";
import {
  BarChart3,
  Play,
  RotateCw,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Clock,
  Layers,
  ShieldCheck,
  Zap,
  Lock,
  ServerOff,
} from "lucide-react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  Cell,
} from "recharts";
import toast from "react-hot-toast";

import ShieldNav from "@/components/shield/ShieldNav";
import OperatorTokenModal from "@/components/shield/OperatorTokenModal";
import {
  getLatestBenchmark,
  listBenchmarkRuns,
  runBenchmark,
} from "@/lib/shieldApi";

const CATEGORY_NAMES = {
  hidden_css: "Hidden CSS",
  zero_width: "Zero-Width Tags",
  comments_and_tags: "HTML Comments",
  prompt_injection: "Prompt Injection",
  indian_scams: "Indian Scams",
};

export default function ShieldBenchmarkPage() {
  const [latestRun, setLatestRun] = useState(null);
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [runMode, setRunMode] = useState("rules"); // 'rules' | 'llm'
  const [error, setError] = useState(null);
  const [tokenModalOpen, setTokenModalOpen] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [latest, history] = await Promise.all([
        getLatestBenchmark().catch(() => null),
        listBenchmarkRuns().catch(() => ({ runs: [] })),
      ]);
      setLatestRun(latest);
      setRuns(history?.runs || []);
    } catch (err) {
      console.error("Benchmark load error:", err);
      setError({
        status: err.status,
        message: err.message || "Failed to load benchmark results.",
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleRunBenchmark = async () => {
    setRunning(true);
    try {
      const res = await runBenchmark({ mode: runMode });
      toast.success(`Benchmark completed in ${runMode.toUpperCase()} mode!`);
      setLatestRun(res);
      await fetchData();
    } catch (err) {
      console.error("Benchmark run error:", err);
      if (err.status === 409) {
        toast.error("A benchmark is already running. Please wait for it to finish.");
      } else {
        toast.error(`Benchmark failed: ${err.message}`);
      }
    } finally {
      setRunning(false);
    }
  };

  // Prepare chart data from per_category
  const chartData = latestRun?.per_category
    ? Object.entries(latestRun.per_category).map(([key, val]) => ({
        name: CATEGORY_NAMES[key] || key,
        detected: val.detected || 0,
        missed: (val.total || 0) - (val.detected || 0),
        rate: val.rate || 0,
      }))
    : [];

  const cm = latestRun?.confusion_matrix || { TP: 0, FP: 0, TN: 0, FN: 0 };

  return (
    <>
      <Head>
        <title>FactFlow Shield — Red-Team Benchmark</title>
      </Head>

      <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6">
        <ShieldNav />

        {/* Header */}
        <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <BarChart3 className="text-red" size={22} />
              <h1 className="font-display text-[22px] font-bold text-primary sm:text-[26px]">
                Red-Team Detection Benchmark
              </h1>
            </div>
            <p className="mt-1 text-[13px] text-secondary">
              Quantitative evaluation over the adversarial attack suite &amp; benign email corpus.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center rounded-lg border border-subtle bg-surface p-1">
              <button
                type="button"
                onClick={() => setRunMode("rules")}
                className={`px-3 py-1 text-[11.5px] rounded-md font-mono transition-colors ${
                  runMode === "rules"
                    ? "bg-card text-primary font-bold border border-active shadow-sm"
                    : "text-muted hover:text-secondary"
                }`}
              >
                Rules Mode
              </button>
              <button
                type="button"
                onClick={() => setRunMode("llm")}
                className={`px-3 py-1 text-[11.5px] rounded-md font-mono transition-colors ${
                  runMode === "llm"
                    ? "bg-card text-primary font-bold border border-active shadow-sm"
                    : "text-muted hover:text-secondary"
                }`}
              >
                LLM Mode
              </button>
            </div>

            <button
              type="button"
              disabled={running}
              onClick={handleRunBenchmark}
              className="btn-red !py-2 !px-4 !text-[12.5px]"
            >
              {running ? (
                <>
                  <RotateCw size={13} className="animate-spin" /> Evaluating...
                </>
              ) : (
                <>
                  <Play size={13} /> Run Benchmark
                </>
              )}
            </button>
          </div>
        </div>

        {/* Loading State */}
        {loading && (
          <div className="flex flex-col gap-4">
            <div className="animate-pulse rounded-lg border border-subtle bg-card p-8">
              <div className="h-6 w-48 rounded bg-surface mb-4" />
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                {[1, 2, 3, 4].map((i) => (
                  <div key={i} className="h-20 rounded bg-surface" />
                ))}
              </div>
            </div>
          </div>
        )}

        {/* Error State */}
        {!loading && error && (
          <div className="rounded-lg border border-red/40 bg-card p-6 text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-red/10 text-red">
              {error.status === 401 ? <Lock size={24} /> : error.status === 503 ? <ServerOff size={24} /> : <AlertTriangle size={24} />}
            </div>
            <h3 className="font-display text-[16px] font-bold text-primary">
              {error.status === 401
                ? "Operator Token Required"
                : "Unable to Load Benchmark"}
            </h3>
            <p className="mx-auto mt-2 max-w-md text-[13px] text-secondary">
              {error.status === 401
                ? "Viewing benchmark metrics requires OPERATOR_TOKEN authentication."
                : error.message}
            </p>
            <div className="mt-4 flex justify-center gap-3">
              {error.status === 401 ? (
                <button
                  type="button"
                  onClick={() => setTokenModalOpen(true)}
                  className="btn-red !py-2 !px-5 !text-[13px]"
                >
                  Enter Operator Token
                </button>
              ) : (
                <button
                  type="button"
                  onClick={fetchData}
                  className="btn-red !py-2 !px-5 !text-[13px]"
                >
                  <RotateCw size={14} /> Retry
                </button>
              )}
            </div>
          </div>
        )}

        {/* Content */}
        {!loading && !error && latestRun && (
          <div className="flex flex-col gap-6">
            {/* KPI Cards */}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="rounded-lg border border-green/30 bg-card p-4">
                <div className="mono text-[10.5px] uppercase tracking-wider text-muted">Detection Rate</div>
                <div className="font-display text-[26px] sm:text-[32px] font-bold text-green mt-1">
                  {latestRun.detection_rate}%
                </div>
                <div className="mono text-[11px] text-secondary mt-1">
                  {latestRun.confusion_matrix?.TP || 0} / {latestRun.attack_count} attacks
                </div>
              </div>

              <div className="rounded-lg border border-orange/30 bg-card p-4">
                <div className="mono text-[10.5px] uppercase tracking-wider text-muted">False Positive Rate</div>
                <div className="font-display text-[26px] sm:text-[32px] font-bold text-orange mt-1">
                  {latestRun.false_positive_rate}%
                </div>
                <div className="mono text-[11px] text-secondary mt-1">
                  {latestRun.confusion_matrix?.FP || 0} benign flagged
                </div>
              </div>

              <div className="rounded-lg border border-subtle bg-card p-4">
                <div className="mono text-[10.5px] uppercase tracking-wider text-muted">Policy Block Rate</div>
                <div className="font-display text-[26px] sm:text-[32px] font-bold text-primary mt-1">
                  {latestRun.policy_block_rate}%
                </div>
                <div className="mono text-[11px] text-secondary mt-1">Zero malicious bypass</div>
              </div>

              <div className="rounded-lg border border-subtle bg-card p-4">
                <div className="mono text-[10.5px] uppercase tracking-wider text-muted">Latency (p50 / p95)</div>
                <div className="font-display text-[22px] sm:text-[26px] font-bold text-primary mt-1">
                  {latestRun.latency_p50_ms}ms
                </div>
                <div className="mono text-[11px] text-secondary mt-1">
                  p95: {latestRun.latency_p95_ms}ms
                </div>
              </div>
            </div>

            {/* Recharts Bar Chart: Per Category */}
            <div className="rounded-lg border border-subtle bg-surface p-5">
              <div className="flex items-center justify-between pb-3 mb-4 border-b border-subtle">
                <div className="flex items-center gap-2">
                  <BarChart3 size={17} className="text-red" />
                  <h3 className="font-display text-[16px] font-bold text-primary">
                    Detection by Threat Category
                  </h3>
                </div>
                <span className="mono text-[11px] text-muted">
                  DATASET: {latestRun.dataset_size} CASES
                </span>
              </div>

              <div className="h-64 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={chartData}
                    margin={{ top: 10, right: 10, left: -20, bottom: 20 }}
                  >
                    <XAxis
                      dataKey="name"
                      stroke="#6a6a80"
                      fontSize={11}
                      tickLine={false}
                      interval={0}
                      angle={-15}
                      textAnchor="end"
                    />
                    <YAxis stroke="#6a6a80" fontSize={11} tickLine={false} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#111118",
                        borderColor: "#2A2A3A",
                        borderRadius: "8px",
                        fontSize: "12px",
                        fontFamily: "var(--font-mono)",
                      }}
                    />
                    <Legend wrapperStyle={{ fontSize: "12px", paddingTop: "8px" }} />
                    <Bar dataKey="detected" fill="#00E676" name="Detected" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="missed" fill="#FF2D2D" name="Missed" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Confusion Matrix Card */}
            <div className="rounded-lg border border-subtle bg-surface p-5">
              <h3 className="font-display text-[16px] font-bold text-primary mb-3">
                Confusion Matrix
              </h3>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 font-mono text-center">
                <div className="rounded-md border border-green/30 bg-card p-3">
                  <div className="text-[11px] text-muted">TRUE POSITIVE (TP)</div>
                  <div className="text-[20px] font-bold text-green mt-1">{cm.TP}</div>
                  <div className="text-[10px] text-secondary">Attack correctly caught</div>
                </div>
                <div className="rounded-md border border-orange/30 bg-card p-3">
                  <div className="text-[11px] text-muted">FALSE POSITIVE (FP)</div>
                  <div className="text-[20px] font-bold text-orange mt-1">{cm.FP}</div>
                  <div className="text-[10px] text-secondary">Benign flagged</div>
                </div>
                <div className="rounded-md border border-subtle bg-card p-3">
                  <div className="text-[11px] text-muted">TRUE NEGATIVE (TN)</div>
                  <div className="text-[20px] font-bold text-primary mt-1">{cm.TN}</div>
                  <div className="text-[10px] text-secondary">Benign passed safe</div>
                </div>
                <div className="rounded-md border border-red/40 bg-card p-3">
                  <div className="text-[11px] text-muted">FALSE NEGATIVE (FN)</div>
                  <div className="text-[20px] font-bold text-red mt-1">{cm.FN}</div>
                  <div className="text-[10px] text-secondary">Attack slipped through</div>
                </div>
              </div>
            </div>

            {/* Run History List */}
            {runs.length > 0 && (
              <div className="rounded-lg border border-subtle bg-surface p-5">
                <h3 className="font-display text-[16px] font-bold text-primary mb-3">
                  Benchmark Run History
                </h3>
                <div className="flex flex-col gap-2">
                  {runs.map((r) => (
                    <div
                      key={r.id}
                      className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 p-3 rounded-md border border-subtle bg-card text-[12px] font-mono"
                    >
                      <div className="flex items-center gap-2">
                        <span className="text-red font-bold">{r.id}</span>
                        <span className="pill text-[9px] bg-subtle text-secondary uppercase">
                          {r.mode}
                        </span>
                      </div>
                      <div className="flex items-center gap-4 text-secondary">
                        <span>Detection: <strong className="text-green">{r.detection_rate}%</strong></span>
                        <span>FP: <strong className="text-orange">{r.false_positive_rate}%</strong></span>
                        <span className="text-muted">{r.created_at ? new Date(r.created_at).toLocaleTimeString() : ""}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <OperatorTokenModal
        isOpen={tokenModalOpen}
        onClose={() => setTokenModalOpen(false)}
        onTokenSaved={() => fetchData()}
      />
    </>
  );
}
