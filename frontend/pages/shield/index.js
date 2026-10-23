import { useState, useEffect, useCallback } from "react";
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
  ShieldAlert,
  Inbox as InboxIcon,
  CheckCircle2,
  Lock,
  ServerOff,
} from "lucide-react";
import toast from "react-hot-toast";

import ShieldNav from "@/components/shield/ShieldNav";
import ShieldBadge from "@/components/shield/ShieldBadge";
import OperatorTokenModal from "@/components/shield/OperatorTokenModal";
import {
  listInbox,
  listDemoEmails,
  runDemoEmail,
  escapeSuspiciousCharacters,
  ShieldApiError,
  hasOperatorToken,
} from "@/lib/shieldApi";

const LABELS = ["ALL", "SAFE", "SUSPICIOUS", "DANGEROUS"];

export default function ShieldInboxPage() {
  const router = useRouter();
  const [emails, setEmails] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeFilter, setActiveFilter] = useState("ALL");
  const [demoList, setDemoList] = useState([]);
  const [demoModalOpen, setDemoModalOpen] = useState(false);
  const [runningDemo, setRunningDemo] = useState(null);
  const [tokenModalOpen, setTokenModalOpen] = useState(false);

  // Read Gmail callback query params if redirected
  useEffect(() => {
    if (router.query.gmail === "connected") {
      toast.success("Gmail successfully connected (read-only)!");
    } else if (router.query.gmail === "error") {
      toast.error(`Gmail connection error: ${router.query.reason || "unknown"}`);
    }
  }, [router.query]);

  const fetchInbox = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const labelParam = activeFilter === "ALL" ? null : activeFilter;
      const res = await listInbox({ limit: 50, label: labelParam });
      setEmails(res.items || []);
    } catch (err) {
      console.error("Inbox load error:", err);
      setError({
        status: err.status,
        message: err.message || "Failed to load emails from Shield inbox.",
      });
    } finally {
      setLoading(false);
    }
  }, [activeFilter]);

  useEffect(() => {
    fetchInbox();
  }, [fetchInbox]);

  const loadDemos = async () => {
    try {
      const res = await listDemoEmails();
      setDemoList(res.items || []);
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
      await fetchInbox();
      if (res.email_id) {
        router.push(`/shield/report/${res.email_id}`);
      }
    } catch (err) {
      toast.error(`Failed to analyze demo: ${err.message}`);
    } finally {
      setRunningDemo(null);
    }
  };

  return (
    <>
      <Head>
        <title>FactFlow Shield — Email Inbox</title>
      </Head>

      <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6">
        <ShieldNav />

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
              Real-time heuristic &amp; LLM security inspection for every message and attachment.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            <button
              type="button"
              onClick={loadDemos}
              className="btn-red !py-2 !px-4 !text-[12.5px]"
            >
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
              <div
                key={i}
                className="animate-pulse rounded-lg border border-subtle bg-card p-5"
              >
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

        {/* Error State */}
        {!loading && error && (
          <div className="rounded-lg border border-red/40 bg-card p-6 text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-red/10 text-red">
              {error.status === 401 ? (
                <Lock size={24} />
              ) : error.status === 503 ? (
                <ServerOff size={24} />
              ) : (
                <AlertCircle size={24} />
              )}
            </div>
            <h3 className="font-display text-[16px] font-bold text-primary">
              {error.status === 401
                ? "Operator Authentication Required"
                : error.status === 503
                ? "Shield Routes Unavailable (503)"
                : "Unable to Load Shield Inbox"}
            </h3>
            <p className="mx-auto mt-2 max-w-md text-[13px] text-secondary">
              {error.status === 401
                ? "Viewing the inbox requires the backend OPERATOR_TOKEN. Enter your token once to save it in sessionStorage."
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
                  onClick={fetchInbox}
                  className="btn-red !py-2 !px-5 !text-[13px]"
                >
                  <RotateCw size={14} /> Retry
                </button>
              )}
            </div>
          </div>
        )}

        {/* Empty State */}
        {!loading && !error && emails.length === 0 && (
          <div className="rounded-lg border border-subtle bg-card p-10 text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-surface text-secondary">
              <InboxIcon size={24} />
            </div>
            <h3 className="font-display text-[16px] font-bold text-primary">
              No Analyzed Messages Found
            </h3>
            <p className="mx-auto mt-1 max-w-sm text-[13px] text-secondary">
              {activeFilter !== "ALL"
                ? `No messages matched the '${activeFilter}' verdict filter.`
                : "The Shield inbox is currently empty. Run the seeded demo attack cases or upload an email."}
            </p>
            <div className="mt-5 flex justify-center gap-3">
              {activeFilter !== "ALL" ? (
                <button
                  type="button"
                  onClick={() => setActiveFilter("ALL")}
                  className="btn-ghost"
                >
                  Clear Filter
                </button>
              ) : (
                <button
                  type="button"
                  onClick={loadDemos}
                  className="btn-red !py-2 !px-5 !text-[13px]"
                >
                  <Play size={13} /> Load Demo Emails
                </button>
              )}
            </div>
          </div>
        )}

        {/* Email List */}
        {!loading && !error && emails.length > 0 && (
          <div className="flex flex-col gap-2.5">
            {emails.map((email) => {
              const safeSubject = escapeSuspiciousCharacters(
                email.subject || "Untitled Email"
              );
              const safeFrom = escapeSuspiciousCharacters(
                email.from_addr || "unknown@example.com"
              );
              const safeReason = escapeSuspiciousCharacters(
                email.top_reason || "No signals detected"
              );

              return (
                <Link
                  key={email.email_id}
                  href={`/shield/report/${email.email_id}`}
                  className="group relative block overflow-hidden rounded-lg border border-subtle bg-card p-4 transition-all hover:border-active hover:bg-hover sm:p-5"
                >
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <ShieldBadge label={email.label} size="sm" />
                        <span className="mono text-[11px] text-muted">
                          ID: {email.email_id.slice(0, 8)}...
                        </span>
                        {email.quarantined && (
                          <span className="pill text-[9.5px] bg-red/10 border-red/40 text-red">
                            QUARANTINED
                          </span>
                        )}
                        {email.reported_phishing && (
                          <span className="pill text-[9.5px] bg-orange/10 border-orange/40 text-orange">
                            REPORTED
                          </span>
                        )}
                      </div>

                      <h2 className="mt-2 text-[15px] font-semibold text-primary transition-colors group-hover:text-red">
                        {safeSubject}
                      </h2>

                      <div className="mono mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-secondary">
                        <span className="truncate">From: {safeFrom}</span>
                        {email.created_at && (
                          <span className="text-muted">· {new Date(email.created_at).toLocaleDateString()}</span>
                        )}
                      </div>

                      <p className="mt-2 text-[12px] text-muted line-clamp-1">
                        Reason: {safeReason}
                      </p>
                    </div>

                    <div className="mt-2 flex shrink-0 items-center justify-between sm:mt-0 sm:flex-col sm:items-end">
                      <div className="mono text-[12px] font-bold text-secondary">
                        Score:{" "}
                        <span
                          className={
                            email.score > 70
                              ? "text-red font-bold"
                              : email.score > 30
                              ? "text-orange font-bold"
                              : "text-green font-bold"
                          }
                        >
                          {email.score}/100
                        </span>
                      </div>
                      <div className="flex items-center gap-1 text-[12px] text-secondary group-hover:text-primary mt-1">
                        <span>View Trust Report</span>
                        <ArrowRight size={13} className="transition-transform group-hover:translate-x-1" />
                      </div>
                    </div>
                  </div>
                </Link>
              );
            })}
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
                onClick={() => setDemoModalOpen(false)}
                className="rounded p-1 text-secondary hover:text-primary hover:bg-hover"
                aria-label="Close dialog"
              >
                ✕
              </button>
            </div>

            <div className="p-4 text-[12.5px] text-secondary border-b border-subtle bg-card">
              Select one of the benchmark demo emails to run through the Shield pipeline. Each test
              covers different threat vectors: white-on-white text, zero-width steganography, quishing QR, or benign alerts.
            </div>

            <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-2">
              {demoList.map((demo) => {
                const isRunning = runningDemo === demo.name;
                return (
                  <div
                    key={demo.name}
                    className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3.5 rounded-md border border-subtle bg-card hover:border-active hover:bg-hover transition-colors"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="mono text-[10.5px] text-red font-semibold uppercase">
                          {demo.name}
                        </span>
                        {demo.label && <ShieldBadge label={demo.label} size="sm" />}
                      </div>
                      <div className="font-medium text-[13.5px] text-primary truncate mt-1">
                        {escapeSuspiciousCharacters(demo.subject || demo.name)}
                      </div>
                      <div className="mono text-[11px] text-muted truncate">
                        {escapeSuspiciousCharacters(demo.from_addr || "")}
                      </div>
                    </div>

                    <button
                      type="button"
                      disabled={Boolean(runningDemo)}
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
                  </div>
                );
              })}
            </div>

            <div className="p-4 border-t border-subtle flex justify-end">
              <button
                type="button"
                onClick={() => setDemoModalOpen(false)}
                className="btn-ghost"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      <OperatorTokenModal
        isOpen={tokenModalOpen}
        onClose={() => setTokenModalOpen(false)}
        onTokenSaved={() => fetchInbox()}
      />
    </>
  );
}
