"use client";

/**
 * RecurringGapAlert
 *
 * Compact red banner displayed at the top of a recapture-gap row when the
 * gap has been open for 2+ consecutive years.  Communicates that the gap is
 * SYSTEMIC — provider isn't capturing it, patient isn't getting visits.
 */

import { AlertTriangle } from "lucide-react";

interface RecurringGapAlertProps {
  yearsRecurring: number;
  className?: string;
  /** When true, render in a more compact horizontal layout. */
  compact?: boolean;
}

export function RecurringGapAlert({
  yearsRecurring,
  className,
  compact = false,
}: RecurringGapAlertProps) {
  const message = yearsRecurring >= 3
    ? `This gap has been open ${yearsRecurring} years — likely systemic`
    : `Recurring gap (open ${yearsRecurring} consecutive years)`;

  return (
    <div
      role="alert"
      aria-live="polite"
      className={className}
      style={{
        display: "flex",
        alignItems: "center",
        gap: compact ? 6 : 10,
        padding: compact ? "6px 10px" : "10px 14px",
        borderRadius: 8,
        background: "#FEF2F2",
        border: "1px solid #FECACA",
        color: "#B91C1C",
        fontSize: compact ? 12 : 13,
        fontWeight: 600,
        lineHeight: 1.4,
      }}
    >
      <AlertTriangle size={compact ? 14 : 16} aria-hidden />
      <span>{message}</span>
      <span
        style={{
          marginLeft: "auto",
          padding: "2px 8px",
          borderRadius: 999,
          background: "#FEE2E2",
          color: "#991B1B",
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: "0.04em",
          textTransform: "uppercase",
        }}
      >
        {yearsRecurring}-yr
      </span>
    </div>
  );
}

export default RecurringGapAlert;
