"use client";

import { TrendingUp, Users, Activity, ShieldCheck } from "lucide-react";
import { tokens } from "@/styles/tokens";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from "@/components/ui/tooltip";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface KPIStripStats {
  high: number;
  unscored: number;
  avgRaf: number;
  hccTotal: number;
  all: number;
}

export interface KPIStripProps {
  stats: KPIStripStats;
  /** Called when "Need Review" tile is clicked */
  onHighClick?: () => void;
  /** Called when "Unscored" tile is clicked */
  onUnscoredClick?: () => void;
}

// ---------------------------------------------------------------------------
// Colour tokens (local constants matching patients/page.tsx "C" object)
// ---------------------------------------------------------------------------

const C = {
  bgCard: "hsl(var(--card))",
  borderSoft: "hsl(var(--border))",
  text: "hsl(var(--card-foreground))",
  textSubtle: tokens.slate500,
  brand: tokens.teal700,
};

// ---------------------------------------------------------------------------
// Component — 4-card KPI row for the patients worklist header
// ---------------------------------------------------------------------------

export function KPIStrip({ stats, onHighClick, onUnscoredClick }: KPIStripProps) {
  return (
    <TooltipProvider delay={200}>
    <div
      className="kpi-full-grid rci-population-overview"
      style={{
        gridTemplateColumns: "repeat(auto-fit, minmax(min(200px, 100%), 1fr))",
        gap: 12,
        marginBottom: 16,
      }}
    >
      {/* Need Review */}
      <div
        style={{
          backgroundColor: C.bgCard,
          border: `1px solid ${C.borderSoft}`,
          borderTop: `3px solid ${tokens.riskHigh}`,
          borderRadius: 12,
          padding: 20,
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          gap: 8,
          boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)",
          minHeight: 120,
          cursor: stats.high > 0 ? "pointer" : "default",
          transition: "border-color 0.15s ease",
        }}
        onClick={() => { if (stats.high > 0 && onHighClick) onHighClick(); }}
        aria-label={stats.high > 0 ? `Show ${stats.high} high-risk patients` : "No high-risk patients"}
        role={stats.high > 0 ? "button" : undefined}
        tabIndex={stats.high > 0 ? 0 : undefined}
        onKeyDown={(e) => {
          if (stats.high > 0 && onHighClick && (e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            onHighClick();
          }
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <TrendingUp size={16} color={tokens.riskHigh} />
          <Tooltip>
            <TooltipTrigger
              style={{ background: "none", border: "none", padding: 0, cursor: "inherit" }}
              data-testid="tooltip-kpi-need-review"
            >
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  color: C.textSubtle,
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                }}
              >
                Need Review
              </span>
            </TooltipTrigger>
            <TooltipContent>Patients with RAF score &ge; 2.0 flagged as high-risk. Click to filter the patient list to this group.</TooltipContent>
          </Tooltip>
        </div>
        <div
          style={{
            fontSize: 24,
            fontWeight: 700,
            color: stats.high > 0 ? tokens.riskHigh : C.text,
            fontVariantNumeric: "tabular-nums",
            letterSpacing: "-0.02em",
            lineHeight: 1,
          }}
        >
          {stats.high}
        </div>
        <div style={{ fontSize: 11, color: C.textSubtle, textTransform: "uppercase", letterSpacing: "0.04em" }}>High-risk patients</div>
      </div>

      {/* Unscored */}
      <div
        style={{
          backgroundColor: C.bgCard,
          border: `1px solid ${C.borderSoft}`,
          borderRadius: 12,
          padding: 20,
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          gap: 8,
          boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)",
          minHeight: 120,
          cursor: stats.unscored > 0 ? "pointer" : "default",
        }}
        onClick={() => { if (stats.unscored > 0 && onUnscoredClick) onUnscoredClick(); }}
        aria-label={
          stats.unscored > 0
            ? `Show ${stats.unscored} unscored patients`
            : "No unscored patients"
        }
        role={stats.unscored > 0 ? "button" : undefined}
        tabIndex={stats.unscored > 0 ? 0 : undefined}
        onKeyDown={(e) => {
          if (stats.unscored > 0 && onUnscoredClick && (e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            onUnscoredClick();
          }
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Users size={16} color={tokens.slate400} />
          <Tooltip>
            <TooltipTrigger
              style={{ background: "none", border: "none", padding: 0, cursor: "inherit" }}
              data-testid="tooltip-kpi-unscored"
            >
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  color: C.textSubtle,
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                }}
              >
                Unscored
              </span>
            </TooltipTrigger>
            <TooltipContent>Patients imported from EMR who have not yet had an AI analysis run. Click to queue them for scoring.</TooltipContent>
          </Tooltip>
        </div>
        <div
          style={{
            fontSize: 24,
            fontWeight: 700,
            color: C.text,
            fontVariantNumeric: "tabular-nums",
            letterSpacing: "-0.02em",
            lineHeight: 1,
          }}
        >
          {stats.unscored}
        </div>
        <div style={{ fontSize: 11, color: C.textSubtle, textTransform: "uppercase", letterSpacing: "0.04em" }}>Pending analysis</div>
      </div>

      {/* Average RAF */}
      <div
        style={{
          backgroundColor: C.bgCard,
          border: `1px solid ${C.borderSoft}`,
          borderRadius: 12,
          padding: 20,
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          gap: 8,
          boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)",
          minHeight: 120,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Activity size={16} color={tokens.success} />
          <Tooltip>
            <TooltipTrigger
              style={{ background: "none", border: "none", padding: 0, cursor: "default" }}
              data-testid="tooltip-kpi-avg-raf"
            >
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  color: C.textSubtle,
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                }}
              >
                Average RAF
              </span>
            </TooltipTrigger>
            <TooltipContent>Mean Risk Adjustment Factor score across all scored patients. A score of 1.0 equals average population risk; values above 1.5 indicate a high-acuity panel.</TooltipContent>
          </Tooltip>
        </div>
        <div
          style={{
            fontSize: 24,
            fontWeight: 700,
            color: C.text,
            fontVariantNumeric: "tabular-nums",
            letterSpacing: "-0.02em",
            lineHeight: 1,
          }}
        >
          {stats.avgRaf > 0 ? stats.avgRaf.toFixed(2) : "—"}
        </div>
        <div style={{ fontSize: 11, color: C.textSubtle, textTransform: "uppercase", letterSpacing: "0.04em" }}>
          {stats.avgRaf > 0
            ? `${stats.avgRaf.toFixed(3)} mean across panel`
            : "No scored patients yet"}
        </div>
      </div>

      {/* Total HCCs */}
      <div
        style={{
          backgroundColor: C.bgCard,
          border: `1px solid ${C.borderSoft}`,
          borderRadius: 12,
          padding: 20,
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          gap: 8,
          boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)",
          minHeight: 120,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <ShieldCheck size={16} color={tokens.infoBlue} />
          <Tooltip>
            <TooltipTrigger
              style={{ background: "none", border: "none", padding: 0, cursor: "default" }}
              data-testid="tooltip-kpi-hccs-captured"
            >
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  color: C.textSubtle,
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                }}
              >
                HCCs Captured
              </span>
            </TooltipTrigger>
            <TooltipContent>Total Hierarchical Condition Categories coded and confirmed across all patients. Higher counts reflect more complete chronic-condition documentation.</TooltipContent>
          </Tooltip>
        </div>
        <div
          style={{
            fontSize: 24,
            fontWeight: 700,
            color: C.text,
            fontVariantNumeric: "tabular-nums",
            letterSpacing: "-0.02em",
            lineHeight: 1,
          }}
        >
          {stats.hccTotal.toLocaleString()}
        </div>
        <div style={{ fontSize: 11, color: C.textSubtle, textTransform: "uppercase", letterSpacing: "0.04em" }}>
          {stats.all > 0
            ? `${(stats.hccTotal / stats.all).toFixed(1)} avg per patient`
            : "Across current view"}
        </div>
      </div>
    </div>
    </TooltipProvider>
  );
}
