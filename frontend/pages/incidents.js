import { motion } from "framer-motion";
import Head from "next/head";
import { useEffect, useState } from "react";

import IncidentCard from "@/components/IncidentCard";
import { getIncidents } from "@/lib/api";
import { EASE } from "@/lib/theme";

export default function IncidentsPage() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getIncidents()
      .then((d) => setItems(d.items))
      .catch((e) => setError(e.message));
  }, []);

  const deaths = items?.reduce((s, i) => s + i.deaths, 0);

  return (
    <>
      <Head>
        <title>Incident Library — FactFlow</title>
      </Head>
      <header className="relative overflow-hidden" style={{ background: "radial-gradient(ellipse 70% 100% at 50% 0%, rgba(255,45,45,0.06), transparent)" }}>
        <div className="mx-auto max-w-4xl px-4 pb-12 pt-20 text-center sm:pt-24">
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="mono mb-6 text-[11px] tracking-[3px] text-red"
          >
            INCIDENT LIBRARY
          </motion.div>
          <h1 className="m-0 font-display font-bold leading-[1.02] tracking-[-0.02em]" style={{ fontSize: "clamp(38px, 7vw, 56px)" }}>
            <motion.span className="block" initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, ease: EASE }}>
              The Human Cost of
            </motion.span>
            <motion.span
              className="block text-red"
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.15, ease: EASE }}
            >
              Misinformation.
            </motion.span>
          </h1>
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.35 }}
            className="mx-auto mt-6 max-w-xl text-[18px] text-secondary"
          >
            These are real incidents. Real deaths. Real consequences.
          </motion.p>
          {deaths != null && (
            <p className="mono mt-4 text-[12px] text-muted">
              {items.length} incidents · {deaths} documented deaths
            </p>
          )}
        </div>
      </header>

      <div className="mx-auto flex max-w-4xl flex-col gap-8 px-4 pb-24">
        {error && (
          <div className="rounded-md p-4 text-[14px]" style={{ background: "rgba(255,45,45,0.06)", border: "1px solid rgba(255,45,45,0.3)" }}>
            {error}
          </div>
        )}
        {!items && !error && Array.from({ length: 3 }).map((_, i) => <div key={i} className="h-[420px] animate-pulse rounded-lg bg-card" />)}
        {items?.map((inc, i) => (
          <IncidentCard key={inc.slug} incident={inc} index={i} />
        ))}
      </div>
    </>
  );
}
