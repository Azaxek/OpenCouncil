import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,

  // Rewrite API calls to the backend.
  // Local dev: proxied to localhost:8000
  // Vercel (monorepo services): proxied to /_/backend via vercel.json experimentalServices
  async rewrites() {
    if (!process.env.NEXT_PUBLIC_API_URL) {
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
    }
    return [];
  },
};

export default nextConfig;