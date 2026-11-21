import { Paperclip, Send, Undo2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import toast from "react-hot-toast";

import { cancelOutgoing, listOutgoing, sendOutgoingNow } from "@/lib/api";
import { timeAgo } from "@/lib/theme";

const STATUS = {
  scheduled: ["#FF6B00", "SENDING SOON"],
  sending: ["#FF6B00", "SENDING"],
  sent: ["#00E676", "SENT"],
  cancelled: ["#8888A0", "UNDONE"],
  failed: ["#FF2D2D", "FAILED"],
};
const ORIGIN = { agent: "Your agent", approved: "You approved", user: "You wrote", digest: "Daily digest" };

function secondsLeft(sendAt, now) {
  return Math.max(0, Math.round((new Date(sendAt).getTime() - now) / 1000));
}

/** Mail being sent for you, with Undo while the undo window is open. `limit` caps how many rows show. */
export default function OutgoingQueue({ limit = 8, onlyActive = false }) {
  const [items, setItems] = useState(null);
  const [now, setNow] = useState(() => Date.now());

  const load = useCallback(async () => {
    try {
      const res = await listOutgoing();
      setItems(res.items || []);
    } catch {
      setItems((x) => x || []);
    }
  }, []);

  useEffect(() => {
    load();
    const poll = setInterval(load, 15000);
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      clearInterval(poll);
      clearInterval(tick);
    };
  }, [load]);

  const act = async (fn, id, message) => {
    try {
      await fn(id);
      toast.success(message);
    } catch (err) {
      toast.error(err.message);
    }
    load();
  };

  if (items === null) return null;
  const shown = (onlyActive ? items.filter((m) => m.status === "scheduled") : items).slice(0, limit);
  if (!shown.length) return null;

  return (
    <section className="mb-6 rounded-lg border border-subtle bg-card">
      <div className="flex items-center gap-2 border-b border-subtle px-4 py-3">
        <Send size={15} className="text-red" />
        <h2 className="m-0 font-display text-[15px] font-semibold text-primary">Sent for you</h2>
        <span className="text-[12px] text-muted">· every message waits a little so you can undo it</span>
      </div>
      <ul className="m-0 list-none divide-y divide-subtle p-0">
        {shown.map((m) => {
          const [color, label] = STATUS[m.status] || STATUS.failed;
          const left = m.status === "scheduled" ? secondsLeft(m.send_at, now) : 0;
          return (
            <li key={m.id} className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2 text-[13px]">
                  <span className="mono rounded-sm border px-1.5 text-[10px]" style={{ borderColor: `${color}66`, color }}>
                    {label}
                    {m.status === "scheduled" ? ` · ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}` : ""}
                  </span>
                  <span className="truncate text-primary">{m.subject || "(no subject)"}</span>
                  {m.file_ids?.length > 0 && <Paperclip size={12} className="text-secondary" aria-label="has an attachment" />}
                </div>
                <div className="mt-0.5 truncate text-[12px] text-secondary">
                  To {m.to} · {ORIGIN[m.origin] || m.origin} · {timeAgo(m.sent_at || m.created_at)}
                  {m.error ? ` · ${m.error}` : ""}
                </div>
              </div>
              {m.status === "scheduled" && (
                <div className="flex shrink-0 gap-2">
                  <button type="button" onClick={() => act(cancelOutgoing, m.id, "Undone: it will not be sent.")} className="btn-red !py-1.5 !px-3 !text-[12px]">
                    <Undo2 size={13} /> Undo
                  </button>
                  <button type="button" onClick={() => act(sendOutgoingNow, m.id, "Sent.")} className="btn-ghost !py-1.5 !px-3 !text-[12px]">
                    Send now
                  </button>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
