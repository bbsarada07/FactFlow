// Single place for frontend configuration.
//
// The browser never talks to the backend directly: it calls this site's own /api/*, which Next.js forwards to
// the backend (next.config.js). Same origin means the HttpOnly session cookie is sent automatically and no
// cross-site cookie rules get in the way.
const DEV_BACKEND_URL = "http://localhost:8000";

/** Backend URL used by the Next.js server (the /api proxy and server-side rendering), never by the browser. */
export const BACKEND_URL = (process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || DEV_BACKEND_URL).replace(/\/$/, "");

/** Base for API calls made in the browser: this site itself. */
export const API_URL = "";

/** Backend URL used during server-side rendering. */
export const SERVER_API_URL = BACKEND_URL;

/** Public site URL, used for canonical and Open Graph links. Falls back to the request host. */
export const SITE_URL = (process.env.NEXT_PUBLIC_SITE_URL || "").replace(/\/$/, "");
