export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export async function api(path, options = {}) {
  let res;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    });
  } catch {
    throw new ApiError(`Can't reach the NemesisAI backend at ${API_URL}. Is it running?`, 0);
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = Array.isArray(body.detail)
      ? body.detail.map((d) => d.msg).join("; ")
      : body.detail || `Request failed (${res.status})`;
    throw new ApiError(detail, res.status);
  }
  return { status: res.status, data: body };
}

export const startVerification = (payload) =>
  api("/api/verify", { method: "POST", body: JSON.stringify(payload) }).then((r) => r.data);

export const getResult = (id) => api(`/api/result/${id}`);
export const getHistory = (limit = 20) => api(`/api/history?limit=${limit}`).then((r) => r.data);
export const getStats = () => api("/api/stats").then((r) => r.data);
export const getIncidents = () => api("/api/incidents").then((r) => r.data);
export const streamUrl = (id) => `${API_URL}/api/stream/${id}`;
