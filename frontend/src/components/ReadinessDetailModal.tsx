"use client";

/**
 * ReadinessDetailModal — drill-down for a single recapture gap.
 *
 * Shows the four scoring components as horizontal bars:
 *   1. Problem-list match
 *   2. Problem-list freshness (< 90 days)
 *   3. Recent encounter (< 90 days)
 *   4. MEAT element coverage (M / E / A / T pills)
 *
 * Beneath the bars we render the recommended-actions list returned by the
 * backend.  The modal owns its own data-fetching: pass a gapId and the
 * authenticated tenant scope is taken care of by the shared axios client.
 */

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { X, CheckCircle2, AlertCircle } from "lucide-react";

import { getGapReadiness, type GapReadiness } from "@/lib/api";
import { ReadinessScoreBadge, tierFromScore } from "@/components/ReadinessScoreBadge";

const colors = {
  slate900: "#0F172A",
  slate700: "#334155",
  slate500: "#64748B",
  slate300: "#CBD5E1",
  slate200: "#E2E8F0",
  slate100: "#F1F5F9",
  slate50: "#F8FAFC",
  white: "#FFFFFF",
  emerald600: "#059669",
  red500: "#EF4444",
  amber500: "#F59E0B",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function ComponentBar({
  label,
  hint,
  earned,
  max,
  satisfied,
}: {
  label: string;
  hint?: string;
  earned: number;
  max: number;
  satisfied: boolean;
}) {
  const pct = Math.max(0, Math.min(100, max === 0 ? 0 : (earned / max) * 100));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {satisfied ? (
          <CheckCircle2 size={14} color={colors.emerald600} />
        ) : (
          <AlertCircle size={14} color={colors.amber500} />
        )}
        <span style={{ fontSize: 12, fontWeight: 600, color: colors.slate700 }}>
          {label}
        </span>
        {hint && (
          <span style={{ fontSize: 11, color: colors.slate500 }}>· {hint}</span>
        )}
        <span
          style={{
            marginLeft: "auto",
            fontSize: 11,
            fontWeight: 700,
            color: colors.slate900,
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, monospace",
          }}
        >
          {earned} / {max}
        </span>
      </div>
      <div style={{ height: 6, borderRadius: 4, background: colors.slate100 }}>
        <div
          style={{
            height: "100%",
            width: `${pct}%`,
            borderRadius: 4,
            background: satisfied
              ? "linear-gradient(90deg, #10B981, #059669)"
              : "linear-gradient(90deg, #F59E0B, #D97706)",
            transition: "width 0.4s cubic-bezier(0.4, 0, 0.2, 1)",
          }}
        />
      </div>
    </div>
  );
}

function MeatPills({ meat }: { meat: GapReadiness["components"]["meat"] }) {
  const items: { key: keyof GapReadiness["components"]["meat"]; label: string }[] = [
    { key: "m", label: "M" },
    { key: "e", label: "E" },
    { key: "a", label: "A" },
    { key: "t", label: "T" },
  ];
  return (
    <div style={{ display: "flex", gap: 6 }}>
      {items.map((it) => {
        const present = !!meat[it.key];
        return (
          <span
            key={it.key}
            title={`${it.label}: ${present ? "Present" : "Missing"}`}
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: 22,
              height: 22,
              borderRadius: 999,
              fontSize: 11,
              fontWeight: 700,
              color: present ? colors.white : colors.slate500,
              background: present ? colors.emerald600 : colors.slate100,
              border: `1px solid ${present ? colors.emerald600 : colors.slate200}`,
            }}
          >
            {it.label}
          </span>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------

export interface ReadinessDetailModalProps {
  gapId: number | null;
  open: boolean;
  onClose: () => void;
}

export function ReadinessDetailModal({ gapId, open, onClose }: ReadinessDetailModalProps) {
  const enabled = open && gapId != null;

  const { data, isLoading, isError } = useQuery<GapReadiness>({
    queryKey: ["recapture-readiness", gapId],
    queryFn: () => getGapReadiness(gapId as number),
    enabled,
  });

  if (!open) return null;

  const tier = data ? tierFromScore(data.score) : undefined;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Recapture Readiness Details"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15, 23, 42, 0.55)",
        zIndex: 100,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: colors.white,
          borderRadius: 12,
          boxShadow: "0 20px 50px rgba(0,0,0,0.25)",
          width: "100%",
          maxWidth: 560,
          maxHeight: "85vh",
          overflowY: "auto",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "18px 22px",
            borderBottom: `1px solid ${colors.slate200}`,
          }}
        >
          <div>
            <p style={{ margin: 0, fontSize: 11, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", color: colors.slate500 }}>
              Recapture Readiness
            </p>
            <h2 style={{ margin: "4px 0 0", fontSize: 18, fontWeight: 700, color: colors.slate900 }}>
              Gap #{gapId ?? "—"}
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            style={{
              background: "transparent",
              border: "none",
              cursor: "pointer",
              padding: 6,
              borderRadius: 6,
              color: colors.slate500,
            }}
          >
            <X size={18} />
          </button>
        </div>

        <div style={{ padding: 22 }}>
          {isLoading && (
            <div style={{ padding: 24, textAlign: "center", color: colors.slate500, fontSize: 13 }}>
              Loading readiness…
            </div>
          )}

          {isError && !isLoading && (
            <div style={{ padding: 16, background: "#FEF2F2", border: "1px solid #FECACA", color: "#B91C1C", borderRadius: 8, fontSize: 13 }}>
              Failed to load readiness for this gap.
            </div>
          )}

          {data && !isLoading && (
            <>
              {/* Top: score + identifiers */}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 16,
                  marginBottom: 20,
                  padding: 16,
                  borderRadius: 10,
                  background: colors.slate50,
                  border: `1px solid ${colors.slate200}`,
                }}
              >
                <ReadinessScoreBadge score={data.score} tier={tier} />
                <div style={{ fontSize: 12, color: colors.slate700 }}>
                  <div>
                    <span style={{ color: colors.slate500 }}>HCC&nbsp;</span>
                    <span style={{ fontFamily: "monospace", fontWeight: 700, color: colors.slate900 }}>
                      {data.hcc_code}
                    </span>
                    <span style={{ color: colors.slate500 }}>&nbsp;·&nbsp;ICD&nbsp;</span>
                    <span style={{ fontFamily: "monospace", color: colors.slate900 }}>
                      {data.icd10_code ?? "—"}
                    </span>
                  </div>
                  <div style={{ marginTop: 2, color: colors.slate500 }}>
                    Patient {String(data.patient_id)} · {data.current_year}
                  </div>
                </div>
              </div>

              {/* Component bars */}
              <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <ComponentBar
                  label="ICD on current problem list"
                  hint="Defensible chart support"
                  earned={data.score_breakdown.problem_list ?? 0}
                  max={30}
                  satisfied={data.components.problem_list}
                />
                <ComponentBar
                  label="Problem list updated < 90 days"
                  hint="Recently reaffirmed"
                  earned={data.score_breakdown.problem_list_recent ?? 0}
                  max={20}
                  satisfied={data.components.problem_list_recent}
                />
                <ComponentBar
                  label="Recent encounter < 90 days"
                  hint="Face-to-face contact"
                  earned={data.score_breakdown.recent_encounter ?? 0}
                  max={20}
                  satisfied={data.components.recent_encounter}
                />
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: 12, fontWeight: 600, color: colors.slate700 }}>
                      MEAT documentation
                    </span>
                    <span style={{ fontSize: 11, color: colors.slate500 }}>
                      · 10 points each, capped at 30
                    </span>
                    <span
                      style={{
                        marginLeft: "auto",
                        fontSize: 11,
                        fontWeight: 700,
                        color: colors.slate900,
                        fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, monospace",
                      }}
                    >
                      {data.score_breakdown.meat ?? 0} / 30
                    </span>
                  </div>
                  <MeatPills meat={data.components.meat} />
                </div>
              </div>

              {/* Recommended actions */}
              <div style={{ marginTop: 22 }}>
                <h3
                  style={{
                    margin: "0 0 10px",
                    fontSize: 12,
                    fontWeight: 700,
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    color: colors.slate500,
                  }}
                >
                  Recommended actions
                </h3>
                {data.recommended_actions.length === 0 ? (
                  <div
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 8,
                      padding: "8px 12px",
                      borderRadius: 8,
                      background: "#D1FAE5",
                      color: "#047857",
                      fontSize: 12,
                      fontWeight: 600,
                    }}
                  >
                    <CheckCircle2 size={14} /> Defensible — no further action needed
                  </div>
                ) : (
                  <ul
                    style={{
                      margin: 0,
                      padding: 0,
                      listStyle: "none",
                      display: "flex",
                      flexDirection: "column",
                      gap: 8,
                    }}
                  >
                    {data.recommended_actions.map((action) => (
                      <li
                        key={action}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 10,
                          padding: "10px 12px",
                          borderRadius: 8,
                          border: `1px solid ${colors.slate200}`,
                          background: colors.white,
                          fontSize: 13,
                          color: colors.slate900,
                        }}
                      >
                        <AlertCircle size={14} color={colors.amber500} />
                        <span>{action}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default ReadinessDetailModal;
