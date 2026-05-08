"use client";

/**
 * RAF Financial Forecast Card.
 *
 * Surfaces the projected $ revenue impact of accepting a patient's open
 * suspect conditions and re-capturing prior-year chronic HCCs.  Backed by
 * GET /api/forecast/patient/{pid}.
 *
 * Design language matches the rest of the patient view: inline-styled
 * tokens (slate / blue / emerald / amber palette), no Tailwind dependency
 * required.  Recharts is imported dynamically when by-suspect data exists
 * so the bundle stays small for empty states.
 */
import React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
} from "recharts";
import { getPatientForecast, type PatientForecast } from "@/lib/api";

// ---------------------------------------------------------------------------
// Design tokens (mirrors the C palette in app/patients/[pid]/page.tsx)
// ---------------------------------------------------------------------------
const T = {
  white: "#FFFFFF",
  slate900: "#0F172A",
  slate700: "#334155",
  slate500: "#64748B",
  slate400: "#94A3B8",
  slate300: "#CBD5E1",
  slate200: "#E2E8F0",
  slate100: "#F1F5F9",
  emerald600: "#059669",
  emerald500: "#10B981",
  emerald50: "#ECFDF5",
  amber600: "#D97706",
  amber500: "#F59E0B",
  amber50: "#FFFBEB",
  red500: "#EF4444",
  red50: "#FEF2F2",
  blue600: "#2563EB",
  blue50: "#EFF6FF",
};

function formatUSD(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `$${(n / 1_000).toFixed(1)}k`;
  return `$${Math.round(n).toLocaleString()}`;
}

function formatRAF(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(3)}`;
}

interface Props {
  pid: number | string;
  year?: number;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export default function RAFForecastCard({ pid, year }: Props) {
  const q = useQuery<PatientForecast>({
    queryKey: ["patient-forecast", pid, year],
    queryFn: () => getPatientForecast(pid, year),
    // Forecast can be expensive; cache for 60s
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  if (q.isLoading) {
    return (
      <Card>
        <div style={{ color: T.slate500, fontSize: 13 }}>
          Calculating financial forecast…
        </div>
      </Card>
    );
  }

  if (q.isError || !q.data) {
    return (
      <Card>
        <div style={{ color: T.red500, fontSize: 13 }}>
          Forecast unavailable. {(q.error as Error)?.message ?? ""}
        </div>
      </Card>
    );
  }

  const f = q.data;
  const netDelta = f.net_projected_revenue - f.current_revenue;
  const positive = netDelta >= 0;

  return (
    <Card>
      {/* Header --------------------------------------------------------- */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 14,
        }}
      >
        <div>
          <div
            style={{
              fontSize: 10,
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.06em",
              color: T.slate400,
              marginBottom: 4,
            }}
          >
            RAF Financial Forecast
          </div>
          <div
            style={{
              fontSize: 18,
              fontWeight: 700,
              color: T.slate900,
            }}
          >
            ${f.suspect_lift_revenue.toLocaleString(undefined, {
              maximumFractionDigits: 0,
            })}{" "}
            <span style={{ fontSize: 13, color: T.slate500, fontWeight: 500 }}>
              opportunity
            </span>
          </div>
        </div>

        <div
          style={{
            padding: "4px 10px",
            borderRadius: 999,
            background: positive ? T.emerald50 : T.red50,
            color: positive ? T.emerald600 : T.red500,
            fontSize: 11,
            fontWeight: 700,
          }}
        >
          {positive ? "▲" : "▼"} {formatUSD(Math.abs(netDelta))}
        </div>
      </div>

      {/* Metrics row ---------------------------------------------------- */}
      <div
        className="raf-forecast-metrics"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 12,
          padding: "12px 0",
          borderTop: `1px solid ${T.slate100}`,
          borderBottom: `1px solid ${T.slate100}`,
        }}
      >
        <Metric
          label="Current"
          raf={f.current_raf}
          revenue={f.current_revenue}
          color={T.slate700}
        />
        <Metric
          label="Suspect Lift"
          raf={f.suspect_lift_raf}
          revenue={f.suspect_lift_revenue}
          color={T.emerald600}
          positive
        />
        <Metric
          label="At Risk"
          raf={-f.removal_risk_raf}
          revenue={-f.removal_risk_revenue}
          color={T.amber600}
        />
        <Metric
          label="Projected"
          raf={f.net_projected_raf}
          revenue={f.net_projected_revenue}
          color={T.blue600}
        />
      </div>

      {/* By-suspect chart ----------------------------------------------- */}
      {f.by_suspect.length > 0 ? (
        <div style={{ marginTop: 16 }}>
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.04em",
              color: T.slate500,
              marginBottom: 8,
            }}
          >
            Top Suspects · $ Lift Per HCC
          </div>
          <div style={{ width: "100%", height: 140 }}>
            <ResponsiveContainer>
              <BarChart
                data={f.by_suspect.slice(0, 6).map((s) => ({
                  name: `HCC ${s.hcc}`,
                  lift: s.lift_revenue,
                  confidence: s.confidence,
                }))}
                layout="vertical"
                margin={{ top: 4, right: 16, bottom: 0, left: 16 }}
              >
                <XAxis
                  type="number"
                  tickFormatter={(v) => formatUSD(v)}
                  stroke={T.slate400}
                  fontSize={10}
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={70}
                  stroke={T.slate500}
                  fontSize={11}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip
                  formatter={(value: any) => formatUSD(Number(value))}
                  cursor={{ fill: T.slate100 }}
                  contentStyle={{
                    border: `1px solid ${T.slate200}`,
                    borderRadius: 6,
                    fontSize: 12,
                  }}
                />
                <Bar dataKey="lift" radius={[0, 4, 4, 0]}>
                  {f.by_suspect.slice(0, 6).map((s, idx) => (
                    <Cell
                      key={idx}
                      fill={
                        s.confidence >= 0.75
                          ? T.emerald500
                          : s.confidence >= 0.5
                            ? T.blue600
                            : T.amber500
                      }
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      ) : (
        <div
          style={{
            marginTop: 14,
            fontSize: 12,
            color: T.slate500,
            fontStyle: "italic",
          }}
        >
          No open suspects.  Run a suspect scan to surface coding opportunities.
        </div>
      )}

      {/* Footer assumptions -------------------------------------------- */}
      <div
        style={{
          marginTop: 12,
          paddingTop: 10,
          borderTop: `1px solid ${T.slate100}`,
          fontSize: 10,
          color: T.slate400,
          lineHeight: 1.5,
        }}
      >
        Projection = Σ(coefficient × confidence) × ${f.base_rate.toLocaleString()} PMPY ·
        segment {f.model_segment} · persistence {Math.round(f.persistence_assumption * 100)}%
      </div>
      <style>{`
        @media (max-width: 640px) {
          .raf-forecast-metrics { grid-template-columns: repeat(2, 1fr) !important; }
        }
      `}</style>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------
function Card({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        background: T.white,
        border: `1px solid ${T.slate200}`,
        borderRadius: 12,
        padding: 16,
        boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)",
      }}
    >
      {children}
    </div>
  );
}

function Metric({
  label,
  raf,
  revenue,
  color,
  positive = false,
}: {
  label: string;
  raf: number;
  revenue: number;
  color: string;
  positive?: boolean;
}) {
  return (
    <div>
      <div
        style={{
          fontSize: 10,
          fontWeight: 600,
          textTransform: "uppercase",
          letterSpacing: "0.04em",
          color: T.slate400,
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: 16, fontWeight: 700, color, lineHeight: 1.1 }}>
        {revenue >= 0 || positive
          ? formatUSD(Math.abs(revenue))
          : `−${formatUSD(Math.abs(revenue))}`}
      </div>
      <div
        style={{
          fontSize: 11,
          color: T.slate500,
          fontFamily: "monospace",
          marginTop: 2,
        }}
      >
        {formatRAF(raf)} RAF
      </div>
    </div>
  );
}
