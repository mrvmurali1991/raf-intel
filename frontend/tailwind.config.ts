import type { Config } from "tailwindcss";

/**
 * Tailwind CSS v4 Configuration
 *
 * In Tailwind v4 the primary theme is defined via @theme blocks in globals.css.
 * This config file provides additional theme extensions (custom colors, fonts,
 * animations) that are merged via the @config directive in globals.css.
 */
const config: Config = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        brand: {
          teal: "#0f766e",
          "teal-light": "#14b8a6",
          "teal-dark": "#0d5f58",
          "teal-soft": "#ccfbf1",
        },
        risk: {
          high: "#DC2626",
          "high-soft": "#FEE2E2",
          "high-fg": "#991B1B",
          medium: "#D97706",
          "medium-soft": "#FEF3C7",
          "medium-fg": "#92400E",
          low: "#059669",
          "low-soft": "#D1FAE5",
          "low-fg": "#065F46",
        },
        raf: {
          blue: "#2563EB",
          "blue-soft": "#DBEAFE",
          cyan: "#06B6D4",
          "cyan-soft": "#CFFAFE",
          emerald: "#059669",
          "emerald-soft": "#D1FAE5",
          amber: "#D97706",
          "amber-soft": "#FEF3C7",
          rose: "#E11D48",
          "rose-soft": "#FFE4E6",
          violet: "#8B5CF6",
          "violet-soft": "#EDE9FE",
        },
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Monaco",
          "Consolas",
          "Liberation Mono",
          "Courier New",
          "monospace",
        ],
        heading: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "sans-serif",
        ],
      },
      borderRadius: {
        "4xl": "2rem",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        scaleIn: {
          "0%": { opacity: "0", transform: "scale(0.95)" },
          "100%": { opacity: "1", transform: "scale(1)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
      },
      animation: {
        "fade-in": "fadeIn 0.25s ease-out",
        "slide-up": "slideUp 0.3s ease-out",
        "scale-in": "scaleIn 0.2s ease-out",
        shimmer: "shimmer 1.5s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
