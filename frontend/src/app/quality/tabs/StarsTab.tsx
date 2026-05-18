"use client";

import React from "react";
import { TrendingUp, TrendingDown, Star } from "lucide-react";
import { tokens } from "@/styles/tokens";
import { SectionHeader } from "@/components/healthcare-ui";
import type { StarsEstimate } from "@/lib/api";
import { C, T, starsColor, StarsGauge, renderStars } from "./_shared";

export default function StarsTab({ stars }: { stars: StarsEstimate }) {
  const diff = stars.projected_estimate - stars.current_estimate;
  const diffUp = diff >= 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div className="qs-stars-top" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        {/* Current */}
        <div
          className="premium-shadow mesh-pattern qs-fade-in qs-fade-in-1"
          style={{
            ...T.card,
            display: "flex", flexDirection: "column", alignItems: "center",
            background: `linear-gradient(135deg, ${tokens.slate900} 0%, ${tokens.slate800} 50%, ${tokens.slate900} 100%)`,
            border: "1px solid rgba(255,255,255,0.06)", borderRadius: 14,
          }}
        >
          <div style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: tokens.slate400, marginBottom: 16 }}>
            Current STARS Estimate — {stars.year}
          </div>
          <StarsGauge rating={stars.current_estimate} />
          <div style={{ marginTop: 10, fontSize: 13, color: tokens.slate500 }}>
            {renderStars(stars.current_estimate)}
          </div>
        </div>

        {/* Projected */}
        <div
          className="premium-shadow mesh-pattern qs-fade-in qs-fade-in-2"
          style={{
            ...T.card,
            display: "flex", flexDirection: "column", alignItems: "center",
            background: `linear-gradient(135deg, ${tokens.primaryDark} 0%, ${tokens.primary} 50%, ${tokens.primaryDark} 100%)`,
            border: "1px solid rgba(255,255,255,0.08)", borderRadius: 14,
          }}
        >
          <div style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: tokens.slate200, marginBottom: 16 }}>
            Projected STARS Estimate
          </div>
          <StarsGauge rating={stars.projected_estimate} />
          <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: tokens.slate200 }}>
            {diffUp ? <TrendingUp size={16} color={tokens.success} /> : <TrendingDown size={16} color={tokens.riskHigh} />}
            <span style={{ color: diffUp ? tokens.success : tokens.riskHigh, fontWeight: 700 }}>
              {diffUp ? "+" : ""}{(diff ?? 0).toFixed(2)} projected change
            </span>
          </div>
        </div>
      </div>

      {stars.measure_breakdown.length > 0 && (
        <div className="premium-card premium-shadow hover-lift qs-fade-in qs-fade-in-3" style={{ ...T.card, borderRadius: 14 }}>
          <SectionHeader title="Measure Breakdown" icon={<Star size={18} />} />
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 8 }}>
            {stars.measure_breakdown.map((mb) => {
              const barColor = starsColor(mb.stars);
              return (
                <div key={mb.measure_id} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <div style={{ width: 90, fontSize: 12, fontWeight: 700, color: C.primary, fontFamily: "monospace", flexShrink: 0 }}>
                    {mb.measure_id}
                  </div>
                  <div style={{ flex: 1, height: 8, borderRadius: 4, background: C.borderLight, overflow: "hidden", boxShadow: "inset 0 1px 2px rgba(0,0,0,0.06)" }}>
                    <div
                      className="qs-progress-bar"
                      style={{
                        height: "100%", width: `${(mb.stars / 5) * 100}%`,
                        background: `linear-gradient(90deg, ${barColor}CC, ${barColor})`,
                        borderRadius: 4, boxShadow: `0 1px 4px ${barColor}40`,
                        transition: "width 0.6s cubic-bezier(0.22,1,0.36,1)",
                      }}
                    />
                  </div>
                  <div style={{ minWidth: 36, textAlign: "right", fontSize: 13, fontWeight: 700, color: barColor }}>
                    {(mb.stars ?? 0).toFixed(1)}
                  </div>
                  <div style={{ minWidth: 48, textAlign: "right", fontSize: 11, color: C.textSub }}>
                    wt {(mb.weight ?? 0).toFixed(2)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
