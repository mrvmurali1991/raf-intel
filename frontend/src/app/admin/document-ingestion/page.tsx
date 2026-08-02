"use client";

/**
 * /admin/document-ingestion
 *
 * Unified operator dashboard for all 8 document-ingestion paths.
 * Features:
 *   - KPI strip (total docs, suspects, success rate, active sources)
 *   - Source card grid (1 col mobile → 4 col desktop), each card links
 *     to a ?source= filtered view and a Configure shortcut
 *   - Recent activity table, paginated at 50 rows, with source filter
 *   - Click row → DocumentIngestionDetailDrawer side panel
 */

import React, { useState, useMemo, useCallback, Suspense } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import {
  Activity,
  FileText,
  Zap,
  Database,
  Cloud,
  Link2,
  Server,
  FlaskConical,
  FileStack,
  ChevronLeft,
  ChevronRight,
  Settings,
  RefreshCw,
  AlertCircle,
} from "lucide-react";
import { getDocumentIngestionDashboard } from "@/lib/api";
import { DocumentIngestionDetailDrawer } from "@/components/admin/DocumentIngestionDetailDrawer";
import { useAuth } from "@/contexts/auth-context";

// ---------------------------------------------------------------------------
// Source metadata (icons, display names, config routes)
// ---------------------------------------------------------------------------

interface SourceMeta {
  id: string;
  name: string;
  icon: React.ComponentType<{ style?: React.CSSProperties; "aria-hidden"?: "true"; className?: string }>;
  configPath: string;
}

const SOURCE_META: SourceMeta[] = [
  { id: "fhir-bulk",    name: "FHIR Bulk Export", icon: Cloud,        configPath: "/admin/fhir/bulk-export" },
  { id: "fhir-docref",  name: "FHIR DocRef",      icon: FileText,     configPath: "/admin/fhir/bulk-export" },
  { id: "hl7v2-mdm",    name: "HL7 v2 MDM",       icon: Server,       configPath: "/admin/hl7v2-sources" },
  { id: "direct-ccda",  name: "Direct / CCDA",    icon: Link2,        configPath: "/admin/direct-anchors" },
  { id: "hie",          name: "HIE",              icon: Database,     configPath: "/admin/hie" },
  { id: "datavant",     name: "Datavant",         icon: FlaskConical, configPath: "/admin/datavant" },
  { id: "inovalon",     name: "Inovalon",         icon: Zap,          configPath: "/admin/inovalon" },
  { id: "reveleer",     name: "Reveleer",         icon: FileStack,    configPath: "/admin/reveleer" },
  { id: "openemr",      name: "OpenEMR Docs",     icon: Activity,     configPath: "/admin/openemr-docs" },
];

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

type SourceStatus = "active" | "idle" | "not_configured";

function statusDot(status: SourceStatus) {
  const MAP: Record<SourceStatus, { className: string; label: string }> = {
    active:          { className: "bg-emerald-500",  label: "Active" },
    idle:            { className: "bg-amber-500",    label: "Configured – idle" },
    not_configured:  { className: "bg-slate-400",    label: "Not configured" },
  };
  const { className, label } = MAP[status] ?? MAP.not_configured;
  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      className={`inline-block w-2.5 h-2.5 rounded-full shrink-0 ${className}`}
    />
  );
}

function statusBadge(s: string): React.ReactNode {
  const map: Record<string, { bgCls: string; fgCls: string; label: string }> = {
    success:   { bgCls: "bg-emerald-50 dark:bg-emerald-950", fgCls: "text-emerald-500 dark:text-emerald-400", label: "Success" },
    completed: { bgCls: "bg-emerald-50 dark:bg-emerald-950", fgCls: "text-emerald-500 dark:text-emerald-400", label: "Success" },
    processed: { bgCls: "bg-emerald-50 dark:bg-emerald-950", fgCls: "text-emerald-500 dark:text-emerald-400", label: "Success" },
    failed:    { bgCls: "bg-red-50 dark:bg-red-950",         fgCls: "text-red-600 dark:text-red-400",         label: "Failed" },
    skipped:   { bgCls: "bg-slate-100 dark:bg-slate-800",    fgCls: "text-slate-400",                         label: "Skipped" },
  };
  const style = map[s?.toLowerCase()] ?? { bgCls: "bg-slate-100 dark:bg-slate-800", fgCls: "text-slate-500 dark:text-slate-400", label: s || "—" };
  return (
    <span
      className={`text-[11px] font-semibold px-2 py-0.5 rounded-[10px] whitespace-nowrap ${style.bgCls} ${style.fgCls}`}
    >
      {style.label}
    </span>
  );
}

function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// KPI Strip
// ---------------------------------------------------------------------------

interface KpiData {
  total_docs_24h: number;
  total_suspects_24h: number;
  success_rate_pct: number | null;
  active_sources: number;
  window_hours: number;
}

function KpiStrip({ kpis }: { kpis: KpiData | undefined }) {
  const items = [
    {
      label: "Total Docs (24h)",
      value: kpis?.total_docs_24h ?? 0,
      colorCls: "text-blue-600 dark:text-blue-400",
    },
    {
      label: "Suspects Extracted",
      value: kpis?.total_suspects_24h ?? 0,
      colorCls: "text-violet-600 dark:text-violet-400",
    },
    {
      label: "Success Rate",
      value:
        kpis?.success_rate_pct != null
          ? `${kpis.success_rate_pct}%`
          : "—",
      colorCls: "text-emerald-500 dark:text-emerald-400",
    },
    {
      label: "Active Sources",
      value: kpis?.active_sources ?? 0,
      colorCls: "text-amber-500 dark:text-amber-400",
    },
  ];

  return (
    <div
      role="region"
      aria-label="Ingestion KPIs"
      className="grid gap-4 mb-7"
      style={{ gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}
    >
      {items.map((item) => (
        <div
          key={item.label}
          className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-[10px] px-5 py-[18px]"
        >
          <div className="text-[11px] font-semibold uppercase tracking-[0.06em] text-slate-400 dark:text-slate-500 mb-1.5">
            {item.label}
          </div>
          <div
            className={`text-[28px] font-bold leading-none ${item.colorCls}`}
            aria-live="polite"
          >
            {item.value.toLocaleString()}
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Source Card
// ---------------------------------------------------------------------------

interface SourceCardData {
  id: string;
  name: string;
  status: SourceStatus;
  docs_24h: number;
  suspects_24h: number;
  last_activity: string | null;
  config_path: string;
}

interface SourceCardProps {
  card: SourceCardData;
  meta: SourceMeta;
  active: boolean;
  onSelect: (id: string) => void;
}

function SourceCard({ card, meta, active, onSelect }: SourceCardProps) {
  const Icon = meta.icon;

  return (
    <div
      className={`bg-white dark:bg-slate-900 rounded-[10px] p-4 flex flex-col gap-3 cursor-pointer transition-[border-color,box-shadow] duration-150 ${
        active
          ? "border-2 border-blue-600 dark:border-blue-400 shadow-[0_0_0_3px_rgba(219,234,254,0.5)] dark:shadow-[0_0_0_3px_rgba(30,58,138,0.3)]"
          : "border-2 border-slate-200 dark:border-slate-700"
      }`}
      onClick={() => onSelect(card.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect(card.id);
        }
      }}
      tabIndex={0}
      role="button"
      aria-pressed={active}
      aria-label={`${card.name} — status: ${card.status.replace(/_/g, " ")}, ${card.docs_24h} docs in last 24h`}
    >
      {/* Icon + status */}
      <div className="flex items-center justify-between">
        <div className="w-9 h-9 rounded-[9px] bg-blue-50 dark:bg-blue-950 flex items-center justify-center text-blue-600 dark:text-blue-400">
          <Icon style={{ width: 18, height: 18 }} aria-hidden="true" />
        </div>
        {statusDot(card.status)}
      </div>

      {/* Name */}
      <div className="text-[13px] font-semibold text-slate-900 dark:text-slate-50">{card.name}</div>

      {/* Counts */}
      <div className="flex gap-4">
        <div>
          <div className="text-[18px] font-bold text-slate-900 dark:text-slate-50 leading-none">
            {card.docs_24h.toLocaleString()}
          </div>
          <div className="text-[10px] text-slate-500 dark:text-slate-400 mt-0.5">docs 24h</div>
        </div>
        <div>
          <div className="text-[18px] font-bold text-violet-600 dark:text-violet-400 leading-none">
            {card.suspects_24h.toLocaleString()}
          </div>
          <div className="text-[10px] text-slate-500 dark:text-slate-400 mt-0.5">suspects</div>
        </div>
      </div>

      {/* Last activity */}
      <div className="text-[11px] text-slate-400 dark:text-slate-500">
        Last: {relativeTime(card.last_activity)}
      </div>

      {/* Configure link */}
      <Link
        href={card.config_path}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
        className="inline-flex items-center gap-[5px] text-[11px] font-medium text-blue-600 dark:text-blue-400 no-underline px-2.5 py-[5px] border border-slate-200 dark:border-slate-700 rounded-md bg-slate-50 dark:bg-slate-800 self-start transition-colors duration-150"
        aria-label={`Configure ${card.name}`}
      >
        <Settings style={{ width: 11, height: 11 }} aria-hidden="true" />
        Configure
      </Link>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Activity table
// ---------------------------------------------------------------------------

const PAGE_SIZE = 50;

interface DocRow {
  source: string;
  timestamp: string | null;
  document_id: string | null;
  patient_id: string | null;
  filename: string | null;
  mimetype: string | null;
  suspects: number;
  status: string;
}

interface ActivityTableProps {
  rows: DocRow[];
  onRowClick: (row: DocRow) => void;
}

function ActivityTable({ rows, onRowClick }: ActivityTableProps) {
  const [page, setPage] = useState(0);
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const pageRows = rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  return (
    <div>
      <div className="overflow-x-auto">
        <table
          className="w-full border-collapse text-[13px]"
          aria-label="Recent document activity"
        >
          <thead>
            <tr className="border-b-2 border-slate-200 dark:border-slate-700">
              {["Timestamp", "Source", "Patient ID", "Filename", "MIME Type", "Suspects", "Status", ""].map(
                (h) => (
                  <th
                    key={h}
                    scope="col"
                    className="px-3 py-2.5 text-left text-[11px] font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-[0.05em] whitespace-nowrap bg-slate-50 dark:bg-slate-800"
                  >
                    {h}
                  </th>
                )
              )}
            </tr>
          </thead>
          <tbody>
            {pageRows.length === 0 && (
              <tr>
                <td
                  colSpan={8}
                  className="p-10 text-center text-slate-500 dark:text-slate-400 text-sm"
                >
                  No documents found in the selected window.
                </td>
              </tr>
            )}
            {pageRows.map((row, i) => {
              const rowIdx = page * PAGE_SIZE + i;
              return (
                <tr
                  key={`${row.source}-${row.document_id}-${rowIdx}`}
                  className={`border-b border-slate-200 dark:border-slate-700 cursor-pointer transition-colors duration-100 ${
                    i % 2 === 0
                      ? "bg-white dark:bg-slate-900"
                      : "bg-slate-50 dark:bg-slate-800"
                  } hover:bg-slate-100 dark:hover:bg-slate-700`}
                  onClick={() => onRowClick(row)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onRowClick(row);
                    }
                  }}
                  tabIndex={0}
                  role="row"
                  aria-label={`Document ${row.filename || row.document_id} — click to view details`}
                >
                  <td className="px-3 py-2.5 whitespace-nowrap text-slate-500 dark:text-slate-400 text-xs">
                    {formatTimestamp(row.timestamp)}
                  </td>
                  <td className="px-3 py-2.5">
                    <span className="text-[11px] font-semibold px-2 py-0.5 rounded-[10px] bg-blue-50 dark:bg-blue-950 text-blue-600 dark:text-blue-400 whitespace-nowrap">
                      {row.source}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 font-mono text-xs text-slate-500 dark:text-slate-400">
                    {row.patient_id ? `PT-${row.patient_id.slice(-6)}` : "—"}
                  </td>
                  <td
                    className="px-3 py-2.5 max-w-[200px] overflow-hidden text-ellipsis whitespace-nowrap text-[13px] text-slate-900 dark:text-slate-100"
                    title={row.filename ?? undefined}
                  >
                    {row.filename || "—"}
                  </td>
                  <td className="px-3 py-2.5 text-[11px] text-slate-500 dark:text-slate-400 whitespace-nowrap">
                    {row.mimetype || "—"}
                  </td>
                  <td className="px-3 py-2.5 font-semibold text-violet-600 dark:text-violet-400 text-right">
                    {row.suspects}
                  </td>
                  <td className="px-3 py-2.5">
                    {statusBadge(row.status)}
                  </td>
                  <td className="px-3 py-2.5">
                    <button
                      className="bg-transparent border border-slate-200 dark:border-slate-700 rounded-md px-2.5 py-[3px] text-[11px] font-medium text-blue-600 dark:text-blue-400 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800"
                      onClick={(e) => {
                        e.stopPropagation();
                        onRowClick(row);
                      }}
                      aria-label={`View document ${row.filename || row.document_id}`}
                    >
                      View
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div
          className="flex items-center justify-end gap-2 py-3"
          role="navigation"
          aria-label="Table pagination"
        >
          <span className="text-xs text-slate-500 dark:text-slate-400">
            Page {page + 1} of {totalPages} &nbsp;({rows.length.toLocaleString()} rows)
          </span>
          <button
            disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}
            className={`flex items-center justify-center w-[30px] h-[30px] border border-slate-200 dark:border-slate-700 rounded-md bg-transparent ${
              page === 0
                ? "cursor-not-allowed text-slate-400 dark:text-slate-500"
                : "cursor-pointer text-slate-900 dark:text-slate-50"
            }`}
            aria-label="Previous page"
          >
            <ChevronLeft style={{ width: 14, height: 14 }} aria-hidden="true" />
          </button>
          <button
            disabled={page >= totalPages - 1}
            onClick={() => setPage((p) => p + 1)}
            className={`flex items-center justify-center w-[30px] h-[30px] border border-slate-200 dark:border-slate-700 rounded-md bg-transparent ${
              page >= totalPages - 1
                ? "cursor-not-allowed text-slate-400 dark:text-slate-500"
                : "cursor-pointer text-slate-900 dark:text-slate-50"
            }`}
            aria-label="Next page"
          >
            <ChevronRight style={{ width: 14, height: 14 }} aria-hidden="true" />
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page — inner (needs useSearchParams so wrapped in Suspense below)
// ---------------------------------------------------------------------------

function DocumentIngestionPageInner() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { user } = useAuth();

  const activeSource = searchParams.get("source");

  // Drawer state
  const [selectedDoc, setSelectedDoc] = useState<DocRow | null>(null);

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["doc-ingestion-dashboard"],
    queryFn: () => getDocumentIngestionDashboard(24),
    staleTime: 60_000,
    refetchInterval: 120_000,
  });

  // Build source cards, merging API data with static meta
  const sourceCards: SourceCardData[] = useMemo(() => {
    const apiSources: SourceCardData[] = data?.sources ?? [];
    return SOURCE_META.map((meta) => {
      const api = apiSources.find((s) => s.id === meta.id);
      return {
        id: meta.id,
        name: meta.name,
        status: (api?.status as SourceStatus) ?? "not_configured",
        docs_24h: api?.docs_24h ?? 0,
        suspects_24h: api?.suspects_24h ?? 0,
        last_activity: api?.last_activity ?? null,
        config_path: meta.configPath,
      };
    });
  }, [data]);

  // Filter recent documents by active source
  const allDocs: DocRow[] = data?.recent_documents ?? [];
  const filteredDocs = useMemo(
    () =>
      activeSource
        ? allDocs.filter((d) => d.source === activeSource)
        : allDocs,
    [allDocs, activeSource]
  );

  const handleSourceSelect = useCallback(
    (id: string) => {
      const current = searchParams.get("source");
      if (current === id) {
        router.push("/admin/document-ingestion");
      } else {
        router.push(`/admin/document-ingestion?source=${id}`);
      }
    },
    [router, searchParams]
  );

  return (
    <>
      <main
        id="main-content"
        className="min-h-screen bg-slate-50 dark:bg-slate-950"
        style={{ padding: "24px clamp(16px, 4vw, 40px)" }}
      >
        {/* Page header */}
        <div className="flex items-start justify-between flex-wrap gap-3 mb-7">
          <div>
            <h1
              className="font-bold text-slate-900 dark:text-slate-50 m-0 leading-tight"
              style={{ fontSize: "clamp(20px, 3vw, 26px)" }}
            >
              Document Ingestion
            </h1>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
              All paths &middot; last 24h
            </p>
          </div>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className={`inline-flex items-center gap-1.5 px-4 py-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg text-[13px] font-medium text-slate-900 dark:text-slate-50 ${
              isFetching ? "cursor-not-allowed opacity-60" : "cursor-pointer"
            }`}
            aria-label="Refresh ingestion data"
          >
            <RefreshCw
              style={{
                width: 14,
                height: 14,
                animation: isFetching ? "spin 1s linear infinite" : "none",
              }}
              aria-hidden="true"
            />
            Refresh
          </button>
        </div>

        {/* Error banner */}
        {isError && (
          <div
            role="alert"
            className="flex items-center gap-2.5 px-4 py-3.5 bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 rounded-[10px] text-red-600 dark:text-red-400 mb-6 text-[13px]"
          >
            <AlertCircle style={{ width: 16, height: 16, flexShrink: 0 }} aria-hidden="true" />
            Failed to load ingestion data. The backend aggregator may not be deployed yet.
          </div>
        )}

        {/* KPI strip */}
        <KpiStrip kpis={data?.kpis} />

        {/* Source card grid */}
        <section aria-label="Ingestion source cards" className="mb-9">
          <div className="flex items-center justify-between mb-3.5">
            <h2 className="text-[15px] font-semibold text-slate-900 dark:text-slate-50 m-0">
              Ingestion Sources
            </h2>
            {activeSource && (
              <button
                onClick={() => router.push("/admin/document-ingestion")}
                className="bg-transparent border-none text-blue-600 dark:text-blue-400 text-xs font-medium cursor-pointer p-0"
                aria-label="Clear source filter"
              >
                Clear filter
              </button>
            )}
          </div>

          {isLoading ? (
            <div
              role="status"
              aria-live="polite"
              className="grid gap-3.5"
              style={{ gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))" }}
            >
              {SOURCE_META.map((m) => (
                <div
                  key={m.id}
                  className="h-[180px] bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-[10px] animate-pulse"
                  aria-hidden="true"
                />
              ))}
              <span className="sr-only">Loading source cards…</span>
            </div>
          ) : (
            <div
              className="grid gap-3.5"
              style={{
                gridTemplateColumns:
                  "repeat(auto-fill, minmax(clamp(160px, 20vw, 220px), 1fr))",
              }}
            >
              {sourceCards.map((card) => {
                const meta = SOURCE_META.find((m) => m.id === card.id)!;
                return (
                  <SourceCard
                    key={card.id}
                    card={card}
                    meta={meta}
                    active={activeSource === card.id}
                    onSelect={handleSourceSelect}
                  />
                );
              })}
            </div>
          )}
        </section>

        {/* Recent activity table */}
        <section aria-label="Recent document activity">
          <div className="mb-3.5">
            <h2 className="text-[15px] font-semibold text-slate-900 dark:text-slate-50 m-0">
              Recent Activity
              {activeSource && (
                <span className="text-xs text-slate-500 dark:text-slate-400 font-normal ml-2">
                  filtered: {activeSource}
                </span>
              )}
            </h2>
          </div>

          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-[10px] overflow-hidden">
            <ActivityTable rows={filteredDocs} onRowClick={setSelectedDoc} />
          </div>
        </section>
      </main>

      {/* Detail drawer */}
      <DocumentIngestionDetailDrawer
        open={!!selectedDoc}
        onClose={() => setSelectedDoc(null)}
        sourceId={selectedDoc?.source}
        documentId={selectedDoc?.document_id ?? undefined}
        isAdmin={user?.role === "admin"}
      />

      {/* Spin keyframe */}
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        .sr-only {
          position: absolute; width: 1px; height: 1px;
          padding: 0; margin: -1px; overflow: hidden;
          clip: rect(0,0,0,0); white-space: nowrap; border: 0;
        }
      `}</style>
    </>
  );
}

// ---------------------------------------------------------------------------
// Export — wrapped in Suspense for useSearchParams
// ---------------------------------------------------------------------------

export default function DocumentIngestionPage() {
  return (
    <Suspense fallback={<div className="p-10 text-slate-500 dark:text-slate-400">Loading…</div>}>
      <DocumentIngestionPageInner />
    </Suspense>
  );
}
