import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow the frontend to connect to the backend API
  // In production, set NEXT_PUBLIC_API_URL to your deployed backend URL
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
  },

  // Enable React strict mode for better development
  reactStrictMode: true,

  // Output as standalone for Vercel deployment
  output: "standalone",
};

export default nextConfig;
