"use client";

/**
 * WorkflowHandoffBanner
 *
 * Contextual CTA banner shown at the top of each HCC workflow page when
 * there are items ready to move to the next stage.
 *
 * Usage:
 *   <WorkflowHandoffBanner
 *     count={acceptedCount}
 *     message="{count} suspects ready for attestation"
 *     ctaLabel="Send to Attestations"
 *     ctaHref="/attestations"
 *   />
 */

import React from "react";
import { useRouter } from "next/navigation";
import { ArrowRight } from "lucide-react";

interface Props {
  count: number;
  message: string;  // use "{count}" as placeholder for the number
  ctaLabel: string;
  ctaHref: string;
  /** Hide the banner when count is 0. Defaults to true. */
  hideWhenZero?: boolean;
}

export default function WorkflowHandoffBanner({
  count,
  message,
  ctaLabel,
  ctaHref,
  hideWhenZero = true,
}: Props) {
  const router = useRouter();

  if (hideWhenZero && count === 0) return null;

  const displayMessage = message.replaceAll("{count}", String(count));

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: 12,
        background: "linear-gradient(135deg, #F0FDF4 0%, #ECFDF5 100%)",
        border: "1px solid #6EE7B7",
        borderRadius: 10,
        padding: "12px 16px",
        marginBottom: 16,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          fontSize: 13,
          fontWeight: 600,
          color: "#065F46",
        }}
      >
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: 24,
            height: 24,
            borderRadius: "50%",
            background: "#059669",
            color: "#fff",
            fontSize: 11,
            fontWeight: 700,
            flexShrink: 0,
          }}
          aria-hidden
        >
          {count > 99 ? "99+" : count}
        </span>
        {displayMessage}
      </div>
      <button
        onClick={() => router.push(ctaHref)}
        aria-label={`${ctaLabel} — ${displayMessage}`}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          padding: "7px 16px",
          borderRadius: 8,
          border: "none",
          background: "#059669",
          color: "#FFFFFF",
          fontSize: 13,
          fontWeight: 600,
          cursor: "pointer",
          whiteSpace: "nowrap",
          boxShadow: "0 1px 3px rgba(5, 150, 105, 0.3)",
          transition: "background 0.15s",
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = "#047857";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = "#059669";
        }}
      >
        {ctaLabel}
        <ArrowRight size={14} aria-hidden />
      </button>
    </div>
  );
}
