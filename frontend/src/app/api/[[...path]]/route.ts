/**
 * Next.js API Route Handler — proxy to the Python backend.
 *
 * Local dev: Proxies to localhost:8000 (Python backend).
 * Vercel: Uses VERCEL_URL to reach the backend service at /_/backend.
 * Custom: Set NEXT_PUBLIC_API_URL env var to override the backend URL.
 */
import { NextRequest, NextResponse } from "next/server";

function getBackendUrl(): string {
  // Custom backend URL takes priority
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL.trim();
  }
  // On Vercel with experimentalServices
  if (process.env.VERCEL) {
    const vercelUrl = process.env.VERCEL_URL || process.env.VERCEL_BRANCH_URL;
    if (vercelUrl) {
      const protocol = process.env.VERCEL_ENV === "production" ? "https" : "https";
      return `${protocol}://${vercelUrl}/_/backend`;
    }
  }
  // Local dev
  return "http://localhost:8000";
}

async function proxy(request: NextRequest, method: string, timeout: number) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/^\/api/, "");
  const backendUrl = getBackendUrl();
  const backendReqUrl = `${backendUrl}/api${path}${url.search}`;

  try {
    const fetchOptions: RequestInit = {
      method,
      headers: {
        "Content-Type": "application/json",
      },
      signal: AbortSignal.timeout(timeout),
    };

    if (method === "POST" || method === "PUT" || method === "PATCH") {
      const body = await request.text();
      if (body) fetchOptions.body = body;
      if (request.headers.get("x-forwarded-for")) {
        (fetchOptions.headers as Record<string, string>)["x-forwarded-for"] =
          request.headers.get("x-forwarded-for")!.split(",")[0]!.trim();
      }
    }

    const response = await fetch(backendReqUrl, fetchOptions);
    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    console.error(`Proxy ${method} ${path} failed:`, error);
    return NextResponse.json(
      {
        detail: `Backend unavailable. ${error instanceof Error ? error.message : "Unknown error"}`,
        path,
        backendUrl,
      },
      { status: 503 }
    );
  }
}

export async function GET(request: NextRequest) {
  return proxy(request, "GET", 10000);
}

export async function POST(request: NextRequest) {
  return proxy(request, "POST", 60000);
}

export async function PUT(request: NextRequest) {
  return proxy(request, "PUT", 60000);
}

export async function PATCH(request: NextRequest) {
  return proxy(request, "PATCH", 60000);
}

export async function DELETE(request: NextRequest) {
  return proxy(request, "DELETE", 10000);
}