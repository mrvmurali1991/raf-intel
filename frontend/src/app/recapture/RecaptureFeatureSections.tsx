"use client";

/**
 * RecaptureFeatureSections — four feature-flagged secondary sections.
 * Extracted from recapture/page.tsx to defer CfoExecutiveSummary,
 * BonusLeaderboard, OutreachSummaryCards, and AuditReadinessCard (~60 kB
 * combined) until after the primary recapture worklist has rendered.
 */

import FeatureFlag from "@/components/FeatureFlag";
import RecaptureVelocityKpis from "@/components/RecaptureVelocityKpis";
import RecaptureDecayChart from "@/components/RecaptureDecayChart";
import OutreachSummaryCards from "@/components/OutreachSummaryCards";
import { BonusLeaderboard } from "@/components/BonusLeaderboard";
import CfoExecutiveSummary from "@/components/CfoExecutiveSummary";
import AuditReadinessCard from "@/components/AuditReadinessCard";
import RecaptureAuditExportButton from "@/components/RecaptureAuditExportButton";
import { tokens } from "@/styles/tokens";

export interface RecaptureFeatureSectionsProps {
  year: number;
}

export default function RecaptureFeatureSections({ year }: RecaptureFeatureSectionsProps) {
  const headingStyle: React.CSSProperties = {
    margin: "0 0 12px",
    fontSize: 16,
    fontWeight: 700,
    color: tokens.slate900,
  };

  const rowStyle: React.CSSProperties = {
    display: "grid",
    gridTemplateColumns: "repeat(12, 1fr)",
    gap: 16,
    marginBottom: 24,
  };

  return (
    <>
      {/* Velocity KPIs + decay curve */}
      <FeatureFlag flagKey="recapture_decay_curve">
        <div className="animate-fade-in" style={rowStyle}>
          <div style={{ gridColumn: "1 / -1" }}>
            <h2 style={headingStyle}>Recapture velocity &amp; decay</h2>
            <div style={{ marginBottom: 16 }}>
              <RecaptureVelocityKpis />
            </div>
            <RecaptureDecayChart />
          </div>
        </div>
      </FeatureFlag>

      {/* CFO executive summary */}
      <FeatureFlag flagKey="recapture_cfo_forecast">
        <div className="animate-fade-in" style={rowStyle}>
          <div style={{ gridColumn: "1 / -1" }}>
            <h2 style={headingStyle}>CFO executive summary</h2>
            <CfoExecutiveSummary year={year} />
          </div>
        </div>
      </FeatureFlag>

      {/* Bonus leaderboard */}
      <FeatureFlag flagKey="recapture_bonus">
        <div className="animate-fade-in" style={rowStyle}>
          <div style={{ gridColumn: "1 / -1" }}>
            <h2 style={headingStyle}>Coder bonus leaderboard</h2>
            <BonusLeaderboard />
          </div>
        </div>
      </FeatureFlag>

      {/* Outreach summary */}
      <FeatureFlag flagKey="recapture_outreach">
        <div className="animate-fade-in" style={rowStyle}>
          <div style={{ gridColumn: "1 / -1" }}>
            <h2 style={headingStyle}>Patient outreach</h2>
            <OutreachSummaryCards />
          </div>
        </div>
      </FeatureFlag>

      {/* RADV Dual-Coder MEAT Audit */}
      <FeatureFlag flagKey="recapture_meat_audit">
        <div className="animate-fade-in" style={rowStyle}>
          <div style={{ gridColumn: "1 / -1" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
              <h2 style={{ ...headingStyle, margin: 0 }}>RADV Audit Defense</h2>
              <RecaptureAuditExportButton year={year} />
            </div>
            <AuditReadinessCard />
          </div>
        </div>
      </FeatureFlag>
    </>
  );
}
