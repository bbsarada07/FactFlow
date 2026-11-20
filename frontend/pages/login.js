import { Lock, MailCheck, ShieldCheck, Smartphone } from "lucide-react";
import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect } from "react";

import Logo from "@/components/Logo";
import { signInUrl, useAuth } from "@/lib/auth";

// Plain-language reasons for the error codes the backend puts in /login?error=...
const ERRORS = {
  cancelled: "Sign-in was cancelled. Try again whenever you are ready.",
  expired: "That sign-in took too long or started in another tab. Please try again.",
  missing_code: "Google did not send a sign-in code back. Please try again.",
  email_not_verified: "Google has not verified this email address, so it cannot be used.",
  not_allowed: "FactFlow is in private testing and this Google account is not on the invite list yet.",
  account_conflict: "This email is already linked to a different Google account.",
  not_configured: "Google sign-in is not set up on this server yet.",
  google_unreachable: "Google could not be reached. Please try again in a moment.",
  exchange_failed: "Google did not accept the sign-in. Please try again.",
  bad_token: "Google's answer could not be verified. Please try again.",
};

const POINTS = [
  { icon: ShieldCheck, text: "Your own agent: fact-checks and email shielding that only you can see." },
  { icon: MailCheck, text: "Connect your Gmail and every email is checked. Risky ones wait for you." },
  { icon: Smartphone, text: "Check anything from the browser extension or WhatsApp, into the same account." },
];

export default function LoginPage() {
  const router = useRouter();
  const { status } = useAuth();
  const next = typeof router.query.next === "string" && router.query.next.startsWith("/") ? router.query.next : "/";
  const error = typeof router.query.error === "string" ? ERRORS[router.query.error] || "Sign-in did not complete. Please try again." : null;

  useEffect(() => {
    if (status === "signed_in") router.replace(next);
  }, [status, next, router]);

  return (
    <>
      <Head>
        <title>Sign in — FactFlow</title>
      </Head>
      <section
        className="flex min-h-[calc(100vh-var(--nav-height))] items-center justify-center px-4 py-16"
        style={{ background: "radial-gradient(ellipse 60% 50% at 50% 40%, rgba(255,45,45,0.07), transparent 70%)" }}
      >
        <div className="w-full max-w-md">
          <div className="mb-8 flex flex-col items-center text-center">
            <Logo size={44} />
            <h1 className="mt-5 font-display text-[30px] font-bold tracking-tight text-primary">Sign in to FactFlow</h1>
            <p className="mt-2 text-[15px] leading-relaxed text-secondary">
              Your personal agent that fact-checks what you read and shields what you are asked to do.
            </p>
          </div>

          <div className="rounded-lg border border-subtle bg-card p-6">
            {router.query.signed_out && !error && (
              <p className="mb-4 rounded-md border border-subtle bg-surface p-3 text-[13px] text-secondary">You are signed out.</p>
            )}
            {error && (
              <p role="alert" className="mb-4 rounded-md border p-3 text-[13px] text-primary" style={{ borderColor: "rgba(255,45,45,0.5)", background: "rgba(255,45,45,0.08)" }}>
                {error}
              </p>
            )}
            <a
              href={signInUrl(next)}
              className="flex w-full items-center justify-center gap-3 rounded-md bg-white px-4 py-3 text-[15px] font-semibold text-[#1f1f1f] transition-opacity hover:opacity-90"
            >
              <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
                <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
                <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
                <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
                <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
              </svg>
              Continue with Google
            </a>
            <ul className="mt-6 space-y-3">
              {POINTS.map(({ icon: Icon, text }) => (
                <li key={text} className="flex items-start gap-3 text-[13.5px] text-secondary">
                  <Icon size={16} className="mt-0.5 shrink-0 text-red" />
                  {text}
                </li>
              ))}
            </ul>
          </div>

          <p className="mt-5 flex items-start gap-2 text-[12px] leading-relaxed text-muted">
            <Lock size={13} className="mt-0.5 shrink-0" />
            FactFlow asks Google only for your name and email to sign you in. Gmail access is a separate step in
            Settings, and you can disconnect it at any time. No password is stored.
          </p>
          <p className="mt-3 text-center text-[13px] text-secondary">
            <Link href="/about" className="hover:text-primary">How FactFlow works →</Link>
          </p>
        </div>
      </section>
    </>
  );
}
