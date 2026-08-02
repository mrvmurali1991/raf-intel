"use client";

/**
 * /attestations — Provider Attestation Queue
 *
 * Data:
 *   GET /api/attestations/dashboard  → { total, by_status: { pending, attested, rejected, deferred }, attestation_rate_pct }
 *   GET /api/attestations            → { count, offset, attestations: [...] }
 *
 * Attestation row fields (provider_attestations table):
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
  FileSignature,
  Eye,
} from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from "@/components/ui/table";
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
}

type StatusFilter = "all" | "pending" | "attested" | "rejected" | "deferred";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_SIZE = 25;

const STATUS_TABS: {
  value: StatusFilter;
  label: string;
  activeClass: string;
}[] = [
  {
    value: "all",
    label: "All",
    activeClass: "bg-foreground text-background",
  },
  {
    value: "pending",
    label: "Pending",
    activeClass: "bg-amber-500 text-white",
  },
  {
    value: "attested",
    label: "Completed",
    activeClass: "bg-emerald-600 text-white",
  },
  {
    value: "rejected",
    label: "Rejected",
    activeClass: "bg-red-600 text-white",
  },
  {
    value: "deferred",
    label: "Deferred",
    activeClass: "bg-indigo-600 text-white",
  },
];

const STATUS_BADGE: Record<
  AttestationRow["status"],
  { label: string; className: string }
> = {
  pending: {
    label: "Pending",
    className: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  },
  attested: {
    label: "Completed",
    className: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  },
  rejected: {
    label: "Rejected",
    className: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  },
  deferred: {
    label: "Deferred",
    className: "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-300",
  },
};

// ---------------------------------------------------------------------------
// Fetchers
// ---------------------------------------------------------------------------

async function fetchDashboard(): Promise<DashboardStats> {
  const { data } = await api.get<{
    total: number;
    by_status: {
      pending: number;
      attested: number;
      rejected: number;
      deferred: number;
    };
    attestation_rate_pct: number;
  }>("/api/attestations/dashboard", { timeout: 15_000 });
  return {
    total: data.total,
    pending: data.by_status?.pending ?? 0,
    attested: data.by_status?.attested ?? 0,
    rejected: data.by_status?.rejected ?? 0,
    deferred: data.by_status?.deferred ?? 0,
    attestation_rate: (data.attestation_rate_pct ?? 0) / 100,
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
// KPI strip
// ---------------------------------------------------------------------------

interface KpiStripProps {
  stats: DashboardStats | undefined;
  loading: boolean;
}

function KpiStrip({ stats, loading }: KpiStripProps) {
  const items = [
    {
      label: "Pending",
      value: stats?.pending ?? 0,
      className: "text-amber-700 bg-amber-50 border-amber-200 dark:text-amber-300 dark:bg-amber-900/20 dark:border-amber-800",
      icon: <Clock size={13} aria-hidden="true" />,
    },
    {
      label: "Completed",
      value: stats?.attested ?? 0,
      className: "text-emerald-700 bg-emerald-50 border-emerald-200 dark:text-emerald-300 dark:bg-emerald-900/20 dark:border-emerald-800",
      icon: <CheckCircle2 size={13} aria-hidden="true" />,
    },
    {
      label: "Rejected",
      value: stats?.rejected ?? 0,
      className: "text-red-700 bg-red-50 border-red-200 dark:text-red-300 dark:bg-red-900/20 dark:border-red-800",
      icon: <XCircle size={13} aria-hidden="true" />,
    },
    {
      label: "Deferred",
      value: stats?.deferred ?? 0,
      className: "text-indigo-700 bg-indigo-50 border-indigo-200 dark:text-indigo-300 dark:bg-indigo-900/20 dark:border-indigo-800",
      icon: <AlertCircle size={13} aria-hidden="true" />,
    },
    {
      label: "Total",
      value: stats?.total ?? 0,
      className: "text-foreground bg-muted border-border",
      icon: <ClipboardCheck size={13} aria-hidden="true" />,
    },
  ];

  if (loading) {
    return (
      <div className="flex flex-wrap gap-2 mb-5" aria-busy="true" aria-label="Loading KPIs">
        {items.map((item) => (
          <div
            key={item.label}
            className="h-7 w-24 rounded-full bg-muted animate-pulse"
          />
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-2 mb-5" role="list" aria-label="Attestation summary">
      {items.map((item) => (
        <div
          key={item.label}
          role="listitem"
          className={[
            "inline-flex items-center gap-1.5 px-3 py-1 rounded-full border text-[12px] font-semibold leading-none whitespace-nowrap",
            item.className,
          ].join(" ")}
        >
          {item.icon}
          <span>{item.label}:</span>
          <span className="tabular-nums">{item.value}</span>
        </div>
      ))}
    </div>
  );
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
    <main className="p-6 max-w-[1280px] mx-auto">
      <WorkflowProgressBar currentStage="attestations" />
      <WorkflowHandoffBanner
        count={stats?.attested ?? 0}
        message="{count} attestations validated — ready for pre-submission checks"
        ctaLabel="Run Pre-submission"
        ctaHref="/pre-submission"
        showWhenZero
        zeroMessage="No attestations completed yet — accept suspects first, then providers can attest."
        zeroCtaLabel="Go to Suspects"
        zeroCtaHref="/suspects"
      />

      {/* Header */}
      <PageHeader
        title="Provider Attestations"
        subtitle="Review and track provider sign-off on suspect HCC conditions"
        icon={<ClipboardCheck size={20} />}
        actions={
          <button
            onClick={handleRefresh}
            aria-label="Refresh attestations"
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg border border-border bg-card text-foreground text-[13px] font-medium cursor-pointer hover:bg-muted transition-colors"
          >
            <RefreshCw size={14} className={isLoading ? "animate-spin" : ""} />
            Refresh
          </button>
        }
      />

      {/* Compact KPI strip */}
      <KpiStrip stats={stats} loading={statsLoading} />

      {/* Filters row */}
      <div className="flex flex-wrap items-center gap-3 mb-4">
        {/* Status tabs — pill style */}
        <div
          className="flex flex-wrap gap-1.5"
          role="tablist"
          aria-label="Filter by status"
        >
          {STATUS_TABS.map((tab) => {
            const isActive = statusFilter === tab.value;
            return (
              <button
                key={tab.value}
                role="tab"
                aria-selected={isActive}
                onClick={() => handleStatusTab(tab.value)}
                className={[
                  "px-3.5 py-1.5 rounded-full border text-[12px] font-semibold leading-none cursor-pointer transition-all whitespace-nowrap",
                  isActive
                    ? tab.activeClass + " border-transparent shadow-sm"
                    : "bg-card border-border text-muted-foreground hover:text-foreground hover:bg-muted",
                ].join(" ")}
              >
                {tab.label}
              </button>
            );
          })}
        </div>

        {/* Search */}
        <div className="relative flex-[1_1_200px] max-w-xs">
          <Search
            size={14}
            aria-hidden="true"
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
          />
          <input
            type="search"
            placeholder="Search HCC, ICD-10, patient ID, NPI…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search attestations"
            className="w-full pl-8 pr-3 py-2 rounded-lg border border-border bg-card text-[13px] text-foreground placeholder:text-muted-foreground outline-none focus:ring-2 focus:ring-ring box-border"
          />
        </div>
      </div>

      {/* Table area */}
      {isError ? (
        <EmptyState
          icon={<AlertCircle size={40} />}
          title="Failed to load attestations"
          description="Check your connection or try refreshing."
        />
      ) : listLoading ? (
        <div className="flex flex-col items-center justify-center py-16 gap-3 text-muted-foreground">
          <RefreshCw size={24} className="animate-spin" aria-hidden="true" />
          <span className="text-[13px]">Loading attestations…</span>
        </div>
      ) : filtered.length === 0 ? (
        search || statusFilter !== "all" ? (
          <EmptyState
            state="filtered-out"
            icon={<FileSignature size={40} />}
            description={
              search
                ? "Try a different search term."
                : "No attestations match the selected filter."
            }
          />
        ) : (
          <EmptyState
            state="no-data"
            icon={<FileSignature size={40} />}
            title="No attestations pending"
            description="Accepted suspects will appear here once providers submit attestations."
            cta={{ label: "Go to Suspects", href: "/suspects" }}
          />
        )
      ) : (
        <div className="bg-card border border-border rounded-xl overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted hover:bg-muted">
                {[
                  "Patient",
                  "Condition",
                  "Provider NPI",
                  "Submitted",
                  "Status",
                  "Action",
                ].map((h) => (
                  <TableHead
                    key={h}
                    scope="col"
                    className="px-3.5 py-2.5 text-[11px] font-semibold text-muted-foreground uppercase tracking-wider whitespace-nowrap border-b border-border"
                  >
                    {h}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((row, idx) => {
                const badge =
                  STATUS_BADGE[row.status] ?? STATUS_BADGE.pending;
                return (
                  <TableRow
                    key={row.id}
                    className={
                      idx % 2 === 1
                        ? "bg-muted/40 hover:bg-muted/70"
                        : "bg-card hover:bg-muted/30"
                    }
                  >
                    {/* Patient */}
                    <TableCell className="px-3.5 py-2.5 align-middle">
                      <span className="text-[13px] font-semibold text-foreground">
                        Patient {row.patient_id}
                      </span>
                    </TableCell>

                    {/* Condition — HCC + ICD-10 stacked */}
                    <TableCell className="px-3.5 py-2.5 align-middle max-w-[260px]">
                      <span className="text-[13px] font-semibold text-foreground">
                        HCC {row.hcc_code}
                      </span>
                      {row.hcc_description && (
                        <div className="text-[11px] text-muted-foreground mt-0.5 leading-snug truncate">
                          {row.hcc_description}
                        </div>
                      )}
                      {row.icd10_code && (
                        <div className="text-[11px] font-mono text-muted-foreground mt-0.5">
                          {row.icd10_code}
                          {row.icd10_description && (
                            <span className="font-sans ml-1 non-italic">
                              — {row.icd10_description}
                            </span>
                          )}
                        </div>
                      )}
                    </TableCell>

                    {/* Provider NPI */}
                    <TableCell className="px-3.5 py-2.5 align-middle">
                      <span className="font-mono text-[12px] text-foreground">
                        {row.provider_npi}
                      </span>
                    </TableCell>

                    {/* Date submitted */}
                    <TableCell className="px-3.5 py-2.5 text-[12px] text-muted-foreground whitespace-nowrap align-middle">
                      {new Date(row.created_at).toLocaleDateString("en-US", {
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                      })}
                    </TableCell>

                    {/* Status badge */}
                    <TableCell className="px-3.5 py-2.5 align-middle">
                      <span
                        className={[
                          "inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-semibold",
                          badge.className,
                        ].join(" ")}
                      >
                        {badge.label}
                      </span>
                    </TableCell>

                    {/* Action */}
                    <TableCell className="px-3.5 py-2.5 align-middle">
                      <button
                        aria-label={`Review attestation for patient ${row.patient_id}`}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border bg-card text-[12px] font-medium text-foreground cursor-pointer hover:bg-muted transition-colors whitespace-nowrap"
                      >
                        <Eye size={13} aria-hidden="true" />
                        Review
                      </button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-4 py-3 border-t border-border bg-muted">
              <span className="text-[12px] text-muted-foreground">
                Page {currentPage} of {totalPages} ({totalCount} total)
              </span>
              <div className="flex gap-2">
                <button
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                  disabled={offset === 0}
                  aria-label="Previous page"
                  className="flex items-center gap-1 px-3 py-1.5 rounded-md border border-border text-[12px] font-medium bg-card text-foreground cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed hover:bg-muted transition-colors"
                >
                  <ChevronLeft size={14} />
                  Prev
                </button>
                <button
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                  disabled={offset + PAGE_SIZE >= totalCount}
                  aria-label="Next page"
                  className="flex items-center gap-1 px-3 py-1.5 rounded-md border border-border text-[12px] font-medium bg-card text-foreground cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed hover:bg-muted transition-colors"
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
