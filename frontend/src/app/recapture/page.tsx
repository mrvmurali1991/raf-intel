"use client";

import React, { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { RefreshCw, Download, Calendar, Search, ChevronLeft, ChevronRight, ArrowUpDown, AlertTriangle } from "lucide-react";
import { getRecaptureGapsReport } from "@/lib/api";
import { StatCard, PageHeader, EmptyState } from "@/components/healthcare-ui";

// ─── Types ──────────────────────────────────────────────────────────────────

interface Gap {
  pid: string;
  first_name: string;
  last_name: string;
  condition: string;
  icd_code: string;
  onset_date: string;
}

interface TopCondition {
  icd_code: string;
  condition: string;
  gap_count: number;
}

interface RecaptureReport {
  measurement_year: number;
  total_gaps: number;
  patients_affected: number;
  gaps: Gap[];
  top_conditions: TopCondition[];
}

// ─── Constants ──────────────────────────────────────────────────────────────

const REVENUE_PER_GAP = 3000;
const PAGE_SIZE = 25;

const colors = {
  primary: "#2563EB",
  slate900: "#0F172A",
  slate600: "#475569",
  slate400: "#94A3B8",
  slate200: "#E2E8F0",
  slate100: "#F1F5F9",
  slate50: "#F8FAFC",
  white: "#FFFFFF",
  red600: "#DC2626",
  amber500: "#F59E0B",
  emerald500: "#10B981",
  subtleText: "#64748B",
};

// ─── Helpers ────────────────────────────────────────────────────────────────

function daysSince(dateStr: string): number {
  const diff = Date.now() - new Date(dateStr).getTime();
  return Math.floor(diff / (1000 * 60 * 60 * 24));
}

function priorityFromDays(days: number): { label: string; color: string; rank: number; border: string } {
  if (days > 365) return { label: "High", color: colors.red600, rank: 3, border: "#DC2626" };
  if (days >= 180) return { label: "Medium", color: colors.amber500, rank: 2, border: "#F59E0B" };
  return { label: "Low", color: colors.emerald500, rank: 1, border: "#10B981" };
}

function formatCurrency(n: number): string {
  return "$" + n.toLocaleString("en-US");
}

type SortKey = "priority" | "name" | "condition";

// ─── Component ──────────────────────────────────────────────────────────────

export default function RecapturePage() {
  const router = useRouter();
  const [year, setYear] = useState(new Date().getFullYear());
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<SortKey>("priority");
  const [page, setPage] = useState(1);

  const { data, isLoading, isError, refetch } = useQuery<RecaptureReport>({
    queryKey: ["recapture-gaps", year],
    queryFn: () => getRecaptureGapsReport(year) as unknown as Promise<RecaptureReport>,
  });

  // ── Derived data ────────────────────────────────────────────────────────

  const enrichedGaps = useMemo(() => {
    if (!data?.gaps?.length) return [];
    return data.gaps.map((g) => {
      const days = daysSince(g.onset_date);
      return { ...g, days, priority: priorityFromDays(days) };
    });
  }, [data]);

  const filtered = useMemo(() => {
    let list = enrichedGaps;
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        (g) =>
          g.first_name.toLowerCase().includes(q) ||
          g.last_name.toLowerCase().includes(q)
      );
    }
    list = [...list].sort((a, b) => {
      if (sortBy === "priority") return b.priority.rank - a.priority.rank;
      if (sortBy === "name") return `${a.last_name} ${a.first_name}`.localeCompare(`${b.last_name} ${b.first_name}`);
      return a.condition.localeCompare(b.condition);
    });
    return list;
  }, [enrichedGaps, search, sortBy]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paged = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  // Reset page on filter change
  React.useEffect(() => { setPage(1); }, [search, sortBy, year]);

  // ── CSV Export ──────────────────────────────────────────────────────────

  function exportCSV() {
    if (!filtered.length) return;
    const header = "Patient,Condition,ICD-10,Last Coded,Days Since,Priority\n";
    const rows = filtered.map((g) =>
      `"${g.last_name}, ${g.first_name}","${g.condition}","${g.icd_code}","${g.onset_date}",${g.days},${g.priority.label}`
    ).join("\n");
    const blob = new Blob([header + rows], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `recapture-gaps-${year}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ── Render ──────────────────────────────────────────────────────────────

  const thStyle: React.CSSProperties = {
    padding: "12px 14px",
    fontSize: 11,
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "0.06em",
    color: colors.slate400,
    textAlign: "left",
    borderBottom: `2px solid ${colors.slate200}`,
    whiteSpace: "nowrap",
    background: colors.slate50,
  };

  const tdStyle: React.CSSProperties = {
    padding: "12px 14px",
    fontSize: 13,
    color: colors.slate900,
    borderBottom: `1px solid ${colors.slate100}`,
  };

  if (isLoading) {
    return (
      <div style={{ padding: 32 }}>
        <PageHeader title="Recapture Gaps" subtitle="Loading recapture opportunities…" />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 24 }}>
          {[1, 2, 3].map((i) => (
            <div key={i} className="premium-card shimmer" style={{ height: 100, borderRadius: 12 }} />
          ))}
        </div>
        <div className="premium-card shimmer" style={{ height: 300, borderRadius: 12 }} />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div style={{ padding: 32 }}>
        <PageHeader title="Recapture Gaps" />
        <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "14px 18px", borderRadius: 10, background: "#FEF2F2", border: "1px solid #FECACA", color: "#B91C1C", fontSize: 14, marginTop: 16 }}>
          <AlertTriangle size={18} />
          <span style={{ flex: 1 }}>Failed to load recapture data. Please try again.</span>
          <button
            type="button"
            onClick={() => refetch()}
            style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "6px 12px", borderRadius: 8, border: "1px solid #FECACA", background: "#fff", color: "#B91C1C", fontSize: 13, fontWeight: 600, cursor: "pointer" }}
          >
            <RefreshCw size={14} /> Retry
          </button>
        </div>
      </div>
    );
  }

  const maxConditionCount = (data.top_conditions ?? []).length > 0
    ? Math.max(...(data.top_conditions ?? []).map((c) => c.gap_count))
    : 1;

  const sortOptions: { key: SortKey; label: string }[] = [
    { key: "priority", label: "Priority" },
    { key: "name", label: "Patient Name" },
    { key: "condition", label: "Condition" },
  ];

  return (
    <div style={{ padding: 32, maxWidth: 1200, margin: "0 auto" }}>
      {/* Header */}
      <div className="animate-fade-in">
        <PageHeader
          title="Recapture Gaps"
          subtitle="Chronic conditions from prior years requiring annual recapture for RAF optimization"
          icon={<RefreshCw size={22} />}
          actions={
            <select
              value={year}
              onChange={(e) => setYear(Number(e.target.value))}
              style={{
                padding: "8px 12px",
                borderRadius: 8,
                border: `1px solid ${colors.slate200}`,
                fontSize: 13,
                fontWeight: 600,
                color: colors.slate900,
                background: colors.white,
                cursor: "pointer",
              }}
            >
              {Array.from({length: 3}, (_, i) => new Date().getFullYear() - i).map(yr => (
                <option key={yr} value={yr}>{yr}</option>
              ))}
            </select>
          }
        />
      </div>

      {/* Summary Strip */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 24 }}>
        <div className="animate-fade-in stagger-1">
          <StatCard
            label="Total Recapture Gaps"
            value={(data.total_gaps ?? 0).toLocaleString()}
            color={colors.amber500}
            icon={<RefreshCw size={18} />}
          />
        </div>
        <div className="animate-fade-in stagger-2">
          <StatCard
            label="Patients Affected"
            value={(data.patients_affected ?? 0).toLocaleString()}
            color={colors.primary}
            icon={<Calendar size={18} />}
          />
        </div>
        <div className="animate-fade-in stagger-3">
          <StatCard
            label="Estimated Revenue at Risk"
            value={formatCurrency((data.total_gaps ?? 0) * REVENUE_PER_GAP)}
            color={colors.red600}
            icon={<ArrowUpDown size={18} />}
          />
        </div>
      </div>

      {/* Top Conditions */}
      {(data.top_conditions ?? []).length > 0 && (
        <div className="premium-card animate-slide-up stagger-4" style={{ padding: 24, marginBottom: 24 }}>
          <h3 className="gradient-text" style={{ margin: "0 0 16px", fontSize: 16, fontWeight: 700 }}>
            Most Common Uncaptured Conditions
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {(data.top_conditions ?? []).slice(0, 10).map((c, idx) => (
              <div
                key={c.icd_code}
                className="hover-lift"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  padding: "8px 12px",
                  borderRadius: 8,
                  background: idx % 2 === 0 ? colors.slate50 : "transparent",
                  transition: "all 0.2s ease",
                }}
              >
                <span style={{ width: 24, fontSize: 11, fontWeight: 700, color: colors.slate400, flexShrink: 0, textAlign: "center" }}>
                  {idx + 1}
                </span>
                <span style={{ width: 220, fontSize: 13, color: colors.slate900, fontWeight: 500, flexShrink: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {c.condition}
                </span>
                <span style={{ width: 72, fontSize: 11, fontWeight: 600, color: colors.primary, flexShrink: 0, fontFamily: "monospace" }}>
                  {c.icd_code}
                </span>
                <div style={{ flex: 1, height: 8, borderRadius: 4, background: colors.slate200, overflow: "hidden" }}>
                  <div
                    style={{
                      height: "100%",
                      width: `${(c.gap_count / maxConditionCount) * 100}%`,
                      borderRadius: 4,
                      background: "linear-gradient(90deg, #2563EB, #3B82F6)",
                      transition: "width 0.6s cubic-bezier(0.4, 0, 0.2, 1)",
                    }}
                  />
                </div>
                <span className="tabular-nums" style={{ width: 40, fontSize: 12, fontWeight: 700, color: colors.slate900, textAlign: "right", flexShrink: 0 }}>
                  {c.gap_count}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Patient Worklist */}
      <div className="premium-card animate-slide-up stagger-5" style={{ padding: 24, marginBottom: 24 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16, flexWrap: "wrap", gap: 12 }}>
          <h3 className="gradient-text" style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>
            Patients Requiring Recapture
          </h3>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {/* Search */}
            <div style={{ position: "relative" }}>
              <Search size={14} style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: colors.slate400 }} />
              <input
                type="text"
                placeholder="Search patient..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                style={{
                  padding: "7px 10px 7px 30px",
                  borderRadius: 20,
                  border: `1px solid ${colors.slate200}`,
                  fontSize: 13,
                  color: colors.slate900,
                  width: 200,
                  outline: "none",
                  transition: "border-color 0.2s, box-shadow 0.2s",
                }}
                onFocus={(e) => {
                  e.currentTarget.style.borderColor = colors.primary;
                  e.currentTarget.style.boxShadow = `0 0 0 3px ${colors.primary}1A`;
                }}
                onBlur={(e) => {
                  e.currentTarget.style.borderColor = colors.slate200;
                  e.currentTarget.style.boxShadow = "none";
                }}
              />
            </div>
            {/* Sort Pills */}
            <div style={{ display: "flex", gap: 4, background: colors.slate100, borderRadius: 20, padding: 3 }}>
              {sortOptions.map((opt) => (
                <button
                  key={opt.key}
                  onClick={() => setSortBy(opt.key)}
                  className="btn-press"
                  style={{
                    padding: "5px 12px",
                    borderRadius: 16,
                    border: "none",
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: "pointer",
                    transition: "all 0.2s ease",
                    background: sortBy === opt.key ? colors.primary : "transparent",
                    color: sortBy === opt.key ? colors.white : colors.slate600,
                    boxShadow: sortBy === opt.key ? "0 1px 3px rgba(37,99,235,0.3)" : "none",
                  }}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {filtered.length === 0 ? (
          <EmptyState title="No recapture gaps found" description="All chronic conditions have been recaptured for the selected year." />
        ) : (
          <>
            <div style={{ overflowX: "auto", borderRadius: 10, border: `1px solid ${colors.slate200}` }}>
              <table style={{ width: "100%", borderCollapse: "collapse" }}>
                <thead>
                  <tr>
                    <th style={thStyle}>Patient</th>
                    <th style={thStyle}>Condition</th>
                    <th style={thStyle}>ICD-10</th>
                    <th style={thStyle}>Last Coded</th>
                    <th style={thStyle}>Days Since</th>
                    <th style={thStyle}>Priority</th>
                  </tr>
                </thead>
                <tbody>
                  {paged.map((g, i) => (
                    <tr
                      key={`${g.pid}-${g.icd_code}-${i}`}
                      onClick={() => router.push(`/patients/${g.pid}`)}
                      style={{
                        cursor: "pointer",
                        transition: "all 0.15s ease",
                        borderLeft: `3px solid ${g.priority.border}`,
                        background: i % 2 === 0 ? colors.white : colors.slate50,
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.background = `${g.priority.border}08`;
                        e.currentTarget.style.transform = "scale(1.002)";
                        e.currentTarget.style.boxShadow = "0 1px 4px rgba(0,0,0,0.06)";
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.background = i % 2 === 0 ? colors.white : colors.slate50;
                        e.currentTarget.style.transform = "none";
                        e.currentTarget.style.boxShadow = "none";
                      }}
                    >
                      <td style={{ ...tdStyle, fontWeight: 600, color: colors.primary }}>
                        {g.last_name}, {g.first_name}
                      </td>
                      <td style={tdStyle}>{g.condition}</td>
                      <td className="tabular-nums" style={{ ...tdStyle, fontFamily: "monospace", fontSize: 12 }}>{g.icd_code}</td>
                      <td className="tabular-nums" style={{ ...tdStyle, color: colors.subtleText }}>{new Date(g.onset_date).toLocaleDateString()}</td>
                      <td className="tabular-nums" style={{ ...tdStyle, fontWeight: 600 }}>{g.days}</td>
                      <td style={tdStyle}>
                        <span
                          style={{
                            display: "inline-block",
                            padding: "3px 10px",
                            borderRadius: 999,
                            fontSize: 11,
                            fontWeight: 600,
                            color: g.priority.color,
                            backgroundColor: `${g.priority.color}1A`,
                          }}
                        >
                          {g.priority.label}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 16, fontSize: 13, color: colors.subtleText }}>
              <span className="tabular-nums">
                Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, filtered.length)} of {filtered.length}
              </span>
              <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="btn-press"
                  style={{
                    padding: "6px 10px",
                    borderRadius: 6,
                    border: `1px solid ${colors.slate200}`,
                    background: colors.white,
                    cursor: page === 1 ? "not-allowed" : "pointer",
                    opacity: page === 1 ? 0.4 : 1,
                    display: "flex",
                    alignItems: "center",
                    transition: "all 0.15s",
                  }}
                >
                  <ChevronLeft size={14} />
                </button>
                <span className="tabular-nums" style={{ padding: "0 8px", fontWeight: 600, color: colors.slate900 }}>
                  {page} / {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="btn-press"
                  style={{
                    padding: "6px 10px",
                    borderRadius: 6,
                    border: `1px solid ${colors.slate200}`,
                    background: colors.white,
                    cursor: page === totalPages ? "not-allowed" : "pointer",
                    opacity: page === totalPages ? 0.4 : 1,
                    display: "flex",
                    alignItems: "center",
                    transition: "all 0.15s",
                  }}
                >
                  <ChevronRight size={14} />
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Action Panel */}
      <div
        className="premium-card animate-slide-up stagger-6"
        style={{
          padding: 24,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          background: `linear-gradient(135deg, ${colors.slate50}, ${colors.white})`,
        }}
      >
        <div>
          <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: colors.slate900 }}>
            Schedule Wellness Visits
          </p>
          <p style={{ margin: "4px 0 0", fontSize: 12, color: colors.subtleText }}>
            Prioritize patients with high-priority recapture gaps for annual wellness visits to ensure chronic conditions are documented.
          </p>
        </div>
        <button
          onClick={exportCSV}
          className="btn-press"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "10px 20px",
            borderRadius: 8,
            border: "none",
            background: "linear-gradient(135deg, #2563EB, #1D4ED8)",
            color: colors.white,
            fontSize: 13,
            fontWeight: 600,
            cursor: "pointer",
            flexShrink: 0,
            boxShadow: "0 2px 8px rgba(37,99,235,0.3)",
            transition: "all 0.2s ease",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.boxShadow = "0 4px 14px rgba(37,99,235,0.4)";
            e.currentTarget.style.transform = "translateY(-1px)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.boxShadow = "0 2px 8px rgba(37,99,235,0.3)";
            e.currentTarget.style.transform = "none";
          }}
        >
          <Download size={14} />
          Export to CSV
        </button>
      </div>
    </div>
  );
}
