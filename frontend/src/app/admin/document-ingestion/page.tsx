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
// Design tokens
// ---------------------------------------------------------------------------

const T = {
  bg: "#F8FAFC",
  card: "#FFFFFF",
  border: "#E2E8F0",
  text: "#0F172A",
  muted: "#64748B",
  subtle: "#94A3B8",
  accent: "#2563EB",
  accentBg: "#EFF6FF",
  success: "#10B981",
  successBg: "#ECFDF5",
  warning: "#F59E0B",
  warningBg: "#FFFBEB",
  danger: "#DC2626",
  dangerBg: "#FEF2F2",
  inactive: "#94A3B8",
  inactiveBg: "#F1F5F9",
  header: "#0F172A",
} as const;

// ---------------------------------------------------------------------------
// Source metadata (icons, display names, config routes)
// ---------------------------------------------------------------------------

interface SourceMeta {
  id: string;
  name: string;
  icon: React.ComponentType<{ style?: React.CSSProperties; "aria-hidden"?: "true" }>;
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
  const MAP: Record<SourceStatus, { color: string; label: string }> = {
    active:          { color: T.success,  label: "Active" },
    idle:            { color: T.warning,  label: "Configured – idle" },
    not_configured:  { color: T.inactive, label: "Not configured" },
  };
  const { color, label } = MAP[status] ?? MAP.not_configured;
  return (
    <span
      role="img"
      aria-label={label}
      title={label}
      style={{
        display: "inline-block",
        width: 9,
        height: 9,
        borderRadius: "50%",
        backgroundColor: color,
        flexShrink: 0,
      }}
    />
  );
}

function statusBadge(s: string): React.ReactNode {
  const map: Record<string, { bg: string; fg: string; label: string }> = {
    success:   { bg: T.successBg, fg: T.success,  label: "Success" },
    completed: { bg: T.successBg, fg: T.success,  label: "Success" },
    processed: { bg: T.successBg, fg: T.success,  label: "Success" },
    failed:    { bg: T.dangerBg,  fg: T.danger,   label: "Failed" },
    skipped:   { bg: T.inactiveBg, fg: T.inactive, label: "Skipped" },
  };
  const style = map[s?.toLowerCase()] ?? { bg: T.inactiveBg, fg: T.muted, label: s || "—" };
  return (
    <span
      style={{
        fontSize: 11,
        fontWeight: 600,
        padding: "2px 8px",
        borderRadius: 10,
        backgroundColor: style.bg,
        color: style.fg,
        whiteSpace: "nowrap",
      }}
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
      color: T.accent,
    },
    {
      label: "Suspects Extracted",
      value: kpis?.total_suspects_24h ?? 0,
      color: "#7C3AED",
    },
    {
      label: "Success Rate",
      value:
        kpis?.success_rate_pct != null
          ? `${kpis.success_rate_pct}%`
          : "—",
      color: T.success,
    },
    {
      label: "Active Sources",
      value: kpis?.active_sources ?? 0,
      color: T.warning,
    },
  ];

  return (
    <div
      role="region"
      aria-label="Ingestion KPIs"
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
        gap: 16,
        marginBottom: 28,
      }}
    >
      {items.map((item) => (
        <div
          key={item.label}
          style={{
            backgroundColor: T.card,
            border: `1px solid ${T.border}`,
            borderRadius: 10,
            padding: "18px 20px",
          }}
        >
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.06em",
              color: T.subtle,
              marginBottom: 6,
            }}
          >
            {item.label}
          </div>
          <div
            style={{ fontSize: 28, fontWeight: 700, color: item.color, lineHeight: 1 }}
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
      style={{
        backgroundColor: T.card,
        border: `2px solid ${active ? T.accent : T.border}`,
        borderRadius: 10,
        padding: "16px",
        display: "flex",
        flexDirection: "column",
        gap: 12,
        cursor: "pointer",
        transition: "border-color 150ms, box-shadow 150ms",
        boxShadow: active ? `0 0 0 3px ${T.accentBg}` : "none",
      }}
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
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: 9,
            backgroundColor: T.accentBg,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: T.accent,
          }}
        >
          <Icon style={{ width: 18, height: 18 }} aria-hidden="true" />
        </div>
        {statusDot(card.status)}
      </div>

      {/* Name */}
      <div style={{ fontSize: 13, fontWeight: 600, color: T.text }}>{card.name}</div>

      {/* Counts */}
      <div style={{ display: "flex", gap: 16 }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: T.text, lineHeight: 1 }}>
            {card.docs_24h.toLocaleString()}
          </div>
          <div style={{ fontSize: 10, color: T.muted, marginTop: 2 }}>docs 24h</div>
        </div>
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: "#7C3AED", lineHeight: 1 }}>
            {card.suspects_24h.toLocaleString()}
          </div>
          <div style={{ fontSize: 10, color: T.muted, marginTop: 2 }}>suspects</div>
        </div>
      </div>

      {/* Last activity */}
      <div style={{ fontSize: 11, color: T.subtle }}>
        Last: {relativeTime(card.last_activity)}
      </div>

      {/* Configure link — stops propagation so it doesn't trigger the card click */}
      <Link
        href={card.config_path}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 5,
          fontSize: 11,
          fontWeight: 500,
          color: T.accent,
          textDecoration: "none",
          padding: "5px 10px",
          border: `1px solid ${T.border}`,
          borderRadius: 6,
          backgroundColor: T.bg,
          alignSelf: "flex-start",
          transition: "background-color 150ms",
        }}
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
      <div style={{ overflowX: "auto" }}>
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            fontSize: 13,
          }}
          aria-label="Recent document activity"
        >
          <thead>
            <tr style={{ borderBottom: `2px solid ${T.border}` }}>
              {["Timestamp", "Source", "Patient ID", "Filename", "MIME Type", "Suspects", "Status", ""].map(
                (h) => (
                  <th
                    key={h}
                    scope="col"
                    style={{
                      padding: "10px 12px",
                      textAlign: "left",
                      fontSize: 11,
                      fontWeight: 600,
                      color: T.muted,
                      textTransform: "uppercase",
                      letterSpacing: "0.05em",
                      whiteSpace: "nowrap",
                      backgroundColor: T.bg,
                    }}
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
                  style={{
                    padding: "40px",
                    textAlign: "center",
                    color: T.muted,
                    fontSize: 14,
                  }}
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
                  style={{
                    backgroundColor: i % 2 === 0 ? T.card : T.bg,
                    borderBottom: `1px solid ${T.border}`,
                    cursor: "pointer",
                    transition: "background-color 100ms",
                  }}
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
                  <td style={{ padding: "10px 12px", whiteSpace: "nowrap", color: T.muted, fontSize: 12 }}>
                    {formatTimestamp(row.timestamp)}
                  </td>
                  <td style={{ padding: "10px 12px" }}>
                    <span
                      style={{
                        fontSize: 11,
                        fontWeight: 600,
                        padding: "2px 8px",
                        borderRadius: 10,
                        backgroundColor: T.accentBg,
                        color: T.accent,
                        whiteSpace: "nowrap",
                      }}
                    >
                      {row.source}
                    </span>
                  </td>
                  <td style={{ padding: "10px 12px", fontFamily: "monospace", fontSize: 12, color: T.muted }}>
                    {row.patient_id ? `PT-${row.patient_id.slice(-6)}` : "—"}
                  </td>
                  <td
                    style={{
                      padding: "10px 12px",
                      maxWidth: 200,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      fontSize: 13,
                    }}
                    title={row.filename ?? undefined}
                  >
                    {row.filename || "—"}
                  </td>
                  <td style={{ padding: "10px 12px", fontSize: 11, color: T.muted, whiteSpace: "nowrap" }}>
                    {row.mimetype || "—"}
                  </td>
                  <td style={{ padding: "10px 12px", fontWeight: 600, color: "#7C3AED", textAlign: "right" }}>
                    {row.suspects}
                  </td>
                  <td style={{ padding: "10px 12px" }}>
                    {statusBadge(row.status)}
                  </td>
                  <td style={{ padding: "10px 12px" }}>
                    <button
                      style={{
                        background: "none",
                        border: `1px solid ${T.border}`,
                        borderRadius: 6,
                        padding: "3px 10px",
                        fontSize: 11,
                        fontWeight: 500,
                        color: T.accent,
                        cursor: "pointer",
                      }}
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
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-end",
            gap: 8,
            padding: "12px 0",
          }}
          role="navigation"
          aria-label="Table pagination"
        >
          <span style={{ fontSize: 12, color: T.muted }}>
            Page {page + 1} of {totalPages} &nbsp;({rows.length.toLocaleString()} rows)
          </span>
          <button
            disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 30,
              height: 30,
              border: `1px solid ${T.border}`,
              borderRadius: 6,
              background: "none",
              cursor: page === 0 ? "not-allowed" : "pointer",
              color: page === 0 ? T.subtle : T.text,
            }}
            aria-label="Previous page"
          >
            <ChevronLeft style={{ width: 14, height: 14 }} aria-hidden="true" />
          </button>
          <button
            disabled={page >= totalPages - 1}
            onClick={() => setPage((p) => p + 1)}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 30,
              height: 30,
              border: `1px solid ${T.border}`,
              borderRadius: 6,
              background: "none",
              cursor: page >= totalPages - 1 ? "not-allowed" : "pointer",
              color: page >= totalPages - 1 ? T.subtle : T.text,
            }}
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
        style={{
          minHeight: "100vh",
          backgroundColor: T.bg,
          padding: "24px clamp(16px, 4vw, 40px)",
          fontFamily:
            '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
        }}
      >
        {/* Page header */}
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: 12,
            marginBottom: 28,
          }}
        >
          <div>
            <h1
              style={{
                fontSize: "clamp(20px, 3vw, 26px)",
                fontWeight: 700,
                color: T.header,
                margin: 0,
                lineHeight: 1.2,
              }}
            >
              Document Ingestion
            </h1>
            <p style={{ fontSize: 14, color: T.muted, margin: "4px 0 0" }}>
              All paths &middot; last 24h
            </p>
          </div>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "8px 16px",
              backgroundColor: T.card,
              border: `1px solid ${T.border}`,
              borderRadius: 8,
              fontSize: 13,
              fontWeight: 500,
              color: T.text,
              cursor: isFetching ? "not-allowed" : "pointer",
              opacity: isFetching ? 0.6 : 1,
            }}
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
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "14px 16px",
              backgroundColor: "#FEF2F2",
              border: `1px solid #FECACA`,
              borderRadius: 10,
              color: T.danger,
              marginBottom: 24,
              fontSize: 13,
            }}
          >
            <AlertCircle style={{ width: 16, height: 16, flexShrink: 0 }} aria-hidden="true" />
            Failed to load ingestion data. The backend aggregator may not be deployed yet.
          </div>
        )}

        {/* KPI strip */}
        <KpiStrip kpis={data?.kpis} />

        {/* Source card grid */}
        <section aria-label="Ingestion source cards" style={{ marginBottom: 36 }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 14,
            }}
          >
            <h2
              style={{
                fontSize: 15,
                fontWeight: 600,
                color: T.header,
                margin: 0,
              }}
            >
              Ingestion Sources
            </h2>
            {activeSource && (
              <button
                onClick={() => router.push("/admin/document-ingestion")}
                style={{
                  background: "none",
                  border: "none",
                  color: T.accent,
                  fontSize: 12,
                  fontWeight: 500,
                  cursor: "pointer",
                  padding: 0,
                }}
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
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
                gap: 14,
              }}
            >
              {SOURCE_META.map((m) => (
                <div
                  key={m.id}
                  style={{
                    height: 180,
                    backgroundColor: T.card,
                    border: `1px solid ${T.border}`,
                    borderRadius: 10,
                    animation: "pulse 1.5s ease-in-out infinite",
                  }}
                  aria-hidden="true"
                />
              ))}
              <span className="sr-only">Loading source cards…</span>
            </div>
          ) : (
            <div
              style={{
                display: "grid",
                // 1 col on phone, 2 on tablet, 4 on desktop
                gridTemplateColumns:
                  "repeat(auto-fill, minmax(clamp(160px, 20vw, 220px), 1fr))",
                gap: 14,
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
          <div style={{ marginBottom: 14 }}>
            <h2 style={{ fontSize: 15, fontWeight: 600, color: T.header, margin: 0 }}>
              Recent Activity
              {activeSource && (
                <span style={{ fontSize: 12, color: T.muted, fontWeight: 400, marginLeft: 8 }}>
                  filtered: {activeSource}
                </span>
              )}
            </h2>
          </div>

          <div
            style={{
              backgroundColor: T.card,
              border: `1px solid ${T.border}`,
              borderRadius: 10,
              overflow: "hidden",
            }}
          >
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
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
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
    <Suspense fallback={<div style={{ padding: 40, color: "#64748B" }}>Loading…</div>}>
      <DocumentIngestionPageInner />
    </Suspense>
  );
}
