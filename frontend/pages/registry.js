import { motion } from "framer-motion";
import { Search } from "lucide-react";
import Head from "next/head";
import Link from "next/link";
import { useEffect, useState } from "react";

import { VerdictBadge } from "@/components/HarmBadge";
import { searchRegistry } from "@/lib/api";
import { EASE, timeAgo } from "@/lib/theme";

/** Public verdict registry: search every public verdict by claim text. */
export default function RegistryPage() {
  const [q, setQ] = useState("");
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const handle = setTimeout(() => {
      searchRegistry(q.trim(), 50)
        .then((d) => {
          setItems(d.items);
          setError(null);
        })
        .catch((e) => setError(e.message));
    }, 250);
    return () => clearTimeout(handle);
  }, [q]);

  return (
    <>
      <Head>
        <title>Verdict Registry — FactFlow</title>
      </Head>
      <header className="mx-auto max-w-3xl px-4 pb-8 pt-20 text-center">
        <div className="mono mb-5 text-[11px] tracking-[3px] text-red">PUBLIC VERDICT REGISTRY</div>
        <h1 className="m-0 font-display font-bold leading-tight tracking-[-0.02em]" style={{ fontSize: "clamp(34px, 6vw, 52px)" }}>
          Every verdict, on the record.
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-[16px] text-secondary">
          Each public check gets a permanent page. When the same claim comes back, it is recognised and answered from here.
        </p>
        <label className="relative mx-auto mt-8 block max-w-xl">
          <span className="sr-only">Search verdicts</span>
          <Search size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-muted" />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search claims, e.g. kidnappers, cow urine, RBI coins"
            className="w-full rounded-full border border-active bg-card py-3 pl-11 pr-4 text-[15px] text-primary outline-none placeholder:text-muted focus:border-[var(--accent-red)]"
          />
        </label>
      </header>

      <div className="mx-auto max-w-3xl px-4 pb-24">
        {error && (
          <div className="rounded-md p-4 text-[14px]" style={{ background: "rgba(255,45,45,0.06)", border: "1px solid rgba(255,45,45,0.3)" }}>
            {error}
          </div>
        )}
        {!items && !error && Array.from({ length: 5 }).map((_, i) => <div key={i} className="mb-2 h-[64px] animate-pulse rounded-md bg-card" />)}
        {items && items.length === 0 && (
          <p className="py-12 text-center text-secondary">
            {q ? "No public verdict matches that yet." : "No public verdicts yet."}{" "}
            <Link href={q ? `/?claim=${encodeURIComponent(q)}` : "/"} className="text-red hover:underline">
              Check a claim
            </Link>
          </p>
        )}
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {items?.map((it, i) => (
            <motion.li
              key={it.slug}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: Math.min(i, 10) * 0.03, ease: EASE }}
            >
              <Link
                href={`/v/${it.slug}`}
                className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-1 rounded-md border border-subtle bg-card px-4 py-3 transition-colors hover:border-active hover:bg-hover sm:grid-cols-[auto_1fr_auto]"
              >
                <VerdictBadge verdict={it.verdict} />
                <span className="min-w-0 truncate text-[14px] text-primary" title={it.claim}>
                  {it.claim}
                </span>
                <span className="mono col-start-2 text-[11px] text-muted sm:col-start-auto sm:text-right">
                  {it.confidence_band} · {it.view_count} views · {timeAgo(it.created_at)}
                </span>
              </Link>
            </motion.li>
          ))}
        </ul>
      </div>
    </>
  );
}
