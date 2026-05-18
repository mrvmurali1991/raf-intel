"use client";

/**
 * WorkflowHandoffBanner
 *
 * Contextual CTA banner shown at the top of each HCC workflow page.
 * When count > 0 renders a green "ready" variant.
 * When count === 0 AND showWhenZero renders a muted grey "neutral" variant
 * pointing back to the previous stage so the user knows what to do next.
 *
 * Usage (non-zero):
 *   <WorkflowHandoffBanner
 *     count={acceptedCount}
 *     message="{count} suspects ready for attestation"
 *     ctaLabel="Send to Attestations"
 *     ctaHref="/attestations"
 *   />
 *
 * Usage (zero-state with back-link):
 *   <WorkflowHandoffBanner
 *     count={acceptedCount}
 *     message="{count} suspects ready for attestation"
 *     ctaLabel="Send to Attestations"
 *     ctaHref="/attestations"
 *     showWhenZero
 *     zeroMessage="No suspects accepted yet — accept suspects to proceed"
 *     zeroCtaLabel="Go to Suspects"
 *     zeroCtaHref="/suspects"
 *   />
 */

import React from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, ArrowLeft, Info } from "lucide-react";

interface Props {
  count: number;
  message: string; // use "{count}" as placeholder
  ctaLabel: string;
  ctaHref: string;
  /** @deprecated use showWhenZero instead */
  hideWhenZero?: boolean;
  /** Render a neutral guidance card when count === 0. Defaults to true. */
  showWhenZero?: boolean;
  /** Copy shown in the zero-state card. */
  zeroMessage?: string;
  /** Label for the zero-state back-link CTA. */
  zeroCtaLabel?: string;
  /** Href for the zero-state back-link CTA. */
  zeroCtaHref?: string;
}

export default function WorkflowHandoffBanner({
  count,
  message,
  ctaLabel,
  ctaHref,
  hideWhenZero,
  showWhenZero = true,
  zeroMessage = "No items ready yet — complete the previous step to proceed.",
  zeroCtaLabel,
  zeroCtaHref,
}: Props) {
  const router = useRouter();

  // Honour legacy hideWhenZero prop: explicit true overrides showWhenZero
  const effectiveShowWhenZero =
    hideWhenZero === true ? false : showWhenZero;

  if (count === 0 && !effectiveShowWhenZero) return null;

  // ── Zero-state (neutral / muted) variant ─────────────────────────────────
  if (count === 0) {
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
          background: "#F9FAFB",
          border: "1px solid #D1D5DB",
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
            fontWeight: 500,
            color: "#6B7280",
          }}
        >
          <Info size={16} aria-hidden style={{ flexShrink: 0, color: "#9CA3AF" }} />
          {zeroMessage}
        </div>
        {zeroCtaLabel && zeroCtaHref && (
          <button
            onClick={() => router.push(zeroCtaHref)}
            aria-label={zeroCtaLabel}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "7px 16px",
              borderRadius: 8,
              border: "1px solid #D1D5DB",
              background: "#FFFFFF",
              color: "#374151",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
              whiteSpace: "nowrap",
              transition: "background 0.15s",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "#F3F4F6";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "#FFFFFF";
            }}
          >
            <ArrowLeft size={14} aria-hidden />
            {zeroCtaLabel}
          </button>
        )}
      </div>
    );
  }

  // ── Normal (green / ready) variant ───────────────────────────────────────
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
