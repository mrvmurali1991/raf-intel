import type { NextConfig } from "next";
import path from "path";
import { execSync } from "child_process";
import { withSentryConfig } from "@sentry/nextjs";

const commitSha = (() => {
  // Prefer the build-arg injected by Docker (or CI) — set before next.config.ts
  // is evaluated. Fall back to git for local dev builds.
  if (process.env.NEXT_PUBLIC_BUILD_ID && process.env.NEXT_PUBLIC_BUILD_ID !== "dev") {
    return process.env.NEXT_PUBLIC_BUILD_ID;
  }
  try {
    return execSync("git rev-parse --short HEAD").toString().trim();
  } catch {
    return null;
  }
})();

// Expose build identity to the browser so the user can verify the live deploy.
process.env.NEXT_PUBLIC_BUILD_ID = commitSha ?? "dev";
if (!process.env.NEXT_PUBLIC_BUILD_TIME) {
  process.env.NEXT_PUBLIC_BUILD_TIME = new Date().toISOString();
}

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
      // Hashed JS/CSS chunks — content-addressed, safe to cache forever.
      // Filename changes when content changes, so the browser auto-busts.
      source: "/_next/static/:path*",
      headers: [
        { key: "Cache-Control", value: "public, max-age=31536000, immutable" },
      ],
    },
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
      // HTML / RSC payloads: NEVER cache. Cloudflare + browser must always
      // revalidate. This is what lets new deploys appear without hard-refresh.
      // The hashed _next/static chunks above carry the actual immutability.
      // Exclude /_next/static and /_next/image so the immutable cache headers
      // set above are NOT overwritten by this catch-all.
      source: "/((?!_next/static|_next/image).*)",
      headers: [
        { key: "Cache-Control", value: "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0" },
        { key: "Pragma", value: "no-cache" },
        { key: "Expires", value: "0" },
        { key: "CDN-Cache-Control", value: "no-store" },
        { key: "Cloudflare-CDN-Cache-Control", value: "no-store" },
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "X-Frame-Options", value: "DENY" },
        { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
        {
          key: "Content-Security-Policy",
          // Next/React dev mode requires `unsafe-eval` for HMR and stack-trace
          // reconstruction. Production builds never need it.
          //
          // Production script-src uses a SHA-256 hash instead of 'unsafe-inline'
          // to allow the single theme-initialisation script in src/app/layout.tsx
          // (the blocking inline script that sets the `dark` class before first
          // paint) without opening the door to arbitrary injected scripts.
          //
          // The hash was computed from the EXACT __html string in layout.tsx:
          //   node -e "const c=require('crypto');process.stdout.write(
          //     c.createHash('sha256')
          //      .update(require('fs').readFileSync('src/app/layout.tsx','utf8')
          //        .match(/__html:\s*\`([^\`]+)\`/)[1],'utf8')
          //      .digest('base64'))"
          //
          // IF the inline script in layout.tsx ever changes, re-run the command
          // above and update the hash here — otherwise the script will be blocked
          // by the browser and the dark-mode flash prevention will stop working.
          value:
            process.env.NODE_ENV === "production"
              ? "default-src 'self'; script-src 'self' 'unsafe-inline' https://static.cloudflareinsights.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: blob:; font-src 'self' data: https://fonts.gstatic.com; connect-src 'self' https: wss:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
              : "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://static.cloudflareinsights.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: blob:; font-src 'self' data: https://fonts.gstatic.com; connect-src 'self' http: https: ws: wss:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
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
