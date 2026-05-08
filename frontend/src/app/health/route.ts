/**
 * Next.js API Route Handler — proxy /health to the Python backend on HF Spaces.
 *
 * This is a separate route because the catch-all at /api/[[...path]]/route.ts
 * only matches paths under /api/.
 */
import { NextRequest, NextResponse } from "next/server";

function getBackendUrl(): string {
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL.trim();
  }
  return "http://localhost:8000";
}

export async function GET(_request: NextRequest) {
  const backendUrl = getBackendUrl();

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
      },
      { status: 503 }
    );
  }
}
