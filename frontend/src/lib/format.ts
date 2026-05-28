/**
 * Canonical formatting utilities for the RAF Intelligence frontend.
 *
 * Rules:
 *  - NEVER use raw `toLocaleString()` for currency — use these helpers.
 *  - All functions are pure (no side effects) and handle null/undefined/NaN.
 *  - Intl.NumberFormat / Intl.DateTimeFormat are the single source of truth.
 *  - Missing or invalid input returns the em-dash sentinel "—" (or 0 for daysUntil).
 */

// ─────────────────────────────────────────────
// Internal helpers
// ─────────────────────────────────────────────

const SENTINEL = "—";

function toDate(value: string | Date): Date {
  return value instanceof Date ? value : new Date(value);
}

function isValidDate(d: Date): boolean {
  return !isNaN(d.getTime());
}

// ─────────────────────────────────────────────
// CURRENCY
// ─────────────────────────────────────────────

/**
 * Format a dollar value with full control over compact/sign/decimals.
 *
 * @example
 * formatCurrency(3200)                         // "$3,200"
 * formatCurrency(3200,  { compact: true })     // "$3.2K"
 * formatCurrency(850)                          // "$850"
 * formatCurrency(1_300_000, { compact: true }) // "$1.3M"
 * formatCurrency(-3200)                        // "-$3,200"
 * formatCurrency(3200, { showSign: true })     // "+$3,200"
 * formatCurrency(NaN)                          // "—"
 */
export function formatCurrency(
  value: number,
  options?: {
    /** Use compact notation: $3.2K / $1.3M. Default false. */
    compact?: boolean;
    /** Prefix positive values with "+". Default false. */
    showSign?: boolean;
    /** Decimal places. Defaults: 0 for full, 1 for compact K/M. */
    decimals?: number;
  }
): string {
  if (value == null || !Number.isFinite(value)) return SENTINEL;

  const { compact = false, showSign = false, decimals } = options ?? {};

  let formatted: string;

  if (compact) {
    const absVal = Math.abs(value);
    // Determine default fraction digits: 0 for small compacts, 1 for K+
    const defaultDecimals = absVal < 1_000 ? 0 : 1;
    const fractionDigits = decimals ?? defaultDecimals;

    formatted = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      notation: "compact",
      compactDisplay: "short",
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    }).format(value);
  } else {
    const fractionDigits = decimals ?? 0;
    formatted = new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    }).format(value);
  }

  if (showSign && value > 0) {
    formatted = `+${formatted}`;
  }

  return formatted;
}

/**
 * Compact display for large values (>= $10K → "$12K", >= $1M → "$1.2M").
 * Preserved for backward compatibility — prefer formatCurrency({ compact: true }).
 *
 * @example
 * fmtCurrencyCompact(12000)   // "$12K"
 * fmtCurrencyCompact(1200000) // "$1.2M"
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
 * Preserved for backward compatibility — prefer formatCurrency().
 *
 * @example
 * fmtCurrencyFull(1234567) // "$1,234,567"
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
 * Preserved for backward compatibility — prefer formatCurrency().
 *
 * @example
 * fmtCurrencySmart(3200)   // "$3,200"
 * fmtCurrencySmart(15000)  // "$15K"
 */
export function fmtCurrencySmart(n: number): string {
  if (!Number.isFinite(n)) return "$0";
  if (Math.abs(n) >= 10_000) return fmtCurrencyCompact(n);
  return fmtCurrencyFull(n);
}

// ─────────────────────────────────────────────
// NUMBERS
// ─────────────────────────────────────────────

/**
 * Format a plain number with optional compact notation and decimal places.
 *
 * @example
 * formatNumber(1200)                        // "1,200"
 * formatNumber(1200, { compact: true })     // "1.2K"
 * formatNumber(1200, { decimals: 2 })       // "1,200.00"
 * formatNumber(NaN)                         // "—"
 */
export function formatNumber(
  value: number,
  options?: {
    /** Use compact notation: 1.2K / 1.3M. Default false. */
    compact?: boolean;
    /** Decimal places. Default 0. */
    decimals?: number;
  }
): string {
  if (value == null || !Number.isFinite(value)) return SENTINEL;

  const { compact = false, decimals = 0 } = options ?? {};

  if (compact) {
    return new Intl.NumberFormat("en-US", {
      notation: "compact",
      compactDisplay: "short",
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(value);
  }

  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

/**
 * Format a plain number with fixed decimal places.
 * Preserved for backward compatibility — prefer formatNumber().
 *
 * @example
 * fmtN(1.5678, 2) // "1.57"
 */
export function fmtN(v: number | null | undefined, d = 2): string {
  if (v == null) return "--";
  return Number(v).toFixed(d);
}

/**
 * Format a percentage value.
 * Accepts a 0–100 value (NOT a 0–1 decimal) unless you use fmtPct.
 *
 * @example
 * formatPercent(85.3)                        // "85.3%"
 * formatPercent(85.3, { decimals: 0 })       // "85%"
 * formatPercent(12.5, { showSign: true })    // "+12.5%"
 * formatPercent(-4.2, { showSign: true })    // "-4.2%"
 * formatPercent(NaN)                         // "—"
 */
export function formatPercent(
  value: number,
  options?: {
    /** Decimal places. Default 1. */
    decimals?: number;
    /** Prefix positive values with "+". Default false. */
    showSign?: boolean;
  }
): string {
  if (value == null || !Number.isFinite(value)) return SENTINEL;

  const { decimals = 1, showSign = false } = options ?? {};
  const formatted = `${value.toFixed(decimals)}%`;

  if (showSign && value > 0) return `+${formatted}`;
  return formatted;
}

/**
 * Format a percentage from a 0–1 decimal (e.g. 0.85 → "85%").
 * Preserved for backward compatibility — prefer formatPercent() with a 0-100 value.
 *
 * @example
 * fmtPct(0.853)     // "85%"
 * fmtPct(0.853, 1)  // "85.3%"
 */
export function fmtPct(v: number | null | undefined, decimals = 0): string {
  if (v == null) return "--";
  return `${(v * 100).toFixed(decimals)}%`;
}

/**
 * Format a RAF score — always 3 decimal places.
 *
 * @example
 * formatRafScore(1.2345)  // "1.234"
 * formatRafScore(0.8)     // "0.800"
 * formatRafScore(NaN)     // "—"
 */
export function formatRafScore(score: number): string {
  if (score == null || !Number.isFinite(score)) return SENTINEL;
  return score.toFixed(3);
}

// ─────────────────────────────────────────────
// DATES
// ─────────────────────────────────────────────

/**
 * Format a date to one of three display styles.
 *
 * @example
 * formatDate("2026-03-15", "short")   // "03/15/26"
 * formatDate("2026-03-15")            // "Mar 15, 2026"  (default: medium)
 * formatDate("2026-03-15", "long")    // "March 15, 2026"
 * formatDate("invalid")               // "—"
 */
export function formatDate(
  date: string | Date,
  style: "short" | "medium" | "long" = "medium"
): string {
  if (date == null) return SENTINEL;
  const d = toDate(date);
  if (!isValidDate(d)) return SENTINEL;

  if (style === "short") {
    // MM/DD/YY
    return new Intl.DateTimeFormat("en-US", {
      month: "2-digit",
      day: "2-digit",
      year: "2-digit",
      timeZone: "UTC",
    }).format(d);
  }

  if (style === "long") {
    return new Intl.DateTimeFormat("en-US", {
      month: "long",
      day: "numeric",
      year: "numeric",
      timeZone: "UTC",
    }).format(d);
  }

  // medium (default)
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(d);
}

/**
 * Format a date relative to today in human-friendly terms.
 *
 * @example
 * formatRelativeDate(today)              // "Today"
 * formatRelativeDate(yesterday)          // "Yesterday"
 * formatRelativeDate(3 days ago)         // "3 days ago"
 * formatRelativeDate(10 days ago)        // "2 weeks ago"
 * formatRelativeDate(older date)         // "Mar 15"  (month + day, no year)
 * formatRelativeDate("invalid")          // "—"
 */
export function formatRelativeDate(date: string | Date): string {
  if (date == null) return SENTINEL;
  const d = toDate(date);
  if (!isValidDate(d)) return SENTINEL;

  const now = new Date();
  // Compare calendar days in local time
  const todayMidnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const targetMidnight = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diffMs = todayMidnight.getTime() - targetMidnight.getTime();
  const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays > 0 && diffDays < 7) return `${diffDays} days ago`;
  if (diffDays >= 7 && diffDays < 14) return "1 week ago";
  if (diffDays >= 14 && diffDays < 21) return "2 weeks ago";
  if (diffDays >= 21 && diffDays < 28) return "3 weeks ago";
  if (diffDays >= 28 && diffDays < 60) return "1 month ago";

  // Older than ~2 months: show "Mar 15"
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
  }).format(d);
}

/**
 * Return the number of whole calendar days between today and a target date.
 * Positive = future, negative = past, 0 = today.
 *
 * @example
 * daysUntil(tomorrow)     // 1
 * daysUntil(yesterday)    // -1
 * daysUntil(today)        // 0
 * daysUntil("invalid")    // 0
 */
export function daysUntil(date: string | Date): number {
  if (date == null) return 0;
  const d = toDate(date);
  if (!isValidDate(d)) return 0;

  const now = new Date();
  const todayMidnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const targetMidnight = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const diffMs = targetMidnight.getTime() - todayMidnight.getTime();
  return Math.round(diffMs / (1000 * 60 * 60 * 24));
}

/**
 * Describe a date offset from today in natural language.
 *
 * @example
 * daysFromNow(0)    // "today"
 * daysFromNow(1)    // "tomorrow"
 * daysFromNow(-1)   // "yesterday"
 * daysFromNow(3)    // "in 3 days"
 * daysFromNow(-3)   // "3 days ago"
 * daysFromNow(14)   // "in 2 weeks"
 * daysFromNow(60)   // "in 2 months"
 * daysFromNow(-90)  // "3 months ago"
 */
export function daysFromNow(days: number): string {
  if (days == null || !Number.isFinite(days)) return SENTINEL;

  const abs = Math.abs(days);
  const future = days > 0;

  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days === -1) return "yesterday";

  if (abs < 7) return future ? `in ${abs} days` : `${abs} days ago`;

  const weeks = Math.round(abs / 7);
  if (abs < 30) return future ? `in ${weeks} week${weeks > 1 ? "s" : ""}` : `${weeks} week${weeks > 1 ? "s" : ""} ago`;

  const months = Math.round(abs / 30);
  return future
    ? `in ${months} month${months > 1 ? "s" : ""}`
    : `${months} month${months > 1 ? "s" : ""} ago`;
}

// ─────────────────────────────────────────────
// PATIENT
// ─────────────────────────────────────────────

/**
 * Format a patient name in clinical "Last, First" format.
 *
 * @example
 * formatPatientName("John", "Smith")   // "Smith, John"
 * formatPatientName(undefined, "Smith") // "Smith"
 * formatPatientName("John", undefined)  // "John"
 * formatPatientName()                   // "—"
 */
export function formatPatientName(first?: string, last?: string): string {
  const f = first?.trim();
  const l = last?.trim();

  if (!f && !l) return SENTINEL;
  if (!f) return l!;
  if (!l) return f;
  return `${l}, ${f}`;
}

/**
 * Calculate a patient's age in whole years from their date of birth.
 * Returns null for invalid/missing DOB.
 *
 * @example
 * formatAge("1980-06-15")  // 45  (depends on today)
 * formatAge("invalid")     // null
 */
export function formatAge(dob: string | Date): number | null {
  if (dob == null) return null;
  const birth = toDate(dob);
  if (!isValidDate(birth)) return null;

  const today = new Date();
  let age = today.getFullYear() - birth.getFullYear();
  const monthDiff = today.getMonth() - birth.getMonth();
  if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < birth.getDate())) {
    age--;
  }
  return age;
}

/**
 * Display a Medical Record Number with consistent zero-padding to 8 digits.
 * Non-numeric characters are preserved as-is (some EHRs use alphanumeric MRNs).
 *
 * @example
 * formatMRN("12345")        // "00012345"
 * formatMRN("00012345")     // "00012345"
 * formatMRN("ABC-123")      // "ABC-123"  (non-numeric: returned as-is)
 * formatMRN("")             // "—"
 */
export function formatMRN(mrn: string): string {
  if (mrn == null || mrn.trim() === "") return SENTINEL;
  const trimmed = mrn.trim();
  // Only zero-pad if the entire string is numeric
  if (/^\d+$/.test(trimmed)) {
    return trimmed.padStart(8, "0");
  }
  return trimmed;
}

// ─────────────────────────────────────────────
// HCC
// ─────────────────────────────────────────────

/**
 * Format an HCC code with the standard "HCC " prefix and no leading zeros on the number.
 *
 * @example
 * formatHccCode(18)      // "HCC 18"
 * formatHccCode("018")   // "HCC 18"
 * formatHccCode("HCC18") // "HCC 18"
 * formatHccCode("hcc 018") // "HCC 18"
 * formatHccCode("")      // "—"
 */
export function formatHccCode(code: string | number): string {
  if (code == null || code === "") return SENTINEL;

  // Strip any existing "HCC" prefix (case-insensitive) and whitespace
  const raw = String(code).replace(/^\s*hcc\s*/i, "").trim();
  if (raw === "") return SENTINEL;

  const num = parseInt(raw, 10);
  if (isNaN(num)) return SENTINEL;

  return `HCC ${num}`;
}

/**
 * Normalize an ICD-10 code to uppercase with a dot after the first 3 characters.
 *
 * @example
 * formatIcd10("e119")   // "E11.9"
 * formatIcd10("E11.9")  // "E11.9"
 * formatIcd10("I5033")  // "I50.33"
 * formatIcd10("")       // "—"
 */
export function formatIcd10(code: string): string {
  if (code == null || code.trim() === "") return SENTINEL;

  // Remove existing dot, uppercase, strip spaces
  const clean = code.replace(/\./g, "").toUpperCase().trim();

  if (clean.length < 3) return clean;

  // Insert dot after position 3
  return `${clean.slice(0, 3)}.${clean.slice(3)}`;
}
