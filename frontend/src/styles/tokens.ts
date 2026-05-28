// Single source of truth for design tokens. CSS vars defined in globals.css, JS references here.

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
 * This file is the BRIDGE between CSS custom properties (defined in globals.css)
 * and JavaScript/TypeScript consumers.  Every exported value references a
 * `var(--token-name)` string so that dark-mode and theming are handled
 * automatically by the browser — no JS toggling required.
 *
 * Usage in React inline styles:
 *   style={{ color: tokens.primary }}          // resolves via CSS at runtime
 *   style={{ fontSize: typography.base }}      // '14px' literal
 *   style={{ padding: spacing[4] }}            // '16px' literal
 *
 * For canvas/SVG APIs that cannot consume var() strings, use resolveToken():
 *   const hex = resolveToken(tokens.primary, '#0f766e');
 *
 * ── COLOR DISCIPLINE RULES (enforced 2026-05-18) ────────────────────────────
 *
 *   TEAL    = brand / primary action ONLY.
 *             Use for: buttons, active states, action links, focus rings,
 *             step number badges, icon backgrounds on action cards.
 *             Decorative pills with no action → use slate/muted instead.
 *             Tokens: tokens.primary, tokens.teal700, tokens.tealSoft, tokens.tealRing
 *
 *   RED / AMBER / GREEN = status ONLY (destructive / warning / success).
 *             Use for: error banners, warning notices (e.g. EMR not connected,
 *             V28 hero), success confirmations, risk-tier indicators.
 *             Never use red/amber/green decoratively.
 *             Tokens: tokens.danger*, tokens.warning*, tokens.success*,
 *                     tokens.riskHigh*, tokens.riskMedium*, tokens.riskLow*
 *
 *   BLUE / PURPLE = secondary analytics ONLY (charts, data-viz, hyperlinks).
 *             Use for: chart series, histogram bars, sparklines, data-coverage
 *             graphs, and in-prose/table hyperlinks.
 *             Never use blue/purple for action buttons, badges, or card accents
 *             on operational screens (dashboard, recapture, suspects, reports).
 *             Tokens: tokens.infoBlue, tokens.accentPurple, tokens.violetBg/Text
 *
 *   SLATE / MUTED = neutral UI chrome.
 *             Decorative pills, disabled states, secondary labels, dividers.
 *             Tokens: tokens.slate*, tokens.bgSubtle, tokens.bgFaintCard
 *
 * ── GRADIENT POLICY ─────────────────────────────────────────────────────────
 *   Login / marketing screens  → expressive gradients permitted.
 *   Operational screens (dashboard, recapture, suspects, reports, v28-impact)
 *     → flat or very-subtle tints only (rgba opacity <= 0.05).
 *     → No bold gradient cards; status bars → solid single-color fills.
 *
 * ── EXCEPTIONS ──────────────────────────────────────────────────────────────
 *   V28 Hero card amber border/bg             → intentional warning; keep.
 *   Reports section-header blue→purple text   → analytics context; keep.
 *   Reports tab active-indicator gradient     → analytics context; keep.
 *
 * ────────────────────────────────────────────────────────────────────────────
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

// ---------------------------------------------------------------------------
// Typography scale
// ---------------------------------------------------------------------------
/**
 * Font-size tokens sourced from CSS custom properties defined in globals.css.
 * Every value is a literal pixel string so it can be dropped directly into
 * `style={{ fontSize: typography.base }}` without further transformation.
 *
 * In Tailwind JSX prefer `text-sm`, `text-base`, etc. — use these only when
 * Tailwind utilities are unavailable (dynamic values, canvas, email templates).
 */
export const typography = {
  /** 11px — fine print, legal footnotes */
  xs:   "var(--text-xs)",
  /** 13px — secondary labels, table cell meta */
  sm:   "var(--text-sm)",
  /** 14px — default body copy */
  base: "var(--text-base)",
  /** 16px — section sub-headings, emphasized body */
  lg:   "var(--text-lg)",
  /** 20px — card titles, modal headings */
  xl:   "var(--text-xl)",
  /** 24px — page-level headings */
  "2xl": "var(--text-2xl)",
  /** 30px — hero metrics, KPI values */
  "3xl": "var(--text-3xl)",
} as const;

export type Typography = typeof typography;

// ---------------------------------------------------------------------------
// Spacing scale
// ---------------------------------------------------------------------------
/**
 * 4 px-base spacing tokens sourced from CSS custom properties in globals.css.
 * Keys are integers (1–10) so consumers can write `spacing[4]` → '16px'.
 *
 * Mapping:
 *   1 → 4px   2 → 8px   3 → 12px   4 → 16px   5 → 20px
 *   6 → 24px  7 → 28px  8 → 32px   9 → 36px   10 → 40px
 */
export const spacing: Record<1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10, string> = {
  1:  "var(--space-1)",
  2:  "var(--space-2)",
  3:  "var(--space-3)",
  4:  "var(--space-4)",
  5:  "var(--space-5)",
  6:  "var(--space-6)",
  7:  "var(--space-7)",
  8:  "var(--space-8)",
  9:  "var(--space-9)",
  10: "var(--space-10)",
} as const;

export type Spacing = typeof spacing;

// ---------------------------------------------------------------------------
// Sidebar layout tokens
// ---------------------------------------------------------------------------
/**
 * Semantic sidebar tokens.  Color values alias the Shadcn `--sidebar-*` CSS
 * variables and adapt automatically in dark mode.  Dimension tokens are
 * fixed pixel values shared by the sidebar component and any layout that
 * needs to know the sidebar width (e.g. main content left-margin calculation).
 */
export const sidebar = {
  /** Background surface — resolves to hsl(--sidebar) */
  bg:        "var(--sidebar-bg)",
  /** Primary text color — resolves to hsl(--sidebar-foreground) */
  text:      "var(--sidebar-text)",
  /** Hover item background — resolves to hsl(--sidebar-accent) */
  hover:     "var(--sidebar-hover)",
  /** Active / selected item highlight — resolves to hsl(--sidebar-primary) */
  active:    "var(--sidebar-active)",
  /** Accent tint (same as hover, kept for semantic clarity) */
  accent:    "var(--sidebar-accent)",
  /** Expanded sidebar width — 240px */
  width:     "var(--sidebar-width)",
  /** Collapsed (icon-only) sidebar width — 64px */
  collapsed: "var(--sidebar-collapsed)",
} as const;

export type Sidebar = typeof sidebar;

// ---------------------------------------------------------------------------
// Table layout tokens
// ---------------------------------------------------------------------------
/**
 * Structural tokens for data tables.  Use these to keep row heights,
 * header heights, and horizontal cell padding consistent across every
 * table in the application.
 *
 * @example
 * <tr style={{ height: table.rowHeight }}>
 * <th style={{ height: table.headerHeight, paddingLeft: table.padX }}>
 */
export const table = {
  /** Data row height — 56px */
  rowHeight:    "var(--table-row-height)",
  /** Header row height — 48px */
  headerHeight: "var(--table-header-height)",
  /** Horizontal cell padding — 24px */
  padX:         "var(--table-pad-x)",
} as const;

export type Table = typeof table;

// ---------------------------------------------------------------------------
// Unified design-token interface
// ---------------------------------------------------------------------------
/**
 * Aggregated type that covers every token group exported from this module.
 * Import individual groups for tree-shaking; import this type for prop typing.
 *
 * @example
 * import type { DesignTokens } from '@/styles/tokens';
 */
export interface DesignTokens {
  tokens:     Tokens;
  typography: Typography;
  spacing:    Spacing;
  sidebar:    Sidebar;
  table:      Table;
}
