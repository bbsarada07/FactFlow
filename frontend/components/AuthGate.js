import { useRouter } from "next/router";
import { useEffect } from "react";

import Logo from "@/components/Logo";
import { useAuth } from "@/lib/auth";

// Pages anyone can open. Everything else belongs to a signed-in person.
// /v/[slug] is rendered on the server, which already sends signed-out visitors of a private verdict to sign in.
export const PUBLIC_PATHS = new Set(["/login", "/about", "/accuracy", "/v/[slug]", "/404", "/500", "/_error"]);

/** Renders the page only for a signed-in user; otherwise sends the browser to /login (and back afterwards). */
export default function AuthGate({ children }) {
  const router = useRouter();
  const { status, refresh } = useAuth();
  const isPublic = PUBLIC_PATHS.has(router.pathname);

  useEffect(() => {
    if (!isPublic && status === "signed_out") {
      router.replace(`/login?next=${encodeURIComponent(router.asPath)}`);
    }
  }, [isPublic, status, router]);

  if (isPublic || status === "signed_in") return children;

  if (status === "error") {
    return (
      <div className="mx-auto max-w-md px-4 py-32 text-center">
        <p className="text-secondary">FactFlow could not check your sign-in. The server may be waking up.</p>
        <button type="button" onClick={refresh} className="btn-red mt-5 !py-2 !px-5 !text-[13px]">
          Try again
        </button>
      </div>
    );
  }

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 text-secondary" aria-busy="true">
      <div className="animate-pulse">
        <Logo size={36} />
      </div>
      <span className="mono text-[11px] tracking-[1.5px]">
        {status === "waking" ? "WAKING UP FACTFLOW…" : "LOADING YOUR AGENT…"}
      </span>
      {status === "waking" && (
        <span className="max-w-xs text-center text-[12.5px] text-muted">
          The server sleeps when nobody has used it for a while. This takes up to a minute.
        </span>
      )}
    </div>
  );
}
