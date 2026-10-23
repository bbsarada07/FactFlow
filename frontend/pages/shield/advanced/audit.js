import { useState, useEffect, useCallback } from "react";
import Head from "next/head";
import {
  ShieldCheck,
  CheckCircle2,
  AlertTriangle,
  RotateCw,
  Search,
  Hash,
  Clock,
  User,
  Activity,
  ChevronDown,
  ChevronRight,
  ShieldAlert,
  Lock,
  ServerOff,
} from "lucide-react";
import toast from "react-hot-toast";

import ShieldNav from "@/components/shield/ShieldNav";
import OperatorTokenModal from "@/components/shield/OperatorTokenModal";
import {
  getAuditLog,
  verifyAuditChain,
  escapeSuspiciousCharacters,
} from "@/lib/shieldApi";

export default function ShieldAuditPage() {
  const [records, setRecords] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [verifying, setVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState(null);
  const [error, setError] = useState(null);
  const [searchEmailId, setSearchEmailId] = useState("");
  const [expandedSeq, setExpandedSeq] = useState(null);
  const [tokenModalOpen, setTokenModalOpen] = useState(false);

  const fetchAudit = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const emailIdParam = searchEmailId.trim() || null;
      const res = await getAuditLog({ limit: 50, emailId: emailIdParam });
      setRecords(res.items || []);
      setTotal(res.total || 0);
    } catch (err) {
      console.error("Audit load error:", err);
      setError({
        status: err.status,
        message: err.message || "Failed to load audit records.",
      });
    } finally {
      setLoading(false);
    }
  }, [searchEmailId]);

  useEffect(() => {
    fetchAudit();
  }, [fetchAudit]);

  const handleVerifyChain = async () => {
    setVerifying(true);
    try {
      const res = await verifyAuditChain();
      setVerifyResult(res);
      if (res.ok) {
        toast.success(`Audit chain verified intact! Checked ${res.checked} records.`);
      } else {
        toast.error(`Tamper detected at sequence #${res.first_broken_seq}!`);
      }
    } catch (err) {
      toast.error(`Chain verification failed: ${err.message}`);
    } finally {
      setVerifying(false);
    }
  };

  return (
    <>
      <Head>
        <title>FactFlow Shield — Audit Log</title>
      </Head>

      <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6">
        <ShieldNav />

        {/* Header */}
        <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <ShieldCheck className="text-red" size={22} />
              <h1 className="font-display text-[22px] font-bold text-primary sm:text-[26px]">
                Tamper-Evident Audit Log
              </h1>
            </div>
            <p className="mt-1 text-[13px] text-secondary">
              Cryptographically chained SHA-256 ledger of every scan, policy decision, approval, and transition.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2.5">
            <button
              type="button"
              disabled={verifying}
              onClick={handleVerifyChain}
              className="btn-red !py-2 !px-4 !text-[12.5px] flex items-center gap-1.5"
            >
              {verifying ? (
                <>
                  <RotateCw size={13} className="animate-spin" /> Verifying...
                </>
              ) : (
                <>
                  <CheckCircle2 size={13} /> Verify Chain
                </>
              )}
            </button>
            <button
              type="button"
              onClick={fetchAudit}
              disabled={loading}
              className="btn-ghost"
            >
              <RotateCw size={13} className={loading ? "animate-spin" : ""} />
              <span>Refresh</span>
            </button>
          </div>
        </div>

        {/* Verification Result Banner */}
        {verifyResult && (
          <div
            className={`mb-6 rounded-lg border p-4 text-[13px] font-mono flex items-center justify-between gap-3 ${
              verifyResult.ok
                ? "border-green/40 bg-green/10 text-green"
                : "border-red/40 bg-red/10 text-red"
            }`}
          >
            <div className="flex items-center gap-2">
              {verifyResult.ok ? (
                <CheckCircle2 size={18} className="shrink-0" />
              ) : (
                <ShieldAlert size={18} className="shrink-0" />
              )}
              <span>
                {verifyResult.ok
                  ? `CHAIN INTACT: ${verifyResult.checked} consecutive blocks verified without tampering.`
                  : `CHAIN BROKEN / TAMPERED at block #${verifyResult.first_broken_seq}: ${verifyResult.reason}`}
              </span>
            </div>
            {verifyResult.head_hash && (
              <span className="text-[10px] text-muted truncate max-w-xs hidden sm:inline">
                HEAD: {verifyResult.head_hash.slice(0, 16)}...
              </span>
            )}
          </div>
        )}

        {/* Search Bar */}
        <div className="mb-6 flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-2.5 text-muted" size={15} />
            <input
              type="text"
              value={searchEmailId}
              onChange={(e) => setSearchEmailId(e.target.value)}
              placeholder="Filter audit records by Email ID..."
              className="w-full rounded-md border border-subtle bg-card pl-9 pr-3 py-2 text-[13px] font-mono text-primary placeholder-muted outline-none focus:border-red"
            />
          </div>
          {searchEmailId && (
            <button
              type="button"
              onClick={() => setSearchEmailId("")}
              className="btn-ghost !text-[12px]"
            >
              Clear
            </button>
          )}
        </div>

        {/* Loading State */}
        {loading && (
          <div className="flex flex-col gap-3">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="animate-pulse rounded-lg border border-subtle bg-card p-4">
                <div className="h-4 w-48 rounded bg-surface mb-2" />
                <div className="h-3 w-1/3 rounded bg-surface" />
              </div>
            ))}
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
                : "Unable to Load Audit Records"}
            </h3>
            <p className="mx-auto mt-2 max-w-md text-[13px] text-secondary">
              {error.status === 401
                ? "The audit ledger is protected by OPERATOR_TOKEN. Enter your token in the operator authentication settings."
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
                  onClick={fetchAudit}
                  className="btn-red !py-2 !px-5 !text-[13px]"
                >
                  <RotateCw size={14} /> Retry
                </button>
              )}
            </div>
          </div>
        )}

        {/* Empty State */}
        {!loading && !error && records.length === 0 && (
          <div className="rounded-lg border border-subtle bg-card p-10 text-center">
            <ShieldCheck size={32} className="text-secondary mx-auto mb-2 opacity-50" />
            <h3 className="font-display text-[16px] font-bold text-primary">No Audit Records</h3>
            <p className="text-[13px] text-secondary mt-1">
              {searchEmailId
                ? `No events logged for email ID '${searchEmailId}'.`
                : "The audit ledger has not recorded any security events yet."}
            </p>
          </div>
        )}

        {/* Audit Records List */}
        {!loading && !error && records.length > 0 && (
          <div className="flex flex-col gap-2.5">
            {records.map((r) => {
              const isExpanded = expandedSeq === r.seq;
              return (
                <div
                  key={r.seq}
                  className="overflow-hidden rounded-lg border border-subtle bg-card transition-colors hover:border-active"
                >
                  <button
                    type="button"
                    onClick={() => setExpandedSeq(isExpanded ? null : r.seq)}
                    className="w-full text-left p-3.5 sm:p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2.5"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="mono text-[11px] font-bold text-red bg-red/10 border border-red/40 px-2 py-0.5 rounded">
                        #{r.seq}
                      </span>
                      <span className="mono text-[12px] font-semibold text-primary">
                        {r.event_type}
                      </span>
                      <span className="mono text-[11px] text-muted">
                        via {r.actor}
                      </span>
                    </div>

                    <div className="flex items-center justify-between sm:justify-end gap-3 mono text-[11px] text-secondary">
                      <span className="flex items-center gap-1">
                        <Clock size={11} />
                        {r.ts ? new Date(r.ts).toLocaleTimeString() : "—"}
                      </span>
                      <span className="text-muted truncate max-w-[120px] sm:max-w-[150px]">
                        HASH: {r.hash?.slice(0, 10)}...
                      </span>
                      {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </div>
                  </button>

                  {isExpanded && (
                    <div className="border-t border-subtle bg-surface p-4 text-[12px] font-mono flex flex-col gap-3">
                      <div>
                        <div className="text-muted text-[10.5px] uppercase mb-1">Cryptographic Link</div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px]">
                          <div className="rounded border border-subtle bg-base p-2 truncate">
                            <span className="text-muted">PREV HASH: </span>
                            <span className="text-secondary">{r.prev_hash}</span>
                          </div>
                          <div className="rounded border border-subtle bg-base p-2 truncate">
                            <span className="text-muted">CURRENT HASH: </span>
                            <span className="text-green">{r.hash}</span>
                          </div>
                        </div>
                      </div>

                      <div>
                        <div className="text-muted text-[10.5px] uppercase mb-1">Payload (Redacted)</div>
                        <pre className="rounded border border-subtle bg-base p-3 overflow-x-auto text-[11.5px] text-primary whitespace-pre-wrap">
                          {JSON.stringify(r.payload || {}, null, 2)}
                        </pre>
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <OperatorTokenModal
        isOpen={tokenModalOpen}
        onClose={() => setTokenModalOpen(false)}
        onTokenSaved={() => fetchAudit()}
      />
    </>
  );
}
