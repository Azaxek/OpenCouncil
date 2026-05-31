/**
 * Next.js API Route Handler — proxy to the Python backend.
 *
 * Local dev: Proxies to localhost:8000 (Python backend).
 * Vercel: Uses VERCEL_URL to reach the backend service at /_/backend.
 * Custom: Set NEXT_PUBLIC_API_URL env var to override the backend URL.
 */
import { NextRequest, NextResponse } from "next/server";

function getBackendUrl(request: NextRequest): string {
  // Custom backend URL takes priority (set on Vercel env vars)
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL.trim();
  }
  // On Vercel — the Python backend runs on HF Space (Docker needed)
  // Hardcoded fallback so the frontend works without any env var config
  if (process.env.VERCEL) {
    return "https://comfoa-civilly-simplified-backend.hf.space";
  }
  // Local dev
  return "http://localhost:8000";
}

async function proxy(request: NextRequest, method: string, timeout: number) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/^\/api/, "");
  const backendUrl = getBackendUrl(request);
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
    
    // Check content type to avoid parsing HTML as JSON
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      const data = await response.json();
      return NextResponse.json(data, { status: response.status });
    }
    
    // Not JSON — likely an HTML error page. Read text and return as error
    const text = await response.text();
    console.error(`Proxy ${method} ${path} returned non-JSON (${response.status}):`, text.slice(0, 200));
    return NextResponse.json(
      {
        detail: `Backend returned ${response.status} with non-JSON response`,
        path,
        backendUrl,
      },
      { status: 502 }
    );
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