import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  output: "standalone",
  generateBuildId: () => `build-${Date.now()}`,
  typescript: {
    ignoreBuildErrors: false,
  },
  headers: async () => [
    {
      source: "/(.*)",
      headers: [
        { key: "Cache-Control", value: "no-cache, no-store, must-revalidate" },
        { key: "Pragma", value: "no-cache" },
      ],
    },
  ],
  turbopack: {
    root: path.resolve(__dirname),
    resolveAlias: {
      tailwindcss: path.resolve(__dirname, "node_modules/tailwindcss"),
      "tw-animate-css": path.resolve(__dirname, "node_modules/tw-animate-css"),
    },
  },
};

export default nextConfig;
