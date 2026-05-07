"use client";

/**
 * Quality Measures & STARS page
 *
 * Data sources (all real API calls via react-query):
 *   getQualitySummary()   → Summary tab KPIs
 *   getQualityMeasures()  → HEDIS Measures tab table
 *   getStarsEstimate()    → STARS Estimate tab gauge + breakdown
 *   getCareGaps()         → Care Gaps tab patient-level table
 *
 * Usage pattern mirrors /reports/page.tsx
 */

import React, { useState, useMemo } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Star,
  TrendingUp,
  TrendingDown,
  AlertCircle,
  AlertTriangle,
  CheckCircle,
  Activity,
  GitMerge,
  ChevronRight,
  ChevronDown,
  Download,
  Filter,
  RefreshCw,
  X,
} from "lucide-react";
import { StatCard, PageHeader, SectionHeader } from "@/components/healthcare-ui";
import { DataQualityBanner } from "@/components/DataQualityBanner";
import { tokens } from "@/styles/tokens";
import {
  getQualityMeasures,
  getQualitySummary,
  getStarsEstimate,
  getCareGaps,
} from "@/lib/api";
import type {
  QualityMeasure,
  QualitySummary,
  StarsEstimate,
  CareGap,
} from "@/lib/api";

// ── Design tokens (all sourced from tokens.ts — no hardcoded hex) ─────────────
const C = {
  bg:           tokens.slate50,
  card:         tokens.white,
  border:       tokens.slate200,
  borderLight:  tokens.slate100,
  text:         tokens.slate900,
  textMuted:    tokens.slate500,
  textSub:      tokens.slate400,
  primary:      tokens.primary,
  primaryLight: tokens.primarySoft,
  emerald:      tokens.success,
  emeraldLight: tokens.successSoft,
  emeraldDark:  tokens.successDark,
  amber:        tokens.warningStrong,
  amberLight:   tokens.warningSoft,
  amberDark:    tokens.warningText,
  red:          tokens.riskHigh,
  redLight:     tokens.riskHighSoft,
  redDark:      tokens.danger,
  blue:         tokens.infoBlue,
  violet:       tokens.accentPurple,
};

const T = {
  card: {
    background: C.card,
    border: `1px solid ${C.border}`,
    borderRadius: 12,
    boxShadow: "0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.02)",
    padding: 24,
  } as React.CSSProperties,
};

// ── Tabs ──────────────────────────────────────────────────────────────────────
const TABS = ["Summary", "HEDIS Measures", "STARS Estimate", "Care Gaps"] as const;
type TabKey = (typeof TABS)[number];

// ── Helper functions ──────────────────────────────────────────────────────────
function starsColor(s: number): string {
  if (s >= 4.5) return tokens.success;
  if (s >= 3.5) return tokens.infoBlue;
  if (s >= 2.5) return tokens.warningStrong;
  if (s >= 1.5) return tokens.riskMedium;
  return tokens.riskHigh;
}

function starsLabel(s: number): string {
  if (s >= 4.5) return "Excellent";
  if (s >= 3.5) return "Good";
  if (s >= 2.5) return "Average";
  if (s >= 1.5) return "Below Average";
  return "Poor";
}

function complianceColor(r: number): string {
  if (r >= 80) return C.emerald;
  if (r >= 60) return C.amber;
  return C.red;
}

function complianceBg(r: number): string {
  if (r >= 80) return C.emeraldLight;
  if (r >= 60) return C.amberLight;
  return C.redLight;
}

function complianceTextColor(r: number): string {
  if (r >= 80) return C.emeraldDark;
  if (r >= 60) return C.amberDark;
  return C.redDark;
}


function gapStatusStyle(status: CareGap["status"]): React.CSSProperties {
  if (status === "closed")
    return { background: C.emeraldLight, color: C.emeraldDark, padding: "2px 10px", borderRadius: 99, fontSize: 12, fontWeight: 600 };
  if (status === "excluded")
    return { background: C.amberLight, color: C.amberDark, padding: "2px 10px", borderRadius: 99, fontSize: 12, fontWeight: 600 };
  return { background: C.redLight, color: C.redDark, padding: "2px 10px", borderRadius: 99, fontSize: 12, fontWeight: 600 };
}

function renderStars(rating: number) {
  const full = Math.floor(rating);
  const half = rating % 1 >= 0.5;
  const empty = 5 - full - (half ? 1 : 0);
  const goldFill = tokens.warningStrong;
  const goldStroke = tokens.riskMedium;
  const emptyFill = tokens.slate200;
  const emptyStroke = tokens.slate300;
  return (
    <div style={{ display: "flex", gap: 3, alignItems: "center" }}>
      {Array.from({ length: full }).map((_, i) => (
        <span key={`f${i}`} className="qs-star-icon" style={{ display: "inline-flex", filter: "drop-shadow(0 1px 2px rgba(245,158,11,0.4))", animationDelay: `${i * 0.08}s` }}>
          <Star size={20} fill={goldFill} color={goldStroke} strokeWidth={1.5} />
        </span>
      ))}
      {half && (
        <span className="qs-star-icon" style={{ position: "relative", display: "inline-flex", filter: "drop-shadow(0 1px 2px rgba(245,158,11,0.25))" }}>
          <Star size={20} color={emptyStroke} fill={emptyFill} strokeWidth={1.5} />
          <span style={{ position: "absolute", left: 0, top: 0, width: "50%", overflow: "hidden", display: "inline-flex" }}>
            <Star size={20} fill={goldFill} color={goldStroke} strokeWidth={1.5} />
          </span>
        </span>
      )}
      {Array.from({ length: empty }).map((_, i) => (
        <span key={`e${i}`} className="qs-star-icon" style={{ display: "inline-flex", opacity: 0.5 }}>
          <Star size={20} color={emptyStroke} fill={emptyFill} strokeWidth={1.5} />
        </span>
      ))}
    </div>
  );
}

// ── Loading / Error / Empty states ────────────────────────────────────────────
function Spinner({ label }: { label?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "80px 0", color: C.textMuted }}>
      <div
        style={{
          width: 32,
          height: 32,
          border: `3px solid ${C.borderLight}`,
          borderTopColor: C.primary,
          borderRadius: "50%",
          animation: "qs-spin 0.8s linear infinite",
        }}
      />
      <p style={{ marginTop: 12, fontSize: 13 }}>{label ?? "Loading data..."}</p>
    </div>
  );
}

function ErrorBox({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "80px 0",
        color: C.red,
        gap: 12,
      }}
    >
      <AlertCircle size={32} />
      <p style={{ margin: 0, fontSize: 13 }}>{message ?? "Failed to load data."}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "8px 16px",
            border: `1px solid ${C.border}`,
            borderRadius: 8,
            background: C.card,
            color: C.textMuted,
            fontSize: 13,
            cursor: "pointer",
          }}
        >
          <RefreshCw size={14} />
          Retry
        </button>
      )}
    </div>
  );
}

function EmptyRow({ colSpan, message }: { colSpan: number; message?: string }) {
  return (
    <tr>
      <td
        colSpan={colSpan}
        style={{ padding: "48px 16px", textAlign: "center", color: C.textSub, fontSize: 14 }}
      >
        {message ?? "No data available."}
      </td>
    </tr>
  );
}

// ── STARS Gauge (SVG arc) ─────────────────────────────────────────────────────
function StarsGauge({ rating }: { rating: number }) {
  const size = 180;
  const strokeWidth = 14;
  const radius = (size - strokeWidth) / 2;
  const sweepAngle = 240;
  const startAngle = 150;
  const fraction = Math.min(rating / 5, 1);
  const color = starsColor(rating);

  function polarToCart(cx: number, cy: number, r: number, angleDeg: number) {
    const rad = ((angleDeg - 90) * Math.PI) / 180;
    return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
  }

  const cx = size / 2;
  const cy = size / 2;

  function describeArc(startDeg: number, endDeg: number) {
    const s = polarToCart(cx, cy, radius, startDeg);
    const e = polarToCart(cx, cy, radius, endDeg);
    const large = endDeg - startDeg > 180 ? 1 : 0;
    return `M ${s.x} ${s.y} A ${radius} ${radius} 0 ${large} 1 ${e.x} ${e.y}`;
  }

  const trackEnd = startAngle + sweepAngle;
  const fillEnd = startAngle + sweepAngle * fraction;

  return (
    <div style={{ position: "relative", width: size, height: size }}>
      <svg width={size} height={size}>
        <defs>
          <linearGradient id={`gaugeGrad-${rating}`} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={color} stopOpacity={0.7} />
            <stop offset="50%" stopColor={color} />
            <stop offset="100%" stopColor={color} stopOpacity={0.85} />
          </linearGradient>
          <filter id={`gaugeShadow-${rating}`}>
            <feDropShadow dx="0" dy="0" stdDeviation="3" floodColor={color} floodOpacity="0.35" />
          </filter>
        </defs>
        <path d={describeArc(startAngle, trackEnd)} fill="none" stroke={C.borderLight} strokeWidth={strokeWidth} strokeLinecap="round" opacity={0.5} />
        {fraction > 0 && (
          <path
            className="qs-gauge-path"
            d={describeArc(startAngle, fillEnd)}
            fill="none"
            stroke={`url(#gaugeGrad-${rating})`}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            filter={`url(#gaugeShadow-${rating})`}
            style={{ transition: "all 0.8s ease" }}
          />
        )}
      </svg>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          paddingTop: 16,
        }}
      >
        <div style={{ fontSize: 48, fontWeight: 800, color, lineHeight: 1, textShadow: `0 2px 12px ${color}40` }}>{(rating ?? 0).toFixed(1)}</div>
        <div style={{ fontSize: 13, fontWeight: 600, color, marginTop: 4, letterSpacing: "0.03em" }}>{starsLabel(rating)}</div>
        <div style={{ marginTop: 6 }}>{renderStars(rating)}</div>
      </div>
    </div>
  );
}

// ── HEDIS Measure row with expandable detail ──────────────────────────────────
function MeasureRow({ measure, index }: { measure: QualityMeasure; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const rate = measure.rate * 100; // API returns 0-1 fraction; display as percent
  const color = complianceColor(rate);
  const bg = complianceBg(rate);
  const tc = complianceTextColor(rate);
  const benchmark = measure.benchmark != null ? measure.benchmark * 100 : null;

  return (
    <>
      <tr
        className="qs-priority-card"
        style={{
          borderBottom: `1px solid ${C.borderLight}`,
          borderLeft: `3px solid ${color}`,
          cursor: "pointer",
          background: expanded ? tokens.slate50 : index % 2 === 0 ? C.card : tokens.slate50,
          transition: "background 0.15s ease",
        }}
        onClick={() => setExpanded(!expanded)}
      >
        {/* Measure ID */}
        <td style={{ padding: "12px 16px", verticalAlign: "middle" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {expanded ? <ChevronDown size={14} color={C.textSub} /> : <ChevronRight size={14} color={C.textSub} />}
            <span style={{ fontSize: 12, fontWeight: 700, color: C.primary, fontFamily: "monospace" }}>
              {measure.measure_id}
            </span>
          </div>
        </td>
        {/* Name */}
        <td style={{ padding: "12px 16px", verticalAlign: "middle" }}>
          <span style={{ fontSize: 13, fontWeight: 500, color: C.text }}>{measure.name}</span>
        </td>
        {/* Denominator (eligible) */}
        <td style={{ padding: "12px 16px", verticalAlign: "middle", textAlign: "center" }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{(measure.denominator ?? 0).toLocaleString()}</span>
        </td>
        {/* Numerator (compliant) */}
        <td style={{ padding: "12px 16px", verticalAlign: "middle", textAlign: "center" }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: C.emerald }}>{(measure.numerator ?? 0).toLocaleString()}</span>
        </td>
        {/* Compliance rate */}
        <td style={{ padding: "12px 16px", verticalAlign: "middle", minWidth: 160 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ flex: 1, height: 7, borderRadius: 4, background: C.borderLight, overflow: "hidden", boxShadow: "inset 0 1px 2px rgba(0,0,0,0.06)" }}>
              <div className="qs-progress-bar" style={{ height: "100%", width: `${Math.min(rate, 100)}%`, borderRadius: 4, background: `linear-gradient(90deg, ${color}CC, ${color})`, boxShadow: `0 1px 4px ${color}40`, transition: "width 0.6s cubic-bezier(0.22,1,0.36,1)" }} />
            </div>
            <span
              style={{
                fontSize: 12,
                fontWeight: 700,
                padding: "2px 8px",
                borderRadius: 999,
                background: bg,
                color: tc,
                minWidth: 44,
                textAlign: "center",
              }}
            >
              {(rate ?? 0).toFixed(1)}%
            </span>
          </div>
        </td>
        {/* Benchmark */}
        <td style={{ padding: "12px 16px", verticalAlign: "middle", textAlign: "center" }}>
          {benchmark != null ? (
            <span style={{ fontSize: 13, color: C.textMuted }}>{(benchmark ?? 0).toFixed(1)}%</span>
          ) : (
            <span style={{ fontSize: 11, color: C.textSub }}>—</span>
          )}
        </td>
        {/* Gap */}
        <td style={{ padding: "12px 16px", verticalAlign: "middle", textAlign: "center" }}>
          {measure.gap > 0 ? (
            <span style={{ fontSize: 12, fontWeight: 700, padding: "2px 10px", borderRadius: 999, background: C.redLight, color: C.redDark }}>
              {measure.gap.toLocaleString()}
            </span>
          ) : (
            <CheckCircle size={16} color={C.emerald} />
          )}
        </td>
      </tr>

      {/* Expanded: show benchmark comparison detail */}
      {expanded && (
        <tr className="qs-card-enter" style={{ background: `linear-gradient(135deg, ${tokens.primarySoft} 0%, ${tokens.primarySoft} 100%)` }}>
          <td colSpan={7} style={{ padding: "16px 20px 20px 48px", borderLeft: `3px solid ${color}` }}>
            <div style={{ display: "flex", gap: 36, flexWrap: "wrap" }}>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                  Compliance Rate
                </div>
                <div style={{ fontSize: 22, fontWeight: 800, color }}>
                  {(rate ?? 0).toFixed(1)}%
                </div>
              </div>
              {benchmark != null && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 700, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                    Benchmark
                  </div>
                  <div style={{ fontSize: 22, fontWeight: 800, color: C.textMuted }}>
                    {(benchmark ?? 0).toFixed(1)}%
                  </div>
                </div>
              )}
              {benchmark != null && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 700, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                    vs Benchmark
                  </div>
                  <div
                    style={{
                      fontSize: 22,
                      fontWeight: 800,
                      color: rate >= benchmark ? C.emerald : C.red,
                    }}
                  >
                    {rate >= benchmark ? "+" : ""}
                    {((rate ?? 0) - (benchmark ?? 0)).toFixed(1)}%
                  </div>
                </div>
              )}
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                  Open Gaps
                </div>
                <div style={{ fontSize: 22, fontWeight: 800, color: measure.gap > 0 ? C.red : C.emerald }}>
                  {measure.gap.toLocaleString()}
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ── Summary Tab ───────────────────────────────────────────────────────────────
function SummaryTab({
  summary,
  measures,
}: {
  summary: QualitySummary;
  measures: QualityMeasure[];
}) {
  const aboveBenchmarkPct =
    summary.total_measures > 0
      ? Math.round((summary.measures_above_benchmark / summary.total_measures) * 100)
      : 0;

  const green = measures.filter((m) => m.rate * 100 >= 80).length;
  const amber = measures.filter((m) => m.rate * 100 >= 60 && m.rate * 100 < 80).length;
  const red = measures.filter((m) => m.rate * 100 < 60).length;
  const total = measures.length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* KPI strip */}
      <div
        className="qs-kpi-strip qs-fade-in"
        style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 18 }}
      >
        <StatCard
          label="Total Measures"
          value={summary.total_measures}
          subtitle={`Measurement year ${summary.year}`}
          icon={<Activity size={20} />}
          color={C.blue}
        />
        <StatCard
          label="Above Benchmark"
          value={`${summary.measures_above_benchmark} / ${summary.total_measures}`}
          subtitle={`${aboveBenchmarkPct}% of tracked measures`}
          icon={<CheckCircle size={20} />}
          color={aboveBenchmarkPct >= 50 ? C.emerald : C.amber}
        />
        <StatCard
          label="Composite Score"
          value={`${((summary.composite_score ?? 0) * 100).toFixed(1)}%`}
          subtitle="Population-weighted avg"
          icon={<GitMerge size={20} />}
          color={C.violet}
        />
        <StatCard
          label="STARS Estimate"
          value={(summary.stars_estimate ?? 0).toFixed(1)}
          subtitle={starsLabel(summary.stars_estimate ?? 0)}
          icon={<Star size={20} />}
          color={starsColor(summary.stars_estimate ?? 0)}
        />
      </div>

      {/* Compliance distribution bar */}
      {total > 0 && (
        <div className="premium-card premium-shadow hover-lift qs-fade-in qs-fade-in-1" style={{ ...T.card, borderRadius: 14 }}>
          <SectionHeader title="Compliance Rate Distribution" icon={<Activity size={18} />} />
          <div style={{ display: "flex", gap: 0, borderRadius: 10, overflow: "hidden", height: 32, marginBottom: 14, boxShadow: "inset 0 1px 3px rgba(0,0,0,0.08)" }}>
            {[
              { pct: (green / total) * 100, color: C.emerald },
              { pct: (amber / total) * 100, color: C.amber },
              { pct: (red / total) * 100, color: C.red },
            ].map((seg, i) => (
              <div
                key={i}
                style={{
                  width: `${seg.pct}%`,
                  background: seg.color,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 11,
                  fontWeight: 700,
                  color: tokens.white,
                  minWidth: seg.pct > 0 ? 30 : 0,
                }}
              >
                {seg.pct > 8 ? `${Math.round(seg.pct)}%` : ""}
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
            {[
              { label: "Meeting target (≥80%)", color: C.emerald, count: green },
              { label: "Near target (60–80%)", color: C.amber, count: amber },
              { label: "Below target (<60%)", color: C.red, count: red },
            ].map((leg) => (
              <div key={leg.label} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: C.textMuted }}>
                <div style={{ width: 10, height: 10, borderRadius: 2, background: leg.color }} />
                <span>
                  <strong style={{ color: C.text }}>{leg.count}</strong> {leg.label}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── HEDIS Measures Tab ────────────────────────────────────────────────────────
function MeasuresTab({ measures }: { measures: QualityMeasure[] }) {
  const [measureFilter, setMeasureFilter] = useState("");

  const filtered = useMemo(
    () =>
      measures.filter(
        (m) =>
          m.name.toLowerCase().includes(measureFilter.toLowerCase()) ||
          m.measure_id.toLowerCase().includes(measureFilter.toLowerCase()),
      ),
    [measures, measureFilter],
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Filter bar */}
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ position: "relative", flex: "1 1 240px", maxWidth: 320 }}>
          <Filter
            size={14}
            style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: C.textSub }}
          />
          <input
            type="text"
            placeholder="Search measures..."
            value={measureFilter}
            onChange={(e) => setMeasureFilter(e.target.value)}
            style={{
              width: "100%",
              paddingLeft: 34,
              paddingRight: 12,
              paddingTop: 8,
              paddingBottom: 8,
              border: `1px solid ${C.border}`,
              borderRadius: 8,
              fontSize: 13,
              background: C.card,
              color: C.text,
              outline: "none",
              boxSizing: "border-box",
            }}
          />
        </div>
        <div style={{ marginLeft: "auto", fontSize: 12, color: C.textSub }}>
          Showing {filtered.length} of {measures.length} measures
        </div>
      </div>

      {/* Measures table */}
      <div className="premium-card premium-shadow qs-fade-in qs-fade-in-1" style={{ ...T.card, padding: 0, overflow: "hidden", borderRadius: 14 }}>
        <div style={{ overflowX: "auto" }}>
          <table className="qs-measure-table" style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {["Measure ID", "Measure Name", "Eligible", "Compliant", "Rate", "Benchmark", "Gap"].map((h) => (
                  <th
                    key={h}
                    style={{
                      padding: "12px 16px",
                      fontSize: 11,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                      color: C.textMuted,
                      textAlign: ["Eligible", "Compliant", "Gap", "Benchmark"].includes(h) ? "center" : "left",
                      borderBottom: `1px solid ${C.border}`,
                      background: tokens.slate50,
                      whiteSpace: "nowrap",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <EmptyRow colSpan={7} message="No measures match the search." />
              ) : (
                filtered.map((m, i) => <MeasureRow key={`${m.measure_id}-${i}`} measure={m} index={i} />)
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ── STARS Estimate Tab ────────────────────────────────────────────────────────
function StarsTab({ stars }: { stars: StarsEstimate }) {
  const diff = stars.projected_estimate - stars.current_estimate;
  const diffUp = diff >= 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Top row: current + projected gauges */}
      <div
        className="qs-stars-top"
        style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}
      >
        {/* Current */}
        <div
          className="premium-shadow mesh-pattern qs-fade-in qs-fade-in-1"
          style={{
            ...T.card,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            background: `linear-gradient(135deg, ${tokens.slate900} 0%, ${tokens.slate800} 50%, ${tokens.slate900} 100%)`,
            border: "1px solid rgba(255,255,255,0.06)",
            borderRadius: 16,
          }}
        >
          <div style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: tokens.slate400, marginBottom: 16 }}>
            Current STARS Estimate — {stars.year}
          </div>
          <StarsGauge rating={stars.current_estimate} />
          <div style={{ marginTop: 10, fontSize: 13, color: tokens.slate500 }}>
            {renderStars(stars.current_estimate)}
          </div>
        </div>

        {/* Projected */}
        <div
          className="premium-shadow mesh-pattern qs-fade-in qs-fade-in-2"
          style={{
            ...T.card,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            background: `linear-gradient(135deg, ${tokens.primaryDark} 0%, ${tokens.primary} 50%, ${tokens.primaryDark} 100%)`,
            border: "1px solid rgba(255,255,255,0.08)",
            borderRadius: 16,
          }}
        >
          <div style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: tokens.slate200, marginBottom: 16 }}>
            Projected STARS Estimate
          </div>
          <StarsGauge rating={stars.projected_estimate} />
          <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 8, fontSize: 13, color: tokens.slate200 }}>
            {diffUp ? <TrendingUp size={16} color={tokens.success} /> : <TrendingDown size={16} color={tokens.riskHigh} />}
            <span style={{ color: diffUp ? tokens.success : tokens.riskHigh, fontWeight: 700 }}>
              {diffUp ? "+" : ""}{(diff ?? 0).toFixed(2)} projected change
            </span>
          </div>
        </div>
      </div>

      {/* Measure breakdown */}
      {stars.measure_breakdown.length > 0 && (
        <div className="premium-card premium-shadow hover-lift qs-fade-in qs-fade-in-3" style={{ ...T.card, borderRadius: 14 }}>
          <SectionHeader title="Measure Breakdown" icon={<Star size={18} />} />
          <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 8 }}>
            {stars.measure_breakdown.map((mb) => {
              const barColor = starsColor(mb.stars);
              return (
                <div key={mb.measure_id} style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <div style={{ width: 90, fontSize: 12, fontWeight: 700, color: C.primary, fontFamily: "monospace", flexShrink: 0 }}>
                    {mb.measure_id}
                  </div>
                  <div style={{ flex: 1, height: 8, borderRadius: 4, background: C.borderLight, overflow: "hidden", boxShadow: "inset 0 1px 2px rgba(0,0,0,0.06)" }}>
                    <div
                      className="qs-progress-bar"
                      style={{
                        height: "100%",
                        width: `${(mb.stars / 5) * 100}%`,
                        background: `linear-gradient(90deg, ${barColor}CC, ${barColor})`,
                        borderRadius: 4,
                        boxShadow: `0 1px 4px ${barColor}40`,
                        transition: "width 0.6s cubic-bezier(0.22,1,0.36,1)",
                      }}
                    />
                  </div>
                  <div style={{ minWidth: 36, textAlign: "right", fontSize: 13, fontWeight: 700, color: barColor }}>
                    {(mb.stars ?? 0).toFixed(1)}
                  </div>
                  <div style={{ minWidth: 48, textAlign: "right", fontSize: 11, color: C.textSub }}>
                    wt {(mb.weight ?? 0).toFixed(2)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Care Gaps Tab ─────────────────────────────────────────────────────────────
function CareGapsTab({ gaps, total }: { gaps: CareGap[]; total: number }) {
  const [statusFilter, setStatusFilter] = useState<"all" | "open" | "closed" | "excluded">("all");
  const [measureFilter, setMeasureFilter] = useState("all");

  const measureIds = useMemo(() => {
    const ids = Array.from(new Set(gaps.map((g) => g.measure_id)));
    return ids.sort();
  }, [gaps]);

  const filtered = useMemo(() => {
    return gaps.filter((g) => {
      const matchStatus = statusFilter === "all" || g.status === statusFilter;
      const matchMeasure = measureFilter === "all" || g.measure_id === measureFilter;
      return matchStatus && matchMeasure;
    });
  }, [gaps, statusFilter, measureFilter]);

  function handleExport() {
    const rows = [
      ["Gap ID", "Patient ID", "Patient Name", "Measure ID", "Measure Name", "Due Date", "Status"],
      ...filtered.map((g) => [g.gap_id, g.pid, g.patient_name, g.measure_id, g.measure_name, g.due_date ?? "", g.status]),
    ];
    const csv = rows.map((r) => r.map(String).map((v) => `"${v}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "care_gaps.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Filter bar */}
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        {/* Status filter */}
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}
          style={{ padding: "8px 12px", border: `1px solid ${C.border}`, borderRadius: 8, fontSize: 13, background: C.card, color: C.text, cursor: "pointer" }}
        >
          <option value="all">All Statuses</option>
          <option value="open">Open</option>
          <option value="closed">Closed</option>
          <option value="excluded">Excluded</option>
        </select>

        {/* Measure filter */}
        <select
          value={measureFilter}
          onChange={(e) => setMeasureFilter(e.target.value)}
          style={{ padding: "8px 12px", border: `1px solid ${C.border}`, borderRadius: 8, fontSize: 13, background: C.card, color: C.text, cursor: "pointer" }}
        >
          <option value="all">All Measures</option>
          {measureIds.map((id) => (
            <option key={id} value={id}>{id}</option>
          ))}
        </select>

        {/* Clear filters */}
        <button
          onClick={() => { setStatusFilter("all"); setMeasureFilter("all"); }}
          style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "8px 14px", border: `1px solid ${C.border}`, borderRadius: 8, background: C.card, color: C.textMuted, fontSize: 13, cursor: "pointer" }}
        >
          <X size={14} />
          Clear
        </button>

        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 12, color: C.textSub }}>
            {filtered.length} of {total.toLocaleString()} gaps
          </span>
          <button
            onClick={handleExport}
            style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "8px 16px", border: `1px solid ${C.border}`, borderRadius: 8, background: C.card, color: C.textMuted, fontSize: 13, fontWeight: 500, cursor: "pointer" }}
          >
            <Download size={14} />
            Export CSV
          </button>
        </div>
      </div>

      {/* Gaps table */}
      <div className="premium-card premium-shadow qs-fade-in qs-fade-in-1" style={{ ...T.card, padding: 0, overflow: "hidden", borderRadius: 14 }}>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {["Patient", "Measure", "Measure Name", "Due Date", "Status", "Actions"].map((h) => (
                  <th
                    key={h}
                    style={{
                      padding: "12px 16px",
                      fontSize: 11,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                      color: C.textMuted,
                      textAlign: "left",
                      background: tokens.slate50,
                      borderBottom: `1px solid ${C.border}`,
                      whiteSpace: "nowrap",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <EmptyRow colSpan={6} message="No care gaps match the selected filters." />
              ) : (
                filtered.map((gap, idx) => (
                  <tr
                    key={gap.gap_id}
                    style={{
                      borderBottom: `1px solid ${C.borderLight}`,
                      background: idx % 2 === 0 ? C.card : tokens.slate50,
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = tokens.primarySoft)}
                    onMouseLeave={(e) => (e.currentTarget.style.background = idx % 2 === 0 ? C.card : tokens.slate50)}
                  >
                    {/* Patient */}
                    <td style={{ padding: "12px 16px", verticalAlign: "middle" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div
                          style={{
                            width: 32,
                            height: 32,
                            borderRadius: "50%",
                            background: C.primary,
                            color: "#FFF",
                            fontSize: 12,
                            fontWeight: 700,
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            flexShrink: 0,
                          }}
                        >
                          {gap.patient_name
                            .split(/[\s,]+/)
                            .filter(Boolean)
                            .slice(0, 2)
                            .map((w) => w[0]?.toUpperCase() ?? "")
                            .join("")}
                        </div>
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{gap.patient_name}</div>
                          <div style={{ fontSize: 11, color: C.textSub }}>PID {gap.pid}</div>
                        </div>
                      </div>
                    </td>
                    {/* Measure ID */}
                    <td style={{ padding: "12px 16px", verticalAlign: "middle" }}>
                      <span style={{ fontSize: 12, fontWeight: 700, color: C.primary, fontFamily: "monospace" }}>
                        {gap.measure_id}
                      </span>
                    </td>
                    {/* Measure Name */}
                    <td style={{ padding: "12px 16px", verticalAlign: "middle" }}>
                      <span style={{ fontSize: 13, color: C.text }}>{gap.measure_name}</span>
                    </td>
                    {/* Due date */}
                    <td style={{ padding: "12px 16px", verticalAlign: "middle" }}>
                      {gap.due_date ? (
                        <span style={{ fontSize: 13, color: C.textMuted }}>{gap.due_date}</span>
                      ) : (
                        <span style={{ fontSize: 11, color: C.textSub }}>—</span>
                      )}
                    </td>
                    {/* Status badge */}
                    <td style={{ padding: "12px 16px", verticalAlign: "middle" }}>
                      <span style={gapStatusStyle(gap.status)}>
                        {gap.status.charAt(0).toUpperCase() + gap.status.slice(1)}
                      </span>
                    </td>
                    {/* Actions */}
                    <td style={{ padding: "12px 16px", verticalAlign: "middle" }}>
                      <Link
                        href={`/patients/${gap.pid}`}
                        className="hover-lift"
                        style={{
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 4,
                          fontSize: 12,
                          fontWeight: 600,
                          color: C.primary,
                          textDecoration: "none",
                          padding: "6px 14px",
                          borderRadius: 8,
                          border: `1px solid ${C.primaryLight}`,
                          background: `linear-gradient(135deg, ${tokens.primarySoft}, ${tokens.primarySoft})`,
                        }}
                      >
                        View Patient <ChevronRight size={13} />
                      </Link>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// PAGE COMPONENT
// ══════════════════════════════════════════════════════════════════════════════
export default function QualityPage() {
  const [activeTab, setActiveTab] = useState<TabKey>("Summary");

  // ── Data queries ─────────────────────────────────────────────────────────
  const summaryQ = useQuery({
    queryKey: ["quality-summary"],
    queryFn: () => getQualitySummary(),
  });

  const measuresQ = useQuery({
    queryKey: ["quality-measures"],
    queryFn: () => getQualityMeasures(),
  });

  const starsQ = useQuery({
    queryKey: ["quality-stars"],
    queryFn: () => getStarsEstimate(),
  });

  const gapsQ = useQuery({
    queryKey: ["quality-gaps"],
    queryFn: () => getCareGaps({ limit: 500 }),
  });

  // ── Derived values for the top header gauge ───────────────────────────────
  const currentStars = starsQ.data?.current_estimate ?? summaryQ.data?.stars_estimate ?? 0;
  const projectedStars = starsQ.data?.projected_estimate ?? currentStars;
  const diff = projectedStars - currentStars;
  const diffUp = diff >= 0;

  function refetchAll() {
    summaryQ.refetch();
    measuresQ.refetch();
    starsQ.refetch();
    gapsQ.refetch();
  }

  // ── Render the active tab content ─────────────────────────────────────────
  function renderTabContent() {
    if (activeTab === "Summary") {
      if (summaryQ.isLoading || measuresQ.isLoading)
        return <Spinner label="Loading quality summary..." />;
      if (summaryQ.isError)
        return <ErrorBox message="Failed to load quality summary." onRetry={() => summaryQ.refetch()} />;
      if (!summaryQ.data) return <ErrorBox message="No summary data available." />;
      return (
        <SummaryTab summary={summaryQ.data} measures={measuresQ.data ?? []} />
      );
    }

    if (activeTab === "HEDIS Measures") {
      if (measuresQ.isLoading) return <Spinner label="Loading HEDIS measures..." />;
      if (measuresQ.isError)
        return <ErrorBox message="Failed to load measures." onRetry={() => measuresQ.refetch()} />;
      const measures = measuresQ.data ?? [];
      if (measures.length === 0)
        return (
          <div
            role="status"
            style={{
              margin: "0 0 16px",
              padding: "16px 20px",
              borderRadius: 10,
              background: tokens.warningSoft,
              border: `1px solid ${tokens.warningBorder}`,
              color: tokens.warningText,
              display: "flex",
              alignItems: "flex-start",
              gap: 12,
              fontSize: 13,
            }}
          >
            <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: 1 }} />
            <div>
              <div style={{ fontWeight: 600, marginBottom: 2 }}>No HEDIS measures available — this is unusual</div>
              <div style={{ fontSize: 12 }}>
                STARS ratings depend on HEDIS measure data. Verify the quality pipeline is running
                and that measure data has been ingested for this plan year.
              </div>
            </div>
          </div>
        );
      return <MeasuresTab measures={measures} />;
    }

    if (activeTab === "STARS Estimate") {
      if (starsQ.isLoading) return <Spinner label="Loading STARS estimate..." />;
      if (starsQ.isError)
        return <ErrorBox message="Failed to load STARS estimate." onRetry={() => starsQ.refetch()} />;
      if (!starsQ.data)
        return (
          <div
            role="status"
            style={{
              margin: "0 0 16px",
              padding: "16px 20px",
              borderRadius: 10,
              background: tokens.warningSoft,
              border: `1px solid ${tokens.warningBorder}`,
              color: tokens.warningText,
              display: "flex",
              alignItems: "flex-start",
              gap: 12,
              fontSize: 13,
            }}
          >
            <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: 1 }} />
            <div>
              <div style={{ fontWeight: 600, marginBottom: 2 }}>No STARS data available — this is unusual</div>
              <div style={{ fontSize: 12 }}>
                STARS estimates are required for CMS bonus payments and quality bonuses.
                Verify STARS calculation pipeline is configured.
              </div>
            </div>
          </div>
        );
      return <StarsTab stars={starsQ.data} />;
    }

    if (activeTab === "Care Gaps") {
      if (gapsQ.isLoading) return <Spinner label="Loading care gaps..." />;
      if (gapsQ.isError)
        return <ErrorBox message="Failed to load care gaps." onRetry={() => gapsQ.refetch()} />;
      return (
        <CareGapsTab
          gaps={gapsQ.data?.gaps ?? []}
          total={gapsQ.data?.total ?? 0}
        />
      );
    }

    return null;
  }

  return (
    <div style={{ background: C.bg, minHeight: "100vh", padding: "36px 44px", overflowX: "hidden" }} className="rci-page-pad-desktop">
      <style>{`
        @keyframes qs-spin { to { transform: rotate(360deg) } }
        @keyframes qs-fadeInUp {
          from { opacity: 0; transform: translateY(16px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes qs-scaleIn {
          from { opacity: 0; transform: scale(0.95); }
          to { opacity: 1; transform: scale(1); }
        }
        @keyframes qs-starPulse {
          0%, 100% { transform: scale(1); }
          50% { transform: scale(1.15); }
        }
        @keyframes qs-progressGrow {
          from { width: 0%; }
        }
        @keyframes qs-shimmer {
          0% { background-position: -200% 0; }
          100% { background-position: 200% 0; }
        }
        @keyframes qs-gaugeStroke {
          from { stroke-dashoffset: 400; }
          to { stroke-dashoffset: 0; }
        }
        .qs-fade-in { animation: qs-fadeInUp 0.5s cubic-bezier(0.22, 1, 0.36, 1) both; }
        .qs-fade-in-1 { animation-delay: 0.05s; }
        .qs-fade-in-2 { animation-delay: 0.1s; }
        .qs-fade-in-3 { animation-delay: 0.15s; }
        .qs-fade-in-4 { animation-delay: 0.2s; }
        .qs-scale-in { animation: qs-scaleIn 0.4s cubic-bezier(0.22, 1, 0.36, 1) both; }
        @media (max-width: 1024px) {
          .qs-kpi-strip { grid-template-columns: repeat(2, 1fr) !important; }
          .qs-stars-top  { grid-template-columns: 1fr !important; }
        }
        @media (max-width: 640px) {
          .qs-kpi-strip { grid-template-columns: 1fr !important; }
          .rci-page-pad-desktop { padding: 20px 16px !important; }
        }
        .qs-measure-table tr:hover td { background: ${tokens.primarySoft} !important; }
        .qs-tab-btn { cursor: pointer; transition: all 0.2s ease; position: relative; }
        .qs-tab-btn:hover { color: ${tokens.primary} !important; }
        .qs-tab-btn::after {
          content: '';
          position: absolute;
          bottom: -2px;
          left: 50%;
          width: 0;
          height: 2px;
          background: ${tokens.primary};
          transition: all 0.25s cubic-bezier(0.22, 1, 0.36, 1);
          transform: translateX(-50%);
        }
        .qs-tab-btn:hover::after { width: 100%; }
        .qs-tab-active::after { width: 100% !important; }
        .qs-tab-btn:focus-visible { outline: 2px solid ${tokens.primary}; outline-offset: 2px; border-radius: 4px; }
        .qs-star-icon { transition: transform 0.2s ease; }
        .qs-star-icon:hover { animation: qs-starPulse 0.4s ease; }
        .qs-progress-bar { animation: qs-progressGrow 0.8s cubic-bezier(0.22, 1, 0.36, 1) both; }
        .qs-card-enter { animation: qs-fadeInUp 0.4s cubic-bezier(0.22, 1, 0.36, 1) both; }
        .qs-priority-card { transition: transform 0.2s ease, box-shadow 0.2s ease; }
        .qs-priority-card:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0,0,0,0.08); }
        .qs-gauge-path { animation: qs-gaugeStroke 1.2s cubic-bezier(0.22, 1, 0.36, 1) both; }
      `}</style>

      {/* ── Data quality banner (degraded data is critical on compliance pages) ── */}
      <DataQualityBanner />

      {/* ── Page Header ── */}
      <PageHeader
        title="Quality Measures & STARS"
        subtitle="HEDIS performance tracking, care gap management, and STARS rating estimation"
        icon={<Star size={22} />}
        actions={
          <button
            onClick={refetchAll}
            disabled={summaryQ.isFetching || measuresQ.isFetching || starsQ.isFetching || gapsQ.isFetching}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "8px 16px",
              border: `1px solid ${C.border}`,
              borderRadius: 8,
              background: C.card,
              color: C.textMuted,
              fontSize: 13,
              fontWeight: 500,
              cursor: "pointer",
              opacity:
                summaryQ.isFetching || measuresQ.isFetching || starsQ.isFetching || gapsQ.isFetching
                  ? 0.6
                  : 1,
            }}
          >
            <RefreshCw size={14} />
            Refresh
          </button>
        }
      />

      {/* ── Top stripe: current STARS summary ── */}
      {currentStars > 0 && (
        <div
          className="premium-card premium-shadow mesh-pattern qs-fade-in"
          style={{
            ...T.card,
            display: "flex",
            alignItems: "center",
            gap: 28,
            background: `linear-gradient(135deg, ${tokens.slate900} 0%, ${tokens.slate800} 50%, ${tokens.slate900} 100%)`,
            border: "1px solid rgba(255,255,255,0.06)",
            marginBottom: 28,
            flexWrap: "wrap",
            borderRadius: 16,
          }}
        >
          <StarsGauge rating={currentStars} />
          <div style={{ flex: 1, minWidth: 200 }}>
            <div style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em", color: tokens.slate400, marginBottom: 8 }}>
              Estimated STARS Rating
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
              {diffUp ? <TrendingUp size={16} color={tokens.success} /> : <TrendingDown size={16} color={tokens.riskHigh} />}
              <span style={{ color: diffUp ? tokens.success : tokens.riskHigh, fontWeight: 700, fontSize: 14 }}>
                {diffUp ? "+" : ""}{(diff ?? 0).toFixed(2)} projected change
              </span>
            </div>
            {summaryQ.data && (
              <div style={{ fontSize: 12, color: tokens.slate500 }}>
                {summaryQ.data.total_measures} measures tracked &middot; {summaryQ.data.measures_above_benchmark} above benchmark
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Tab Bar ── */}
      {/* overflow-x: auto lets the strip scroll horizontally on narrow viewports */}
      <div className="qs-fade-in qs-fade-in-2" style={{ overflowX: "auto", WebkitOverflowScrolling: "touch", borderBottom: `2px solid ${C.borderLight}`, marginBottom: 24 } as React.CSSProperties}>
        <div style={{ display: "flex", gap: 0, minWidth: "max-content" }}>
        {TABS.map((tab) => (
          <button
            key={tab}
            className={`qs-tab-btn ${activeTab === tab ? "qs-tab-active" : ""}`}
            onClick={() => setActiveTab(tab)}
            style={{
              padding: "12px 22px",
              fontSize: 14,
              fontWeight: 600,
              color: activeTab === tab ? C.primary : C.textMuted,
              background: activeTab === tab ? `${C.primary}08` : "none",
              border: "none",
              borderBottom: activeTab === tab ? `2px solid ${C.primary}` : "2px solid transparent",
              borderRadius: "8px 8px 0 0",
              marginBottom: -2,
              cursor: "pointer",
              letterSpacing: "0.01em",
              whiteSpace: "nowrap",
            }}
          >
            {tab}
          </button>
        ))}
        </div>
      </div>

      {/* ── Active Tab Content ── */}
      <div key={activeTab} className="qs-fade-in qs-fade-in-3">
        {renderTabContent()}
      </div>
    </div>
  );
}
