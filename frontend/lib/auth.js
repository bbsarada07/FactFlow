// Who is signed in, and the CSRF token every change must carry.
//
// The session itself is an HttpOnly cookie the page cannot read. /api/auth/me says who it belongs to and
// returns the CSRF token, which is sent back in X-CSRF-Token on POST/PUT/PATCH/DELETE (lib/api.js,
// lib/shieldApi.js). Another site can neither read the token nor send it, so it cannot act for the user.
import { createContext, createElement, useCallback, useContext, useEffect, useState } from "react";

const AuthContext = createContext({ status: "loading", user: null, refresh: () => {} });

let csrfToken = null;

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

export async function fetchMe() {
  const res = await fetch("/api/auth/me", { credentials: "same-origin", cache: "no-store" });
  if (res.status === 401) {
    csrfToken = null;
    const body = await res.json().catch(() => ({}));
    return { user: null, googleConfigured: body.google_configured !== false };
  }
  if (!res.ok) throw new Error(`Could not check your sign-in (${res.status})`);
  const body = await res.json();
  csrfToken = body.csrf_token || null;
  return { user: body.user, googleConfigured: true };
}

export async function signOut() {
  await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin", headers: csrfHeaders("POST") }).catch(() => {});
  csrfToken = null;
  window.location.assign("/login?signed_out=1");
}

/** Loads the signed-in user once for the whole app. status: loading | signed_in | signed_out | error */
export function AuthProvider({ children }) {
  const [state, setState] = useState({ status: "loading", user: null, googleConfigured: true });

  const refresh = useCallback(async () => {
    try {
      const { user, googleConfigured } = await fetchMe();
      setState({ status: user ? "signed_in" : "signed_out", user, googleConfigured });
    } catch {
      setState((s) => ({ ...s, status: "error" }));
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
