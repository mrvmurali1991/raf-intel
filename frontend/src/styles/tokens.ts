/**
 * @radius-policy Radius tokens — use ONLY Tailwind token classes, never arbitrary values.
 *   rounded-sm  → ~6px   (--radius * 0.6)  — inputs, chips
 *   rounded-md  → ~8px   (--radius * 0.8)  — buttons, small cards
 *   rounded-lg  → 10px   (--radius)        — standard cards (default)
 *   rounded-xl  → ~14px  (--radius * 1.4)  — hero/modal cards only
 *   rounded-2xl → ~18px  (--radius * 1.8)  — login panel only
 *   rounded-full                            — badges, avatars, pills ONLY
 *   NEVER use rounded-[Npx] — add a token above instead.
 *   eslint: no arbitrary value rounded classes (enforced by review)
 *
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
 *   - All semantic domain tokens (risk, warning, kappa, sky/orange/violet chips)
 *     now return `hsl(var(--token-name))` — dark mode is handled via the `.dark`
 *     block in globals.css, no `[style*="rgb(...)"]` spray selectors needed.
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
  riskHigh:       "hsl(var(--risk-high))",
  riskHighSoft:   "hsl(var(--risk-high-soft))",
  riskMedium:     "hsl(var(--risk-medium))",
  riskMediumSoft: "hsl(var(--risk-medium-soft))",
  riskLow:        "hsl(var(--risk-low))",
  riskLowSoft:    "hsl(var(--risk-low-soft))",

  // ---- Warning / amber palette ----
  warningSoft:   "hsl(var(--warning-soft))",
  warningBorder: "hsl(var(--warning-border))",
  warningText:   "hsl(var(--warning-text))",
  warningStrong: "hsl(var(--warning-strong))",

  // ---- Primary action / brand-info palette ----
  // --primary is defined in :root and overridden in .dark in globals.css.
  // Use var(--primary) so dark mode resolves automatically.
  primary:       "hsl(var(--primary))",
  primaryDark:   "hsl(var(--primary))",          // dark variant resolves via .dark block
  primarySoft:   "hsl(var(--primary) / 0.08)",

  // ---- Success palette ----
  success:       "hsl(var(--success-base))",
  successDark:   "hsl(var(--success-dark))",
  successSoft:   "hsl(var(--success-soft))",

  // ---- Danger / destructive palette ----
  // --destructive is defined in globals.css for both modes.
  danger:        "hsl(var(--destructive))",
  dangerSoft:    "hsl(var(--danger-soft))",
  dangerBorder:  "hsl(var(--danger-border))",

  // ---- Emerald palette ----
  emerald100:    "hsl(var(--emerald-100))",
  emerald300:    "hsl(var(--emerald-300))",
  emerald800:    "hsl(var(--emerald-800))",

  // ---- Info-blue and accent purple ----
  infoBlue:      "hsl(var(--info-blue))",
  accentPurple:  "hsl(var(--accent-purple))",

  // ---- Sky / teal sub-chips ----
  skyBg:         "hsl(var(--sky-bg))",
  skyBorder:     "hsl(var(--sky-border))",
  skyText:       "hsl(var(--sky-text))",
  orangeBg:      "hsl(var(--orange-bg))",
  orangeBorder:  "hsl(var(--orange-border))",
  orangeText:    "hsl(var(--orange-text))",
  violetBg:      "hsl(var(--violet-bg))",
  violetBorder:  "hsl(var(--violet-border))",
  violetText:    "hsl(var(--violet-text))",

  // ---- Indigo accent ----
  indigoText:    "hsl(var(--indigo-text))",
  indigoBg:      "hsl(var(--indigo-bg))",

  // ---- Utility / separator ----
  // --border is defined for both modes; use var() so tables auto-adapt.
  divider:       "hsl(var(--border))",

  // ---- Brand teal (clinical / OpenEMR) ----
  // Exposed as --brand-primary in globals.css; use that for tenant-aware contexts.
  teal700:       "hsl(var(--teal-700))",
  teal900:       "hsl(var(--teal-900))",
  tealSoft:      "hsl(var(--teal-soft))",
  tealRing:      "hsl(var(--teal-ring))",

  // ---- Neutral hover / stripe helpers ----
  bgFaintCard:   "hsl(var(--bg-faint-card))",
  bgSubtle:      "hsl(var(--bg-subtle))",
  warningMuted:  "hsl(var(--warning-muted))",
  dangerStrong:  "hsl(var(--danger-strong))",
  dangerMedium:  "hsl(var(--danger-medium))",
  dangerAlt:     "hsl(var(--danger-alt))",
  successMedium: "hsl(var(--success-medium))",
  successStrong: "hsl(var(--success-strong))",
  amber600:      "hsl(var(--amber-600))",

  // ---- Cohen's kappa IRR band colours ----
  kappaExcellent:     "hsl(var(--kappa-excellent))",
  kappaExcellentSoft: "hsl(var(--kappa-excellent-soft))",
  kappaModerate:      "hsl(var(--kappa-moderate))",
  kappaModerateSoft:  "hsl(var(--kappa-moderate-soft))",
  kappaPoor:          "hsl(var(--kappa-poor))",
  kappaPoorSoft:      "hsl(var(--kappa-poor-soft))",
  kappaNeutral:       "hsl(var(--kappa-neutral))",
  kappaNeutralSoft:   "hsl(var(--kappa-neutral-soft))",

  // ---- Typography helpers ----
  // Consumers: attestations/page.tsx uses tokens.font?.sans as a fontFamily value.
  font: {
    sans: "var(--font-sans, system-ui, sans-serif)",
    mono: "var(--font-mono, ui-monospace, monospace)",
  },
} as const;

export type Tokens = typeof tokens;
