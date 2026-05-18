"use client";

/**
 * ReportsHeavyTabs — lazy-loaded tab panels for Analytics & Reports.
 *
 * Contains tabs 6–9 (Longitudinal Trends, CMS Benchmarks, Settlement
 * Projection, Scheduled Reports).  Dynamically imported from reports/page.tsx
 * so these panels are excluded from the initial JS bundle.
 */

import { ErrorBoundary } from "@/components/error-boundary";
import React, { useState } from "react";
import { tokens } from "@/styles/tokens";
import type { RevenueOpportunityReport } from "@/lib/api";

// ── Shared types ──────────────────────────────────────────────────────────────
type QueryResult<T = unknown> = { data?: T; isLoading?: boolean; isError?: boolean; refetch?: () => void };

// ── Constants ─────────────────────────────────────────────────────────────────
const YEARS = Array.from({ length: 3 }, (_, i) => new Date().getFullYear() - i);
const CMS_NATIONAL_AVG: { [year: number]: number } = { 2024: 1.08, 2025: 1.10, 2026: 1.12 };
const getCmsAvg = (yr: number) => CMS_NATIONAL_AVG[yr] ?? CMS_NATIONAL_AVG[Math.max(...Object.keys(CMS_NATIONAL_AVG).map(Number))];

const REPORT_TYPES = ["Revenue Opportunity", "Patient Scorecard", "HCC Distribution", "Provider Performance"];
const FREQUENCIES  = ["Weekly", "Monthly", "Quarterly"];
const FORMATS      = ["PDF", "CSV", "Excel"];
const SS_KEY = "raf_scheduled_reports";

// ── Colors ────────────────────────────────────────────────────────────────────
const C = {
  bg: tokens.slate50,
  card: tokens.white,
  border: tokens.slate200,
  borderLight: tokens.slate100,
  text: tokens.slate900,
  textMuted: tokens.slate500,
  textSub: tokens.slate400,
  primary: tokens.primary,
  primaryLight: tokens.primarySoft,
  emerald: tokens.success,
  emeraldLight: tokens.emerald100,
  emeraldDark: tokens.emerald800,
  amber: tokens.warningStrong,
  amberLight: tokens.warningSoft,
  amberDark: tokens.warningText,
  red: tokens.riskHigh,
  redLight: tokens.riskHighSoft,
  redDark: tokens.danger,
  blue: tokens.infoBlue,
  blueLight: tokens.primarySoft,
  blueDark: tokens.primaryDark,
  gray200: tokens.slate200,
  gray300: tokens.slate300,
  gray400: tokens.slate400,
  white: tokens.white,
};

// ── Shared inline styles ──────────────────────────────────────────────────────
const cardStyle: React.CSSProperties = {
  background: C.card,
  border: `1px solid ${C.border}`,
  borderRadius: 14,
  overflow: "hidden",
  boxShadow: "0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)",
};

const thStyle: React.CSSProperties = {
  padding: "12px 16px",
  fontSize: 11,
  fontWeight: 700,
  textTransform: "uppercase" as const,
  letterSpacing: "0.06em",
  color: C.textMuted,
  borderBottom: `2px solid ${C.border}`,
  background: `linear-gradient(180deg, ${C.borderLight} 0%, ${tokens.slate100} 100%)`,
  whiteSpace: "nowrap" as const,
};

const tdStyle: React.CSSProperties = {
  padding: "12px 16px",
  fontSize: 13,
  borderBottom: `1px solid ${C.borderLight}`,
  whiteSpace: "nowrap" as const,
};

function fmt$(v: number | null | undefined): string {
  if (v == null) return "$0";
  return "$" + Math.round(v).toLocaleString("en-US");
}

function GradientSectionHeader({ title }: { title: string }) {
  return (
    <div style={{ padding: "18px 22px", borderBottom: `1px solid ${C.border}`, background: "linear-gradient(135deg, rgba(37,99,235,0.03) 0%, rgba(139,92,246,0.03) 100%)" }}>
      <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, background: `linear-gradient(135deg, ${tokens.primary} 0%, ${tokens.accentPurple} 100%)`, WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text" }}>
        {title}
      </h3>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 6: LONGITUDINAL TRENDS
// ══════════════════════════════════════════════════════════════════════════════
function LongitudinalTrendsTab({ revenue }: { revenue: QueryResult<RevenueOpportunityReport> }) {
  const avgRaf: number = (revenue.data as any)?.average_raf_score ?? 0;
  const yourData: { [year: number]: number } = avgRaf > 0 ? { [new Date().getFullYear()]: avgRaf } : {};

  const W = 660;
  const H = 240;
  const PAD = { top: 24, right: 48, bottom: 48, left: 60 };
  const chartW = W - PAD.left - PAD.right;
  const chartH = H - PAD.top - PAD.bottom;

  const allVals = [...Object.values(yourData), ...Object.values(CMS_NATIONAL_AVG)];
  const minV = Math.min(...allVals) - 0.05;
  const maxV = Math.max(...allVals) + 0.05;

  function xPos(year: number) {
    const idx = YEARS.indexOf(year);
    return PAD.left + (idx / (YEARS.length - 1)) * chartW;
  }
  function yPos(val: number) {
    return PAD.top + chartH - ((val - minV) / (maxV - minV)) * chartH;
  }

  const yourPoints = YEARS.map((y) => ({ x: xPos(y), y: yPos(yourData[y]), val: yourData[y] }));
  const cmsPoints  = YEARS.map((y) => ({ x: xPos(y), y: yPos(getCmsAvg(y)), val: getCmsAvg(y) }));

  function polyline(pts: { x: number; y: number }[]) {
    return pts.map((p) => `${p.x},${p.y}`).join(" ");
  }

  const areaPath = [
    `M ${yourPoints[0].x} ${yourPoints[0].y}`,
    ...yourPoints.slice(1).map((p) => `L ${p.x} ${p.y}`),
    `L ${cmsPoints[cmsPoints.length - 1].x} ${cmsPoints[cmsPoints.length - 1].y}`,
    ...cmsPoints.slice().reverse().map((p) => `L ${p.x} ${p.y}`),
    "Z",
  ].join(" ");

  const gridCount = 4;
  const gridLines = Array.from({ length: gridCount + 1 }).map((_, i) => {
    const v = minV + (i / gridCount) * (maxV - minV);
    return { y: yPos(v), label: (v ?? 0).toFixed(2) };
  });

  const tableRows = YEARS.map((y, i) => {
    const yourVal = yourData[y];
    const prevVal = i > 0 ? yourData[YEARS[i - 1]] : null;
    const delta = prevVal !== null ? yourVal - prevVal : null;
    const vsNational = yourVal - getCmsAvg(y);
    const estRevenue = 5000 * yourVal * 12000;
    return { year: y, yourVal, delta, vsNational, estRevenue };
  });

  return (
    <div>
      <div className="premium-shadow" style={{ ...cardStyle, padding: 28, marginBottom: 24 }}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 20 }}>
          <div>
            <h3 className="gradient-text" style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Average RAF Score — 3-Year Trend</h3>
            <p style={{ margin: "4px 0 0", fontSize: 12, color: C.textMuted }}>Your population vs CMS national average</p>
          </div>
          <div style={{ display: "flex", gap: 20 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ width: 24, height: 3, background: C.primary, borderRadius: 2 }} />
              <span className="text-xs text-muted-foreground font-medium">Your Population</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ width: 24, height: 0, borderTop: `2px dashed ${C.gray400}` }} />
              <span className="text-xs text-muted-foreground font-medium">CMS National Avg</span>
            </div>
          </div>
        </div>

        <div style={{ overflowX: "auto" }}>
          <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", maxWidth: W, display: "block" }} aria-label="RAF score trend chart" role="img">
            {gridLines.map((g) => (
              <g key={g.y}>
                <line x1={PAD.left} y1={g.y} x2={W - PAD.right} y2={g.y} stroke={C.gray200} strokeWidth={1} strokeDasharray="4 3" />
                <text x={PAD.left - 8} y={g.y + 4} textAnchor="end" fontSize={10} fill={C.textSub}>{g.label}</text>
              </g>
            ))}
            {YEARS.map((y) => (
              <text key={y} x={xPos(y)} y={H - 10} textAnchor="middle" fontSize={12} fontWeight={600} fill={C.textMuted}>{y}</text>
            ))}
            <path d={areaPath} fill={tokens.success} fillOpacity={0.12} />
            <polyline points={polyline(cmsPoints)} fill="none" stroke={C.gray400} strokeWidth={2} strokeDasharray="6 4" />
            <polyline points={polyline(yourPoints)} fill="none" stroke={C.primary} strokeWidth={2.5} />
            {cmsPoints.map((p, i) => (
              <circle key={i} cx={p.x} cy={p.y} r={4} fill={C.white} stroke={C.gray400} strokeWidth={2} />
            ))}
            {yourPoints.map((p, i) => (
              <g key={i}>
                <circle cx={p.x} cy={p.y} r={6} fill={C.primary} stroke={C.white} strokeWidth={2} />
                <text x={p.x} y={p.y - 12} textAnchor="middle" fontSize={11} fontWeight={700} fill={C.primary}>{(p.val ?? 0).toFixed(3)}</text>
              </g>
            ))}
            {cmsPoints.map((p, i) => (
              <text key={i} x={p.x + 10} y={p.y + 4} fontSize={10} fill={C.gray400}>{(p.val ?? 0).toFixed(2)}</text>
            ))}
            <line x1={PAD.left} y1={PAD.top} x2={PAD.left} y2={H - PAD.bottom} stroke={C.border} strokeWidth={1} />
            <line x1={PAD.left} y1={H - PAD.bottom} x2={W - PAD.right} y2={H - PAD.bottom} stroke={C.border} strokeWidth={1} />
          </svg>
        </div>
      </div>

      <div className="premium-shadow" style={cardStyle}>
        <GradientSectionHeader title="Year-over-Year Summary" />
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={thStyle}>Year</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Avg RAF</th>
                <th style={{ ...thStyle, textAlign: "right" }}>vs Prior Year</th>
                <th style={{ ...thStyle, textAlign: "right" }}>vs National Avg</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Est. Annual Revenue</th>
              </tr>
            </thead>
            <tbody>
              {tableRows.map((row) => {
                const deltaUp = row.delta != null && row.delta > 0;
                const aboveBench = row.vsNational > 0;
                return (
                  <tr key={row.year}>
                    <td style={{ ...tdStyle, fontWeight: 700, fontSize: 14 }}>{row.year}</td>
                    <td style={{ ...tdStyle, textAlign: "right", fontFamily: "monospace", fontWeight: 600 }}>
                      {(row.yourVal ?? 0).toFixed(3)}
                    </td>
                    <td style={{ ...tdStyle, textAlign: "right" }}>
                      {row.delta != null ? (
                        <span style={{ color: deltaUp ? C.emerald : C.red, fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 3 }}>
                          {deltaUp ? "▲" : "▼"} {Math.abs(row.delta ?? 0).toFixed(3)}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td style={{ ...tdStyle, textAlign: "right" }}>
                      <span style={{ color: aboveBench ? C.emerald : C.red, fontWeight: 600 }}>
                        {aboveBench ? "+" : ""}{(row.vsNational ?? 0).toFixed(3)}
                      </span>
                    </td>
                    <td style={{ ...tdStyle, textAlign: "right", fontWeight: 600, color: C.emeraldDark }}>
                      {fmt$(row.estRevenue)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 7: CMS BENCHMARK COMPARISONS
// ══════════════════════════════════════════════════════════════════════════════
function CmsBenchmarksTab({ revenue }: { revenue: QueryResult<RevenueOpportunityReport> }) {
  const avgRaf: number = (revenue.data as any)?.average_raf_score ?? 0;

  const benchmarks: Array<{
    label: string; desc: string;
    yourValue: number | null; benchmarkValue: number;
    benchmarkLabel: string; unit: string; isRaf?: boolean;
  }> = [
    { label: "Avg RAF vs National", desc: "Population average RAF score", yourValue: avgRaf > 0 ? avgRaf : null, benchmarkValue: getCmsAvg(new Date().getFullYear()), benchmarkLabel: "CMS National Avg", unit: "", isRaf: true },
    { label: "HCC Capture Rate", desc: "Percent of expected HCCs captured", yourValue: 88, benchmarkValue: 85, benchmarkLabel: "Industry Target", unit: "%" },
    { label: "MEAT Completeness", desc: "Documentation completeness score", yourValue: 92, benchmarkValue: 90, benchmarkLabel: "Best Practice", unit: "%" },
    { label: "Suspect Closure Rate", desc: "Closed suspects / total suspects", yourValue: 64, benchmarkValue: 70, benchmarkLabel: "Industry Target", unit: "%" },
  ];

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h3 className="gradient-text" style={{ margin: "0 0 6px", fontSize: 18, fontWeight: 800 }}>CMS Benchmark Comparisons</h3>
        <p style={{ margin: 0, fontSize: 13, color: C.textMuted }}>How your population metrics compare to national benchmarks and industry targets</p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: 20 }}>
        {benchmarks.map((b) => {
          if (b.yourValue === null) {
            return (
              <div key={b.label} className="hover-lift premium-shadow" style={{ ...cardStyle, padding: 24 }}>
                <p style={{ margin: "0 0 4px", fontSize: 11, fontWeight: 600, textTransform: "uppercase" as const, letterSpacing: "0.05em", color: C.textSub }}>{b.label}</p>
                <p style={{ margin: "0 0 16px", fontSize: 12, color: C.textMuted }}>{b.desc}</p>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: "32px 0", color: C.textSub }}>
                  <div style={{ textAlign: "center" }}>
                    <p className="text-sm font-semibold">Data not available</p>
                    <p style={{ fontSize: 11, marginTop: 4 }}>Benchmark: {b.benchmarkValue}{b.unit} ({b.benchmarkLabel})</p>
                  </div>
                </div>
              </div>
            );
          }

          const above = b.yourValue >= b.benchmarkValue;
          const delta = b.yourValue - b.benchmarkValue;
          const deltaStr = b.isRaf
            ? (delta >= 0 ? "+" : "") + (delta ?? 0).toFixed(3)
            : (delta >= 0 ? "+" : "") + (delta ?? 0).toFixed(1) + b.unit;
          const displayYour = b.isRaf ? (b.yourValue ?? 0).toFixed(3) : (b.yourValue ?? 0).toFixed(1) + b.unit;
          const displayBench = b.isRaf ? (b.benchmarkValue ?? 0).toFixed(2) : (b.benchmarkValue ?? 0).toFixed(0) + b.unit;
          const barScale = b.isRaf ? 4 : 100;
          const yourPct = Math.min((b.yourValue / barScale) * 100, 100);
          const benchPct = Math.min((b.benchmarkValue / barScale) * 100, 100);

          return (
            <div key={b.label} className="hover-lift premium-shadow" style={{ ...cardStyle, padding: 24 }}>
              <p style={{ margin: "0 0 4px", fontSize: 11, fontWeight: 600, textTransform: "uppercase" as const, letterSpacing: "0.05em", color: C.textSub }}>{b.label}</p>
              <p style={{ margin: "0 0 16px", fontSize: 12, color: C.textMuted }}>{b.desc}</p>
              <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 16 }}>
                <div>
                  <div style={{ fontSize: 36, fontWeight: 700, lineHeight: 1, color: above ? C.emeraldDark : C.redDark }}>{displayYour}</div>
                  <div style={{ fontSize: 11, color: C.textSub, marginTop: 3 }}>Your population</div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div className="text-lg font-semibold text-muted-foreground">{displayBench}</div>
                  <div className="text-[11px] text-muted-foreground">{b.benchmarkLabel}</div>
                </div>
              </div>
              <div style={{ marginBottom: 14 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: above ? C.emeraldDark : C.redDark, background: above ? C.emeraldLight : C.redLight, padding: "4px 10px", borderRadius: 99 }}>
                  {above ? "▲" : "▼"} {deltaStr} vs benchmark
                </span>
              </div>
              <div style={{ position: "relative", height: 10, background: C.gray200, borderRadius: 5, overflow: "visible" }}>
                <div style={{ height: "100%", width: `${yourPct}%`, borderRadius: 5, background: above ? `linear-gradient(90deg, ${C.emerald}, ${tokens.emerald300})` : `linear-gradient(90deg, ${C.red}, ${tokens.riskHighSoft})`, transition: "width 0.5s ease" }} />
                <div style={{ position: "absolute", top: -3, left: `${benchPct}%`, width: 3, height: 16, background: C.gray400, borderRadius: 2, transform: "translateX(-50%)" }} />
                <div style={{ position: "absolute", top: -18, left: `${benchPct}%`, transform: "translateX(-50%)", fontSize: 9, color: C.textSub, whiteSpace: "nowrap" as const, fontWeight: 600 }}>Target</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 8: SETTLEMENT PROJECTION
// ══════════════════════════════════════════════════════════════════════════════
function SettlementProjectionTab({ revenue }: { revenue: QueryResult<RevenueOpportunityReport> }) {
  const [gapClosurePct, setGapClosurePct] = useState(50);

  const r = revenue.data as any;
  const population = r?.total_patients_analyzed ?? r?.total_patients ?? 0;
  const avgRaf      = r?.average_raf_score ?? 0;
  const totalGap    = r?.total_gap ?? 0;

  const BASE_PAYMENT_PER_MEMBER = 12_000;
  const currentAnnualRevenue = population * avgRaf * BASE_PAYMENT_PER_MEMBER;
  const additionalRevenue    = (gapClosurePct / 100) * totalGap * BASE_PAYMENT_PER_MEMBER;
  const projectedRevenue     = currentAnnualRevenue + additionalRevenue;

  const scenarios = [25, 50, 75, 100].map((pct) => ({
    pct,
    additional: (pct / 100) * totalGap * BASE_PAYMENT_PER_MEMBER,
  }));

  function fmt$M(v: number) {
    if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`;
    if (v >= 1_000) return `$${Math.round(v / 1_000)}K`;
    return `$${Math.round(v)}`;
  }

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h3 className="gradient-text" style={{ margin: "0 0 6px", fontSize: 18, fontWeight: 800 }}>Risk Adjustment Settlement Projection</h3>
        <p style={{ margin: 0, fontSize: 13, color: C.textMuted }}>Estimated annual revenue impact based on gap closure trajectory</p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 20, marginBottom: 28 }}>
        <div className="hover-lift card-glow-blue" style={{ ...cardStyle, borderLeft: `4px solid ${C.blue}`, padding: 24 }}>
          <p style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase" as const, letterSpacing: "0.06em", color: C.textMuted, margin: 0 }}>Current Annual RAF Payment</p>
          <p style={{ fontSize: 28, fontWeight: 700, margin: "8px 0 4px", color: C.blueDark }}>{fmt$M(currentAnnualRevenue)}</p>
          <p style={{ fontSize: 12, color: C.textSub, margin: 0 }}>{population.toLocaleString()} members × {(avgRaf ?? 0).toFixed(3)} RAF × $12K</p>
        </div>
        <div className="hover-lift card-glow-amber" style={{ ...cardStyle, borderLeft: `4px solid ${C.amber}`, padding: 24 }}>
          <p style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase" as const, letterSpacing: "0.06em", color: C.textMuted, margin: 0 }}>Identified RAF Gap</p>
          <p style={{ fontSize: 28, fontWeight: 700, margin: "8px 0 4px", color: C.amberDark }}>{(totalGap ?? 0).toFixed(1)} pts</p>
          <p style={{ fontSize: 12, color: C.textSub, margin: 0 }}>Uncaptured RAF across population</p>
        </div>
        <div className="hover-lift card-glow-emerald" style={{ ...cardStyle, borderLeft: `4px solid ${C.emerald}`, padding: 24 }}>
          <p style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase" as const, letterSpacing: "0.06em", color: C.textMuted, margin: 0 }}>Max Additional Revenue</p>
          <p style={{ fontSize: 28, fontWeight: 700, margin: "8px 0 4px", color: C.emeraldDark }}>{fmt$M(totalGap * BASE_PAYMENT_PER_MEMBER)}</p>
          <p style={{ fontSize: 12, color: C.textSub, margin: 0 }}>If 100% of gaps are closed</p>
        </div>
      </div>

      <div className="premium-shadow" style={{ ...cardStyle, padding: 28, marginBottom: 24 }}>
        <h4 style={{ margin: "0 0 20px", fontSize: 14, fontWeight: 600 }}>Gap Closure Simulator</h4>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
          <label className="text-[13px] font-medium text-muted-foreground">Gap Closure Target</label>
          <span className="text-xl font-bold text-primary">{gapClosurePct}%</span>
        </div>
        <input
          type="range" min={0} max={100} step={1} value={gapClosurePct}
          onChange={(e) => setGapClosurePct(Number(e.target.value))}
          style={{ width: "100%", accentColor: C.primary, cursor: "pointer", height: 6, marginBottom: 24 }}
          aria-label="Gap closure target percentage"
        />
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "20px 24px", background: tokens.successSoft, borderRadius: 10, border: `1px solid ${tokens.emerald100}` }}>
          <div>
            <p style={{ margin: 0, fontSize: 13, color: C.textMuted }}>If you close {gapClosurePct}% of gaps...</p>
            <p style={{ margin: "6px 0 0", fontSize: 13, color: C.textMuted }}>
              Additional annual revenue:
              <span style={{ fontSize: 26, fontWeight: 700, color: C.emeraldDark, marginLeft: 12 }}>{fmt$M(additionalRevenue)}</span>
            </p>
          </div>
          <div style={{ textAlign: "right" }}>
            <p style={{ margin: 0, fontSize: 12, color: C.textSub }}>Projected total</p>
            <p style={{ margin: "4px 0 0", fontSize: 20, fontWeight: 700, color: C.emeraldDark }}>{fmt$M(projectedRevenue)}</p>
          </div>
        </div>
      </div>

      <div className="premium-shadow" style={cardStyle}>
        <GradientSectionHeader title="Scenario Comparison" />
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={thStyle}>Gap Closure %</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Additional Revenue</th>
                <th style={{ ...thStyle, textAlign: "right" }}>Projected Annual Total</th>
                <th style={{ ...thStyle, textAlign: "left" }}>Progress to Max</th>
              </tr>
            </thead>
            <tbody>
              {scenarios.map((s) => (
                <tr key={s.pct} style={{ background: s.pct === Math.round(gapClosurePct / 25) * 25 ? C.borderLight : "transparent" }}>
                  <td style={{ ...tdStyle, fontWeight: 700 }}>{s.pct}%</td>
                  <td style={{ ...tdStyle, textAlign: "right", fontWeight: 600, color: C.emeraldDark }}>{fmt$M(s.additional)}</td>
                  <td style={{ ...tdStyle, textAlign: "right", fontWeight: 600 }}>{fmt$M(currentAnnualRevenue + s.additional)}</td>
                  <td style={{ ...tdStyle }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <div style={{ flex: 1, height: 6, background: C.gray200, borderRadius: 3 }}>
                        <div style={{ width: `${s.pct}%`, height: "100%", background: C.emerald, borderRadius: 3 }} />
                      </div>
                      <span style={{ fontSize: 11, color: C.textMuted, width: 34 }}>{s.pct}%</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// TAB 9: SCHEDULED REPORTS
// ══════════════════════════════════════════════════════════════════════════════

interface ScheduledReport {
  id: string; type: string; frequency: string;
  recipients: string; format: string; enabled: boolean; createdAt: string;
}

function loadScheduled(): ScheduledReport[] {
  if (typeof window === "undefined") return [];
  try { return JSON.parse(sessionStorage.getItem(SS_KEY) ?? "[]"); } catch { return []; }
}

function saveScheduled(list: ScheduledReport[]) {
  if (typeof window === "undefined") return;
  const redacted = list.map((r) => ({ ...r, recipients: "[stored-server-side]" }));
  sessionStorage.setItem(SS_KEY, JSON.stringify(redacted));
}

function ScheduledReportsTab() {
  const [reports, setReports] = useState<ScheduledReport[]>(() => loadScheduled());
  const [showDialog, setShowDialog] = useState(false);
  const [form, setForm] = useState({ type: REPORT_TYPES[0], frequency: FREQUENCIES[1], recipients: "", format: FORMATS[0] });

  function handleCreate() {
    if (!form.recipients.trim()) return;
    const newReport: ScheduledReport = { id: `sr_${Date.now()}`, type: form.type, frequency: form.frequency, recipients: form.recipients, format: form.format, enabled: true, createdAt: new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) };
    const updated = [newReport, ...reports];
    setReports(updated); saveScheduled(updated); setShowDialog(false);
    setForm({ type: REPORT_TYPES[0], frequency: FREQUENCIES[1], recipients: "", format: FORMATS[0] });
  }

  function toggleEnabled(id: string) { const updated = reports.map((r) => (r.id === id ? { ...r, enabled: !r.enabled } : r)); setReports(updated); saveScheduled(updated); }
  function deleteReport(id: string) { const updated = reports.filter((r) => r.id !== id); setReports(updated); saveScheduled(updated); }

  const inputStyle: React.CSSProperties = { width: "100%", padding: "9px 12px", fontSize: 13, border: `1px solid ${C.border}`, borderRadius: 8, background: C.white, color: C.text, boxSizing: "border-box" as const };
  const labelStyle: React.CSSProperties = { display: "block", fontSize: 12, fontWeight: 600, color: C.textMuted, marginBottom: 6, textTransform: "uppercase" as const, letterSpacing: "0.05em" };

  return (
    <ErrorBoundary fallbackTitle="Reports page failed to load">
    <div>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <h3 className="gradient-text" style={{ margin: "0 0 4px", fontSize: 18, fontWeight: 800 }}>Scheduled Reports</h3>
          <p style={{ margin: 0, fontSize: 13, color: C.textMuted }}>
            Automate report delivery to your team.
            <span style={{ marginLeft: 8, padding: "2px 8px", borderRadius: 99, background: C.amberLight, color: C.amberDark, fontSize: 11, fontWeight: 600 }}>Email delivery coming soon</span>
          </p>
        </div>
        <button onClick={() => setShowDialog(true)} style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "9px 18px", fontSize: 13, fontWeight: 600, color: C.white, background: C.primary, border: "none", borderRadius: 8, cursor: "pointer" }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          Schedule Report
        </button>
      </div>

      {showDialog && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(15,23,42,0.45)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000 }} onClick={(e) => { if (e.target === e.currentTarget) setShowDialog(false); }}>
          <div style={{ background: C.white, borderRadius: 14, padding: 32, width: 480, maxWidth: "90vw", boxShadow: "0 20px 60px rgba(0,0,0,0.2)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Schedule a Report</h3>
              <button onClick={() => setShowDialog(false)} style={{ background: "none", border: "none", cursor: "pointer", color: C.textMuted, fontSize: 20, lineHeight: 1, padding: 4 }} aria-label="Close dialog">×</button>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div>
                <label style={labelStyle}>Report Type</label>
                <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} style={inputStyle}>
                  {REPORT_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <div>
                  <label style={labelStyle}>Frequency</label>
                  <select value={form.frequency} onChange={(e) => setForm({ ...form, frequency: e.target.value })} style={inputStyle}>
                    {FREQUENCIES.map((f) => <option key={f} value={f}>{f}</option>)}
                  </select>
                </div>
                <div>
                  <label style={labelStyle}>Format</label>
                  <select value={form.format} onChange={(e) => setForm({ ...form, format: e.target.value })} style={inputStyle}>
                    {FORMATS.map((f) => <option key={f} value={f}>{f}</option>)}
                  </select>
                </div>
              </div>
              <div>
                <label style={labelStyle}>Recipients (comma-separated emails)</label>
                <input type="text" placeholder="jane@clinic.org, ops@healthplan.com" value={form.recipients} onChange={(e) => setForm({ ...form, recipients: e.target.value })} style={inputStyle} />
              </div>
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 24 }}>
              <button onClick={() => setShowDialog(false)} style={{ padding: "9px 18px", fontSize: 13, fontWeight: 500, border: `1px solid ${C.border}`, borderRadius: 8, background: C.white, cursor: "pointer", color: C.text }}>Cancel</button>
              <button onClick={handleCreate} disabled={!form.recipients.trim()} style={{ padding: "9px 18px", fontSize: 13, fontWeight: 600, border: "none", borderRadius: 8, background: form.recipients.trim() ? C.primary : C.gray200, color: form.recipients.trim() ? C.white : C.textSub, cursor: form.recipients.trim() ? "pointer" : "not-allowed" }}>Save Schedule</button>
            </div>
          </div>
        </div>
      )}

      {reports.length === 0 ? (
        <div className="premium-shadow" style={{ ...cardStyle, padding: 60, textAlign: "center" as const }}>
          <div style={{ width: 56, height: 56, borderRadius: 14, background: C.borderLight, display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 16px" }}>
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke={C.textSub} strokeWidth="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
          </div>
          <p style={{ margin: 0, fontSize: 15, fontWeight: 600, color: C.text }}>No scheduled reports yet</p>
          <p style={{ margin: "8px 0 0", fontSize: 13, color: C.textMuted }}>Click &quot;Schedule Report&quot; to create your first automated report.</p>
        </div>
      ) : (
        <div className="premium-shadow" style={cardStyle}>
          <table className="premium-table" style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={thStyle}>Report Type</th>
                <th style={thStyle}>Frequency</th>
                <th style={thStyle}>Format</th>
                <th style={thStyle}>Recipients</th>
                <th style={thStyle}>Created</th>
                <th style={{ ...thStyle, textAlign: "center" }}>Status</th>
                <th style={{ ...thStyle, textAlign: "center" }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {reports.map((r, idx) => (
                <tr key={r.id} style={{ background: idx % 2 === 1 ? tokens.slate50 : "transparent", transition: "background-color 0.15s ease" }}>
                  <td style={{ ...tdStyle, fontWeight: 500 }}>{r.type}</td>
                  <td style={tdStyle}>{r.frequency}</td>
                  <td style={tdStyle}>
                    <span style={{ padding: "2px 8px", borderRadius: 4, background: C.blueLight, color: C.blueDark, fontSize: 11, fontWeight: 600 }}>{r.format}</span>
                  </td>
                  <td style={{ ...tdStyle, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", color: C.textMuted, fontSize: 12 }}>{r.recipients}</td>
                  <td style={{ ...tdStyle, color: C.textSub, fontSize: 12 }}>{r.createdAt}</td>
                  <td style={{ ...tdStyle, textAlign: "center" }}>
                    <button onClick={() => toggleEnabled(r.id)} role="switch" aria-checked={r.enabled} aria-label={`${r.enabled ? "Disable" : "Enable"} ${r.type} schedule`}
                      style={{ width: 38, height: 22, borderRadius: 11, border: "none", background: r.enabled ? C.emerald : C.gray300, cursor: "pointer", position: "relative", transition: "background 0.2s", padding: 0 }}>
                      <span style={{ position: "absolute", top: 3, left: r.enabled ? 19 : 3, width: 16, height: 16, borderRadius: "50%", background: C.white, transition: "left 0.2s", display: "block" }} />
                    </button>
                  </td>
                  <td style={{ ...tdStyle, textAlign: "center" }}>
                    <button onClick={() => deleteReport(r.id)} aria-label={`Delete ${r.type} schedule`}
                      style={{ background: "none", border: "none", cursor: "pointer", color: C.red, fontSize: 13, padding: "4px 8px", borderRadius: 4 }}>Remove</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
    </ErrorBoundary>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Exported wrapper — renders the active heavy tab
// ══════════════════════════════════════════════════════════════════════════════
type HeavyTabKey = "Longitudinal Trends" | "CMS Benchmarks" | "Settlement Projection" | "Scheduled Reports";

interface ReportsHeavyTabsProps {
  activeTab: HeavyTabKey;
  revenue: QueryResult<RevenueOpportunityReport>;
}

export default function ReportsHeavyTabs({ activeTab, revenue }: ReportsHeavyTabsProps) {
  if (activeTab === "Longitudinal Trends") return <LongitudinalTrendsTab revenue={revenue} />;
  if (activeTab === "CMS Benchmarks") return <CmsBenchmarksTab revenue={revenue} />;
  if (activeTab === "Settlement Projection") return <SettlementProjectionTab revenue={revenue} />;
  if (activeTab === "Scheduled Reports") return <ScheduledReportsTab />;
  return null;
}
