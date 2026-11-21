import { LogIn } from "lucide-react";
import { useRouter } from "next/router";

import { signInUrl, useSignIn } from "@/lib/auth";

/** Shown when a request answers 401 (the session ended): sign in and come back to this page. */
export default function SignInAgain({ className = "btn-red !py-2 !px-5 !text-[13px]" }) {
  const router = useRouter();
  const signIn = useSignIn(router.asPath);
  return (
    <a href={signInUrl(router.asPath)} onClick={signIn.go} className={className}>
      <LogIn size={13} /> {signIn.phase === "waking" ? "Waking up FactFlow…" : "Sign in again"}
    </a>
  );
}
