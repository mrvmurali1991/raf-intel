/**
 * Next.js Middleware entry point.
 *
 * Next.js requires the middleware to be exported as `middleware` from a file
 * named `middleware.ts` at the project root (alongside next.config.ts).
 * The actual logic lives in src/proxy.ts to keep it co-located with the app.
 */
export { proxy as middleware } from "./src/proxy";

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
