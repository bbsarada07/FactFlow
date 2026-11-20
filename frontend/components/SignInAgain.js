import { LogIn } from "lucide-react";
import { useRouter } from "next/router";

import { signInUrl } from "@/lib/auth";

/** Shown when a request answers 401 (the session ended): sign in and come back to this page. */
export default function SignInAgain({ className = "btn-red !py-2 !px-5 !text-[13px]" }) {
  const router = useRouter();
  return (
    <a href={signInUrl(router.asPath)} className={className}>
      <LogIn size={13} /> Sign in again
    </a>
  );
}
