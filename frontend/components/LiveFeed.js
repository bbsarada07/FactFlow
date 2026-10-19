import { AnimatePresence, motion } from "framer-motion";

import HarmBadge, { VerdictBadge } from "@/components/HarmBadge";
import { EASE, platformIcon, timeAgo } from "@/lib/theme";

export default function LiveFeed({ items, onSelect, loading }) {
  return (
    <section className="rounded-lg border border-subtle bg-card">
      <header className="flex items-center justify-between border-b border-subtle px-5 py-4">
        <h2 className="mono m-0 flex items-center gap-2.5 text-[12px] font-medium tracking-[2px] text-primary">
          <span className="live-dot" /> LIVE VERIFICATION FEED
        </h2>
        <span className="mono text-[10.5px] text-muted">auto-refresh 5s</span>
      </header>

      {loading && !items.length ? (
        <ul className="m-0 flex list-none flex-col gap-2 p-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <li key={i} className="h-[52px] animate-pulse rounded-md bg-surface" />
          ))}
        </ul>
      ) : !items.length ? (
        <p className="p-8 text-center text-secondary">No verifications yet. Run one from the Verify page.</p>
      ) : (
        <ul className="m-0 flex list-none flex-col p-2">
          <AnimatePresence initial={false}>
            {items.map((it, i) => (
              <motion.li
                key={it.request_id}
                layout
                initial={{ opacity: 0, x: 40 }}
                animate={{ opacity: i >= 16 ? 0.35 + (20 - i) * 0.15 : 1, x: 0 }}
                exit={{ opacity: 0, y: 20 }}
                transition={{ duration: 0.45, ease: EASE }}
              >
                <button
                  type="button"
                  onClick={() => onSelect(it.request_id)}
                  className="grid w-full grid-cols-[auto_1fr_auto] items-center gap-x-3 gap-y-1.5 rounded-md px-3 py-3 text-left transition-colors hover:bg-hover sm:grid-cols-[auto_1fr_auto_auto_auto]"
                >
                  <VerdictBadge verdict={it.verdict} />
                  <span className="min-w-0 truncate text-[14px] text-primary" title={it.claim}>
                    {it.claim}
                  </span>
                  <span className="mono text-right text-[11px] text-muted sm:order-last">
                    {it.is_seed ? "ARCHIVE" : timeAgo(it.created_at)}
                  </span>
                  <span className="col-span-2 col-start-2 flex items-center gap-2 sm:col-span-1 sm:col-start-auto">
                    <HarmBadge type={it.harm_type} />
                  </span>
                  <span className="hidden text-[15px] sm:inline" title={it.platform}>
                    {platformIcon(it.platform)}
                  </span>
                </button>
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}
    </section>
  );
}
