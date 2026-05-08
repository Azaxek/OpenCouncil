/**
 * Next.js API Route Handler — proxy to the Python backend on HF Spaces.
 *
 * Local dev: Proxies to localhost:8000 (Python backend).
 * Vercel: Proxies to HF Spaces backend URL (set via NEXT_PUBLIC_API_URL env var).
 *
 * This eliminates the need for Python on Vercel entirely.
 */
import { NextRequest, NextResponse } from "next/server";

function getBackendUrl(): string {
  // On Vercel, use the Railway backend URL
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL;
  }
  // Local dev
  return "http://localhost:8000";
}

function getClientIp(request: NextRequest): string {
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded) return forwarded.split(",")[0].trim();
  const ip = request.headers.get("x-real-ip");
  return ip || "127.0.0.1";
}

export async function GET(request: NextRequest) {
  const url = new URL(request.url);
  const path = url.pathname;
  const backendUrl = getBackendUrl();

  try {
    const backendReqUrl = `${backendUrl}${path}${url.search}`;
    const response = await fetch(backendReqUrl, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
        "x-forwarded-for": getClientIp(request),
      },
      signal: AbortSignal.timeout(10000),
    });
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error(`Proxy GET ${path} failed:`, error);
    return NextResponse.json(
      {
        detail: `Backend unavailable. ${error instanceof Error ? error.message : "Unknown error"}`,
      },
      { status: 503 }
    );
  }
}

export async function POST(request: NextRequest) {
  const url = new URL(request.url);
  const path = url.pathname;
  const backendUrl = getBackendUrl();

  try {
    const body = await request.text();
    const backendReqUrl = `${backendUrl}${path}${url.search}`;
    const response = await fetch(backendReqUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-forwarded-for": getClientIp(request),
      },
      body,
      signal: AbortSignal.timeout(60000), // 60s for summarization
    });
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error(`Proxy POST ${path} failed:`, error);
    return NextResponse.json(
      {
        detail: `Backend unavailable. ${error instanceof Error ? error.message : "Unknown error"}`,
      },
      { status: 503 }
    );
  }
}
