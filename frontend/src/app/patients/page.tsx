"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { searchPatients } from "@/lib/api";
import { RiskBadge, PageHeader, EmptyState } from "@/components/healthcare-ui";
import { calculateAge } from "@/lib/utils";
import {
  Users,
  Search,
  ChevronRight,
  ChevronLeft,
  ChevronUp,
  ChevronDown,
  AlertTriangle,
  RefreshCw,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Constants & Types
// ---------------------------------------------------------------------------

const PAGE_SIZE = 20;

type SortKey = "name" | "age" | "raf_score" | "hcc_count";
type SortDir = "asc" | "desc";
type RiskFilter = "all" | "high" | "medium" | "low" | "unscored";

const RISK_FILTERS: { key: RiskFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "high", label: "High Risk" },
  { key: "medium", label: "Medium" },
  { key: "low", label: "Low" },
  { key: "unscored", label: "Unscored" },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatLocation(p: any): string {
  const parts: string[] = [];
  if (p.city) parts.push(p.city);
  if (p.state) parts.push(p.state);
  if (parts.length === 0 && p.postal_code) return p.postal_code;
  return parts.join(", ") || "\u2014";
}

function initialsColor(name: string): string {
  const colors = [
    "#2563EB", "#7C3AED", "#DB2777", "#DC2626",
    "#EA580C", "#D97706", "#059669", "#0891B2",
    "#4F46E5", "#9333EA", "#E11D48", "#0D9488",
  ];
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  return colors[Math.abs(hash) % colors.length];
}

function riskBorderColor(score: number | null | undefined): string {
  if (score == null || score === 0) return "#D1D5DB";
  if (score >= 2.0) return "#DC2626";
  if (score >= 1.0) return "#F59E0B";
  if (score >= 0.5) return "#10B981";
  return "#D1D5DB";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function PatientsPage() {
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [riskFilter, setRiskFilter] = useState<RiskFilter>("all");
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: "name", dir: "asc" });
  const [page, setPage] = useState(0);
  const [hoveredRow, setHoveredRow] = useState<number | null>(null);
  const router = useRouter();

  // Server-side search & pagination
  const { data: apiResult, isLoading, isError, refetch } = useQuery({
    queryKey: ["patients", debouncedSearch, page],
    queryFn: () => searchPatients({
      search: debouncedSearch || undefined,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
    placeholderData: (prev: any) => prev,
  });

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search);
      setPage(0);
    }, 400);
    return () => clearTimeout(timer);
  }, [search]);

  // Derived data — sorting and risk filtering are client-side on the current page
  const { rows, total, totalPages } = useMemo(() => {
    let list = (apiResult?.patients ?? []) as any[];
    const serverTotal = apiResult?.total ?? 0;

    if (riskFilter !== "all") {
      list = list.filter((p: any) => {
        const s = p.raf_score ?? 0;
        if (riskFilter === "high") return s > 2.0;
        if (riskFilter === "medium") return s >= 1.0 && s <= 2.0;
        if (riskFilter === "low") return s > 0 && s < 1.0;
        if (riskFilter === "unscored") return !s || s === 0;
        return true;
      });
    }

    list = [...list].sort((a: any, b: any) => {
      let aVal: any, bVal: any;
      switch (sort.key) {
        case "name":
          aVal = `${a.lname} ${a.fname}`.toLowerCase();
          bVal = `${b.lname} ${b.fname}`.toLowerCase();
          break;
        case "age":
          aVal = a.DOB ? calculateAge(a.DOB) : 0;
          bVal = b.DOB ? calculateAge(b.DOB) : 0;
          break;
        case "raf_score":
          aVal = a.raf_score ?? 0;
          bVal = b.raf_score ?? 0;
          break;
        case "hcc_count":
          aVal = a.hcc_count ?? 0;
          bVal = b.hcc_count ?? 0;
          break;
        default:
          aVal = 0;
          bVal = 0;
      }
      if (aVal < bVal) return sort.dir === "asc" ? -1 : 1;
      if (aVal > bVal) return sort.dir === "asc" ? 1 : -1;
      return 0;
    });

    const total = riskFilter !== "all" ? list.length : serverTotal;
    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    // When server-side paginated, don't slice again (already sliced by API)
    const rows = riskFilter !== "all" ? list.slice(0, PAGE_SIZE) : list;
    return { rows, total, totalPages };
  }, [apiResult, debouncedSearch, riskFilter, sort, page]);

  const totalPatients = apiResult?.total ?? 0;

  const handleSort = useCallback((key: SortKey) => {
    setSort((prev) => ({
      key,
      dir: prev.key === key && prev.dir === "asc" ? "desc" : "asc",
    }));
    setPage(0);
  }, []);

  // ---- Error state ----
  if (isError) {
    return (
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "60vh", gap: 16 }}>
        <div style={{ borderRadius: 16, backgroundColor: "#FEF2F2", padding: 20 }}>
          <AlertTriangle size={40} color="#EF4444" />
        </div>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: "#0F172A", margin: 0 }}>Failed to load patients</h2>
        <p style={{ fontSize: 14, color: "#64748B", margin: 0 }}>Check that the server is running and try again.</p>
        <button
          onClick={() => refetch()}
          style={{
            display: "inline-flex", alignItems: "center", gap: 8,
            borderRadius: 8, border: "1px solid #E2E8F0", backgroundColor: "#FFFFFF",
            padding: "8px 16px", fontSize: 14, fontWeight: 500, color: "#475569",
            cursor: "pointer",
          }}
        >
          <RefreshCw size={16} /> Retry
        </button>
      </div>
    );
  }

  // ---- Sort column header (inline in worklist header) ----
  const SortLabel = ({ col, label }: { col: SortKey; label: string }) => {
    const active = sort.key === col;
    return (
      <button
        onClick={() => handleSort(col)}
        style={{
          display: "inline-flex", alignItems: "center", gap: 2,
          background: "none", border: "none", padding: 0, margin: 0,
          cursor: "pointer", fontSize: 11, fontWeight: 600,
          textTransform: "uppercase" as const, letterSpacing: "0.05em",
          color: active ? "#2563EB" : "#94A3B8",
          whiteSpace: "nowrap" as const,
        }}
      >
        {label}
        {active && (sort.dir === "asc" ? <ChevronUp size={12} /> : <ChevronDown size={12} />)}
      </button>
    );
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      {/* ---- Page Header ---- */}
      <PageHeader
        title="Patient Population"
        icon={<Users size={22} />}
        subtitle={!isLoading ? `${totalPatients.toLocaleString()} patients in registry` : undefined}
        actions={
          <div style={{ position: "relative" }}>
            <Search
              size={16}
              style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "#94A3B8", pointerEvents: "none" }}
            />
            <input
              type="text"
              placeholder="Search by name or PID..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search patients"
              style={{
                height: 40, width: 320, borderRadius: 10,
                border: "1px solid #E2E8F0", backgroundColor: "#FFFFFF",
                paddingLeft: 38, paddingRight: 14,
                fontSize: 14, color: "#0F172A",
                outline: "none",
              }}
            />
          </div>
        }
      />

      {/* ---- Filter Strip ---- */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        flexWrap: "wrap", gap: 8, marginBottom: 16,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          {RISK_FILTERS.map((r) => {
            const active = riskFilter === r.key;
            return (
              <button
                key={r.key}
                onClick={() => { setRiskFilter(r.key); setPage(0); }}
                className="rci-filter-pill"
                style={{
                  display: "inline-flex", alignItems: "center",
                  padding: "6px 16px", borderRadius: 999,
                  fontSize: 13, fontWeight: 500, cursor: "pointer",
                  border: active ? "1px solid #2563EB" : "1px solid #D1D5DB",
                  backgroundColor: active ? "#2563EB" : "#FFFFFF",
                  color: active ? "#FFFFFF" : "#6B7280",
                  transition: "all 0.15s ease",
                }}
              >
                {r.label}
              </button>
            );
          })}
          {(riskFilter !== "all" || debouncedSearch) && (
            <button
              onClick={() => { setRiskFilter("all"); setSearch(""); setPage(0); }}
              style={{
                background: "none", border: "none", padding: "6px 10px",
                fontSize: 13, fontWeight: 500, color: "#94A3B8", cursor: "pointer",
              }}
            >
              Clear filters
            </button>
          )}
        </div>
        {!isLoading && (
          <span style={{ fontSize: 13, color: "#64748B", whiteSpace: "nowrap" }}>
            Showing <strong style={{ color: "#0F172A" }}>{total.toLocaleString()}</strong> of{" "}
            <strong style={{ color: "#0F172A" }}>{totalPatients.toLocaleString()}</strong> patients
          </span>
        )}
      </div>

      {/* ---- Worklist Container ---- */}
      <div style={{
        backgroundColor: "#FFFFFF", borderRadius: 12,
        border: "1px solid #E2E8F0", overflow: "hidden",
      }}>
        {/* Column sort header */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "minmax(220px, 2fr) 80px 140px 1fr 90px 70px 28px",
          alignItems: "center", padding: "10px 16px 10px 20px",
          backgroundColor: "#F8FAFC", borderBottom: "1px solid #E2E8F0",
          gap: 8,
        }}>
          <SortLabel col="name" label="Patient" />
          <SortLabel col="age" label="Age / Sex" />
          <span style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "#94A3B8" }}>Location</span>
          <SortLabel col="raf_score" label="RAF Score" />
          <SortLabel col="hcc_count" label="HCCs" />
          <span style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "#94A3B8" }}>Status</span>
          <span />
        </div>

        {/* ---- Loading Skeleton ---- */}
        {isLoading && Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(220px, 2fr) 80px 140px 1fr 90px 70px 28px",
              alignItems: "center", padding: "0 16px 0 20px", height: 64,
              borderBottom: "1px solid #F1F5F9", gap: 8,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ width: 36, height: 36, borderRadius: 18, backgroundColor: "#F1F5F9", animation: "pulse 1.5s ease-in-out infinite" }} />
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <div style={{ width: 120, height: 12, borderRadius: 4, backgroundColor: "#F1F5F9", animation: "pulse 1.5s ease-in-out infinite" }} />
                <div style={{ width: 60, height: 10, borderRadius: 4, backgroundColor: "#F1F5F9", animation: "pulse 1.5s ease-in-out infinite" }} />
              </div>
            </div>
            <div style={{ width: 36, height: 12, borderRadius: 4, backgroundColor: "#F1F5F9", animation: "pulse 1.5s ease-in-out infinite" }} />
            <div style={{ width: 80, height: 12, borderRadius: 4, backgroundColor: "#F1F5F9", animation: "pulse 1.5s ease-in-out infinite" }} />
            <div style={{ width: 64, height: 24, borderRadius: 12, backgroundColor: "#F1F5F9", animation: "pulse 1.5s ease-in-out infinite" }} />
            <div style={{ width: 48, height: 20, borderRadius: 6, backgroundColor: "#F1F5F9", animation: "pulse 1.5s ease-in-out infinite" }} />
            <div style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: "#F1F5F9", animation: "pulse 1.5s ease-in-out infinite" }} />
            <div />
          </div>
        ))}

        {/* ---- Empty State ---- */}
        {!isLoading && rows.length === 0 && (
          <EmptyState
            icon={<Search size={24} />}
            title="No patients match your criteria"
            description="Try broadening your search or adjusting the risk filter."
          />
        )}

        {/* ---- Patient Rows ---- */}
        {rows.map((p: any) => {
          const pid = Math.round(Number(p.pid));
          const age = p.DOB ? calculateAge(p.DOB) : null;
          const score = p.raf_score ?? 0;
          const hccCount = p.hcc_count ?? 0;
          const scored = score > 0;
          const fullName = `${p.lname}, ${p.fname}`;
          const initials = `${(p.fname || "?")[0]}${(p.lname || "?")[0]}`.toUpperCase();
          const sexLabel = p.sex === "Female" ? "F" : p.sex === "Male" ? "M" : p.sex ? p.sex[0] : "\u2014";
          const bgColor = initialsColor(fullName);
          const isHovered = hoveredRow === pid;

          return (
            <div
              key={p.pid}
              onClick={() => router.push(`/patients/${pid}`)}
              onMouseEnter={() => setHoveredRow(pid)}
              onMouseLeave={() => setHoveredRow(null)}
              style={{
                display: "grid",
                gridTemplateColumns: "minmax(220px, 2fr) 80px 140px 1fr 90px 70px 28px",
                alignItems: "center",
                padding: "0 16px 0 0",
                height: 64,
                borderBottom: "1px solid #F1F5F9",
                borderLeft: `4px solid ${riskBorderColor(scored ? score : null)}`,
                paddingLeft: 16,
                backgroundColor: isHovered ? "#EFF6FF" : "#FFFFFF",
                cursor: "pointer",
                transition: "background-color 0.15s ease",
                gap: 8,
              }}
            >
              {/* Patient name + initials */}
              <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                <div style={{
                  width: 36, height: 36, borderRadius: 18, flexShrink: 0,
                  backgroundColor: `${bgColor}1A`, color: bgColor,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 13, fontWeight: 700,
                }}>
                  {initials}
                </div>
                <div style={{ minWidth: 0 }}>
                  <div style={{
                    display: "flex", alignItems: "center", gap: 6,
                  }}>
                    <span style={{ fontSize: 14, fontWeight: 600, color: "#0F172A", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {fullName}
                    </span>
                    <span style={{ fontSize: 12, color: "#94A3B8", fontFamily: "monospace", whiteSpace: "nowrap" }}>
                      #{pid}
                    </span>
                  </div>
                </div>
              </div>

              {/* Age / Sex */}
              <span style={{ fontSize: 12, color: "#64748B" }}>
                {age !== null ? `${age} ${sexLabel}` : sexLabel}
              </span>

              {/* Location */}
              <span style={{ fontSize: 12, color: "#64748B", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {formatLocation(p)}
              </span>

              {/* RAF Score */}
              <div>
                {scored ? (
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{
                      fontSize: 15, fontWeight: 700, color: riskBorderColor(score),
                      fontFamily: "monospace",
                    }}>
                      {Number(score).toFixed(2)}
                    </span>
                    <RiskBadge score={score} size="sm" />
                  </div>
                ) : (
                  <span style={{ fontSize: 13, color: "#D1D5DB" }}>{"\u2014"}</span>
                )}
              </div>

              {/* HCC Count */}
              <div>
                {hccCount > 0 ? (
                  <span style={{
                    display: "inline-flex", alignItems: "center",
                    padding: "3px 8px", borderRadius: 6,
                    backgroundColor: "#F1F5F9", fontSize: 12, fontWeight: 600,
                    color: "#475569",
                  }}>
                    {hccCount} HCCs
                  </span>
                ) : (
                  <span style={{ fontSize: 12, color: "#D1D5DB" }}>{"\u2014"}</span>
                )}
              </div>

              {/* Status dot */}
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{
                  width: 8, height: 8, borderRadius: 4,
                  backgroundColor: scored ? "#10B981" : "#D1D5DB",
                }} />
                <span style={{ fontSize: 11, color: scored ? "#059669" : "#9CA3AF", fontWeight: 500 }}>
                  {scored ? "Analyzed" : "Pending"}
                </span>
              </div>

              {/* Chevron */}
              <ChevronRight size={16} color={isHovered ? "#2563EB" : "#CBD5E1"} />
            </div>
          );
        })}

        {/* ---- Pagination ---- */}
        {!isLoading && totalPages > 1 && (
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "center",
            gap: 16, padding: "14px 20px",
            borderTop: "1px solid #E2E8F0", backgroundColor: "#F8FAFC",
          }}>
            <button
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
              style={{
                display: "inline-flex", alignItems: "center", gap: 4,
                padding: "6px 14px", borderRadius: 8,
                border: "1px solid #E2E8F0", backgroundColor: "#FFFFFF",
                fontSize: 13, fontWeight: 500, color: page === 0 ? "#CBD5E1" : "#475569",
                cursor: page === 0 ? "not-allowed" : "pointer",
                opacity: page === 0 ? 0.5 : 1,
              }}
              aria-label="Previous page"
            >
              <ChevronLeft size={14} /> Previous
            </button>

            <span style={{ fontSize: 13, color: "#64748B" }}>
              Page <strong style={{ color: "#0F172A" }}>{page + 1}</strong> of <strong style={{ color: "#0F172A" }}>{totalPages}</strong>
            </span>

            <button
              disabled={page >= totalPages - 1}
              onClick={() => setPage((p) => p + 1)}
              style={{
                display: "inline-flex", alignItems: "center", gap: 4,
                padding: "6px 14px", borderRadius: 8,
                border: "1px solid #E2E8F0", backgroundColor: "#FFFFFF",
                fontSize: 13, fontWeight: 500,
                color: page >= totalPages - 1 ? "#CBD5E1" : "#475569",
                cursor: page >= totalPages - 1 ? "not-allowed" : "pointer",
                opacity: page >= totalPages - 1 ? 0.5 : 1,
              }}
              aria-label="Next page"
            >
              Next <ChevronRight size={14} />
            </button>
          </div>
        )}
      </div>

      {/* Pulse animation keyframes */}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
        /* WCAG 2.5.5 — touch targets ≥44px on mobile */
        @media (max-width: 768px) {
          .rci-filter-pill {
            min-height: 44px !important;
            padding-top: 5px !important;
            padding-bottom: 5px !important;
          }
        }
      `}</style>
    </div>
  );
}
