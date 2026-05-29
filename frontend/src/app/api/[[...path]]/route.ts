/**
 * Next.js API Route Handler — proxy to the Python backend.
 *
 * Local dev: Proxies to localhost:8000 (Python backend).
 * Vercel (experimentalServices): Backend is at /_/backend within the same deployment.
 * Custom: Set NEXT_PUBLIC_API_URL env var to override the backend URL.
 */
import { NextRequest, NextResponse } from "next/server";

function getBackendUrl(): string {
  // Custom backend URL takes priority
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL.trim();
  }
  // When deployed on Vercel with experimentalServices, backend is at /_/backend
  if (process.env.VERCEL) {
    return "/_/backend";
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
  const path = url.pathname.replace(/^\/api/, ""); // strip /api prefix
  const backendUrl = getBackendUrl();

  try {
    const backendReqUrl = `${backendUrl}/api${path}${url.search}`;
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
  const path = url.pathname.replace(/^\/api/, "");
  const backendUrl = getBackendUrl();

  try {
    const body = await request.text();
    const backendReqUrl = `${backendUrl}/api${path}${url.search}`;
    const response = await fetch(backendReqUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-forwarded-for": getClientIp(request),
      },
      body,
      signal: AbortSignal.timeout(60000),
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