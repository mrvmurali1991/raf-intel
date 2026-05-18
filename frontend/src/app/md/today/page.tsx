"use client";

/**
 * MD Today — pre-visit huddle UI.
 *
 * Mobile/tablet-first. Each scheduled visit becomes a card with the top
 * HCC gaps for that patient. One-tap Accept/Reject with a MEAT-attestation
 * checkbox gates the FHIR write-back.
 */

import { useEffect, useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { useAuth } from "@/contexts/auth-context";

// ---------- Types ----------

interface LabEvidenceEntry {
  label: string;
  loinc: string;
  value: number;
  units: string;
  date: string | null;
  reference_range: string;
  abnormal_flag: string;
  status: "support" | "borderline" | "contradict";
}

interface LabEvidence {
  supporting?: LabEvidenceEntry[];
  borderline?: LabEvidenceEntry[];
  contradictory?: LabEvidenceEntry[];
}

interface HCCGap {
  hcc_code?: string | number;
  hcc?: string | number;
  description?: string;
  display?: string;
  confidence?: number;
  confidence_score?: number;
  expected_dollars?: number;
  revenue_estimate?: number;
  estimated_annual_revenue_dollars?: number;
  raf_coefficient?: number;
  lab_evidence?: LabEvidence;
  source?: string;
  suspect_id?: number;
  meat_status?: string;
}

interface Briefing {
  patient_id: number;
  patient_name?: string;
  first_name?: string;
  last_name?: string;
  age?: number;
  sex?: string;
  mrn?: string;
  visit_time?: string;
  visit_date?: string;
  reason?: string;
  hcc_gaps?: HCCGap[];
  top_gaps?: HCCGap[];
  reviewed?: boolean;
}

interface MDTodayResponse {
  provider_id: number;
  date: string;
  briefings: Briefing[];
  summary: {
    total_visits: number;
    total_open_hcc_gaps: number;
    reviewed_count: number;
    review_progress_pct: number;
    total_revenue_at_stake_dollars?: number;
    total_supporting_labs?: number;
  };
}

// ---------- Helpers ----------

function gapsOf(b: Briefing): HCCGap[] {
  return b.hcc_gaps || b.top_gaps || [];
}

function nameOf(b: Briefing): string {
  if (b.patient_name) return b.patient_name;
  const fn = [b.first_name, b.last_name].filter(Boolean).join(" ").trim();
  return fn || `Patient #${b.patient_id}`;
}

function confidenceOf(g: HCCGap): number {
  return g.confidence ?? g.confidence_score ?? 0;
}

function signalBand(c: number): { label: string; color: string; bg: string } {
  if (c >= 0.85) return { label: "Strong", color: "#065F46", bg: "#D1FAE5" };
  if (c >= 0.65) return { label: "Moderate", color: "#92400E", bg: "#FEF3C7" };
  return { label: "Weak", color: "#991B1B", bg: "#FEE2E2" };
}

function dollarsOf(g: HCCGap): number {
  return (
    g.estimated_annual_revenue_dollars ??
    g.expected_dollars ??
    g.revenue_estimate ??
    0
  );
}

function formatUSD(n: number): string {
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  });
}

function labStatusColor(s: LabEvidenceEntry["status"]): {
  bg: string;
  fg: string;
} {
  if (s === "support") return { bg: "#D1FAE5", fg: "#065F46" };
  if (s === "borderline") return { bg: "#FEF3C7", fg: "#92400E" };
  return { bg: "#FEE2E2", fg: "#991B1B" };
}

function hccLabel(g: HCCGap): string {
  return `HCC ${g.hcc_code ?? g.hcc ?? "—"}`;
}

// ---------- Component ----------

export default function MDTodayPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [meatChecked, setMeatChecked] = useState<Record<string, boolean>>({});

  const { data, isLoading, isError, refetch } = useQuery<MDTodayResponse>({
    queryKey: ["md-today"],
    queryFn: async () => {
      const res = await api.get<MDTodayResponse>("/api/md/today", {
        params: { days: 7, limit_per_patient: 3 },
      });
      return res.data;
    },
    refetchInterval: 60_000,
    staleTime: 30_000,
  });

  const accept = useMutation({
    mutationFn: async (vars: {
      suspect_id: number;
      meat_signed: boolean;
      patient_id: number;
    }) => {
      const res = await api.post(`/api/suspects/${vars.suspect_id}/accept`, {
        meat_signed: vars.meat_signed,
      });
      return res.data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["md-today"] }),
  });

  const decline = useMutation({
    mutationFn: async (suspect_id: number) => {
      const res = await api.post(`/api/suspects/${suspect_id}/decline`, {
        reason: "MD reviewed in huddle, not currently active",
      });
      return res.data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["md-today"] }),
  });

  const markReviewed = useMutation({
    mutationFn: async (patient_id: number) => {
      const res = await api.post(`/api/md/today/reviewed/${patient_id}`);
      return res.data;
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["md-today"] }),
  });

  const briefings = useMemo(() => data?.briefings ?? [], [data]);

  // Keyboard A/D shortcuts on the currently focused card
  const [focusIdx, setFocusIdx] = useState(0);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName ?? "";
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) return;
      if (e.key === "ArrowDown" || e.key === "j") {
        setFocusIdx((i) => Math.min(i + 1, Math.max(0, briefings.length - 1)));
        e.preventDefault();
      } else if (e.key === "ArrowUp" || e.key === "k") {
        setFocusIdx((i) => Math.max(0, i - 1));
        e.preventDefault();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [briefings.length]);

  // ---------- Render ----------

  return (
    <div
      className="min-h-screen bg-slate-50 print:bg-white"
      style={{ paddingBottom: 80 }}
    >
      {/* ---- Header / summary ---- */}
      <header
        className="sticky top-0 z-10 bg-white border-b border-slate-200 shadow-sm print:static print:shadow-none"
        style={{ padding: "14px 20px" }}
      >
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1
              style={{
                fontSize: 22,
                fontWeight: 700,
                color: "#0F172A",
                margin: 0,
              }}
            >
              Today&apos;s Huddle
            </h1>
            <div style={{ fontSize: 13, color: "#64748b", marginTop: 2 }}>
              {data?.date ?? "—"} · {user?.first_name ?? "Provider"}{" "}
              {user?.last_name ?? ""}
            </div>
          </div>

          <div className="flex items-center gap-6 text-sm">
            <SummaryStat
              label="Visits"
              value={data?.summary.total_visits ?? 0}
            />
            <SummaryStat
              label="Open HCC gaps"
              value={data?.summary.total_open_hcc_gaps ?? 0}
            />
            <SummaryStat
              label="Reviewed"
              value={`${data?.summary.reviewed_count ?? 0} / ${
                data?.summary.total_visits ?? 0
              }`}
            />
            <SummaryStat
              label="Revenue at stake"
              value={
                data?.summary.total_revenue_at_stake_dollars
                  ? formatUSD(data.summary.total_revenue_at_stake_dollars)
                  : "$0"
              }
            />
            <SummaryStat
              label="Supporting labs"
              value={data?.summary.total_supporting_labs ?? 0}
            />
            <button
              type="button"
              onClick={() => window.print()}
              className="px-3 py-2 rounded-md border border-slate-300 hover:bg-slate-100 text-slate-700 font-medium print:hidden"
              aria-label="Print huddle sheet"
            >
              Print
            </button>
          </div>
        </div>

        {/* Progress bar */}
        <div
          className="mt-3 h-2 bg-slate-100 rounded-full overflow-hidden print:hidden"
          aria-hidden="true"
        >
          <div
            className="h-full bg-emerald-500 transition-all"
            style={{ width: `${data?.summary.review_progress_pct ?? 0}%` }}
          />
        </div>
      </header>

      {/* ---- Content ---- */}
      <main
        className="max-w-7xl mx-auto"
        style={{ padding: "20px" }}
        role="region"
        aria-label="Pre-visit huddle cards"
      >
        {isLoading && (
          <div className="text-slate-500" role="status">
            Loading today&apos;s huddle…
          </div>
        )}

        {isError && (
          <div
            role="alert"
            className="p-4 bg-red-50 border border-red-200 rounded text-red-800"
          >
            Failed to load huddle.{" "}
            <button
              type="button"
              onClick={() => refetch()}
              className="underline font-semibold"
            >
              Retry
            </button>
          </div>
        )}

        {!isLoading && !isError && briefings.length === 0 && (
          <div className="p-8 bg-white border border-slate-200 rounded text-center text-slate-600">
            No scheduled visits found for today.
          </div>
        )}

        <div
          className="grid gap-4"
          style={{
            gridTemplateColumns:
              "repeat(auto-fill, minmax(320px, 1fr))",
          }}
        >
          {briefings.map((b, idx) => (
            <HuddleCard
              key={b.patient_id}
              b={b}
              focused={idx === focusIdx}
              meatChecked={meatChecked[`${b.patient_id}`] ?? false}
              setMeatChecked={(v) =>
                setMeatChecked((s) => ({
                  ...s,
                  [`${b.patient_id}`]: v,
                }))
              }
              onAccept={(g) => {
                if (!g.suspect_id) return;
                accept.mutate({
                  suspect_id: g.suspect_id,
                  meat_signed:
                    meatChecked[`${b.patient_id}`] ?? false,
                  patient_id: b.patient_id,
                });
              }}
              onDecline={(g) => {
                if (!g.suspect_id) return;
                decline.mutate(g.suspect_id);
              }}
              onReviewed={() => markReviewed.mutate(b.patient_id)}
            />
          ))}
        </div>
      </main>

      <style jsx global>{`
        @media print {
          .print\\:hidden {
            display: none !important;
          }
          .print\\:static {
            position: static !important;
          }
          header {
            page-break-after: avoid;
          }
          article {
            page-break-inside: avoid;
          }
        }
      `}</style>
    </div>
  );
}

// ---------- Sub-components ----------

function SummaryStat({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="flex flex-col items-end">
      <div style={{ fontSize: 18, fontWeight: 700, color: "#0F172A" }}>
        {value}
      </div>
      <div style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase" }}>
        {label}
      </div>
    </div>
  );
}

function HuddleCard({
  b,
  focused,
  meatChecked,
  setMeatChecked,
  onAccept,
  onDecline,
  onReviewed,
}: {
  b: Briefing;
  focused: boolean;
  meatChecked: boolean;
  setMeatChecked: (v: boolean) => void;
  onAccept: (g: HCCGap) => void;
  onDecline: (g: HCCGap) => void;
  onReviewed: () => void;
}) {
  const gaps = gapsOf(b);
  return (
    <article
      tabIndex={0}
      style={{
        background: "#fff",
        border: `1px solid ${focused ? "#0EA5E9" : "#e2e8f0"}`,
        outline: focused ? "2px solid #0EA5E9" : "none",
        outlineOffset: -2,
        borderRadius: 12,
        padding: 16,
        boxShadow: "0 1px 3px rgba(15,23,42,0.05)",
        opacity: b.reviewed ? 0.7 : 1,
      }}
      aria-label={`Huddle card for ${nameOf(b)}`}
    >
      {/* Patient header */}
      <div className="flex items-start justify-between gap-2">
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: "#0F172A" }}>
            {nameOf(b)}
          </div>
          <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>
            {b.age ? `${b.age}y` : ""} {b.sex ? `· ${b.sex}` : ""}{" "}
            {b.mrn ? `· MRN ${b.mrn}` : ""}
          </div>
          {b.visit_time && (
            <div style={{ fontSize: 12, color: "#0F172A", marginTop: 4, fontWeight: 600 }}>
              {b.visit_time}
              {b.reason ? ` · ${b.reason}` : ""}
            </div>
          )}
        </div>
        {b.reviewed ? (
          <span
            style={{
              fontSize: 11,
              fontWeight: 700,
              background: "#D1FAE5",
              color: "#065F46",
              padding: "3px 8px",
              borderRadius: 999,
            }}
          >
            Reviewed
          </span>
        ) : (
          <button
            type="button"
            onClick={onReviewed}
            className="text-xs px-2 py-1 rounded border border-slate-300 hover:bg-slate-100"
            aria-label={`Mark ${nameOf(b)} reviewed`}
          >
            Mark reviewed
          </button>
        )}
      </div>

      {/* MEAT checkbox */}
      <label
        className="flex items-center gap-2 mt-3 mb-2 text-sm cursor-pointer print:hidden"
        style={{ color: "#0F172A" }}
      >
        <input
          type="checkbox"
          checked={meatChecked}
          onChange={(e) => setMeatChecked(e.target.checked)}
          aria-label="I documented MEAT in today's note"
          style={{ width: 18, height: 18 }}
        />
        <span>MEAT documented in today&apos;s note</span>
      </label>

      {/* HCC gap list */}
      {gaps.length === 0 ? (
        <div className="text-sm text-slate-500 mt-2">No open HCC gaps.</div>
      ) : (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {gaps.map((g, i) => {
            const c = confidenceOf(g);
            const sig = signalBand(c);
            return (
              <li
                key={(g.suspect_id ?? i) + "-" + (g.hcc_code ?? "")}
                style={{
                  borderTop: i === 0 ? "1px solid #f1f5f9" : "1px solid #f1f5f9",
                  paddingTop: 10,
                  paddingBottom: 10,
                  display: "flex",
                  alignItems: "flex-start",
                  justifyContent: "space-between",
                  gap: 10,
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="flex items-center gap-2 flex-wrap">
                    <span
                      style={{
                        fontSize: 11,
                        fontWeight: 700,
                        background: "#EFF6FF",
                        color: "#1D4ED8",
                        padding: "2px 6px",
                        borderRadius: 4,
                      }}
                    >
                      {hccLabel(g)}
                    </span>
                    <span
                      style={{
                        fontSize: 10,
                        fontWeight: 700,
                        background: sig.bg,
                        color: sig.color,
                        padding: "2px 6px",
                        borderRadius: 4,
                      }}
                      title={`Internal signal score: ${(c * 100).toFixed(0)}%`}
                    >
                      {sig.label}
                    </span>
                    {dollarsOf(g) > 0 && (
                      <span
                        style={{
                          fontSize: 12,
                          fontWeight: 700,
                          color: "#065F46",
                          background: "#D1FAE5",
                          padding: "2px 8px",
                          borderRadius: 6,
                          fontVariantNumeric: "tabular-nums",
                        }}
                        title={`Estimated annual revenue at the V28 base rate (RAF coefficient ${g.raf_coefficient ?? "—"})`}
                      >
                        {formatUSD(dollarsOf(g))}/yr
                      </span>
                    )}
                  </div>
                  <div
                    style={{
                      fontSize: 13,
                      color: "#0F172A",
                      marginTop: 3,
                      lineHeight: 1.35,
                    }}
                  >
                    {g.description ?? g.display ?? ""}
                  </div>
                  {/* Inline lab evidence — labs that support this HCC. */}
                  {g.lab_evidence && (
                    <ul
                      style={{
                        listStyle: "none",
                        padding: 0,
                        margin: "6px 0 0",
                        display: "flex",
                        flexWrap: "wrap",
                        gap: 4,
                      }}
                      aria-label="Supporting lab values"
                    >
                      {[
                        ...(g.lab_evidence.supporting ?? []),
                        ...(g.lab_evidence.borderline ?? []),
                        ...(g.lab_evidence.contradictory ?? []),
                      ]
                        .slice(0, 4)
                        .map((lab, li) => {
                          const c = labStatusColor(lab.status);
                          return (
                            <li
                              key={`${lab.loinc}-${li}`}
                              title={`${lab.label} ${lab.value} ${lab.units} on ${lab.date?.slice(0, 10) ?? "?"} (ref ${lab.reference_range || "—"})`}
                              style={{
                                fontSize: 10,
                                fontWeight: 600,
                                background: c.bg,
                                color: c.fg,
                                padding: "2px 6px",
                                borderRadius: 4,
                                fontVariantNumeric: "tabular-nums",
                              }}
                            >
                              {lab.label.replace(/Hemoglobin /i, "")}
                              {" "}
                              {lab.value}
                              {lab.units}
                            </li>
                          );
                        })}
                    </ul>
                  )}
                </div>

                <div className="flex flex-col gap-1 print:hidden">
                  <button
                    type="button"
                    onClick={() => onAccept(g)}
                    disabled={!g.suspect_id}
                    style={{
                      minWidth: 64,
                      minHeight: 32,
                      borderRadius: 6,
                      border: "1px solid #10B981",
                      background: "#10B981",
                      color: "#fff",
                      fontSize: 12,
                      fontWeight: 700,
                      cursor: g.suspect_id ? "pointer" : "not-allowed",
                      opacity: g.suspect_id ? 1 : 0.4,
                    }}
                    aria-label={`Accept ${hccLabel(g)} for ${nameOf(b)}`}
                  >
                    Accept
                  </button>
                  <button
                    type="button"
                    onClick={() => onDecline(g)}
                    disabled={!g.suspect_id}
                    style={{
                      minWidth: 64,
                      minHeight: 32,
                      borderRadius: 6,
                      border: "1px solid #cbd5e1",
                      background: "#fff",
                      color: "#475569",
                      fontSize: 12,
                      fontWeight: 600,
                      cursor: g.suspect_id ? "pointer" : "not-allowed",
                      opacity: g.suspect_id ? 1 : 0.4,
                    }}
                    aria-label={`Decline ${hccLabel(g)} for ${nameOf(b)}`}
                  >
                    Decline
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </article>
  );
}
