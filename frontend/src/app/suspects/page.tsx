"use client";

import React, { useState, useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getSuspects,
  acceptSuspect,
  dismissSuspect,
  bulkUpdateSuspects,
} from "@/lib/api";
import {
  StatCard,
  PageHeader,
  EmptyState,
  ConfidencePill,
} from "@/components/healthcare-ui";
import type { DBSuspect } from "@/types";
import { useToast } from "@/components/Toast";
import {
  ClipboardList,
  TrendingUp,
  Users,
  Activity,
  Search,
  FileSearch,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";

/* ------------------------------------------------------------------ */
/*  Constants                                                          */
/* ------------------------------------------------------------------ */

const TOKENS = {
  white: "#FFFFFF",
  slate50: "#F8FAFC",
  slate100: "#F1F5F9",
  slate200: "#E2E8F0",
  slate300: "#CBD5E1",
  slate400: "#94A3B8",
  slate500: "#64748B",
  slate600: "#475569",
  slate700: "#334155",
  slate800: "#1E293B",
  slate900: "#0F172A",
  blue50: "#EFF6FF",
  blue100: "#DBEAFE",
  blue500: "#3B82F6",
  blue600: "#2563EB",
  blue700: "#1D4ED8",
  emerald50: "#ECFDF5",
  emerald500: "#10B981",
  emerald600: "#059669",
  emerald700: "#047857",
  amber50: "#FFFBEB",
  amber500: "#F59E0B",
  amber600: "#D97706",
  red50: "#FEF2F2",
  red500: "#EF4444",
  red600: "#DC2626",
  gray100: "#F3F4F6",
  gray200: "#E5E7EB",
  gray400: "#9CA3AF",
  gray500: "#6B7280",
};

const PAGE_SIZE = 25;

type StatusTab = "open" | "accepted" | "dismissed" | "all";
type ConfidenceBand = "all" | "high" | "medium" | "low";
type SortField = "confidence" | "patient";

const STATUS_TABS: { value: StatusTab; label: string }[] = [
  { value: "open", label: "Open" },
  { value: "accepted", label: "Accepted" },
  { value: "dismissed", label: "Dismissed" },
  { value: "all", label: "All" },
];

const CONFIDENCE_OPTIONS: { value: ConfidenceBand; label: string }[] = [
  { value: "all", label: "All" },
  { value: "high", label: "High >85%" },
  { value: "medium", label: "Medium 60-85%" },
  { value: "low", label: "Low <60%" },
];

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function confBarColor(score: number): string {
  if (score >= 0.85) return TOKENS.emerald500;
  if (score >= 0.6) return TOKENS.amber500;
  return TOKENS.red500;
}

function matchesBand(score: number, band: ConfidenceBand): boolean {
  if (band === "all") return true;
  if (band === "high") return score >= 0.85;
  if (band === "medium") return score >= 0.6 && score < 0.85;
  return score < 0.6;
}

function evidenceText(s: DBSuspect): string {
  const parts: string[] = [];
  if (s.evidence_type) parts.push(s.evidence_type);
  if (s.trigger_value) parts.push(s.trigger_value);
  if (!parts.length && s.evidence_detail) {
    parts.push(
      typeof s.evidence_detail === "object"
        ? JSON.stringify(s.evidence_detail)
        : String(s.evidence_detail)
    );
  }
  return parts.join(" — ") || "No evidence recorded";
}

/* ------------------------------------------------------------------ */
/*  Skeleton Card                                                      */
/* ------------------------------------------------------------------ */

function SkeletonCard() {
  const bar: React.CSSProperties = {
    height: 14,
    borderRadius: 4,
    background: TOKENS.slate100,
    animation: "pulse 1.5s ease-in-out infinite",
  };
  return (
    <div
      style={{
        height: 80,
        background: TOKENS.white,
        border: `1px solid ${TOKENS.slate200}`,
        borderRadius: 10,
        display: "flex",
        alignItems: "center",
        gap: 16,
        padding: "0 20px",
      }}
    >
      <div style={{ ...bar, width: 16, height: 16, borderRadius: 3 }} />
      <div style={{ width: 4, height: 40, borderRadius: 2, background: TOKENS.slate100 }} />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ ...bar, width: "30%" }} />
        <div style={{ ...bar, width: "50%", height: 10 }} />
      </div>
      <div style={{ ...bar, width: 60 }} />
      <div style={{ ...bar, width: 60 }} />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Page Component                                                     */
/* ------------------------------------------------------------------ */

export default function SuspectsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const toast = useToast();

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [statusFilter, setStatusFilter] = useState<StatusTab>("open");
  const [searchTerm, setSearchTerm] = useState("");
  const [confidenceBand, setConfidenceBand] = useState<ConfidenceBand>("all");
  const [sortField, setSortField] = useState<SortField>("confidence");
  const [page, setPage] = useState(0);

  /* --- Data -------------------------------------------------------- */

  const { data: suspectsData, isLoading } = useQuery({
    queryKey: ["suspects", statusFilter],
    queryFn: () => getSuspects(statusFilter),
  });

  const allSuspects: DBSuspect[] = suspectsData?.suspects ?? [];

  const filteredSorted = useMemo(() => {
    let list = allSuspects;
    if (searchTerm.trim()) {
      const t = searchTerm.toLowerCase();
      list = list.filter(
        (s) =>
          (s.patient_name ?? "").toLowerCase().includes(t) ||
          String(s.patient_id).includes(t)
      );
    }
    if (confidenceBand !== "all") {
      list = list.filter((s) => matchesBand(s.confidence_score ?? 0, confidenceBand));
    }
    list = [...list].sort((a, b) => {
      if (sortField === "confidence")
        return (b.confidence_score ?? 0) - (a.confidence_score ?? 0);
      return (a.patient_name ?? "").localeCompare(b.patient_name ?? "");
    });
    return list;
  }, [allSuspects, searchTerm, confidenceBand, sortField]);

  const totalPages = Math.max(1, Math.ceil(filteredSorted.length / PAGE_SIZE));
  const pagedSuspects = filteredSorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  /* --- Stats ------------------------------------------------------- */

  const stats = useMemo(() => {
    const total = allSuspects.length;
    const highConf = allSuspects.filter((s) => (s.confidence_score ?? 0) >= 0.85).length;
    const uniquePatients = new Set(allSuspects.map((s) => s.patient_id)).size;
    const avgConf =
      total > 0
        ? allSuspects.reduce((sum, s) => sum + (s.confidence_score ?? 0), 0) / total
        : 0;
    return { total, highConf, uniquePatients, avgConf };
  }, [allSuspects]);

  /* --- Mutations --------------------------------------------------- */

  const acceptMut = useMutation({
    mutationFn: (id: number) => acceptSuspect(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["suspects"] });
      toast.success("Accepted", "Suspect condition accepted.");
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
      toast.success(
        "Bulk Update",
        `${data.succeeded} suspects ${vars.action === "accept" ? "accepted" : "dismissed"}.`
      );
    },
    onError: () => toast.error("Error", "Bulk update failed."),
  });

  /* --- Selection --------------------------------------------------- */

  const selectableIds = useMemo(
    () => pagedSuspects.filter((s) => s.status === "open").map((s) => s.id),
    [pagedSuspects]
  );

  const allSelected = selectableIds.length > 0 && selectableIds.every((id) => selected.has(id));

  const toggleSelect = useCallback((id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
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

  /* --- Styles ------------------------------------------------------ */

  const pillBase: React.CSSProperties = {
    padding: "6px 16px",
    borderRadius: 999,
    fontSize: 13,
    fontWeight: 600,
    border: "none",
    cursor: "pointer",
    transition: "all 0.15s ease",
  };

  const pillActive: React.CSSProperties = {
    ...pillBase,
    background: TOKENS.blue600,
    color: TOKENS.white,
  };

  const pillInactive: React.CSSProperties = {
    ...pillBase,
    background: "transparent",
    color: TOKENS.slate500,
  };

  /* --- Render ------------------------------------------------------ */

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto", padding: "24px 16px", fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" }}>
      {/* Pulse keyframes */}
      <style>{`@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }`}</style>

      {/* ── Page Header ─────────────────────────────────────────── */}
      <PageHeader
        title="Review Queue"
        subtitle="Evaluate and action suspected conditions for documentation improvement"
        icon={<ClipboardList size={22} />}
        actions={
          !isLoading ? (
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                background: TOKENS.blue600,
                color: TOKENS.white,
                fontSize: 13,
                fontWeight: 700,
                borderRadius: 999,
                padding: "4px 14px",
                minWidth: 32,
              }}
            >
              {suspectsData?.count ?? 0}
            </span>
          ) : undefined
        }
      />

      {/* ── Summary Strip ───────────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}>
        <StatCard
          label="Open Suspects"
          value={isLoading ? "--" : stats.total}
          icon={<ClipboardList size={18} />}
          color={TOKENS.blue600}
        />
        <StatCard
          label="High Confidence >85%"
          value={isLoading ? "--" : stats.highConf}
          icon={<TrendingUp size={18} />}
          color={TOKENS.emerald600}
        />
        <StatCard
          label="Patients Affected"
          value={isLoading ? "--" : stats.uniquePatients}
          icon={<Users size={18} />}
          color={TOKENS.amber600}
        />
        <StatCard
          label="Avg Confidence"
          value={isLoading ? "--" : `${(stats.avgConf * 100).toFixed(0)}%`}
          icon={<Activity size={18} />}
          color={TOKENS.gray500}
        />
      </div>

      {/* ── Filter Bar ──────────────────────────────────────────── */}
      <div
        style={{
          background: TOKENS.white,
          border: `1px solid ${TOKENS.slate200}`,
          borderRadius: 12,
          padding: "12px 20px",
          display: "flex",
          alignItems: "center",
          gap: 16,
          flexWrap: "wrap",
          marginBottom: 20,
        }}
      >
        {/* Status pills */}
        <div style={{ display: "flex", alignItems: "center", gap: 4, background: TOKENS.slate50, borderRadius: 999, padding: 3 }}>
          {STATUS_TABS.map((tab) => (
            <button
              key={tab.value}
              onClick={() => handleStatusChange(tab.value)}
              style={statusFilter === tab.value ? pillActive : pillInactive}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Search */}
        <div style={{ position: "relative", flex: 1, minWidth: 200, maxWidth: 320 }}>
          <Search
            size={15}
            style={{
              position: "absolute",
              left: 10,
              top: "50%",
              transform: "translateY(-50%)",
              color: TOKENS.slate400,
              pointerEvents: "none",
            }}
          />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => { setSearchTerm(e.target.value); setPage(0); }}
            placeholder="Search patient name..."
            aria-label="Search patients"
            style={{
              width: "100%",
              height: 36,
              paddingLeft: 34,
              paddingRight: 12,
              border: `1px solid ${TOKENS.slate200}`,
              borderRadius: 8,
              fontSize: 13,
              outline: "none",
              background: TOKENS.slate50,
              color: TOKENS.slate800,
            }}
          />
        </div>

        {/* Confidence dropdown */}
        <select
          value={confidenceBand}
          onChange={(e) => { setConfidenceBand(e.target.value as ConfidenceBand); setPage(0); }}
          aria-label="Filter by confidence"
          style={{
            height: 36,
            paddingLeft: 12,
            paddingRight: 28,
            border: `1px solid ${TOKENS.slate200}`,
            borderRadius: 8,
            fontSize: 13,
            fontWeight: 500,
            background: TOKENS.slate50,
            color: TOKENS.slate700,
            cursor: "pointer",
            outline: "none",
            appearance: "none" as const,
            backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2394A3B8' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E")`,
            backgroundRepeat: "no-repeat",
            backgroundPosition: "right 8px center",
          }}
        >
          {CONFIDENCE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>

        {/* Sort toggle */}
        <button
          onClick={() => setSortField((f) => (f === "confidence" ? "patient" : "confidence"))}
          style={{
            height: 36,
            padding: "0 14px",
            border: `1px solid ${TOKENS.slate200}`,
            borderRadius: 8,
            fontSize: 12,
            fontWeight: 600,
            background: TOKENS.white,
            color: TOKENS.slate600,
            cursor: "pointer",
          }}
        >
          Sort: {sortField === "confidence" ? "Confidence" : "Patient"}
        </button>

        {/* Result count */}
        <span
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: TOKENS.slate500,
            marginLeft: "auto",
          }}
        >
          {filteredSorted.length} result{filteredSorted.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* ── Select-all header ───────────────────────────────────── */}
      {selectableIds.length > 0 && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, paddingLeft: 20 }}>
          <input
            type="checkbox"
            checked={allSelected}
            onChange={toggleAll}
            style={{ width: 15, height: 15, accentColor: TOKENS.blue600, cursor: "pointer" }}
            aria-label="Select all on this page"
          />
          <span style={{ fontSize: 12, color: TOKENS.slate500, fontWeight: 500 }}>
            Select all on page
          </span>
        </div>
      )}

      {/* ── Suspect Cards ───────────────────────────────────────── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {isLoading &&
          Array.from({ length: 8 }).map((_, i) => <SkeletonCard key={i} />)}

        {!isLoading && filteredSorted.length === 0 && (
          <div
            style={{
              background: TOKENS.white,
              border: `1px solid ${TOKENS.slate200}`,
              borderRadius: 12,
            }}
          >
            <EmptyState
              icon={<FileSearch size={28} />}
              title="No suspects to review"
              description="There are no suspect conditions matching your current filters. Adjust the status or search criteria to see results."
            />
          </div>
        )}

        {!isLoading &&
          pagedSuspects.map((s) => {
            const conf = s.confidence_score ?? 0;
            const barCol = confBarColor(conf);
            const isOpen = s.status === "open";
            const isSelected = selected.has(s.id);

            return (
              <div
                key={s.id}
                style={{
                  height: 80,
                  background: isSelected ? TOKENS.blue50 : TOKENS.white,
                  border: `1px solid ${isSelected ? TOKENS.blue500 + "40" : TOKENS.slate200}`,
                  borderRadius: 10,
                  display: "flex",
                  alignItems: "center",
                  cursor: "pointer",
                  transition: "all 0.12s ease",
                  overflow: "hidden",
                  position: "relative",
                }}
                onClick={() => router.push(`/patients/${s.patient_id}`)}
              >
                {/* Checkbox */}
                <div
                  style={{ width: 48, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}
                  onClick={(e) => e.stopPropagation()}
                >
                  {isOpen ? (
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => toggleSelect(s.id)}
                      style={{ width: 15, height: 15, accentColor: TOKENS.blue600, cursor: "pointer" }}
                      aria-label={`Select suspect ${s.id}`}
                    />
                  ) : (
                    <div style={{ width: 15, height: 15 }} />
                  )}
                </div>

                {/* Confidence color bar (left edge) */}
                <div
                  style={{
                    width: 4,
                    height: 48,
                    borderRadius: 2,
                    background: barCol,
                    flexShrink: 0,
                  }}
                />

                {/* Content area */}
                <div
                  style={{
                    flex: 1,
                    display: "flex",
                    alignItems: "center",
                    gap: 20,
                    padding: "0 20px",
                    minWidth: 0,
                  }}
                >
                  {/* Patient name */}
                  <div style={{ width: 160, flexShrink: 0, minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: 14,
                        fontWeight: 700,
                        color: TOKENS.blue700,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {s.patient_name ?? `Patient ${s.patient_id}`}
                    </div>
                  </div>

                  {/* Condition */}
                  <div style={{ width: 180, flexShrink: 0, minWidth: 0 }}>
                    <div
                      style={{
                        fontSize: 13,
                        color: TOKENS.slate700,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      {s.suspected_condition ?? `HCC ${s.suspect_hcc}`}
                    </div>
                  </div>

                  {/* ICD-10 badge */}
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      padding: "3px 8px",
                      borderRadius: 6,
                      fontSize: 11,
                      fontFamily: "'SF Mono', 'Fira Code', monospace",
                      fontWeight: 600,
                      background: TOKENS.slate100,
                      color: TOKENS.slate700,
                      border: `1px solid ${TOKENS.slate200}`,
                      whiteSpace: "nowrap",
                      flexShrink: 0,
                    }}
                  >
                    {s.suspect_icd10}
                  </span>

                  {/* HCC badge */}
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      padding: "3px 8px",
                      borderRadius: 6,
                      fontSize: 11,
                      fontWeight: 600,
                      background: s.suspect_hcc ? TOKENS.blue50 : TOKENS.gray100,
                      color: s.suspect_hcc ? TOKENS.blue700 : TOKENS.gray400,
                      border: `1px solid ${s.suspect_hcc ? TOKENS.blue100 : TOKENS.gray200}`,
                      whiteSpace: "nowrap",
                      flexShrink: 0,
                    }}
                  >
                    {s.suspect_hcc ? `HCC ${s.suspect_hcc}` : "\u2014"}
                  </span>

                  {/* Confidence bar + percentage */}
                  <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
                    <div
                      style={{
                        width: 80,
                        height: 6,
                        borderRadius: 3,
                        background: TOKENS.slate100,
                        overflow: "hidden",
                      }}
                    >
                      <div
                        style={{
                          height: "100%",
                          width: `${conf * 100}%`,
                          borderRadius: 3,
                          background: barCol,
                          transition: "width 0.3s ease",
                        }}
                      />
                    </div>
                    <span
                      style={{
                        fontSize: 12,
                        fontWeight: 700,
                        color: barCol,
                        minWidth: 32,
                        textAlign: "right",
                      }}
                    >
                      {(conf * 100).toFixed(0)}%
                    </span>
                  </div>

                  {/* Evidence preview */}
                  <div
                    style={{
                      flex: 1,
                      minWidth: 0,
                      fontSize: 12,
                      color: TOKENS.slate400,
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {evidenceText(s)}
                  </div>
                </div>

                {/* Action buttons */}
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 6,
                    paddingRight: 16,
                    flexShrink: 0,
                  }}
                  onClick={(e) => e.stopPropagation()}
                >
                  {isOpen && (
                    <>
                      <button
                        disabled={acceptMut.isPending}
                        onClick={() => acceptMut.mutate(s.id)}
                        aria-label="Accept"
                        title="Accept"
                        style={{
                          width: 32,
                          height: 32,
                          borderRadius: 8,
                          border: `1.5px solid ${TOKENS.emerald500}`,
                          background: "transparent",
                          color: TOKENS.emerald600,
                          cursor: "pointer",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          fontSize: 16,
                          fontWeight: 700,
                          transition: "all 0.12s ease",
                          opacity: acceptMut.isPending ? 0.4 : 1,
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = TOKENS.emerald50;
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = "transparent";
                        }}
                      >
                        &#x2713;
                      </button>
                      <button
                        disabled={dismissMut.isPending}
                        onClick={() => dismissMut.mutate(s.id)}
                        aria-label="Dismiss"
                        title="Dismiss"
                        style={{
                          width: 32,
                          height: 32,
                          borderRadius: 8,
                          border: `1.5px solid ${TOKENS.red500}`,
                          background: "transparent",
                          color: TOKENS.red600,
                          cursor: "pointer",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          fontSize: 16,
                          fontWeight: 700,
                          transition: "all 0.12s ease",
                          opacity: dismissMut.isPending ? 0.4 : 1,
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.background = TOKENS.red50;
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.background = "transparent";
                        }}
                      >
                        &#x2717;
                      </button>
                    </>
                  )}
                </div>
              </div>
            );
          })}
      </div>

      {/* ── Pagination ──────────────────────────────────────────── */}
      {!isLoading && filteredSorted.length > PAGE_SIZE && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 16,
            marginTop: 20,
          }}
        >
          <button
            disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}
            style={{
              width: 36,
              height: 36,
              borderRadius: 8,
              border: `1px solid ${TOKENS.slate200}`,
              background: TOKENS.white,
              cursor: page === 0 ? "default" : "pointer",
              opacity: page === 0 ? 0.4 : 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: TOKENS.slate600,
            }}
            aria-label="Previous page"
          >
            <ChevronLeft size={16} />
          </button>
          <span style={{ fontSize: 13, fontWeight: 600, color: TOKENS.slate600 }}>
            Page {page + 1} of {totalPages}
          </span>
          <button
            disabled={page >= totalPages - 1}
            onClick={() => setPage((p) => p + 1)}
            style={{
              width: 36,
              height: 36,
              borderRadius: 8,
              border: `1px solid ${TOKENS.slate200}`,
              background: TOKENS.white,
              cursor: page >= totalPages - 1 ? "default" : "pointer",
              opacity: page >= totalPages - 1 ? 0.4 : 1,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: TOKENS.slate600,
            }}
            aria-label="Next page"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}

      {/* ── Bulk Actions Bar (fixed bottom) ─────────────────────── */}
      {selected.size > 0 && (
        <div
          style={{
            position: "fixed",
            bottom: 0,
            left: 0,
            right: 0,
            background: TOKENS.white,
            borderTop: `1px solid ${TOKENS.slate200}`,
            boxShadow: "0 -4px 24px rgba(0,0,0,0.08)",
            padding: "12px 32px",
            display: "flex",
            alignItems: "center",
            gap: 16,
            zIndex: 50,
          }}
        >
          <span style={{ fontSize: 14, fontWeight: 700, color: TOKENS.slate800 }}>
            {selected.size} selected
          </span>

          <div style={{ width: 1, height: 24, background: TOKENS.slate200 }} />

          <button
            disabled={bulkMut.isPending}
            onClick={() => bulkMut.mutate({ action: "accept" })}
            style={{
              height: 36,
              padding: "0 20px",
              borderRadius: 8,
              border: "none",
              background: TOKENS.emerald600,
              color: TOKENS.white,
              fontSize: 13,
              fontWeight: 700,
              cursor: "pointer",
              opacity: bulkMut.isPending ? 0.6 : 1,
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            {bulkMut.isPending ? "..." : "\u2713"} Accept All
          </button>

          <button
            disabled={bulkMut.isPending}
            onClick={() => bulkMut.mutate({ action: "dismiss" })}
            style={{
              height: 36,
              padding: "0 20px",
              borderRadius: 8,
              border: `1.5px solid ${TOKENS.red500}`,
              background: "transparent",
              color: TOKENS.red600,
              fontSize: 13,
              fontWeight: 700,
              cursor: "pointer",
              opacity: bulkMut.isPending ? 0.6 : 1,
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            &#x2717; Dismiss All
          </button>

          <button
            onClick={() => setSelected(new Set())}
            style={{
              marginLeft: "auto",
              height: 36,
              padding: "0 16px",
              borderRadius: 8,
              border: `1px solid ${TOKENS.slate200}`,
              background: TOKENS.white,
              color: TOKENS.slate500,
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Clear
          </button>
        </div>
      )}
    </div>
  );
}
