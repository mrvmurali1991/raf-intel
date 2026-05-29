"use client";

import Link from "next/link";
import { TrendingUp, ArrowUpRight } from "lucide-react";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from "@/components/ui/tooltip";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface V28Summary {
  total_revenue_delta: number;
  computed_patient_count: number;
  top_eroded_patients: Array<{ revenue: number }>;
}

export interface V28HeroCardProps {
  v28Summary: V28Summary | undefined;
  isLoading: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function V28HeroCard({ v28Summary, isLoading }: V28HeroCardProps) {
  if (!v28Summary && !isLoading) return null;

  return (
    <TooltipProvider delay={200}>
    <div
      data-testid="v28-hero-card"
      className="fade-in-up fade-in-up-1"
      style={{
        background: "hsl(var(--card))",
        border: "1px solid hsl(var(--border))",
        borderRadius: 12,
        padding: 20,
        marginBottom: 20,
        display: "flex",
        alignItems: "center",
        gap: 24,
        flexWrap: "wrap",
        boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
      }}
    >
      {/* Icon badge */}
      <div
        style={{
          background: "rgba(245,158,11,0.15)",
          border: "1px solid rgba(245,158,11,0.35)",
          borderRadius: 10,
          padding: "10px 12px",
          flexShrink: 0,
          display: "flex",
          alignItems: "center",
        }}
      >
        <TrendingUp size={24} color="#d97706" />
      </div>

      {/* Text block */}
      <div style={{ flex: 1, minWidth: 220 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
          <span
            style={{
              fontSize: 15,
              fontWeight: 700,
              color: "hsl(var(--foreground))",
              letterSpacing: "-0.01em",
            }}
          >
            V28 Risk Model — 100% Live (PY2026)
          </span>
          <span
            style={{
              background: "#f59e0b",
              color: "#fff",
              fontSize: 10,
              fontWeight: 700,
              padding: "2px 7px",
              borderRadius: 99,
              letterSpacing: "0.03em",
            }}
          >
            LIVE
          </span>
        </div>
        {isLoading ? (
          <div
            style={{
              height: 14,
              width: 260,
              background: "rgba(217,119,6,0.15)",
              borderRadius: 4,
              marginTop: 6,
            }}
          />
        ) : v28Summary ? (
          <>
            <Tooltip>
              <TooltipTrigger
                style={{ background: "none", border: "none", padding: 0, cursor: "default", textAlign: "left" }}
                data-testid="tooltip-v28-delta"
              >
                <div
                  style={{
                    fontSize: 28,
                    fontWeight: 900,
                    color: v28Summary.total_revenue_delta >= 0 ? "#059669" : "#dc2626",
                    lineHeight: 1.1,
                    marginTop: 2,
                    letterSpacing: "-0.02em",
                  }}
                >
                  {v28Summary.total_revenue_delta >= 0 ? "+" : "−"}
                  {`$${(Math.abs(v28Summary.total_revenue_delta) / 1_000_000).toFixed(2)}M`}
                </div>
              </TooltipTrigger>
              <TooltipContent>Portfolio-wide annual revenue impact of the CMS-HCC V28 model vs V24, summed across all {v28Summary.computed_patient_count} patients. Negative means V28 reduces risk scores; positive means V28 increases them.</TooltipContent>
            </Tooltip>
            <div style={{ fontSize: 12, color: "hsl(var(--muted-foreground))", marginTop: 3, fontWeight: 500 }}>
              {(() => {
                const eroded = (v28Summary.top_eroded_patients ?? []).filter(
                  (p) => p.revenue < -500,
                );
                const topPt = (v28Summary.top_eroded_patients ?? [])[0];
                return (
                  <>
                    {eroded.length > 0 && (
                      <span>
                        {eroded.length.toLocaleString()} patient
                        {eroded.length !== 1 ? "s" : ""} with &ge;&minus;$500 erosion
                        {topPt
                          ? ` · top eroded patient = −$${Math.abs(topPt.revenue).toLocaleString("en-US", { maximumFractionDigits: 0 })}`
                          : ""}
                      </span>
                    )}
                    {eroded.length === 0 && topPt && (
                      <span>
                        Top eroded patient: −$
                        {Math.abs(topPt.revenue).toLocaleString("en-US", {
                          maximumFractionDigits: 0,
                        })}
                      </span>
                    )}
                    {eroded.length === 0 && !topPt && (
                      <span>Portfolio V24 &rarr; V28 transition impact</span>
                    )}
                  </>
                );
              })()}
            </div>
          </>
        ) : null}
      </div>

      {/* CTA */}
      <Tooltip>
        <TooltipTrigger style={{ background: "none", border: "none", padding: 0 }} data-testid="tooltip-v28-cta">
          <Link
            href="/v28-impact"
        style={{
          background: "#f59e0b",
          color: "#fff",
          fontWeight: 700,
          fontSize: 13,
          padding: "10px 20px",
          borderRadius: 10,
          textDecoration: "none",
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          whiteSpace: "nowrap",
          flexShrink: 0,
          boxShadow: "none",
          transition: "opacity 0.15s",
        }}
        aria-label="Open V28 Impact Analysis"
      >
        Open V28 Impact Analysis
        <ArrowUpRight size={14} />
      </Link>
        </TooltipTrigger>
        <TooltipContent>Open the full V28 patient-by-patient impact report showing which patients gained or lost revenue under the new CMS model.</TooltipContent>
      </Tooltip>
    </div>
    </TooltipProvider>
  );
}
