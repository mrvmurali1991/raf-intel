import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * Public path prefixes that never require authentication.
 *
 * /login        — login page itself
 * /api          — all backend API routes (JWT validated by the backend)
 * /_next        — Next.js runtime chunks, HMR, etc.
 * /favicon.ico  — browser favicon request
 * /robots.txt   — crawler directives
 * /sitemap.xml  — SEO sitemap
 * /icons        — PWA / app icons served from /public/icons
 * /images       — static images served from /public/images
 */
const PUBLIC_PATHS = [
  "/login",
  "/api",
  "/_next",
  "/favicon.ico",
  "/robots.txt",
  "/sitemap.xml",
  "/icons",
  "/images",
];

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Allow public paths without any auth check
  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  // Check for the lightweight boolean cookie set by the client after a
  // successful login. This carries no sensitive data — its sole purpose is
  // to let middleware know a session exists before any JS executes on the
  // client. The actual JWT is validated by the backend on every API call.
  const authCookie = request.cookies.get("raf_authenticated");

  if (!authCookie || authCookie.value !== "true") {
    const loginUrl = new URL("/login", request.url);
    // Preserve the originally-requested path so the login page can redirect
    // the user back after a successful sign-in.
    if (pathname !== "/") {
      loginUrl.searchParams.set("redirect", pathname);
    }
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  /**
   * Run on every path EXCEPT Next.js static assets and optimised images,
   * which are served directly from the CDN / file system.
   */
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
