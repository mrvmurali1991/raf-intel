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
} as const;

export type Tokens = typeof tokens;
