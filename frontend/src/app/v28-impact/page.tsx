"use client";

/**
 * V28 Transition Impact — portfolio dashboard.
 *
 * Surfaces the per-tenant V24 → V28 transition impact:
 *   - Top-line KPIs (total V24, V28, $ delta, erosion %).
 *   - Histogram: per-patient $ delta distribution.
 *   - Top-eroded patients table (drill-into the patient detail V28 Impact tab).
 *   - HCC erosion breakdown — which HCC categories drop the most across the panel.
 *
 * Backed by GET /api/v28-impact/portfolio.
 */

import { useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import {
  Loader2,
  AlertTriangle,
  RefreshCw,
  TrendingDown,
  TrendingUp,
  Calendar,
  Users,
} from "lucide-react";

// ---------- Types ----------

type Histogram = { bucket_label: string; lo: number; hi: number; count: number };
type ErodedRow = {
  pid: number;
  v24: number;
  v28: number;
  delta: number;
  delta_pct: number;
  revenue: number;
  dropped_hccs: string[];
};
type GainedRow = Omit<ErodedRow, "dropped_hccs"> & { gained_hccs: string[] };

type PortfolioImpact = {
  tenant_id: string;
  measurement_year: number;
  patient_count: number;
  computed_patient_count: number;
  total_v24_raf: number;
  total_v28_raf: number;
  avg_v24_raf: number;
  avg_v28_raf: number;
  total_raf_delta: number;
  raf_erosion_pct: number;
  total_revenue_delta: number;
  top_eroded_patients: ErodedRow[];
  top_gained_patients: GainedRow[];
  hcc_erosion_breakdown: Record<string, number>;
  delta_histogram: Histogram[];
  errors: number;
  revenue_per_raf_point: number;
  generated_at: string;
};

// ---------- Helpers ----------

function fmtMoney(n: number): string {
  const sign = n < 0 ? "-" : n > 0 ? "+" : "";
  return `${sign}$${Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function fmtRAF(n: number): string {
  return n.toFixed(3);
}

// ---------- Page ----------

export default function V28ImpactPage() {
  const queryClient = useQueryClient();
  const [year, setYear] = useState<number>(2026);

  const { data, isLoading, error, refetch, isRefetching } = useQuery<PortfolioImpact>({
    queryKey: ["v28-impact", "portfolio", year],
    queryFn: async () => {
      const res = await api.get<PortfolioImpact>("/api/v28-impact/portfolio", {
        params: { year },
      });
      return res.data;
    },
    staleTime: 60_000,
    retry: 1,
  });

  const runAnalysis = useMutation({
    mutationFn: async () => {
      const res = await api.post("/api/v28-impact/run-analysis", null, {
        params: { year },
      });
      return res.data as { queued: boolean; status: string };
    },
    onSuccess: () => {
      // Refetch after a short delay so Celery/sync result is included
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["v28-impact", "portfolio", year] });
      }, 1500);
    },
  });

  return (
    <main style={{ padding: 24, maxWidth: 1400, margin: "0 auto" }}>
      <header style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16, marginBottom: 16 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 800, color: "#0f172a", margin: 0 }}>
            V28 Transition Impact
          </h1>
          <p style={{ fontSize: 13, color: "#64748b", margin: "4px 0 0" }}>
            Portfolio-wide CMS V24 → V28 model erosion forecast. CMS projects
            ~-3.12% aggregate RAF erosion at the PY2026 100% V28 cutover.
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "#475569" }}>
            <Calendar size={14} />
            Year
            <select
              value={year}
              onChange={(e) => setYear(Number(e.target.value))}
              style={{
                padding: "4px 8px",
                border: "1px solid #cbd5e1",
                borderRadius: 6,
                background: "#fff",
                fontSize: 12,
              }}
            >
              <option value={2024}>2024 (67% V24 / 33% V28)</option>
              <option value={2025}>2025 (33% V24 / 67% V28)</option>
              <option value={2026}>2026 (100% V28)</option>
              <option value={2027}>2027 (100% V28)</option>
            </select>
          </label>
          <button
            type="button"
            onClick={() => runAnalysis.mutate()}
            disabled={runAnalysis.isPending}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "6px 12px",
              background: "#0f172a",
              color: "#fff",
              border: "none",
              borderRadius: 6,
              fontSize: 12,
              fontWeight: 600,
              cursor: runAnalysis.isPending ? "wait" : "pointer",
            }}
          >
            {runAnalysis.isPending ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            Run Analysis
          </button>
        </div>
      </header>

      {isLoading && (
        <div style={{ padding: 32, color: "#64748b", display: "flex", alignItems: "center", gap: 8 }}>
          <Loader2 size={16} className="animate-spin" />
          Loading portfolio impact…
        </div>
      )}

      {error && !isLoading && (
        <div
          role="alert"
          style={{
            padding: 16,
            border: "1px solid #fca5a5",
            background: "#fef2f2",
            color: "#7f1d1d",
            borderRadius: 8,
            display: "flex",
            gap: 8,
            alignItems: "center",
          }}
        >
          <AlertTriangle size={16} />
          Could not load portfolio impact.{" "}
          <button onClick={() => refetch()} style={{ marginLeft: 8, textDecoration: "underline" }}>
            Retry
          </button>
        </div>
      )}

      {data && (
        <>
          {/* Top KPIs */}
          <section
            aria-label="Portfolio KPIs"
            className="kpi-grid"
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(4, minmax(180px, 1fr))",
              gap: 12,
              marginBottom: 20,
            }}
          >
            <KPI
              label="Patients in panel"
              value={`${data.computed_patient_count.toLocaleString()}`}
              subtitle={
                data.errors > 0
                  ? `${data.errors} skipped (errors)`
                  : `${data.patient_count} discovered`
              }
              icon={<Users size={16} />}
            />
            <KPI
              label="Total V24 RAF"
              value={fmtRAF(data.total_v24_raf)}
              subtitle={`avg ${fmtRAF(data.avg_v24_raf)}/pt`}
            />
            <KPI
              label="Total V28 RAF"
              value={fmtRAF(data.total_v28_raf)}
              subtitle={`avg ${fmtRAF(data.avg_v28_raf)}/pt`}
            />
            <KPI
              label="Annual Δ Revenue (V28 - V24)"
              value={fmtMoney(data.total_revenue_delta)}
              subtitle={`${data.raf_erosion_pct > 0 ? "+" : ""}${data.raf_erosion_pct.toFixed(2)}% RAF erosion`}
              accent={data.total_revenue_delta < 0 ? "#dc2626" : "#059669"}
              icon={
                data.total_revenue_delta < 0 ? (
                  <TrendingDown size={16} />
                ) : (
                  <TrendingUp size={16} />
                )
              }
            />
          </section>

          {/* Histogram */}
          <section
            aria-label="Per-patient delta distribution"
            style={{
              padding: 16,
              background: "#fff",
              border: "1px solid #e2e8f0",
              borderRadius: 8,
              marginBottom: 20,
            }}
          >
            <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a", marginBottom: 4 }}>
              Per-patient annual Δ revenue distribution
            </div>
            <div style={{ fontSize: 11, color: "#64748b", marginBottom: 12 }}>
              X axis: $ bucket. Y axis: patient count. Negative bins (left) indicate erosion.
            </div>
            <DeltaHistogram buckets={data.delta_histogram} />
          </section>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(0, 2fr) minmax(280px, 1fr)",
              gap: 20,
            }}
          >
            {/* Top eroded patients */}
            <section
              aria-label="Top eroded patients"
              style={{
                background: "#fff",
                border: "1px solid #e2e8f0",
                borderRadius: 8,
                padding: 16,
              }}
            >
              <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a", marginBottom: 8 }}>
                Top-eroded patients ({data.top_eroded_patients.length})
              </div>
              {data.top_eroded_patients.length === 0 ? (
                <div style={{ fontSize: 12, color: "#64748b", fontStyle: "italic" }}>
                  No patients show negative V28 erosion in the current panel.
                </div>
              ) : (
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                  <thead>
                    <tr style={{ textAlign: "left", color: "#64748b", borderBottom: "1px solid #e2e8f0" }}>
                      <Th>PID</Th>
                      <Th align="right">V24 RAF</Th>
                      <Th align="right">V28 RAF</Th>
                      <Th align="right">Δ RAF</Th>
                      <Th align="right">Δ Revenue</Th>
                      <Th>Top dropped HCCs</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.top_eroded_patients.map((row) => (
                      <tr key={row.pid} style={{ borderBottom: "1px solid #f1f5f9" }}>
                        <Td>
                          <Link
                            href={`/patients/${row.pid}?tab=v28-impact`}
                            style={{ color: "#0369a1", fontWeight: 600 }}
                          >
                            {row.pid}
                          </Link>
                        </Td>
                        <Td align="right">{fmtRAF(row.v24)}</Td>
                        <Td align="right">{fmtRAF(row.v28)}</Td>
                        <Td align="right" color="#dc2626">
                          {row.delta > 0 ? "+" : ""}
                          {fmtRAF(row.delta)}
                        </Td>
                        <Td align="right" color="#dc2626">
                          {fmtMoney(row.revenue)}
                        </Td>
                        <Td>
                          {row.dropped_hccs.length === 0 ? (
                            <span aria-label="none" style={{ color: "#64748b", fontStyle: "italic" }}>—</span>
                          ) : (
                            <span style={{ display: "inline-flex", flexWrap: "wrap", gap: 4 }}>
                              {row.dropped_hccs.map((h) => (
                                <span
                                  key={h}
                                  style={{
                                    padding: "1px 6px",
                                    borderRadius: 999,
                                    background: "#fef2f2",
                                    color: "#dc2626",
                                    fontSize: 10,
                                    fontWeight: 600,
                                    border: "1px solid #fecaca",
                                  }}
                                >
                                  HCC {h}
                                </span>
                              ))}
                            </span>
                          )}
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </section>

            {/* HCC erosion breakdown */}
            <section
              aria-label="HCC erosion breakdown"
              style={{
                background: "#fff",
                border: "1px solid #e2e8f0",
                borderRadius: 8,
                padding: 16,
              }}
            >
              <div style={{ fontSize: 13, fontWeight: 700, color: "#0f172a", marginBottom: 4 }}>
                HCC erosion breakdown
              </div>
              <div style={{ fontSize: 11, color: "#64748b", marginBottom: 12 }}>
                HCCs most-frequently dropped across the panel.
              </div>
              {Object.keys(data.hcc_erosion_breakdown).length === 0 ? (
                <div style={{ fontSize: 12, color: "#64748b", fontStyle: "italic" }}>
                  No HCCs dropped — the entire panel rolls cleanly to V28.
                </div>
              ) : (
                <>
                  {/* Visual bar chart */}
                  <ol
                    aria-label="HCC erosion bar chart"
                    style={{ margin: 0, padding: 0, listStyle: "none", display: "grid", gap: 6 }}
                  >
                    {Object.entries(data.hcc_erosion_breakdown).map(([hcc, count]) => {
                      const max = Math.max(...Object.values(data.hcc_erosion_breakdown));
                      const pct = Math.round((count / max) * 100);
                      return (
                        <li key={hcc} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ minWidth: 56, fontSize: 11, color: "#475569", fontWeight: 600 }}>
                            HCC {hcc}
                          </span>
                          <div
                            aria-hidden="true"
                            style={{
                              flex: 1,
                              height: 8,
                              background: "#fef2f2",
                              borderRadius: 4,
                              overflow: "hidden",
                            }}
                          >
                            <div
                              style={{ width: `${pct}%`, height: "100%", background: "#dc2626" }}
                            />
                          </div>
                          <span style={{ minWidth: 32, fontSize: 11, color: "#475569", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                            {count}
                          </span>
                        </li>
                      );
                    })}
                  </ol>
                  {/* SR-only data table: accessible alternative to HCC erosion bars */}
                  <table className="sr-only">
                    <caption>HCC codes most frequently dropped across the panel</caption>
                    <thead>
                      <tr>
                        <th scope="col">HCC code</th>
                        <th scope="col">Patients affected</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(data.hcc_erosion_breakdown).map(([hcc, count]) => (
                        <tr key={hcc}>
                          <th scope="row">HCC {hcc}</th>
                          <td>{count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </section>
          </div>

          <footer style={{ marginTop: 16, fontSize: 11, color: "#64748b", lineHeight: 1.5 }}>
            Computed {data.generated_at} · ${data.revenue_per_raf_point.toLocaleString()} per RAF
            point ·{" "}
            {isRefetching && <span style={{ marginLeft: 4 }}>Refreshing…</span>}
            <br />
            Disclaimer: V24 / V28 coefficients sourced from the hccinfhir
            third-party CMS-HCC implementation; not validated by CMS.
            Cross-check against the official CMS HCC Software before
            contract or payment use.
          </footer>
        </>
      )}
    </main>
  );
}

// ---------- Subcomponents ----------

function KPI({
  label,
  value,
  subtitle,
  accent,
  icon,
}: {
  label: string;
  value: string;
  subtitle?: string;
  accent?: string;
  icon?: React.ReactNode;
}) {
  return (
    <div
      style={{
        padding: 14,
        background: "#fff",
        border: "1px solid #e2e8f0",
        borderRadius: 8,
        display: "flex",
        flexDirection: "column",
        gap: 4,
      }}
    >
      <div
        style={{
          fontSize: 11,
          color: "#64748b",
          textTransform: "uppercase",
          letterSpacing: 0.4,
          display: "flex",
          alignItems: "center",
          gap: 4,
        }}
      >
        {icon}
        {label}
      </div>
      <div style={{ fontSize: 24, fontWeight: 800, color: accent ?? "#0f172a", lineHeight: 1.1 }}>
        {value}
      </div>
      {subtitle && <div style={{ fontSize: 11, color: "#64748b" }}>{subtitle}</div>}
    </div>
  );
}

function DeltaHistogram({ buckets }: { buckets: Histogram[] }) {
  const max = Math.max(1, ...buckets.map((b) => b.count));
  const height = 120;

  // Build a concise aria-label summarising the top non-zero buckets (up to 5).
  const topBuckets = [...buckets]
    .filter((b) => b.count > 0)
    .sort((a, b) => b.count - a.count)
    .slice(0, 5);
  const ariaLabel =
    topBuckets.length === 0
      ? "Distribution of patients by revenue delta: no data"
      : `Distribution of patients by revenue delta: ${topBuckets
          .map((b) => `${b.count} in ${b.bucket_label}`)
          .join(", ")}`;

  return (
    <div>
      <div
        role="img"
        aria-label={ariaLabel}
        style={{ display: "flex", alignItems: "flex-end", gap: 6, height: height + 36 }}
      >
        {buckets.map((b) => {
          const h = (b.count / max) * height;
          const negative = b.hi <= 0;
          const positive = b.lo >= 0;
          const color = negative ? "#dc2626" : positive ? "#059669" : "#475569";
          return (
            <div
              key={b.bucket_label}
              style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}
              title={`${b.bucket_label}: ${b.count} patients`}
            >
              <div style={{ fontSize: 11, color: "#475569", fontVariantNumeric: "tabular-nums" }}>
                {b.count}
              </div>
              <div
                style={{
                  width: "100%",
                  height: Math.max(2, h),
                  background: color,
                  borderRadius: 4,
                  opacity: b.count === 0 ? 0.15 : 1,
                }}
              />
              <div
                aria-hidden="true"
                style={{
                  fontSize: 9,
                  color: "#94a3b8",
                  textAlign: "center",
                  whiteSpace: "nowrap",
                  transform: "rotate(-30deg)",
                  transformOrigin: "left top",
                  marginTop: 8,
                  width: 60,
                }}
              >
                {b.bucket_label}
              </div>
            </div>
          );
        })}
      </div>
      {/* SR-only data table: provides accessible alternative to the visual histogram */}
      <table className="sr-only">
        <caption>Distribution of patients by revenue delta</caption>
        <thead>
          <tr>
            <th scope="col">Revenue bucket</th>
            <th scope="col">Patient count</th>
          </tr>
        </thead>
        <tbody>
          {buckets.map((b) => (
            <tr key={b.bucket_label}>
              <th scope="row">{b.bucket_label}</th>
              <td>{b.count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Th({
  children,
  align,
}: {
  children: React.ReactNode;
  align?: "left" | "right" | "center";
}) {
  return (
    <th
      style={{
        padding: "6px 8px",
        textAlign: align ?? "left",
        fontWeight: 600,
        fontSize: 11,
        textTransform: "uppercase",
        letterSpacing: 0.3,
      }}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  align,
  color,
}: {
  children: React.ReactNode;
  align?: "left" | "right" | "center";
  color?: string;
}) {
  return (
    <td
      style={{
        padding: "6px 8px",
        textAlign: align ?? "left",
        color: color ?? "#0f172a",
        fontVariantNumeric: "tabular-nums",
      }}
    >
      {children}
    </td>
  );
}
