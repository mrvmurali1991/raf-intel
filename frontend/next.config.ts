import type { NextConfig } from "next";
import path from "path";
import { execSync } from "child_process";
import { withSentryConfig } from "@sentry/nextjs";

const commitSha = (() => {
  try {
    return execSync("git rev-parse --short HEAD").toString().trim();
  } catch {
    return null;
  }
})();

const nextConfig: NextConfig = {
  output: "standalone",
  generateBuildId: () => commitSha ?? null,
  typescript: {
    ignoreBuildErrors: false,
  },
  // Fix: Set turbopack root to THIS project directory
  // Without this, Next.js scans the entire home directory and spikes CPU
  turbopack: {
    root: path.resolve(__dirname),
  },
  // Production optimizations
  poweredByHeader: false,
  reactStrictMode: true,
  compress: true,
  // Security headers
  headers: async () => [
    {
      // Public images/icons: cache for 1 month
      source: "/:path*.(png|jpg|jpeg|gif|ico|svg|webp)",
      headers: [
        { key: "Cache-Control", value: "public, max-age=2592000" },
      ],
    },
    {
      // API routes: no cache
      source: "/api/:path*",
      headers: [
        { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
      ],
    },
    {
      // HTML pages: short cache with revalidation
      source: "/:path*",
      headers: [
        { key: "Cache-Control", value: "public, max-age=60, stale-while-revalidate=300" },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "X-Frame-Options", value: "DENY" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        {
          key: "Content-Security-Policy",
          // Next/React dev mode requires `unsafe-eval` for HMR and stack-trace
          // reconstruction. Production builds never need it.
          value:
            process.env.NODE_ENV === "production"
              ? "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' https: wss:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
              : "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' http: https: ws: wss:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        },
        {
          key: "Strict-Transport-Security",
          value: "max-age=63072000; includeSubDomains",
        },
        {
          key: "Permissions-Policy",
          value:
            "camera=(), microphone=(), geolocation=(), payment=(), usb=(), magnetometer=(), gyroscope=()",
        },
        { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
      ],
    },
  ],
};

// Only enable the Sentry webpack plugin (source map upload, instrumentation
// injection) when a DSN is configured. Without this guard, builds without
// Sentry credentials emit noisy warnings on every CI run. The runtime SDK
// in sentry.{client,server,edge}.config.ts still no-ops cleanly when DSN
// is absent — so wrapping here is purely for the build-time integration.
const sentryEnabled = Boolean(
  process.env.NEXT_PUBLIC_SENTRY_DSN || process.env.SENTRY_DSN,
);

export default sentryEnabled
  ? withSentryConfig(nextConfig, {
      silent: true,
      // Source map upload requires SENTRY_AUTH_TOKEN; if absent the plugin
      // skips upload but still injects release/debug-id metadata.
      org: process.env.SENTRY_ORG,
      project: process.env.SENTRY_PROJECT,
      disableLogger: true,
      // Tunnel through a Next.js rewrite to bypass ad-blockers (optional).
      // Not enabled by default — keep CSP/connect-src minimal.
    })
  : nextConfig;
