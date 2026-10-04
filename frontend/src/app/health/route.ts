/**
 * Next.js API Route Handler — proxy /health to the Python backend.
 *
 * Local dev: Proxies to localhost:8000.
 * Vercel: Proxies to the Hugging Face Space backend.
 * Custom: Set NEXT_PUBLIC_API_URL env var to override.
 */
import { NextResponse } from "next/server";
import { getBackendUrl } from "@/lib/backend";

export async function GET() {
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
        backendUrl,
      },
      { status: 503 }
    );
  }
}