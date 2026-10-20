import { ArrowUpRight, CircleHelp } from "lucide-react";

/**
 * "Honest uncertainty": why a definite verdict isn't possible yet, what evidence is missing,
 * and the checks a reader can do themselves. Deliberately calm: this is a result, not an error.
 */
export default function HonestUncertainty({ result, prominent = true }) {
  const gaps = result.evidence_gaps || [];
  const checks = result.checks_to_do || [];
  const reasons = result.gate_reasons || [];
  if (!gaps.length && !checks.length && !reasons.length) return null;

  return (
    <section
      className="rounded-md p-5"
      style={{
        background: prominent ? "rgba(136,136,160,0.06)" : "var(--bg-surface)",
        border: `1px solid ${prominent ? "rgba(136,136,160,0.25)" : "var(--border-subtle)"}`,
      }}
    >
      <div className="mb-3 flex items-center gap-2">
        <CircleHelp size={16} className="text-secondary" />
        <span className="label !text-primary">{prominent ? "Honest uncertainty" : "What is still missing"}</span>
      </div>

      {prominent && reasons.length > 0 && (
        <ul className="m-0 mb-4 flex list-none flex-col gap-1.5 p-0 text-[14px] text-primary">
          {reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}

      {gaps.length > 0 && (
        <div className="mb-4">
          <div className="mono mb-2 text-[10.5px] tracking-[2px] text-secondary">EVIDENCE GAPS</div>
          <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
            {gaps.map((g) => (
              <li key={g} className="rounded-full border border-active px-3 py-1 text-[12.5px] text-secondary">
                {g}
              </li>
            ))}
          </ul>
        </div>
      )}

      {checks.length > 0 && (
        <div>
          <div className="mono mb-2 text-[10.5px] tracking-[2px] text-secondary">CHECKS YOU CAN DO</div>
          <ol className="m-0 flex list-none flex-col gap-2 p-0">
            {checks.map((c, i) => {
              const body = (
                <>
                  <span className="mono mt-0.5 text-[11px] text-muted">{String(i + 1).padStart(2, "0")}</span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1 font-medium text-primary">
                      {c.label}
                      {c.url && <ArrowUpRight size={13} className="text-secondary" />}
                    </span>
                    <span className="block text-[12.5px] text-secondary">{c.why}</span>
                  </span>
                </>
              );
              return (
                <li key={c.label}>
                  {c.url ? (
                    <a
                      href={c.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex gap-3 rounded-md border border-subtle bg-card p-3 transition-colors hover:border-active hover:bg-hover"
                    >
                      {body}
                    </a>
                  ) : (
                    <div className="flex gap-3 rounded-md border border-subtle bg-card p-3">{body}</div>
                  )}
                </li>
              );
            })}
          </ol>
        </div>
      )}
    </section>
  );
}
