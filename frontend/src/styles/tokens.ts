// Single source of truth for design tokens.
// Per project rule: never copy these values into pages — always import.

export const tokens = {
  // Slate neutral palette (shared across pages)
  slate50:  "#F8FAFC",
  slate100: "#F1F5F9",
  slate200: "#E2E8F0",
  slate300: "#CBD5E1",
  slate400: "#94A3B8",
  slate500: "#64748B",
  slate600: "#475569",
  slate700: "#334155",
  slate800: "#1E293B",
  slate900: "#0F172A",

  white: "#FFFFFF",

  // Risk-level colors (shared between risk indicators, badges, filters)
  riskHigh:       "#DC2626", // red
  riskHighSoft:   "#FEF2F2",
  riskMedium:     "#D97706", // amber / orange
  riskMediumSoft: "#FFFBEB",
  riskLow:        "#059669", // emerald / green
  riskLowSoft:    "#ECFDF5",

  // Brand / primary
  primary:        "#0f766e", // teal-700
  primarySoft:    "#0f766e1A",

  // Semantic
  red600:         "#e11d48",
  amber500:       "#d97706",
  emerald500:     "#059669",
  gray400:        "#9CA3AF",
  gray200:        "#E5E7EB",
  subtleText:     "#64748B",
  violet500:      "#8B5CF6",
} as const;

export type Tokens = typeof tokens;
