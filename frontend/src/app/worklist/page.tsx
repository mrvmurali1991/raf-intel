"use client";

/**
 * /worklist — "Today's priorities" page.
 *
 * Admin/manager/supervisor users additionally see:
 *  - Provider Workload heatmap (collapsible) above summary tiles
 *  - Provider filter pills to scope the card grid to one provider
 *
 * Bulk-select: always-visible 16px checkbox top-left each card.
 *   Shift+Click range · Cmd/Ctrl+A select all visible · Esc clear
 * Bulk actions bar (sticky top when any selection):
 *   Send to Attestation · Schedule AWV · Export CSV
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CalendarClock,
  CheckSquare,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Download,
  FileText,
  Activity,
  Loader2,
  Stethoscope,
  Users,
  X,
} from "lucide-react";
import { useAuth } from "@/contexts/auth-context";
import { PageHeader } from "@/components/healthcare-ui";
import { tokens } from "@/styles/tokens";
import DataQualityBanner from "@/components/DataQualityBanner";
import api from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface WorklistGap {
  hcc_code: string;
  icd10_codes?: string[];
  prior_year?: number;
  revenue_impact?: number;
}

interface WorklistSuspect {
  hcc_code: string;
  source?: string;
  confidence?: number;
}

interface WorklistItem {
  patient_id: number;
  patient_name: string;
  dob?: string | null;
  last_visit_date?: string | null;
  open_recapture_gaps: WorklistGap[];
  suspect_conditions: WorklistSuspect[];
  estimated_raf_impact: number;
  estimated_revenue_at_risk: number;
  priority_score: number;
}

interface WorklistResponse {
  provider_id: number;
  measurement_year: number;
  total: number;
  items: WorklistItem[];
}

interface ProviderWorkloadRow {
  provider_id: number;
  provider_name: string;
  open_gaps: number;
  awv_due: number;
  suspect_count: number;
  total_workload: number;
  capacity_pct: number;
}

interface ProviderWorkloadResponse {
  providers: ProviderWorkloadRow[];
  total_open_gaps: number;
  target_capacity: number;
  measurement_year: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtCurrency(n: number): string {
  if (Math.abs(n) >= 1000) return `$${(n / 1000).toFixed(1)}K`;
  return `$${Math.round(n).toLocaleString()}`;
}

function priorityBand(score: number): { label: string; color: string; bg: string } {
  if (score >= 70) return { label: "High", color: tokens.riskHigh, bg: tokens.riskHighSoft };
  if (score >= 40) return { label: "Medium", color: tokens.warningStrong, bg: tokens.warningSoft };
  return { label: "Low", color: tokens.success, bg: tokens.successSoft };
}

function capacityColor(pct: number): string {
  if (pct >= 90) return tokens.riskHigh;
  if (pct >= 70) return tokens.warningStrong;
  return tokens.success;
}

const ELEVATED_ROLES = new Set(["admin", "super_admin", "manager", "supervisor"]);

// ---------------------------------------------------------------------------
// Toast
// ---------------------------------------------------------------------------

function Toast({
  message,
  linkHref,
  linkLabel,
  onDismiss,
}: {
  message: string;
  linkHref?: string;
  linkLabel?: string;
  onDismiss: () => void;
}) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 6000);
    return () => clearTimeout(t);
  }, [onDismiss]);

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: "fixed",
        bottom: 24,
        left: "50%",
        transform: "translateX(-50%)",
        zIndex: 9999,
        background: tokens.slate900,
        color: tokens.white,
        padding: "12px 20px",
        borderRadius: 10,
        display: "flex",
        alignItems: "center",
        gap: 12,
        fontSize: 13,
        fontWeight: 500,
        boxShadow: "0 8px 32px rgba(15,23,42,0.35)",
        maxWidth: "90vw",
        whiteSpace: "nowrap",
      }}
    >
      <CheckSquare size={16} style={{ flexShrink: 0, color: "#34d399" }} />
      <span>{message}</span>
      {linkHref && linkLabel && (
        <Link href={linkHref} style={{ color: "#67e8f9", fontWeight: 700, textDecoration: "underline" }}>
          {linkLabel}
        </Link>
      )}
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss notification"
        style={{ background: "none", border: "none", color: tokens.slate400, cursor: "pointer", padding: 0, marginLeft: 4, display: "flex", alignItems: "center" }}
      >
        <X size={14} />
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// WorklistBulkActionsBar
// ---------------------------------------------------------------------------

function WorklistBulkActionsBar({
  selectedCount,
  totalCount,
  onClear,
  onSelectAll,
  onAttest,
  onScheduleAWV,
  onExportCSV,
  attesting,
  exporting,
}: {
  selectedCount: number;
  totalCount: number;
  onClear: () => void;
  onSelectAll: () => void;
  onAttest: () => void;
  onScheduleAWV: () => void;
  onExportCSV: () => void;
  attesting: boolean;
  exporting: boolean;
}) {
  const brand = "#0F766E";
  if (selectedCount === 0) return null;
  return (
    <div
      role="region"
      aria-label="Bulk actions"
      style={{
        position: "sticky",
        top: 0,
        zIndex: 40,
        display: "flex",
        alignItems: "center",
        flexWrap: "wrap",
        gap: 10,
        padding: "10px 16px",
        borderBottom: `2px solid ${brand}`,
        background: "rgba(15,118,110,0.08)",
        backdropFilter: "blur(4px)",
        WebkitBackdropFilter: "blur(4px)",
      }}
    >
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {selectedCount} patient{selectedCount === 1 ? "" : "s"} selected
      </span>
      <span style={{ display: "inline-flex", alignItems: "center", background: brand, color: tokens.white, borderRadius: 999, padding: "3px 12px", fontSize: 12, fontWeight: 700 }}>
        {selectedCount} selected
      </span>
      <button type="button" onClick={onClear} aria-label="Clear selection" style={{ padding: "4px 10px", borderRadius: 6, border: `1px solid ${tokens.slate300}`, background: tokens.white, color: tokens.slate700, fontSize: 12, cursor: "pointer" }}>
        Clear
      </button>
      {selectedCount < totalCount && (
        <button type="button" onClick={onSelectAll} style={{ padding: "4px 10px", borderRadius: 6, border: `1px solid ${tokens.slate300}`, background: tokens.white, color: tokens.slate700, fontSize: 12, cursor: "pointer" }}>
          Select all {totalCount}
        </button>
      )}
      <div style={{ width: 1, height: 20, background: tokens.slate200, flexShrink: 0 }} />
      <button
        type="button"
        onClick={onAttest}
        disabled={attesting}
        aria-label={`Send ${selectedCount} patients to attestation`}
        style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 14px", borderRadius: 6, border: "none", background: attesting ? tokens.slate300 : brand, color: tokens.white, fontSize: 12, fontWeight: 600, cursor: attesting ? "not-allowed" : "pointer" }}
      >
        {attesting ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> : <FileText size={13} />}
        {attesting ? "Creating…" : "Send to Attestation"}
      </button>
      <button
        type="button"
        onClick={onScheduleAWV}
        aria-label={`Schedule AWV for ${selectedCount} patients`}
        style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 14px", borderRadius: 6, border: `1px solid ${brand}`, background: tokens.white, color: brand, fontSize: 12, fontWeight: 600, cursor: "pointer" }}
      >
        <CalendarClock size={13} />
        Schedule AWV
      </button>
      <button
        type="button"
        onClick={onExportCSV}
        disabled={exporting}
        aria-label={`Export ${selectedCount} patients to CSV`}
        style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "5px 14px", borderRadius: 6, border: `1px solid ${tokens.slate300}`, background: tokens.white, color: tokens.slate700, fontSize: 12, fontWeight: 600, cursor: exporting ? "not-allowed" : "pointer" }}
      >
        {exporting ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} /> : <Download size={13} />}
        {exporting ? "Exporting…" : "Export CSV"}
      </button>
      <span aria-hidden style={{ marginLeft: "auto", fontSize: 11, color: tokens.slate500, fontStyle: "italic" }}>
        Shift+Click range · Cmd/Ctrl+A all · Esc clear
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// AWV batch modal
// ---------------------------------------------------------------------------

function AWVBatchModal({ selectedCount, onClose }: { selectedCount: number; onClose: () => void }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Schedule AWV for selected patients"
      tabIndex={-1}
      style={{ position: "fixed", inset: 0, zIndex: 9990, background: "rgba(0,0,0,0.6)", display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}
      onClick={onClose}
    >
      <div
        style={{ background: tokens.white, borderRadius: 12, boxShadow: "0 12px 48px rgba(15,23,42,0.25)", width: "100%", maxWidth: 480, padding: 24 }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: tokens.slate900 }}>
            Schedule AWV — {selectedCount} patient{selectedCount === 1 ? "" : "s"}
          </h3>
          <button type="button" onClick={onClose} aria-label="Close" style={{ background: "none", border: "none", cursor: "pointer", color: tokens.slate500, display: "flex" }}>
            <X size={18} />
          </button>
        </div>
        <p style={{ fontSize: 13, color: tokens.slate600, margin: "0 0 16px" }}>
          Batch AWV scheduling is managed in the Calendar module. Open the calendar to assign
          appointment slots for all {selectedCount} selected patient{selectedCount === 1 ? "" : "s"}.
        </p>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button type="button" onClick={onClose} style={{ padding: "7px 14px", borderRadius: 6, border: `1px solid ${tokens.slate300}`, background: tokens.white, color: tokens.slate700, fontSize: 13, cursor: "pointer" }}>
            Cancel
          </button>
          <Link href="/appointments" style={{ padding: "7px 16px", borderRadius: 6, background: "#0F766E", color: tokens.white, fontSize: 13, fontWeight: 600, textDecoration: "none" }}>
            Open Calendar
          </Link>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// WorklistPage
// ---------------------------------------------------------------------------

export default function WorklistPage() {
  const { user, isLoading: authLoading } = useAuth();
  const measurementYear = new Date().getFullYear();
  const providerId = user?.id ? Number(user.id) : null;
  const isElevated = Boolean(user?.role && ELEVATED_ROLES.has(user.role));

  const [heatmapOpen, setHeatmapOpen] = useState(true);
  const [filterProviderId, setFilterProviderId] = useState<number | null>(null);

  // Bulk-select state
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const lastClickedIndexRef = useRef<number | null>(null);
  const [attesting, setAttesting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [awvBatchOpen, setAwvBatchOpen] = useState(false);
  const [bulkToast, setBulkToast] = useState<{ message: string; linkHref?: string; linkLabel?: string } | null>(null);

  const queryProviderId = isElevated ? (filterProviderId ?? providerId) : providerId;

  const { data, isLoading, isError, error, refetch } = useQuery<WorklistResponse>({
    queryKey: ["provider-worklist", queryProviderId, measurementYear],
    queryFn: async () => {
      const { data } = await api.get<WorklistResponse>(
        `/api/worklist/provider/${queryProviderId}`,
        { params: { measurement_year: measurementYear } },
      );
      return data;
    },
    enabled: queryProviderId != null,
    staleTime: 60_000,
  });

  const { data: workloadData, isLoading: workloadLoading } =
    useQuery<ProviderWorkloadResponse>({
      queryKey: ["provider-workload", measurementYear],
      queryFn: async () => {
        const { data } = await api.get<ProviderWorkloadResponse>(
          "/api/worklist/provider-workload",
          { params: { measurement_year: measurementYear } },
        );
        return data;
      },
      enabled: isElevated,
      staleTime: 120_000,
    });

  const visibleItems = useMemo(() => data?.items ?? [], [data]);

  // Keyboard shortcuts: Cmd/Ctrl+A selects all visible, Esc clears
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (visibleItems.length === 0) return;
      const tag = (document.activeElement as HTMLElement)?.tagName?.toLowerCase();
      if ((e.metaKey || e.ctrlKey) && e.key === "a") {
        if (tag === "input" || tag === "textarea") return;
        e.preventDefault();
        setSelectedIds(new Set(visibleItems.map((i) => i.patient_id)));
      }
      if (e.key === "Escape") {
        setSelectedIds(new Set());
        lastClickedIndexRef.current = null;
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [visibleItems]);

  const handleCardSelect = useCallback(
    (patientId: number, index: number, shiftKey: boolean) => {
      setSelectedIds((prev) => {
        const next = new Set(prev);
        if (shiftKey && lastClickedIndexRef.current != null) {
          const lo = Math.min(index, lastClickedIndexRef.current);
          const hi = Math.max(index, lastClickedIndexRef.current);
          for (let i = lo; i <= hi; i++) next.add(visibleItems[i].patient_id);
        } else {
          if (next.has(patientId)) next.delete(patientId);
          else next.add(patientId);
        }
        lastClickedIndexRef.current = index;
        return next;
      });
    },
    [visibleItems],
  );

  const handleBulkAttest = useCallback(async () => {
    if (selectedIds.size === 0) return;
    setAttesting(true);
    try {
      const { data: result } = await api.post<{ created: number }>("/api/v1/worklist/bulk-attest", {
        patient_ids: Array.from(selectedIds),
      });
      setBulkToast({
        message: `${result.created} attestation${result.created === 1 ? "" : "s"} created`,
        linkHref: "/attestations",
        linkLabel: "View in Attestations",
      });
      setSelectedIds(new Set());
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setBulkToast({ message: `Error: ${detail ?? "Attestation creation failed"}` });
    } finally {
      setAttesting(false);
    }
  }, [selectedIds]);

  const handleBulkExportCSV = useCallback(async () => {
    if (selectedIds.size === 0) return;
    setExporting(true);
    try {
      const resp = await api.post(
        "/api/v1/worklist/bulk-export",
        { patient_ids: Array.from(selectedIds) },
        { responseType: "blob" },
      );
      const url = URL.createObjectURL(new Blob([resp.data], { type: "text/csv" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `worklist_export_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setBulkToast({ message: "CSV export failed. Please try again." });
    } finally {
      setExporting(false);
    }
  }, [selectedIds]);

  const summary = useMemo(() => {
    if (!data?.items) return { patients: 0, gaps: 0, revenue: 0 };
    return {
      patients: data.items.length,
      gaps: data.items.reduce((s, p) => s + (p.open_recapture_gaps?.length ?? 0), 0),
      revenue: data.items.reduce((s, p) => s + (p.estimated_revenue_at_risk ?? 0), 0),
    };
  }, [data]);

  const providerPills = useMemo(() => {
    if (!workloadData?.providers) return [];
    return workloadData.providers.map((p) => ({
      id: p.provider_id,
      name: p.provider_name,
      taskCount: p.total_workload,
    }));
  }, [workloadData]);

  // ---- Guards ----

  if (authLoading || (queryProviderId != null && isLoading)) {
    return (
      <div style={{ padding: "20px 16px" }} className="rci-page-pad-desktop">
        <PageHeader title="Today's worklist" subtitle="Loading prioritized patients…" />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 16, marginTop: 16 }}>
          {[1, 2, 3].map((i) => (
            <div key={i} className="premium-card shimmer" style={{ height: 140, borderRadius: 10 }} />
          ))}
        </div>
      </div>
    );
  }

  if (queryProviderId == null) {
    return (
      <div style={{ padding: "20px 16px" }} className="rci-page-pad-desktop">
        <PageHeader title="Today's worklist" />
        <div style={{ marginTop: 16, padding: 16, borderRadius: 10, background: tokens.warningSoft, border: `1px solid ${tokens.warningBorder}`, color: tokens.warningText, fontSize: 14 }}>
          Sign in to view your worklist.
        </div>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div style={{ padding: "20px 16px" }} className="rci-page-pad-desktop">
        <PageHeader title="Today's worklist" />
        <div role="alert" style={{ marginTop: 16, padding: 14, borderRadius: 10, background: tokens.dangerSoft, border: `1px solid ${tokens.dangerBorder}`, color: tokens.danger, display: "flex", alignItems: "center", gap: 10, fontSize: 14 }}>
          <AlertTriangle size={18} />
          <span style={{ flex: 1 }}>
            Couldn't load your worklist{error instanceof Error ? `: ${error.message}` : ""}
          </span>
          <button
            type="button"
            onClick={() => refetch()}
            aria-label="Retry loading worklist"
            style={{ padding: "6px 12px", borderRadius: 8, border: `1px solid ${tokens.dangerBorder}`, background: tokens.white, color: tokens.danger, fontSize: 13, fontWeight: 600, cursor: "pointer" }}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (data.items.length === 0 && !isElevated) {
    return (
      <div style={{ padding: "20px 16px" }} className="rci-page-pad-desktop">
        <PageHeader title="Today's worklist" subtitle={`Measurement year ${measurementYear}`} />
        <div style={{ marginTop: 24, padding: "32px 20px", borderRadius: 10, background: tokens.successSoft, border: `1px solid ${tokens.success}`, color: tokens.successDark, textAlign: "center" }}>
          <Stethoscope size={28} style={{ marginBottom: 8 }} />
          <h2 style={{ margin: "0 0 6px", fontSize: 18, fontWeight: 700 }}>You're caught up</h2>
          <p style={{ margin: 0, fontSize: 14, lineHeight: 1.5 }}>
            No prioritized patients to see this week.
          </p>
          <div style={{ marginTop: 16, display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
            <Link href="/patients" style={{ padding: "8px 16px", borderRadius: 8, background: tokens.white, color: tokens.successDark, border: `1px solid ${tokens.success}`, fontSize: 13, fontWeight: 600, textDecoration: "none" }}>
              View full panel
            </Link>
            <Link href="/recapture" style={{ padding: "8px 16px", borderRadius: 8, background: tokens.successDark, color: tokens.white, fontSize: 13, fontWeight: 600, textDecoration: "none" }}>
              Open recapture report
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <>
      {/* Sticky bulk-actions bar — only appears when cards are selected */}
      <WorklistBulkActionsBar
        selectedCount={selectedIds.size}
        totalCount={visibleItems.length}
        onClear={() => { setSelectedIds(new Set()); lastClickedIndexRef.current = null; }}
        onSelectAll={() => setSelectedIds(new Set(visibleItems.map((i) => i.patient_id)))}
        onAttest={handleBulkAttest}
        onScheduleAWV={() => setAwvBatchOpen(true)}
        onExportCSV={handleBulkExportCSV}
        attesting={attesting}
        exporting={exporting}
      />

      <div style={{ padding: "20px 16px", maxWidth: 1280, margin: "0 auto" }} className="rci-page-pad-desktop">
        <DataQualityBanner />
        <PageHeader
          title="Today's worklist"
          subtitle={`${summary.patients} patient${summary.patients === 1 ? "" : "s"} prioritized for ${measurementYear}`}
        />

        {/* Provider Workload Heatmap — elevated roles only */}
        {isElevated && (
          <section
            style={{ marginTop: 20, borderRadius: 10, border: `1px solid ${tokens.slate200}`, background: tokens.white, overflow: "hidden" }}
            aria-label="Provider workload heatmap"
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px", borderBottom: heatmapOpen ? `1px solid ${tokens.slate100}` : "none", background: tokens.slate50 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Users size={16} color={tokens.slate600} />
                <span style={{ fontWeight: 700, fontSize: 14, color: tokens.slate800 }}>Provider Workload</span>
                {workloadData && (
                  <span style={{ fontSize: 12, color: tokens.slate500, fontWeight: 400 }}>
                    — Total open: {workloadData.total_open_gaps} gaps
                  </span>
                )}
              </div>
              <button
                type="button"
                aria-expanded={heatmapOpen}
                aria-label={heatmapOpen ? "Collapse workload heatmap" : "Expand workload heatmap"}
                onClick={() => setHeatmapOpen((v) => !v)}
                style={{ display: "flex", alignItems: "center", gap: 4, padding: "4px 10px", borderRadius: 6, border: `1px solid ${tokens.slate200}`, background: tokens.white, color: tokens.slate600, fontSize: 12, fontWeight: 600, cursor: "pointer" }}
              >
                {heatmapOpen ? <><ChevronUp size={13} /> Collapse</> : <><ChevronDown size={13} /> Expand</>}
              </button>
            </div>

            {heatmapOpen && (
              <div style={{ padding: "12px 16px 16px" }}>
                {workloadLoading && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {[1, 2, 3].map((i) => <div key={i} className="shimmer" style={{ height: 36, borderRadius: 6 }} />)}
                  </div>
                )}
                {!workloadLoading && (!workloadData || workloadData.providers.length === 0) && (
                  <p style={{ margin: 0, fontSize: 13, color: tokens.slate500 }}>
                    No provider data available for {measurementYear}.
                  </p>
                )}
                {!workloadLoading && workloadData && workloadData.providers.length > 0 && (
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    {workloadData.providers.map((prov) => (
                      <HeatmapRow
                        key={prov.provider_id}
                        prov={prov}
                        isSelected={filterProviderId === prov.provider_id}
                        onClick={() => setFilterProviderId((c) => c === prov.provider_id ? null : prov.provider_id)}
                      />
                    ))}
                  </div>
                )}
              </div>
            )}
          </section>
        )}

        {/* Summary strip */}
        <div style={{ marginTop: 16, marginBottom: isElevated ? 8 : 24, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 }}>
          <SummaryTile label="Patients to see" value={summary.patients} icon={<Stethoscope size={18} />} color={tokens.primary} />
          <SummaryTile label="Open gaps" value={summary.gaps} icon={<FileText size={18} />} color={tokens.riskHigh} />
          <SummaryTile label="Revenue at risk" value={fmtCurrency(summary.revenue)} icon={<Activity size={18} />} color={tokens.warningStrong} />
        </div>

        {/* Provider filter pills — elevated only */}
        {isElevated && providerPills.length > 0 && (
          <div role="group" aria-label="Filter by provider" style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12, marginBottom: 20 }}>
            <ProviderPill label="All providers" count={null} active={filterProviderId === null} onClick={() => setFilterProviderId(null)} />
            {providerPills.map((p) => (
              <ProviderPill
                key={p.id}
                label={p.name}
                count={p.taskCount}
                active={filterProviderId === p.id}
                onClick={() => setFilterProviderId((c) => c === p.id ? null : p.id)}
              />
            ))}
          </div>
        )}

        {/* Patient cards */}
        {visibleItems.length === 0 ? (
          <div style={{ marginTop: 8, padding: "28px 20px", borderRadius: 10, background: tokens.successSoft, border: `1px solid ${tokens.success}`, color: tokens.successDark, textAlign: "center" }}>
            <Stethoscope size={24} style={{ marginBottom: 6 }} />
            <p style={{ margin: 0, fontSize: 14 }}>No patients for the selected provider.</p>
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 16 }}>
            {visibleItems.map((item, index) => (
              <PatientCard
                key={item.patient_id}
                item={item}
                isSelected={selectedIds.has(item.patient_id)}
                onSelect={(shiftKey) => handleCardSelect(item.patient_id, index, shiftKey)}
              />
            ))}
          </div>
        )}
      </div>

      {/* AWV batch modal */}
      {awvBatchOpen && (
        <AWVBatchModal selectedCount={selectedIds.size} onClose={() => setAwvBatchOpen(false)} />
      )}

      {/* Success/error toast */}
      {bulkToast && (
        <Toast
          message={bulkToast.message}
          linkHref={bulkToast.linkHref}
          linkLabel={bulkToast.linkLabel}
          onDismiss={() => setBulkToast(null)}
        />
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </>
  );
}

// ---------------------------------------------------------------------------
// HeatmapRow
// ---------------------------------------------------------------------------

function HeatmapRow({ prov, isSelected, onClick }: { prov: ProviderWorkloadRow; isSelected: boolean; onClick: () => void }) {
  const barColor = capacityColor(prov.capacity_pct);
  const barPct = Math.max(prov.capacity_pct, 2);
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={isSelected}
      aria-label={`${prov.provider_name}: ${prov.capacity_pct}% capacity. Click to filter.`}
      style={{ display: "grid", gridTemplateColumns: "180px 1fr 120px", alignItems: "center", gap: 12, padding: "6px 8px", borderRadius: 8, border: isSelected ? `1.5px solid ${barColor}` : `1px solid ${tokens.slate100}`, background: isSelected ? `${barColor}0D` : "transparent", cursor: "pointer", textAlign: "left", width: "100%" }}
    >
      <span style={{ fontSize: 13, fontWeight: 600, color: tokens.slate800, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {prov.provider_name}
      </span>
      <div style={{ height: 10, borderRadius: 999, background: tokens.slate100, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${barPct}%`, background: barColor, borderRadius: 999, transition: "width 300ms ease" }} />
      </div>
      <span style={{ fontSize: 12, color: tokens.slate500, whiteSpace: "nowrap", textAlign: "right" }}>
        <span style={{ fontWeight: 700, color: barColor }}>{prov.capacity_pct}%</span>{" · "}{prov.total_workload} tasks
      </span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// ProviderPill
// ---------------------------------------------------------------------------

function ProviderPill({ label, count, active, onClick }: { label: string; count: number | null; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "4px 12px", borderRadius: 999, border: `1.5px solid ${active ? tokens.primary : tokens.slate200}`, background: active ? tokens.primarySoft : tokens.white, color: active ? tokens.primary : tokens.slate600, fontSize: 12, fontWeight: 600, cursor: "pointer", transition: "all 100ms ease", whiteSpace: "nowrap" }}
    >
      {label}
      {count !== null && (
        <span style={{ padding: "1px 6px", borderRadius: 999, background: active ? tokens.primary : tokens.slate200, color: active ? tokens.white : tokens.slate600, fontSize: 11 }}>
          {count}
        </span>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// SummaryTile
// ---------------------------------------------------------------------------

function SummaryTile({ label, value, icon, color }: { label: string; value: string | number; icon: React.ReactNode; color: string }) {
  return (
    <div style={{ padding: "14px 16px", borderRadius: 10, background: tokens.white, border: `1px solid ${tokens.slate200}`, display: "flex", alignItems: "center", gap: 12 }}>
      <div style={{ width: 36, height: 36, borderRadius: 10, background: `${color}1A`, color, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
        {icon}
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: tokens.slate500, textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</div>
        <div className="tabular-nums" style={{ fontSize: 22, fontWeight: 700, color: tokens.slate900, lineHeight: 1.1 }}>{value}</div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// PatientCard — always-visible 16px checkbox top-left
// ---------------------------------------------------------------------------

function PatientCard({
  item,
  isSelected,
  onSelect,
}: {
  item: WorklistItem;
  isSelected: boolean;
  onSelect: (shiftKey: boolean) => void;
}) {
  const band = priorityBand(item.priority_score);
  const brand = "#0F766E";

  const handleCheckboxClick = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    onSelect(e.shiftKey);
  };

  const handleCardClick = (e: React.MouseEvent) => {
    // When a selection is already active or shift is held, toggle instead of navigating
    if (isSelected || e.shiftKey) {
      e.preventDefault();
      onSelect(e.shiftKey);
    }
  };

  return (
    <div style={{ position: "relative" }}>
      {/* 16px checkbox — always visible, positioned top-left */}
      <button
        type="button"
        role="checkbox"
        aria-checked={isSelected}
        aria-label={`Select ${item.patient_name}`}
        onClick={handleCheckboxClick}
        style={{
          position: "absolute",
          top: 10,
          left: 10,
          zIndex: 10,
          width: 16,
          height: 16,
          borderRadius: 4,
          border: isSelected ? `2px solid ${brand}` : `2px solid ${tokens.slate300}`,
          background: isSelected ? brand : tokens.white,
          cursor: "pointer",
          padding: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          transition: "background 100ms, border-color 100ms",
          boxShadow: isSelected ? `0 0 0 3px rgba(15,118,110,0.18)` : undefined,
        }}
      >
        {isSelected && (
          <svg width="9" height="7" viewBox="0 0 9 7" fill="none" aria-hidden>
            <path d="M1 3.5L3.5 6L8 1" stroke="white" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </button>

      <Link
        href={`/patients/${item.patient_id}`}
        onClick={handleCardClick}
        style={{
          display: "block",
          padding: "16px 16px 16px 34px",
          borderRadius: 10,
          background: isSelected ? "rgba(15,118,110,0.06)" : tokens.white,
          border: isSelected ? `1.5px solid ${brand}` : `1px solid ${tokens.slate200}`,
          textDecoration: "none",
          color: "inherit",
          transition: "box-shadow 120ms ease, border-color 120ms, background 120ms",
        }}
        className="hover-lift"
      >
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, marginBottom: 10 }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: tokens.slate900, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.patient_name}</div>
            <div style={{ fontSize: 12, color: tokens.slate500, marginTop: 2 }}>
              {item.dob ? `DOB ${item.dob}` : "DOB unknown"}
              {item.last_visit_date ? ` · last visit ${item.last_visit_date}` : ""}
            </div>
          </div>
          <span style={{ flexShrink: 0, padding: "3px 10px", borderRadius: 999, background: band.bg, color: band.color, fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.04em" }}>
            {band.label}
          </span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
          <Stat label="Open gaps" value={item.open_recapture_gaps?.length ?? 0} tone={(item.open_recapture_gaps?.length ?? 0) > 0 ? tokens.riskHigh : tokens.slate500} />
          <Stat label="Revenue at risk" value={fmtCurrency(item.estimated_revenue_at_risk ?? 0)} tone={tokens.slate900} />
        </div>
        {item.open_recapture_gaps && item.open_recapture_gaps.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
            {item.open_recapture_gaps.slice(0, 4).map((g, i) => (
              <span key={`${g.hcc_code}-${i}`} style={{ padding: "2px 8px", borderRadius: 999, background: tokens.dangerSoft, color: tokens.danger, fontSize: 11, fontWeight: 600 }}>
                HCC {g.hcc_code}
              </span>
            ))}
            {item.open_recapture_gaps.length > 4 && (
              <span style={{ fontSize: 11, color: tokens.slate500, alignSelf: "center" }}>+{item.open_recapture_gaps.length - 4} more</span>
            )}
          </div>
        )}
        <div style={{ marginTop: 8, display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 12, color: tokens.primary, fontWeight: 600 }}>
          <span>Priority score · {item.priority_score}</span>
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}>Open chart <ChevronRight size={14} /></span>
        </div>
      </Link>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stat
// ---------------------------------------------------------------------------

function Stat({ label, value, tone }: { label: string; value: string | number; tone: string }) {
  return (
    <div style={{ padding: "8px 10px", borderRadius: 8, background: tokens.slate50, border: `1px solid ${tokens.slate100}` }}>
      <div style={{ fontSize: 10, fontWeight: 600, color: tokens.slate500, textTransform: "uppercase", letterSpacing: "0.05em" }}>{label}</div>
      <div className="tabular-nums" style={{ fontSize: 16, fontWeight: 700, color: tone }}>{value}</div>
    </div>
  );
}
