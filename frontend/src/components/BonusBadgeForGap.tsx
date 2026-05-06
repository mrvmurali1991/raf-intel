"use client";

/**
 * BonusBadgeForGap — small inline pill rendered next to a gap row.
 *
 *   "Close now: +$25"
 *
 * The bonus is fetched lazily for each gap. Use ``initialMultiplier`` and
 * ``initialBaseBonus`` to pre-render an optimistic preview if you already
 * know the current month multiplier (e.g. read from ``BonusMultiplierBanner``
 * data) — this avoids a fetch storm when rendering long lists.
 */

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";

import { getGapBonusPreview, type BonusPreview } from "@/lib/api";

export interface BonusBadgeForGapProps {
  gapId: number;
  /** Pre-render an estimate before the API responds. */
  initialBaseBonus?: number;
  initialMultiplier?: number;
  /** Skip the fetch and just show the optimistic estimate. */
  optimisticOnly?: boolean;
  /** Compact = no icon / smaller padding. */
  compact?: boolean;
}

function formatBonus(n: number): string {
  // Show whole dollars when integer, else 2 decimals
  return Number.isInteger(n) ? `$${n}` : `$${n.toFixed(2)}`;
}

export function BonusBadgeForGap({
  gapId,
  initialBaseBonus,
  initialMultiplier,
  optimisticOnly = false,
  compact = false,
}: BonusBadgeForGapProps) {
  const optimisticBonus =
    initialBaseBonus !== undefined && initialMultiplier !== undefined
      ? Math.round(initialBaseBonus * initialMultiplier * 100) / 100
      : null;

  const { data } = useQuery<BonusPreview>({
    queryKey: ["gap-bonus-preview", gapId],
    queryFn: () => getGapBonusPreview(gapId),
    staleTime: 60_000,
    enabled: !optimisticOnly && Number.isFinite(gapId) && gapId > 0,
    retry: 0,
  });

  // Resolve the displayed value. Prefer the live API response.
  const bonus = data?.bonus ?? optimisticBonus;
  const eligible = data ? data.eligible : optimisticBonus !== null;

  if (bonus === null || bonus === undefined) return null;
  if (!eligible || bonus <= 0) {
    return (
      <span
        title={data?.reason || "No bonus available for this gap"}
        style={{
          display: "inline-flex",
          alignItems: "center",
          padding: compact ? "2px 8px" : "3px 10px",
          borderRadius: 999,
          background: "#F1F5F9",
          color: "#64748B",
          fontSize: compact ? 10 : 11,
          fontWeight: 600,
        }}
      >
        Closed
      </span>
    );
  }

  return (
    <span
      title={`Close now to earn ${formatBonus(bonus)} (month ${data?.month ?? "?"} multiplier ${data?.multiplier?.toFixed(2) ?? "?"}×)`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: compact ? "2px 8px" : "3px 10px",
        borderRadius: 999,
        background: "linear-gradient(135deg, #ECFDF5, #D1FAE5)",
        color: "#065F46",
        fontSize: compact ? 10 : 11,
        fontWeight: 700,
        border: "1px solid #6EE7B7",
        whiteSpace: "nowrap",
      }}
    >
      {!compact && <Sparkles size={11} aria-hidden />}
      Close now: +{formatBonus(bonus)}
    </span>
  );
}

export default BonusBadgeForGap;
