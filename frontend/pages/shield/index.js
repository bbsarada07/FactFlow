import { useState, useEffect, useCallback, useRef } from "react";
import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import {
  Mail,
  Play,
  RotateCw,
  AlertCircle,
  Filter,
  ArrowRight,
  Inbox as InboxIcon,
  Lock,
  ServerOff,
  Upload,
  ScanLine,
  ListChecks,
  Trash2,
  KeyRound,
} from "lucide-react";
import toast from "react-hot-toast";

import GmailBanner from "@/components/agent/GmailBanner";
import OutgoingQueue from "@/components/agent/OutgoingQueue";
import ShieldNav from "@/components/shield/ShieldNav";
import SignInAgain from "@/components/SignInAgain";
import ShieldBadge from "@/components/shield/ShieldBadge";
import {
  listInbox,
  listDemoEmails,
  runDemoEmail,
  runAllDemoEmails,
  analyzeMessage,
  getMyChecks,
  clearMyChecks,
  escapeSuspiciousCharacters,
  USE_MOCKS,
} from "@/lib/shieldApi";

const LABELS = ["ALL", "SAFE", "SUSPICIOUS", "DANGEROUS"];
const MAX_EMAIL_BYTES = 5 * 1024 * 1024;

function scoreClass(score) {
  if (score == null) return "text-muted";
  if (score >= 60) return "text-red font-bold";
  if (score >= 25) return "text-orange font-bold";
  return "text-green font-bold";
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function EmailRow({ email }) {
  // Never let a missing label fall back to ShieldBadge's SAFE default.
  const label = email.label || "UNKNOWN";
  return (
    <Link
      href={`/shield/report/${email.email_id}`}
      className="group relative block overflow-hidden rounded-lg border border-subtle bg-card p-4 transition-all hover:border-active hover:bg-hover sm:p-5"
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <ShieldBadge label={label} size="sm" />
            {!email.label && (
              <span className="pill text-[9.5px] border-subtle text-secondary">
                {email.status === "failed" ? "FAILED" : "OPEN TO SEE VERDICT"}
              </span>
            )}
            <span className="mono text-[11px] text-muted">ID: {email.email_id.slice(0, 8)}...</span>
            {email.source && (
              <span className="pill text-[9.5px] border-subtle text-secondary uppercase">{email.source}</span>
            )}
            {email.quarantined && (
              <span className="pill text-[9.5px] bg-red/10 border-red/40 text-red">QUARANTINED</span>
            )}
            {email.reported_phishing && (
              <span className="pill text-[9.5px] bg-orange/10 border-orange/40 text-orange">REPORTED</span>
            )}
          </div>

          <h2 className="mt-2 text-[15px] font-semibold text-primary transition-colors group-hover:text-red">
            {escapeSuspiciousCharacters(email.subject || email.demo_name || "Untitled Email")}
          </h2>

          <div className="mono mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-secondary">
            <span className="truncate">From: {escapeSuspiciousCharacters(email.from_addr || "unknown")}</span>
            {email.created_at && (
              <span className="text-muted">· {new Date(email.created_at).toLocaleString()}</span>
            )}
          </div>

          {email.top_reason && (
            <p className="mt-2 text-[12px] text-muted line-clamp-1">
              Reason: {escapeSuspiciousCharacters(email.top_reason)}
            </p>
          )}
        </div>

        <div className="mt-2 flex shrink-0 items-center justify-between sm:mt-0 sm:flex-col sm:items-end">
          <div className="mono text-[12px] font-bold text-secondary">
            Score: <span className={scoreClass(email.score)}>{email.score ?? "–"}/100</span>
          </div>
          <div className="flex items-center gap-1 text-[12px] text-secondary group-hover:text-primary mt-1">
            <span>View Trust Report</span>
            <ArrowRight size={13} className="transition-transform group-hover:translate-x-1" />
          </div>
        </div>
      </div>
    </Link>
  );
}

export default function ShieldInboxPage() {
  const router = useRouter();
  const [emails, setEmails] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [view, setView] = useState("operator"); // "operator": your inbox from the server | "session": this tab's checks (if it fails)
  const [activeFilter, setActiveFilter] = useState("ALL");
  const [myChecks, setMyChecks] = useState([]);

  const [demoList, setDemoList] = useState([]);
  const [demoModalOpen, setDemoModalOpen] = useState(false);
  const [runningDemo, setRunningDemo] = useState(null);
  const [batch, setBatch] = useState(null); // { done, total, waiting, results: {name: {label, score, error}} }
  const batchAbort = useRef(null);

  const [pasteOpen, setPasteOpen] = useState(false);
  const [rawText, setRawText] = useState("");
  const [emlFile, setEmlFile] = useState(null);
  const [scanMode, setScanMode] = useState("rules");
  const [scanning, setScanning] = useState(false);
  const fileInput = useRef(null);

  // Old Gmail callback links (?gmail=...) now belong to the Settings page
  useEffect(() => {
    if (router.query.gmail) router.replace("/settings" + window.location.search);
  }, [router]);

  const refreshMyChecks = useCallback(() => setMyChecks(getMyChecks()), []);

  const fetchInbox = useCallback(async () => {
    refreshMyChecks();
    setError(null);
    setLoading(true);
    try {
      const labelParam = activeFilter === "ALL" ? null : activeFilter;
      const res = await listInbox({ limit: 50, label: labelParam });
      setEmails(res.items || []);
      setView("operator");
    } catch (err) {
      console.error("Inbox load error:", err);
      setView("session");
      setError({ status: err.status, message: err.message || "Failed to load emails from Shield inbox." });
    } finally {
      setLoading(false);
    }
  }, [activeFilter, refreshMyChecks]);

  useEffect(() => {
    fetchInbox();
  }, [fetchInbox]);


  useEffect(() => () => batchAbort.current?.abort(), []);

  const loadDemos = async () => {
    try {
      const res = await listDemoEmails();
      setDemoList(res.items || []);
      setBatch(null);
      setDemoModalOpen(true);
    } catch (err) {
      toast.error(`Failed to load demo list: ${err.message}`);
    }
  };

  const handleRunDemo = async (demoName) => {
    setRunningDemo(demoName);
    try {
      const res = await runDemoEmail(demoName, { mode: "rules" });
      toast.success(`Analyzed demo: ${demoName}`);
      setDemoModalOpen(false);
      refreshMyChecks();
      if (res.email_id) {
        router.push(`/shield/report/${res.email_id}`);
      }
    } catch (err) {
      toast.error(`Failed to analyze demo: ${err.message}`);
    } finally {
      setRunningDemo(null);
    }
  };

  const handleRunAll = async () => {
    const names = demoList.map((d) => d.name);
    if (!names.length) return;
    const controller = new AbortController();
    batchAbort.current = controller;
    setBatch({ done: 0, total: names.length, waiting: null, results: {}, running: true });
    await runAllDemoEmails(
      names,
      ({ index, name, result, error: err, waitingSeconds }) => {
        setBatch((b) => {
          if (!b) return b;
          if (waitingSeconds) return { ...b, waiting: { name, seconds: waitingSeconds } };
          const o = result?.verdict?.overall;
          return {
            ...b,
            waiting: null,
            done: index + 1,
            results: {
              ...b.results,
              [name]: err
                ? { error: err.message }
                : { label: o?.label, score: o?.score, email_id: result?.email_id },
            },
          };
        });
      },
      { signal: controller.signal }
    );
    setBatch((b) => (b ? { ...b, running: false, waiting: null } : b));
    refreshMyChecks();
    if (view === "operator") fetchInbox();
  };

  const handleScan = async (e) => {
    e.preventDefault();
    if (!emlFile && !rawText.trim()) {
      toast.error("Paste an email or choose an .eml file first.");
      return;
    }
    setScanning(true);
    try {
      let payload;
      if (emlFile) {
        if (emlFile.size > MAX_EMAIL_BYTES) throw new Error("That file is larger than 5 MB.");
        payload = { eml_base64: await fileToBase64(emlFile), source: "upload", mode: scanMode };
      } else {
        payload = { raw: rawText, source: "paste", mode: scanMode };
      }
      const res = await analyzeMessage(payload);
      toast.success(res.cached ? "Already checked before: showing the saved report." : "Email submitted for analysis.");
      setRawText("");
      setEmlFile(null);
      if (fileInput.current) fileInput.current.value = "";
      router.push(`/shield/report/${res.email_id}`);
    } catch (err) {
      toast.error(`Scan failed: ${err.message}`);
    } finally {
      setScanning(false);
    }
  };

  const shownChecks =
    activeFilter === "ALL" ? myChecks : myChecks.filter((c) => c.label === activeFilter);
  const list = view === "operator" ? emails : shownChecks;

  return (
    <>
      <Head>
        <title>FactFlow Shield — Email Inbox</title>
      </Head>

      <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
        <ShieldNav />
        <GmailBanner />
        <OutgoingQueue limit={6} />

        {/* Page Header */}
        <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Mail className="text-red" size={22} />
              <h1 className="font-display text-[22px] font-bold text-primary sm:text-[26px]">
                Email Trust Inbox
              </h1>
            </div>
            <p className="mt-1 text-[13px] text-secondary">
              Checks every message for hidden text, prompt injection, spoofed senders, bad links, QR codes and scams.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            <button type="button" onClick={() => setPasteOpen((o) => !o)} className="btn-ghost">
              <ScanLine size={13} /> <span>Check an Email</span>
            </button>
            <button type="button" onClick={loadDemos} className="btn-red !py-2 !px-4 !text-[12.5px]">
              <Play size={13} /> Run Demo Emails
            </button>
            <button
              type="button"
              onClick={fetchInbox}
              disabled={loading}
              className="btn-ghost"
              aria-label="Refresh inbox"
            >
              <RotateCw size={13} className={loading ? "animate-spin" : ""} />
              <span>Refresh</span>
            </button>
          </div>
        </div>

        {/* Check your own email */}
        {pasteOpen && (
          <form onSubmit={handleScan} className="mb-6 rounded-lg border border-subtle bg-surface p-4 sm:p-5">
            <div className="flex items-center gap-2 mb-2">
              <ScanLine size={16} className="text-red" />
              <h2 className="font-display text-[15px] font-bold text-primary">Check an email</h2>
            </div>
            <p className="text-[12.5px] text-secondary mb-3">
              Paste the full source (in Gmail: ⋮ → <em>Show original</em>; in Outlook: <em>View message source</em>) for
              the best result, or just the text. Or upload a saved <code>.eml</code> file. No token needed.
            </p>
            <textarea
              value={rawText}
              onChange={(e) => {
                setRawText(e.target.value);
                if (e.target.value) setEmlFile(null);
              }}
              disabled={Boolean(emlFile)}
              rows={7}
              placeholder={"From: someone@example.com\nSubject: ...\n\nMessage body..."}
              className="w-full rounded-md border border-subtle bg-card px-3 py-2.5 text-[12.5px] font-mono text-primary placeholder-muted outline-none focus:border-red disabled:opacity-50"
            />
            <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex flex-wrap items-center gap-3">
                <label className="btn-ghost cursor-pointer !py-1.5 !text-[12px]">
                  <Upload size={13} />
                  <span>{emlFile ? escapeSuspiciousCharacters(emlFile.name) : "Upload .eml"}</span>
                  <input
                    ref={fileInput}
                    type="file"
                    accept=".eml,message/rfc822,text/plain"
                    className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0] || null;
                      setEmlFile(f);
                      if (f) setRawText("");
                    }}
                  />
                </label>
                {emlFile && (
                  <button
                    type="button"
                    className="text-[12px] text-secondary hover:text-red"
                    onClick={() => {
                      setEmlFile(null);
                      if (fileInput.current) fileInput.current.value = "";
                    }}
                  >
                    Remove file
                  </button>
                )}
                <label className="flex items-center gap-2 text-[12px] text-secondary">
                  <span>Mode</span>
                  <select
                    value={scanMode}
                    onChange={(e) => setScanMode(e.target.value)}
                    className="rounded border border-subtle bg-card px-2 py-1 text-[12px] text-primary"
                  >
                    <option value="rules">Rules only (instant, no AI)</option>
                    <option value="full">Full (rules + AI reader + fact check)</option>
                  </select>
                </label>
              </div>
              <button type="submit" disabled={scanning} className="btn-red !py-2 !px-5 !text-[13px]">
                {scanning ? (
                  <>
                    <RotateCw size={13} className="animate-spin" /> Scanning...
                  </>
                ) : (
                  <>
                    <ScanLine size={13} /> Scan
                  </>
                )}
              </button>
            </div>
          </form>
        )}

        {/* Which list is shown */}
        {!loading && view === "session" && !USE_MOCKS && (
          <div className="mb-4 flex flex-col gap-3 rounded-lg border border-subtle bg-card p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-start gap-3">
              <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-surface text-secondary">
                {error?.status === 503 ? <ServerOff size={17} /> : error?.status === 401 ? <Lock size={17} /> : <ListChecks size={17} />}
              </div>
              <div className="text-[12.5px] text-secondary">
                <div className="font-semibold text-primary text-[13.5px]">My checks (this browser tab)</div>
                {error?.status === 401
                  ? "Your session has ended, so only the messages you checked in this tab are shown. Sign in again to see your inbox."
                  : error
                  ? `Your inbox could not be loaded (${error.message}), so only the messages you checked in this tab are shown.`
                  : "The messages you checked in this tab."}
              </div>
            </div>
            <div className="flex shrink-0 gap-2">
              {myChecks.length > 0 && (
                <button
                  type="button"
                  onClick={() => {
                    clearMyChecks();
                    refreshMyChecks();
                  }}
                  className="btn-ghost !py-1.5 !text-[12px]"
                >
                  <Trash2 size={12} /> Clear list
                </button>
              )}
              <SignInAgain />
            </div>
          </div>
        )}

        {/* Filter Bar */}
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-subtle bg-surface p-3">
          <div className="flex items-center gap-2">
            <Filter size={14} className="text-secondary" />
            <span className="mono text-[11px] tracking-[1.5px] uppercase text-secondary">
              Filter by Verdict:
            </span>
          </div>

          <div className="flex flex-wrap gap-1.5">
            {LABELS.map((label) => {
              const active = activeFilter === label;
              return (
                <button
                  key={label}
                  type="button"
                  onClick={() => setActiveFilter(label)}
                  data-active={active}
                  className={`pill text-[11px] transition-all ${
                    active
                      ? label === "SAFE"
                        ? "bg-green/20 border-green/60 text-green font-bold"
                        : label === "SUSPICIOUS"
                        ? "bg-orange/20 border-orange/60 text-orange font-bold"
                        : label === "DANGEROUS"
                        ? "bg-red/20 border-red/60 text-red font-bold"
                        : "bg-primary/20 border-primary/50 text-primary font-bold"
                      : "border-subtle text-secondary hover:text-primary hover:bg-hover"
                  }`}
                >
                  {label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Content Area */}
        {loading && (
          <div className="flex flex-col gap-3">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="animate-pulse rounded-lg border border-subtle bg-card p-5">
                <div className="flex items-center justify-between gap-4">
                  <div className="h-4 w-32 rounded bg-surface" />
                  <div className="h-5 w-20 rounded-full bg-surface" />
                </div>
                <div className="mt-3 h-5 w-3/4 rounded bg-surface" />
                <div className="mt-2 h-3 w-1/2 rounded bg-surface" />
              </div>
            ))}
          </div>
        )}

        {/* Error loading your inbox */}
        {!loading && error && view === "operator" && (
          <div className="rounded-lg border border-red/40 bg-card p-6 text-center">
            <AlertCircle size={24} className="mx-auto mb-3 text-red" />
            <p className="mx-auto max-w-md text-[13px] text-secondary">{error.message}</p>
            <button type="button" onClick={fetchInbox} className="btn-red !py-2 !px-5 !text-[13px] mt-4">
              <RotateCw size={14} /> Retry
            </button>
          </div>
        )}

        {/* Empty State */}
        {!loading && list.length === 0 && (
          <div className="rounded-lg border border-subtle bg-card p-10 text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-surface text-secondary">
              <InboxIcon size={24} />
            </div>
            <h3 className="font-display text-[16px] font-bold text-primary">No Analyzed Messages Found</h3>
            <p className="mx-auto mt-1 max-w-sm text-[13px] text-secondary">
              {activeFilter !== "ALL"
                ? `No messages matched the '${activeFilter}' verdict filter.`
                : "Run the seeded demo attack cases or check an email of your own."}
            </p>
            <div className="mt-5 flex justify-center gap-3">
              {activeFilter !== "ALL" ? (
                <button type="button" onClick={() => setActiveFilter("ALL")} className="btn-ghost">
                  Clear Filter
                </button>
              ) : (
                <>
                  <button type="button" onClick={loadDemos} className="btn-red !py-2 !px-5 !text-[13px]">
                    <Play size={13} /> Load Demo Emails
                  </button>
                  <button type="button" onClick={() => setPasteOpen(true)} className="btn-ghost">
                    <ScanLine size={13} /> Check an Email
                  </button>
                </>
              )}
            </div>
          </div>
        )}

        {/* Email List */}
        {!loading && list.length > 0 && (
          <div className="flex flex-col gap-2.5">
            {list.map((email) => (
              <EmailRow key={email.email_id} email={email} />
            ))}
          </div>
        )}
      </div>

      {/* Demo Email Selection Modal */}
      {demoModalOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="demo-modal-title"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm"
        >
          <div className="relative w-full max-w-xl max-h-[85vh] flex flex-col overflow-hidden rounded-lg border border-subtle bg-surface shadow-2xl">
            <div className="flex items-center justify-between p-5 border-b border-subtle">
              <div className="flex items-center gap-2">
                <Play className="text-red" size={18} />
                <h3 id="demo-modal-title" className="font-display text-[16px] font-bold text-primary">
                  Run Seeded Demo Emails
                </h3>
              </div>
              <button
                type="button"
                onClick={() => {
                  batchAbort.current?.abort();
                  setDemoModalOpen(false);
                }}
                className="rounded p-1 text-secondary hover:text-primary hover:bg-hover"
                aria-label="Close dialog"
              >
                ✕
              </button>
            </div>

            <div className="p-4 text-[12.5px] text-secondary border-b border-subtle bg-card flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <span>
                Benign mail, hidden-text injections, lookalike senders, Hindi and Telugu scams, UPI fraud and a QR code.
              </span>
              <button
                type="button"
                disabled={Boolean(runningDemo) || batch?.running || demoList.length === 0}
                onClick={handleRunAll}
                className="btn-red shrink-0 !py-1.5 !px-3 !text-[12px]"
              >
                {batch?.running ? (
                  <>
                    <RotateCw size={12} className="animate-spin" /> {batch.done}/{batch.total}
                  </>
                ) : (
                  <>
                    <Play size={12} /> Run all {demoList.length}
                  </>
                )}
              </button>
            </div>

            {batch?.waiting && (
              <div className="px-4 py-2 text-[12px] text-orange border-b border-subtle">
                Server rate limit reached; waiting {batch.waiting.seconds}s before continuing with {batch.waiting.name}...
              </div>
            )}

            <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-2">
              {demoList.map((demo) => {
                const isRunning = runningDemo === demo.name;
                const outcome = batch?.results?.[demo.name];
                return (
                  <div
                    key={demo.name}
                    className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3.5 rounded-md border border-subtle bg-card hover:border-active hover:bg-hover transition-colors"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="mono text-[10.5px] text-red font-semibold uppercase">{demo.name}</span>
                      </div>
                      <div className="font-medium text-[13.5px] text-primary truncate mt-1">
                        {escapeSuspiciousCharacters(demo.subject || demo.name)}
                      </div>
                      <div className="mono text-[11px] text-muted truncate">
                        {escapeSuspiciousCharacters(demo.from_addr || "")}
                      </div>
                    </div>

                    {outcome ? (
                      outcome.error ? (
                        <span className="text-[11.5px] text-red self-end sm:self-center">{outcome.error}</span>
                      ) : (
                        <Link
                          href={`/shield/report/${outcome.email_id}`}
                          className="flex shrink-0 items-center gap-2 self-end sm:self-center"
                        >
                          <ShieldBadge label={outcome.label || "UNKNOWN"} size="sm" />
                          <span className={`mono text-[11.5px] ${scoreClass(outcome.score)}`}>{outcome.score}</span>
                          <ArrowRight size={13} className="text-secondary" />
                        </Link>
                      )
                    ) : (
                      <button
                        type="button"
                        disabled={Boolean(runningDemo) || batch?.running}
                        onClick={() => handleRunDemo(demo.name)}
                        className="btn-ghost shrink-0 !py-1.5 !px-3 !text-[12px] self-end sm:self-center"
                      >
                        {isRunning ? (
                          <>
                            <RotateCw size={12} className="animate-spin text-red" />
                            <span>Scanning...</span>
                          </>
                        ) : (
                          <>
                            <Play size={12} className="text-red" />
                            <span>Analyze</span>
                          </>
                        )}
                      </button>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="p-4 border-t border-subtle flex justify-end">
              <button
                type="button"
                onClick={() => {
                  batchAbort.current?.abort();
                  setDemoModalOpen(false);
                }}
                className="btn-ghost"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
