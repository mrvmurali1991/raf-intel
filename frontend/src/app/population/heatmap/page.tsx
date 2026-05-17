"use client";

/**
 * Population Geographic Heat-Map page.
 *
 * Visualises risk + care-gap clustering by ZIP code, sourced from
 * GET /api/population/heatmap?year=YYYY.
 *
 * Visualisation choice: a horizontal-bar chart of the top-20 ZIPs by patient
 * count, coloured by average RAF.  This conveys clustering without pulling
 * in a heavyweight mapping library (react-simple-maps + a topojson file
 * would add ~250 KB to the bundle for what is essentially a sorting-by-ZIP
 * exercise).
 *
 * The page handles loading (skeleton), empty (no ZIPs), and error states.
 */

import { useMemo, useState, useId } from "react";
import { useQuery } from "@tanstack/react-query";
import { MapPin, AlertTriangle, Users, Activity } from "lucide-react";

import api from "@/lib/api";
import { PageHeader, EmptyState } from "@/components/healthcare-ui";
import { tokens } from "@/styles/tokens";

// ---------------------------------------------------------------------------
// Types — match backend/app/routers/population_heatmap.py response shape
// ---------------------------------------------------------------------------

interface HeatmapRow {
  zip_code: string;
  patient_count: number;
  avg_raf: number;
  total_open_gaps: number;
  high_risk_count: number;
}

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------

async function getPopulationHeatmap(year: number): Promise<HeatmapRow[]> {
  const { data } = await api.get<HeatmapRow[]>("/api/population/heatmap", {
    params: { year },
  });
  return Array.isArray(data) ? data : [];
}

// ---------------------------------------------------------------------------
// RAF -> colour ramp (low = green, medium = amber, high = red).
// Thresholds match the risk-stratification tiers used elsewhere in the app.
// ---------------------------------------------------------------------------

function rafColor(raf: number): string {
  if (raf >= 1.8) return tokens.riskHigh;        // very high
  if (raf >= 1.2) return tokens.warningStrong;   // high
  if (raf >= 0.8) return tokens.primary;         // medium
  return tokens.riskLow;                          // low
}

function rafLabel(raf: number): string {
  if (raf >= 1.8) return "Very High";
  if (raf >= 1.2) return "High";
  if (raf >= 0.8) return "Medium";
  return "Low";
}

const YEARS = Array.from({ length: 3 }, (_, i) => new Date().getFullYear() - i);

// ---------------------------------------------------------------------------
// Skeleton — shown while data is loading
// ---------------------------------------------------------------------------

function HeatmapSkeleton() {
  return (
    <div className="animate-pulse" aria-hidden>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-24 rounded-xl bg-muted/50 border border-border"
          />
        ))}
      </div>
      <div className="rounded-xl border border-border bg-card p-6">
        {[...Array(8)].map((_, i) => (
          <div key={i} className="flex items-center gap-3 mb-3">
            <div className="w-16 h-4 rounded bg-muted/70" />
            <div className="flex-1 h-7 rounded bg-muted/50" />
            <div className="w-14 h-4 rounded bg-muted/70" />
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function PopulationHeatmapPage() {
  const [year, setYear] = useState(new Date().getFullYear());
  const [viewAsTable, setViewAsTable] = useState(false);
  const tableToggleId = useId();

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["population-heatmap", year],
    queryFn: () => getPopulationHeatmap(year),
    staleTime: 5 * 60_000,
  });

  // Top-20 by patient_count, descending.  Backend already returns sorted but
  // we re-sort defensively in case a caller swaps to a different endpoint.
  const top20: HeatmapRow[] = useMemo(() => {
    const rows = data ?? [];
    return [...rows]
      .sort((a, b) => b.patient_count - a.patient_count)
      .slice(0, 20);
  }, [data]);

  // KPI totals (across all returned ZIPs, not just the top 20).
  const totals = useMemo(() => {
    const rows = data ?? [];
    const zipCount = rows.length;
    const patientCount = rows.reduce((s, r) => s + r.patient_count, 0);
    const openGaps = rows.reduce((s, r) => s + r.total_open_gaps, 0);
    const highRisk = rows.reduce((s, r) => s + r.high_risk_count, 0);
    return { zipCount, patientCount, openGaps, highRisk };
  }, [data]);

  const maxPatients = top20[0]?.patient_count ?? 1;

  return (
    <div
      className="rci-page-pad-desktop"
      style={{
        minHeight: "100vh",
        background: tokens.slate50,
        padding: "20px 16px 56px",
        fontFamily:
          "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        color: tokens.slate900,
      }}
    >
      <PageHeader
        title="Population Heat-Map"
        subtitle="Risk and care-gap clusters by ZIP code"
        icon={<MapPin size={20} />}
        actions={
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <label
              htmlFor="heatmap-year"
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: tokens.slate500,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
              }}
            >
              Year
            </label>
            <select
              id="heatmap-year"
              value={year}
              onChange={(e) => setYear(Number(e.target.value))}
              style={{
                padding: "8px 32px 8px 14px",
                fontSize: 14,
                fontWeight: 600,
                border: `1px solid ${tokens.slate200}`,
                borderRadius: 8,
                background: tokens.white,
                color: tokens.slate900,
                cursor: "pointer",
                appearance: "none",
                backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2394A3B8' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E")`,
                backgroundRepeat: "no-repeat",
                backgroundPosition: "right 10px center",
              }}
            >
              {YEARS.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          </div>
        }
      />

      {/* ── Loading ────────────────────────────────────────────────── */}
      {isLoading && <HeatmapSkeleton />}

      {/* ── Error ─────────────────────────────────────────────────── */}
      {isError && !isLoading && (
        <div
          role="alert"
          style={{
            padding: "40px 24px",
            textAlign: "center",
            color: tokens.danger,
            background: tokens.riskHighSoft,
            border: `1px solid ${tokens.riskHigh}33`,
            borderRadius: 12,
          }}
        >
          <AlertTriangle size={28} style={{ marginBottom: 10 }} />
          <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>
            Failed to load population heat-map
          </div>
          <button
            onClick={() => refetch()}
            style={{
              padding: "8px 20px",
              borderRadius: 8,
              border: `1px solid ${tokens.riskHigh}`,
              background: tokens.white,
              color: tokens.riskHigh,
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Retry
          </button>
        </div>
      )}

      {/* ── Empty ─────────────────────────────────────────────────── */}
      {!isLoading && !isError && top20.length === 0 && (
        <EmptyState
          icon={<MapPin size={22} />}
          title="No population data yet"
          description={`No patients with ZIP codes and ${year} RAF scores were found in this tenant.  Once patients are imported and scored, clusters will appear here.`}
        />
      )}

      {/* ── Loaded ────────────────────────────────────────────────── */}
      {!isLoading && !isError && top20.length > 0 && (
        <>
          {/* KPI cards */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: 16,
              marginBottom: 24,
            }}
          >
            <KpiCard
              label="ZIP Codes"
              value={totals.zipCount.toLocaleString()}
              icon={<MapPin size={20} />}
              color={tokens.primary}
              bg={tokens.primarySoft}
            />
            <KpiCard
              label="Patients"
              value={totals.patientCount.toLocaleString()}
              icon={<Users size={20} />}
              color={tokens.primaryDark}
              bg={tokens.primarySoft}
            />
            <KpiCard
              label="Open Gaps"
              value={totals.openGaps.toLocaleString()}
              icon={<Activity size={20} />}
              color={tokens.warningStrong}
              bg={"rgba(245, 158, 11, 0.10)"}
            />
            <KpiCard
              label="High-Risk Patients"
              value={totals.highRisk.toLocaleString()}
              icon={<AlertTriangle size={20} />}
              color={tokens.riskHigh}
              bg={tokens.riskHighSoft}
            />
          </div>

          {/* Bar chart */}
          <div
            style={{
              background: tokens.white,
              border: `1px solid ${tokens.slate200}`,
              borderRadius: 14,
              overflow: "hidden",
              boxShadow:
                "0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)",
            }}
          >
            <div
              style={{
                padding: "18px 22px",
                borderBottom: `1px solid ${tokens.slate200}`,
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                flexWrap: "wrap",
                gap: 10,
                background:
                  "linear-gradient(135deg, rgba(37,99,235,0.03) 0%, rgba(139,92,246,0.03) 100%)",
              }}
            >
              <div>
                <h3
                  style={{
                    margin: 0,
                    fontSize: 15,
                    fontWeight: 700,
                    color: tokens.slate900,
                  }}
                >
                  Top {top20.length} ZIP Codes by Patient Count
                </h3>
                <p
                  style={{
                    margin: "4px 0 0",
                    fontSize: 12,
                    color: tokens.slate500,
                  }}
                >
                  Bar length = patient count.  Colour reflects average RAF
                  (green low → red very high).
                </p>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                <RafLegend />
                <button
                  id={tableToggleId}
                  type="button"
                  aria-pressed={viewAsTable}
                  onClick={() => setViewAsTable((v) => !v)}
                  style={{
                    padding: "6px 14px",
                    borderRadius: 8,
                    border: `1px solid ${tokens.slate200}`,
                    background: viewAsTable ? tokens.primary : tokens.white,
                    color: viewAsTable ? tokens.white : tokens.slate700,
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: "pointer",
                    whiteSpace: "nowrap",
                  }}
                >
                  {viewAsTable ? "View as chart" : "View as table"}
                </button>
              </div>
            </div>

            {/* ── Table view ────────────────────────────────────────── */}
            {viewAsTable ? (
              <div style={{ padding: "16px 22px", overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                  <caption className="sr-only">Top ZIP codes by patient count — {year}</caption>
                  <thead>
                    <tr style={{
                      fontSize: 11, fontWeight: 700, textTransform: "uppercase",
                      letterSpacing: "0.06em", color: tokens.slate500,
                      borderBottom: `1px solid ${tokens.slate200}`,
                    }}>
                      <th scope="col" style={{ padding: "8px 12px 8px 0", textAlign: "left" }}>ZIP</th>
                      <th scope="col" style={{ padding: "8px 12px", textAlign: "left" }}>Risk tier</th>
                      <th scope="col" style={{ padding: "8px 12px", textAlign: "right" }}>Patients</th>
                      <th scope="col" style={{ padding: "8px 12px", textAlign: "right" }}>Avg RAF</th>
                      <th scope="col" style={{ padding: "8px 12px", textAlign: "right" }}>Open gaps</th>
                      <th scope="col" style={{ padding: "8px 12px", textAlign: "right" }}>High risk</th>
                    </tr>
                  </thead>
                  <tbody>
                    {top20.map((row) => {
                      const color = rafColor(row.avg_raf);
                      const tier = rafLabel(row.avg_raf);
                      return (
                        <tr key={row.zip_code} style={{ borderBottom: `1px solid ${tokens.slate100}` }}>
                          <td style={{ padding: "8px 12px 8px 0", fontFamily: "monospace", fontWeight: 700, color: tokens.slate900 }}>{row.zip_code}</td>
                          <td style={{ padding: "8px 12px" }}>
                            <span style={{
                              display: "inline-flex", alignItems: "center", gap: 6,
                              fontSize: 12, fontWeight: 600, color,
                            }}>
                              <span style={{ width: 10, height: 10, borderRadius: 2, background: color, flexShrink: 0 }} aria-hidden="true" />
                              {tier}
                            </span>
                          </td>
                          <td style={{ padding: "8px 12px", textAlign: "right", fontWeight: 600, color: tokens.slate900 }}>{row.patient_count.toLocaleString()}</td>
                          <td style={{ padding: "8px 12px", textAlign: "right", fontFamily: "monospace", fontWeight: 700, color }}>{row.avg_raf.toFixed(2)}</td>
                          <td style={{ padding: "8px 12px", textAlign: "right", color: row.total_open_gaps > 0 ? tokens.warningText : tokens.slate500, fontWeight: row.total_open_gaps > 0 ? 600 : 400 }}>{row.total_open_gaps}</td>
                          <td style={{ padding: "8px 12px", textAlign: "right", color: row.high_risk_count > 0 ? tokens.riskHigh : tokens.slate500, fontWeight: row.high_risk_count > 0 ? 600 : 400 }}>{row.high_risk_count}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
            /* ── Bar chart view ───────────────────────────────────── */
            <div
              role="table"
              aria-label="Top ZIP codes by patient count"
              style={{ padding: "16px 22px" }}
            >
              <div
                role="row"
                style={{
                  display: "grid",
                  gridTemplateColumns: "80px 120px 1fr 70px 90px 90px",
                  gap: 12,
                  alignItems: "center",
                  paddingBottom: 8,
                  borderBottom: `1px solid ${tokens.slate100}`,
                  marginBottom: 10,
                  fontSize: 11,
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                  color: tokens.slate500,
                }}
              >
                <div role="columnheader">ZIP</div>
                <div role="columnheader">Risk tier</div>
                <div role="columnheader">Patient distribution</div>
                <div role="columnheader" style={{ textAlign: "right" }}>
                  Avg RAF
                </div>
                <div role="columnheader" style={{ textAlign: "right" }}>
                  Open gaps
                </div>
                <div role="columnheader" style={{ textAlign: "right" }}>
                  High risk
                </div>
              </div>

              {top20.map((row) => {
                const pct = (row.patient_count / maxPatients) * 100;
                const color = rafColor(row.avg_raf);
                const tier = rafLabel(row.avg_raf);
                return (
                  <div
                    role="row"
                    key={row.zip_code}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "80px 120px 1fr 70px 90px 90px",
                      gap: 12,
                      alignItems: "center",
                      padding: "8px 0",
                      borderBottom: `1px solid ${tokens.slate100}`,
                    }}
                  >
                    <div
                      role="cell"
                      style={{
                        fontFamily: "monospace",
                        fontWeight: 700,
                        fontSize: 13,
                        color: tokens.slate900,
                      }}
                    >
                      {row.zip_code}
                    </div>

                    <div
                      role="cell"
                      style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600, color }}
                    >
                      <span style={{ width: 10, height: 10, borderRadius: 2, background: color, flexShrink: 0 }} aria-hidden="true" />
                      {tier}
                    </div>

                    <div
                      role="cell"
                      style={{
                        position: "relative",
                        height: 26,
                        background: tokens.slate100,
                        borderRadius: 6,
                        overflow: "hidden",
                      }}
                    >
                      <div
                        aria-label={`ZIP ${row.zip_code}: ${row.patient_count} patients, avg RAF ${row.avg_raf.toFixed(2)}, ${tier} risk`}
                        style={{
                          width: `${Math.max(pct, 2)}%`,
                          height: "100%",
                          background: color,
                          borderRadius: 6,
                          opacity: 0.85,
                          transition: "width 0.4s ease",
                          display: "flex",
                          alignItems: "center",
                          paddingLeft: 10,
                          color: tokens.white,
                          fontSize: 12,
                          fontWeight: 600,
                        }}
                      >
                        {row.patient_count}
                      </div>
                    </div>

                    <div
                      role="cell"
                      style={{
                        textAlign: "right",
                        fontFamily: "monospace",
                        fontWeight: 700,
                        fontSize: 13,
                        color,
                      }}
                    >
                      {row.avg_raf.toFixed(2)}
                    </div>

                    <div
                      role="cell"
                      style={{
                        textAlign: "right",
                        fontSize: 13,
                        color:
                          row.total_open_gaps > 0
                            ? tokens.warningText
                            : tokens.slate500,
                        fontWeight: row.total_open_gaps > 0 ? 600 : 400,
                      }}
                    >
                      {row.total_open_gaps}
                    </div>

                    <div
                      role="cell"
                      style={{
                        textAlign: "right",
                        fontSize: 13,
                        color:
                          row.high_risk_count > 0
                            ? tokens.riskHigh
                            : tokens.slate500,
                        fontWeight: row.high_risk_count > 0 ? 600 : 400,
                      }}
                    >
                      {row.high_risk_count}
                    </div>
                  </div>
                );
              })}
            </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function KpiCard({
  label,
  value,
  icon,
  color,
  bg,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
  color: string;
  bg: string;
}) {
  return (
    <div
      style={{
        background: tokens.white,
        border: `1px solid ${tokens.slate200}`,
        borderLeft: `4px solid ${color}`,
        borderRadius: 14,
        padding: 20,
        display: "flex",
        alignItems: "center",
        gap: 14,
        boxShadow: "0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)",
      }}
    >
      <div
        style={{
          width: 44,
          height: 44,
          borderRadius: 10,
          background: bg,
          color,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
        }}
      >
        {icon}
      </div>
      <div>
        <div
          style={{
            fontSize: 11,
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            color: tokens.slate500,
          }}
        >
          {label}
        </div>
        <div
          style={{
            fontSize: 24,
            fontWeight: 700,
            color: tokens.slate900,
            marginTop: 4,
            letterSpacing: "-0.02em",
          }}
        >
          {value}
        </div>
      </div>
    </div>
  );
}

function RafLegend() {
  const items: Array<{ label: string; color: string }> = [
    { label: "Low (<0.8)", color: tokens.riskLow },
    { label: "Medium (0.8–1.2)", color: tokens.primary },
    { label: "High (1.2–1.8)", color: tokens.warningStrong },
    { label: "Very High (≥1.8)", color: tokens.riskHigh },
  ];
  return (
    <div
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 10,
        alignItems: "center",
      }}
      aria-label="RAF colour legend"
    >
      {items.map((item) => (
        <div
          key={item.label}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: 11,
            color: tokens.slate600,
          }}
        >
          <span
            style={{
              width: 12,
              height: 12,
              borderRadius: 3,
              background: item.color,
              flexShrink: 0,
            }}
          />
          {item.label}
        </div>
      ))}
    </div>
  );
}
