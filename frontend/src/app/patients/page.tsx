"use client";

import React, { useState, useMemo, useCallback, useEffect, useRef, useTransition } from "react";
import { ErrorBoundary } from "@/components/error-boundary";
import { FocusTrap } from "@/components/ui/focus-trap";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { searchPatients, isEmrDeactivatedError } from "@/lib/api";
import api, { API_BASE } from "@/lib/api";
import type { Patient } from "@/types";
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
  FileDown,
  FileUp,
  Upload,
  X,
  CheckCircle,
  Download,
  Filter,
  FilterX,
  ShieldCheck,
  Trash2,
  TrendingUp,
  Activity,
} from "lucide-react";
import { downloadCSV } from "@/lib/csv-export";
import { C, FONT_MONO, initialsColor, deriveInitials, riskAccentColor, riskTone } from "@/lib/ui-utils";
import { tokens } from "@/styles/tokens";
import {
  usePatientActivity,
  formatActionLabel,
  formatRelativeTime,
  ActivityEndpointMissingError,
} from "@/components/raf-central/common/ActivityFeed";
import { ImportCSVModal } from "./components/ImportCSVModal";
import { BulkActionsBar } from "./components/BulkActionsBar";
import { KPIStrip } from "@/components/dashboards/admin/KPIStrip";
import { RiskFilterChips } from "./components/RiskFilterChips";
import { HelpButton } from "@/components/HelpPanel";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/empty-state";

// ---------------------------------------------------------------------------
// Constants & Types
// ---------------------------------------------------------------------------

const PAGE_SIZE = 20;

type SortKey = "name" | "age" | "raf_score" | "hcc_count";
type SortDir = "asc" | "desc";
type RiskFilter = "all" | "high" | "medium" | "low" | "unscored";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatLocation(p: Patient): string {
  const parts: string[] = [];
  if (p.city) parts.push(p.city);
  if (p.state) parts.push(p.state);
  if (parts.length === 0 && p.postal_code) return p.postal_code;
  return parts.join(", ") || "—";
}

// ---------------------------------------------------------------------------
// SortLabel
// ---------------------------------------------------------------------------

function SortLabel({
  col,
  label,
  sort,
  onSort,
  align = "left",
}: {
  col: SortKey;
  label: string;
  sort: { key: SortKey; dir: SortDir };
  onSort: (key: SortKey) => void;
  align?: "left" | "right";
}) {
  const active = sort.key === col;
  const sortSuffix = active
    ? sort.dir === "asc" ? ", sorted ascending" : ", sorted descending"
    : "";
  return (
    <button
      aria-label={`Sort by ${label}${sortSuffix}`}
      onClick={() => onSort(col)}
      className={[
        "inline-flex items-center gap-1 bg-transparent border-none p-0 m-0 cursor-pointer",
        "font-sans text-[11.5px] font-bold uppercase tracking-[0.08em] whitespace-nowrap transition-colors duration-150",
        active ? "text-slate-900" : "text-slate-500",
        align === "right" ? "justify-self-end" : "justify-self-start",
      ].join(" ")}
    >
      {label}
      {active && (
        <span className="inline-flex ml-0.5">
          {sort.dir === "asc"
            ? <ChevronUp size={11} className="text-slate-900" />
            : <ChevronDown size={11} className="text-slate-900" />
          }
        </span>
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// WorklistRowHoverActivity
// ---------------------------------------------------------------------------

const HOVER_DWELL_MS = 600;

function WorklistRowHoverActivity({
  patientId,
  isHovered,
}: {
  patientId: number | null | undefined;
  isHovered: boolean;
}) {
  const [dwelled, setDwelled] = useState(false);
  useEffect(() => {
    if (!isHovered || patientId == null) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setDwelled(false);
      return;
    }
    const t = setTimeout(() => setDwelled(true), HOVER_DWELL_MS);
    return () => clearTimeout(t);
  }, [isHovered, patientId]);

  const { data, isLoading, isError, error } = usePatientActivity(
    patientId,
    3,
    dwelled,
  );

  if (!dwelled) return null;
  if (isError && error instanceof ActivityEndpointMissingError) return null;

  return (
    <div
      role="tooltip"
      aria-label="Recent activity for this patient"
      onClick={(e) => e.stopPropagation()}
      className="absolute top-[calc(100%-4px)] right-4 z-40 min-w-[260px] max-w-[320px] py-2.5 px-3 rounded-lg bg-white border border-slate-200 shadow-[0_8px_24px_rgba(15,23,42,0.14),0_2px_6px_rgba(15,23,42,0.08)] text-xs text-slate-900 pointer-events-auto"
    >
      <div className="text-[10px] font-bold uppercase tracking-[0.04em] text-slate-600 mb-1.5">
        Recent activity
      </div>
      {isLoading && (
        <div className="text-slate-600 text-[11px]">Loading…</div>
      )}
      {isError && !(error instanceof ActivityEndpointMissingError) && (
        <div className="text-slate-600 text-[11px]">Unable to load activity.</div>
      )}
      {!isLoading && !isError && (!data || data.length === 0) && (
        <div className="text-slate-600 text-[11px]">No activity recorded yet.</div>
      )}
      {data && data.length > 0 && (
        <ol className="list-none m-0 p-0 flex flex-col gap-2">
          {data.map((it) => (
            <li key={it.id} className="flex flex-col leading-[1.3]">
              <span className="text-xs font-semibold text-slate-900">
                {formatActionLabel(it.action)}
              </span>
              <span className="text-[11px] text-slate-600">
                {it.actor_email || "system"}
                <span className="mx-1 text-slate-300">&middot;</span>
                <span title={new Date(it.created_at).toLocaleString()}>
                  {formatRelativeTime(it.created_at)}
                </span>
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Worklist column-filter input helpers — shared style via className
// ---------------------------------------------------------------------------

const colFilterInputCls = (active: boolean) =>
  [
    "w-full h-8 text-[11px] rounded-[4px] px-1 text-center tabular-nums",
    "border outline-none transition-colors",
    active
      ? "border-teal-600 bg-teal-50"
      : "border-slate-200 bg-white",
  ].join(" ");

const colFilterSelectCls = (active: boolean) =>
  [
    "h-8 text-[11px] rounded-[6px] px-1 cursor-pointer",
    "border outline-none transition-colors",
    active
      ? "border-teal-600 bg-teal-50 text-teal-700"
      : "border-slate-200 bg-white text-slate-500",
  ].join(" ");

// ---------------------------------------------------------------------------
// Worklist grid column template — single source of truth consumed by
// header row, filter row, skeleton rows, and data rows so all columns align.
// ---------------------------------------------------------------------------
const WORKLIST_COLS = "minmax(240px,2.2fr) 100px 100px minmax(200px,2fr) 100px 110px 32px";

// ---------------------------------------------------------------------------
// Worklist skeleton row
// ---------------------------------------------------------------------------

function SkeletonRow() {
  return (
    <div
      aria-hidden="true"
      className="grid items-center h-16 px-6 border-b border-slate-100 border-l-[3px] border-l-slate-200 animate-pulse"
      style={{ gridTemplateColumns: WORKLIST_COLS }}
    >
      {/* Patient */}
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-full bg-slate-100 shrink-0" />
        <div className="flex flex-col gap-1.5">
          <div className="w-36 h-3 rounded bg-slate-100" />
          <div className="w-20 h-2.5 rounded bg-slate-100" />
        </div>
      </div>
      {/* Risk Level */}
      <div className="w-16 h-[22px] rounded-full bg-slate-100" />
      {/* RAF */}
      <div className="w-14 h-[18px] rounded bg-slate-100" />
      {/* Risk Factors */}
      <div className="flex gap-1.5">
        <div className="w-14 h-5 rounded-md bg-slate-100" />
        <div className="w-14 h-5 rounded-md bg-slate-100" />
      </div>
      {/* HCCs */}
      <div className="w-10 h-[18px] rounded bg-slate-100 justify-self-end" />
      {/* Status */}
      <div className="w-[86px] h-6 rounded-full bg-slate-100" />
      {/* Chevron placeholder */}
      <div />
    </div>
  );
}

// ---------------------------------------------------------------------------
// PatientRow — memoised so sibling rows don't re-render when hover state or
// selection changes for a different row.  All data is passed via props; the
// only local state is the hover animation on the chevron which is driven by
// the `isHovered` prop from the parent.
// ---------------------------------------------------------------------------

interface PatientRowProps {
  p: Patient;
  rowIndex: number;
  isHovered: boolean;
  isSelected: boolean;
  onHoverEnter: () => void;
  onHoverLeave: () => void;
  onToggleSelect: (pid: number) => void;
}

const PatientRow = React.memo(function PatientRow({
  p,
  rowIndex,
  isHovered,
  isSelected,
  onHoverEnter,
  onHoverLeave,
  onToggleSelect,
}: PatientRowProps) {
  const pid = p.pid;
  const age = p.DOB ? calculateAge(p.DOB) : null;
  const score = p.raf_score ?? 0;
  const hccCount = p.hcc_count ?? 0;
  const scored = score > 0;
  const fullName =
    `${p.lname || ""}, ${p.fname || ""}`
      .trim()
      .replace(/^,\s*/, "")
      .replace(/,\s*$/, "") || "•";
  const initials = deriveInitials(p.fname, p.lname, pid);
  const sexLabel =
    p.sex === "Female" ? "F" :
    p.sex === "Male" ? "M" :
    p.sex ? p.sex[0] : "—";
  const avatarColor = initialsColor(fullName);
  const accent = riskAccentColor(scored ? score : null);
  const tone = riskTone(scored ? score : null);
  const toneFgAA =
    tone.label === "High" ? "#B91C1C" :
    tone.label === "Medium" ? "#B45309" :
    tone.label === "Low" ? "#047857" :
    tone.fg;
  const location = formatLocation(p);

  return (
    <tr
      key={p.pid != null ? `pid-${p.pid}` : `row-${rowIndex}`}
      role="row"
      aria-label={`${fullName}, ${age !== null ? `age ${age}` : "age unknown"}, RAF ${scored ? Number(score).toFixed(2) : "not calculated"}, ${tone.label} risk, ${hccCount} HCC${hccCount === 1 ? "" : "s"}`}
      onMouseEnter={onHoverEnter}
      onMouseLeave={onHoverLeave}
      data-selected={isSelected ? "true" : undefined}
      className="flex relative overflow-visible border-b border-slate-100 transition-colors duration-150"
      style={{
        height: 64,
        minHeight: 64,
        maxHeight: 64,
        borderLeft: `3px solid ${accent}`,
        backgroundColor: isHovered
          ? tokens.slate50
          : tone.label === "High"
            ? tokens.riskHighSoft
            : "#ffffff",
        animation: `fadeSlideIn 0.25s ease-out ${Math.min(rowIndex, 12) * 0.025}s both`,
      }}
    >
      {/* Checkbox cell */}
      <td
        role="gridcell"
        className="flex items-center justify-center shrink-0 p-0"
        style={{ width: 21 }}
      >
        <input
          type="checkbox"
          checked={typeof pid === "number" && isSelected}
          onChange={(e) => {
            e.stopPropagation();
            if (typeof pid === "number") onToggleSelect(pid);
          }}
          onClick={(e) => e.stopPropagation()}
          aria-label={`Select ${fullName} for bulk actions`}
          className="w-3.5 h-3.5 shrink-0 cursor-pointer accent-teal-700 transition-opacity"
          style={{
            opacity: isHovered || isSelected ? 1 : 0,
          }}
          onFocus={(e) => { e.currentTarget.style.opacity = "1"; }}
          onBlur={(e) => {
            e.currentTarget.style.opacity = isHovered || isSelected ? "1" : "0";
          }}
        />
      </td>

      {/* Content cell — Link is the sole navigation target */}
      <td role="gridcell" className="flex-1 min-w-0 p-0">
        <Link
          href={`/patients/${pid}`}
          className="worklist-grid worklist-row-anchor grid items-center overflow-visible pl-2 pr-6 gap-0 cursor-pointer no-underline text-inherit outline-none focus:shadow-[inset_0_0_0_2px_rgba(13,148,136,0.15)]"
          style={{
            gridTemplateColumns: WORKLIST_COLS,
            height: 64,
          }}
        >
          {/* Patient: avatar + name + subtitle */}
          <div
            title={`${fullName} · PID ${pid}`}
            className="flex items-center gap-2 min-w-0"
          >
            <div
              className="w-8 h-8 rounded-full shrink-0 flex items-center justify-center text-[11px] font-bold tracking-wide border"
              style={{
                background: `linear-gradient(135deg, ${avatarColor}1F 0%, ${avatarColor}0F 100%)`,
                color: avatarColor,
                borderColor: `${avatarColor}26`,
              }}
            >
              {initials}
            </div>
            <div className="min-w-0 flex flex-col gap-0.5">
              <span className="text-[14px] font-semibold text-slate-900 truncate leading-[1.2] tracking-[-0.005em]">
                {fullName}
              </span>
              <span
                className="text-[11px] text-slate-400 whitespace-nowrap tabular-nums tracking-wide"
                style={{ fontFamily: FONT_MONO }}
              >
                {age !== null ? `${age}${sexLabel !== "—" ? sexLabel : ""}` : ""}
                {age !== null && <span className="mx-1 text-slate-200">&middot;</span>}
                {pid}
                {location !== "—" && (
                  <>
                    <span className="mx-1 text-slate-200">&middot;</span>
                    {location}
                  </>
                )}
                {p.data_source === "upload" && (
                  <>
                    <span className="mx-1 text-slate-200">&middot;</span>
                    <span className="text-[9px] font-semibold tracking-[0.04em] px-[5px] py-px rounded bg-sky-50 text-blue-500 border border-sky-200 uppercase">
                      CSV
                    </span>
                  </>
                )}
              </span>
            </div>
          </div>

          {/* Risk Level badge */}
          <div>
            {scored ? (
              <span
                className="inline-flex items-center gap-1 h-6 px-2.5 rounded-full text-[11.5px] font-bold whitespace-nowrap"
                style={{ backgroundColor: tone.bg, color: toneFgAA }}
              >
                {tone.label === "High" ? "▲" : tone.label === "Medium" ? "●" : "▼"}{" "}
                {tone.label}
              </span>
            ) : (
              <span className="inline-flex items-center h-6 px-2.5 rounded-full bg-slate-100 text-slate-500 text-[11.5px] font-semibold">
                Unscored
              </span>
            )}
          </div>

          {/* RAF Score */}
          <div title={`Total CMS-HCC RAF Score: ${scored ? Number(score).toFixed(4) : "Not yet calculated"}`}>
            {scored ? (
              <span className="text-[20px] font-bold text-slate-900 tabular-nums leading-none tracking-[-0.025em]">
                {Number(score).toFixed(2)}
              </span>
            ) : (
              <span className="text-[18px] text-slate-200 font-normal tabular-nums">&mdash;</span>
            )}
          </div>

          {/* Risk Factors chips */}
          <div className="risk-factors-cell flex flex-wrap gap-1 items-center">
            {scored && (
              (p.demographic_score != null && p.demographic_score > 0) ||
              (p.disease_score != null && p.disease_score > 0) ||
              (p.interaction_score != null && p.interaction_score > 0)
            ) ? (
              <>
                {p.demographic_score != null && p.demographic_score > 0 && (
                  <span
                    title={`Demographic RAF component — age/sex/disability adjustment: ${Number(p.demographic_score).toFixed(4)}`}
                    className="inline-flex items-center gap-0.5 h-[22px] px-[7px] rounded-md bg-slate-100 border border-slate-200 text-[10.5px] font-semibold tabular-nums whitespace-nowrap cursor-default"
                  >
                    <span className="text-slate-500">Demo</span>
                    <span className="text-slate-900">{Number(p.demographic_score).toFixed(3)}</span>
                  </span>
                )}
                {p.disease_score != null && p.disease_score > 0 && (
                  <span
                    title={`Disease RAF component — HCC condition category contributions: ${Number(p.disease_score).toFixed(4)}`}
                    className="inline-flex items-center gap-0.5 h-[22px] px-[7px] rounded-md bg-slate-100 border border-slate-200 text-[10.5px] font-semibold tabular-nums whitespace-nowrap cursor-default"
                  >
                    <span className="text-slate-500">Disease</span>
                    <span className="text-slate-900">{Number(p.disease_score).toFixed(3)}</span>
                  </span>
                )}
                {p.interaction_score != null && p.interaction_score > 0 && (
                  <span
                    title={`Interaction RAF component — disease-disease interaction adjustments: ${Number(p.interaction_score).toFixed(4)}`}
                    className="inline-flex items-center gap-0.5 h-[22px] px-[7px] rounded-md bg-slate-100 border border-slate-200 text-[10.5px] font-semibold tabular-nums whitespace-nowrap cursor-default"
                  >
                    <span className="text-slate-500">Interact</span>
                    <span className="text-slate-900">{Number(p.interaction_score).toFixed(3)}</span>
                  </span>
                )}
              </>
            ) : (
              <span className="text-[12px] text-slate-200">&mdash;</span>
            )}
          </div>

          {/* HCC Count */}
          <div
            title={`${hccCount} Hierarchical Condition Categories identified`}
            className="flex flex-col items-end gap-px"
          >
            {hccCount > 0 ? (
              <>
                <span className="text-[17px] font-bold text-slate-900 tabular-nums leading-none tracking-[-0.015em]">
                  {hccCount}
                </span>
                <span className="text-[9px] font-semibold text-slate-400 uppercase tracking-[0.08em]">
                  {hccCount === 1 ? "HCC" : "HCCs"}
                </span>
              </>
            ) : (
              <span className="text-[17px] text-slate-200 font-normal">&mdash;</span>
            )}
          </div>

          {/* Status pill */}
          <div title={scored ? (tone.label === "High" ? "High risk — needs review" : "RAF score has been calculated") : "RAF score pending — patient needs analysis"}>
            <span
              className="inline-flex items-center gap-1.5 h-6 pl-2.5 pr-3 rounded-full text-[11.5px] font-semibold whitespace-nowrap tracking-[-0.005em] border"
              style={{
                backgroundColor:
                  !scored ? tokens.slate50 :
                  tone.label === "High" ? C.highSoft :
                  C.lowSoft,
                borderColor:
                  !scored ? C.border :
                  tone.label === "High" ? tokens.dangerBorder :
                  tokens.emerald100,
                color:
                  !scored ? tokens.slate600 :
                  tone.label === "High" ? "#B91C1C" :
                  tokens.successDark,
              }}
            >
              <span
                className="w-1.5 h-1.5 rounded-full"
                style={{
                  backgroundColor:
                    !scored ? tokens.slate300 :
                    tone.label === "High" ? tokens.dangerMedium :
                    tokens.success,
                  boxShadow:
                    !scored ? "none" :
                    tone.label === "High" ? "0 0 0 2px rgba(239,68,68,0.18)" :
                    "0 0 0 2px rgba(16,185,129,0.18)",
                }}
              />
              {!scored ? "Pending" : tone.label === "High" ? "Needs Review" : "Analyzed"}
            </span>
          </div>

          {/* Chevron */}
          <ChevronRight
            size={16}
            className={[
              "transition-all duration-150",
              isHovered ? "text-teal-700 translate-x-0.5" : "text-slate-300",
            ].join(" ")}
          />

          {/* Recent-activity hover card */}
          {typeof pid === "number" && (
            <WorklistRowHoverActivity patientId={pid} isHovered={isHovered} />
          )}
        </Link>
      </td>
    </tr>
  );
});

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

export default function PatientsPage() {
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const searchParams = useSearchParams();
  const initialRisk = (searchParams.get("risk") as RiskFilter) || "all";
  const [riskFilter, setRiskFilter] = useState<RiskFilter>(
    ["all", "high", "medium", "low", "unscored"].includes(initialRisk) ? initialRisk : "all"
  );
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: "raf_score", dir: "desc" });
  const [page, setPage] = useState(0);
  const [hoveredRow, setHoveredRow] = useState<string | number | null>(null);

  const [selectedPids, setSelectedPids] = useState<Set<number>>(new Set());
  const togglePid = (pid: number) => {
    setSelectedPids((prev) => {
      const next = new Set(prev);
      if (next.has(pid)) next.delete(pid);
      else next.add(pid);
      return next;
    });
  };
  const clearSelection = () => setSelectedPids(new Set());

  const [bulkRequestText, setBulkRequestText] = useState("");
  const [bulkRequestOpen, setBulkRequestOpen] = useState(false);
  const [bulkRequestSubmitting, setBulkRequestSubmitting] = useState(false);
  const runBulkRequestDocs = async () => {
    if (bulkRequestText.trim().length < 10) return;
    setBulkRequestSubmitting(true);
    try {
      const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";
      const ids = Array.from(selectedPids);
      const results = await Promise.allSettled(
        ids.map((pid) =>
          fetch(`${API_BASE}/api/clinical-queries`, {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              patient_id: pid,
              query_text: bulkRequestText.trim(),
            }),
          }),
        ),
      );
      const ok = results.filter((r) => r.status === "fulfilled" && (r as PromiseFulfilledResult<Response>).value.ok).length;
      const failed = results.length - ok;
      const msg = failed === 0
        ? `Sent ${ok} documentation request${ok === 1 ? "" : "s"} — PCPs notified.`
        : `Sent ${ok}, ${failed} failed — retry the failed patients individually.`;
      setSyncToast({ msg, id: Date.now() });
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
      toastTimerRef.current = setTimeout(() => setSyncToast(null), 8000);
      setBulkRequestText("");
      setBulkRequestOpen(false);
      clearSelection();
    } catch (e) {
      setSyncToast({ msg: `Bulk request failed: ${String(e)}`, id: Date.now() });
    } finally {
      setBulkRequestSubmitting(false);
    }
  };

  type EndpointStatus = "unknown" | "available" | "missing";
  const [reassignEndpointStatus, setReassignEndpointStatus] =
    useState<EndpointStatus>("unknown");
  const [recalcEndpointStatus, setRecalcEndpointStatus] =
    useState<EndpointStatus>("unknown");
  const [reviewedEndpointStatus, setReviewedEndpointStatus] =
    useState<EndpointStatus>("unknown");

  const [bulkReassignOpen, setBulkReassignOpen] = useState(false);
  const [bulkReassignUserId, setBulkReassignUserId] = useState("");
  const [bulkReassignSubmitting, setBulkReassignSubmitting] = useState(false);
  type ReassignUser = { id: number | string; full_name?: string; email?: string };
  const [bulkReassignUsers, setBulkReassignUsers] = useState<ReassignUser[] | null>(null);
  const [bulkReassignUsersError, setBulkReassignUsersError] = useState<string | null>(null);

  const [bulkRecalcOpen, setBulkRecalcOpen] = useState(false);
  const [bulkRecalcSubmitting, setBulkRecalcSubmitting] = useState(false);

  const [bulkReviewedOpen, setBulkReviewedOpen] = useState(false);
  const [bulkReviewedNote, setBulkReviewedNote] = useState("");
  const [bulkReviewedSubmitting, setBulkReviewedSubmitting] = useState(false);

  const callBulkAction = useCallback(
    async (
      path: string,
      body: Record<string, unknown>,
    ): Promise<{ ok: number; failed: number; total: number; missing: boolean; error?: string }> => {
      try {
        const res = await fetch(`${API_BASE}${path}`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (res.status === 404) {
          return { ok: 0, failed: 0, total: 0, missing: true };
        }
        let json: { ok?: number; succeeded?: number; failed?: number; total?: number; error?: string; message?: string } | null = null;
        try { json = await res.json(); } catch { /* tolerate empty body */ }
        if (!res.ok) {
          return {
            ok: 0,
            failed: Array.isArray(body.patient_ids) ? (body.patient_ids as number[]).length : 0,
            total: Array.isArray(body.patient_ids) ? (body.patient_ids as number[]).length : 0,
            missing: false,
            error: json?.error || json?.message || `HTTP ${res.status}`,
          };
        }
        const total = typeof json?.total === "number"
          ? json.total
          : Array.isArray(body.patient_ids) ? (body.patient_ids as number[]).length : 0;
        const ok = typeof json?.ok === "number"
          ? json.ok
          : (typeof json?.succeeded === "number" ? json.succeeded : total);
        const failed = typeof json?.failed === "number" ? json.failed : Math.max(0, total - ok);
        return { ok, failed, total, missing: false };
      } catch (e) {
        return {
          ok: 0,
          failed: Array.isArray(body.patient_ids) ? (body.patient_ids as number[]).length : 0,
          total: Array.isArray(body.patient_ids) ? (body.patient_ids as number[]).length : 0,
          missing: false,
          error: String(e),
        };
      }
    },
    [],
  );

  const showBulkToast = useCallback(
    (variant: "ok" | "warn" | "error", msg: string) => {
      const prefix =
        variant === "ok" ? "" :
        variant === "warn" ? "Partial: " :
        "Error: ";
      setSyncToast({ msg: `${prefix}${msg}`, id: Date.now() });
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
      toastTimerRef.current = setTimeout(
        () => setSyncToast(null),
        variant === "ok" ? 8000 : 12000,
      );
    },
    [],
  );

  useEffect(() => {
    if (!bulkReassignOpen) return;
    if (bulkReassignUsers !== null || bulkReassignUsersError !== null) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/api/auth/users`, { credentials: "include" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const raw = Array.isArray(data) ? data : (data?.users ?? []);
        if (cancelled) return;
        type RawUser = { id: number | string; full_name?: string; first_name?: string; last_name?: string; email?: string };
        setBulkReassignUsers(
          (raw as RawUser[]).map((u) => ({
            id: u.id,
            full_name: u.full_name ?? [u.first_name, u.last_name].filter(Boolean).join(" "),
            email: u.email,
          })),
        );
      } catch (e) {
        if (cancelled) return;
        setBulkReassignUsersError(String(e));
      }
    })();
    return () => { cancelled = true; };
  }, [bulkReassignOpen, bulkReassignUsers, bulkReassignUsersError]);

  const runBulkReassign = async () => {
    const assignee = bulkReassignUserId.trim();
    if (!assignee) return;
    setBulkReassignSubmitting(true);
    const ids = Array.from(selectedPids);
    const assigneeNumeric = Number(assignee);
    const result = await callBulkAction("/api/bulk-actions/patients/reassign", {
      patient_ids: ids,
      assignee_user_id: Number.isFinite(assigneeNumeric) && assignee !== "" ? assigneeNumeric : assignee,
    });
    setBulkReassignSubmitting(false);
    if (result.missing) {
      setReassignEndpointStatus("missing");
      showBulkToast("error", "Reassign endpoint not yet deployed.");
      setBulkReassignOpen(false);
      return;
    }
    setReassignEndpointStatus("available");
    if (result.error) {
      showBulkToast("error", `Reassign failed — ${result.error}`);
      return;
    }
    if (result.failed > 0) {
      showBulkToast("warn", `Reassigned ${result.ok}/${result.total} patient${result.total === 1 ? "" : "s"} — ${result.failed} failed.`);
    } else {
      showBulkToast("ok", `Reassigned ${result.ok} patient${result.ok === 1 ? "" : "s"} to user ${assignee}.`);
    }
    setBulkReassignUserId("");
    setBulkReassignOpen(false);
    clearSelection();
  };

  const runBulkRecalc = async () => {
    setBulkRecalcSubmitting(true);
    const ids = Array.from(selectedPids);
    const result = await callBulkAction("/api/bulk-actions/patients/recalculate-raf", {
      patient_ids: ids,
    });
    setBulkRecalcSubmitting(false);
    if (result.missing) {
      setRecalcEndpointStatus("missing");
      showBulkToast("error", "Recalculate-RAF endpoint not yet deployed.");
      setBulkRecalcOpen(false);
      return;
    }
    setRecalcEndpointStatus("available");
    if (result.error) {
      showBulkToast("error", `RAF recalc failed — ${result.error}`);
      return;
    }
    if (result.failed > 0) {
      showBulkToast("warn", `Recalculated RAF for ${result.ok}/${result.total} — ${result.failed} failed.`);
    } else {
      showBulkToast("ok", `RAF recalc kicked off for ${result.ok} patient${result.ok === 1 ? "" : "s"}.`);
    }
    setBulkRecalcOpen(false);
    clearSelection();
    queryClient.invalidateQueries({ queryKey: ["patients"] });
  };

  const runBulkMarkReviewed = async () => {
    setBulkReviewedSubmitting(true);
    const ids = Array.from(selectedPids);
    const result = await callBulkAction("/api/bulk-actions/patients/mark-reviewed", {
      patient_ids: ids,
      note: bulkReviewedNote.trim(),
    });
    setBulkReviewedSubmitting(false);
    if (result.missing) {
      setReviewedEndpointStatus("missing");
      showBulkToast("error", "Mark-reviewed endpoint not yet deployed.");
      setBulkReviewedOpen(false);
      return;
    }
    setReviewedEndpointStatus("available");
    if (result.error) {
      showBulkToast("error", `Mark-reviewed failed — ${result.error}`);
      return;
    }
    if (result.failed > 0) {
      showBulkToast("warn", `Marked ${result.ok}/${result.total} reviewed — ${result.failed} failed.`);
    } else {
      showBulkToast("ok", `Marked ${result.ok} patient${result.ok === 1 ? "" : "s"} as reviewed.`);
    }
    setBulkReviewedNote("");
    setBulkReviewedOpen(false);
    clearSelection();
  };

  const [showImportModal, setShowImportModal] = useState(false);
  const [showColumnFilters, setShowColumnFilters] = useState(false);
  const [measurementYear, setMeasurementYear] = useState<number>(2026);
  const [colFilters, setColFilters] = useState({
    sex: "all" as "all" | "Male" | "Female",
    ageMin: "",
    ageMax: "",
    rafMin: "",
    rafMax: "",
    demoMin: "",
    demoMax: "",
    diseaseMin: "",
    diseaseMax: "",
    interactMin: "",
    interactMax: "",
    hccMin: "",
    hccMax: "",
    status: "all" as "all" | "analyzed" | "pending",
  });
  const hasActiveColFilters = colFilters.sex !== "all" || colFilters.ageMin || colFilters.ageMax || colFilters.rafMin || colFilters.rafMax || colFilters.demoMin || colFilters.demoMax || colFilters.diseaseMin || colFilters.diseaseMax || colFilters.interactMin || colFilters.interactMax || colFilters.hccMin || colFilters.hccMax || colFilters.status !== "all";
  const clearColFilters = () => setColFilters({ sex: "all", ageMin: "", ageMax: "", rafMin: "", rafMax: "", demoMin: "", demoMax: "", diseaseMin: "", diseaseMax: "", interactMin: "", interactMax: "", hccMin: "", hccMax: "", status: "all" });
  const router = useRouter();
  const queryClient = useQueryClient();

  // ---------------------------------------------------------------------------
  // Auto-sync: SSE subscription for patient.synced / patient.scored events
  // ---------------------------------------------------------------------------
  const [syncToast, setSyncToast] = useState<{ msg: string; id: number } | null>(null);
  const [autoSyncActive, setAutoSyncActive] = useState(false);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let es: EventSource | null = null;
    let cancelled = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    const connect = async () => {
      if (cancelled) return;
      try {
        const ticketRes = await api.get<{ ticket: string }>("/api/notifications/sse-ticket");
        if (cancelled) return;
        const ticket = ticketRes.data.ticket;
        es = new EventSource(`${API_BASE}/api/notifications/stream?ticket=${ticket}`);

        es.onopen = () => { if (!cancelled) setAutoSyncActive(true); };

        es.onmessage = (e) => {
          if (cancelled) return;
          try {
            const payload = JSON.parse(e.data) as Record<string, unknown>;
            const evType = payload.event_type as string | undefined;
            if (evType === "patient.synced" || evType === "patient.scored") {
              queryClient.invalidateQueries({ queryKey: ["patients"] });
              const fname = (payload.fname as string | undefined) ?? "";
              const lname = (payload.lname as string | undefined) ?? "";
              const raf = payload.raf_score != null ? Number(payload.raf_score).toFixed(2) : null;
              const initials = `${fname.charAt(0) || "?"}${lname.charAt(0) || ""}`.toUpperCase();
              const pidStr = String(payload.pid ?? "");
              const pidTail = pidStr ? pidStr.slice(-4) : "";
              const identity = pidTail ? `${initials} (·${pidTail})` : initials || "Patient";
              const msg = evType === "patient.synced"
                ? `New patient synced: ${identity}${raf ? ` (RAF ${raf})` : ""}`
                : `Patient scored: ${identity}${raf ? ` (RAF ${raf})` : ""}`;
              setSyncToast({ msg, id: Date.now() });
              if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
              toastTimerRef.current = setTimeout(() => setSyncToast(null), 15000);
            }
          } catch {}
        };

        es.onerror = () => {
          if (cancelled) return;
          setAutoSyncActive(false);
          if (es && es.readyState === EventSource.OPEN) {
            es.close();
            es = null;
          }
          if (!cancelled) {
            reconnectTimer = setTimeout(connect, 5000);
          }
        };
      } catch {
        if (!cancelled) {
          reconnectTimer = setTimeout(connect, 10000);
        }
      }
    };

    connect();

    return () => {
      cancelled = true;
      setAutoSyncActive(false);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (es) es.close();
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Server-side search & pagination
  const { data: apiResult, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["patients", debouncedSearch, page, riskFilter, hasActiveColFilters, measurementYear],
    queryFn: () => searchPatients({
      search: debouncedSearch || undefined,
      limit: (riskFilter !== "all" || hasActiveColFilters) ? 500 : PAGE_SIZE,
      offset: (riskFilter !== "all" || hasActiveColFilters) ? 0 : page * PAGE_SIZE,
      year: measurementYear,
    }),
    placeholderData: (prev) => prev,
    staleTime: 60_000,
  });

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search);
      setPage(0);
    }, 400);
    return () => clearTimeout(timer);
  }, [search]);

  const { rows, total, totalPages } = useMemo(() => {
    let list: Patient[] = apiResult?.patients ?? [];
    const serverTotal = apiResult?.total ?? 0;

    if (riskFilter !== "all") {
      list = list.filter((p) => {
        const s = p.raf_score ?? 0;
        if (riskFilter === "high") return s >= 2.0;
        if (riskFilter === "medium") return s >= 1.0 && s <= 2.0;
        if (riskFilter === "low") return s > 0 && s < 1.0;
        if (riskFilter === "unscored") return !s || s === 0;
        return true;
      });
    }

    if (colFilters.sex !== "all") {
      list = list.filter((p) => p.sex === colFilters.sex);
    }
    if (colFilters.ageMin) {
      const min = Number(colFilters.ageMin);
      list = list.filter((p) => (p.DOB ? (calculateAge(p.DOB) ?? 0) : 0) >= min);
    }
    if (colFilters.ageMax) {
      const max = Number(colFilters.ageMax);
      list = list.filter((p) => (p.DOB ? (calculateAge(p.DOB) ?? 0) : 999) <= max);
    }
    if (colFilters.rafMin) {
      const min = Number(colFilters.rafMin);
      list = list.filter((p) => (p.raf_score ?? 0) >= min);
    }
    if (colFilters.rafMax) {
      const max = Number(colFilters.rafMax);
      list = list.filter((p) => (p.raf_score ?? 0) <= max);
    }
    if (colFilters.demoMin) {
      const min = Number(colFilters.demoMin);
      list = list.filter((p) => (p.demographic_score ?? 0) >= min);
    }
    if (colFilters.demoMax) {
      const max = Number(colFilters.demoMax);
      list = list.filter((p) => (p.demographic_score ?? 0) <= max);
    }
    if (colFilters.diseaseMin) {
      const min = Number(colFilters.diseaseMin);
      list = list.filter((p) => (p.disease_score ?? 0) >= min);
    }
    if (colFilters.diseaseMax) {
      const max = Number(colFilters.diseaseMax);
      list = list.filter((p) => (p.disease_score ?? 0) <= max);
    }
    if (colFilters.interactMin) {
      const min = Number(colFilters.interactMin);
      list = list.filter((p) => (p.interaction_score ?? 0) >= min);
    }
    if (colFilters.interactMax) {
      const max = Number(colFilters.interactMax);
      list = list.filter((p) => (p.interaction_score ?? 0) <= max);
    }
    if (colFilters.hccMin) {
      const min = Number(colFilters.hccMin);
      list = list.filter((p) => (p.hcc_count ?? 0) >= min);
    }
    if (colFilters.hccMax) {
      const max = Number(colFilters.hccMax);
      list = list.filter((p) => (p.hcc_count ?? 0) <= max);
    }
    if (colFilters.status !== "all") {
      list = list.filter((p) => {
        const scored = (p.raf_score ?? 0) > 0;
        return colFilters.status === "analyzed" ? scored : !scored;
      });
    }

    list = [...list].sort((a, b) => {
      let aVal: string | number, bVal: string | number;
      switch (sort.key) {
        case "name":
          aVal = `${a.lname} ${a.fname}`.toLowerCase();
          bVal = `${b.lname} ${b.fname}`.toLowerCase();
          break;
        case "age":
          aVal = a.DOB ? (calculateAge(a.DOB) ?? 0) : 0;
          bVal = b.DOB ? (calculateAge(b.DOB) ?? 0) : 0;
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

    const clientFiltered = riskFilter !== "all" || hasActiveColFilters;
    const total = clientFiltered ? list.length : serverTotal;
    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
    const rows = clientFiltered ? list.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE) : list;
    return { rows, total, totalPages };
  }, [apiResult, riskFilter, sort, colFilters, hasActiveColFilters, page]);

  const totalPatients = apiResult?.total ?? 0;

  const stats = useMemo(() => {
    const all = apiResult?.patients ?? [];
    let high = 0, medium = 0, low = 0, unscored = 0;
    let rafSum = 0, rafCount = 0, hccSum = 0;
    for (const p of all) {
      const s = p.raf_score ?? 0;
      if (!s || s === 0) unscored++;
      else if (s >= 2.0) high++;
      else if (s >= 1.0) medium++;
      else low++;
      if (s > 0) { rafSum += s; rafCount++; }
      hccSum += p.hcc_count ?? 0;
    }
    return {
      high, medium, low, unscored,
      all: all.length,
      avgRaf: rafCount > 0 ? rafSum / rafCount : 0,
      analyzedPct: all.length > 0 ? Math.round(((all.length - unscored) / all.length) * 100) : 0,
      hccTotal: hccSum,
    };
  }, [apiResult]);

  const [, startTransition] = useTransition();

  const handleSort = useCallback((key: SortKey) => {
    setSort((prev) => ({
      key,
      dir: prev.key === key && prev.dir === "asc" ? "desc" : "asc",
    }));
    setPage(0);
  }, []);

  function exportPatientsCSV() {
    if (!rows.length) return;
    const data = rows.map((p) => ({
      "Name": `${p.lname}, ${p.fname}`,
      "PID": p.pid,
      "DOB": p.DOB ?? "",
      "Age": p.DOB ? (calculateAge(p.DOB) ?? "") : "",
      "Sex": p.sex ?? "",
      "Location": formatLocation(p),
      "RAF Score": p.raf_score != null ? Number(p.raf_score).toFixed(2) : "",
      "HCC Count": p.hcc_count ?? 0,
      "Status": (p.raf_score ?? 0) > 0 ? "Analyzed" : "Pending",
    }));
    downloadCSV(data, "patients");
  }

  // ---- EMR deactivated empty state ----
  if (isError && isEmrDeactivatedError(error)) {
    return (
      <div role="status" className="flex flex-col items-center justify-center h-[60vh] gap-4 font-sans">
        <div className="rounded-2xl bg-amber-50 p-5">
          <AlertTriangle size={40} className="text-amber-500" />
        </div>
        <h2 className="text-lg font-bold text-slate-900 m-0">No patient data available</h2>
        <p className="text-sm text-slate-600 m-0 max-w-[440px] text-center">
          Connect an EMR or upload a CSV/Excel file of patients to get started.
        </p>
        <div className="flex gap-2.5 mt-2">
          <button
            type="button"
            onClick={() => router.push("/uploads")}
            className="inline-flex items-center gap-2 rounded-[10px] border border-teal-700 bg-teal-700 py-2 px-4 text-sm font-semibold text-white cursor-pointer"
          >
            <Upload size={16} /> Upload a patient file
          </button>
          <button
            type="button"
            onClick={() => router.push("/emr-config")}
            className="inline-flex items-center gap-2 rounded-[10px] border border-slate-200 bg-white py-2 px-4 text-sm font-medium text-slate-600 cursor-pointer"
          >
            Go to EMR Configuration
          </button>
        </div>
      </div>
    );
  }

  // ---- Error state ----
  if (isError) {
    return (
      <div role="alert" className="flex flex-col items-center justify-center h-[60vh] gap-4 font-sans">
        <div className="rounded-2xl bg-red-50 p-5">
          <AlertTriangle size={40} className="text-red-500" />
        </div>
        <h2 className="text-lg font-bold text-slate-900 m-0">Failed to load patients</h2>
        <p className="text-sm text-slate-600 m-0">Check that the server is running and try again.</p>
        <button
          onClick={() => refetch()}
          className="inline-flex items-center gap-2 rounded-[10px] border border-slate-200 bg-white py-2 px-4 text-sm font-medium text-slate-600 cursor-pointer"
        >
          <RefreshCw size={16} /> Retry
        </button>
      </div>
    );
  }

  return (
    <ErrorBoundary fallbackTitle="Patients page failed to load">
      <>
        {/* ============================================================ */}
        {/* Auto-sync toast notification                                 */}
        {/* ============================================================ */}
        {syncToast && (
          <div
            role="status"
            aria-live="polite"
            aria-label={syncToast.msg}
            className="fixed top-5 right-5 z-[9999] flex items-center gap-2.5 bg-slate-900 text-slate-50 py-3 px-4 rounded-[10px] shadow-[0_8px_24px_rgba(0,0,0,0.25)] text-sm font-medium font-sans max-w-[380px] [animation:slideInRight_0.25s_ease]"
          >
            <span className="text-lg shrink-0">🆕</span>
            <span className="flex-1">{syncToast.msg}</span>
            <button
              onClick={() => setSyncToast(null)}
              aria-label="Dismiss notification"
              className="bg-transparent border-none text-slate-500 cursor-pointer p-0.5 flex"
            >
              <X size={14} />
            </button>
          </div>
        )}

        {/* ============================================================ */}
        {/* Page shell                                                   */}
        {/* ============================================================ */}
        <div className="flex flex-col gap-0 bg-slate-50 min-h-screen p-4 md:p-6 overflow-x-hidden font-sans text-slate-900">

          {/* ============================================================ */}
          {/* Page header                                                  */}
          {/* ============================================================ */}
          <PageHeader
            icon={<Users size={20} />}
            title={
              <span className="flex items-center gap-2.5">
                Worklist
                {/* Auto-sync live indicator */}
                <span
                  role="status"
                  title={autoSyncActive ? "Auto-sync active" : "Auto-sync connecting…"}
                  aria-label={autoSyncActive ? "Auto-sync active" : "Auto-sync connecting"}
                  className={[
                    "inline-block w-2.5 h-2.5 rounded-full shrink-0 transition-all duration-300",
                    autoSyncActive
                      ? "bg-green-500 shadow-[0_0_0_3px_rgba(34,197,94,0.25)]"
                      : "bg-slate-400",
                  ].join(" ")}
                />
                {/* Measurement year picker */}
                <span className="inline-flex items-center gap-1.5 h-[26px] pl-2.5 pr-1 rounded-lg bg-teal-50 border border-teal-200 text-teal-700 text-[11px] font-semibold tracking-wide tabular-nums">
                  <span>MY</span>
                  <select
                    value={measurementYear}
                    onChange={(e) => { setMeasurementYear(Number(e.target.value)); setPage(0); }}
                    aria-label="Measurement year"
                    className="appearance-none bg-transparent border-none text-teal-700 text-xs font-bold tabular-nums cursor-pointer pr-4 focus:outline-none"
                    style={{
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
                </span>
              </span>
            }
            subtitle={
              isLoading
                ? "Loading registry…"
                : `${totalPatients.toLocaleString()} patients in registry · CMS-HCC V28 · MY ${measurementYear}`
            }
            actions={
              <div className="flex items-center gap-2.5 flex-wrap">
                {/* Search */}
                <div className="relative">
                  <label htmlFor="patients-search" className="sr-only">Search patients</label>
                  <Search
                    size={16}
                    className="absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none"
                    aria-hidden="true"
                  />
                  <input
                    id="patients-search"
                    type="text"
                    title="Search patients by name or PID"
                    placeholder="Search patients…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className="h-10 w-[min(320px,calc(100vw-180px))] rounded-[10px] border border-slate-200 bg-white pl-9 pr-3.5 text-[13px] text-slate-900 outline-none transition-all focus:border-teal-600 focus:ring-2 focus:ring-teal-100"
                  />
                </div>

                {/* Import (hidden — data ingestion handled elsewhere) */}
                <button
                  onClick={() => setShowImportModal(true)}
                  aria-label="Import patients from CSV"
                  className="hidden"
                >
                  <FileUp size={14} />
                  Import
                </button>

                {/* Export */}
                <button
                  onClick={exportPatientsCSV}
                  aria-label="Export patients as CSV"
                  className="inline-flex items-center gap-1.5 h-10 px-4 rounded-[10px] bg-teal-700 text-white text-[13px] font-semibold cursor-pointer shrink-0 shadow-[0_1px_2px_rgba(15,118,110,0.25),0_4px_12px_rgba(15,118,110,0.18)] hover:bg-teal-800 transition-colors border-none"
                >
                  <FileDown size={14} />
                  Export
                </button>

                <HelpButton />
              </div>
            }
          />

          {/* ============================================================ */}
          {/* KPI strip (compact ≤1280px)                                  */}
          {/* ============================================================ */}
          <div className="kpi-compact-strip" aria-label="Key performance indicators">
            {/* Need Review */}
            <div
              className={`kpi-compact-item kpi-compact-item--alert${stats.high > 0 ? " kpi-compact-item--clickable" : ""}`}
              onClick={() => { if (stats.high > 0) { setRiskFilter("high"); setPage(0); } }}
              role={stats.high > 0 ? "button" : undefined}
              tabIndex={stats.high > 0 ? 0 : undefined}
              aria-label={stats.high > 0 ? `Show ${stats.high} high-risk patients` : "No high-risk patients"}
              onKeyDown={(e) => { if (stats.high > 0 && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); setRiskFilter("high"); setPage(0); } }}
            >
              <TrendingUp size={14} className="text-red-600 shrink-0" />
              <span className="kpi-compact-label">Need Review</span>
              <span className={`kpi-compact-value ${stats.high > 0 ? "text-red-600" : "text-slate-700"}`}>{stats.high}</span>
            </div>
            {/* Unscored */}
            <div
              className={`kpi-compact-item${stats.unscored > 0 ? " kpi-compact-item--clickable" : ""}`}
              onClick={() => { if (stats.unscored > 0) { setRiskFilter("unscored"); setPage(0); } }}
              role={stats.unscored > 0 ? "button" : undefined}
              tabIndex={stats.unscored > 0 ? 0 : undefined}
              aria-label={stats.unscored > 0 ? `Show ${stats.unscored} unscored patients` : "No unscored patients"}
              onKeyDown={(e) => { if (stats.unscored > 0 && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); setRiskFilter("unscored"); setPage(0); } }}
            >
              <Users size={14} className="text-slate-400 shrink-0" />
              <span className="kpi-compact-label">Unscored</span>
              <span className="kpi-compact-value text-slate-700">{stats.unscored}</span>
            </div>
            {/* Average RAF */}
            <div className="kpi-compact-item">
              <Activity size={14} className="text-emerald-600 shrink-0" />
              <span className="kpi-compact-label">Avg RAF</span>
              <span className="kpi-compact-value text-slate-700">
                {stats.avgRaf > 0 ? stats.avgRaf.toFixed(2) : "—"}
              </span>
            </div>
            {/* HCCs Captured */}
            <div className="kpi-compact-item">
              <ShieldCheck size={14} className="text-blue-500 shrink-0" />
              <span className="kpi-compact-label">HCCs</span>
              <span className="kpi-compact-value text-slate-700">{stats.hccTotal.toLocaleString()}</span>
            </div>
          </div>

          {/* ---- Full 4-card KPI grid (>1280px only) ---- */}
          <KPIStrip
            stats={stats}
            onHighClick={() => { setRiskFilter("high"); setPage(0); }}
            onUnscoredClick={() => { setRiskFilter("unscored"); setPage(0); }}
          />

          {/* ============================================================ */}
          {/* Filter chips / column filter toggle                          */}
          {/* ============================================================ */}
          <RiskFilterChips
            stats={stats}
            riskFilter={riskFilter}
            onRiskFilterChange={(key) => startTransition(() => { setRiskFilter(key); setPage(0); })}
            showColumnFilters={showColumnFilters}
            onToggleColumnFilters={() => setShowColumnFilters((v) => !v)}
            hasActiveColFilters={!!hasActiveColFilters}
            colFilters={colFilters}
            onClearColFilters={() => { clearColFilters(); setPage(0); }}
            onColFiltersChange={(patch) => { setColFilters((f) => ({ ...f, ...patch })); setPage(0); }}
            isLoading={isLoading}
            page={page}
            total={total}
            totalPatients={totalPatients}
            PAGE_SIZE={PAGE_SIZE}
          />

          {/* ============================================================ */}
          {/* Worklist table                                               */}
          {/* ============================================================ */}
          <div
            role="region"
            aria-label="Patient worklist"
            aria-busy={isLoading}
            aria-live="polite"
            className="bg-white rounded-2xl overflow-x-auto border border-slate-100 shadow-[0_1px_3px_rgba(15,23,42,0.04),0_4px_16px_rgba(15,23,42,0.04)]"
          >
            {/* Bulk actions bar */}
            <BulkActionsBar
              selectedCount={selectedPids.size}
              onClearSelection={clearSelection}
              onRequestDocs={() => setBulkRequestOpen(true)}
              reassignEndpointStatus={reassignEndpointStatus}
              onOpenReassign={() => setBulkReassignOpen(true)}
              bulkReassignOpen={bulkReassignOpen}
              onCloseReassign={() => setBulkReassignOpen(false)}
              bulkReassignUsers={bulkReassignUsers}
              bulkReassignUsersError={bulkReassignUsersError}
              bulkReassignUserId={bulkReassignUserId}
              onReassignUserChange={setBulkReassignUserId}
              bulkReassignSubmitting={bulkReassignSubmitting}
              onConfirmReassign={runBulkReassign}
              recalcEndpointStatus={recalcEndpointStatus}
              onOpenRecalc={() => setBulkRecalcOpen(true)}
              bulkRecalcOpen={bulkRecalcOpen}
              onCloseRecalc={() => setBulkRecalcOpen(false)}
              bulkRecalcSubmitting={bulkRecalcSubmitting}
              onConfirmRecalc={runBulkRecalc}
              reviewedEndpointStatus={reviewedEndpointStatus}
              onOpenReviewed={() => setBulkReviewedOpen(true)}
              bulkReviewedOpen={bulkReviewedOpen}
              onCloseReviewed={() => setBulkReviewedOpen(false)}
              bulkReviewedNote={bulkReviewedNote}
              onReviewedNoteChange={setBulkReviewedNote}
              bulkReviewedSubmitting={bulkReviewedSubmitting}
              onConfirmReviewed={runBulkMarkReviewed}
              bulkRequestOpen={bulkRequestOpen}
              onCloseRequestDocs={() => setBulkRequestOpen(false)}
              bulkRequestText={bulkRequestText}
              onRequestTextChange={setBulkRequestText}
              bulkRequestSubmitting={bulkRequestSubmitting}
              onConfirmRequestDocs={runBulkRequestDocs}
            />

            {/* ---- Column header row ---- */}
            <div
              className="worklist-grid worklist-header-row grid items-center px-6 py-3 bg-slate-50 border-b border-slate-100"
              style={{ gridTemplateColumns: WORKLIST_COLS }}
            >
              <SortLabel col="name" label="Patient" sort={sort} onSort={handleSort} />
              <span className="text-[11.5px] font-bold uppercase tracking-[0.08em] text-slate-500">
                Risk Level
              </span>
              <span title="Risk Adjustment Factor (RAF): CMS-HCC V28 score. 1.0 = average cost. Higher = more complex patient.">
                <SortLabel col="raf_score" label="RAF Score" sort={sort} onSort={handleSort} />
              </span>
              <span className="risk-factors-cell text-[11.5px] font-bold uppercase tracking-[0.08em] text-slate-500">
                Risk Factors
              </span>
              <SortLabel col="hcc_count" label="HCCs" sort={sort} onSort={handleSort} align="right" />
              <span className="text-[11.5px] font-bold uppercase tracking-[0.08em] text-slate-500 pl-2">
                HCC Status
              </span>
              <span aria-hidden="true" />
            </div>

            {/* ---- Column filter row ---- */}
            {showColumnFilters && (
              <div
                className="worklist-grid worklist-filter-row grid items-center px-6 py-2.5 bg-slate-50 border-b border-slate-100"
                style={{ gridTemplateColumns: WORKLIST_COLS }}
              >
                {/* Patient col: sex + age range */}
                <div className="flex gap-1.5 items-center">
                  <select
                    title="Filter by sex"
                    aria-label="Filter by sex"
                    value={colFilters.sex}
                    onChange={(e) => { setColFilters((f) => ({ ...f, sex: e.target.value as typeof f.sex })); setPage(0); }}
                    className={colFilterSelectCls(colFilters.sex !== "all") + " w-[52px]"}
                  >
                    <option value="all">Sex</option>
                    <option value="Male">M</option>
                    <option value="Female">F</option>
                  </select>
                  <input
                    title="Minimum age" placeholder="Age≥"
                    aria-label="Minimum age"
                    value={colFilters.ageMin}
                    onChange={(e) => { setColFilters((f) => ({ ...f, ageMin: e.target.value })); setPage(0); }}
                    className={colFilterInputCls(!!colFilters.ageMin) + " w-11"}
                    type="number"
                  />
                  <input
                    title="Maximum age" placeholder="Age≤"
                    aria-label="Maximum age"
                    value={colFilters.ageMax}
                    onChange={(e) => { setColFilters((f) => ({ ...f, ageMax: e.target.value })); setPage(0); }}
                    className={colFilterInputCls(!!colFilters.ageMax) + " w-11"}
                    type="number"
                  />
                </div>

                {/* Risk Level col — derived from RAF, no direct filter */}
                <span className="text-[10px] text-slate-500 italic">auto</span>

                {/* RAF Score col */}
                <div className="flex flex-col gap-0.5">
                  <input
                    title="Minimum RAF score" placeholder="Min"
                    aria-label="Minimum RAF score"
                    value={colFilters.rafMin}
                    onChange={(e) => { setColFilters((f) => ({ ...f, rafMin: e.target.value })); setPage(0); }}
                    className={colFilterInputCls(!!colFilters.rafMin)}
                    type="number" step="0.1"
                  />
                  <input
                    title="Maximum RAF score" placeholder="Max"
                    aria-label="Maximum RAF score"
                    value={colFilters.rafMax}
                    onChange={(e) => { setColFilters((f) => ({ ...f, rafMax: e.target.value })); setPage(0); }}
                    className={colFilterInputCls(!!colFilters.rafMax)}
                    type="number" step="0.1"
                  />
                </div>

                {/* Risk Factors col — demo/disease/interact */}
                <div className="risk-factors-cell flex gap-1">
                  <div className="flex flex-col gap-0.5 flex-1">
                    <input title="Min demographic score" aria-label="Min demographic score" placeholder="Demo≥" value={colFilters.demoMin} onChange={(e) => { setColFilters((f) => ({ ...f, demoMin: e.target.value })); setPage(0); }} type="number" step="0.01" className={colFilterInputCls(!!colFilters.demoMin) + " !text-[10px]"} />
                    <input title="Max demographic score" aria-label="Max demographic score" placeholder="Demo≤" value={colFilters.demoMax} onChange={(e) => { setColFilters((f) => ({ ...f, demoMax: e.target.value })); setPage(0); }} type="number" step="0.01" className={colFilterInputCls(!!colFilters.demoMax) + " !text-[10px]"} />
                  </div>
                  <div className="flex flex-col gap-0.5 flex-1">
                    <input title="Min disease score" aria-label="Min disease score" placeholder="Dis≥" value={colFilters.diseaseMin} onChange={(e) => { setColFilters((f) => ({ ...f, diseaseMin: e.target.value })); setPage(0); }} type="number" step="0.01" className={colFilterInputCls(!!colFilters.diseaseMin) + " !text-[10px]"} />
                    <input title="Max disease score" aria-label="Max disease score" placeholder="Dis≤" value={colFilters.diseaseMax} onChange={(e) => { setColFilters((f) => ({ ...f, diseaseMax: e.target.value })); setPage(0); }} type="number" step="0.01" className={colFilterInputCls(!!colFilters.diseaseMax) + " !text-[10px]"} />
                  </div>
                  <div className="flex flex-col gap-0.5 flex-1">
                    <input title="Min interaction score" aria-label="Min interaction score" placeholder="Int≥" value={colFilters.interactMin} onChange={(e) => { setColFilters((f) => ({ ...f, interactMin: e.target.value })); setPage(0); }} type="number" step="0.01" className={colFilterInputCls(!!colFilters.interactMin) + " !text-[10px]"} />
                    <input title="Max interaction score" aria-label="Max interaction score" placeholder="Int≤" value={colFilters.interactMax} onChange={(e) => { setColFilters((f) => ({ ...f, interactMax: e.target.value })); setPage(0); }} type="number" step="0.01" className={colFilterInputCls(!!colFilters.interactMax) + " !text-[10px]"} />
                  </div>
                </div>

                {/* HCCs col */}
                <div className="flex flex-col gap-0.5">
                  <input
                    title="Minimum HCC count" placeholder="Min"
                    aria-label="Minimum HCC count"
                    value={colFilters.hccMin}
                    onChange={(e) => { setColFilters((f) => ({ ...f, hccMin: e.target.value })); setPage(0); }}
                    className={colFilterInputCls(!!colFilters.hccMin)}
                    type="number"
                  />
                  <input
                    title="Maximum HCC count" placeholder="Max"
                    aria-label="Maximum HCC count"
                    value={colFilters.hccMax}
                    onChange={(e) => { setColFilters((f) => ({ ...f, hccMax: e.target.value })); setPage(0); }}
                    className={colFilterInputCls(!!colFilters.hccMax)}
                    type="number"
                  />
                </div>

                {/* Status col */}
                <select
                  title="Filter by analysis status"
                  aria-label="Filter by analysis status"
                  value={colFilters.status}
                  onChange={(e) => { setColFilters((f) => ({ ...f, status: e.target.value as typeof f.status })); setPage(0); }}
                  className={colFilterSelectCls(colFilters.status !== "all") + " w-full"}
                >
                  <option value="all">All</option>
                  <option value="analyzed">Analyzed</option>
                  <option value="pending">Pending</option>
                </select>

                <span />
              </div>
            )}

            {/* ---- Loading skeleton ---- */}
            {isLoading && Array.from({ length: 8 }).map((_, i) => (
              <SkeletonRow key={`skeleton-${i}`} />
            ))}

            {/* ---- Empty state ---- */}
            {!isLoading && rows.length === 0 && (
              <div className="py-16 px-6">
                <EmptyState
                  state="filtered-out"
                  icon={<Users size={28} strokeWidth={1.75} />}
                  title={
                    riskFilter === "high" ? "No high-risk patients right now" :
                    riskFilter === "unscored" ? "No unscored patients" :
                    "No patients found"
                  }
                  description={
                    riskFilter === "high"
                      ? "Check Unscored patients for pending analysis — they may need a risk calculation."
                      : "Try broadening your search or adjusting the risk filter to see more results."
                  }
                  cta={
                    (riskFilter !== "all" || debouncedSearch || hasActiveColFilters)
                      ? {
                          label: "Clear all filters",
                          onClick: () => { setRiskFilter("all"); setSearch(""); clearColFilters(); setPage(0); },
                        }
                      : undefined
                  }
                />
              </div>
            )}

            {/* ---- Patient rows — rendered via memoised PatientRow ---- */}
            {rows.map((p, rowIndex) => {
              const pid = p.pid;
              const isHovered = hoveredRow === pid;
              const isSelected = typeof pid === "number" && selectedPids.has(pid);
              return (
                <PatientRow
                  key={p.pid != null ? `pid-${p.pid}` : `row-${rowIndex}`}
                  p={p}
                  rowIndex={rowIndex}
                  isHovered={isHovered}
                  isSelected={isSelected}
                  onHoverEnter={() => setHoveredRow(pid)}
                  onHoverLeave={() => setHoveredRow(null)}
                  onToggleSelect={togglePid}
                />
              );
            })}

            {/* ---- Pagination ---- */}
            {!isLoading && totalPages > 1 && (
              <div className="flex items-center justify-between gap-2 py-3.5 px-5 border-t border-slate-200 bg-slate-50/80">
                <span className="text-xs text-slate-600 tabular-nums">
                  Showing{" "}
                  <strong className="text-slate-900 font-semibold">
                    {Math.min(page * PAGE_SIZE + 1, total)}&ndash;{Math.min((page + 1) * PAGE_SIZE, total)}
                  </strong>{" "}
                  of <strong className="text-slate-900 font-semibold">{total.toLocaleString()}</strong>
                </span>

                <div className="flex items-center gap-1.5">
                  <button
                    disabled={page === 0}
                    onClick={() => setPage((p) => p - 1)}
                    aria-label="Previous page"
                    className="inline-flex items-center gap-1 h-8 px-3 rounded-lg border border-slate-200 bg-white text-xs font-medium text-slate-500 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed transition-colors hover:enabled:bg-slate-50"
                  >
                    <ChevronLeft size={13} /> Prev
                  </button>

                  {Array.from({ length: Math.min(totalPages, 7) }, (_, i) => {
                    let pageNum: number;
                    if (totalPages <= 7) {
                      pageNum = i;
                    } else if (page < 3) {
                      pageNum = i;
                    } else if (page > totalPages - 4) {
                      pageNum = totalPages - 7 + i;
                    } else {
                      pageNum = page - 3 + i;
                    }
                    const isActive = pageNum === page;
                    return (
                      <button
                        key={pageNum}
                        onClick={() => setPage(pageNum)}
                        className={[
                          "w-8 h-8 rounded-lg inline-flex items-center justify-center text-xs tabular-nums transition-colors cursor-pointer border-none",
                          isActive
                            ? "bg-teal-700 text-white font-semibold shadow-[0_2px_6px_rgba(15,118,110,0.25)]"
                            : "bg-transparent text-slate-500 font-medium hover:bg-slate-100",
                        ].join(" ")}
                        aria-current={isActive ? "page" : undefined}
                        aria-label={`Page ${pageNum + 1}`}
                      >
                        {pageNum + 1}
                      </button>
                    );
                  })}

                  <button
                    disabled={page >= totalPages - 1}
                    onClick={() => setPage((p) => p + 1)}
                    aria-label="Next page"
                    className="inline-flex items-center gap-1 h-8 px-3 rounded-lg border border-slate-200 bg-white text-xs font-medium text-slate-500 cursor-pointer disabled:opacity-60 disabled:cursor-not-allowed transition-colors hover:enabled:bg-slate-50"
                  >
                    Next <ChevronRight size={13} />
                  </button>
                </div>
              </div>
            )}
          </div>

          <style>{`
            @keyframes fadeSlideIn {
              from { opacity: 0; transform: translateY(6px); }
              to { opacity: 1; transform: translateY(0); }
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

          {showImportModal && (
            <ImportCSVModal
              onClose={() => setShowImportModal(false)}
              onImported={() => refetch()}
            />
          )}
        </div>
      </>
    </ErrorBoundary>
  );
}
