import { AlertTriangle, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import toast from "react-hot-toast";

import { dismissAlert, listAlerts } from "@/lib/api";
import { timeAgo } from "@/lib/theme";

/** Things your agent wants you to look at that are not approvals (e.g. a leak in mail you sent from Gmail). */
export default function AlertsList({ onChange }) {
  const [items, setItems] = useState([]);

  const load = useCallback(async () => {
    try {
      setItems((await listAlerts()).items || []);
    } catch {
      setItems([]);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const dismiss = async (id) => {
    try {
      await dismissAlert(id);
      await load();
      onChange?.();
    } catch (err) {
      toast.error(err.message);
    }
  };

  if (!items.length) return null;
  return (
    <section className="mb-6 space-y-3">
      {items.map((a) => (
        <div key={a.id} className="flex items-start gap-3 rounded-lg border p-4" style={{ borderColor: "rgba(255,107,0,0.45)", background: "rgba(255,107,0,0.06)" }}>
          <AlertTriangle size={18} className="mt-0.5 shrink-0 text-orange" />
          <div className="min-w-0 flex-1">
            <div className="text-[14px] font-semibold text-primary">{a.title}</div>
            {(a.detail?.findings || []).map((f) => (
              <div key={f.message} className="mt-1 text-[13px] text-secondary">• {f.message}</div>
            ))}
            {a.detail?.error && <div className="mt-1 text-[13px] text-secondary">{a.detail.error}</div>}
            {a.detail?.to?.length > 0 && <div className="mt-1 text-[12px] text-muted">To {a.detail.to.join(", ")}</div>}
            <div className="mono mt-1 text-[11px] text-muted">{timeAgo(a.created_at)}</div>
          </div>
          <button type="button" onClick={() => dismiss(a.id)} className="rounded p-1.5 text-secondary hover:bg-hover hover:text-primary" aria-label="Dismiss">
            <X size={15} />
          </button>
        </div>
      ))}
    </section>
  );
}
