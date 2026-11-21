import { Mail } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { getMailStatus } from "@/lib/api";

/** Tells the user when their agent cannot act yet: Gmail not connected, or connected with read access only. */
export default function GmailBanner() {
  const [gmail, setGmail] = useState(null);

  useEffect(() => {
    getMailStatus().then((m) => setGmail(m.gmail)).catch(() => {});
  }, []);

  if (!gmail || (gmail.status === "connected" && !gmail.needs_upgrade)) return null;
  const text =
    gmail.status === "connected"
      ? "Your Gmail is connected with read access only, so your agent can check mail but not reply or quarantine. Reconnect once to let it act (it still asks you before anything risky)."
      : gmail.reconnect_required
        ? "Google ended FactFlow's access to your Gmail. Reconnect to keep your agent working."
        : "Connect your Gmail and your agent checks every new email, answers routine ones and asks you about anything risky.";

  return (
    <div className="mb-6 flex flex-col gap-3 rounded-lg border p-4 sm:flex-row sm:items-center sm:justify-between"
      style={{ borderColor: "rgba(255,45,45,0.4)", background: "rgba(255,45,45,0.05)" }}>
      <div className="flex items-start gap-3 text-[13.5px] text-secondary">
        <Mail size={18} className="mt-0.5 shrink-0 text-red" />
        <span>{text}</span>
      </div>
      <Link href="/settings" className="btn-red shrink-0 !py-2 !px-4 !text-[13px]">
        {gmail.status === "connected" ? "Reconnect Gmail" : "Connect Gmail"}
      </Link>
    </div>
  );
}
