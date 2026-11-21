import { Globe2, Link2, Lock } from "lucide-react";
import { useState } from "react";
import toast from "react-hot-toast";

import { shareVerdict, unshareVerdict } from "@/lib/api";

/**
 * Whether one verdict's page is shared, for its owner. `requestId` is only given to the owner; without it nothing
 * can be changed and `ensureShared` simply lets the caller go on (the page is already readable to this visitor).
 */
export function useVerdictSharing(requestId, sharedAtStart) {
  const [shared, setShared] = useState(Boolean(sharedAtStart));
  const [busy, setBusy] = useState(false);
  const canManage = Boolean(requestId);

  async function ensureShared() {
    if (!canManage || shared) return true;
    setBusy(true);
    try {
      await shareVerdict(requestId);
      setShared(true);
      return true;
    } catch (err) {
      toast.error(`Could not share: ${err.message}`);
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function stopSharing() {
    setBusy(true);
    try {
      await unshareVerdict(requestId);
      setShared(false);
      toast.success("This verdict is private again. Links you already sent no longer open it.");
    } catch (err) {
      toast.error(err.message);
    } finally {
      setBusy(false);
    }
  }

  return { canManage, shared, busy, ensureShared, stopSharing };
}

/** The owner's control: who can open this verdict's page, with Share / Copy link / Stop sharing. */
export default function SharingBar({ sharing, url }) {
  if (!sharing.canManage || !url) return null;

  async function copyLink() {
    if (!(await sharing.ensureShared())) return;
    try {
      await navigator.clipboard.writeText(url);
      toast.success("Link copied. Anyone with it can open this verdict.");
    } catch {
      toast.error("Clipboard access was blocked by the browser");
    }
  }

  const btn =
    "inline-flex items-center gap-1.5 rounded-full border border-active px-3 py-1.5 text-[12px] font-medium text-primary transition-colors hover:bg-hover disabled:opacity-50";
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-subtle bg-surface px-4 py-3">
      <p className="m-0 flex min-w-0 items-start gap-2 text-[12.5px] text-secondary">
        {sharing.shared ? (
          <>
            <Globe2 size={14} className="mt-0.5 shrink-0" style={{ color: "#25D366" }} />
            <span>
              <span className="font-medium text-primary">Shared.</span> Anyone with the link sees the claim, verdict and
              sources, never who checked it.
            </span>
          </>
        ) : (
          <>
            <Lock size={14} className="mt-0.5 shrink-0" />
            <span>
              <span className="font-medium text-primary">Private.</span> Only you can open this verdict&apos;s page.
            </span>
          </>
        )}
      </p>
      <div className="flex shrink-0 gap-2">
        <button type="button" onClick={copyLink} disabled={sharing.busy} className={btn}>
          <Link2 size={13} /> {sharing.shared ? "Copy link" : "Share page"}
        </button>
        {sharing.shared && (
          <button type="button" onClick={sharing.stopSharing} disabled={sharing.busy} className={`${btn} text-secondary`}>
            Stop sharing
          </button>
        )}
      </div>
    </div>
  );
}
