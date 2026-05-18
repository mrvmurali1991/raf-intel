"use client";

/**
 * /worklist — "Today's priorities" page.
 *
 * The single screen a provider opens on Monday morning.  Lists patients
 * sorted by ``priority_score`` desc with their open recapture gaps,
 * suspect conditions, and estimated revenue at risk.
 *
 * Mobile-first: collapses to a single column on narrow viewports.  Each
 * patient row is a self-contained card so it survives tablet / phone
 * layouts in an exam-room context.
 *
 * Inline fetching against /api/worklist/provider/{id} — no api.ts
 * dependency so this can land alongside other api.ts edits.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CalendarClock, CheckSquare, ChevronRight, Download, ExternalLink, FileText, Activity, Loader2, Stethoscope, X } from "lucide-react";
import { useAuth } from "@/contexts/auth-context";
import { PageHeader } from "@/components/healthcare-ui";
import { tokens } from "@/styles/tokens";
import DataQualityBanner from "@/components/DataQualityBanner";
import { RejectGapModal } from "@/components/RejectGapModal";
import api from "@/lib/api";

interface RejectTarget {
  patientId: number;
  patientName: string;
  hccCode: string;
  paymentYear: number;
}

interface EvidencePreview {
  hcc_code: string;
  hcc_description: string;
  raf_lift: number;
  estimated_revenue: number;
  raw_note_excerpt: string;
  highlight_term: string;
  confidence_score: "Strong" | "Moderate" | "Calibrated";
  source_doc_id: number | null;
}

interface WorklistGap {
  hcc_code: string;
  icd10_codes?: string[];
  prior_year?: number;
  revenue_impact?: number;
  evidence_preview?: EvidencePreview | null;
}

interface WorklistSuspect {
  hcc_code: string;
  source?: string;
  confidence?: number;
}

type AwvStatus = "overdue" | "due_soon" | "current" | "future" | "unknown";

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
  awv_last_date?: string | null;
  awv_due_date?: string | null;
  awv_status?: AwvStatus;
}

interface WorklistResponse {
  provider_id: number;
  measurement_year: number;
  total: number;
  items: WorklistItem[];
}

type SortKey = "priority" | "awv_due";

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
      }}
    >
      <CheckSquare size={16} style={{ flexShrink: 0, color: "#34d399" }} />
      <span>{message}</span>
      {linkHref && linkLabel && (
        <Link href={linkHref} style={{ color: "#67e8f9", fontWeight: 700, textDecoration: "underline", whiteSpace: "nowrap" }}>
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
        background: "rgba(15,118,110,0.07)",
        backdropFilter: "blur(4px)",
        WebkitBackdropFilter: "blur(4px)",
      }}
    >
      <span className="sr-only" aria-live="polite" aria-atomic="true">
        {selectedCount} patient{selectedCount === 1 ? "" : "s"} selected
      </span>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6, background: brand, color: tokens.white, borderRadius: 999, padding: "3px 12px", fontSize: 12, fontWeight: 700 }}>
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
          Batch AWV scheduling is managed in the Calendar module. Open the calendar to
          assign appointment slots for all {selectedCount} selected patient{selectedCount === 1 ? "" : "s"}.
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

// AWV helpers ----------------------------------------------------------------

function awvPill(status: AwvStatus): { bg: string; color: string; border: string } {
  switch (status) {
    case "overdue":
      return { bg: tokens.dangerSoft, color: tokens.danger, border: tokens.dangerBorder };
    case "due_soon":
      return { bg: tokens.warningSoft, color: tokens.warningStrong, border: tokens.warningBorder };
    case "current":
      return { bg: tokens.slate100, color: tokens.slate600, border: tokens.slate200 };
    default:
      return { bg: tokens.slate50, color: tokens.slate400, border: tokens.slate200 };
  }
}

function awvLabel(status: AwvStatus, dueDate: string | null | undefined): string {
  if (status === "unknown") return "AWV unknown";
  if (!dueDate) return "AWV current";
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const due = new Date(dueDate);
  due.setHours(0, 0, 0, 0);
  const diffDays = Math.round((due.getTime() - today.getTime()) / 86_400_000);
  if (status === "overdue") return `AWV overdue by ${Math.abs(diffDays)}d`;
  if (status === "due_soon") return `AWV due in ${diffDays}d`;
  return `AWV due in ${diffDays}d`;
}

function fmtCurrency(n: number): string {
  if (Math.abs(n) >= 1000) return `$${(n / 1000).toFixed(1)}K`;
  return `$${Math.round(n).toLocaleString()}`;
}

function priorityBand(score: number): { label: string; color: string; bg: string } {
  if (score >= 70) return { label: "High", color: tokens.riskHigh, bg: tokens.riskHighSoft };
  if (score >= 40) return { label: "Medium", color: tokens.warningStrong, bg: tokens.warningSoft };
  return { label: "Low", color: tokens.success, bg: tokens.successSoft };
}

export default function WorklistPage() {
  const { user, isLoading: authLoading } = useAuth();
  const measurementYear = new Date().getFullYear();
  const providerId = user?.id ? Number(user.id) : null;
  const [awvFilter, setAwvFilter] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("priority");

  const queryClient = useQueryClient();
  const [rejectTarget, setRejectTarget] = useState<RejectTarget | null>(null);
  const [rejectedGaps, setRejectedGaps] = useState<Set<string>>(new Set());

  const handleRejected = useCallback(
    (_rejectionId: number) => {
      if (!rejectTarget) return;
      const key = `${rejectTarget.patientId}:${rejectTarget.hccCode}:${rejectTarget.paymentYear}`;
      setRejectedGaps((prev) => new Set([...prev, key]));
      queryClient.invalidateQueries({ queryKey: ["provider-worklist"] });
    },
    [rejectTarget, queryClient],
  );

  const { data, isLoading, isError, error, refetch } = useQuery<WorklistResponse>({
    queryKey: ["provider-worklist", providerId, measurementYear],
    queryFn: async () => {
      const { data } = await api.get<WorklistResponse>(
        `/api/worklist/provider/${providerId}`,
        { params: { measurement_year: measurementYear } },
      );
      return data;
    },
    enabled: providerId != null,
    staleTime: 60_000,
  });

  const displayItems = useMemo(() => {
    if (!data?.items) return [];
    let items = [...data.items];
    if (awvFilter) {
      items = items.filter((p) => p.awv_status === "overdue" || p.awv_status === "due_soon");
    }
    if (sortKey === "awv_due") {
      items.sort((a, b) => {
        const fa = a.awv_due_date ?? "9999-99-99";
        const fb = b.awv_due_date ?? "9999-99-99";
        return fa < fb ? -1 : fa > fb ? 1 : 0;
      });
    }
    return items;
  }, [data, awvFilter, sortKey]);

  const summary = useMemo(() => {
    if (!data?.items) return { patients: 0, gaps: 0, revenue: 0, awvDue: 0 };
    return {
      patients: data.items.length,
      gaps: data.items.reduce((sum, p) => sum + (p.open_recapture_gaps?.length ?? 0), 0),
      revenue: data.items.reduce((sum, p) => sum + (p.estimated_revenue_at_risk ?? 0), 0),
      awvDue: data.items.filter((p) => p.awv_status === "overdue" || p.awv_status === "due_soon").length,
    };
  }, [data]);

  if (authLoading || (providerId != null && isLoading)) {
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

  if (providerId == null) {
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
            style={{
              padding: "6px 12px",
              borderRadius: 8,
              border: `1px solid ${tokens.dangerBorder}`,
              background: tokens.white,
              color: tokens.danger,
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (data.items.length === 0) {
    return (
      <div style={{ padding: "20px 16px" }} className="rci-page-pad-desktop">
        <PageHeader title="Today's worklist" subtitle={`Measurement year ${measurementYear}`} />
        <div
          style={{
            marginTop: 24,
            padding: "32px 20px",
            borderRadius: 10,
            background: tokens.successSoft,
            border: `1px solid ${tokens.success}`,
            color: tokens.successDark,
            textAlign: "center",
          }}
        >
          <Stethoscope size={28} style={{ marginBottom: 8 }} />
          <h2 style={{ margin: "0 0 6px", fontSize: 18, fontWeight: 700 }}>You're caught up</h2>
          <p style={{ margin: 0, fontSize: 14, lineHeight: 1.5 }}>
            No prioritized patients to see this week.  When new gaps or
            suspect conditions surface, they'll appear here.
          </p>
          <div style={{ marginTop: 16, display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
            <Link
              href="/patients"
              style={{
                padding: "8px 16px",
                borderRadius: 8,
                background: tokens.white,
                color: tokens.successDark,
                border: `1px solid ${tokens.success}`,
                fontSize: 13,
                fontWeight: 600,
                textDecoration: "none",
              }}
            >
              View full panel
            </Link>
            <Link
              href="/recapture"
              style={{
                padding: "8px 16px",
                borderRadius: 8,
                background: tokens.successDark,
                color: tokens.white,
                fontSize: 13,
                fontWeight: 600,
                textDecoration: "none",
              }}
            >
              Open recapture report
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ padding: "20px 16px", maxWidth: 1280, margin: "0 auto" }} className="rci-page-pad-desktop">
      <DataQualityBanner />
      <PageHeader
        title="Today's worklist"
        subtitle={`${summary.patients} patient${summary.patients === 1 ? "" : "s"} prioritized for ${measurementYear}`}
      />

      {/* Summary strip */}
      <div
        style={{
          marginTop: 16,
          marginBottom: 16,
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: 12,
        }}
      >
        <SummaryTile label="Patients to see" value={summary.patients} icon={<Stethoscope size={18} />} color={tokens.primary} />
        <SummaryTile label="Open gaps" value={summary.gaps} icon={<FileText size={18} />} color={tokens.riskHigh} />
        <SummaryTile label="Revenue at risk" value={fmtCurrency(summary.revenue)} icon={<Activity size={18} />} color={tokens.warningStrong} />
        <SummaryTile label="AWV due/overdue" value={summary.awvDue} icon={<CalendarClock size={18} />} color={summary.awvDue > 0 ? tokens.danger : tokens.slate500} />
      </div>

      {/* Filter + sort toolbar */}
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 10, marginBottom: 20 }}>
        <button
          type="button"
          onClick={() => setAwvFilter((v) => !v)}
          aria-pressed={awvFilter}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "5px 14px",
            borderRadius: 999,
            fontSize: 12,
            fontWeight: 700,
            cursor: "pointer",
            border: `1.5px solid ${awvFilter ? tokens.danger : tokens.slate300}`,
            background: awvFilter ? tokens.dangerSoft : tokens.white,
            color: awvFilter ? tokens.danger : tokens.slate600,
            transition: "all 120ms ease",
          }}
        >
          <CalendarClock size={13} />
          AWV Due Soon{summary.awvDue > 0 ? ` (${summary.awvDue})` : ""}
        </button>
        <label htmlFor="worklist-sort" style={{ fontSize: 12, fontWeight: 600, color: tokens.slate500, whiteSpace: "nowrap" }}>
          Sort by
        </label>
        <select
          id="worklist-sort"
          value={sortKey}
          onChange={(e) => setSortKey(e.target.value as SortKey)}
          style={{
            fontSize: 12,
            fontWeight: 600,
            padding: "5px 10px",
            borderRadius: 8,
            border: `1px solid ${tokens.slate200}`,
            background: tokens.white,
            color: tokens.slate700,
            cursor: "pointer",
          }}
        >
          <option value="priority">Priority score</option>
          <option value="awv_due">AWV due date</option>
        </select>
        {awvFilter && (
          <span style={{ fontSize: 12, color: tokens.slate500 }}>
            Showing {displayItems.length} of {summary.patients}
          </span>
        )}
      </div>

      {/* Patient cards */}
      {displayItems.length === 0 ? (
        <div style={{ padding: "24px 16px", borderRadius: 10, background: tokens.slate50, border: `1px solid ${tokens.slate200}`, color: tokens.slate500, textAlign: "center", fontSize: 14 }}>
          No patients match the current filter.
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
            gap: 16,
          }}
        >
          {displayItems.map((item) => (
            <PatientCard key={item.patient_id} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}

function SummaryTile({
  label,
  value,
  icon,
  color,
}: {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  color: string;
}) {
  return (
    <div
      style={{
        padding: "14px 16px",
        borderRadius: 10,
        background: tokens.white,
        border: `1px solid ${tokens.slate200}`,
        display: "flex",
        alignItems: "center",
        gap: 12,
      }}
    >
      <div
        style={{
          width: 36,
          height: 36,
          borderRadius: 10,
          background: `${color}1A`,
          color,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
        }}
      >
        {icon}
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: tokens.slate500, textTransform: "uppercase", letterSpacing: "0.05em" }}>
          {label}
        </div>
        <div className="tabular-nums" style={{ fontSize: 22, fontWeight: 700, color: tokens.slate900, lineHeight: 1.1 }}>
          {value}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// GapChipWithPreview — HCC pill that reveals an AI evidence hover card
// ---------------------------------------------------------------------------

const CONFIDENCE_COLOR: Record<string, string> = {
  Strong: "#16a34a",
  Moderate: "#d97706",
  Calibrated: "#6366f1",
};

function HighlightedExcerpt({ text, term }: { text: string; term: string }) {
  if (!term || !text.includes(term)) {
    return <span style={{ fontFamily: "monospace", fontSize: 11, lineHeight: 1.6 }}>{text}</span>;
  }
  const idx = text.indexOf(term);
  return (
    <span style={{ fontFamily: "monospace", fontSize: 11, lineHeight: 1.6 }}>
      {text.slice(0, idx)}
      <mark
        style={{
          background: "#fef08a",
          color: "#713f12",
          borderRadius: 2,
          padding: "0 2px",
        }}
      >
        {term}
      </mark>
      {text.slice(idx + term.length)}
    </span>
  );
}

function GapChipWithPreview({
  gap,
  patientId,
  onReject,
}: {
  gap: WorklistGap;
  patientId: number;
  onReject: () => void;
}) {
  const [open, setOpen] = useState(false);
  const openTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const preview = gap.evidence_preview;

  const scheduleOpen = useCallback(() => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    openTimer.current = setTimeout(() => setOpen(true), 200);
  }, []);

  const scheduleClose = useCallback(() => {
    if (openTimer.current) clearTimeout(openTimer.current);
    closeTimer.current = setTimeout(() => setOpen(false), 150);
  }, []);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      setOpen((v) => !v);
    }
    if (e.key === "Escape") {
      setOpen(false);
    }
  }, []);

  const hccCode = String(gap.hcc_code).replace("HCC", "").trim();
  const viewChartHref = `/patients/${patientId}?gap=HCC${hccCode}`;

  return (
    <span
      style={{ position: "relative", display: "inline-block" }}
      onMouseEnter={scheduleOpen}
      onMouseLeave={scheduleClose}
    >
      {/* The pill chip */}
      <span
        role="button"
        tabIndex={0}
        aria-expanded={open}
        aria-haspopup="true"
        aria-label={`HCC ${hccCode} evidence preview`}
        onKeyDown={handleKeyDown}
        onFocus={scheduleOpen}
        onBlur={scheduleClose}
        style={{
          display: "inline-block",
          padding: "2px 8px",
          borderRadius: 999,
          background: tokens.dangerSoft,
          color: tokens.danger,
          fontSize: 11,
          fontWeight: 600,
          cursor: preview ? "pointer" : "default",
          outline: open ? `2px solid ${tokens.primary}` : undefined,
          outlineOffset: 2,
          userSelect: "none",
        }}
      >
        HCC {hccCode}
      </span>
      {/* Reject button — visible on hover of outer span */}
      <button
        type="button"
        onClick={(e) => { e.preventDefault(); e.stopPropagation(); onReject(); }}
        aria-label={`Reject HCC ${hccCode} gap`}
        title="Reject this gap"
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: 14,
          height: 14,
          borderRadius: "50%",
          border: "none",
          background: "transparent",
          color: tokens.danger,
          cursor: "pointer",
          padding: 0,
          fontSize: 10,
          fontWeight: 700,
          lineHeight: 1,
          verticalAlign: "middle",
          marginLeft: 2,
          opacity: 0.5,
        }}
        onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.opacity = "1"; (e.currentTarget as HTMLButtonElement).style.background = tokens.danger; (e.currentTarget as HTMLButtonElement).style.color = tokens.white; }}
        onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.opacity = "0.5"; (e.currentTarget as HTMLButtonElement).style.background = "transparent"; (e.currentTarget as HTMLButtonElement).style.color = tokens.danger; }}
      >
        ✕
      </button>

      {/* Hover card popover — only rendered when evidence exists and open */}
      {open && preview && (
        <div
          role="tooltip"
          data-testid={`evidence-preview-${hccCode}`}
          onMouseEnter={scheduleOpen}
          onMouseLeave={scheduleClose}
          style={{
            position: "absolute",
            bottom: "calc(100% + 8px)",
            left: "50%",
            transform: "translateX(-50%)",
            zIndex: 9999,
            width: 320,
            background: "#0f172a",
            border: "1px solid #1e3a5f",
            borderRadius: 10,
            padding: "14px 16px",
            color: "#e2e8f0",
            boxShadow: "0 8px 32px rgba(0,0,0,0.45)",
            pointerEvents: "auto",
          }}
        >
          {/* Header: code + description */}
          <div style={{ marginBottom: 10 }}>
            <span
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: tokens.danger,
                letterSpacing: "0.06em",
                textTransform: "uppercase",
              }}
            >
              HCC {preview.hcc_code}
            </span>
            <div
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: "#f1f5f9",
                marginTop: 2,
                lineHeight: 1.35,
              }}
            >
              {preview.hcc_description}
            </div>
          </div>

          {/* RAF lift + revenue row */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 8,
              marginBottom: 10,
            }}
          >
            <div
              style={{
                background: "#1e293b",
                borderRadius: 6,
                padding: "6px 10px",
              }}
            >
              <div style={{ fontSize: 10, color: "#94a3b8", fontWeight: 600, textTransform: "uppercase" }}>
                RAF Lift
              </div>
              <div style={{ fontSize: 14, fontWeight: 700, color: "#f1f5f9" }}>
                {preview.raf_lift.toFixed(3)}
              </div>
            </div>
            <div
              style={{
                background: "#1e293b",
                borderRadius: 6,
                padding: "6px 10px",
              }}
            >
              <div style={{ fontSize: 10, color: "#94a3b8", fontWeight: 600, textTransform: "uppercase" }}>
                Est. Revenue
              </div>
              <div style={{ fontSize: 14, fontWeight: 700, color: "#f1f5f9" }}>
                ${preview.estimated_revenue.toLocaleString()}
              </div>
            </div>
          </div>

          {/* Source excerpt */}
          <div
            style={{
              background: "#1e293b",
              borderRadius: 6,
              padding: "8px 10px",
              marginBottom: 10,
              lineHeight: 1.6,
              color: "#cbd5e1",
            }}
          >
            <HighlightedExcerpt
              text={preview.raw_note_excerpt}
              term={preview.highlight_term}
            />
          </div>

          {/* Confidence badge + view chart link */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <span
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: CONFIDENCE_COLOR[preview.confidence_score] ?? "#94a3b8",
                background: `${CONFIDENCE_COLOR[preview.confidence_score] ?? "#6366f1"}22`,
                borderRadius: 999,
                padding: "2px 8px",
              }}
            >
              {preview.confidence_score}
            </span>
            <Link
              href={viewChartHref}
              tabIndex={0}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                fontSize: 11,
                fontWeight: 600,
                color: "#93c5fd",
                textDecoration: "none",
              }}
              onClick={(e) => e.stopPropagation()}
            >
              View full chart <ExternalLink size={11} />
            </Link>
          </div>
        </div>
      )}
    </span>
  );
}

function PatientCard({ item }: { item: WorklistItem }) {
  const band = priorityBand(item.priority_score);
  const awvStatus: AwvStatus = item.awv_status ?? "unknown";
  const pill = awvPill(awvStatus);
  const awvText = awvLabel(awvStatus, item.awv_due_date);
  // hide the row for "future" (not actionable) to keep cards compact
  const showAwvRow = awvStatus !== "future";
  return (
    <Link
      href={`/patients/${item.patient_id}`}
      style={{
        display: "block",
        padding: 16,
        borderRadius: 10,
        background: tokens.white,
        border: `1px solid ${tokens.slate200}`,
        textDecoration: "none",
        color: "inherit",
        transition: "box-shadow 120ms ease",
      }}
      className="hover-lift"
    >
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, marginBottom: 10 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div
            style={{
              fontSize: 15,
              fontWeight: 700,
              color: tokens.slate900,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {item.patient_name}
          </div>
          <div style={{ fontSize: 12, color: tokens.slate500, marginTop: 2 }}>
            {item.dob ? `DOB ${item.dob}` : "DOB unknown"}
            {item.last_visit_date ? ` · last visit ${item.last_visit_date}` : ""}
          </div>
        </div>
        <span
          style={{
            flexShrink: 0,
            padding: "3px 10px",
            borderRadius: 999,
            background: band.bg,
            color: band.color,
            fontSize: 11,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.04em",
          }}
        >
          {band.label}
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
        <Stat
          label="Open gaps"
          value={item.open_recapture_gaps?.length ?? 0}
          tone={(item.open_recapture_gaps?.length ?? 0) > 0 ? tokens.riskHigh : tokens.slate500}
        />
        <Stat
          label="Revenue at risk"
          value={fmtCurrency(item.estimated_revenue_at_risk ?? 0)}
          tone={tokens.slate900}
        />
      </div>

      {visibleGaps.length > 0 && (
        // stopPropagation so chip clicks/hover don't bubble to the card Link
        <div
          style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}
          onClick={(e) => e.stopPropagation()}
        >
          {visibleGaps.slice(0, 4).map((g, i) => (
            <GapChipWithPreview
              key={`${g.hcc_code}-${i}`}
              gap={g}
              patientId={item.patient_id}
              onReject={() => onRejectGap(g)}
            />
          ))}
          {visibleGaps.length > 4 && (
            <span style={{ fontSize: 11, color: tokens.slate500, alignSelf: "center" }}>
              +{visibleGaps.length - 4} more
            </span>
          )}
        </div>
      )}

      {/* AWV status row */}
      {showAwvRow && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 6, marginBottom: 4 }}>
          <CalendarClock size={13} style={{ color: pill.color, flexShrink: 0 }} />
          <span
            style={{
              padding: "2px 9px",
              borderRadius: 999,
              background: pill.bg,
              color: pill.color,
              border: `1px solid ${pill.border}`,
              fontSize: 11,
              fontWeight: 700,
            }}
          >
            {awvText}
          </span>
        </div>
      )}

      <div
        style={{
          marginTop: 8,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          fontSize: 12,
          color: tokens.primary,
          fontWeight: 600,
        }}
      >
        <span>Priority score · {item.priority_score}</span>
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          Open chart <ChevronRight size={14} />
        </span>
      </div>
    </Link>
  );
}

function Stat({ label, value, tone }: { label: string; value: string | number; tone: string }) {
  return (
    <div
      style={{
        padding: "8px 10px",
        borderRadius: 8,
        background: tokens.slate50,
        border: `1px solid ${tokens.slate100}`,
      }}
    >
      <div style={{ fontSize: 10, fontWeight: 600, color: tokens.slate500, textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {label}
      </div>
      <div className="tabular-nums" style={{ fontSize: 16, fontWeight: 700, color: tone }}>
        {value}
      </div>
    </div>
  );
}
