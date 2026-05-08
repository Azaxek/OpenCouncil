import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Enable React strict mode for better development
  reactStrictMode: true,

  // Rewrite API calls to the backend during local development only.
  // On Vercel (production), the API route handler at app/api/[[...path]]/route.ts
  // proxies to the HF Space backend via NEXT_PUBLIC_API_URL env var.
  async rewrites() {
    // Only apply rewrites when NEXT_PUBLIC_API_URL is NOT set (i.e., local dev)
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
