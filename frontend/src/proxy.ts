import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Paths that are allowed without authentication.
 * Matches login flow, API routes (which have their own auth), Next internals,
 * static assets, and the public embed surface.
 */
const PUBLIC_PATH_RE = /^\/(login|forgot-password|reset-password|api|_next|favicon|public|embed)(\/|$|\?|\.)/;

/**
 * Static asset extensions that should bypass auth gating entirely.
 */
const STATIC_ASSET_RE = /\.(svg|png|jpg|jpeg|gif|webp|ico|css|js|map|woff|woff2|ttf|otf)$/i;

export function proxy(request: NextRequest) {
  try {
    const { pathname } = request.nextUrl;

    // Allow public paths through without inspection.
    if (PUBLIC_PATH_RE.test(pathname)) {
      return NextResponse.next();
    }

    // Allow static assets through without inspection.
    if (STATIC_ASSET_RE.test(pathname)) {
      return NextResponse.next();
    }

    // Root '/' is treated as a protected route — the app redirects to either
    // /login or the dashboard depending on auth state.
    const authCookie = request.cookies.get("raf_authenticated");
    const isAuthed = !!authCookie && authCookie.value.length > 0 && authCookie.value !== "false";

    if (!isAuthed) {
      const loginUrl = new URL(
        "/login?next=" + encodeURIComponent(pathname),
        request.url,
      );
      return NextResponse.redirect(loginUrl);
    }

    return NextResponse.next();
  } catch {
    // Defensive: never 500 the whole site from the auth gate.
    return NextResponse.next();
  }
}
