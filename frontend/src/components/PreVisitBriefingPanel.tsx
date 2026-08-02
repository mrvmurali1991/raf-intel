"use client";

/**
 * Pre-Visit HCC Briefing Panel.
 *
 * Renders a "huddle card" for each upcoming visit (today + N days) for a
 * provider, listing the patient + top 3 HCC gaps that should be addressed
 * during the visit. Backed by:
 *
 *   GET /api/providers/{id}/pre-visit-briefings?days=N
 *
 * Each card has a "Print huddle sheet" button that prints just that card
 * via a scoped print stylesheet. The empty-state UI is rendered when no
 * upcoming visits are returned.
 */
import React, { useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { Calendar, Printer, AlertCircle, Sparkles, FileText } from "lucide-react";
import {
  getProviderPreVisitBriefings,
  type PreVisitBriefing,
  type PreVisitBriefingsResponse,
  type PreVisitBriefingTopHcc as PreVisitHcc,
} from "@/lib/api";

type PreVisitHccStatus = PreVisitHcc["status"];

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

function formatUSD(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `$${(n / 1_000).toFixed(1)}k`;
  return `$${Math.round(n).toLocaleString()}`;
}

function formatVisitDate(date: string, time: string): string {
  if (!date) return "";
  try {
    const d = new Date(`${date}T${time || "00:00"}`);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const target = new Date(date);
    target.setHours(0, 0, 0, 0);
    const diffDays = Math.round(
      (target.getTime() - today.getTime()) / (1000 * 60 * 60 * 24)
    );
    let prefix = "";
    if (diffDays === 0) prefix = "Today";
    else if (diffDays === 1) prefix = "Tomorrow";
    else
      prefix = d.toLocaleDateString(undefined, {
        weekday: "short",
        month: "short",
        day: "numeric",
      });
    if (time) return `${prefix} · ${time}`;
    return prefix;
  } catch {
    return date;
  }
}

// ---------------------------------------------------------------------------
// Status palette — returns Tailwind class strings
// ---------------------------------------------------------------------------

function statusStyle(status: PreVisitHccStatus): {
  bgClass: string;
  fgClass: string;
  label: string;
} {
  switch (status) {
    case "suspect":
      return { bgClass: "bg-blue-100 dark:bg-blue-900", fgClass: "text-blue-700 dark:text-blue-300", label: "Suspect" };
    case "recapture":
      return { bgClass: "bg-amber-100 dark:bg-amber-900", fgClass: "text-amber-700 dark:text-amber-300", label: "Recapture" };
    case "meat_weak":
      return { bgClass: "bg-violet-100 dark:bg-violet-900", fgClass: "text-violet-700 dark:text-violet-300", label: "MEAT gap" };
    default:
      return { bgClass: "bg-slate-100 dark:bg-slate-800", fgClass: "text-slate-700 dark:text-slate-200", label: status };
  }
}

// ---------------------------------------------------------------------------
// Top-level panel
// ---------------------------------------------------------------------------

interface Props {
  providerId: number;
  days?: number;
}

export default function PreVisitBriefingPanel({
  providerId,
  days = 7,
}: Props) {
  const q = useQuery<PreVisitBriefingsResponse>({
    queryKey: ["pre-visit-briefings", providerId, days],
    queryFn: () => getProviderPreVisitBriefings(providerId, days),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  return (
    <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-[14px] p-5">
      <Header
        days={days}
        count={q.data?.briefings?.length ?? 0}
        loading={q.isLoading}
      />

      {q.isLoading && <LoadingState />}

      {q.isError && !q.isLoading && (
        <ErrorState message={(q.error as Error)?.message ?? "Unable to load."} />
      )}

      {!q.isLoading && !q.isError && q.data && (
        <>
          {q.data.briefings.length === 0 ? (
            <EmptyState message={q.data.message ?? "No upcoming visits."} days={days} />
          ) : (
            <div className="flex flex-col gap-3.5">
              {q.data.briefings.map((b) => (
                <BriefingCard key={b.encounter_id} briefing={b} />
              ))}
            </div>
          )}
        </>
      )}

      {/* Print stylesheet — only the active card prints. */}
      <style jsx global>{`
        @media print {
          body * {
            visibility: hidden !important;
          }
          .pvb-print-target,
          .pvb-print-target * {
            visibility: visible !important;
          }
          .pvb-print-target {
            position: absolute !important;
            left: 0 !important;
            top: 0 !important;
            width: 100% !important;
            box-shadow: none !important;
            border: 1px solid #000 !important;
          }
          .pvb-no-print {
            display: none !important;
          }
        }
      `}</style>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

function Header({
  days,
  count,
  loading,
}: {
  days: number;
  count: number;
  loading: boolean;
}) {
  return (
    <div
      className="pvb-no-print flex items-center justify-between mb-4"
    >
      <div className="flex items-center gap-2.5">
        <div
          className="bg-blue-50 dark:bg-blue-950 text-blue-600 dark:text-blue-400 flex items-center justify-center"
          style={{ width: 36, height: 36, borderRadius: 10 }}
        >
          <Calendar size={18} />
        </div>
        <div>
          <div className="text-[15px] font-bold text-slate-900 dark:text-slate-50 leading-tight">
            Upcoming visits (next {days} day{days !== 1 ? "s" : ""})
          </div>
          <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
            Top HCC gaps to address during each huddle
          </div>
        </div>
      </div>
      <div className="bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200 rounded-full text-xs font-semibold px-2.5 py-1">
        {loading ? "…" : count} briefing{count === 1 ? "" : "s"}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Single huddle card
// ---------------------------------------------------------------------------

function BriefingCard({ briefing }: { briefing: PreVisitBriefing }) {
  const ref = useRef<HTMLDivElement>(null);

  function handlePrint() {
    if (!ref.current) return;
    ref.current.classList.add("pvb-print-target");
    setTimeout(() => {
      window.print();
      ref.current?.classList.remove("pvb-print-target");
    }, 50);
  }

  return (
    <div
      ref={ref}
      className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-[10px] p-4"
    >
      {/* Patient + visit row */}
      <div className="flex items-start justify-between gap-3 mb-3.5 pb-3.5 border-b border-slate-100 dark:border-slate-800">
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className="text-base font-bold text-slate-900 dark:text-slate-50 mb-1">
            {briefing.patient_name}
          </div>
          <div className="text-xs text-slate-500 dark:text-slate-400 flex flex-wrap gap-2.5">
            {briefing.dob && (
              <span>
                DOB {briefing.dob}
                {briefing.age !== null && ` (${briefing.age}y)`}
              </span>
            )}
            {briefing.sex && <span>{briefing.sex}</span>}
            {briefing.mrn && <span>MRN {briefing.mrn}</span>}
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-[13px] font-semibold text-blue-700 dark:text-blue-300 mb-0.5">
            {formatVisitDate(briefing.visit_date, briefing.visit_time ?? "")}
          </div>
          {briefing.encounter_reason && (
            <div
              className="text-xs text-slate-600 dark:text-slate-300 italic max-w-[220px] overflow-hidden text-ellipsis whitespace-nowrap"
              title={briefing.encounter_reason}
            >
              CC: {briefing.encounter_reason}
            </div>
          )}
        </div>
      </div>

      {/* Top HCCs */}
      {briefing.top_hccs.length === 0 ? (
        <div className="text-[13px] text-slate-500 dark:text-slate-400 py-3 text-center italic">
          No open HCC gaps for this patient — code the visit as documented.
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {briefing.top_hccs.map((h, i) => (
            <HccRow key={`${h.hcc_code}-${i}`} hcc={h} />
          ))}
        </div>
      )}

      {/* Footer: total + print */}
      <div className="flex items-center justify-between mt-3.5 pt-3.5 border-t border-slate-100 dark:border-slate-800">
        <div className="flex items-center gap-1.5">
          <Sparkles size={14} className="text-emerald-600 dark:text-emerald-400" />
          <span className="text-xs text-slate-600 dark:text-slate-300">
            Total potential
          </span>
          <span className="text-sm font-bold text-emerald-700 dark:text-emerald-300 ml-1">
            {formatUSD(briefing.total_potential_dollars)}
          </span>
        </div>
        <button
          type="button"
          onClick={handlePrint}
          className="pvb-no-print flex items-center gap-1.5 bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-200 border border-slate-300 dark:border-slate-600 rounded-lg text-xs font-semibold cursor-pointer px-3 py-1.5"
          aria-label={`Print huddle sheet for ${briefing.patient_name}`}
        >
          <Printer size={13} />
          Print huddle sheet
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Single HCC mini-row
// ---------------------------------------------------------------------------

function HccRow({ hcc }: { hcc: PreVisitHcc }) {
  const sty = statusStyle(hcc.status);
  return (
    <div className="flex items-center gap-2.5 bg-slate-50 dark:bg-slate-800 rounded-[10px] border border-slate-100 dark:border-slate-800 px-3 py-2.5">
      {/* Code chip */}
      <div className="bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 rounded-md text-[11px] font-bold font-mono shrink-0 px-2 py-0.5">
        HCC {hcc.hcc_code}
      </div>

      {/* Label + evidence */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          className="text-[13px] font-semibold text-slate-900 dark:text-slate-50 overflow-hidden text-ellipsis whitespace-nowrap"
          title={hcc.hcc_label}
        >
          {hcc.hcc_label}
        </div>
        <div className="text-[11px] text-slate-500 dark:text-slate-400 flex items-center gap-1 mt-0.5">
          <FileText size={10} />
          <span
            className="overflow-hidden text-ellipsis whitespace-nowrap"
            title={hcc.evidence_snippet ?? undefined}
          >
            {hcc.evidence_snippet}
          </span>
        </div>
      </div>

      {/* Status pill */}
      <div
        className={`${sty.bgClass} ${sty.fgClass} rounded-full text-[10px] font-bold uppercase tracking-wide shrink-0 px-2 py-0.5`}
      >
        {sty.label}
      </div>

      {/* $ pill */}
      <div
        className="bg-emerald-50 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 rounded-full text-[11px] font-bold shrink-0 text-center px-2 py-0.5"
        style={{ minWidth: 50 }}
        title={`Confidence ${(hcc.confidence * 100).toFixed(0)}%`}
      >
        {formatUSD(hcc.expected_dollars)}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty / loading / error states
// ---------------------------------------------------------------------------

function EmptyState({ message, days }: { message: string; days: number }) {
  return (
    <div className="bg-slate-50 dark:bg-slate-800 rounded-[10px] border border-dashed border-slate-200 dark:border-slate-700 text-center px-5 py-8">
      <Calendar
        size={28}
        className="text-slate-500 dark:text-slate-400 mb-2.5 mx-auto"
      />
      <div className="text-sm font-semibold text-slate-700 dark:text-slate-200 mb-1">
        No upcoming visits in next {days} day{days !== 1 ? "s" : ""}
      </div>
      <div className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
        {message ||
          "When new visits are scheduled in OpenEMR, huddle cards will appear here."}
        <br />
        Pre-visit briefings update automatically as the schedule fills in.
      </div>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="p-8 text-center text-slate-500 dark:text-slate-400 text-[13px]">
      Loading upcoming visits…
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="bg-amber-50 dark:bg-amber-950 border border-amber-100 dark:border-amber-900 rounded-[10px] flex gap-2.5 items-start p-5">
      <AlertCircle size={16} className="text-amber-600 dark:text-amber-400 shrink-0" />
      <div>
        <div className="text-[13px] font-semibold text-amber-700 dark:text-amber-300 mb-0.5">
          Pre-visit briefing unavailable
        </div>
        <div className="text-xs text-slate-600 dark:text-slate-300">{message}</div>
      </div>
    </div>
  );
}
