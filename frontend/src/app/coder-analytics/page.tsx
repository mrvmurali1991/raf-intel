"use client";

/**
 * /coder-analytics — Personal productivity dashboard + Team analytics view.
 *
 * Two tabs (driven by `?view=team` query string):
 *   * "Me" (default)  — stat tiles for the authenticated user + 30-day sparkline.
 *   * "Team"          — per-coder rows (manager-only; gated by API permission).
 *
 * Sparkline is rendered inline with raw SVG (no chart library dependency).
 * HCC heat-map is rendered as a small table colour-coded by frequency.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import api from "@/lib/api";
import { ChartExportMenu } from "@/components/ui/chart-export-menu";
import { downloadCSV } from "@/lib/csv-export";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface HccTop { hcc: string; count: number }
interface DailyTrend { date: string; accepted: number; dismissed: number; total: number }
interface CoderMetrics {
  coder_user_id: number;
  coder_email: string | null;
  coder_name: string | null;
  date_from: string;
  date_to: string;
  charts_reviewed: number;
  charts_per_hour: number;
  suspects_accepted: number;
  suspects_dismissed: number;
  suspects_force_accepted_no_meat: number;
  avg_time_on_chart_seconds: number;
  ai_acceptance_rate_pct: number;
  specificity_capture_rate_pct: number;
  top_5_accepted_hccs: HccTop[];
  top_5_dismissed_hccs: HccTop[];
  daily_trend: DailyTrend[];
}
interface TeamPayload {
  tenant_id: string;
  date_from: string;
  date_to: string;
  per_coder_rows: CoderMetrics[];
  team_avg_charts_per_hour: number;
  team_median_charts_per_hour: number;
  team_p95_charts_per_hour: number;
  active_coders: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtSeconds(s: number): string {
  if (!s) return "—";
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const r = s % 60;
  return r ? `${m}m ${r}s` : `${m}m`;
}

function StatTile({
  label,
  value,
  subtitle,
  good,
}: {
  label: string;
  value: string | number;
  subtitle?: string;
  good?: "up" | "down" | null;
}) {
  const accent = good === "up" ? "#10B981" : good === "down" ? "#EF4444" : "#3B82F6";
  return (
    <div
      style={{
        border: "1px solid #E2E8F0",
        borderRadius: 10,
        padding: 16,
        background: "white",
        boxShadow: "0 1px 2px rgba(15,23,42,0.04)",
        minWidth: 160,
        flex: 1,
      }}
    >
      <div style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "#64748B" }}>
        {label}
      </div>
      <div style={{ marginTop: 6, fontSize: 26, fontWeight: 700, color: accent, lineHeight: 1.1 }}>
        {value}
      </div>
      {subtitle && <div style={{ marginTop: 4, fontSize: 12, color: "#64748b" }}>{subtitle}</div>}
    </div>
  );
}

function Sparkline({ values, width = 320, height = 56 }: { values: number[]; width?: number; height?: number }) {
  if (!values.length) {
    return <div style={{ fontSize: 12, color: "#64748b" }}>No data in window</div>;
  }
  const max = Math.max(...values, 1);
  const stepX = values.length > 1 ? width / (values.length - 1) : 0;
  const pts = values.map((v, i) => {
    const x = i * stepX;
    const y = height - (v / max) * (height - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const path = `M${pts.join(" L")}`;
  const area = `M0,${height} L${pts.join(" L")} L${width},${height} Z`;
  return (
    <svg width={width} height={height} aria-label="30-day trend">
      <path d={area} fill="#3B82F6" fillOpacity={0.08} />
      <path d={path} fill="none" stroke="#3B82F6" strokeWidth={2} strokeLinejoin="round" />
      {pts.length === 1 && <circle cx={pts[0].split(",")[0]} cy={pts[0].split(",")[1]} r={3} fill="#3B82F6" />}
    </svg>
  );
}

function HccTable({ title, rows, accent }: { title: string; rows: HccTop[]; accent: string }) {
  return (
    <div style={{ border: "1px solid #E2E8F0", borderRadius: 10, background: "white", overflow: "hidden" }}>
      <div style={{ padding: "10px 14px", borderBottom: "1px solid #F1F5F9", fontSize: 12, fontWeight: 600, color: "#0F172A" }}>
        {title}
      </div>
      {rows.length === 0 ? (
        <div style={{ padding: "16px 14px", fontSize: 12, color: "#64748b" }}>No activity in window</div>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <tbody>
            {rows.map((r) => (
              <tr key={r.hcc} style={{ borderTop: "1px solid #F1F5F9" }}>
                <td style={{ padding: "6px 14px", fontWeight: 500 }}>HCC {r.hcc}</td>
                <td style={{ padding: "6px 14px", textAlign: "right", color: accent, fontWeight: 600 }}>{r.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function CoderAnalyticsPage() {
  const router = useRouter();
  const params = useSearchParams();
  const view = params?.get("view") === "team" ? "team" : "me";

  const [me, setMe] = useState<CoderMetrics | null>(null);
  const [team, setTeam] = useState<TeamPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<keyof CoderMetrics>("charts_per_hour");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setErr(null);
      try {
        if (view === "me") {
          const { data } = await api.get<CoderMetrics>("/api/coder-analytics/me");
          if (!cancelled) setMe(data);
        } else {
          const { data } = await api.get<TeamPayload>("/api/coder-analytics/team");
          if (!cancelled) setTeam(data);
        }
      } catch (e) {
        const msg = (e as { message?: string })?.message ?? "Failed to load analytics";
        if (!cancelled) setErr(msg);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [view]);

  const sortedTeam = useMemo(() => {
    if (!team) return [];
    const rows = [...team.per_coder_rows];
    rows.sort((a, b) => {
      const av = (a[sortKey] as number) ?? 0;
      const bv = (b[sortKey] as number) ?? 0;
      return bv - av;
    });
    return rows;
  }, [team, sortKey]);

  return (
    <div style={{ padding: "20px 28px", maxWidth: 1280, margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: "#0F172A", margin: 0 }}>Coder Productivity Analytics</h1>
          <p style={{ fontSize: 13, color: "#64748B", margin: "4px 0 0" }}>
            Industry baseline: 5-10 charts/hr · AI-acceptance ground truth: 60-75%
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={() => router.replace("/coder-analytics")}
            style={tabStyle(view === "me")}
          >
            My Productivity
          </button>
          <button
            onClick={() => router.replace("/coder-analytics?view=team")}
            style={tabStyle(view === "team")}
          >
            Team Analytics
          </button>
        </div>
      </div>

      {loading && <div style={{ padding: 40, color: "#64748b" }}>Loading…</div>}
      {err && (
        <div style={{ padding: 16, border: "1px solid #FCA5A5", background: "#FEF2F2", color: "#991B1B", borderRadius: 8 }}>
          {err}
        </div>
      )}

      {!loading && !err && view === "me" && me && (
        <PersonalDashboard m={me} />
      )}

      {!loading && !err && view === "team" && team && (
        <TeamView team={team} sortedRows={sortedTeam} sortKey={sortKey} onSort={setSortKey} />
      )}
    </div>
  );
}

function tabStyle(active: boolean): React.CSSProperties {
  return {
    background: active ? "#3B82F6" : "white",
    color: active ? "white" : "#0F172A",
    border: "1px solid " + (active ? "#3B82F6" : "#E2E8F0"),
    borderRadius: 8,
    padding: "6px 14px",
    fontSize: 13,
    fontWeight: 500,
    cursor: "pointer",
  };
}

// ---------------------------------------------------------------------------
// Personal dashboard
// ---------------------------------------------------------------------------

function PersonalDashboard({ m }: { m: CoderMetrics }) {
  const trendValues = m.daily_trend.map((d) => d.total);
  const trendRef = useRef<HTMLDivElement | null>(null);
  return (
    <>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
        <StatTile
          label="Charts / hour"
          value={m.charts_per_hour || 0}
          subtitle={`${m.charts_reviewed} charts reviewed`}
          good={m.charts_per_hour >= 5 ? "up" : null}
        />
        <StatTile
          label="AI acceptance rate"
          value={`${m.ai_acceptance_rate_pct.toFixed(1)}%`}
          subtitle={`${m.suspects_accepted} accepted · ${m.suspects_dismissed} dismissed`}
          good={m.ai_acceptance_rate_pct >= 60 ? "up" : null}
        />
        <StatTile
          label="Avg time on chart"
          value={fmtSeconds(m.avg_time_on_chart_seconds)}
          subtitle="Derived from PHI views"
        />
        <StatTile
          label="Specificity capture"
          value={`${m.specificity_capture_rate_pct.toFixed(1)}%`}
          subtitle="Accepted suspects with MEAT"
        />
        <StatTile
          label="Force-accept w/o MEAT"
          value={m.suspects_force_accepted_no_meat}
          subtitle="Audit-risk events"
          good={m.suspects_force_accepted_no_meat === 0 ? "up" : "down"}
        />
      </div>

      <div ref={trendRef} style={{ border: "1px solid #E2E8F0", borderRadius: 10, background: "white", padding: 16, marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#0F172A" }}>Daily review trend</div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ fontSize: 12, color: "#64748B" }}>{m.date_from} → {m.date_to}</div>
            <ChartExportMenu
              filename="coder-daily-trend"
              csvData={m.daily_trend.map((d) => ({
                "Date": d.date,
                "Accepted": d.accepted,
                "Dismissed": d.dismissed,
                "Total": d.total,
              }))}
              chartRef={trendRef as React.RefObject<HTMLElement>}
              rawData={m.daily_trend as unknown as Record<string, unknown>[]}
            />
          </div>
        </div>
        <Sparkline values={trendValues} />
        <div style={{ marginTop: 8, fontSize: 12, color: "#64748B" }}>
          Total decisions in window: <strong>{m.suspects_accepted + m.suspects_dismissed}</strong>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <HccTable title="Top 5 accepted HCCs" rows={m.top_5_accepted_hccs} accent="#10B981" />
        <HccTable title="Top 5 dismissed HCCs" rows={m.top_5_dismissed_hccs} accent="#EF4444" />
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Team view
// ---------------------------------------------------------------------------

function TeamView({
  team,
  sortedRows,
  sortKey,
  onSort,
}: {
  team: TeamPayload;
  sortedRows: CoderMetrics[];
  sortKey: keyof CoderMetrics;
  onSort: (k: keyof CoderMetrics) => void;
}) {
  const histRef = useRef<HTMLDivElement | null>(null);
  const tableRef = useRef<HTMLDivElement | null>(null);

  // Build a simple distribution histogram of charts/hr (5 buckets).
  const cph = sortedRows.map((r) => r.charts_per_hour).filter((v) => v > 0);
  const max = Math.max(...cph, 12);
  const buckets = [0, max * 0.25, max * 0.5, max * 0.75, max];
  const histogram = buckets.slice(0, -1).map((lo, i) => {
    const hi = buckets[i + 1];
    return {
      label: `${lo.toFixed(1)}-${hi.toFixed(1)}`,
      count: cph.filter((v) => v >= lo && v < hi).length,
    };
  });

  return (
    <>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
        <StatTile label="Active coders" value={team.active_coders} />
        <StatTile label="Team avg charts/hr" value={team.team_avg_charts_per_hour} />
        <StatTile label="Median charts/hr" value={team.team_median_charts_per_hour} />
        <StatTile label="P95 charts/hr" value={team.team_p95_charts_per_hour} good="up" />
      </div>

      <div ref={histRef} style={{ border: "1px solid #E2E8F0", borderRadius: 10, background: "white", padding: 16, marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#0F172A" }}>
            Charts/hour distribution
          </div>
          <ChartExportMenu
            filename="coder-charts-per-hour-dist"
            csvData={histogram.map((b) => ({ "Range (charts/hr)": b.label, "Coder Count": b.count }))}
            chartRef={histRef as React.RefObject<HTMLElement>}
            rawData={histogram.map((b) => ({ label: b.label, count: b.count }))}
          />
        </div>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 12, height: 100 }}>
          {histogram.map((b) => {
            const h = Math.max(2, (b.count / Math.max(1, ...histogram.map((x) => x.count))) * 100);
            return (
              <div key={b.label} style={{ flex: 1, textAlign: "center" }}>
                <div style={{
                  height: `${h}%`, background: "#3B82F6", borderRadius: 4, marginBottom: 4,
                }} />
                <div style={{ fontSize: 11, color: "#64748B" }}>{b.label}</div>
                <div style={{ fontSize: 12, fontWeight: 600 }}>{b.count}</div>
              </div>
            );
          })}
        </div>
      </div>

      <div ref={tableRef} style={{ border: "1px solid #E2E8F0", borderRadius: 10, background: "white", overflow: "hidden" }}>
        <div style={{ padding: "10px 14px", borderBottom: "1px solid #F1F5F9", fontSize: 13, fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <span>Per-coder breakdown</span>
          <ChartExportMenu
            filename="coder-team-breakdown"
            csvData={sortedRows.map((r) => ({
              "Coder": r.coder_name ?? `Coder ${r.coder_user_id}`,
              "Email": r.coder_email ?? "",
              "Charts Reviewed": r.charts_reviewed,
              "Charts/hr": r.charts_per_hour,
              "AI Accept %": `${r.ai_acceptance_rate_pct}%`,
              "Avg Time on Chart": fmtSeconds(r.avg_time_on_chart_seconds),
              "Force-accept no MEAT": r.suspects_force_accepted_no_meat,
            }))}
            chartRef={tableRef as React.RefObject<HTMLElement>}
            rawData={sortedRows.map((r) => ({
              coder_id: r.coder_user_id,
              coder_name: r.coder_name ?? "",
              charts_reviewed: r.charts_reviewed,
              charts_per_hour: r.charts_per_hour,
              ai_acceptance_rate_pct: r.ai_acceptance_rate_pct,
              avg_time_on_chart_seconds: r.avg_time_on_chart_seconds,
              force_accept_no_meat: r.suspects_force_accepted_no_meat,
            }))}
          />
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead style={{ background: "#F8FAFC" }}>
            <tr>
              {[
                ["coder_name" as const, "Coder", "left"],
                ["charts_reviewed" as const, "Charts", "right"],
                ["charts_per_hour" as const, "Charts/hr", "right"],
                ["ai_acceptance_rate_pct" as const, "Accept %", "right"],
                ["avg_time_on_chart_seconds" as const, "Avg time/chart", "right"],
                ["suspects_force_accepted_no_meat" as const, "Force-accept no MEAT", "right"],
              ].map(([k, label, align]) => (
                <th
                  key={k as string}
                  onClick={() => onSort(k as keyof CoderMetrics)}
                  style={{
                    padding: "8px 14px",
                    textAlign: align as "left" | "right",
                    fontWeight: 600,
                    color: sortKey === k ? "#3B82F6" : "#0F172A",
                    cursor: "pointer",
                    userSelect: "none",
                  }}
                >
                  {label} {sortKey === k ? "↓" : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sortedRows.map((r) => (
              <tr key={r.coder_user_id} style={{ borderTop: "1px solid #F1F5F9" }}>
                <td style={{ padding: "8px 14px" }}>
                  <div style={{ fontWeight: 500 }}>{r.coder_name ?? `Coder ${r.coder_user_id}`}</div>
                  <div style={{ fontSize: 11, color: "#64748b" }}>{r.coder_email ?? ""}</div>
                </td>
                <td style={{ padding: "8px 14px", textAlign: "right" }}>{r.charts_reviewed}</td>
                <td style={{ padding: "8px 14px", textAlign: "right", fontWeight: 600 }}>{r.charts_per_hour}</td>
                <td style={{ padding: "8px 14px", textAlign: "right" }}>{r.ai_acceptance_rate_pct}%</td>
                <td style={{ padding: "8px 14px", textAlign: "right" }}>{fmtSeconds(r.avg_time_on_chart_seconds)}</td>
                <td style={{ padding: "8px 14px", textAlign: "right", color: r.suspects_force_accepted_no_meat ? "#EF4444" : "#64748B" }}>
                  {r.suspects_force_accepted_no_meat}
                </td>
              </tr>
            ))}
            {sortedRows.length === 0 && (
              <tr>
                <td colSpan={6} style={{ padding: "16px 14px", color: "#64748b", textAlign: "center" }}>
                  No coder activity in window.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
