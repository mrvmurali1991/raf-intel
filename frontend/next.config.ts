import type { NextConfig } from "next";
import path from "path";
import { execSync } from "child_process";

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
      ],
    },
  ],
};

export default nextConfig;
