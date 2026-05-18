"use client";

/**
 * HistoricalPYBanner
 *
 * Renders an amber read-only warning strip when the globally-selected payment
 * year is earlier than the current calendar year.  Renders nothing for current
 * or future years so callers can mount it unconditionally.
 *
 * Usage:
 *   import { HistoricalPYBanner } from "@/components/HistoricalPYBanner";
 *   <HistoricalPYBanner paymentYear={year} />
 *   // or without prop — hook reads from context automatically:
 *   <HistoricalPYBanner />
 */

import { Lock } from "lucide-react";
import { usePaymentYear } from "@/contexts/payment-year-context";
import { tokens } from "@/styles/tokens";

interface Props {
  /** Override the year to check.  Defaults to the context value. */
  paymentYear?: number;
  /** Extra bottom margin (default 24 px). */
  marginBottom?: number;
}

export function HistoricalPYBanner({ paymentYear: pyProp, marginBottom = 24 }: Props) {
  const { paymentYear: ctxYear } = usePaymentYear();
  const year = pyProp ?? ctxYear;
  const currentYear = new Date().getFullYear();

  if (year >= currentYear) return null;

  return (
    <div
      data-testid="historical-view-badge"
      role="status"
      aria-live="polite"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "12px 18px",
        marginBottom,
        borderRadius: 10,
        background: tokens.warningSoft,
        border: `1px solid ${tokens.warningBorder}`,
        color: tokens.warningText,
        fontSize: 14,
        fontWeight: 600,
      }}
    >
      <Lock size={16} style={{ flexShrink: 0, color: tokens.amber600 }} aria-hidden="true" />
      Historical view — PY{year}. Data is read-only.
    </div>
  );
}

export default HistoricalPYBanner;
