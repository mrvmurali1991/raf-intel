"use client";

/**
 * PreVisitSummaryModal — on-demand modal with provider checklist, RAF
 * opportunity breakdown, and documentation checklist. Extracted from
 * prospective/page.tsx to defer ~35 kB of modal JSX until the user clicks
 * "Pre-Visit Summary" on a patient row.
 */

import React from "react";
import {
  ClipboardList,
  X,
  Printer,
  AlertTriangle,
  Clock,
  RefreshCw,
  Eye,
  CheckCircle,
} from "lucide-react";
import { tokens } from "@/styles/tokens";
import { fmtCurrencyFull } from "@/lib/format";

// ── Design tokens (mirror of page.tsx C map — no duplication of hex values) ──
const C = {
  primary:    tokens.primary,
  slate900:   tokens.slate900,
  slate700:   tokens.slate700,
  slate600:   tokens.slate600,
  slate400:   tokens.slate400,
  slate300:   tokens.slate300,
  slate200:   tokens.slate200,
  slate100:   tokens.slate100,
  slate50:    tokens.slate50,
  white:      tokens.white,
  red600:     tokens.riskHigh,
  amber500:   tokens.warningStrong,
  emerald500: tokens.success,
  subtleText: tokens.slate500,
};

// ── Constants ──
const AVG_SUSPECT_HCC_COEFFICIENT = 0.35;
const AWV_REVENUE_SUBSEQUENT = 175;

// ── Helpers ──
function calcAge(dob?: string): number | null {
  if (!dob) return null;
  const diff = Date.now() - new Date(dob).getTime();
  return Math.floor(diff / (365.25 * 24 * 60 * 60 * 1000));
}

function fmtCurrency(n: number): string {
  return fmtCurrencyFull(n);
}

// ── Types ──
export interface PreVisitSummaryPatient {
  pid: number;
  fname: string;
  lname: string;
  DOB?: string;
  sex?: string;
  raf_score: number;
  potential_raf: number;
  raf_gap: number;
  open_suspects_count: number;
  recapture_gaps_count: number;
  estimated_revenue_opportunity: number;
  provider?: string;
}

// ── Component ──
export default function PreVisitSummaryModal({
  patient,
  onClose,
}: {
  patient: PreVisitSummaryPatient;
  onClose: () => void;
}) {
  const age = calcAge(patient.DOB);
  const sexLabel =
    patient.sex === "Female" ? "F" : patient.sex === "Male" ? "M" : patient.sex ?? "—";

  const thStyle: React.CSSProperties = {
    padding: "8px 12px",
    fontSize: 11,
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    color: C.slate400,
    textAlign: "left",
    borderBottom: `1px solid ${C.slate200}`,
    background: C.slate50,
  };

  const tdStyle: React.CSSProperties = {
    padding: "10px 12px",
    fontSize: 13,
    color: C.slate900,
    borderBottom: `1px solid ${C.slate100}`,
  };

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        backgroundColor: "rgba(15,23,42,0.6)",
        backdropFilter: "blur(4px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
      }}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Pre-Visit Summary"
    >
      <div
        className="premium-card animate-scale-in"
        style={{
          background: C.white,
          borderRadius: 14,
          width: "100%",
          maxWidth: 720,
          maxHeight: "90vh",
          overflow: "auto",
          boxShadow: "0 20px 60px rgba(0,0,0,0.25)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Modal Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "20px 24px 16px",
            borderBottom: `1px solid ${C.slate200}`,
            background: C.slate50,
            borderRadius: "16px 16px 0 0",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div
              style={{
                width: 40, height: 40, borderRadius: 10,
                backgroundColor: `${C.primary}1A`,
                display: "flex", alignItems: "center", justifyContent: "center",
                color: C.primary,
              }}
            >
              <ClipboardList size={18} />
            </div>
            <div>
              <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: C.slate900 }}>Pre-Visit Summary</h2>
              <p style={{ margin: "2px 0 0", fontSize: 12, color: C.subtleText }}>
                {patient.lname}, {patient.fname} &mdash; PID #{patient.pid}
              </p>
            </div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              onClick={() => window.print()}
              style={{ display: "flex", alignItems: "center", gap: 6, padding: "7px 14px", borderRadius: 8, border: `1px solid ${C.slate200}`, background: C.white, fontSize: 12, fontWeight: 600, color: C.slate600, cursor: "pointer" }}
            >
              <Printer size={13} /> Print
            </button>
            <button
              onClick={onClose}
              aria-label="Close modal"
              style={{ display: "flex", alignItems: "center", justifyContent: "center", width: 32, height: 32, borderRadius: 8, border: `1px solid ${C.slate200}`, background: C.white, cursor: "pointer", color: C.slate600 }}
            >
              <X size={15} />
            </button>
          </div>
        </div>

        <div style={{ padding: 24 }}>
          {/* Demographics */}
          <section style={{ marginBottom: 24 }}>
            <h3 style={{ margin: "0 0 12px", fontSize: 14, fontWeight: 700, color: C.slate900 }}>Patient Demographics</h3>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, padding: 16, background: C.slate50, borderRadius: 10, border: `1px solid ${C.slate200}` }}>
              {[
                { label: "Name", value: `${patient.lname}, ${patient.fname}` },
                { label: "PID", value: `#${patient.pid}` },
                { label: "Age / Sex", value: age !== null ? `${age} ${sexLabel}` : sexLabel || "—" },
                { label: "Provider", value: patient.provider || "—" },
                { label: "Current RAF", value: patient.raf_score > 0 ? (patient.raf_score ?? 0).toFixed(3) : "—" },
                { label: "Target RAF", value: patient.potential_raf > 0 ? (patient.potential_raf ?? 0).toFixed(3) : "—" },
              ].map((item) => (
                <div key={item.label}>
                  <div style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", color: C.slate400, marginBottom: 2 }}>{item.label}</div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: C.slate900 }}>{item.value}</div>
                </div>
              ))}
            </div>
          </section>

          {/* RAF Opportunity */}
          <section style={{ marginBottom: 24 }}>
            <h3 style={{ margin: "0 0 12px", fontSize: 14, fontWeight: 700, color: C.slate900 }}>RAF Opportunity</h3>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
              {[
                { label: "Current RAF Score", value: patient.raf_score > 0 ? (patient.raf_score ?? 0).toFixed(3) : "Unscored", color: C.slate900 },
                { label: "Potential RAF (if captured)", value: patient.potential_raf > 0 ? (patient.potential_raf ?? 0).toFixed(3) : "—", color: C.primary },
                { label: "Revenue Opportunity", value: fmtCurrency(patient.estimated_revenue_opportunity), color: C.emerald500, useGradient: true },
              ].map((item) => (
                <div
                  key={item.label}
                  className="hover-lift"
                  style={{ padding: 14, background: C.white, border: `1px solid ${C.slate200}`, borderRadius: 10, textAlign: "center", transition: "transform 0.2s, box-shadow 0.2s" }}
                >
                  <div style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", color: C.slate400, marginBottom: 6 }}>{item.label}</div>
                  <div className={`tabular-nums${(item as { useGradient?: boolean }).useGradient ? " gradient-text" : ""}`} style={{ fontSize: 22, fontWeight: 700, color: (item as { useGradient?: boolean; color?: string }).useGradient ? undefined : item.color }}>{item.value}</div>
                </div>
              ))}
            </div>
          </section>

          {/* Suspect Conditions */}
          {patient.open_suspects_count > 0 && (
            <section style={{ marginBottom: 24 }}>
              <h3 style={{ margin: "0 0 12px", fontSize: 14, fontWeight: 700, color: C.slate900 }}>
                Suspect Conditions to Address ({patient.open_suspects_count})
              </h3>
              <div style={{ padding: 14, background: `${C.amber500}0D`, border: `1px solid ${C.amber500}33`, borderRadius: 10, fontSize: 13, color: C.slate700, lineHeight: 1.6 }}>
                <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                  <AlertTriangle size={16} style={{ color: C.amber500, marginTop: 2, flexShrink: 0 }} />
                  <div>
                    <p style={{ margin: "0 0 8px", fontWeight: 600, color: C.slate900 }}>
                      {patient.open_suspects_count} open suspect condition{patient.open_suspects_count !== 1 ? "s" : ""} identified from clinical evidence
                    </p>
                    <p style={{ margin: 0, fontSize: 12, color: C.subtleText }}>
                      Review AI-identified suspect conditions in the patient&apos;s Review Queue. Each suspect includes supporting clinical evidence from notes, labs, and vitals. Evaluate and document or rule out each condition during this visit.
                    </p>
                  </div>
                </div>
              </div>
            </section>
          )}

          {/* Recapture Gaps */}
          {patient.recapture_gaps_count > 0 && (
            <section style={{ marginBottom: 24 }}>
              <h3 style={{ margin: "0 0 12px", fontSize: 14, fontWeight: 700, color: C.slate900 }}>
                Chronic Conditions Needing Recapture ({patient.recapture_gaps_count})
              </h3>
              <div style={{ padding: 14, background: `${C.red600}0A`, border: `1px solid ${C.red600}22`, borderRadius: 10, fontSize: 13, color: C.slate700, lineHeight: 1.6 }}>
                <div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
                  <Clock size={16} style={{ color: C.red600, marginTop: 2, flexShrink: 0 }} />
                  <div>
                    <p style={{ margin: "0 0 8px", fontWeight: 600, color: C.slate900 }}>
                      {patient.recapture_gaps_count} chronic condition{patient.recapture_gaps_count !== 1 ? "s" : ""} coded in prior year not yet recaptured this year
                    </p>
                    <p style={{ margin: 0, fontSize: 12, color: C.subtleText }}>
                      CMS requires annual documentation of chronic HCC conditions to maintain RAF score. Review Recapture Gaps for specific ICD-10 codes and ensure MEAT criteria are documented for each condition.
                    </p>
                  </div>
                </div>
              </div>
            </section>
          )}

          {/* Documentation Checklist */}
          <section style={{ marginBottom: 24 }}>
            <h3 style={{ margin: "0 0 12px", fontSize: 14, fontWeight: 700, color: C.slate900 }}>
              Provider Checklist for This Visit
            </h3>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  <th style={thStyle}>Task</th>
                  <th style={thStyle}>Details</th>
                  <th style={thStyle}>RAF Impact</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { task: "Review & document suspect conditions", details: `${patient.open_suspects_count} AI-identified suspects pending`, impact: `+${(patient.open_suspects_count * AVG_SUSPECT_HCC_COEFFICIENT).toFixed(2)} RAF`, show: patient.open_suspects_count > 0 },
                  { task: "Recapture chronic HCC conditions", details: `${patient.recapture_gaps_count} conditions from prior year`, impact: "Maintain current RAF", show: patient.recapture_gaps_count > 0 },
                  { task: "Complete MEAT documentation", details: "Monitor, Evaluate, Assess, Treat for each HCC", impact: "Required for RAF validity", show: true },
                  { task: "Annual Wellness Visit elements", details: "Health risk assessment, preventive screenings", impact: `${fmtCurrency(AWV_REVENUE_SUBSEQUENT)} AWV revenue`, show: true },
                ]
                  .filter((r) => r.show)
                  .map((row) => (
                    <tr key={row.task}>
                      <td style={{ ...tdStyle, fontWeight: 600 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <div style={{ width: 18, height: 18, borderRadius: 4, border: `2px solid ${C.slate300}`, flexShrink: 0 }} />
                          {row.task}
                        </div>
                      </td>
                      <td style={{ ...tdStyle, color: C.subtleText }}>{row.details}</td>
                      <td style={{ ...tdStyle, color: C.emerald500, fontWeight: 600 }}>{row.impact}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </section>

          {/* Actions */}
          <div style={{ display: "flex", gap: 10 }}>
            <button onClick={() => window.open(`/patients/${patient.pid}`, "_blank")} style={{ display: "flex", alignItems: "center", gap: 6, padding: "9px 18px", borderRadius: 8, border: `1px solid ${C.slate200}`, background: C.white, fontSize: 13, fontWeight: 600, color: C.slate600, cursor: "pointer" }}>
              <Eye size={14} /> Full Profile
            </button>
            <button onClick={() => window.open(`/recapture`, "_blank")} style={{ display: "flex", alignItems: "center", gap: 6, padding: "9px 18px", borderRadius: 8, border: `1px solid ${C.slate200}`, background: C.white, fontSize: 13, fontWeight: 600, color: C.slate600, cursor: "pointer" }}>
              <RefreshCw size={14} /> Recapture Gaps
            </button>
            <button onClick={onClose} style={{ display: "flex", alignItems: "center", gap: 6, padding: "9px 18px", borderRadius: 8, border: "none", background: C.primary, fontSize: 13, fontWeight: 600, color: C.white, cursor: "pointer", marginLeft: "auto" }}>
              <CheckCircle size={14} /> Done
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
