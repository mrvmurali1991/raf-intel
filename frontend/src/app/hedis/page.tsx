"use client";

/**
 * HEDIS / Star Ratings + Health Equity Index dashboard.
 *
 * Data sources
 *   GET /api/hedis/scores                  → top-strip per-measure rates + stars
 *   GET /api/hedis/scores/by-segment       → segmented disparity bar chart
 *   GET /api/hedis/patients-failing/{id}   → gap list, lazy-loaded on click
 *
 * Notes
 * - Star cutoffs come from the backend NCQA cut-points so we don't drift.
 * - "Open chart" links to /patients/{pid}; "Send to outreach" stubs a call.
 * - PHI audit (HEDIS_GAP_LIST_VIEWED) is emitted server-side every time
 *   patients-failing is fetched.
 */

import React, { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Star, AlertTriangle, Users, Activity, ExternalLink, Send } from "lucide-react";
import { PageHeader, StatCard, SectionHeader } from "@/components/healthcare-ui";
import {
  getHedisScores,
  getHedisScoresBySegment,
  getHedisPatientsFailing,
  type HedisMeasureScore,
  type HedisMeasureBySegment,
} from "@/lib/api";

const YEAR = new Date().getFullYear();

const SEGMENT_COLORS: Record<string, string> = {
  dual: "#7c3aed",       // purple — highest priority
  lis: "#2563eb",        // blue
  disability: "#ea580c", // orange
  other: "#64748b",      // slate
};

const SEGMENT_LABEL: Record<string, string> = {
  dual: "Dual-Eligible",
  lis: "LIS",
  disability: "Disability",
  other: "Other",
};

function starsStr(n: number): string {
  if (!n || n < 1) return "—";
  return "★".repeat(Math.min(5, Math.max(1, Math.round(n))));
}

// --------------------------------------------------------------------------
// Segmented bar chart — pure inline SVG, no chart-lib dependency
// --------------------------------------------------------------------------
function SegmentedBarChart({ data }: { data: HedisMeasureBySegment[] }) {
  if (!data?.length) return <div style={{ padding: 24, color: "#64748b" }}>No data</div>;
  const segments = ["dual", "lis", "disability", "other"] as const;
  const rowHeight = 64;
  const barAreaWidth = 720;
  const labelWidth = 120;
  const totalWidth = labelWidth + barAreaWidth + 100;
  const totalHeight = data.length * rowHeight + 60;
  return (
    <div style={{ overflowX: "auto" }}>
      <svg width={totalWidth} height={totalHeight} role="img" aria-label="HEDIS rates by HEI segment">
        {/* Legend */}
        <g transform="translate(120, 12)">
          {segments.map((seg, i) => (
            <g key={seg} transform={`translate(${i * 140}, 0)`}>
              <rect width={14} height={14} fill={SEGMENT_COLORS[seg]} />
              <text x={20} y={11} fontSize={12} fill="#334155">{SEGMENT_LABEL[seg]}</text>
            </g>
          ))}
        </g>
        {/* Rows */}
        {data.map((measure, rowIdx) => {
          const y = 48 + rowIdx * rowHeight;
          const segMap = new Map(measure.by_segment.map(s => [s.segment, s]));
          return (
            <g key={measure.measure_id} transform={`translate(0, ${y})`}>
              <text x={8} y={20} fontSize={13} fontWeight={600} fill="#0f172a">
                {measure.measure_id}
              </text>
              <text x={8} y={38} fontSize={11} fill="#64748b">
                gap {measure.disparity_gap_pct.toFixed(1)}%
              </text>
              {segments.map((seg, i) => {
                const row = segMap.get(seg);
                const rate = row?.rate_pct ?? 0;
                const w = (rate / 100) * (barAreaWidth / 4) * 0.92;
                const x = labelWidth + i * (barAreaWidth / 4);
                return (
                  <g key={seg}>
                    {/* Track */}
                    <rect
                      x={x}
                      y={8}
                      width={(barAreaWidth / 4) * 0.92}
                      height={32}
                      fill="#f1f5f9"
                      rx={4}
                    />
                    {/* Bar */}
                    <rect
                      x={x}
                      y={8}
                      width={w}
                      height={32}
                      fill={SEGMENT_COLORS[seg]}
                      rx={4}
                    >
                      <title>
                        {SEGMENT_LABEL[seg]}: {rate.toFixed(1)}% (n={row?.denominator ?? 0})
                      </title>
                    </rect>
                    <text x={x + 8} y={28} fontSize={12} fill="#fff" fontWeight={600}>
                      {rate.toFixed(0)}%
                    </text>
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// --------------------------------------------------------------------------
// Gap list — lazy fetched per measure
// --------------------------------------------------------------------------
function GapList({ measureId }: { measureId: string }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["hedis-failing", measureId, YEAR],
    queryFn: () => getHedisPatientsFailing(measureId, YEAR, 200, 0),
    staleTime: 60_000,
  });

  if (isLoading) return <div style={{ padding: 16, color: "#64748b" }}>Loading gap list…</div>;
  if (isError || !data) return <div style={{ padding: 16, color: "#dc2626" }}>Failed to load gap list</div>;

  if (data.total === 0) {
    return <div style={{ padding: 16, color: "#16a34a" }}>No gaps — all denominator patients met this measure.</div>;
  }

  return (
    <div>
      <div style={{ marginBottom: 8, fontSize: 13, color: "#64748b" }}>
        {data.total} patients in denominator but NOT in numerator (showing {data.patients.length})
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "#f8fafc" }}>
              <th style={th}>Patient</th>
              <th style={th}>DOB</th>
              <th style={th}>Sex</th>
              <th style={th}>HEI Segment</th>
              <th style={th}>Last Evidence</th>
              <th style={th}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {data.patients.map((p) => (
              <tr key={p.patient_id} style={{ borderTop: "1px solid #e2e8f0" }}>
                <td style={td}>
                  {p.last_name ?? ""}, {p.first_name ?? ""} <span style={{ color: "#94a3b8" }}>#{p.patient_id}</span>
                </td>
                <td style={td}>{p.dob ?? "—"}</td>
                <td style={td}>{p.sex ?? "—"}</td>
                <td style={td}>
                  <span
                    style={{
                      background: SEGMENT_COLORS[p.hei_segment] + "22",
                      color: SEGMENT_COLORS[p.hei_segment],
                      padding: "2px 8px",
                      borderRadius: 999,
                      fontSize: 11,
                      fontWeight: 600,
                    }}
                  >
                    {SEGMENT_LABEL[p.hei_segment]}
                  </span>
                </td>
                <td style={{ ...td, fontSize: 11, color: "#64748b" }}>
                  {p.evidence?.[0] ?? "—"}
                </td>
                <td style={td}>
                  <Link
                    href={`/patients/${p.patient_id}`}
                    style={{ marginRight: 12, color: "#2563eb", display: "inline-flex", alignItems: "center", gap: 4 }}
                  >
                    <ExternalLink size={12} /> Open chart
                  </Link>
                  <button
                    style={{
                      background: "transparent",
                      border: "1px solid #cbd5e1",
                      color: "#334155",
                      padding: "2px 8px",
                      borderRadius: 4,
                      fontSize: 11,
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                      cursor: "pointer",
                    }}
                    onClick={() => {
                      // Stub: production wires this to /api/care-gaps or
                      // /api/recapture-outreach campaign create endpoint.
                      // eslint-disable-next-line no-console
                      console.log("send-to-outreach", { measureId, patient_id: p.patient_id });
                    }}
                  >
                    <Send size={11} /> Send to outreach
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const th: React.CSSProperties = {
  textAlign: "left",
  padding: "8px 12px",
  fontWeight: 600,
  fontSize: 12,
  color: "#475569",
  borderBottom: "1px solid #cbd5e1",
};
const td: React.CSSProperties = { padding: "8px 12px", verticalAlign: "top" };

// --------------------------------------------------------------------------
// Page
// --------------------------------------------------------------------------
export default function HedisPage() {
  const [activeMeasure, setActiveMeasure] = useState<string | null>(null);

  const scoresQ = useQuery({
    queryKey: ["hedis-scores", YEAR],
    queryFn: () => getHedisScores(YEAR),
    staleTime: 60_000,
  });
  const segQ = useQuery({
    queryKey: ["hedis-by-segment", YEAR],
    queryFn: () => getHedisScoresBySegment(YEAR),
    staleTime: 60_000,
  });

  return (
    <div style={{ padding: 24, maxWidth: 1400, margin: "0 auto" }}>
      <PageHeader
        title="HEDIS + Stars"
        subtitle={`Measurement year ${YEAR} — quality measures with Health Equity Index segmentation`}
        icon={<Star size={20} />}
      />

      {/* Measure-level stat cards */}
      <SectionHeader title="Tenant-wide measure rates" icon={<Activity size={16} />} />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: 16,
          marginBottom: 32,
        }}
      >
        {(scoresQ.data?.measures ?? []).map((m: HedisMeasureScore) => (
          <StatCard
            key={m.measure_id}
            label={`${m.measure_id} · ${m.name.split("(")[0].trim()}`}
            value={`${m.rate_pct.toFixed(1)}%`}
            subtitle={`${starsStr(m.stars)} · n=${m.denominator}`}
            icon={<Star size={18} />}
          />
        ))}
        {scoresQ.isLoading && <div style={{ color: "#64748b" }}>Loading scores…</div>}
        {scoresQ.isError && (
          <div style={{ color: "#dc2626" }}>
            <AlertTriangle size={14} /> Failed to load HEDIS scores
          </div>
        )}
      </div>

      {/* Segmented bar chart */}
      <SectionHeader
        title="Disparity — HEDIS rates by CMS Health Equity Index segment"
        icon={<Users size={16} />}
      />
      <div
        style={{
          background: "#fff",
          border: "1px solid #e2e8f0",
          borderRadius: 8,
          padding: 16,
          marginBottom: 32,
        }}
      >
        {segQ.isLoading && <div style={{ color: "#64748b" }}>Loading segment data…</div>}
        {segQ.data && <SegmentedBarChart data={segQ.data.measures} />}
        {segQ.data && (
          <div style={{ fontSize: 11, color: "#64748b", marginTop: 12 }}>
            Segment population: {Object.entries(segQ.data.segment_population).map(([k, v]) => `${SEGMENT_LABEL[k] ?? k}=${v}`).join(" · ")}
          </div>
        )}
      </div>

      {/* Gap list */}
      <SectionHeader title="Gap list" icon={<AlertTriangle size={16} />} />
      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        {(scoresQ.data?.measures ?? []).map((m) => (
          <button
            key={m.measure_id}
            onClick={() => setActiveMeasure(m.measure_id)}
            style={{
              padding: "8px 16px",
              borderRadius: 6,
              border: activeMeasure === m.measure_id ? "2px solid #2563eb" : "1px solid #cbd5e1",
              background: activeMeasure === m.measure_id ? "#eff6ff" : "#fff",
              color: activeMeasure === m.measure_id ? "#1e3a8a" : "#334155",
              fontWeight: 600,
              fontSize: 13,
              cursor: "pointer",
            }}
          >
            {m.measure_id} <span style={{ fontWeight: 400, color: "#64748b" }}>({m.denominator - m.numerator} gaps)</span>
          </button>
        ))}
      </div>

      <div
        style={{
          background: "#fff",
          border: "1px solid #e2e8f0",
          borderRadius: 8,
          padding: 16,
          minHeight: 200,
        }}
      >
        {activeMeasure ? (
          <GapList measureId={activeMeasure} />
        ) : (
          <div style={{ color: "#64748b", padding: 32, textAlign: "center" }}>
            Select a measure above to view the patient gap list.
          </div>
        )}
      </div>

      <div style={{ marginTop: 24, fontSize: 11, color: "#94a3b8" }}>
        HEDIS measure specifications © NCQA. This MVP uses simplified
        deterministic logic for demo purposes; production deployment requires
        an NCQA license — see https://www.ncqa.org/hedis/measures/.
      </div>
    </div>
  );
}
