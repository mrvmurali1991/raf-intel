/**
 * Next.js catch-all API proxy route.
 *
 * Forwards every request to /api/* to the backend (NEXT_PUBLIC_API_URL).
 * This ensures that any code using relative `fetch("/api/...")` works
 * correctly — the request is proxied to raf-api rather than returning a 404.
 *
 * Auth headers (Authorization: Bearer ...) and the original request body
 * are forwarded as-is. Cookies are also forwarded for credential-based flows.
 *
 * This route is used as a fallback so existing deployed JS bundles that make
 * relative-URL fetch() calls continue to work after the API_BASE migration.
 */

import { NextRequest, NextResponse } from "next/server";

const BACKEND_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8500";

// Headers that must NOT be forwarded — Next.js/host-specific headers that
// would confuse the backend or cause request loops.
const BLOCKED_HEADERS = new Set([
  "host",
  "connection",
  "transfer-encoding",
  "te",
  "upgrade",
  "proxy-authorization",
  "x-forwarded-host",
  "x-forwarded-proto",
  "x-forwarded-for",
]);

async function proxyRequest(req: NextRequest): Promise<NextResponse> {
  const url = req.nextUrl;

  // Build the backend URL: strip the /api prefix since the backend already
  // mounts at /api (or preserve it — the backend expects /api/... paths).
  const backendUrl = new URL(url.pathname + url.search, BACKEND_BASE);

  const forwardHeaders = new Headers();
  req.headers.forEach((value, key) => {
    if (!BLOCKED_HEADERS.has(key.toLowerCase())) {
      forwardHeaders.set(key, value);
    }
  });

  // Forward the client IP for audit-trail purposes.
  const clientIp = req.headers.get("x-real-ip") ?? req.headers.get("x-forwarded-for");
  if (clientIp) {
    forwardHeaders.set("x-forwarded-for", clientIp);
  }

  let body: BodyInit | undefined;
  if (req.method !== "GET" && req.method !== "HEAD") {
    body = await req.arrayBuffer();
  }

  try {
    const backendRes = await fetch(backendUrl.toString(), {
      method: req.method,
      headers: forwardHeaders,
      body,
      // Do not follow redirects — let the client handle them.
      redirect: "manual",
      // @ts-expect-error — Node 18+ fetch supports duplex for streaming bodies
      duplex: body instanceof ReadableStream ? "half" : undefined,
    });

    const resHeaders = new Headers();
    backendRes.headers.forEach((value, key) => {
      // Strip headers that Next.js manages itself.
      if (!["transfer-encoding", "connection", "keep-alive"].includes(key.toLowerCase())) {
        resHeaders.set(key, value);
      }
    });

    return new NextResponse(backendRes.body, {
      status: backendRes.status,
      statusText: backendRes.statusText,
      headers: resHeaders,
    });
  } catch (err) {
    console.error("[api-proxy] Backend unreachable:", err);
    return NextResponse.json(
      { error: "Backend service unavailable", detail: String(err) },
      { status: 503 }
    );
  }
}

export const GET = proxyRequest;
export const POST = proxyRequest;
export const PUT = proxyRequest;
export const PATCH = proxyRequest;
export const DELETE = proxyRequest;
export const HEAD = proxyRequest;
export const OPTIONS = proxyRequest;
