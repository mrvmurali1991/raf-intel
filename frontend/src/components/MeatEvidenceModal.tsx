"use client";

/**
 * MeatEvidenceModal — RADV audit drilldown UX.
 *
 * Layout
 * ------
 * - Header: provider name + risk tier
 * - Body:
 *   - Top stats: MEAT %, HCC count
 *   - List of weak HCCs (each row is expandable)
 *     - Click expands and lazy-loads per-patient evidence rows
 *     - Each row renders M / E / A / T as filled-or-not checkboxes
 *   - When no weak HCCs: cheerful "all clear" empty state
 *
 * Built without an external modal lib to keep the component small and
 * dependency-free.  Uses a fixed-position overlay; click outside or hit
 * Escape to dismiss.
 */
import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronUp,
  X,
  Check,
  AlertTriangle,
  ShieldCheck,
} from "lucide-react";
import {
  getProviderMeatEvidence,
  type MeatAuditRisk,
  type MeatAuditWeakHcc,
  type MeatEvidenceResponse,
} from "@/lib/api";

const TIER_COPY: Record<
  MeatAuditRisk["risk_tier"],
  { color: string; bg: string; description: string }
> = {
  ready: {
    color: "#065F46",
    bg: "#D1FAE5",
    description:
      "Documentation is RADV-ready across coded HCCs. No urgent gaps detected.",
  },
  at_risk: {
    color: "#92400E",
    bg: "#FEF3C7",
    description:
      "Some coded HCCs are missing one or more MEAT components. Address the weak HCCs below before the next RADV sweep.",
  },
  audit_risk: {
    color: "#991B1B",
    bg: "#FEE2E2",
    description:
      "High clawback risk: a majority of coded HCCs lack defensible MEAT documentation. Prioritize the weak HCCs below for re-documentation.",
  },
  insufficient: {
    color: "#475569",
    bg: "#F1F5F9",
    description:
      "Not enough coded HCCs to render a verdict. Provider needs at least 3 coded HCCs in the measurement year.",
  },
};

const MEAT_KEYS: Array<{ short: string; long: string }> = [
  { short: "M", long: "Monitor" },
  { short: "E", long: "Evaluate" },
  { short: "A", long: "Assess" },
  { short: "T", long: "Treat" },
];

// ---------------------------------------------------------------------------
// MEAT checkbox row — present = filled green, missing = hollow gray
// ---------------------------------------------------------------------------

function MeatCheckRow({
  present,
}: {
  present: string[];
}) {
  return (
    <div style={{ display: "flex", gap: 8 }}>
      {MEAT_KEYS.map((k) => {
        const isOn = present.includes(k.long);
        return (
          <span
            key={k.short}
            title={`${k.long}${isOn ? " (present)" : " (missing)"}`}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              padding: "3px 8px",
              borderRadius: 6,
              fontSize: 11,
              fontWeight: 600,
              background: isOn ? "#D1FAE5" : "#F1F5F9",
              color: isOn ? "#065F46" : "#94A3B8",
              border: `1px solid ${isOn ? "#10B981" : "#E2E8F0"}`,
            }}
          >
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                width: 12,
                height: 12,
                borderRadius: 3,
                border: `1.5px solid ${isOn ? "#065F46" : "#94A3B8"}`,
                background: isOn ? "#10B981" : "transparent",
                color: "#FFFFFF",
              }}
            >
              {isOn ? <Check size={10} strokeWidth={3} /> : null}
            </span>
            {k.short}
          </span>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Per-HCC expandable section
// ---------------------------------------------------------------------------

function WeakHccRow({
  providerId,
  hcc,
  year,
}: {
  providerId: number;
  hcc: MeatAuditWeakHcc;
  year?: number;
}) {
  const [open, setOpen] = useState(false);

  const { data: evidence, isLoading } = useQuery<MeatEvidenceResponse>({
    queryKey: ["meat-evidence", providerId, hcc.hcc_code, year ?? 2026],
    queryFn: () => getProviderMeatEvidence(providerId, hcc.hcc_code, year),
    enabled: open,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  const pct = Math.round(hcc.meat_score * 100);

  return (
    <div
      style={{
        border: "1px solid #E2E8F0",
        borderRadius: 10,
        marginBottom: 10,
        background: "#FFFFFF",
        overflow: "hidden",
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          padding: "12px 16px",
          background: open ? "#F8FAFC" : "#FFFFFF",
          border: "none",
          borderBottom: open ? "1px solid #E2E8F0" : "none",
          cursor: "pointer",
          textAlign: "left",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0, flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span
              style={{
                fontSize: 12,
                fontWeight: 700,
                color: "#475569",
                background: "#F1F5F9",
                padding: "2px 8px",
                borderRadius: 6,
              }}
            >
              HCC {hcc.hcc_code}
            </span>
            <span style={{ fontSize: 14, fontWeight: 600, color: "#0F172A" }}>
              {hcc.label}
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span
              style={{
                fontSize: 12,
                fontWeight: 700,
                color: pct < 50 ? "#991B1B" : pct < 75 ? "#92400E" : "#065F46",
              }}
            >
              {pct}% MEAT
            </span>
            {hcc.missing_components.length > 0 && (
              <span style={{ fontSize: 12, color: "#64748B" }}>
                Missing: {hcc.missing_components.join(", ")}
              </span>
            )}
          </div>
        </div>
        {open ? (
          <ChevronUp size={16} color="#64748B" />
        ) : (
          <ChevronDown size={16} color="#64748B" />
        )}
      </button>

      {open && (
        <div style={{ padding: "12px 16px", background: "#FAFBFC" }}>
          {isLoading ? (
            <div style={{ fontSize: 13, color: "#64748B" }}>Loading evidence…</div>
          ) : !evidence || evidence.evidence.length === 0 ? (
            <div style={{ fontSize: 13, color: "#64748B" }}>
              No documented encounters found for this HCC. Schedule a re-documentation visit.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {evidence.evidence.map((row, i) => (
                <div
                  key={`${row.patient_hcc_id}-${row.encounter_id ?? "nil"}-${i}`}
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 6,
                    padding: 10,
                    borderRadius: 8,
                    background: "#FFFFFF",
                    border: "1px solid #E2E8F0",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      gap: 12,
                      fontSize: 12,
                      color: "#475569",
                    }}
                  >
                    <span>
                      <strong style={{ color: "#0F172A" }}>Patient #{row.patient_id}</strong>
                      {row.encounter_date && (
                        <>
                          {" · "}Encounter {row.encounter_date}
                        </>
                      )}
                    </span>
                    <MeatCheckRow present={row.components_present} />
                  </div>
                  {row.evidence_snippet && (
                    <div
                      style={{
                        fontSize: 12,
                        color: "#334155",
                        background: "#F8FAFC",
                        borderRadius: 6,
                        padding: "8px 10px",
                        fontStyle: "italic",
                        lineHeight: 1.5,
                      }}
                    >
                      &ldquo;{row.evidence_snippet}&rdquo;
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main modal
// ---------------------------------------------------------------------------

export interface MeatEvidenceModalProps {
  providerId: number;
  providerName?: string;
  year?: number;
  assessment: MeatAuditRisk;
  onClose: () => void;
}

export function MeatEvidenceModal({
  providerId,
  providerName,
  year,
  assessment,
  onClose,
}: MeatEvidenceModalProps) {
  // Close on Escape
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const tier = TIER_COPY[assessment.risk_tier];
  const pct = Math.round(assessment.meat_completeness * 100);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="meat-modal-title"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15, 23, 42, 0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
        padding: 24,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#FFFFFF",
          borderRadius: 14,
          width: "min(720px, 100%)",
          maxHeight: "85vh",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          boxShadow: "0 30px 60px rgba(15, 23, 42, 0.35)",
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "18px 22px",
            borderBottom: "1px solid #E2E8F0",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <h2
              id="meat-modal-title"
              style={{
                margin: 0,
                fontSize: 16,
                fontWeight: 700,
                color: "#0F172A",
              }}
            >
              MEAT Audit Risk
              {providerName && (
                <span style={{ color: "#64748B", fontWeight: 500 }}>
                  {" "}
                  · {providerName}
                </span>
              )}
            </h2>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                  fontSize: 12,
                  fontWeight: 700,
                  padding: "3px 10px",
                  borderRadius: 9999,
                  color: tier.color,
                  background: tier.bg,
                }}
              >
                {assessment.risk_tier === "ready" ? (
                  <ShieldCheck size={12} />
                ) : (
                  <AlertTriangle size={12} />
                )}
                {assessment.risk_label}
              </span>
              <span style={{ fontSize: 12, color: "#64748B" }}>
                Measurement year {assessment.year}
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            style={{
              padding: 6,
              border: "none",
              background: "transparent",
              cursor: "pointer",
              color: "#64748B",
              borderRadius: 6,
            }}
          >
            <X size={20} />
          </button>
        </div>

        {/* Stat strip */}
        <div
          style={{
            padding: "14px 22px",
            display: "flex",
            gap: 24,
            borderBottom: "1px solid #E2E8F0",
            background: "#FAFBFC",
          }}
        >
          <div>
            <div style={{ fontSize: 11, color: "#64748B", fontWeight: 600 }}>
              MEAT compliance
            </div>
            <div
              style={{
                fontSize: 24,
                fontWeight: 700,
                color: tier.color,
                lineHeight: 1.2,
              }}
            >
              {pct}%
            </div>
          </div>
          <div>
            <div style={{ fontSize: 11, color: "#64748B", fontWeight: 600 }}>
              Coded HCCs
            </div>
            <div
              style={{
                fontSize: 24,
                fontWeight: 700,
                color: "#0F172A",
                lineHeight: 1.2,
              }}
            >
              {assessment.hcc_count}
            </div>
          </div>
          <div style={{ flex: 1, fontSize: 12, color: "#64748B", lineHeight: 1.45 }}>
            {tier.description}
          </div>
        </div>

        {/* Weak HCC list */}
        <div style={{ padding: "16px 22px", overflowY: "auto", flex: 1 }}>
          <h3
            style={{
              margin: "0 0 10px",
              fontSize: 13,
              fontWeight: 700,
              color: "#0F172A",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
            }}
          >
            Weak HCCs ({assessment.top_weak_hccs.length})
          </h3>
          {assessment.top_weak_hccs.length === 0 ? (
            <div
              style={{
                padding: "24px 16px",
                borderRadius: 10,
                background: "#F8FAFC",
                border: "1px dashed #CBD5E1",
                color: "#64748B",
                fontSize: 13,
                textAlign: "center",
              }}
            >
              No HCCs below the 75% MEAT threshold. Documentation is in good shape.
            </div>
          ) : (
            assessment.top_weak_hccs.map((hcc) => (
              <WeakHccRow
                key={hcc.hcc_code}
                providerId={providerId}
                hcc={hcc}
                year={year}
              />
            ))
          )}
        </div>
      </div>
    </div>
  );
}

export default MeatEvidenceModal;
