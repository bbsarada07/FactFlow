import { useState, useEffect, useCallback } from "react";
import Head from "next/head";
import Link from "next/link";
import {
  CheckSquare,
  ShieldAlert,
  AlertTriangle,
  RotateCw,
  Check,
  X,
  Clock,
  ArrowRight,
  User,
  Shield,
  HelpCircle,
  Lock,
  ServerOff,
} from "lucide-react";
import toast from "react-hot-toast";

import ShieldNav from "@/components/shield/ShieldNav";
import ShieldBadge from "@/components/shield/ShieldBadge";
import OperatorTokenModal from "@/components/shield/OperatorTokenModal";
import {
  listApprovals,
  decideApproval,
  escapeSuspiciousCharacters,
  ShieldApiError,
} from "@/lib/shieldApi";

const STATUS_FILTERS = ["all", "pending", "approved", "denied", "expired"];

export default function ShieldApprovalsPage() {
  const [approvals, setApprovals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState("pending");
  const [decidingId, setDecidingId] = useState(null);
  const [tokenModalOpen, setTokenModalOpen] = useState(false);

  const fetchApprovals = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const statusParam = filter === "all" ? null : filter;
      const res = await listApprovals(statusParam, 100);
      setApprovals(res.items || []);
    } catch (err) {
      console.error("Error loading approvals:", err);
      setError({
        status: err.status,
        message: err.message || "Failed to load approval requests.",
      });
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    fetchApprovals();
  }, [fetchApprovals]);

  const handleDecision = async (approval, decision) => {
    if (!approval.token) {
      toast.error("Missing single-use approval token. Please refresh the page.");
      return;
    }

    setDecidingId(approval.id);
    try {
      const res = await decideApproval(approval.id, decision, approval.token);
      toast.success(
        decision === "approve"
          ? "Step approved once. Task executed safely into simulated outbox."
          : "Step denied. Protective block recorded."
      );
      // Refresh list
      await fetchApprovals();
    } catch (err) {
      console.error("Decision error:", err);
      if (err.status === 403) {
        toast.error("Forbidden (403): Approval token was invalid or mismatched.");
      } else if (err.status === 409) {
        toast.error("Conflict (409): This approval was already decided.");
      } else if (err.status === 410) {
        toast.error("Expired (410): The 10-minute approval window has elapsed.");
      } else {
        toast.error(`Error (${err.status}): ${err.message}`);
      }
    } finally {
      setDecidingId(null);
    }
  };

  return (
    <>
      <Head>
        <title>FactFlow Shield — Human-in-the-Loop Approvals</title>
      </Head>

      <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6">
        <ShieldNav />

        {/* Header */}
        <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <CheckSquare className="text-red" size={22} />
              <h1 className="font-display text-[22px] font-bold text-primary sm:text-[26px]">
                Human-in-the-Loop Approvals
              </h1>
            </div>
            <p className="mt-1 text-[13px] text-secondary">
              Review and authorize sensitive autonomous actions (forwarding emails, external sharing, opening links).
            </p>
          </div>

          <button
            type="button"
            onClick={fetchApprovals}
            disabled={loading}
            className="btn-ghost self-start sm:self-auto"
          >
            <RotateCw size={13} className={loading ? "animate-spin" : ""} />
            <span>Refresh</span>
          </button>
        </div>

        {/* Safety Callout */}
        <div className="mb-6 rounded-lg border border-subtle bg-surface p-4 text-[12.5px] leading-relaxed text-secondary">
          <div className="flex items-center gap-2 text-primary font-semibold mb-1">
            <Shield size={15} className="text-red shrink-0" />
            <span>FactFlow Quarantine Guarantee</span>
          </div>
          Nothing in FactFlow touches your real mailbox or contacts. Approved outgoing steps are written to the{" "}
          <strong className="text-primary font-mono">simulated outbox only</strong>. There is no &ldquo;always allow&rdquo; setting, and <strong>Deny</strong> is the primary default.
        </div>

        {/* Filter Bar */}
        <div className="mb-6 flex flex-wrap gap-1.5 border-b border-subtle pb-3">
          {STATUS_FILTERS.map((s) => {
            const active = filter === s;
            return (
              <button
                key={s}
                type="button"
                onClick={() => setFilter(s)}
                className={`pill text-[11px] uppercase transition-all ${
                  active
                    ? "bg-red/15 border-red/50 text-red font-bold"
                    : "border-subtle text-secondary hover:text-primary hover:bg-hover"
                }`}
              >
                {s}
              </button>
            );
          })}
        </div>

        {/* Loading State */}
        {loading && (
          <div className="flex flex-col gap-4">
            {[1, 2, 3].map((i) => (
              <div key={i} className="animate-pulse rounded-lg border border-subtle bg-card p-5">
                <div className="h-4 w-48 rounded bg-surface mb-3" />
                <div className="h-4 w-3/4 rounded bg-surface mb-2" />
                <div className="h-4 w-1/3 rounded bg-surface" />
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
                : error.status === 503
                ? "Approvals Disabled (503)"
                : "Unable to Load Approvals"}
            </h3>
            <p className="mx-auto mt-2 max-w-md text-[13px] text-secondary">
              {error.status === 401
                ? "The approvals endpoint is protected by OPERATOR_TOKEN. Enter your token in the operator authentication settings."
                : error.status === 503
                ? "The backend is missing the APPROVAL_SECRET configuration (must be at least 32 characters)."
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
                  onClick={fetchApprovals}
                  className="btn-red !py-2 !px-5 !text-[13px]"
                >
                  <RotateCw size={14} /> Retry
                </button>
              )}
            </div>
          </div>
        )}

        {/* Empty State */}
        {!loading && !error && approvals.length === 0 && (
          <div className="rounded-lg border border-subtle bg-card p-10 text-center">
            <CheckSquare size={32} className="text-secondary mx-auto mb-2 opacity-50" />
            <h3 className="font-display text-[16px] font-bold text-primary">No Approval Requests</h3>
            <p className="text-[13px] text-secondary mt-1">
              {filter === "pending"
                ? "No pending approvals currently require human intervention."
                : `No approvals found with status '${filter}'.`}
            </p>
          </div>
        )}

        {/* Approval Items */}
        {!loading && !error && approvals.length > 0 && (
          <div className="flex flex-col gap-4">
            {approvals.map((appr) => {
              const isPending = appr.status === "pending";
              const isDeciding = decidingId === appr.id;

              return (
                <div
                  key={appr.id}
                  className="rounded-lg border border-subtle bg-card p-5 transition-all hover:border-active"
                >
                  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 pb-3 border-b border-subtle">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="mono text-[11px] font-bold text-red bg-red/10 border border-red/40 px-2 py-0.5 rounded uppercase">
                        {appr.action}
                      </span>
                      <span className="mono text-[11px] text-muted">
                        Rule: {appr.rule_id}
                      </span>
                      {appr.origin && (
                        <span className="pill text-[9.5px] bg-subtle text-secondary">
                          Origin: {appr.origin}
                        </span>
                      )}
                    </div>

                    <div className="flex items-center gap-2">
                      <span
                        className={`pill text-[10px] uppercase font-bold ${
                          appr.status === "pending"
                            ? "bg-orange/15 border-orange/40 text-orange animate-pulse"
                            : appr.status === "approved"
                            ? "bg-green/15 border-green/40 text-green"
                            : "bg-red/15 border-red/40 text-red"
                        }`}
                      >
                        {appr.status}
                      </span>
                      {appr.created_at && (
                        <span className="mono text-[11px] text-muted flex items-center gap-1">
                          <Clock size={11} /> {new Date(appr.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Reason & Target */}
                  <div className="mt-3 text-[13.5px]">
                    <div className="text-primary font-medium leading-relaxed">
                      {appr.reason}
                    </div>

                    {appr.target && (
                      <div className="mono text-[12px] text-secondary mt-1">
                        Target recipient/URL: <code className="text-primary">{appr.target}</code>
                      </div>
                    )}
                  </div>

                  {/* Evidence Box */}
                  {appr.evidence && (
                    <div className="mt-3 rounded border border-subtle bg-surface p-3 text-[12px]">
                      <div className="mono text-[10.5px] text-secondary uppercase tracking-wider mb-1 flex items-center justify-between">
                        <span>Associated Step Evidence: {appr.evidence.task}</span>
                        {appr.evidence.label && (
                          <ShieldBadge label={appr.evidence.label} size="sm" />
                        )}
                      </div>
                      {appr.evidence.hidden_text?.length > 0 && (
                        <div className="text-orange font-mono mt-1">
                          Hidden text: &ldquo;{escapeSuspiciousCharacters(appr.evidence.hidden_text[0])}&rdquo;
                        </div>
                      )}
                    </div>
                  )}

                  {/* Decision Actions */}
                  {isPending && (
                    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-subtle">
                      <div className="text-[11px] mono text-muted">
                        Expires in ~10m from creation
                      </div>

                      <div className="flex items-center gap-3">
                        {/* Deny is primary and default */}
                        <button
                          type="button"
                          disabled={isDeciding}
                          onClick={() => handleDecision(appr, "deny")}
                          className="btn-red !py-2 !px-4 !text-[12.5px] flex items-center gap-1.5"
                        >
                          <X size={14} /> Deny (Recommended)
                        </button>

                        {/* Approve Once is secondary */}
                        <button
                          type="button"
                          disabled={isDeciding}
                          onClick={() => handleDecision(appr, "approve")}
                          className="btn-ghost !py-2 !px-4 !text-[12.5px] flex items-center gap-1.5 !border-green/40 hover:!bg-green/10 text-green"
                        >
                          <Check size={14} /> Approve once
                        </button>
                      </div>
                    </div>
                  )}

                  {!isPending && appr.decided_at && (
                    <div className="mt-3 pt-2 border-t border-subtle mono text-[11px] text-muted flex items-center justify-between">
                      <span>Decided by: {appr.decided_by || "operator"}</span>
                      <span>At: {new Date(appr.decided_at).toLocaleString()}</span>
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
        onTokenSaved={() => fetchApprovals()}
      />
    </>
  );
}
