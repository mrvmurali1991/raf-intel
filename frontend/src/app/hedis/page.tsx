"use client";

/**
 * HEDIS + Stars — Health Equity Index (HEI) Disparity Dashboard
 *
 * Unique content: per-measure rates with HEI segmentation (dual, LIS,
 * disability, other), a disparity bar chart, and a per-measure patient gap
 * list with outreach actions.  The /quality page covers composite STARS
 * and care-gap management; this page covers HEI segmentation and equity gaps.
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
import {
  Star,
  AlertTriangle,
  Users,
  Activity,
  ExternalLink,
  Send,
  RefreshCw,
} from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { SectionHeader } from "@/components/ui/section-header";
import { MetricCard } from "@/components/ui/metric-card";
import {
  getHedisScores,
  getHedisScoresBySegment,
  getHedisPatientsFailing,
  type HedisMeasureScore,
  type HedisMeasureBySegment,
} from "@/lib/api";

const YEAR = new Date().getFullYear();

const SEGMENT_COLORS: Record<string, string> = {
  dual:       "#7c3aed", // purple — highest priority
  lis:        "#2563eb", // blue
  disability: "#ea580c", // orange
  other:      "#64748b", // slate
};

const SEGMENT_LABEL: Record<string, string> = {
  dual:       "Dual-Eligible",
  lis:        "LIS",
  disability: "Disability",
  other:      "Other",
};

function starsStr(n: number): string {
  if (!n || n < 1) return "—";
  return "★".repeat(Math.min(5, Math.max(1, Math.round(n))));
}

// ── Table style constants ────────────────────────────────────────────────────
const thCls = "text-left px-3 py-2 font-semibold text-xs text-muted-foreground border-b border-border";
const tdCls = "px-3 py-2 align-top";

// --------------------------------------------------------------------------
// Segmented bar chart — pure inline SVG, no chart-lib dependency
// --------------------------------------------------------------------------
function SegmentedBarChart({ data }: { data: HedisMeasureBySegment[] }) {
  if (!data?.length)
    return (
      <div className="flex items-center justify-center py-10 text-muted-foreground text-sm">
        No segment data available.
      </div>
    );

  const segments = ["dual", "lis", "disability", "other"] as const;
  const rowHeight = 64;
  const barAreaWidth = 720;
  const labelWidth = 120;
  const totalWidth = labelWidth + barAreaWidth + 100;
  const totalHeight = data.length * rowHeight + 60;

  return (
    <div className="overflow-x-auto">
      <svg
        width={totalWidth}
        height={totalHeight}
        role="img"
        aria-label="HEDIS rates by HEI segment"
      >
        {/* Legend */}
        <g transform="translate(120, 12)">
          {segments.map((seg, i) => (
            <g key={seg} transform={`translate(${i * 140}, 0)`}>
              <rect width={14} height={14} fill={SEGMENT_COLORS[seg]} />
              <text x={20} y={11} fontSize={12} fill="#334155">
                {SEGMENT_LABEL[seg]}
              </text>
            </g>
          ))}
        </g>
        {/* Rows */}
        {data.map((measure, rowIdx) => {
          const y = 48 + rowIdx * rowHeight;
          const segMap = new Map(measure.by_segment.map((s) => [s.segment, s]));
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
                        {SEGMENT_LABEL[seg]}: {rate.toFixed(1)}% (n=
                        {row?.denominator ?? 0})
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

  if (isLoading)
    return (
      <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
        <RefreshCw size={14} className="animate-spin" />
        Loading gap list…
      </div>
    );

  if (isError || !data)
    return (
      <div className="flex items-center gap-2 p-4 text-sm text-red-600">
        <AlertTriangle size={14} />
        Failed to load gap list
      </div>
    );

  if (data.total === 0)
    return (
      <div className="flex items-center gap-2 p-4 text-sm text-emerald-600">
        <span className="text-lg">✓</span>
        No gaps — all denominator patients met this measure.
      </div>
    );

  return (
    <div>
      <div className="mb-2 text-xs text-muted-foreground">
        {data.total} patients in denominator but NOT in numerator (showing{" "}
        {data.patients.length})
      </div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr className="bg-muted/50">
              <th className={thCls}>Patient</th>
              <th className={thCls}>DOB</th>
              <th className={thCls}>Sex</th>
              <th className={thCls}>HEI Segment</th>
              <th className={thCls}>Last Evidence</th>
              <th className={thCls}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {data.patients.map((p) => (
              <tr key={p.patient_id} className="border-t border-border hover:bg-muted/50 transition-colors">
                <td className={tdCls}>
                  {p.last_name ?? ""}, {p.first_name ?? ""}{" "}
                  <span className="text-muted-foreground">#{p.patient_id}</span>
                </td>
                <td className={tdCls}>{p.dob ?? "—"}</td>
                <td className={tdCls}>{p.sex ?? "—"}</td>
                <td className={tdCls}>
                  <span
                    className="px-2 py-0.5 rounded-full text-[11px] font-semibold"
                    style={{
                      background: SEGMENT_COLORS[p.hei_segment] + "22",
                      color: SEGMENT_COLORS[p.hei_segment],
                    }}
                  >
                    {SEGMENT_LABEL[p.hei_segment]}
                  </span>
                </td>
                <td className={`${tdCls} text-[11px] text-muted-foreground`}>
                  {p.evidence?.[0] ?? "—"}
                </td>
                <td className={tdCls}>
                  <Link
                    href={`/patients/${p.patient_id}`}
                    className="inline-flex items-center gap-1 text-blue-600 hover:underline mr-3 text-[12px]"
                  >
                    <ExternalLink size={12} /> Open chart
                  </Link>
                  <button
                    aria-label={`Send patient ${p.patient_id} to outreach for ${measureId}`}
                    className="inline-flex items-center gap-1 bg-transparent border border-border text-muted-foreground px-2 py-0.5 rounded text-[11px] cursor-pointer hover:bg-muted transition-colors"
                    onClick={() => {
                      // Stub: production wires this to /api/care-gaps or
                      // /api/recapture-outreach campaign create endpoint.
                      // eslint-disable-next-line no-console
                      console.log("send-to-outreach", {
                        measureId,
                        patient_id: p.patient_id,
                      });
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

  function refetchAll() {
    scoresQ.refetch();
    segQ.refetch();
  }

  return (
    <div className="min-h-screen bg-background p-4 sm:p-6 overflow-x-hidden max-w-[1400px] mx-auto">
      <PageHeader
        title="HEDIS + Stars — Health Equity"
        subtitle={`Measurement year ${YEAR} — quality measures with Health Equity Index (HEI) segmentation`}
        icon={<Star size={20} />}
        actions={
          <button
            onClick={refetchAll}
            disabled={scoresQ.isFetching || segQ.isFetching}
            aria-label="Refresh HEDIS scores and segment data"
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg border border-border bg-card text-muted-foreground text-[13px] font-medium cursor-pointer disabled:opacity-60 hover:text-foreground transition-colors"
          >
            <RefreshCw size={14} />
            Refresh
          </button>
        }
      />

      {/* ── Measure-level stat cards ── */}
      <SectionHeader
        title="Tenant-wide measure rates"
        icon={<Activity size={16} />}
      />

      {scoresQ.isLoading && (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <RefreshCw size={14} className="animate-spin" />
          Loading scores…
        </div>
      )}

      {scoresQ.isError && (
        <div className="flex items-center gap-2 p-4 rounded-lg border border-red-200 bg-red-50 text-red-600 text-sm mb-8">
          <AlertTriangle size={14} />
          Failed to load HEDIS scores
        </div>
      )}

      {!scoresQ.isLoading && !scoresQ.isError && (scoresQ.data?.measures ?? []).length === 0 && (
        <div className="flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 mb-8">
          <AlertTriangle size={16} className="flex-shrink-0 mt-0.5" />
          <div>
            <div className="font-semibold mb-0.5">No HEDIS measures available</div>
            <div className="text-xs text-muted-foreground">
              Verify the quality pipeline is running and measure data has been ingested for
              measurement year {YEAR}.
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 mb-8">
        {(scoresQ.data?.measures ?? []).map((m: HedisMeasureScore) => (
          <MetricCard
            key={m.measure_id}
            label={`${m.measure_id} · ${m.name.split("(")[0].trim()}`}
            value={`${m.rate_pct.toFixed(1)}%`}
            subtitle={`${starsStr(m.stars)} · n=${m.denominator}`}
            icon={<Star size={18} />}
            intent={m.rate_pct >= 80 ? "success" : m.rate_pct >= 60 ? "warning" : "danger"}
          />
        ))}
      </div>

      {/* ── Segmented bar chart ── */}
      <SectionHeader
        title="Disparity — HEDIS rates by CMS Health Equity Index segment"
        icon={<Users size={16} />}
      />
      <div className="bg-card border border-border rounded-lg p-4 mb-8">
        {segQ.isLoading && (
          <div className="flex items-center gap-2 py-6 text-sm text-muted-foreground">
            <RefreshCw size={14} className="animate-spin" />
            Loading segment data…
          </div>
        )}
        {segQ.isError && (
          <div className="flex items-center gap-2 p-4 text-red-600 text-sm">
            <AlertTriangle size={14} />
            Failed to load segment data
          </div>
        )}
        {segQ.data && <SegmentedBarChart data={segQ.data.measures} />}
        {segQ.data && (
          <div className="mt-3 text-[11px] text-muted-foreground">
            Segment population:{" "}
            {Object.entries(segQ.data.segment_population)
              .map(([k, v]) => `${SEGMENT_LABEL[k] ?? k}=${v}`)
              .join(" · ")}
          </div>
        )}
      </div>

      {/* ── Gap list ── */}
      <SectionHeader title="Gap list" icon={<AlertTriangle size={16} />} />

      {(scoresQ.data?.measures ?? []).length === 0 && !scoresQ.isLoading && (
        <div className="text-sm text-muted-foreground mb-4">
          No measures loaded — gap list unavailable.
        </div>
      )}

      <div className="flex gap-2 mb-4 flex-wrap">
        {(scoresQ.data?.measures ?? []).map((m) => (
          <button
            key={m.measure_id}
            onClick={() => setActiveMeasure(m.measure_id)}
            aria-label={`View gap list for ${m.measure_id} with ${m.denominator - m.numerator} gaps`}
            className={[
              "px-4 py-2 rounded-md text-[13px] font-semibold cursor-pointer transition-colors",
              activeMeasure === m.measure_id
                ? "border-2 border-primary bg-primary/10 text-foreground"
                : "border border-border bg-card text-muted-foreground hover:bg-muted",
            ].join(" ")}
          >
            {m.measure_id}{" "}
            <span className="font-normal text-muted-foreground">
              ({m.denominator - m.numerator} gaps)
            </span>
          </button>
        ))}
      </div>

      <div className="bg-card border border-border rounded-lg p-4 min-h-[200px]">
        {activeMeasure ? (
          <GapList measureId={activeMeasure} />
        ) : (
          <div className="flex items-center justify-center h-full min-h-[160px] text-muted-foreground text-sm">
            Select a measure above to view the patient gap list.
          </div>
        )}
      </div>

      <div className="mt-6 text-[11px] text-muted-foreground">
        HEDIS measure specifications &copy; NCQA. This MVP uses simplified
        deterministic logic for demo purposes; production deployment requires
        an NCQA license — see{" "}
        <a
          href="https://www.ncqa.org/hedis/measures/"
          target="_blank"
          rel="noopener noreferrer"
          className="underline hover:text-foreground"
        >
          ncqa.org/hedis/measures
        </a>
        .
      </div>
    </div>
  );
}
