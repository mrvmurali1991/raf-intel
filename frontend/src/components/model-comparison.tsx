"use client";

/**
 * ModelComparison — V24 / V28 side-by-side RAF model comparison panel.
 *
 * Usage:
 *   <ModelComparison pid="12345" />
 *
 * Data source: GET /api/raf/scores/{pid}/model-comparison
 *
 * Expected response shape (all fields optional/nullable):
 * {
 *   v24_score: number,
 *   v28_score: number,
 *   blended_score: number,
 *   hcc_comparison: Array<{
 *     hcc_code: string,
 *     description: string,
 *     v24_coefficient: number | null,
 *     v28_coefficient: number | null,
 *     in_v24: boolean,
 *     in_v28: boolean,
 *   }>,
 * }
 */

import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getModelComparison } from "@/lib/api";
import { SectionHeader, EmptyState } from "@/components/healthcare-ui";
import {
  GitCompareArrows,
  TrendingUp,
  TrendingDown,
  Minus,
  DollarSign,
  Calendar,
  BarChart3,
  AlertCircle,
  CheckCircle2,
  XCircle,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Design tokens (mirrors patient page C object)
// ---------------------------------------------------------------------------
const C = {
  bg: "#F8FAFC",
  white: "#FFFFFF",
  slate900: "#0F172A",
  slate800: "#1E293B",
  slate700: "#334155",
  slate600: "#475569",
  slate500: "#64748B",
  slate400: "#64748B",
  slate300: "#CBD5E1",
  slate200: "#E2E8F0",
  slate100: "#F1F5F9",
  blue700: "#1D4ED8",
  blue600: "#2563EB",
  blue500: "#3B82F6",
  blue100: "#DBEAFE",
  blue50: "#EFF6FF",
  emerald600: "#059669",
  emerald500: "#10B981",
  emerald100: "#D1FAE5",
  emerald50: "#ECFDF5",
  amber600: "#D97706",
  amber500: "#F59E0B",
  amber100: "#FEF3C7",
  amber50: "#FFFBEB",
  red600: "#DC2626",
  red500: "#EF4444",
  red100: "#FEE2E2",
  red50: "#FEF2F2",
  purple600: "#7C3AED",
  purple100: "#EDE9FE",
  purple50: "#F5F3FF",
  gray200: "#E5E7EB",
  gray400: "#9CA3AF",
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const BASE_RATE_PER_RAF_POINT = 12000; // $12,000 per RAF point annually

// Blend weights by payment year
const BLEND_SCHEDULE = [
  { year: "PY2024", v24Pct: 67, v28Pct: 33 },
  { year: "PY2025", v24Pct: 33, v28Pct: 67 },
  { year: "PY2026", v24Pct: 0, v28Pct: 100 },
] as const;

const CURRENT_PY = `PY${new Date().getFullYear()}`;

// ---------------------------------------------------------------------------
// Local helpers
// ---------------------------------------------------------------------------
function fmt$(n: number): string {
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "+";
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(1)}K`;
  return `${sign}$${Math.round(abs)}`;
}

function fmtScore(n: number | null | undefined): string {
  if (n == null) return "—";
  return Number(n).toFixed(3);
}

function deltaColor(delta: number): string {
  if (delta > 0.001) return C.emerald600;
  if (delta < -0.001) return C.red600;
  return C.slate500;
}

function blendedScore(v24: number, v28: number, v24Pct: number, v28Pct: number): number {
  return (v24 * v24Pct + v28 * v28Pct) / 100;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Segmented control for model view filter */
function ModelToggle({
  value,
  onChange,
}: {
  value: "blended" | "v24" | "v28";
  onChange: (v: "blended" | "v24" | "v28") => void;
}) {
  const options: { id: "blended" | "v24" | "v28"; label: string }[] = [
    { id: "blended", label: "Blended (Default)" },
    { id: "v24", label: "V24 Only" },
    { id: "v28", label: "V28 Only" },
  ];

  return (
    <div
      style={{
        display: "inline-flex",
        background: C.slate100,
        borderRadius: 10,
        padding: 3,
        gap: 2,
      }}
      role="tablist"
      aria-label="Model view selector"
    >
      {options.map((opt) => {
        const active = value === opt.id;
        return (
          <button
            key={opt.id}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(opt.id)}
            style={{
              padding: "7px 16px",
              borderRadius: 8,
              border: "none",
              fontSize: 13,
              fontWeight: active ? 600 : 500,
              color: active ? C.blue600 : C.slate500,
              background: active ? C.white : "transparent",
              boxShadow: active ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
              cursor: "pointer",
              transition: "all 0.15s",
              whiteSpace: "nowrap",
            }}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

/** Three-column score comparison with visual blend bar */
function ScoreComparisonCard({
  v24Score,
  v28Score,
  blendedScoreValue,
  activeView,
}: {
  v24Score: number | null;
  v28Score: number | null;
  blendedScoreValue: number | null;
  activeView: "blended" | "v24" | "v28";
}) {
  const delta = v24Score != null && v28Score != null ? v28Score - v24Score : null;
  const deltaPct =
    delta != null && v24Score != null && v24Score > 0
      ? (delta / v24Score) * 100
      : null;

  const revenueImpact =
    delta != null ? delta * BASE_RATE_PER_RAF_POINT : null;

  const currentBlend = BLEND_SCHEDULE.find((b) => b.year === CURRENT_PY)
    || { year: CURRENT_PY, v24Pct: 0, v28Pct: 100 };

  return (
    <div
      style={{
        background: C.white,
        border: `1px solid ${C.slate200}`,
        borderRadius: 12,
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div style={{ padding: "16px 20px 0" }}>
        <SectionHeader
          title="Score Comparison"
          icon={<BarChart3 size={18} />}
        />
      </div>

      {/* Score columns */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          borderTop: `1px solid ${C.slate100}`,
        }}
      >
        {[
          {
            model: "V24",
            score: v24Score,
            color: C.blue600,
            bg: C.blue50,
            border: C.blue100,
            active: activeView === "v24",
          },
          {
            model: "V28",
            score: v28Score,
            color: C.emerald600,
            bg: C.emerald50,
            border: C.emerald100,
            active: activeView === "v28",
          },
          {
            model: "Blended",
            score: blendedScoreValue,
            color: C.purple600,
            bg: C.purple50,
            border: C.purple100,
            active: activeView === "blended",
            sub: `${currentBlend.v24Pct}% V24 + ${currentBlend.v28Pct}% V28`,
          },
        ].map((col, idx) => (
          <div
            key={col.model}
            style={{
              padding: "20px 16px",
              borderLeft: idx > 0 ? `1px solid ${C.slate100}` : "none",
              background: col.active ? col.bg : C.white,
              transition: "background 0.15s",
            }}
          >
            <div
              style={{
                fontSize: 10,
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                color: col.active ? col.color : C.slate400,
                marginBottom: 8,
                display: "flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              <span
                style={{
                  display: "inline-block",
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: col.active ? col.color : C.slate300,
                }}
              />
              {col.model}
            </div>
            <div
              style={{
                fontSize: 28,
                fontWeight: 800,
                color: col.active ? col.color : C.slate800,
                fontFamily: "monospace",
                lineHeight: 1,
              }}
            >
              {fmtScore(col.score)}
            </div>
            {col.sub && (
              <div
                style={{
                  fontSize: 11,
                  color: C.slate400,
                  marginTop: 6,
                  lineHeight: 1.4,
                }}
              >
                {col.sub}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Blend proportion bar */}
      <div style={{ padding: "12px 20px", borderTop: `1px solid ${C.slate100}` }}>
        <div
          style={{
            fontSize: 11,
            color: C.slate400,
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.05em",
            marginBottom: 8,
          }}
        >
          {CURRENT_PY} Blend Weights
        </div>
        <div
          style={{
            display: "flex",
            height: 10,
            borderRadius: 5,
            overflow: "hidden",
            background: C.slate100,
          }}
          role="img"
          aria-label={`V24 ${currentBlend.v24Pct}%, V28 ${currentBlend.v28Pct}%`}
        >
          <div
            style={{
              width: `${currentBlend.v24Pct}%`,
              background: C.blue500,
              transition: "width 0.4s ease",
            }}
          />
          <div
            style={{
              width: `${currentBlend.v28Pct}%`,
              background: C.emerald500,
              transition: "width 0.4s ease",
            }}
          />
        </div>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            marginTop: 6,
            fontSize: 11,
            fontWeight: 600,
          }}
        >
          <span style={{ color: C.blue600 }}>{currentBlend.v24Pct}% V24</span>
          <span style={{ color: C.emerald600 }}>{currentBlend.v28Pct}% V28</span>
        </div>
      </div>

      {/* Delta summary row */}
      {delta != null && (
        <div
          style={{
            padding: "12px 20px",
            borderTop: `1px solid ${C.slate100}`,
            background:
              delta > 0.001
                ? C.emerald50
                : delta < -0.001
                  ? C.red50
                  : C.slate100,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: 8,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {delta > 0.001 ? (
              <TrendingUp size={16} color={C.emerald600} />
            ) : delta < -0.001 ? (
              <TrendingDown size={16} color={C.red600} />
            ) : (
              <Minus size={16} color={C.slate500} />
            )}
            <span
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: deltaColor(delta),
              }}
            >
              V28 vs V24:{" "}
              {delta > 0 ? "+" : ""}
              {delta.toFixed(3)}
              {deltaPct != null && (
                <span style={{ fontWeight: 400, marginLeft: 4 }}>
                  ({deltaPct > 0 ? "+" : ""}
                  {deltaPct.toFixed(1)}%)
                </span>
              )}
            </span>
          </div>
          {revenueImpact != null && (
            <span
              style={{
                fontSize: 13,
                fontWeight: 700,
                color: deltaColor(delta),
                display: "flex",
                alignItems: "center",
                gap: 4,
              }}
            >
              <DollarSign size={14} />
              {fmt$(revenueImpact)}/yr revenue impact
            </span>
          )}
        </div>
      )}
    </div>
  );
}

/** HCC comparison table with V24/V28 status columns */
function HCCComparisonTable({
  hccs,
  activeView,
}: {
  hccs: HCCRow[];
  activeView: "blended" | "v24" | "v28";
}) {
  const filtered =
    activeView === "v24"
      ? hccs.filter((h) => h.in_v24)
      : activeView === "v28"
        ? hccs.filter((h) => h.in_v28)
        : hccs;

  const addedInV28 = hccs.filter((h) => !h.in_v24 && h.in_v28).length;
  const removedInV28 = hccs.filter((h) => h.in_v24 && !h.in_v28).length;
  const inBoth = hccs.filter((h) => h.in_v24 && h.in_v28).length;

  return (
    <div
      style={{
        background: C.white,
        border: `1px solid ${C.slate200}`,
        borderRadius: 12,
        overflow: "hidden",
      }}
    >
      <div style={{ padding: "16px 20px" }}>
        <SectionHeader
          title="HCC Code Comparison"
          icon={<GitCompareArrows size={18} />}
          count={filtered.length}
        />

        {/* Legend chips */}
        <div
          style={{
            display: "flex",
            gap: 8,
            flexWrap: "wrap",
            marginBottom: 16,
          }}
        >
          {[
            { label: `${inBoth} in both`, color: C.slate600, bg: C.slate100 },
            {
              label: `${addedInV28} new in V28`,
              color: C.emerald600,
              bg: C.emerald100,
            },
            {
              label: `${removedInV28} removed in V28`,
              color: C.red600,
              bg: C.red100,
            },
          ].map((chip) => (
            <span
              key={chip.label}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                padding: "3px 10px",
                borderRadius: 999,
                fontSize: 11,
                fontWeight: 600,
                color: chip.color,
                background: chip.bg,
              }}
            >
              {chip.label}
            </span>
          ))}
        </div>
      </div>

      {filtered.length === 0 ? (
        <EmptyState
          icon={<GitCompareArrows size={24} />}
          title="No HCC codes found"
          description="No HCC conditions match this view filter."
        />
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: 13,
            }}
          >
            <thead>
              <tr
                style={{
                  background: C.slate100,
                  borderBottom: `1px solid ${C.slate200}`,
                }}
              >
                {[
                  "HCC Code",
                  "Description",
                  "V24 Status",
                  "V24 Coefficient",
                  "V28 Status",
                  "V28 Coefficient",
                  "Revenue Delta",
                ].map((h) => (
                  <th
                    key={h}
                    style={{
                      padding: "10px 16px",
                      textAlign: "left",
                      fontSize: 11,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                      color: C.slate500,
                      whiteSpace: "nowrap",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((row, idx) => {
                const isNewInV28 = !row.in_v24 && row.in_v28;
                const isRemovedInV28 = row.in_v24 && !row.in_v28;
                const coefDelta =
                  row.v24_coefficient != null && row.v28_coefficient != null
                    ? row.v28_coefficient - row.v24_coefficient
                    : null;
                const revDelta =
                  coefDelta != null
                    ? coefDelta * BASE_RATE_PER_RAF_POINT
                    : null;

                let rowBg = C.white;
                if (isNewInV28) rowBg = C.emerald50;
                else if (isRemovedInV28) rowBg = C.red50;

                return (
                  <tr
                    key={row.hcc_code}
                    style={{
                      background: rowBg,
                      borderBottom:
                        idx < filtered.length - 1
                          ? `1px solid ${C.slate100}`
                          : "none",
                    }}
                  >
                    {/* HCC Code */}
                    <td style={{ padding: "10px 16px", whiteSpace: "nowrap" }}>
                      <span
                        style={{
                          fontFamily: "monospace",
                          fontWeight: 700,
                          fontSize: 13,
                          color: C.blue600,
                          background: C.blue50,
                          padding: "2px 8px",
                          borderRadius: 4,
                        }}
                      >
                        {row.hcc_code}
                      </span>
                    </td>

                    {/* Description */}
                    <td
                      style={{
                        padding: "10px 16px",
                        color: C.slate700,
                        maxWidth: 280,
                      }}
                    >
                      <div
                        style={{
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                        title={row.description}
                      >
                        {row.description || "—"}
                      </div>
                    </td>

                    {/* V24 Status */}
                    <td style={{ padding: "10px 16px", whiteSpace: "nowrap" }}>
                      {row.in_v24 ? (
                        <span
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 4,
                            color: C.blue600,
                            fontSize: 12,
                            fontWeight: 600,
                          }}
                        >
                          <CheckCircle2 size={14} />
                          Active
                        </span>
                      ) : (
                        <span
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 4,
                            color: C.slate400,
                            fontSize: 12,
                          }}
                        >
                          <XCircle size={14} />
                          Not mapped
                        </span>
                      )}
                    </td>

                    {/* V24 Coefficient */}
                    <td
                      style={{
                        padding: "10px 16px",
                        fontFamily: "monospace",
                        color: row.v24_coefficient != null ? C.blue600 : C.slate300,
                        fontWeight: 600,
                        fontSize: 13,
                      }}
                    >
                      {row.v24_coefficient != null
                        ? row.v24_coefficient.toFixed(4)
                        : "—"}
                    </td>

                    {/* V28 Status */}
                    <td style={{ padding: "10px 16px", whiteSpace: "nowrap" }}>
                      {row.in_v28 ? (
                        <span
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 4,
                            color: isNewInV28 ? C.emerald600 : C.emerald600,
                            fontSize: 12,
                            fontWeight: 600,
                          }}
                        >
                          <CheckCircle2 size={14} />
                          {isNewInV28 ? "NEW in V28" : "Active"}
                        </span>
                      ) : (
                        <span
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 4,
                            color: isRemovedInV28 ? C.red600 : C.slate400,
                            fontSize: 12,
                            fontWeight: isRemovedInV28 ? 600 : 400,
                          }}
                        >
                          <XCircle size={14} />
                          {isRemovedInV28 ? "REMOVED" : "Not mapped"}
                        </span>
                      )}
                    </td>

                    {/* V28 Coefficient */}
                    <td
                      style={{
                        padding: "10px 16px",
                        fontFamily: "monospace",
                        color: row.v28_coefficient != null ? C.emerald600 : C.slate300,
                        fontWeight: 600,
                        fontSize: 13,
                      }}
                    >
                      {row.v28_coefficient != null
                        ? row.v28_coefficient.toFixed(4)
                        : "—"}
                    </td>

                    {/* Revenue Delta */}
                    <td
                      style={{
                        padding: "10px 16px",
                        whiteSpace: "nowrap",
                        fontWeight: 700,
                        fontSize: 13,
                        color:
                          revDelta == null
                            ? C.slate300
                            : revDelta > 0
                              ? C.emerald600
                              : revDelta < 0
                                ? C.red600
                                : C.slate500,
                      }}
                    >
                      {revDelta != null
                        ? `${revDelta > 0 ? "+" : ""}$${Math.round(Math.abs(revDelta)).toLocaleString()}`
                        : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** Transition timeline: PY2024 → PY2025 → PY2026 with RAF projections */
function TransitionTimeline({
  v24Score,
  v28Score,
}: {
  v24Score: number | null;
  v28Score: number | null;
}) {
  return (
    <div
      style={{
        background: C.white,
        border: `1px solid ${C.slate200}`,
        borderRadius: 12,
        padding: "16px 20px",
      }}
    >
      <SectionHeader title="V24 → V28 Transition Timeline" icon={<Calendar size={18} />} />

      <div style={{ position: "relative", paddingBottom: 8 }}>
        {/* Connector line */}
        <div
          style={{
            position: "absolute",
            top: 24,
            left: "calc(16.67% + 8px)",
            right: "calc(16.67% + 8px)",
            height: 2,
            background: `linear-gradient(90deg, ${C.blue500}, ${C.purple600}, ${C.emerald500})`,
            zIndex: 0,
          }}
          aria-hidden
        />

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 12,
            position: "relative",
            zIndex: 1,
          }}
        >
          {BLEND_SCHEDULE.map((entry) => {
            const isCurrent = entry.year === CURRENT_PY;
            const projected =
              v24Score != null && v28Score != null
                ? blendedScore(v24Score, v28Score, entry.v24Pct, entry.v28Pct)
                : null;

            const nodeColor = isCurrent ? C.blue600 : C.slate300;

            return (
              <div
                key={entry.year}
                style={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                {/* Node dot */}
                <div
                  style={{
                    width: 18,
                    height: 18,
                    borderRadius: "50%",
                    background: isCurrent ? C.blue600 : C.slate300,
                    border: `3px solid ${isCurrent ? C.blue100 : C.slate200}`,
                    boxShadow: isCurrent
                      ? `0 0 0 4px ${C.blue100}`
                      : "none",
                    transition: "all 0.2s",
                    flexShrink: 0,
                  }}
                  aria-label={isCurrent ? `${entry.year} (current)` : entry.year}
                />

                {/* Year label */}
                <div
                  style={{
                    fontSize: 13,
                    fontWeight: isCurrent ? 700 : 500,
                    color: isCurrent ? C.blue600 : C.slate500,
                    textAlign: "center",
                  }}
                >
                  {entry.year}
                  {isCurrent && (
                    <span
                      style={{
                        display: "block",
                        fontSize: 10,
                        fontWeight: 600,
                        color: C.blue500,
                        background: C.blue50,
                        padding: "1px 6px",
                        borderRadius: 4,
                        marginTop: 2,
                      }}
                    >
                      Current
                    </span>
                  )}
                </div>

                {/* Blend weights */}
                <div
                  style={{
                    display: "flex",
                    height: 6,
                    borderRadius: 3,
                    overflow: "hidden",
                    width: "100%",
                    maxWidth: 100,
                    background: C.slate100,
                  }}
                >
                  <div
                    style={{
                      width: `${entry.v24Pct}%`,
                      background: C.blue500,
                    }}
                  />
                  <div
                    style={{
                      width: `${entry.v28Pct}%`,
                      background: C.emerald500,
                    }}
                  />
                </div>

                <div style={{ fontSize: 11, color: C.slate400, textAlign: "center" }}>
                  <span style={{ color: C.blue600, fontWeight: 600 }}>{entry.v24Pct}%</span>
                  {" V24 / "}
                  <span style={{ color: C.emerald600, fontWeight: 600 }}>{entry.v28Pct}%</span>
                  {" V28"}
                </div>

                {/* Projected score */}
                <div
                  style={{
                    background: isCurrent ? C.blue50 : C.slate100,
                    border: `1px solid ${isCurrent ? C.blue100 : C.slate200}`,
                    borderRadius: 8,
                    padding: "8px 12px",
                    textAlign: "center",
                    width: "100%",
                  }}
                >
                  <div
                    style={{
                      fontSize: 10,
                      fontWeight: 600,
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                      color: isCurrent ? C.blue500 : C.slate400,
                      marginBottom: 4,
                    }}
                  >
                    Projected RAF
                  </div>
                  <div
                    style={{
                      fontSize: 20,
                      fontWeight: 800,
                      fontFamily: "monospace",
                      color: isCurrent ? C.blue700 : C.slate600,
                      lineHeight: 1,
                    }}
                  >
                    {projected != null ? projected.toFixed(3) : "—"}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/** Revenue impact summary banner */
function RevenueImpactSummary({
  v24Score,
  v28Score,
}: {
  v24Score: number | null;
  v28Score: number | null;
}) {
  if (v24Score == null || v28Score == null) return null;

  const delta = v28Score - v24Score;
  const annualImpact = delta * BASE_RATE_PER_RAF_POINT;
  const isPositive = annualImpact > 0;
  const isNeutral = Math.abs(annualImpact) < 50;

  const bg = isNeutral ? C.slate100 : isPositive ? C.emerald50 : C.red50;
  const border = isNeutral
    ? C.slate200
    : isPositive
      ? C.emerald100
      : C.red100;
  const color = isNeutral ? C.slate600 : isPositive ? C.emerald600 : C.red600;
  const Icon = isNeutral ? Minus : isPositive ? TrendingUp : TrendingDown;

  return (
    <div
      style={{
        background: bg,
        border: `1px solid ${border}`,
        borderRadius: 12,
        padding: "16px 20px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: 12,
      }}
      role="region"
      aria-label="Revenue impact summary"
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div
          style={{
            width: 40,
            height: 40,
            borderRadius: 10,
            background: isNeutral
              ? C.slate200
              : isPositive
                ? C.emerald100
                : C.red100,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color,
            flexShrink: 0,
          }}
        >
          <DollarSign size={20} />
        </div>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.slate800 }}>
            Revenue Impact Summary
          </div>
          <div style={{ fontSize: 13, color: C.slate500, marginTop: 2 }}>
            {isNeutral
              ? "Switching to V28 has minimal revenue impact for this patient."
              : `Switching to V28 changes annual revenue by `}
            {!isNeutral && (
              <strong style={{ color }}>
                ${Math.abs(annualImpact).toLocaleString("en-US", {
                  minimumFractionDigits: 0,
                  maximumFractionDigits: 0,
                })}{" "}
                per patient
              </strong>
            )}
            {!isNeutral && (isPositive ? " (increase)." : " (decrease).")}
          </div>
          <div
            style={{ fontSize: 11, color: C.slate400, marginTop: 4 }}
          >
            Based on ${BASE_RATE_PER_RAF_POINT.toLocaleString()} base rate per RAF point
          </div>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <Icon size={18} color={color} />
        <span
          style={{
            fontSize: 22,
            fontWeight: 800,
            color,
            fontFamily: "monospace",
          }}
        >
          {isPositive ? "+" : ""}$
          {Math.round(Math.abs(annualImpact)).toLocaleString("en-US")}
          /yr
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface HCCRow {
  hcc_code: string;
  description: string;
  v24_coefficient: number | null;
  v28_coefficient: number | null;
  in_v24: boolean;
  in_v28: boolean;
}

interface ModelComparisonData {
  v24_score: number | null;
  v28_score: number | null;
  blended_score: number | null;
  hcc_comparison: HCCRow[];
}

// ---------------------------------------------------------------------------
// Skeleton loader
// ---------------------------------------------------------------------------
function ComparisonSkeleton() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {[200, 280, 120, 60].map((h, i) => (
        <div
          key={i}
          style={{
            background: C.white,
            border: `1px solid ${C.slate200}`,
            borderRadius: 12,
            height: h,
            animation: "pulse 1.5s ease-in-out infinite",
          }}
        />
      ))}
      <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }`}</style>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Root export
// ---------------------------------------------------------------------------
export interface ModelComparisonProps {
  pid: string;
  year?: number;
}

export function ModelComparison({ pid, year }: ModelComparisonProps) {
  const [activeView, setActiveView] = useState<"blended" | "v24" | "v28">(
    "blended"
  );

  const { data, isLoading, isError, error } = useQuery<ModelComparisonData>({
    queryKey: ["model-comparison", pid, year],
    queryFn: () => getModelComparison(pid, year) as unknown as Promise<ModelComparisonData>,
    retry: 1,
  });

  // ── Loading ──
  if (isLoading) return <ComparisonSkeleton />;

  // ── Error ──
  if (isError || !data) {
    const message =
      (error as any)?.response?.data?.detail ||
      (error as any)?.message ||
      "Unable to load model comparison data.";
    return (
      <div
        style={{
          background: C.red50,
          border: `1px solid ${C.red100}`,
          borderRadius: 12,
          padding: "24px 20px",
          display: "flex",
          alignItems: "flex-start",
          gap: 12,
        }}
        role="alert"
      >
        <AlertCircle size={20} color={C.red600} style={{ flexShrink: 0, marginTop: 1 }} />
        <div>
          <div style={{ fontSize: 14, fontWeight: 600, color: C.red600, marginBottom: 4 }}>
            Model Comparison Unavailable
          </div>
          <div style={{ fontSize: 13, color: C.red600, opacity: 0.8 }}>
            {message}
          </div>
          <div style={{ fontSize: 12, color: C.slate500, marginTop: 8 }}>
            Ensure the backend endpoint{" "}
            <code
              style={{
                fontFamily: "monospace",
                background: C.red100,
                padding: "1px 5px",
                borderRadius: 3,
              }}
            >
              GET /api/raf/scores/{pid}/model-comparison
            </code>{" "}
            is implemented and returning data.
          </div>
        </div>
      </div>
    );
  }

  // Compute blended score locally as fallback
  const currentBlend = BLEND_SCHEDULE.find((b) => b.year === CURRENT_PY)
    || { year: CURRENT_PY, v24Pct: 0, v28Pct: 100 };
  const computedBlended =
    data.v24_score != null && data.v28_score != null
      ? blendedScore(
          data.v24_score,
          data.v28_score,
          currentBlend.v24Pct,
          currentBlend.v28Pct
        )
      : data.blended_score;

  const hccs: HCCRow[] = Array.isArray(data.hcc_comparison)
    ? data.hcc_comparison
    : [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Model toggle */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: C.slate800 }}>
            V24 / V28 Model Comparison
          </div>
          <div style={{ fontSize: 12, color: C.slate400, marginTop: 2 }}>
            CMS-HCC risk adjustment model transition analysis
          </div>
        </div>
        <ModelToggle value={activeView} onChange={setActiveView} />
      </div>

      {/* Score comparison */}
      <ScoreComparisonCard
        v24Score={data.v24_score}
        v28Score={data.v28_score}
        blendedScoreValue={computedBlended ?? null}
        activeView={activeView}
      />

      {/* Revenue impact banner */}
      <RevenueImpactSummary
        v24Score={data.v24_score}
        v28Score={data.v28_score}
      />

      {/* Transition timeline */}
      <TransitionTimeline v24Score={data.v24_score} v28Score={data.v28_score} />

      {/* HCC table */}
      <HCCComparisonTable hccs={hccs} activeView={activeView} />
    </div>
  );
}
