"use client";

/**
 * /attestations — Provider Attestation Queue
 *
 * Renders the full list of provider attestations with KPI summary cards,
 * status filter tabs, and a sortable table.
 *
 * Data:
 *   GET /api/attestations/dashboard  → { pending, attested, rejected, deferred, total, attestation_rate }
 *   GET /api/attestations            → { count, offset, attestations: [...] }
 *
 * Attestation row fields (from provider_attestations table):
 *   id, patient_id, hcc_code, hcc_description, icd10_code, icd10_description,
 *   provider_npi, status, source, created_at, updated_at, attestation_type,
 *   reject_reason, clinical_justification, deferred_until
 */

import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import WorkflowProgressBar from "@/components/WorkflowProgressBar";
import WorkflowHandoffBanner from "@/components/WorkflowHandoffBanner";
import {
  ClipboardCheck,
  CheckCircle2,
  XCircle,
  Clock,
  AlertCircle,
  Search,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
} from "lucide-react";
import { PageHeader, EmptyState } from "@/components/healthcare-ui";
import { MetricCard } from "@/components/ui/metric-card";
import { tokens } from "@/styles/tokens";
import api from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AttestationRow {
  id: number;
  patient_id: number;
  hcc_code: string;
  hcc_description: string;
  icd10_code: string;
  icd10_description: string;
  provider_npi: string;
  status: "pending" | "attested" | "rejected" | "deferred";
  source: string;
  created_at: string;
  updated_at: string;
  attestation_type?: string;
  reject_reason?: string;
  clinical_justification?: string;
  deferred_until?: string;
}

interface AttestationListResponse {
  count: number;
  offset: number;
  attestations: AttestationRow[];
}

interface DashboardStats {
  total: number;
  pending: number;
  attested: number;
  rejected: number;
  deferred: number;
  attestation_rate: number;
  avg_turnaround_hours?: number;
}

type StatusFilter = "all" | "pending" | "attested" | "rejected" | "deferred";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_SIZE = 25;

const STATUS_TABS: { value: StatusFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "pending", label: "Pending" },
  { value: "attested", label: "Attested" },
  { value: "rejected", label: "Rejected" },
  { value: "deferred", label: "Deferred" },
];

const STATUS_BADGE: Record<
  AttestationRow["status"],
  { label: string; bg: string; color: string }
> = {
  pending: { label: "Pending", bg: "#FEF3C7", color: "#92400E" },
  attested: { label: "Attested", bg: "#D1FAE5", color: "#065F46" },
  rejected: { label: "Rejected", bg: "#FEE2E2", color: "#991B1B" },
  deferred: { label: "Deferred", bg: "#E0E7FF", color: "#3730A3" },
};

// ---------------------------------------------------------------------------
// Fetchers
// ---------------------------------------------------------------------------

// Backend shape: { period_days, total, by_status: {pending,attested,rejected,deferred},
//                   attestation_rate_pct, avg_turnaround_hours, ... }
// Map to the flat DashboardStats shape the component consumes.
async function fetchDashboard(): Promise<DashboardStats> {
  const { data } = await api.get<{
    total: number;
    by_status: { pending: number; attested: number; rejected: number; deferred: number };
    attestation_rate_pct: number;
    avg_turnaround_hours?: number;
  }>("/api/attestations/dashboard", { timeout: 15_000 });
  return {
    total: data.total,
    pending: data.by_status?.pending ?? 0,
    attested: data.by_status?.attested ?? 0,
    rejected: data.by_status?.rejected ?? 0,
    deferred: data.by_status?.deferred ?? 0,
    // Backend returns a percentage (0–100); frontend displays it as-is via toFixed(1)%
    // so we normalise to 0–1 fraction here.
    attestation_rate: (data.attestation_rate_pct ?? 0) / 100,
    avg_turnaround_hours: data.avg_turnaround_hours,
  };
}

async function fetchAttestations(
  status: StatusFilter,
  offset: number
): Promise<AttestationListResponse> {
  const params = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String(offset),
  });
  if (status !== "all") params.set("status", status);
  const { data } = await api.get<AttestationListResponse>(
    `/api/attestations?${params.toString()}`,
    { timeout: 15_000 }
  );
  return data;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AttestationsPage() {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");

  const {
    data: stats,
    isLoading: statsLoading,
    refetch: refetchStats,
  } = useQuery({
    queryKey: ["attestations-dashboard"],
    queryFn: fetchDashboard,
    staleTime: 60_000,
  });

  const {
    data: listData,
    isLoading: listLoading,
    refetch: refetchList,
    isError,
  } = useQuery({
    queryKey: ["attestations", statusFilter, offset],
    queryFn: () => fetchAttestations(statusFilter, offset),
    staleTime: 30_000,
  });

  function handleStatusTab(s: StatusFilter) {
    setStatusFilter(s);
    setOffset(0);
  }

  function handleRefresh() {
    refetchStats();
    refetchList();
  }

  const rows = listData?.attestations ?? [];
  const totalCount = listData?.count ?? 0;

  const filtered = search.trim()
    ? rows.filter(
        (r) =>
          r.hcc_code.toLowerCase().includes(search.toLowerCase()) ||
          r.hcc_description.toLowerCase().includes(search.toLowerCase()) ||
          r.icd10_code.toLowerCase().includes(search.toLowerCase()) ||
          String(r.patient_id).includes(search) ||
          r.provider_npi.includes(search)
      )
    : rows;

  const totalPages = Math.ceil(totalCount / PAGE_SIZE);
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  const isLoading = statsLoading || listLoading;

  return (
    <main
      style={{
        padding: "24px",
        maxWidth: 1280,
        margin: "0 auto",
        fontFamily: tokens.font?.sans ?? "system-ui, sans-serif",
      }}
    >
      <WorkflowProgressBar currentStage="attestations" />
      <WorkflowHandoffBanner
        count={stats?.attested ?? 0}
        message="{count} attestations validated — ready for pre-submission checks"
        ctaLabel="Run Pre-submission"
        ctaHref="/pre-submission"
      />
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
        <PageHeader
          title="Provider Attestations"
          subtitle="Review and track provider sign-off on suspect HCC conditions"
        />
        <button
          onClick={handleRefresh}
          aria-label="Refresh attestations"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "8px 14px",
            borderRadius: 8,
            border: "1px solid #E5E7EB",
            background: "#fff",
            cursor: "pointer",
            fontSize: 13,
            color: "#374151",
          }}
        >
          <RefreshCw size={14} className={isLoading ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {/* KPI Cards */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
          gap: 16,
          marginBottom: 24,
        }}
      >
        <MetricCard
          label="Total"
          value={statsLoading ? "—" : String(stats?.total ?? 0)}
          icon={<ClipboardCheck size={18} />}
          loading={statsLoading}
        />
        <MetricCard
          label="Pending"
          value={statsLoading ? "—" : String(stats?.pending ?? 0)}
          icon={<Clock size={18} />}
          intent="warning"
          loading={statsLoading}
        />
        <MetricCard
          label="Attested"
          value={statsLoading ? "—" : String(stats?.attested ?? 0)}
          icon={<CheckCircle2 size={18} />}
          intent="success"
          loading={statsLoading}
        />
        <MetricCard
          label="Rejected"
          value={statsLoading ? "—" : String(stats?.rejected ?? 0)}
          icon={<XCircle size={18} />}
          intent="danger"
          loading={statsLoading}
        />
        <MetricCard
          label="Deferred"
          value={statsLoading ? "—" : String(stats?.deferred ?? 0)}
          icon={<AlertCircle size={18} />}
          loading={statsLoading}
        />
        <MetricCard
          label="Attestation Rate"
          value={statsLoading ? "—" : `${((stats?.attestation_rate ?? 0) * 100).toFixed(1)}%`}
          icon={<CheckCircle2 size={18} />}
          intent="success"
          loading={statsLoading}
        />
      </div>

      {/* Filters row */}
      <div
        style={{
          display: "flex",
          gap: 12,
          alignItems: "center",
          marginBottom: 16,
          flexWrap: "wrap",
        }}
      >
        {/* Status tabs */}
        <div style={{ display: "flex", gap: 4, background: "#F3F4F6", borderRadius: 8, padding: 4 }}>
          {STATUS_TABS.map((tab) => (
            <button
              key={tab.value}
              onClick={() => handleStatusTab(tab.value)}
              aria-pressed={statusFilter === tab.value}
              style={{
                padding: "6px 14px",
                borderRadius: 6,
                border: "none",
                background: statusFilter === tab.value ? "#fff" : "transparent",
                boxShadow: statusFilter === tab.value ? "0 1px 3px rgba(0,0,0,0.1)" : "none",
                fontWeight: statusFilter === tab.value ? 600 : 400,
                fontSize: 13,
                color: statusFilter === tab.value ? "#111827" : "#6B7280",
                cursor: "pointer",
                transition: "all 0.15s",
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Search */}
        <div style={{ position: "relative", flex: "1 1 200px", maxWidth: 320 }}>
          <Search
            size={14}
            style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "#9CA3AF" }}
          />
          <input
            type="search"
            placeholder="Search HCC, ICD-10, patient ID, NPI…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search attestations"
            style={{
              width: "100%",
              padding: "8px 10px 8px 32px",
              borderRadius: 8,
              border: "1px solid #E5E7EB",
              fontSize: 13,
              color: "#111827",
              outline: "none",
              boxSizing: "border-box",
            }}
          />
        </div>
      </div>

      {/* Table */}
      {isError ? (
        <EmptyState
          icon={<AlertCircle size={40} />}
          title="Failed to load attestations"
          description="Check your connection or try refreshing."
        />
      ) : listLoading ? (
        <div style={{ textAlign: "center", padding: 48, color: "#9CA3AF" }}>
          Loading attestations…
        </div>
      ) : filtered.length === 0 ? (
        search || statusFilter !== "all" ? (
          <EmptyState
            icon={<ClipboardCheck size={40} />}
            title="No attestations found"
            description={
              search
                ? "Try a different search term."
                : "No attestations match the selected filter."
            }
          />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 16 }}>
            <EmptyState
              icon={<ClipboardCheck size={40} />}
              title="No attestations yet"
              description="Accepted suspects appear here once providers are assigned. Review your suspect queue to get started."
            />
            <a
              href="/suspects"
              style={{
                display: "inline-block",
                padding: "9px 20px",
                borderRadius: 8,
                background: "#2563EB",
                color: "#fff",
                fontWeight: 600,
                fontSize: 13,
                textDecoration: "none",
              }}
            >
              Go to Suspects
            </a>
          </div>
        )
      ) : (
        <div
          style={{
            background: "#fff",
            borderRadius: 12,
            border: "1px solid #E5E7EB",
            overflow: "hidden",
          }}
        >
          <table style={{ width: "100%", borderCollapse: "collapse" }} role="table">
            <thead>
              <tr style={{ background: "#F9FAFB" }}>
                {["Patient ID", "HCC", "ICD-10", "Provider NPI", "Source", "Status", "Created"].map(
                  (h) => (
                    <th
                      key={h}
                      scope="col"
                      style={{
                        padding: "10px 14px",
                        textAlign: "left",
                        fontSize: 11,
                        fontWeight: 600,
                        color: "#6B7280",
                        textTransform: "uppercase",
                        letterSpacing: "0.05em",
                        borderBottom: "1px solid #E5E7EB",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {h}
                    </th>
                  )
                )}
              </tr>
            </thead>
            <tbody>
              {filtered.map((row, idx) => {
                const badge = STATUS_BADGE[row.status] ?? STATUS_BADGE.pending;
                return (
                  <tr
                    key={row.id}
                    style={{
                      borderBottom: idx < filtered.length - 1 ? "1px solid #F3F4F6" : "none",
                      background: idx % 2 === 0 ? "#fff" : "#FAFAFA",
                    }}
                  >
                    <td style={tdStyle}>{row.patient_id}</td>
                    <td style={tdStyle}>
                      <span style={{ fontWeight: 600 }}>{row.hcc_code}</span>
                      {row.hcc_description && (
                        <div style={{ fontSize: 11, color: "#6B7280", marginTop: 2 }}>
                          {row.hcc_description}
                        </div>
                      )}
                    </td>
                    <td style={tdStyle}>
                      <span style={{ fontFamily: "monospace", fontSize: 13 }}>{row.icd10_code}</span>
                      {row.icd10_description && (
                        <div style={{ fontSize: 11, color: "#6B7280", marginTop: 2 }}>
                          {row.icd10_description}
                        </div>
                      )}
                    </td>
                    <td style={{ ...tdStyle, fontFamily: "monospace", fontSize: 12 }}>
                      {row.provider_npi}
                    </td>
                    <td style={tdStyle}>
                      <span
                        style={{
                          padding: "2px 8px",
                          borderRadius: 4,
                          background: "#F3F4F6",
                          fontSize: 11,
                          color: "#374151",
                        }}
                      >
                        {row.source}
                      </span>
                    </td>
                    <td style={tdStyle}>
                      <span
                        style={{
                          padding: "3px 10px",
                          borderRadius: 99,
                          background: badge.bg,
                          color: badge.color,
                          fontSize: 11,
                          fontWeight: 600,
                        }}
                      >
                        {badge.label}
                      </span>
                    </td>
                    <td style={{ ...tdStyle, color: "#6B7280", fontSize: 12, whiteSpace: "nowrap" }}>
                      {new Date(row.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {/* Pagination */}
          {totalPages > 1 && (
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                padding: "12px 16px",
                borderTop: "1px solid #E5E7EB",
                background: "#F9FAFB",
              }}
            >
              <span style={{ fontSize: 12, color: "#6B7280" }}>
                Page {currentPage} of {totalPages} ({totalCount} total)
              </span>
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                  disabled={offset === 0}
                  aria-label="Previous page"
                  style={paginationBtnStyle(offset === 0)}
                >
                  <ChevronLeft size={14} />
                  Prev
                </button>
                <button
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                  disabled={offset + PAGE_SIZE >= totalCount}
                  aria-label="Next page"
                  style={paginationBtnStyle(offset + PAGE_SIZE >= totalCount)}
                >
                  Next
                  <ChevronRight size={14} />
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </main>
  );
}

// ---------------------------------------------------------------------------
// Style helpers
// ---------------------------------------------------------------------------

const tdStyle: React.CSSProperties = {
  padding: "10px 14px",
  verticalAlign: "top",
  fontSize: 13,
  color: "#111827",
};

function paginationBtnStyle(disabled: boolean): React.CSSProperties {
  return {
    display: "flex",
    alignItems: "center",
    gap: 4,
    padding: "6px 12px",
    borderRadius: 6,
    border: "1px solid #E5E7EB",
    background: disabled ? "#F9FAFB" : "#fff",
    color: disabled ? "#D1D5DB" : "#374151",
    cursor: disabled ? "not-allowed" : "pointer",
    fontSize: 12,
    fontWeight: 500,
  };
}
