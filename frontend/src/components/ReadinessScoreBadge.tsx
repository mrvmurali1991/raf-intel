"use client";

/**
 * ReadinessScoreBadge — small color-coded pill rendering an IMO-style
 * recapture readiness score (0–100).
 *
 * Tier mapping (must mirror backend `_tier()` in recapture_readiness_service.py):
 *   >= 70  strong   (emerald)
 *   40–69  moderate (amber)
 *   < 40   weak     (red)
 *
 * Render forms:
 *   <ReadinessScoreBadge score={72} />            // pill: "72 · Strong"
 *   <ReadinessScoreBadge score={32} compact />    // pill: "32"
 *   <ReadinessScoreBadge score={undefined} />     // dash placeholder
 *
 * Click is supported via `onClick` (used by the gap row to open the
 * ReadinessDetailModal); when provided, the badge becomes a button.
 */

import React from "react";

export type ReadinessTier = "strong" | "moderate" | "weak";

export function tierFromScore(score: number): ReadinessTier {
  if (score >= 70) return "strong";
  if (score >= 40) return "moderate";
  return "weak";
}

interface TierStyle {
  fg: string;
  bg: string;
  border: string;
  label: string;
}

const TIER_STYLES: Record<ReadinessTier, TierStyle> = {
  strong:   { fg: "#047857", bg: "#D1FAE5", border: "#10B981", label: "Strong"   },
  moderate: { fg: "#B45309", bg: "#FEF3C7", border: "#F59E0B", label: "Moderate" },
  weak:     { fg: "#B91C1C", bg: "#FEE2E2", border: "#EF4444", label: "Weak"     },
};

export interface ReadinessScoreBadgeProps {
  score: number | null | undefined;
  tier?: ReadinessTier;
  compact?: boolean;
  onClick?: (e: React.MouseEvent<HTMLElement>) => void;
  title?: string;
  /** Optional className appended to the root style element. */
  className?: string;
}

export function ReadinessScoreBadge({
  score,
  tier,
  compact = false,
  onClick,
  title,
  className,
}: ReadinessScoreBadgeProps) {
  if (score === null || score === undefined || Number.isNaN(score)) {
    return (
      <span
        className={className}
        style={{
          display: "inline-flex",
          alignItems: "center",
          padding: "2px 8px",
          fontSize: 11,
          fontWeight: 600,
          color: "#64748B",
          background: "#F1F5F9",
          borderRadius: 999,
          border: "1px solid #E2E8F0",
        }}
        title={title ?? "Readiness not yet computed"}
      >
        —
      </span>
    );
  }

  const clamped = Math.max(0, Math.min(100, Math.round(score)));
  const t = tier ?? tierFromScore(clamped);
  const s = TIER_STYLES[t];

  const baseStyle: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: compact ? "2px 8px" : "3px 10px",
    fontSize: 11,
    fontWeight: 700,
    color: s.fg,
    background: s.bg,
    borderRadius: 999,
    border: `1px solid ${s.border}`,
    fontFamily:
      'ui-monospace, SFMono-Regular, Menlo, Monaco, "Cascadia Mono", monospace',
    lineHeight: 1.4,
    cursor: onClick ? "pointer" : "default",
    userSelect: "none",
    transition: "transform 0.12s ease, box-shadow 0.12s ease",
  };

  const content = (
    <>
      <span aria-hidden style={{
        width: 6,
        height: 6,
        borderRadius: 999,
        background: s.border,
        flexShrink: 0,
      }} />
      <span className="tabular-nums">{clamped}</span>
      {!compact && (
        <span style={{ fontWeight: 600, opacity: 0.85 }}>{s.label}</span>
      )}
    </>
  );

  const ariaLabel = title ?? `Recapture readiness score ${clamped} of 100, ${s.label}`;

  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={className}
        style={baseStyle}
        title={ariaLabel}
        aria-label={ariaLabel}
      >
        {content}
      </button>
    );
  }

  return (
    <span
      className={className}
      style={baseStyle}
      title={ariaLabel}
      aria-label={ariaLabel}
    >
      {content}
    </span>
  );
}

export default ReadinessScoreBadge;
