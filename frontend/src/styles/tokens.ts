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

  // Warning / amber palette — "needs attention" banners and status pills.
  warningSoft:   "#FEF3C7",
  warningBorder: "#FCD34D",
  warningText:   "#78350F",
  warningStrong: "#F59E0B",

  // Primary action / brand-info palette — primary CTAs and info icons.
  primary:       "#2563EB",
  primaryDark:   "#1D4ED8",
  primarySoft:   "rgba(37, 99, 235, 0.08)",

  // Success palette — confirmation icons and "all clear" states.
  success:       "#10B981",
  successDark:   "#047857",
  successSoft:   "#ECFDF5",

  // Danger / destructive palette — error banners, rejected states.
  danger:        "#B91C1C",
  dangerSoft:    "#FEF2F2",
  dangerBorder:  "#FECACA",

  // Emerald palette — bonus / earnings / "you earned" badges.
  emerald100:    "#D1FAE5",
  emerald300:    "#6EE7B7",
  emerald800:    "#065F46",

  // Info-blue and accent purple — used by velocity / forecast charts.
  infoBlue:      "#3B82F6",
  accentPurple:  "#8B5CF6",

  // Sky / teal palette — used by demographic/score sub-chips.
  skyBg:         "#F0F9FF",
  skyBorder:     "#BAE6FD",
  skyText:       "#0369A1",
  orangeBg:      "#FFF7ED",
  orangeBorder:  "#FED7AA",
  orangeText:    "#C2410C",
  violetBg:      "#F5F3FF",
  violetBorder:  "#DDD6FE",
  violetText:    "#6D28D9",

  // Indigo accent — bulk-action selected state, KG annotation chips.
  indigoText:    "#6366f1",
  indigoBg:      "#eef2ff",

  // Utility / separator colour.
  divider:       "#CBD5E1",

  // Brand teal (clinical/OpenEMR) — distinct from "primary" blue.
  teal700:       "#0F766E",
  teal900:       "#134E4A",
  tealSoft:      "rgba(15, 118, 110, 0.06)",
  tealRing:      "rgba(15, 118, 110, 0.18)",

  // Neutral hover / stripe helpers used in tables.
  bgFaintCard:   "#FAFBFC",
  bgSubtle:      "#FAFAF8",
  warningMuted:  "#92400E",
  dangerStrong:  "#DC2626",
  dangerMedium:  "#EF4444",
  dangerAlt:     "#991B1B",
  successMedium: "#059669",
  successStrong: "#10B981",
  amber600:      "#D97706",

  // Cohen's kappa IRR band colours
  kappaExcellent:     "#16A34A", // green-600  — kappa >= 0.80
  kappaExcellentSoft: "#DCFCE7", // green-100
  kappaModerate:      "#D97706", // amber-600  — 0.40 <= kappa < 0.80
  kappaModerateSoft:  "#FEF3C7", // amber-100
  kappaPoor:          "#DC2626", // red-600    — kappa < 0.40
  kappaPoorSoft:      "#FEE2E2", // red-100
  kappaNeutral:       "#94A3B8", // slate-400  — no data / proportion-only
  kappaNeutralSoft:   "#F1F5F9", // slate-100
} as const;

export type Tokens = typeof tokens;
