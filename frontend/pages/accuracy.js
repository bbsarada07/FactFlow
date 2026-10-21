import Head from "next/head";
import { useEffect, useState } from "react";

import { getAccuracy } from "@/lib/api";

const COUNT_LABELS = {
  total: "Claims run",
  matches: "Matched expected",
  false_negatives: "True claims not confirmed",
  false_positives: "False claims called true",
  wrong_but_honest: "Labelled claims left UNVERIFIED",
  errors: "Errors",
  ungrounded_sentences: "Uncited sentences",
};

/** Last complete bench run, exactly as recorded in backend/tests/bench/results/latest.json. */
export default function AccuracyPage() {
  const [run, setRun] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    getAccuracy()
      .then(setRun)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <>
      <Head>
        <title>Accuracy — NemesisAI</title>
      </Head>
      <header className="mx-auto max-w-4xl px-4 pb-8 pt-20 text-center">
        <div className="mono mb-5 text-[11px] tracking-[3px] text-red">BENCH ACCURACY</div>
        <h1 className="m-0 font-display font-bold leading-tight tracking-[-0.02em]" style={{ fontSize: "clamp(32px, 6vw, 48px)" }}>
          How the last full run went.
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-[15px] text-secondary">
          Every labelled bench claim is run through the live pipeline. This page shows the last run that finished with no
          errors, as recorded. Nothing here is typed in by hand.
        </p>
      </header>

      <div className="mx-auto max-w-4xl px-4 pb-24">
        {error && (
          <div className="rounded-md p-4 text-[14px]" style={{ background: "rgba(255,45,45,0.06)", border: "1px solid rgba(255,45,45,0.3)" }}>
            {error}
          </div>
        )}
        {!run && !error && <div className="h-[120px] animate-pulse rounded-md bg-card" />}
        {run && !run.complete && <p className="py-12 text-center text-[16px] text-secondary">{run.message}</p>}
        {run?.complete && <RunReport run={run} />}
      </div>
    </>
  );
}

function RunReport({ run }) {
  const models = Object.entries(run.models || {}).filter(([, name]) => name);
  return (
    <div className="flex flex-col gap-8">
      <div className="mono flex flex-wrap gap-x-6 gap-y-2 text-[12px] text-secondary">
        <span>RUN: {run.run_at ? new Date(run.run_at).toLocaleString() : "date not recorded"}</span>
        {models.map(([role, name]) => (
          <span key={role}>
            {role.toUpperCase()}: <span className="text-primary">{name}</span>
          </span>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
        {Object.entries(run.counts || {}).map(([key, value]) => (
          <div key={key} className="rounded-md border border-subtle bg-card px-4 py-3">
            <div className="font-display text-[26px] font-bold leading-none">{value}</div>
            <div className="mono mt-1.5 text-[10.5px] text-muted">{COUNT_LABELS[key] || key}</div>
          </div>
        ))}
      </div>

      <section>
        <h2 className="mono m-0 mb-3 text-[11px] font-normal tracking-[3px] text-secondary">EXPECTED VS GOT</h2>
        <div className="overflow-x-auto rounded-md border border-subtle">
          <table className="w-full min-w-[560px] border-collapse text-left text-[13px]">
            <thead className="mono text-[10.5px] text-muted">
              <tr>
                <th className="px-3 py-2 font-normal">ID</th>
                <th className="px-3 py-2 font-normal">CLAIM</th>
                <th className="px-3 py-2 font-normal">EXPECTED</th>
                <th className="px-3 py-2 font-normal">GOT</th>
              </tr>
            </thead>
            <tbody>
              {run.rows.map((r) => {
                const ok = r.got === r.expected;
                return (
                  <tr key={r.id} className="border-t border-subtle">
                    <td className="mono px-3 py-2 text-muted">{r.id}</td>
                    <td className="px-3 py-2 text-secondary">{r.claim}</td>
                    <td className="mono px-3 py-2">{r.expected}</td>
                    <td className="mono px-3 py-2" style={{ color: ok ? "#00E676" : "#FF2D2D" }}>
                      {r.got}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="mono m-0 mb-3 text-[11px] font-normal tracking-[3px] text-secondary">KNOWN FAILURES</h2>
        {run.known_failures.length === 0 ? (
          <p className="m-0 text-[14px] text-secondary">Every claim in this run matched its expected label.</p>
        ) : (
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {run.known_failures.map((r) => (
              <li key={r.id} className="rounded-md border border-subtle bg-card px-4 py-3 text-[13.5px]">
                <div className="mono text-[11px] text-muted">
                  {r.id} · expected {r.expected} · got {r.got}
                </div>
                <div className="mt-1 text-secondary">{r.claim}</div>
                {r.gaps?.length > 0 && <div className="mt-1 text-[12.5px] text-muted">Gaps: {r.gaps.join("; ")}</div>}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
