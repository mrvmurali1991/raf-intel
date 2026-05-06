/**
 * Canonical currency and number formatting utilities.
 *
 * Rule: NEVER use raw `${n.toLocaleString()}` for currency — use these helpers.
 * Intl.NumberFormat is the single source of truth for all $ formatting.
 */

/**
 * Compact display for large values (>= $10K → "$12K", >= $1M → "$1.2M").
 * CFO dashboards, KPI tiles, stat cards.
 */
export function fmtCurrencyCompact(n: number): string {
  if (!Number.isFinite(n)) return "$0";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: "compact",
    compactDisplay: "short",
    maximumFractionDigits: 1,
  }).format(n);
}

/**
 * Full USD format with comma separators — for line-item detail views.
 * e.g. $1,234,567
 */
export function fmtCurrencyFull(n: number): string {
  if (!Number.isFinite(n)) return "$0";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(n);
}

/**
 * Smart currency: compact for values >= $10K, full for smaller amounts.
 * Use this on financial pages when you don't know the magnitude.
 */
export function fmtCurrencySmart(n: number): string {
  if (!Number.isFinite(n)) return "$0";
  if (Math.abs(n) >= 10_000) return fmtCurrencyCompact(n);
  return fmtCurrencyFull(n);
}

/**
 * Format a percentage from a 0-1 decimal (e.g. 0.85 → "85%").
 */
export function fmtPct(v: number | null | undefined, decimals = 0): string {
  if (v == null) return "--";
  return `${(v * 100).toFixed(decimals)}%`;
}

/**
 * Format a plain number with fixed decimal places.
 */
export function fmtN(v: number | null | undefined, d = 2): string {
  if (v == null) return "--";
  return Number(v).toFixed(d);
}
