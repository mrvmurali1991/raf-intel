"use client";

/**
 * <AuditReadinessCard /> — RADV audit-readiness gauge with breakdown.
 *
 * Shows:
 *   - Big % "Audit Ready" gauge (dual_signed / total_gaps)
 *   - Numeric breakdown: with_evidence / dual_signed / total_gaps
 *   - Cohen's kappa IRR tile (or proportion-agreement fallback for pre-rollout)
 *   - Top-5 list of gaps blocking audit-readiness (no MEAT phrase or unapproved)
 *
 * Pulls from GET /api/recapture/audit-readiness.
 *
 * Usage:
 *   <AuditReadinessCard />
 */

import { useQuery } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { ShieldCheck, AlertTriangle, Users, Info } from "lucide-react";

import { getRecaptureAuditReadiness } from "@/lib/api";
import type { AuditReadinessResponse } from "@/lib/api";
import { tokens } from "@/styles/tokens";

// ---- Helpers -----------------------------------------------------------------

type IrrBand = "excellent" | "acceptable" | "moderate" | "needs_review" | null | undefined;

/** Map audit-ready % to a gauge stroke colour via tokens. */
function gaugeColor(pct: number): string {
  if (pct >= 80) return tokens.riskLow;
  if (pct >= 50) return tokens.warningStrong;
  return tokens.riskHigh;
}

/** Map kappa IRR band to { text, soft } token pair. */
function kappaBandTokens(band: IrrBand): { text: string; soft: string } {
  if (band === "excellent") return { text: tokens.kappaExcellent, soft: tokens.kappaExcellentSoft };
  if (band === "acceptable" || band === "moderate") return { text: tokens.kappaModerate, soft: tokens.kappaModerateSoft };
  if (band === "needs_review") return { text: tokens.kappaPoor, soft: tokens.kappaPoorSoft };
  return { text: tokens.kappaNeutral, soft: tokens.kappaNeutralSoft };
}

/** Human-readable band label. */
function bandLabel(band: IrrBand): string {
  if (band === "excellent") return "Excellent";
  if (band === "acceptable" || band === "moderate") return "Moderate";
  if (band === "needs_review") return "Needs review";
  return "Insufficient data";
}

// ---- Sub-components ----------------------------------------------------------

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div
      style={{
        padding: 10,
        borderRadius: 8,
        background: tokens.slate50,
        border: `1px solid ${tokens.slate200}`,
      }}
    >
      <div style={{ fontSize: 22, fontWeight: 700, color: tokens.slate900 }}>{value}</div>
      <div
        style={{
          fontSize: 11,
          color: tokens.slate500,
          textTransform: "uppercase",
          letterSpacing: "0.05em",
        }}
      >
        {label}
      </div>
    </div>
  );
}

/**
 * IRR tile — renders Cohen's kappa prominently when available, falling back
 * to proportion-agreement with an explanatory note for pre-rollout data.
 */
function IrrTile({
  irr,
}: {
  irr: NonNullable<AuditReadinessResponse["inter_rater_reliability"]> & { band?: IrrBand };
}) {
  const { text: bandText, soft: bandSoft } = kappaBandTokens(irr.band);
  const isKappa = irr.method === "cohens_kappa" && irr.kappa != null;

  const kappaDisplay = isKappa && irr.kappa != null ? irr.kappa.toFixed(2) : null;
  const agreementDisplay =
    irr.agreement_pct != null ? `${irr.agreement_pct.toFixed(1)}%` : "—";

  return (
    <div
      data-testid="irr-tile"
      style={{
        borderRadius: 10,
        background: bandSoft,
        border: `1.5px solid ${bandText}`,
        padding: "16px 18px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Users size={16} color={bandText} aria-hidden="true" />
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            color: bandText,
          }}
        >
          Inter-rater reliability
        </span>
      </div>

      {/* Primary metric */}
      {isKappa ? (
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <span
            data-testid="irr-kappa-value"
            style={{ fontSize: 38, fontWeight: 800, lineHeight: 1, color: bandText }}
          >
            {kappaDisplay}
          </span>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span
              data-testid="irr-band-label"
              style={{ fontSize: 13, fontWeight: 700, color: bandText }}
            >
              {bandLabel(irr.band)}
            </span>
            <span style={{ fontSize: 12, color: tokens.slate500 }}>
              Cohen&apos;s &kappa;
            </span>
          </div>
        </div>
      ) : (
        /* Proportion-agreement fallback */
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <span
            data-testid="irr-agreement-value"
            style={{ fontSize: 38, fontWeight: 800, lineHeight: 1, color: bandText }}
          >
            {agreementDisplay}
          </span>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: bandText }}>
              {bandLabel(irr.band)}
            </span>
            <span style={{ fontSize: 12, color: tokens.slate500 }}>agreement</span>
          </div>
        </div>
      )}

      {/* Secondary stats */}
      <div style={{ display: "flex", gap: 12, fontSize: 12, color: tokens.slate600 }}>
        {isKappa && (
          <span>
            Agreement:{" "}
            <strong style={{ color: tokens.slate800 }}>{agreementDisplay}</strong>
          </span>
        )}
        <span>
          &#10003;{" "}
          <strong style={{ color: tokens.slate800 }}>{irr.secondary_approved}</strong>
        </span>
        <span>
          &#10007;{" "}
          <strong style={{ color: tokens.slate800 }}>{irr.secondary_rejected}</strong>
        </span>
        {irr.pending_review > 0 && (
          <span style={{ color: tokens.warningStrong }}>{irr.pending_review} pending</span>
        )}
      </div>

      {/* Footnote */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          gap: 5,
          fontSize: 11,
          color: tokens.slate400,
          borderTop: `1px solid ${bandText}33`,
          paddingTop: 8,
        }}
      >
        {!isKappa && (
          <Info
            size={12}
            color={tokens.slate400}
            aria-label="Using proportion agreement — kappa requires dual-coded gap data"
            style={{ flexShrink: 0, marginTop: 1 }}
          />
        )}
        <span>
          {isKappa
            ? `Cohen's kappa, n=${irr.kappa_n ?? "?"} dual-coded gaps`
            : "Proportion agreement (kappa pending dual-coded data)"}
        </span>
      </div>
    </div>
  );
}

// ---- Main component ----------------------------------------------------------

export function AuditReadinessCard() {
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 640px)");
    setIsMobile(mq.matches);
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["recapture-audit-readiness"],
    queryFn: getRecaptureAuditReadiness,
    staleTime: 60_000,
  });

  if (isLoading) {
    return (
      <div className="premium-card shimmer" style={{ height: 220, borderRadius: 10 }} />
    );
  }

  if (isError || !data) {
    return (
      <div
        className="premium-card"
        style={{
          padding: 20,
          borderRadius: 10,
          background: tokens.dangerSoft,
          border: `1px solid ${tokens.dangerBorder}`,
          color: tokens.danger,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14 }}>
          <AlertTriangle size={16} aria-hidden="true" /> Audit readiness unavailable
          {error instanceof Error ? `: ${error.message}` : ""}
        </div>
      </div>
    );
  }

  const pct = data.audit_ready_pct;
  const color = gaugeColor(pct);

  return (
    <div
      className="premium-card"
      data-testid="arc-card"
      style={{
        padding: isMobile ? 16 : 24,
        borderRadius: 10,
        display: "grid",
        gridTemplateColumns: isMobile ? "1fr" : "260px 1fr",
        gap: isMobile ? 16 : 24,
        alignItems: "stretch",
      }}
    >
      {/* Gauge column */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: 12,
          borderRight: isMobile ? "none" : `1px solid ${tokens.slate200}`,
          borderBottom: isMobile ? `1px solid ${tokens.slate200}` : "none",
          paddingBottom: isMobile ? 16 : 12,
        }}
      >
        <div
          style={{
            position: "relative",
            width: 180,
            height: 180,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <svg
            width="180"
            height="180"
            viewBox="0 0 180 180"
            aria-label={`Audit ready: ${pct.toFixed(1)}%`}
          >
            <circle
              cx="90"
              cy="90"
              r="76"
              stroke={tokens.slate100}
              strokeWidth="14"
              fill="none"
            />
            <circle
              cx="90"
              cy="90"
              r="76"
              stroke={color}
              strokeWidth="14"
              fill="none"
              strokeLinecap="round"
              strokeDasharray={`${(2 * Math.PI * 76 * pct) / 100} ${2 * Math.PI * 76}`}
              transform="rotate(-90 90 90)"
            />
          </svg>
          <div style={{ position: "absolute", textAlign: "center" }}>
            <div style={{ fontSize: 36, fontWeight: 700, color }}>{pct.toFixed(1)}%</div>
            <div
              style={{
                fontSize: 11,
                color: tokens.slate500,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
              }}
            >
              Audit Ready
            </div>
          </div>
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            marginTop: 12,
            fontSize: 12,
            color: tokens.slate600,
          }}
        >
          <ShieldCheck size={14} color={color} aria-hidden="true" /> RADV defense readiness
        </div>
      </div>

      {/* Right column: stats + IRR tile + blockers */}
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {/* Numeric breakdown */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: isMobile ? 8 : 12,
          }}
        >
          <Stat label="Total gaps" value={data.total_gaps} />
          <Stat label="With evidence" value={data.with_evidence} />
          <Stat label="Dual-signed" value={data.dual_signed} />
        </div>

        {/* IRR tile — shown when backend provides inter_rater_reliability */}
        {data.inter_rater_reliability != null && (
          <IrrTile irr={data.inter_rater_reliability} />
        )}

        {/* Top-5 blockers */}
        <div>
          <h3
            style={{
              margin: "0 0 8px",
              fontSize: 13,
              color: tokens.slate500,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
            }}
          >
            Top 5 blockers
          </h3>
          {data.missing_meat.length === 0 ? (
            <div style={{ fontSize: 13, color: tokens.riskLow, padding: "12px 0" }}>
              All gaps are dual-signed and audit-ready.
            </div>
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {data.missing_meat.map((m) => (
                <li
                  key={m.gap_id}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "flex-start",
                    padding: "8px 10px",
                    borderBottom: `1px solid ${tokens.slate100}`,
                    fontSize: 13,
                    gap: 8,
                  }}
                >
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <span style={{ fontWeight: 600, color: tokens.slate900 }}>
                      HCC {m.hcc}
                    </span>
                    <span style={{ color: tokens.slate500, marginLeft: 8 }}>
                      patient {m.patient_id} &middot; {m.reason}
                    </span>
                  </div>
                  <div style={{ color: tokens.riskHigh, fontWeight: 600, fontSize: 12, flexShrink: 0 }}>
                    ${(m.revenue_impact || 0).toLocaleString()}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

export default AuditReadinessCard;
