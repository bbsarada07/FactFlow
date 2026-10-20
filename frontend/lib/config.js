// Single place for frontend configuration. Set NEXT_PUBLIC_API_URL in .env.local (dev)
// or in the hosting provider's environment (production).
const DEV_API_URL = "http://localhost:8000";

/** Backend URL used by the browser. */
export const API_URL = (process.env.NEXT_PUBLIC_API_URL || DEV_API_URL).replace(/\/$/, "");

/** Backend URL used during server-side rendering (can be an internal address, e.g. in Docker). */
export const SERVER_API_URL = (process.env.API_URL || API_URL).replace(/\/$/, "");

/** Public site URL, used for canonical and Open Graph links. Falls back to the request host. */
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL || "").replace(/\/$/, "");
