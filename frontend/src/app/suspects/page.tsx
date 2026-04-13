"use client";

import React, { useState, useMemo, useCallback, useEffect, useRef, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getSuspects,
  acceptSuspect,
  dismissSuspect,
  bulkUpdateSuspects,
} from "@/lib/api";
import type { DBSuspect } from "@/types";
import { useToast } from "@/components/Toast";
import {
  ClipboardList,
  TrendingUp,
  DollarSign,
  Activity,
  Search,
  FileSearch,
  ChevronLeft,
  ChevronRight,
  AlertCircle,
  FileDown,
  Check,
  X,
  CheckCircle2,
  XCircle,
  Pill,
  FlaskConical,
  ScanLine,
  Stethoscope,
  Clock,
  Sparkles,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { downloadCSV } from "@/lib/csv-export";
import { C, FONT_SYS, FONT_MONO, initialsColor, deriveInitials } from "@/lib/ui-utils";

/* ================================================================== */
/*  Page-specific constants                                            */
/* ================================================================== */

const REVENUE_PER_RAF = 11015;
const PAGE_SIZE = 25;

type StatusTab = "all" | "open" | "accepted" | "dismissed" | "coded";
type EvidenceFilter = "all" | "medication" | "lab" | "imaging" | "referral" | "historical";
type ConfidenceBand = "all" | "high" | "medium" | "low";
type SortField = "confidence" | "patient" | "raf";

const STATUS_TABS: { value: StatusTab; label: string; dot: string | null }[] = [
  { value: "all", label: "All", dot: null },
  { value: "open", label: "Open", dot: C.blue },
  { value: "accepted", label: "Accepted", dot: C.low },
  { value: "dismissed", label: "Dismissed", dot: "#94A3B8" },
  { value: "coded", label: "Coded", dot: C.brand },
];

const EVIDENCE_FILTERS: { value: EvidenceFilter; label: string }[] = [
  { value: "all", label: "All Sources" },
  { value: "lab", label: "Lab" },
  { value: "medication", label: "Medication" },
  { value: "imaging", label: "Imaging" },
  { value: "referral", label: "Referral" },
  { value: "historical", label: "Historical" },
];

const CONFIDENCE_OPTIONS: { value: ConfidenceBand; label: string; color: string }[] = [
  { value: "all", label: "Any", color: C.textSubtle },
  { value: "high", label: "High >85%", color: C.low },
  { value: "medium", label: "Med 65-85%", color: C.medium },
  { value: "low", label: "Low <65%", color: C.high },
];

const VALID_STATUS: StatusTab[] = ["all", "open", "accepted", "dismissed", "coded"];
const VALID_EVIDENCE: EvidenceFilter[] = ["all", "medication", "lab", "imaging", "referral", "historical"];
const VALID_CONFIDENCE: ConfidenceBand[] = ["all", "high", "medium", "low"];
const VALID_SORT: SortField[] = ["confidence", "patient", "raf"];

/* ================================================================== */
/*  Helpers                                                            */
/* ================================================================== */

function confColor(score: number): string {
  if (score >= 0.85) return C.low;
  if (score >= 0.65) return C.medium;
  return C.textSubtle;
}

function confSoftBg(score: number): string {
  if (score >= 0.85) return C.lowSoft;
  if (score >= 0.65) return C.mediumSoft;
  return "#F1F5F9";
}

function confAccent(score: number): string {
  if (score >= 0.85) return C.low;
  if (score >= 0.65) return C.medium;
  return "#CBD5E1";
}

function matchesBand(score: number, band: ConfidenceBand): boolean {
  if (band === "all") return true;
  if (band === "high") return score >= 0.85;
  if (band === "medium") return score >= 0.65 && score < 0.85;
  return score < 0.65;
}

function evidenceIcon(type: string | undefined, size = 12) {
  switch (type) {
    case "medication": return <Pill size={size} />;
    case "lab": return <FlaskConical size={size} />;
    case "imaging": return <ScanLine size={size} />;
    case "referral": return <Stethoscope size={size} />;
    case "historical": return <Clock size={size} />;
    default: return <ClipboardList size={size} />;
  }
}

function evidenceLabelShort(type: string | undefined): string {
  switch (type) {
    case "medication": return "Medication";
    case "lab": return "Lab";
    case "imaging": return "Imaging";
    case "referral": return "Referral";
    case "historical": return "Historical";
    default: return "Clinical";
  }
}

function rationaleText(s: DBSuspect): string {
  if (s.trigger_value && s.trigger_value.trim()) return s.trigger_value;
  const evd = (s.evidence_detail && typeof s.evidence_detail === "object")
    ? s.evidence_detail as Record<string, unknown>
    : null;
  if (evd) {
    const rationale = (evd.rationale ?? evd.reason ?? evd.summary) as string | undefined;
    if (rationale) return rationale;
    const parts: string[] = [];
    if (evd.result_name) parts.push(String(evd.result_name));
    if (evd.result_value != null) parts.push(`${evd.result_value}`);
    if (evd.drug_name) parts.push(String(evd.drug_name));
    if (parts.length) return parts.join(" \u2014 ");
  }
  return "Clinical evidence detected \u2014 review chart";
}

function getCoefficient(s: DBSuspect): number {
  const coef = (s as unknown as { hcc_coefficient?: number }).hcc_coefficient;
  if (typeof coef === "number" && coef > 0) return coef;
  return 0.25;
}

function formatCurrency(n: number): string {
  if (!isFinite(n)) return "$0";
  return `$${Math.round(n).toLocaleString()}`;
}

function statusPill(status: string | undefined): { bg: string; fg: string; border: string; label: string } {
  switch (status) {
    case "accepted":
      return { bg: C.lowSoft, fg: C.low, border: "rgba(5, 150, 105, 0.25)", label: "Accepted" };
    case "dismissed":
      return { bg: "#F1F5F9", fg: C.textSubtle, border: C.border, label: "Dismissed" };
    case "coded":
      return { bg: C.brandSoft, fg: C.brand, border: C.brandRing, label: "Coded" };
    default:
      return { bg: C.blueSoft, fg: "#0369A1", border: "rgba(14, 165, 233, 0.25)", label: "Open" };
  }
}

/* ================================================================== */
/*  TH style helper (shared across all header cells)                   */
/* ================================================================== */

const TH_STYLE: React.CSSProperties = {
  padding: "12px 8px",
  textAlign: "left",
  fontSize: 11,
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: "0.06em",
  color: C.label,
  whiteSpace: "nowrap",
  borderBottom: `1px solid ${C.border}`,
};

/* ================================================================== */
/*  Skeleton row                                                       */
/* ================================================================== */

function SkeletonRow({ index }: { index: number }) {
  return (
    <tr style={{ animation: `pulseSk 1.4s ease-in-out ${index * 80}ms infinite` }}>
      <td style={{ padding: "12px 22px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ width: 36, height: 36, borderRadius: 10, background: "#E2E8F0" }} />
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6 }}>
            <div style={{ width: "70%", height: 12, borderRadius: 4, background: "#E2E8F0" }} />
            <div style={{ width: "50%", height: 9, borderRadius: 4, background: "#EEF2F6" }} />
          </div>
        </div>
      </td>
      <td style={{ padding: "12px 8px" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ width: "80%", height: 12, borderRadius: 4, background: "#E2E8F0" }} />
          <div style={{ width: "55%", height: 9, borderRadius: 4, background: "#EEF2F6" }} />
        </div>
      </td>
      <td className="suspects-hide-1024" style={{ padding: "12px 8px" }}>
        <div style={{ width: 92, height: 22, borderRadius: 999, background: "#E2E8F0" }} />
      </td>
      <td style={{ padding: "12px 8px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ flex: 1, height: 6, borderRadius: 4, background: "#E2E8F0" }} />
          <div style={{ width: 30, height: 12, borderRadius: 4, background: "#E2E8F0" }} />
        </div>
      </td>
      <td className="suspects-hide-1024" style={{ padding: "12px 8px", textAlign: "right" as const }}>
        <div style={{ width: 50, height: 14, borderRadius: 4, background: "#E2E8F0", marginLeft: "auto" }} />
      </td>
      <td style={{ padding: "12px 8px", textAlign: "right" as const }}>
        <div style={{ width: 60, height: 14, borderRadius: 4, background: "#E2E8F0", marginLeft: "auto" }} />
      </td>
      <td style={{ padding: "12px 8px", textAlign: "right" as const }}>
        <div style={{ width: 78, height: 22, borderRadius: 999, background: "#E2E8F0", marginLeft: "auto" }} />
      </td>
      <td style={{ padding: "12px 22px", textAlign: "right" as const }}>
        <div style={{ width: 64, height: 28, borderRadius: 8, background: "#E2E8F0", marginLeft: "auto" }} />
      </td>
    </tr>
  );
}

/* ================================================================== */
/*  Inner component (uses useSearchParams, needs Suspense boundary)    */
/* ================================================================== */

function SuspectsPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const toast = useToast();

  /* --- Initialize state from URL query params ---------------------- */
  const paramStatus = searchParams.get("status") as StatusTab | null;
  const paramEvidence = searchParams.get("evidence") as EvidenceFilter | null;
  const paramConfidence = searchParams.get("confidence") as ConfidenceBand | null;
  const paramSort = searchParams.get("sort") as SortField | null;

  const initStatus: StatusTab = paramStatus && VALID_STATUS.includes(paramStatus) ? paramStatus : "open";
  const initEvidence: EvidenceFilter = paramEvidence && VALID_EVIDENCE.includes(paramEvidence) ? paramEvidence : "all";
  const initConfidence: ConfidenceBand = paramConfidence && VALID_CONFIDENCE.includes(paramConfidence) ? paramConfidence : "all";
  const initSearch = searchParams.get("q") || "";
  const initSort: SortField = paramSort && VALID_SORT.includes(paramSort) ? paramSort : "confidence";

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [statusFilter, setStatusFilter] = useState<StatusTab>(initStatus);
  const [evidenceFilter, setEvidenceFilter] = useState<EvidenceFilter>(initEvidence);
  const [searchTerm, setSearchTerm] = useState(initSearch);
  const [confidenceBand, setConfidenceBand] = useState<ConfidenceBand>(initConfidence);
  const [sortField, setSortField] = useState<SortField>(initSort);
  const [page, setPage] = useState(0);
  const [bulkAction, setBulkAction] = useState<"accept" | "dismiss" | null>(null);
  const [hoveredId, setHoveredId] = useState<number | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const [expandedRationale, setExpandedRationale] = useState<Set<number>>(new Set());
  const [measurementYear, setMeasurementYear] = useState<number>(2026);

  /* --- Sync filters to URL ----------------------------------------- */
  const isInitialMount = useRef(true);
  useEffect(() => {
    if (isInitialMount.current) {
      isInitialMount.current = false;
      return;
    }
    const params = new URLSearchParams();
    if (statusFilter !== "open") params.set("status", statusFilter);
    if (evidenceFilter !== "all") params.set("evidence", evidenceFilter);
    if (confidenceBand !== "all") params.set("confidence", confidenceBand);
    if (searchTerm.trim()) params.set("q", searchTerm.trim());
    if (sortField !== "confidence") params.set("sort", sortField);
    const qs = params.toString();
    router.replace(qs ? `/suspects?${qs}` : "/suspects", { scroll: false });
  }, [statusFilter, evidenceFilter, confidenceBand, searchTerm, sortField, router]);

  /* --- Data -------------------------------------------------------- */

  const { data: suspectsData, isLoading, isError } = useQuery({
    queryKey: ["suspects", statusFilter],
    queryFn: () => getSuspects(statusFilter === "coded" ? "all" : statusFilter, 500),
  });

  const allSuspects: DBSuspect[] = useMemo(
    () => suspectsData?.suspects ?? [],
    [suspectsData?.suspects]
  );

  const statusCounts = useMemo(() => {
    const counts: Record<StatusTab, number> = {
      all: allSuspects.length,
      open: 0, accepted: 0, dismissed: 0, coded: 0,
    };
    for (const s of allSuspects) {
      const st = (s.status || "open") as StatusTab;
      if (st in counts) counts[st]++;
    }
    return counts;
  }, [allSuspects]);

  const filteredSorted = useMemo(() => {
    let list = allSuspects;

    if (statusFilter !== "all") {
      list = list.filter((s) => (s.status || "open") === statusFilter);
    }

    if (evidenceFilter !== "all") {
      list = list.filter((s) => (s.evidence_type || "") === evidenceFilter);
    }

    if (searchTerm.trim()) {
      const t = searchTerm.toLowerCase();
      list = list.filter((s) => {
        return (
          (s.patient_name ?? "").toLowerCase().includes(t) ||
          String(s.patient_id).includes(t) ||
          (s.suspect_icd10 ?? "").toLowerCase().includes(t) ||
          (s.suspected_condition ?? "").toLowerCase().includes(t) ||
          String(s.suspect_hcc ?? "").includes(t) ||
          rationaleText(s).toLowerCase().includes(t)
        );
      });
    }

    if (confidenceBand !== "all") {
      list = list.filter((s) => matchesBand(s.confidence_score ?? 0, confidenceBand));
    }

    list = [...list].sort((a, b) => {
      if (sortField === "confidence") return (b.confidence_score ?? 0) - (a.confidence_score ?? 0);
      if (sortField === "raf") return getCoefficient(b) - getCoefficient(a);
      return (a.patient_name ?? "").localeCompare(b.patient_name ?? "");
    });

    return list;
  }, [allSuspects, statusFilter, evidenceFilter, searchTerm, confidenceBand, sortField]);

  const totalPages = Math.max(1, Math.ceil(filteredSorted.length / PAGE_SIZE));
  const pagedSuspects = filteredSorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const hasActiveFilters =
    statusFilter !== "open" ||
    evidenceFilter !== "all" ||
    confidenceBand !== "all" ||
    searchTerm.trim() !== "";

  const clearAllFilters = () => {
    setStatusFilter("open");
    setEvidenceFilter("all");
    setConfidenceBand("all");
    setSearchTerm("");
    setPage(0);
  };

  /* --- Hero stats -------------------------------------------------- */

  const heroStats = useMemo(() => {
    const openSet = allSuspects.filter((s) => (s.status || "open") === "open");
    const totalUplift = openSet.reduce((sum, s) => sum + getCoefficient(s), 0);
    const totalRevenue = totalUplift * REVENUE_PER_RAF;
    const avgConf =
      openSet.length > 0
        ? openSet.reduce((sum, s) => sum + (s.confidence_score ?? 0), 0) / openSet.length
        : 0;
    return {
      openCount: openSet.length,
      totalUplift,
      totalRevenue,
      avgConf,
    };
  }, [allSuspects]);

  /* --- Mutations --------------------------------------------------- */

  const acceptMut = useMutation({
    mutationFn: (id: number) => acceptSuspect(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["suspects"] });
      toast.success("Accepted via EMR", "Suspect condition accepted & written to OpenEMR.");
    },
    onError: () => toast.error("Error", "Failed to accept suspect."),
  });

  const dismissMut = useMutation({
    mutationFn: (id: number) => dismissSuspect(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["suspects"] });
      toast.success("Dismissed", "Suspect condition dismissed.");
    },
    onError: () => toast.error("Error", "Failed to dismiss suspect."),
  });

  const bulkMut = useMutation({
    mutationFn: ({ action }: { action: "accept" | "dismiss" }) =>
      bulkUpdateSuspects(Array.from(selected), action),
    onSuccess: (data, vars) => {
      queryClient.invalidateQueries({ queryKey: ["suspects"] });
      setSelected(new Set());
      setBulkAction(null);
      toast.success(
        "Bulk Update",
        `${data.succeeded} suspects ${vars.action === "accept" ? "accepted & written to OpenEMR" : "dismissed"}.`
      );
    },
    onError: () => {
      setBulkAction(null);
      toast.error("Error", "Bulk update failed.");
    },
  });

  /* --- Selection --------------------------------------------------- */

  const selectableIds = useMemo(
    () => pagedSuspects.filter((s) => (s.status || "open") === "open").map((s) => s.id),
    [pagedSuspects]
  );

  const allSelected = selectableIds.length > 0 && selectableIds.every((id) => selected.has(id));

  const toggleSelect = useCallback((id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const toggleAll = useCallback(() => {
    if (allSelected) {
      setSelected((prev) => {
        const next = new Set(prev);
        selectableIds.forEach((id) => next.delete(id));
        return next;
      });
    } else {
      setSelected((prev) => new Set([...prev, ...selectableIds]));
    }
  }, [allSelected, selectableIds]);

  const handleStatusChange = useCallback((tab: StatusTab) => {
    setStatusFilter(tab);
    setSelected(new Set());
    setPage(0);
  }, []);

  /* --- Expand toggles ---------------------------------------------- */

  const toggleExpand = useCallback((id: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const toggleRationale = useCallback((id: number) => {
    setExpandedRationale((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  /* --- CSV Export -------------------------------------------------- */

  function exportSuspectsCSV() {
    if (!filteredSorted.length) return;
    const data = filteredSorted.map((s) => ({
      "Patient ID": s.patient_id,
      "Patient Name": s.patient_name ?? `Patient ${s.patient_id}`,
      "Measurement Year": s.measurement_year ?? measurementYear,
      "Condition": s.suspected_condition ?? "",
      "ICD-10": s.suspect_icd10 ?? "",
      "HCC": s.suspect_hcc ?? "",
      "RAF Coefficient": getCoefficient(s).toFixed(3),
      "Est. Revenue": Math.round(getCoefficient(s) * REVENUE_PER_RAF),
      "Confidence": `${((s.confidence_score ?? 0) * 100).toFixed(0)}%`,
      "Status": s.status ?? "",
      "Evidence Type": s.evidence_type ?? "",
      "Rationale": rationaleText(s),
    }));
    downloadCSV(data, "suspects");
  }

  /* ============================================================== */
  /*  Render                                                         */
  /* ============================================================== */

  return (
    <div
      style={{
        background: C.bgPage,
        minHeight: "100vh",
        padding: "32px 40px 48px",
        fontFamily: FONT_SYS,
        color: C.text,
      }}
    >
      <style>{`
        @keyframes pulseSk { 0%, 100% { opacity: 1; } 50% { opacity: 0.55; } }
        @keyframes rowEnter { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes drawerFadeIn { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: translateY(0); } }

        .suspect-row {
          animation: rowEnter 0.32s cubic-bezier(0.16, 1, 0.3, 1) both;
          transition: background-color 0.15s ease;
        }
        .suspect-row:hover { background-color: ${C.bgBand} !important; }
        .suspect-row:focus-visible {
          outline: 2px solid ${C.brand};
          outline-offset: -2px;
        }

        .row-action-btn {
          opacity: 0;
          transform: translateY(2px);
          transition: opacity 0.15s ease, transform 0.15s ease, background-color 0.15s ease, color 0.15s ease;
        }
        .suspect-row:hover .row-action-btn,
        .suspect-row:focus-within .row-action-btn { opacity: 1; transform: translateY(0); }

        /* Semantic table resets */
        .suspects-table { width: 100%; border-collapse: collapse; border-spacing: 0; table-layout: auto; }
        .suspects-table th, .suspects-table td { vertical-align: middle; }

        /* Responsive: hide columns below 1024px */
        @media (max-width: 1024px) {
          .suspects-hide-1024 { display: none !important; }
        }

        /* Mobile card layout below 768px */
        @media (max-width: 768px) {
          .suspects-table thead { display: none !important; }
          .suspects-table tbody tr.suspect-row {
            display: flex !important;
            flex-wrap: wrap;
            padding: 14px 16px !important;
            gap: 8px;
            border-bottom: 1px solid ${C.rowDivider} !important;
          }
          .suspects-table tbody tr.suspect-row td {
            display: block !important;
            padding: 0 !important;
            border: none !important;
            text-align: left !important;
          }
          .suspects-table tbody tr.suspect-row td.suspects-cell-patient { width: 100%; order: 1; }
          .suspects-table tbody tr.suspect-row td.suspects-cell-condition { width: 100%; order: 2; margin-top: 4px; }
          .suspects-table tbody tr.suspect-row td.suspects-cell-evidence { order: 3; }
          .suspects-table tbody tr.suspect-row td.suspects-cell-confidence { order: 4; flex: 1; min-width: 120px; }
          .suspects-table tbody tr.suspect-row td.suspects-cell-raf { display: none !important; }
          .suspects-table tbody tr.suspect-row td.suspects-cell-revenue { order: 6; }
          .suspects-table tbody tr.suspect-row td.suspects-cell-status { order: 7; }
          .suspects-table tbody tr.suspect-row td.suspects-cell-actions { order: 8; margin-left: auto; }
          .suspects-table tbody tr.suspect-drawer-row td { display: block !important; padding: 0 !important; }
          .row-action-btn { opacity: 1 !important; transform: none !important; }
        }

        @media (min-width: 769px) and (max-width: 900px) {
          .row-action-btn { opacity: 1; transform: none; }
        }
        @media (max-width: 900px) {
          .row-action-btn { opacity: 1; transform: none; }
        }
      `}</style>

      {/* Error Banner */}
      {isError && (
        <div
          role="alert"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 12,
            background: C.highSoft,
            border: "1px solid #FCA5A5",
            borderRadius: 12,
            padding: "12px 16px",
            marginBottom: 20,
            fontSize: 13,
            color: C.high,
            fontWeight: 600,
          }}
        >
          <AlertCircle size={18} />
          Failed to load suspects. Please check the server connection and refresh.
        </div>
      )}

      {/* ============================================================ */}
      {/* Page header                                                  */}
      {/* ============================================================ */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 24,
          marginBottom: 24,
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 16, minWidth: 0 }}>
          <div
            style={{
              width: 48,
              height: 48,
              borderRadius: 14,
              background: `linear-gradient(135deg, ${C.brand} 0%, ${C.brandDark} 100%)`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              boxShadow:
                "0 6px 16px rgba(15, 118, 110, 0.25), inset 0 1px 0 rgba(255,255,255,0.18)",
              flexShrink: 0,
            }}
          >
            <Sparkles size={22} color="#FFFFFF" strokeWidth={2.25} />
          </div>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <h1
                style={{
                  margin: 0,
                  fontSize: 24,
                  fontWeight: 700,
                  color: C.text,
                  letterSpacing: "-0.02em",
                  lineHeight: 1.15,
                }}
              >
                Suspect Conditions
              </h1>
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  height: 26,
                  padding: "0 4px 0 10px",
                  borderRadius: 8,
                  backgroundColor: C.brandSoft,
                  border: `1px solid ${C.brandRing}`,
                  color: C.brand,
                  fontSize: 11,
                  fontWeight: 600,
                  letterSpacing: "0.02em",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                <span>MY</span>
                <select
                  value={measurementYear}
                  onChange={(e) => setMeasurementYear(Number(e.target.value))}
                  aria-label="Measurement year"
                  style={{
                    appearance: "none",
                    WebkitAppearance: "none",
                    MozAppearance: "none",
                    background: "transparent",
                    border: "none",
                    color: C.brand,
                    fontSize: 12,
                    fontWeight: 700,
                    fontFamily: FONT_SYS,
                    fontVariantNumeric: "tabular-nums",
                    letterSpacing: "0.01em",
                    cursor: "pointer",
                    padding: "0 18px 0 2px",
                    outline: "none",
                    backgroundImage:
                      "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 20 20' fill='%230F766E'><path d='M5 8l5 5 5-5H5z'/></svg>\")",
                    backgroundRepeat: "no-repeat",
                    backgroundPosition: "right 2px center",
                  }}
                >
                  {[2024, 2025, 2026].map((y) => (
                    <option key={y} value={y}>{y}</option>
                  ))}
                </select>
              </div>
            </div>
            <p
              style={{
                margin: "4px 0 0",
                fontSize: 13,
                color: C.textSubtle,
                fontVariantNumeric: "tabular-nums",
              }}
            >
              {isLoading
                ? "Loading review queue\u2026"
                : `${heroStats.openCount.toLocaleString()} open suspects \u00B7 ${formatCurrency(heroStats.totalRevenue)} estimated RAF opportunity \u00B7 CMS-HCC V28`}
            </p>
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 10, flexShrink: 0 }}>
          <div style={{ position: "relative" }}>
            <Search
              size={16}
              style={{
                position: "absolute",
                left: 14,
                top: "50%",
                transform: "translateY(-50%)",
                color: C.label,
                pointerEvents: "none",
              }}
            />
            <input
              type="text"
              title="Search by patient, ICD, HCC, or rationale"
              placeholder="Search suspects\u2026"
              value={searchTerm}
              onChange={(e) => { setSearchTerm(e.target.value); setPage(0); }}
              aria-label="Search suspects"
              style={{
                height: 40,
                width: 320,
                maxWidth: "calc(100vw - 200px)",
                borderRadius: 10,
                border: `1px solid ${C.border}`,
                backgroundColor: "#FFFFFF",
                paddingLeft: 38,
                paddingRight: 14,
                fontSize: 13,
                color: C.text,
                fontFamily: FONT_SYS,
                outline: "none",
                transition: "border-color 0.15s, box-shadow 0.15s",
              }}
              onFocus={(e) => {
                e.currentTarget.style.borderColor = C.brand;
                e.currentTarget.style.boxShadow = `0 0 0 3px ${C.brandSoft}`;
              }}
              onBlur={(e) => {
                e.currentTarget.style.borderColor = C.border;
                e.currentTarget.style.boxShadow = "none";
              }}
            />
          </div>
          <button
            onClick={exportSuspectsCSV}
            aria-label="Export suspects as CSV"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 7,
              height: 40,
              padding: "0 16px",
              borderRadius: 10,
              border: "none",
              backgroundColor: C.brand,
              color: "#FFFFFF",
              fontSize: 13,
              fontWeight: 600,
              fontFamily: FONT_SYS,
              cursor: "pointer",
              flexShrink: 0,
              boxShadow:
                "0 1px 2px rgba(15, 118, 110, 0.25), 0 4px 12px rgba(15, 118, 110, 0.18)",
              transition: "background-color 0.15s ease",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = "#0d6b63"; }}
            onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = C.brand; }}
          >
            <FileDown size={14} />
            Export
          </button>
        </div>
      </div>

      {/* ============================================================ */}
      {/* Hero summary strip                                           */}
      {/* ============================================================ */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: 12,
          marginBottom: 16,
        }}
      >
        {[
          {
            label: "Open Suspects",
            value: isLoading ? "\u2014" : heroStats.openCount.toLocaleString(),
            sub: `In MY ${measurementYear}`,
            icon: ClipboardList,
            tone: C.blue,
          },
          {
            label: "Est. RAF Uplift",
            value: isLoading ? "\u2014" : `+${heroStats.totalUplift.toFixed(2)}`,
            sub: "Sum of coefficients",
            icon: TrendingUp,
            tone: C.brand,
          },
          {
            label: "Est. Annual Revenue",
            value: isLoading ? "\u2014" : formatCurrency(heroStats.totalRevenue),
            sub: `at $${REVENUE_PER_RAF.toLocaleString()}/RAF point`,
            icon: DollarSign,
            tone: C.low,
          },
          {
            label: "Avg Confidence",
            value: isLoading ? "\u2014" : `${(heroStats.avgConf * 100).toFixed(0)}%`,
            sub: "Across open suspects",
            icon: Activity,
            tone: C.medium,
          },
        ].map(({ label, value, sub, icon: Icon, tone }) => (
          <div
            key={label}
            style={{
              backgroundColor: C.bgCard,
              border: `1px solid ${C.borderSoft}`,
              borderRadius: 12,
              padding: "14px 16px",
              display: "flex",
              alignItems: "center",
              gap: 14,
              boxShadow: "0 1px 2px rgba(15, 23, 42, 0.03)",
            }}
          >
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: 10,
                backgroundColor: `${tone}14`,
                color: tone,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              <Icon size={17} strokeWidth={2.25} />
            </div>
            <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 2 }}>
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                  color: C.label,
                }}
              >
                {label}
              </span>
              <span
                style={{
                  fontSize: 22,
                  fontWeight: 700,
                  color: C.text,
                  lineHeight: 1.1,
                  letterSpacing: "-0.02em",
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {value}
              </span>
              <span
                style={{
                  fontSize: 11,
                  color: C.textSubtle,
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {sub}
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* ============================================================ */}
      {/* Filter strip                                                 */}
      {/* ============================================================ */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 12,
          marginBottom: 14,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          {/* Status segmented chips */}
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              backgroundColor: "#FFFFFF",
              border: `1px solid ${C.border}`,
              borderRadius: 10,
              padding: 3,
              gap: 2,
              height: 36,
            }}
          >
            {STATUS_TABS.map(({ value, label, dot }) => {
              const active = statusFilter === value;
              const count = statusCounts[value];
              return (
                <button
                  key={value}
                  onClick={() => handleStatusChange(value)}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    height: 28,
                    padding: "0 12px",
                    borderRadius: 7,
                    border: "none",
                    backgroundColor: active ? C.text : "transparent",
                    color: active ? "#FFFFFF" : C.textMuted,
                    fontSize: 12,
                    fontWeight: 600,
                    fontFamily: FONT_SYS,
                    cursor: "pointer",
                    transition: "all 0.15s ease",
                  }}
                >
                  {dot && (
                    <span
                      style={{
                        width: 6,
                        height: 6,
                        borderRadius: 3,
                        backgroundColor: dot,
                        boxShadow: active ? "0 0 0 1.5px rgba(255,255,255,0.25)" : "none",
                      }}
                    />
                  )}
                  {label}
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      color: active ? "rgba(255,255,255,0.7)" : C.label,
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    {count}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Evidence type chips */}
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              backgroundColor: "#FFFFFF",
              border: `1px solid ${C.border}`,
              borderRadius: 10,
              padding: 3,
              gap: 2,
              height: 36,
            }}
          >
            {EVIDENCE_FILTERS.map(({ value, label }) => {
              const active = evidenceFilter === value;
              return (
                <button
                  key={value}
                  onClick={() => { setEvidenceFilter(value); setPage(0); }}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 5,
                    height: 28,
                    padding: "0 10px",
                    borderRadius: 7,
                    border: "none",
                    backgroundColor: active ? C.brandSoft : "transparent",
                    color: active ? C.brand : C.textMuted,
                    fontSize: 12,
                    fontWeight: 600,
                    fontFamily: FONT_SYS,
                    cursor: "pointer",
                    transition: "all 0.15s ease",
                  }}
                >
                  {value !== "all" && evidenceIcon(value, 11)}
                  {label}
                </button>
              );
            })}
          </div>

          {/* Confidence chips */}
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              backgroundColor: "#FFFFFF",
              border: `1px solid ${C.border}`,
              borderRadius: 10,
              padding: 3,
              gap: 2,
              height: 36,
            }}
          >
            {CONFIDENCE_OPTIONS.map(({ value, label, color }) => {
              const active = confidenceBand === value;
              return (
                <button
                  key={value}
                  onClick={() => { setConfidenceBand(value); setPage(0); }}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    height: 28,
                    padding: "0 10px",
                    borderRadius: 7,
                    border: "none",
                    backgroundColor: active ? `${color}14` : "transparent",
                    color: active ? color : C.textMuted,
                    fontSize: 12,
                    fontWeight: 600,
                    fontFamily: FONT_SYS,
                    cursor: "pointer",
                    transition: "all 0.15s ease",
                  }}
                >
                  {value !== "all" && (
                    <span
                      style={{
                        width: 6,
                        height: 6,
                        borderRadius: 3,
                        backgroundColor: color,
                      }}
                    />
                  )}
                  {label}
                </button>
              );
            })}
          </div>

          {/* Sort */}
          <button
            onClick={() =>
              setSortField((f) =>
                f === "confidence" ? "raf" : f === "raf" ? "patient" : "confidence"
              )
            }
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              height: 36,
              padding: "0 14px",
              borderRadius: 10,
              border: `1px solid ${C.border}`,
              backgroundColor: "#FFFFFF",
              color: C.textMuted,
              fontSize: 12,
              fontWeight: 600,
              fontFamily: FONT_SYS,
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
          >
            Sort: {sortField === "confidence" ? "Confidence" : sortField === "raf" ? "RAF lift" : "Patient"}
          </button>

          {hasActiveFilters && (
            <button
              onClick={clearAllFilters}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                height: 36,
                padding: "0 14px",
                borderRadius: 999,
                border: `1px dashed ${C.border}`,
                backgroundColor: "transparent",
                color: C.textSubtle,
                fontSize: 12,
                fontWeight: 600,
                fontFamily: FONT_SYS,
                cursor: "pointer",
              }}
            >
              <X size={12} />
              Clear filters
            </button>
          )}
        </div>

        <div
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: C.textSubtle,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          Showing {filteredSorted.length.toLocaleString()} of {allSuspects.length.toLocaleString()}
        </div>
      </div>

      {/* ============================================================ */}
      {/* Worklist -- Semantic Table with overflow-x-auto wrapper       */}
      {/* ============================================================ */}
      <div
        style={{
          backgroundColor: C.bgCard,
          border: `1px solid ${C.border}`,
          borderRadius: 14,
          overflow: "hidden",
          boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)",
          overflowX: "auto",
          WebkitOverflowScrolling: "touch",
        }}
      >
        <table className="suspects-table" role="grid" aria-label="Suspect conditions worklist">
          <thead>
            <tr style={{ backgroundColor: C.bgBand }}>
              <th scope="col" style={{ ...TH_STYLE, padding: "12px 22px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                  {selectableIds.length > 0 && (
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={toggleAll}
                      aria-label="Select all on page"
                      style={{ width: 14, height: 14, accentColor: C.brand, cursor: "pointer" }}
                    />
                  )}
                  Patient
                </div>
              </th>
              <th scope="col" style={TH_STYLE}>Suspected Condition</th>
              <th scope="col" className="suspects-hide-1024" style={TH_STYLE}>Evidence</th>
              <th scope="col" style={TH_STYLE}>Confidence</th>
              <th scope="col" className="suspects-hide-1024" style={{ ...TH_STYLE, textAlign: "right" }}>RAF Lift</th>
              <th scope="col" style={{ ...TH_STYLE, textAlign: "right" }}>Revenue</th>
              <th scope="col" style={{ ...TH_STYLE, textAlign: "right" }}>Status</th>
              <th scope="col" style={{ ...TH_STYLE, textAlign: "right", padding: "12px 22px" }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && Array.from({ length: 8 }).map((_, i) => <SkeletonRow key={i} index={i} />)}

            {!isLoading && filteredSorted.length === 0 && (
              <tr>
                <td colSpan={8}>
                  <div
                    style={{
                      padding: "56px 24px",
                      display: "flex",
                      flexDirection: "column",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: 12,
                      textAlign: "center",
                    }}
                  >
                    <div
                      style={{
                        width: 56,
                        height: 56,
                        borderRadius: 16,
                        backgroundColor: C.brandSoft,
                        color: C.brand,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                    >
                      <FileSearch size={26} />
                    </div>
                    <div style={{ fontSize: 15, fontWeight: 700, color: C.text }}>
                      No suspects match your filters
                    </div>
                    <div style={{ fontSize: 13, color: C.textSubtle, maxWidth: 360 }}>
                      Try widening your status, evidence, or confidence filters to see more results.
                    </div>
                    {hasActiveFilters && (
                      <button
                        onClick={clearAllFilters}
                        style={{
                          marginTop: 4,
                          height: 36,
                          padding: "0 18px",
                          borderRadius: 10,
                          border: `1px solid ${C.brand}`,
                          backgroundColor: C.brandSoft,
                          color: C.brand,
                          fontSize: 13,
                          fontWeight: 600,
                          cursor: "pointer",
                        }}
                      >
                        Clear filters
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            )}

            {!isLoading && pagedSuspects.map((s, idx) => {
              const conf = s.confidence_score ?? 0;
              const cConf = confColor(conf);
              const accent = confAccent(conf);
              const isOpen = (s.status || "open") === "open";
              const isSelected = selected.has(s.id);
              const pill = statusPill(s.status);
              const coef = getCoefficient(s);
              const revenue = coef * REVENUE_PER_RAF;
              const initials = deriveInitials(s.patient_name, undefined, s.patient_id);
              const seed = (s.patient_name || String(s.patient_id) || "x").trim();
              const aColor = initialsColor(seed);
              const conditionLabel =
                s.suspected_condition ||
                (s.suspect_hcc ? `HCC ${s.suspect_hcc}` : "Suspected Condition");
              const rationale = rationaleText(s);

              const isExpanded = expandedIds.has(s.id);
              const isRationaleExpanded = expandedRationale.has(s.id);
              const rationaleIsLong = rationale.length > 80;

              return (
                <React.Fragment key={s.id}>
                  <tr
                    tabIndex={0}
                    className="suspect-row"
                    aria-expanded={isExpanded}
                    onClick={() => toggleExpand(s.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        toggleExpand(s.id);
                      }
                    }}
                    onMouseEnter={() => setHoveredId(s.id)}
                    onMouseLeave={() => setHoveredId(null)}
                    style={{
                      borderBottom: idx < pagedSuspects.length - 1 && !isExpanded ? `1px solid ${C.rowDivider}` : "none",
                      backgroundColor: isExpanded ? C.bgBand : isSelected ? C.brandSoft : C.bgCard,
                      borderLeft: `3px solid ${accent}`,
                      cursor: "pointer",
                      animationDelay: `${idx * 25}ms`,
                    }}
                  >
                    {/* Patient */}
                    <td className="suspects-cell-patient" style={{ padding: "14px 22px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 12, minWidth: 0 }}>
                        {isOpen ? (
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => toggleSelect(s.id)}
                            onClick={(e) => e.stopPropagation()}
                            aria-label={`Select suspect ${s.id}`}
                            style={{ width: 14, height: 14, accentColor: C.brand, cursor: "pointer", flexShrink: 0 }}
                          />
                        ) : (
                          <div style={{ width: 14, flexShrink: 0 }} />
                        )}
                        <div
                          aria-hidden
                          style={{
                            width: 36, height: 36, borderRadius: 10,
                            background: `linear-gradient(135deg, ${aColor}, ${aColor}CC)`,
                            color: "#FFFFFF", display: "flex", alignItems: "center", justifyContent: "center",
                            fontSize: 12, fontWeight: 700, letterSpacing: "0.02em", flexShrink: 0,
                            boxShadow: "inset 0 1px 0 rgba(255,255,255,0.18)",
                          }}
                        >
                          {initials}
                        </div>
                        <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 2 }}>
                          <div style={{ fontSize: 14, fontWeight: 600, color: C.text, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", letterSpacing: "-0.005em" }}>
                            {s.patient_name ?? `Patient ${s.patient_id}`}
                          </div>
                          <div style={{ fontSize: 11, color: C.label, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                            PID {s.patient_id} &middot; MY {s.measurement_year ?? measurementYear}
                          </div>
                        </div>
                      </div>
                    </td>

                    {/* Condition + expandable rationale */}
                    <td className="suspects-cell-condition" style={{ padding: "14px 8px" }}>
                      <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 4 }}>
                        <div style={{ fontSize: 14, fontWeight: 600, color: C.text, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", letterSpacing: "-0.005em" }} title={conditionLabel}>
                          {conditionLabel}
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 11, color: C.textSubtle, fontFamily: FONT_MONO, letterSpacing: "0.01em" }}>
                          {s.suspect_hcc != null && <span>HCC {s.suspect_hcc}</span>}
                          {s.suspect_hcc != null && s.suspect_icd10 && <span style={{ color: C.label }}>&middot;</span>}
                          {s.suspect_icd10 && <span>ICD {s.suspect_icd10}</span>}
                        </div>
                        {/* Expandable evidence/rationale text */}
                        <div>
                          <div
                            style={{
                              fontSize: 12,
                              color: C.textSubtle,
                              fontStyle: "italic",
                              fontFamily: FONT_SYS,
                              overflow: isRationaleExpanded ? "visible" : "hidden",
                              display: isRationaleExpanded ? "block" : "-webkit-box",
                              WebkitLineClamp: isRationaleExpanded ? undefined : 1,
                              WebkitBoxOrient: isRationaleExpanded ? undefined : ("vertical" as const),
                              textOverflow: isRationaleExpanded ? undefined : "ellipsis",
                              whiteSpace: isRationaleExpanded ? "pre-wrap" : undefined,
                              wordBreak: "break-word",
                            }}
                          >
                            &ldquo;{rationale}&rdquo;
                          </div>
                          {rationaleIsLong && (
                            <button
                              onClick={(e) => { e.stopPropagation(); toggleRationale(s.id); }}
                              aria-label={isRationaleExpanded ? "Show less evidence text" : "Show more evidence text"}
                              style={{
                                background: "none", border: "none", padding: "2px 0",
                                fontSize: 11, fontWeight: 600, color: C.brand, cursor: "pointer",
                                fontFamily: FONT_SYS, display: "inline-flex", alignItems: "center", gap: 3,
                              }}
                            >
                              {isRationaleExpanded
                                ? <>Show less <ChevronUp size={10} /></>
                                : <>Show more <ChevronDown size={10} /></>}
                            </button>
                          )}
                        </div>
                      </div>
                    </td>

                    {/* Evidence pill */}
                    <td className="suspects-cell-evidence suspects-hide-1024" style={{ padding: "14px 8px" }}>
                      <span
                        style={{
                          display: "inline-flex", alignItems: "center", gap: 6, height: 22, padding: "0 10px",
                          borderRadius: 999, backgroundColor: C.bgBand, border: `1px solid ${C.border}`,
                          color: C.textMuted, fontSize: 11, fontWeight: 600, textTransform: "capitalize", whiteSpace: "nowrap",
                        }}
                      >
                        {evidenceIcon(s.evidence_type, 11)}
                        {evidenceLabelShort(s.evidence_type)}
                      </span>
                    </td>

                    {/* Confidence */}
                    <td className="suspects-cell-confidence" style={{ padding: "14px 8px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
                        <div style={{ flex: 1, height: 6, borderRadius: 4, backgroundColor: confSoftBg(conf), overflow: "hidden", minWidth: 40 }}>
                          <div style={{ height: "100%", width: `${Math.max(4, conf * 100)}%`, borderRadius: 4, backgroundColor: cConf, transition: "width 0.3s ease" }} />
                        </div>
                        <span style={{ fontSize: 12, fontWeight: 700, color: cConf, fontVariantNumeric: "tabular-nums", minWidth: 32, textAlign: "right" }}>
                          {(conf * 100).toFixed(0)}%
                        </span>
                      </div>
                    </td>

                    {/* RAF lift */}
                    <td className="suspects-cell-raf suspects-hide-1024" style={{ padding: "14px 8px", textAlign: "right" }}>
                      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 1 }}>
                        <span style={{ fontSize: 14, fontWeight: 700, color: C.brand, fontVariantNumeric: "tabular-nums", letterSpacing: "-0.01em" }}>
                          +{coef.toFixed(3)}
                        </span>
                        <span style={{ fontSize: 10, fontWeight: 600, color: C.label, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                          RAF
                        </span>
                      </div>
                    </td>

                    {/* Revenue */}
                    <td className="suspects-cell-revenue" style={{ padding: "14px 8px", textAlign: "right" }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: C.text, fontVariantNumeric: "tabular-nums" }}>
                        {formatCurrency(revenue)}
                      </span>
                    </td>

                    {/* Status */}
                    <td className="suspects-cell-status" style={{ padding: "14px 8px", textAlign: "right" }}>
                      <span
                        style={{
                          display: "inline-flex", alignItems: "center", gap: 6, height: 22, padding: "0 10px",
                          borderRadius: 999, backgroundColor: pill.bg, color: pill.fg, border: `1px solid ${pill.border}`,
                          fontSize: 11, fontWeight: 700, letterSpacing: "0.02em",
                          textDecoration: s.status === "dismissed" ? "line-through" : "none", whiteSpace: "nowrap",
                        }}
                      >
                        <span style={{ width: 6, height: 6, borderRadius: 3, backgroundColor: pill.fg }} />
                        {pill.label}
                      </span>
                    </td>

                    {/* Actions */}
                    <td className="suspects-cell-actions" style={{ padding: "14px 22px", textAlign: "right" }}>
                      <div
                        style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 6 }}
                        onClick={(e) => e.stopPropagation()}
                      >
                        {isOpen ? (
                          <>
                            <button
                              className="row-action-btn"
                              disabled={acceptMut.isPending}
                              onClick={() => acceptMut.mutate(s.id)}
                              aria-label="Push to EMR"
                              title="Push to EMR"
                              style={{
                                width: 32, height: 32, borderRadius: 8, border: `1px solid ${C.low}`,
                                backgroundColor: "transparent", color: C.low, cursor: "pointer",
                                display: "flex", alignItems: "center", justifyContent: "center",
                              }}
                              onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = C.lowSoft; }}
                              onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = "transparent"; }}
                            >
                              <Check size={15} strokeWidth={2.5} />
                            </button>
                            <button
                              className="row-action-btn"
                              disabled={dismissMut.isPending}
                              onClick={() => dismissMut.mutate(s.id)}
                              aria-label="Dismiss suspect"
                              title="Dismiss"
                              style={{
                                width: 32, height: 32, borderRadius: 8, border: `1px solid ${C.high}`,
                                backgroundColor: "transparent", color: C.high, cursor: "pointer",
                                display: "flex", alignItems: "center", justifyContent: "center",
                              }}
                              onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = C.highSoft; }}
                              onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = "transparent"; }}
                            >
                              <X size={15} strokeWidth={2.5} />
                            </button>
                          </>
                        ) : (
                          <span style={{ fontSize: 11, color: C.label, display: "inline-flex", alignItems: "center", gap: 4 }}>
                            {s.status === "accepted" && <CheckCircle2 size={13} color={C.low} />}
                            {s.status === "dismissed" && <XCircle size={13} color={C.textSubtle} />}
                            {s.status === "coded" && <CheckCircle2 size={13} color={C.brand} />}
                          </span>
                        )}
                        <ChevronRight
                          size={14}
                          color={isExpanded || hoveredId === s.id ? C.brand : "#CBD5E1"}
                          style={{ transform: isExpanded ? "rotate(90deg)" : "rotate(0deg)", transition: "transform 0.18s ease" }}
                        />
                      </div>
                    </td>
                  </tr>

                  {/* Expanded detail drawer */}
                  {isExpanded && (
                    <tr className="suspect-drawer-row" style={{ borderBottom: `1px solid ${C.rowDivider}` }}>
                      <td colSpan={8} style={{ padding: 0 }}>
                        <SuspectDrawer
                          suspect={s}
                          conf={conf}
                          coef={coef}
                          revenue={revenue}
                          rationale={rationale}
                          conditionLabel={conditionLabel}
                          onOpenChart={() => router.push(`/patients/${s.patient_id}`)}
                          onAccept={() => acceptMut.mutate(s.id)}
                          onDismiss={() => dismissMut.mutate(s.id)}
                          acceptPending={acceptMut.isPending}
                          dismissPending={dismissMut.isPending}
                        />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* ============================================================ */}
      {/* Pagination                                                   */}
      {/* ============================================================ */}
      {!isLoading && filteredSorted.length > PAGE_SIZE && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 16, marginTop: 20 }}>
          <button
            disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}
            aria-label="Previous page"
            style={{
              width: 36, height: 36, borderRadius: 10, border: `1px solid ${C.border}`,
              backgroundColor: "#FFFFFF", cursor: page === 0 ? "default" : "pointer",
              opacity: page === 0 ? 0.4 : 1, display: "flex", alignItems: "center", justifyContent: "center", color: C.textMuted,
            }}
          >
            <ChevronLeft size={16} />
          </button>
          <span style={{ fontSize: 13, fontWeight: 600, color: C.textMuted, fontVariantNumeric: "tabular-nums" }}>
            Page {page + 1} of {totalPages}
          </span>
          <button
            disabled={page >= totalPages - 1}
            onClick={() => setPage((p) => p + 1)}
            aria-label="Next page"
            style={{
              width: 36, height: 36, borderRadius: 10, border: `1px solid ${C.border}`,
              backgroundColor: "#FFFFFF", cursor: page >= totalPages - 1 ? "default" : "pointer",
              opacity: page >= totalPages - 1 ? 0.4 : 1, display: "flex", alignItems: "center", justifyContent: "center", color: C.textMuted,
            }}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}

      {/* ============================================================ */}
      {/* Bulk action bar                                              */}
      {/* ============================================================ */}
      {selected.size > 0 && (
        <div
          style={{
            position: "fixed", bottom: 20, left: "50%", transform: "translateX(-50%)",
            width: "min(720px, calc(100% - 32px))",
            backgroundColor: "rgba(15, 23, 42, 0.96)", backdropFilter: "blur(12px)", WebkitBackdropFilter: "blur(12px)",
            borderRadius: 14, boxShadow: "0 -4px 32px rgba(0, 0, 0, 0.2), 0 0 0 1px rgba(255, 255, 255, 0.06)",
            padding: "14px 20px", display: "flex", alignItems: "center", gap: 14, zIndex: 50,
          }}
        >
          <span style={{ fontSize: 13, fontWeight: 600, color: "#FFFFFF", display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ backgroundColor: C.brand, color: "#FFFFFF", fontSize: 12, fontWeight: 700, borderRadius: 999, padding: "2px 10px", minWidth: 24, textAlign: "center", fontVariantNumeric: "tabular-nums" }}>
              {selected.size}
            </span>
            selected
          </span>

          <div style={{ width: 1, height: 24, backgroundColor: "rgba(255,255,255,0.15)" }} />

          <button
            disabled={bulkMut.isPending}
            onClick={() => { setBulkAction("accept"); bulkMut.mutate({ action: "accept" }); }}
            style={{
              height: 36, padding: "0 18px", borderRadius: 10, border: "none",
              backgroundColor: C.low, color: "#FFFFFF", fontSize: 13, fontWeight: 700,
              cursor: bulkMut.isPending ? "not-allowed" : "pointer", opacity: bulkMut.isPending ? 0.6 : 1,
              display: "flex", alignItems: "center", gap: 6, boxShadow: "0 2px 8px rgba(5, 150, 105, 0.3)",
            }}
          >
            <Check size={14} strokeWidth={2.5} />
            {bulkMut.isPending && bulkAction === "accept" ? "Accepting\u2026" : "Accept all"}
          </button>

          <button
            disabled={bulkMut.isPending}
            onClick={() => { setBulkAction("dismiss"); bulkMut.mutate({ action: "dismiss" }); }}
            style={{
              height: 36, padding: "0 18px", borderRadius: 10, border: "1px solid rgba(255,255,255,0.2)",
              backgroundColor: "transparent", color: "#FFFFFF", fontSize: 13, fontWeight: 600,
              cursor: bulkMut.isPending ? "not-allowed" : "pointer", opacity: bulkMut.isPending ? 0.6 : 1,
              display: "flex", alignItems: "center", gap: 6,
            }}
          >
            <X size={14} strokeWidth={2.5} />
            {bulkMut.isPending && bulkAction === "dismiss" ? "Dismissing\u2026" : "Dismiss all"}
          </button>

          <button
            onClick={() => setSelected(new Set())}
            style={{
              marginLeft: "auto", height: 36, padding: "0 14px", borderRadius: 10,
              border: "none", backgroundColor: "transparent", color: "rgba(255,255,255,0.7)",
              fontSize: 13, fontWeight: 600, cursor: "pointer",
            }}
          >
            Clear
          </button>
        </div>
      )}

      {selected.size > 0 && <div style={{ height: 80 }} />}
    </div>
  );
}

/* ================================================================== */
/*  Default export with Suspense boundary for useSearchParams          */
/* ================================================================== */

export default function SuspectsPage() {
  return (
    <Suspense fallback={
      <div style={{ background: C.bgPage, minHeight: "100vh", padding: "32px 40px 48px", fontFamily: FONT_SYS }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 24 }}>
          <div style={{ width: 48, height: 48, borderRadius: 14, background: `linear-gradient(135deg, ${C.brand} 0%, ${C.brandDark} 100%)`, display: "flex", alignItems: "center", justifyContent: "center" }}>
            <Sparkles size={22} color="#FFFFFF" strokeWidth={2.25} />
          </div>
          <div>
            <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, color: C.text, letterSpacing: "-0.02em" }}>Suspect Conditions</h1>
            <p style={{ margin: "4px 0 0", fontSize: 13, color: C.textSubtle }}>Loading review queue&hellip;</p>
          </div>
        </div>
      </div>
    }>
      <SuspectsPageInner />
    </Suspense>
  );
}

/* ================================================================== */
/*  SuspectDrawer -- inline expanded row detail                        */
/* ================================================================== */

function SuspectDrawer({
  suspect, conf, coef, revenue, rationale, conditionLabel,
  onOpenChart, onAccept, onDismiss, acceptPending, dismissPending,
}: {
  suspect: DBSuspect; conf: number; coef: number; revenue: number;
  rationale: string; conditionLabel: string;
  onOpenChart: () => void; onAccept: () => void; onDismiss: () => void;
  acceptPending: boolean; dismissPending: boolean;
}) {
  const s = suspect;
  const isOpen = (s.status || "open") === "open";
  const cConf = confColor(conf);

  const evidenceLines: { label: string; value: string }[] = [];
  const detail = s.evidence_detail;
  try {
    const obj =
      typeof detail === "string" && detail.trim().startsWith("{")
        ? JSON.parse(detail)
        : detail && typeof detail === "object"
          ? detail
          : null;
    if (obj && typeof obj === "object") {
      for (const [k, v] of Object.entries(obj)) {
        if (v == null || v === "") continue;
        const label = k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
        const value = typeof v === "object" ? JSON.stringify(v) : String(v);
        evidenceLines.push({ label, value });
      }
    }
  } catch {
    // ignore
  }

  const fmtDate = (d?: string) => {
    if (!d) return "\u2014";
    try { return new Date(d).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }); }
    catch { return d; }
  };

  return (
    <div
      onClick={(e) => e.stopPropagation()}
      style={{
        padding: "18px 22px 22px 22px", backgroundColor: "#FCFDFE",
        borderTop: `1px solid ${C.borderSoft}`, borderLeft: `3px solid ${confAccent(conf)}`,
        display: "grid", gridTemplateColumns: "minmax(0, 1.4fr) minmax(0, 1fr)", gap: 24,
        animation: "drawerFadeIn 0.22s ease",
      }}
    >
      {/* LEFT */}
      <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 16 }}>
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, color: C.label, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>
            Why we flagged this
          </div>
          <div style={{ fontSize: 14, lineHeight: 1.55, color: C.text, fontStyle: "italic", padding: "12px 14px", borderRadius: 10, backgroundColor: C.white, border: `1px solid ${C.borderSoft}`, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            &ldquo;{rationale}&rdquo;
          </div>
        </div>

        {evidenceLines.length > 0 && (
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, color: C.label, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>
              Supporting evidence
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 8, padding: 12, borderRadius: 10, backgroundColor: C.white, border: `1px solid ${C.borderSoft}` }}>
              {evidenceLines.map((ln, i) => (
                <div key={i} style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 10, color: C.label, textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 600, marginBottom: 2 }}>
                    {ln.label}
                  </div>
                  <div style={{ fontSize: 12, color: C.text, fontFamily: FONT_MONO, wordBreak: "break-word" }}>
                    {ln.value}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        <div style={{ display: "flex", gap: 16, fontSize: 11, color: C.textSubtle }}>
          <span><span style={{ color: C.label }}>Detected </span>{fmtDate(s.created_at)}</span>
          {s.reviewed_at && (
            <span>
              <span style={{ color: C.label }}>Reviewed </span>{fmtDate(s.reviewed_at)}
              {s.reviewed_by && <span style={{ color: C.label }}> &middot; {s.reviewed_by}</span>}
            </span>
          )}
        </div>
      </div>

      {/* RIGHT */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ padding: 16, borderRadius: 12, backgroundColor: C.white, border: `1px solid ${C.border}` }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: C.label, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>
            Suspected Code
          </div>
          <div style={{ fontSize: 15, fontWeight: 700, color: C.text, marginBottom: 6, letterSpacing: "-0.01em" }}>
            {conditionLabel}
          </div>
          <div style={{ display: "flex", gap: 8, fontFamily: FONT_MONO, fontSize: 11, color: C.textMuted, marginBottom: 12 }}>
            {s.suspect_hcc != null && (
              <span style={{ padding: "2px 8px", borderRadius: 6, backgroundColor: C.brandSoft, color: C.brand, fontWeight: 700 }}>
                HCC {s.suspect_hcc}
              </span>
            )}
            {s.suspect_icd10 && (
              <span style={{ padding: "2px 8px", borderRadius: 6, backgroundColor: C.bgSubtle, border: `1px solid ${C.borderSoft}`, fontWeight: 700 }}>
                ICD {s.suspect_icd10}
              </span>
            )}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, paddingTop: 12, borderTop: `1px solid ${C.borderSoft}` }}>
            <div>
              <div style={{ fontSize: 9, color: C.label, textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 700 }}>Confidence</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: cConf, fontVariantNumeric: "tabular-nums" }}>{(conf * 100).toFixed(0)}%</div>
            </div>
            <div>
              <div style={{ fontSize: 9, color: C.label, textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 700 }}>RAF Lift</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: C.brand, fontVariantNumeric: "tabular-nums" }}>+{coef.toFixed(3)}</div>
            </div>
            <div>
              <div style={{ fontSize: 9, color: C.label, textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 700 }}>Revenue</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: C.text, fontVariantNumeric: "tabular-nums" }}>{formatCurrency(revenue)}</div>
            </div>
          </div>
        </div>

        {isOpen && (
          <div style={{ display: "flex", gap: 8 }}>
            <button
              onClick={onAccept} disabled={acceptPending}
              style={{
                flex: 1, height: 40, borderRadius: 10, border: "none", backgroundColor: C.low, color: "#FFFFFF",
                fontSize: 13, fontWeight: 700, cursor: acceptPending ? "default" : "pointer",
                opacity: acceptPending ? 0.6 : 1, display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6, letterSpacing: "0.01em",
              }}
            >
              <Check size={15} strokeWidth={2.5} />
              Push to EMR
            </button>
            <button
              onClick={onDismiss} disabled={dismissPending}
              style={{
                flex: 1, height: 40, borderRadius: 10, border: `1px solid ${C.high}`, backgroundColor: "#FFFFFF", color: C.high,
                fontSize: 13, fontWeight: 700, cursor: dismissPending ? "default" : "pointer",
                opacity: dismissPending ? 0.6 : 1, display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6, letterSpacing: "0.01em",
              }}
            >
              <X size={15} strokeWidth={2.5} />
              Dismiss
            </button>
          </div>
        )}

        <button
          onClick={onOpenChart}
          style={{
            height: 40, borderRadius: 10, border: `1px solid ${C.brand}`, backgroundColor: C.brandSoft, color: C.brand,
            fontSize: 13, fontWeight: 700, cursor: "pointer", display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8, letterSpacing: "0.01em",
          }}
        >
          <FileSearch size={15} strokeWidth={2.2} />
          Open Patient Chart
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );
}
