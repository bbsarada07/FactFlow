/** @type {import('next').NextConfig} */

// The browser only ever talks to this site. /api/* (and /health) are forwarded to the FastAPI backend, so the
// HttpOnly session cookie is first-party and sent automatically, with no cross-site cookie rules involved.
const BACKEND_URL = (process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Compression buffers responses, which would hold back live Server-Sent Events from the backend.
  compress: false,
  experimental: {
    // A live verification streams for up to a few minutes; the default proxy timeout is 30 s.
    proxyTimeout: 300_000,
  },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${BACKEND_URL}/api/:path*` },
      { source: "/health", destination: `${BACKEND_URL}/health` },
    ];
  },
};

module.exports = nextConfig;
