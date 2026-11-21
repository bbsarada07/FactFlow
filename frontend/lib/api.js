import { csrfHeaders } from "@/lib/auth";
import { API_URL } from "@/lib/config";

export { API_URL };

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

/** Fetch JSON from this site's /api (forwarded to the backend), with the session cookie and CSRF token. */
export async function api(path, options = {}) {
  let res;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...options,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", ...csrfHeaders(options.method), ...(options.headers || {}) },
    });
  } catch {
    throw new ApiError("Can't reach FactFlow right now. Check your connection and try again.", 0);
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const structured = body.detail && typeof body.detail === "object" && !Array.isArray(body.detail) ? body.detail : null;
    const detail =
      res.status === 401
        ? "Your session has ended. Sign in again to continue."
        : structured
          ? structured.message || `Request failed (${res.status})`
          : Array.isArray(body.detail)
            ? body.detail.map((d) => d.msg).join("; ")
            : body.detail || `Request failed (${res.status})`;
    const error = new ApiError(detail, res.status);
    error.data = structured; // e.g. the findings of a pre-send check
    throw error;
  }
  return { status: res.status, data: body };
}

export const startVerification = (payload) =>
  api("/api/verify", { method: "POST", body: JSON.stringify(payload) }).then((r) => r.data);

export const getResult = (id) => api(`/api/result/${id}`);
export const getHistory = (limit = 20) => api(`/api/history?limit=${limit}`).then((r) => r.data);
export const getStats = () => api("/api/stats").then((r) => r.data);
export const getIncidents = () => api("/api/incidents").then((r) => r.data);
export const getPublicConfig = () => api("/api/config").then((r) => r.data);
export const getAccuracy = () => api("/api/accuracy").then((r) => r.data);
export const searchRegistry = (q = "", limit = 30) =>
  api(`/api/registry?q=${encodeURIComponent(q)}&limit=${limit}`).then((r) => r.data);
export const streamUrl = (id) => `${API_URL}/api/stream/${id}`;

// ------------------------------------------------------------------------------------------- account

export const getMailStatus = () => api("/api/mail/status").then((r) => r.data);
export const connectGmail = () => api("/api/mail/gmail/connect", { method: "POST" }).then((r) => r.data);
export const syncMail = () => api("/api/mail/sync", { method: "POST", body: "{}" }).then((r) => r.data);
export const disconnectGmail =() => api("/api/mail/gmail/disconnect", { method: "POST" }).then((r) => r.data);
export const setMailProvider = (provider) =>
  api("/api/mail/provider", { method: "PUT", body: JSON.stringify({ provider }) }).then((r) => r.data);
export const getPolicy = () => api("/api/policy").then((r) => r.data);
export const setPolicyMode = (mode, confirm = false) =>
  api("/api/policy/mode", { method: "PUT", body: JSON.stringify({ mode, confirm }) }).then((r) => r.data);
export const listExtensionTokens = () => api("/api/account/extension-tokens").then((r) => r.data);
export const createExtensionToken = (label) =>
  api("/api/account/extension-tokens", { method: "POST", body: JSON.stringify({ label }) }).then((r) => r.data);
export const revokeExtensionToken = (id) =>
  api(`/api/account/extension-tokens/${id}`, { method: "DELETE" }).then((r) => r.data);
export const getWhatsAppLink = () => api("/api/account/whatsapp").then((r) => r.data);
export const newWhatsAppCode = () => api("/api/account/whatsapp/link-code", { method: "POST" }).then((r) => r.data);
export const unlinkWhatsApp = () => api("/api/account/whatsapp", { method: "DELETE" }).then((r) => r.data);
export const signOutEverywhere = () => api("/api/auth/logout-everywhere", { method: "POST" }).then((r) => r.data);

// --------------------------------------------------------------------------------------------- agent

export const getAgentSettings = () => api("/api/agent/settings").then((r) => r.data);
export const setAgentSettings = (values) =>
  api("/api/agent/settings", { method: "PUT", body: JSON.stringify(values) }).then((r) => r.data);
export const getNeedsYou = () => api("/api/agent/needs-you").then((r) => r.data);
export const listOutgoing = () => api("/api/agent/outgoing").then((r) => r.data);
export const cancelOutgoing = (id) => api(`/api/agent/outgoing/${id}/cancel`, { method: "POST" }).then((r) => r.data);
export const sendOutgoingNow = (id) => api(`/api/agent/outgoing/${id}/send-now`, { method: "POST" }).then((r) => r.data);
export const listAlerts = () => api("/api/agent/alerts").then((r) => r.data);
export const dismissAlert = (id) => api(`/api/agent/alerts/${id}/dismiss`, { method: "POST" }).then((r) => r.data);
export const listMyFiles = () => api("/api/agent/files").then((r) => r.data);
export const uploadMyFile = (payload) =>
  api("/api/agent/files", { method: "POST", body: JSON.stringify(payload) }).then((r) => r.data);
export const updateMyFile = (id, values) =>
  api(`/api/agent/files/${id}`, { method: "PATCH", body: JSON.stringify(values) }).then((r) => r.data);
export const deleteMyFile = (id) => api(`/api/agent/files/${id}`, { method: "DELETE" }).then((r) => r.data);
export const checkCompose = (msg) =>
  api("/api/agent/compose/check", { method: "POST", body: JSON.stringify(msg) }).then((r) => r.data);
export const sendCompose = (msg) =>
  api("/api/agent/compose/send", { method: "POST", body: JSON.stringify(msg) }).then((r) => r.data);
export const deleteAccount = () => api("/api/account", { method: "DELETE" }).then((r) => r.data);
