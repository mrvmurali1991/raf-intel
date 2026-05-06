"use client";

/**
 * BonusMultiplierBanner — top-of-page urgency banner for the recapture page.
 *
 *   "🔥 May closures earn 1.0× bonus — drops to 0.9× in 25 days"
 *
 * Reads ``current_month_multiplier`` from the bonus config endpoint. The
 * component degrades silently (renders nothing) on fetch failure so a
 * backend hiccup never blocks the recapture page.
 */

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Flame, TrendingDown, TrendingUp, ArrowRight } from "lucide-react";

import {
  getRecaptureBonusConfig,
  type RecaptureBonusConfig,
} from "@/lib/api";

const MONTH_NAMES = [
  "", "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

export interface BonusMultiplierBannerProps {
  /** Hide entirely while the API call is in flight. Defaults to true. */
  hideWhileLoading?: boolean;
}

export function BonusMultiplierBanner({
  hideWhileLoading = true,
}: BonusMultiplierBannerProps) {
  const { data, isLoading, isError } = useQuery<RecaptureBonusConfig>({
    queryKey: ["recapture-bonus-config"],
    queryFn: getRecaptureBonusConfig,
    staleTime: 60_000,
    retry: 1,
  });

  if (isLoading && hideWhileLoading) return null;
  if (isError || !data) return null;

  const cm = data.current_month_multiplier;
  const monthLabel = MONTH_NAMES[cm.month] || `Month ${cm.month}`;
  const nextLabel = MONTH_NAMES[cm.next_month] || `Month ${cm.next_month}`;
  const directionDown = cm.delta < 0;
  const directionUp = cm.delta > 0;
  const sameMultiplier = Math.abs(cm.delta) < 0.01;

  // Pick a colour treatment that matches the urgency:
  //  - down (most common after January): orange/red urgency tint
  //  - up   (year wrap): green/blue celebration tint
  //  - same: neutral slate
  const tint = directionDown
    ? { bg: "linear-gradient(135deg, #FFF7ED, #FFEDD5)", border: "#FDBA74", icon: "#EA580C", text: "#9A3412" }
    : directionUp
    ? { bg: "linear-gradient(135deg, #ECFDF5, #D1FAE5)", border: "#6EE7B7", icon: "#059669", text: "#065F46" }
    : { bg: "linear-gradient(135deg, #F8FAFC, #F1F5F9)", border: "#CBD5E1", icon: "#475569", text: "#334155" };

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "12px 18px",
        borderRadius: 12,
        background: tint.bg,
        border: `1px solid ${tint.border}`,
        color: tint.text,
        marginBottom: 16,
      }}
    >
      <div
        style={{
          flexShrink: 0,
          width: 36,
          height: 36,
          borderRadius: 10,
          background: "rgba(255,255,255,0.6)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: tint.icon,
        }}
      >
        <Flame size={20} aria-hidden />
      </div>
      <div style={{ flex: 1, lineHeight: 1.4 }}>
        <div style={{ fontSize: 14, fontWeight: 700 }}>
          {monthLabel} closures earn{" "}
          <span className="tabular-nums">{cm.multiplier.toFixed(2)}×</span> bonus
          {sameMultiplier ? (
            <> — same rate continues into {nextLabel}.</>
          ) : (
            <>
              {" "}
              {directionDown ? "drops" : "jumps"} to{" "}
              <span className="tabular-nums" style={{ color: tint.icon }}>
                {cm.next_multiplier.toFixed(2)}×
              </span>{" "}
              in {cm.days_until_next_month} day
              {cm.days_until_next_month === 1 ? "" : "s"}.
            </>
          )}
        </div>
        <div style={{ fontSize: 12, opacity: 0.85, marginTop: 2 }}>
          Close gaps now to maximise your incentive payout for {monthLabel}.
        </div>
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: 13,
          fontWeight: 600,
          color: tint.icon,
          flexShrink: 0,
        }}
      >
        <span className="tabular-nums">{cm.multiplier.toFixed(2)}×</span>
        <ArrowRight size={14} aria-hidden />
        <span className="tabular-nums">{cm.next_multiplier.toFixed(2)}×</span>
        {directionDown && <TrendingDown size={14} aria-hidden />}
        {directionUp && <TrendingUp size={14} aria-hidden />}
      </div>
    </div>
  );
}

export default BonusMultiplierBanner;
