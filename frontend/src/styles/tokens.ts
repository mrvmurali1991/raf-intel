/**
 * @deprecated DO NOT ADD NEW VALUES HERE.
 *
 * This file is the single source of truth for design tokens used as inline
 * `style={{}}` props across ~52 files (legacy pattern).  New components must
 * use Tailwind utility classes or CSS-variable references directly instead.
 *
 * Dark-mode strategy (2025-05-18 refactor):
 *   - Tokens that map 1-to-1 to a CSS variable defined in globals.css now
 *     return `var(--token-name)` strings instead of hard-coded hex values.
 *     At runtime the browser resolves these through the active `:root` / `.dark`
 *     block, so dark-mode is handled automatically without any JS toggling.
 *   - Domain-specific tokens with no direct CSS-variable counterpart retain
 *     their hex literals — they are overridden at the stylesheet level by the
 *     `.dark [style*="..."]` selectors already present in globals.css.
 *   - The `resolveToken(value)` helper is provided for the rare case where a
 *     consumer needs the *computed* hex string at runtime (e.g. canvas/SVG
 *     APIs that cannot consume `var(--…)` strings).
 *
 * Migration guide for new code:
 *   - Background  → `bg-primary`, `bg-destructive`, `bg-muted`, etc.
 *   - Text        → `text-primary`, `text-muted-foreground`, etc.
 *   - Border      → `border-border`, `border-primary`, etc.
 *   - Risk badges → use the `.status-dot-*` CSS classes from globals.css.
 */

// ---------------------------------------------------------------------------
// Runtime resolver — use this when you need a real computed colour string
// (e.g. for Chart.js datasets or <canvas> fill).  Returns the hex/rgb value
// of any `var(--x)` token by reading the live CSS custom property.
// Falls back to the supplied `fallback` when called in SSR / test environments.
// ---------------------------------------------------------------------------
export function resolveToken(
  value: string,
  fallback = "inherit"
): string {
  if (typeof document === "undefined") return fallback;
  if (!value.startsWith("var(")) return value;
  const name = value.slice(4, -1).trim(); // strip "var(" and ")"
  return (
    getComputedStyle(document.documentElement)
      .getPropertyValue(name)
      .trim() || fallback
  );
}

// ---------------------------------------------------------------------------
// Token map
// ---------------------------------------------------------------------------
export const tokens = {
  // ---- Slate neutral palette ----
  // These map to --muted / --muted-foreground / --border / --foreground in globals.css.
  // Kept as hex so existing consumers still get a concrete value; the dark-mode
  // overrides in globals.css catch the rendered rgb() values.
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

  // ---- Risk-level colors ----
  riskHigh:       "#DC2626",
  riskHighSoft:   "#FEF2F2",
  riskMedium:     "#D97706",
  riskMediumSoft: "#FFFBEB",
  riskLow:        "#059669",
  riskLowSoft:    "#ECFDF5",

  // ---- Warning / amber palette ----
  warningSoft:   "#FEF3C7",
  warningBorder: "#FCD34D",
  warningText:   "#78350F",
  warningStrong: "#F59E0B",

  // ---- Primary action / brand-info palette ----
  // --primary is defined in :root and overridden in .dark in globals.css.
  // Use var(--primary) so dark mode resolves automatically.
  primary:       "hsl(var(--primary))",
  primaryDark:   "hsl(var(--primary))",          // dark variant resolves via .dark block
  primarySoft:   "hsl(var(--primary) / 0.08)",

  // ---- Success palette ----
  success:       "#10B981",
  successDark:   "#047857",
  successSoft:   "#ECFDF5",

  // ---- Danger / destructive palette ----
  // --destructive is defined in globals.css for both modes.
  danger:        "hsl(var(--destructive))",
  dangerSoft:    "#FEF2F2",
  dangerBorder:  "#FECACA",

  // ---- Emerald palette ----
  emerald100:    "#D1FAE5",
  emerald300:    "#6EE7B7",
  emerald800:    "#065F46",

  // ---- Info-blue and accent purple ----
  infoBlue:      "#3B82F6",
  accentPurple:  "#8B5CF6",

  // ---- Sky / teal sub-chips ----
  skyBg:         "#F0F9FF",
  skyBorder:     "#BAE6FD",
  skyText:       "#0369A1",
  orangeBg:      "#FFF7ED",
  orangeBorder:  "#FED7AA",
  orangeText:    "#C2410C",
  violetBg:      "#F5F3FF",
  violetBorder:  "#DDD6FE",
  violetText:    "#6D28D9",

  // ---- Indigo accent ----
  indigoText:    "#6366f1",
  indigoBg:      "#eef2ff",

  // ---- Utility / separator ----
  // --border is defined for both modes; use var() so tables auto-adapt.
  divider:       "hsl(var(--border))",

  // ---- Brand teal (clinical / OpenEMR) ----
  // Exposed as --brand-primary in globals.css; use that for tenant-aware contexts.
  teal700:       "#0F766E",
  teal900:       "#134E4A",
  tealSoft:      "rgba(15, 118, 110, 0.06)",
  tealRing:      "rgba(15, 118, 110, 0.18)",

  // ---- Neutral hover / stripe helpers ----
  bgFaintCard:   "#FAFBFC",
  bgSubtle:      "#FAFAF8",
  warningMuted:  "#92400E",
  dangerStrong:  "#DC2626",
  dangerMedium:  "#EF4444",
  dangerAlt:     "#991B1B",
  successMedium: "#059669",
  successStrong: "#10B981",
  amber600:      "#D97706",

  // ---- Cohen's kappa IRR band colours ----
  kappaExcellent:     "#16A34A",
  kappaExcellentSoft: "#DCFCE7",
  kappaModerate:      "#D97706",
  kappaModerateSoft:  "#FEF3C7",
  kappaPoor:          "#DC2626",
  kappaPoorSoft:      "#FEE2E2",
  kappaNeutral:       "#94A3B8",
  kappaNeutralSoft:   "#F1F5F9",

  // ---- Typography helpers ----
  // Consumers: attestations/page.tsx uses tokens.font?.sans as a fontFamily value.
  font: {
    sans: "var(--font-sans, system-ui, sans-serif)",
    mono: "var(--font-mono, ui-monospace, monospace)",
  },
} as const;

export type Tokens = typeof tokens;
