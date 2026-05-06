"use client";

/**
 * <AuditReadinessCard /> — RADV audit-readiness gauge with breakdown.
 *
 * Shows:
 *   - Big % "Audit Ready" gauge (dual_signed / total_gaps)
 *   - Numeric breakdown: with_evidence / dual_signed / total_gaps
 *   - Top-5 list of gaps blocking audit-readiness (no MEAT phrase or unapproved)
 *
 * Pulls from GET /api/recapture/audit-readiness.
 */

import { useQuery } from "@tanstack/react-query";
import { ShieldCheck, AlertTriangle, Users } from "lucide-react";

import { getRecaptureAuditReadiness } from "@/lib/api";

function gaugeColor(pct: number): string {
  if (pct >= 80) return "#16a34a"; // green
  if (pct >= 50) return "#f59e0b"; // amber
  return "#dc2626";                // red
}

function irrColor(band: "excellent" | "acceptable" | "needs_review" | null | undefined): string {
  if (band === "excellent") return "#16a34a";
  if (band === "acceptable") return "#f59e0b";
  if (band === "needs_review") return "#dc2626";
  return "#94a3b8";
}

function irrLabel(band: "excellent" | "acceptable" | "needs_review" | null | undefined): string {
  if (band === "excellent") return "Excellent";
  if (band === "acceptable") return "Acceptable";
  if (band === "needs_review") return "Needs review";
  return "Insufficient data";
}

export function AuditReadinessCard() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["recapture-audit-readiness"],
    queryFn: getRecaptureAuditReadiness,
    staleTime: 60_000,
  });

  if (isLoading) {
    return (
      <div className="premium-card shimmer" style={{ height: 220, borderRadius: 12 }} />
    );
  }

  if (isError || !data) {
    return (
      <div
        className="premium-card"
        style={{
          padding: 20,
          borderRadius: 12,
          background: "#fef2f2",
          border: "1px solid #fecaca",
          color: "#b91c1c",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14 }}>
          <AlertTriangle size={16} /> Audit readiness unavailable
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
      style={{
        padding: 24,
        borderRadius: 12,
        display: "grid",
        gridTemplateColumns: "260px 1fr",
        gap: 24,
        alignItems: "stretch",
      }}
    >
      {/* Gauge */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: 12,
          borderRight: "1px solid #e2e8f0",
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
          <svg width="180" height="180" viewBox="0 0 180 180">
            <circle
              cx="90" cy="90" r="76"
              stroke="#f1f5f9" strokeWidth="14" fill="none"
            />
            <circle
              cx="90" cy="90" r="76"
              stroke={color} strokeWidth="14" fill="none"
              strokeLinecap="round"
              strokeDasharray={`${(2 * Math.PI * 76 * pct) / 100} ${2 * Math.PI * 76}`}
              transform="rotate(-90 90 90)"
            />
          </svg>
          <div
            style={{
              position: "absolute",
              textAlign: "center",
            }}
          >
            <div style={{ fontSize: 36, fontWeight: 700, color }}>{pct.toFixed(1)}%</div>
            <div style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>
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
            color: "#475569",
          }}
        >
          <ShieldCheck size={14} color={color} /> RADV defense readiness
        </div>
      </div>

      {/* Breakdown + missing list */}
      <div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, marginBottom: 16 }}>
          <Stat label="Total gaps" value={data.total_gaps} />
          <Stat label="With evidence" value={data.with_evidence} />
          <Stat label="Dual-signed" value={data.dual_signed} />
        </div>

        {data.inter_rater_reliability && (
          <div
            title={data.inter_rater_reliability.note}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              padding: "10px 12px",
              borderRadius: 8,
              background: "#f8fafc",
              border: "1px solid #e2e8f0",
              marginBottom: 16,
            }}
          >
            <Users size={18} color={irrColor(data.inter_rater_reliability.band)} />
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                Inter-rater reliability
              </div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span style={{ fontSize: 20, fontWeight: 700, color: irrColor(data.inter_rater_reliability.band) }}>
                  {data.inter_rater_reliability.agreement_pct != null
                    ? `${data.inter_rater_reliability.agreement_pct.toFixed(1)}%`
                    : "—"}
                </span>
                <span style={{ fontSize: 12, color: "#475569" }}>
                  {irrLabel(data.inter_rater_reliability.band)}
                </span>
              </div>
              <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 2 }}>
                {data.inter_rater_reliability.secondary_approved} approved ·{" "}
                {data.inter_rater_reliability.secondary_rejected} rejected ·{" "}
                {data.inter_rater_reliability.pending_review} pending
              </div>
            </div>
          </div>
        )}

        <div>
          <h3 style={{ margin: "0 0 8px", fontSize: 13, color: "#475569", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Top 5 blockers
          </h3>
          {data.missing_meat.length === 0 ? (
            <div style={{ fontSize: 13, color: "#16a34a", padding: "12px 0" }}>
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
                    alignItems: "center",
                    padding: "8px 10px",
                    borderBottom: "1px solid #f1f5f9",
                    fontSize: 13,
                  }}
                >
                  <div>
                    <span style={{ fontWeight: 600, color: "#0f172a" }}>HCC {m.hcc}</span>
                    <span style={{ color: "#64748b", marginLeft: 8 }}>
                      patient {m.patient_id} · {m.reason}
                    </span>
                  </div>
                  <div style={{ color: "#dc2626", fontWeight: 600, fontSize: 12 }}>
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

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div
      style={{
        padding: 10,
        borderRadius: 8,
        background: "#f8fafc",
        border: "1px solid #e2e8f0",
      }}
    >
      <div style={{ fontSize: 22, fontWeight: 700, color: "#0f172a" }}>{value}</div>
      <div style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {label}
      </div>
    </div>
  );
}

export default AuditReadinessCard;
