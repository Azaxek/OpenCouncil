/**
 * Next.js API Route Handler — proxy /health to the Python backend.
 *
 * Local dev: Proxies to localhost:8000.
 * Vercel (experimentalServices): Backend is at /_/backend.
 * Custom: Set NEXT_PUBLIC_API_URL env var to override.
 */
import { NextRequest, NextResponse } from "next/server";

function getBackendUrl(request: NextRequest): string {
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL.trim();
  }
  if (process.env.VERCEL) {
    const origin = new URL(request.url).origin;
    return `${origin}/_/backend`;
  }
  return "http://localhost:8000";
}

export async function GET(request: NextRequest) {
  const backendUrl = getBackendUrl(request);

  try {
    const response = await fetch(`${backendUrl}/health`, {
      method: "GET",
      headers: { "Content-Type": "application/json" },
      signal: AbortSignal.timeout(10000),
    });
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error("Proxy /health failed:", error);
    return NextResponse.json(
      {
        detail: `Backend unavailable. ${error instanceof Error ? error.message : "Unknown error"}`,
        backendUrl,
      },
      { status: 503 }
    );
  }
}