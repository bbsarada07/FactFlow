import Link from "next/link";

import { useConfig } from "@/lib/useConfig";

/** Site footer stating the models and evidence sources actually in use (from /api/config). */
export default function Footer() {
  const config = useConfig();

  return (
    <footer className="border-t border-subtle px-4 py-8">
      <div className="mono mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 text-center text-[11.5px] text-muted md:flex-row md:text-left">
        <p className="m-0">
          {config && !config.unavailable ? (
            <>
              Models: <span className="text-secondary">{config.models.nano}</span> /{" "}
              <span className="text-secondary">{config.models.ultra}</span> via {config.provider} (all verdicts).
              {config.vision && (
                <>
                  {" "}Screenshots read by <span className="text-secondary">{config.vision.model}</span> via{" "}
                  {config.vision.provider}.
                </>
              )}{" "}
              Sources:{" "}
              {config.evidence_sources.join(", ")}.
            </>
          ) : config?.unavailable ? (
            "Backend unreachable: model and source details unavailable."
          ) : (
            "Loading configuration…"
          )}
        </p>
        <nav className="flex gap-4">
          <Link href="/registry" className="hover:text-primary">
            Registry
          </Link>
          <Link href="/about" className="hover:text-primary">
            How it works
          </Link>
          <span>MIT License</span>
        </nav>
      </div>
    </footer>
  );
}
