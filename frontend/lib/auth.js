// Who is signed in, and the CSRF token every change must carry.
//
// The session itself is an HttpOnly cookie the page cannot read. /api/auth/me says who it belongs to and
// returns the CSRF token, which is sent back in X-CSRF-Token on POST/PUT/PATCH/DELETE (lib/api.js,
// lib/shieldApi.js). Another site can neither read the token nor send it, so it cannot act for the user.
//
// On free hosting the backend sleeps when idle. While it boots, the host answers with its own holding page
// instead of FactFlow's JSON. Everything here treats that as "waking up": it waits and retries, and sign-in
// only goes to Google once the backend can answer the callback.
import { createContext, createElement, useCallback, useContext, useEffect, useRef, useState } from "react";

const AuthContext = createContext({ status: "loading", user: null, refresh: () => {} });
const WAKE_TIMEOUT_MS = 120_000;

let csrfToken = null;

class WakingError extends Error {}

/** The CSRF token for this session (from /api/auth/me, or the readable ff_csrf cookie as a fallback). */
export function getCsrfToken() {
  if (csrfToken) return csrfToken;
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|;\s*)ff_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

/** Headers to add to a request: the CSRF token for anything that changes something. */
export function csrfHeaders(method = "GET") {
  const m = String(method).toUpperCase();
  if (m === "GET" || m === "HEAD" || m === "OPTIONS") return {};
  const token = getCsrfToken();
  return token ? { "X-CSRF-Token": token } : {};
}

/** Where "Sign in" sends the browser; `next` is where to come back to afterwards. */
export function signInUrl(next = "/") {
  return `/api/auth/google/login?next=${encodeURIComponent(next || "/")}`;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** True when the FactFlow backend itself answered (not the host's holding page while it boots). */
async function backendAwake() {
  try {
    const res = await fetch("/health", { cache: "no-store", credentials: "same-origin" });
    if (!res.ok || !(res.headers.get("content-type") || "").includes("application/json")) return false;
    const body = await res.json();
    return typeof body.status === "string";
  } catch {
    return false;
  }
}

/** Wait until the backend is awake (up to two minutes). Returns true when it is. */
export async function waitForBackend(onWaiting) {
  const started = Date.now();
  let first = true;
  while (Date.now() - started < WAKE_TIMEOUT_MS) {
    if (await backendAwake()) return true;
    if (first && onWaiting) onWaiting();
    first = false;
    await sleep(3000);
  }
  return false;
}

/** Wake the backend if needed, then go to Google's sign-in. */
export async function startSignIn(next = "/", onWaiting) {
  await waitForBackend(onWaiting);
  window.location.assign(signInUrl(next));
}

/** For sign-in buttons: `go` (an onClick handler) wakes the backend first, then goes to Google.
 * `phase` is idle | checking | waking, for the button label. */
export function useSignIn(next = "/") {
  const [phase, setPhase] = useState("idle");
  const go = useCallback(
    (event) => {
      event?.preventDefault();
      if (phase !== "idle") return;
      setPhase("checking");
      startSignIn(next, () => setPhase("waking")).catch(() => setPhase("idle"));
    },
    [next, phase]
  );
  return { go, phase };
}

export async function fetchMe() {
  let res;
  try {
    res = await fetch("/api/auth/me", { credentials: "same-origin", cache: "no-store" });
  } catch {
    throw new WakingError("network");
  }
  const json = (res.headers.get("content-type") || "").includes("application/json");
  if (!json || res.status >= 500) throw new WakingError(String(res.status)); // host holding page / still booting
  const body = await res.json().catch(() => ({}));
  if (res.status === 401) {
    csrfToken = null;
    return { user: null, googleConfigured: body.google_configured !== false };
  }
  if (!res.ok) throw new Error(`Could not check your sign-in (${res.status})`);
  csrfToken = body.csrf_token || null;
  return { user: body.user, googleConfigured: true };
}

export async function signOut() {
  await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin", headers: csrfHeaders("POST") }).catch(() => {});
  csrfToken = null;
  window.location.assign("/login?signed_out=1");
}

/** Loads the signed-in user once for the whole app.
 * status: loading | waking (backend booting, retrying) | signed_in | signed_out | error */
export function AuthProvider({ children }) {
  const [state, setState] = useState({ status: "loading", user: null, googleConfigured: true });
  const started = useRef(0);

  const refresh = useCallback(async () => {
    started.current = Date.now();
    for (;;) {
      try {
        const { user, googleConfigured } = await fetchMe();
        setState({ status: user ? "signed_in" : "signed_out", user, googleConfigured });
        return;
      } catch (err) {
        if (!(err instanceof WakingError) || Date.now() - started.current > WAKE_TIMEOUT_MS) {
          setState((s) => ({ ...s, status: "error" }));
          return;
        }
        setState((s) => ({ ...s, status: "waking" }));
        await sleep(3000);
      }
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return createElement(AuthContext.Provider, { value: { ...state, refresh } }, children);
}

export function useAuth() {
  return useContext(AuthContext);
}
