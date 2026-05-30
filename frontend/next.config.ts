import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,

  // Rewrite API calls to the backend.
  // Local dev: proxied to localhost:8000
  // Vercel (monorepo services): handled by api/[[...path]]/route.ts proxy -> /_/backend
  async rewrites() {
    // Skip rewrites on Vercel — the catch-all API route handles the proxy
    if (process.env.VERCEL || process.env.NEXT_PUBLIC_API_URL) {
      return [];
    }
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
      {
        source: "/health",
        destination: "http://localhost:8000/health",
      },
    ];
  },
};

export default nextConfig;