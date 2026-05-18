"use client";

/**
 * MD Today — pre-visit huddle UI (polished demo-grade).
 *
 * Features:
 *  - Premium empty state with next-visit date computation
 *  - Loading skeleton mirroring the card layout (shimmer-pulse)
 *  - Card fade-in + translate-up animations, staggered 80ms/card (CSS keyframes)
 *  - Accept/Decline tactile press (scale-down on :active)
 *  - Reviewed state: 70% opacity + green check overlay in 200ms
 *  - Print-sheet upgrade: clinic logo, per-patient page-break, no action buttons
 *  - Keyboard-shortcuts sticky footer
 *  - Revenue tile animated glow when total > $50k
 *  - WCAG 2.2 AA: prefers-reduced-motion, focus indicators, aria-live toasts
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
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
  next_visit_date?: string;
  summary: {
    total_visits: number;
    total_open_hcc_gaps: number;
    reviewed_count: number;
    review_progress_pct: number;
    total_revenue_at_stake_dollars?: number;
    total_supporting_labs?: number;
  };
  tenant_branding?: {
    clinic_name?: string;
    logo_url?: string;
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

/** Derive the soonest future visit date from briefing list or server hint */
function nextVisitDate(data: MDTodayResponse | undefined): string | null {
  if (data?.next_visit_date) return data.next_visit_date;
  if (!data?.briefings?.length) return null;
  const dates = data.briefings
    .map((b) => b.visit_date)
    .filter((d): d is string => Boolean(d))
    .sort();
  return dates[0] ?? null;
}

function formatDateFriendly(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      weekday: "long",
      month: "long",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

// ---------- Toast ----------

interface Toast {
  id: number;
  message: string;
  type: "success" | "error";
}

// ---------- Main Component ----------

export default function MDTodayPage() {
  const { user } = useAuth();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [meatChecked, setMeatChecked] = useState<Record<string, boolean>>({});
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastCounter = useRef(0);

  const pushToast = useCallback((message: string, type: Toast["type"] = "success") => {
    const id = ++toastCounter.current;
    setToasts((t) => [...t, { id, message, type }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3500);
  }, []);

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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["md-today"] });
      pushToast("HCC gap accepted", "success");
    },
    onError: () => pushToast("Failed to accept — please retry", "error"),
  });

  const decline = useMutation({
    mutationFn: async (suspect_id: number) => {
      const res = await api.post(`/api/suspects/${suspect_id}/decline`, {
        reason: "MD reviewed in huddle, not currently active",
      });
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["md-today"] });
      pushToast("HCC gap declined", "success");
    },
    onError: () => pushToast("Failed to decline — please retry", "error"),
  });

  const markReviewed = useMutation({
    mutationFn: async (patient_id: number) => {
      const res = await api.post(`/api/md/today/reviewed/${patient_id}`);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["md-today"] });
      pushToast("Patient marked as reviewed", "success");
    },
  });

  const briefings = useMemo(() => data?.briefings ?? [], [data]);

  // Keyboard navigation
  const [focusIdx, setFocusIdx] = useState(0);
  const [showHelp, setShowHelp] = useState(false);

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
      } else if (e.key === "?" ) {
        setShowHelp((v) => !v);
      } else if (e.key === "a" || e.key === "A") {
        const b = briefings[focusIdx];
        if (b) {
          const gaps = gapsOf(b);
          const firstGap = gaps.find((g) => g.suspect_id);
          if (firstGap?.suspect_id) {
            accept.mutate({
              suspect_id: firstGap.suspect_id,
              meat_signed: meatChecked[`${b.patient_id}`] ?? false,
              patient_id: b.patient_id,
            });
          }
        }
      } else if (e.key === "d" || e.key === "D") {
        const b = briefings[focusIdx];
        if (b) {
          const gaps = gapsOf(b);
          const firstGap = gaps.find((g) => g.suspect_id);
          if (firstGap?.suspect_id) decline.mutate(firstGap.suspect_id);
        }
      } else if (e.key === "r" || e.key === "R") {
        const b = briefings[focusIdx];
        if (b) markReviewed.mutate(b.patient_id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [briefings, focusIdx, meatChecked, accept, decline, markReviewed]);

  const revenueAtStake = data?.summary.total_revenue_at_stake_dollars ?? 0;
  const highRevenue = revenueAtStake > 50_000;
  const clinicName = data?.tenant_branding?.clinic_name ?? "Clinic";
  const logoUrl = data?.tenant_branding?.logo_url;

  // ---------- Render ----------
  return (
    <div
      className="min-h-screen bg-slate-50 print:bg-white"
      style={{ paddingBottom: 88 }}
    >
      {/* ===== Global keyframe styles ===== */}
      <style>{`
        @keyframes huddle-fade-up {
          from { opacity: 0; transform: translateY(12px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes huddle-shimmer {
          0%   { background-position: -400px 0; }
          100% { background-position: 400px 0; }
        }
        @keyframes huddle-reviewed {
          from { opacity: 1; }
          to   { opacity: 0.7; }
        }
        @keyframes huddle-revenue-glow {
          0%, 100% { box-shadow: 0 0 0 0 rgba(16,185,129,0); }
          50%       { box-shadow: 0 0 0 8px rgba(16,185,129,0.18), 0 0 24px rgba(16,185,129,0.12); }
        }
        @keyframes huddle-check-pop {
          0%   { transform: scale(0) rotate(-20deg); opacity: 0; }
          70%  { transform: scale(1.15) rotate(4deg); opacity: 1; }
          100% { transform: scale(1) rotate(0); opacity: 1; }
        }
        @keyframes toast-in {
          from { opacity: 0; transform: translateY(8px) scale(0.97); }
          to   { opacity: 1; transform: translateY(0) scale(1); }
        }

        /* Card entry animation */
        .huddle-card-anim {
          animation: huddle-fade-up 0.32s ease both;
        }

        /* Shimmer skeleton bar */
        .huddle-shimmer-bar {
          background: linear-gradient(90deg, #e2e8f0 25%, #f1f5f9 50%, #e2e8f0 75%);
          background-size: 800px 100%;
          animation: huddle-shimmer 1.4s infinite linear;
          border-radius: 6px;
        }

        /* Revenue glow */
        .huddle-revenue-glow {
          animation: huddle-revenue-glow 2.4s ease-in-out infinite;
        }

        /* Green check overlay pop */
        .huddle-check-overlay {
          animation: huddle-check-pop 0.2s ease both;
        }

        /* Toast */
        .huddle-toast {
          animation: toast-in 0.22s ease both;
        }

        /* Button tactile press */
        .huddle-btn-press:active {
          transform: scale(0.97);
        }

        /* Focus ring */
        .huddle-focus:focus-visible {
          outline: 3px solid #0EA5E9;
          outline-offset: 2px;
        }

        /* Respect reduced-motion */
        @media (prefers-reduced-motion: reduce) {
          .huddle-card-anim,
          .huddle-shimmer-bar,
          .huddle-revenue-glow,
          .huddle-check-overlay,
          .huddle-toast,
          .huddle-btn-press:active {
            animation: none !important;
            transition: none !important;
            transform: none !important;
          }
        }

        /* ====== Print styles ====== */
        @media print {
          .print-hide { display: none !important; }
          .print-show { display: block !important; }
          body { background: white !important; color: black !important; }
          .print-page-break { page-break-after: always; }
          .huddle-card-anim { animation: none !important; }
          header { page-break-after: avoid; position: static !important; box-shadow: none !important; }
          article { page-break-inside: avoid; }
          .print-coder-footer { display: flex !important; }
        }
      `}</style>

      {/* ===== Print-only header ===== */}
      <div
        className="hidden print-show"
        style={{
          display: "none",
          padding: "8px 20px 12px",
          borderBottom: "2px solid #0F172A",
          marginBottom: 12,
          alignItems: "center",
          justifyContent: "space-between",
        }}
        aria-hidden="true"
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          {logoUrl ? (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img src={logoUrl} alt={clinicName} style={{ height: 36 }} />
          ) : (
            <span style={{ fontWeight: 800, fontSize: 18, color: "#0F172A" }}>
              {clinicName}
            </span>
          )}
        </div>
        <div style={{ textAlign: "right", fontSize: 12, color: "#475569" }}>
          <div style={{ fontWeight: 700 }}>Pre-Visit Huddle Sheet</div>
          <div>{data?.date ?? new Date().toISOString().slice(0, 10)}</div>
          <div>
            {user?.first_name ?? "Provider"} {user?.last_name ?? ""}
          </div>
        </div>
      </div>

      {/* ===== Header / summary ===== */}
      <header
        className="sticky top-0 z-10 bg-white border-b border-slate-200 shadow-sm print-hide"
        style={{ padding: "14px 20px" }}
      >
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div>
            <h1
              style={{ fontSize: 22, fontWeight: 700, color: "#0F172A", margin: 0 }}
            >
              Today&apos;s Huddle
            </h1>
            <div style={{ fontSize: 13, color: "#64748b", marginTop: 2 }}>
              {data?.date ?? "—"} · {user?.first_name ?? "Provider"}{" "}
              {user?.last_name ?? ""}
            </div>
          </div>

          <div className="flex items-center gap-4 text-sm flex-wrap">
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
              value={revenueAtStake ? formatUSD(revenueAtStake) : "$0"}
              glow={highRevenue}
            />
            <SummaryStat
              label="Supporting labs"
              value={data?.summary.total_supporting_labs ?? 0}
            />
            <button
              type="button"
              onClick={() => window.print()}
              className="huddle-btn-press huddle-focus px-3 py-2 rounded-md border border-slate-300 hover:bg-slate-100 text-slate-700 font-medium print-hide"
              style={{ transition: "background 0.15s" }}
              aria-label="Print huddle sheet"
            >
              Print
            </button>
          </div>
        </div>

        {/* Progress bar */}
        <div
          className="mt-3 h-2 bg-slate-100 rounded-full overflow-hidden print-hide"
          role="progressbar"
          aria-valuenow={data?.summary.review_progress_pct ?? 0}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${data?.summary.review_progress_pct ?? 0}% of patients reviewed`}
        >
          <div
            className="h-full bg-emerald-500"
            style={{
              width: `${data?.summary.review_progress_pct ?? 0}%`,
              transition: "width 0.4s ease",
            }}
          />
        </div>
      </header>

      {/* ===== Main content ===== */}
      <main
        className="max-w-7xl mx-auto"
        style={{ padding: "20px" }}
        role="region"
        aria-label="Pre-visit huddle cards"
      >
        {/* Loading skeleton */}
        {isLoading && <HuddleSkeleton />}

        {/* Error state */}
        {isError && (
          <div
            role="alert"
            className="p-4 bg-red-50 border border-red-200 rounded-xl text-red-800"
          >
            Failed to load huddle.{" "}
            <button
              type="button"
              onClick={() => refetch()}
              className="underline font-semibold huddle-focus"
            >
              Retry
            </button>
          </div>
        )}

        {/* Empty state */}
        {!isLoading && !isError && briefings.length === 0 && (
          <EmptyState data={data} router={router} />
        )}

        {/* Cards grid */}
        {!isLoading && briefings.length > 0 && (
          <div
            className="grid gap-4"
            style={{ gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))" }}
          >
            {briefings.map((b, idx) => (
              <HuddleCard
                key={b.patient_id}
                b={b}
                cardIndex={idx}
                focused={idx === focusIdx}
                meatChecked={meatChecked[`${b.patient_id}`] ?? false}
                setMeatChecked={(v) =>
                  setMeatChecked((s) => ({ ...s, [`${b.patient_id}`]: v }))
                }
                onAccept={(g) => {
                  if (!g.suspect_id) return;
                  accept.mutate({
                    suspect_id: g.suspect_id,
                    meat_signed: meatChecked[`${b.patient_id}`] ?? false,
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
        )}
      </main>

      {/* ===== Keyboard shortcuts sticky footer ===== */}
      <ShortcutsBanner showHelp={showHelp} onDismissHelp={() => setShowHelp(false)} />

      {/* ===== Toast region ===== */}
      <div
        aria-live="polite"
        aria-atomic="false"
        role="status"
        className="print-hide"
        style={{
          position: "fixed",
          bottom: 96,
          right: 20,
          zIndex: 50,
          display: "flex",
          flexDirection: "column",
          gap: 8,
          pointerEvents: "none",
        }}
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            className="huddle-toast"
            style={{
              background: t.type === "success" ? "#065F46" : "#991B1B",
              color: "#fff",
              padding: "10px 16px",
              borderRadius: 10,
              fontSize: 13,
              fontWeight: 600,
              boxShadow: "0 4px 12px rgba(0,0,0,0.18)",
              maxWidth: 280,
            }}
          >
            {t.message}
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------- Empty state ----------

function EmptyState({
  data,
  router,
}: {
  data: MDTodayResponse | undefined;
  router: ReturnType<typeof useRouter>;
}) {
  const nd = nextVisitDate(data);
  return (
    <div
      className="huddle-card-anim"
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "72px 24px",
        background: "#fff",
        border: "1px solid #e2e8f0",
        borderRadius: 16,
        textAlign: "center",
        gap: 12,
      }}
      data-testid="empty-state"
    >
      {/* Calendar icon */}
      <div
        style={{
          width: 72,
          height: 72,
          background: "#F0F9FF",
          borderRadius: "50%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          marginBottom: 4,
        }}
        aria-hidden="true"
      >
        <svg
          width="36"
          height="36"
          viewBox="0 0 24 24"
          fill="none"
          stroke="#0EA5E9"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
          <line x1="16" y1="2" x2="16" y2="6" />
          <line x1="8" y1="2" x2="8" y2="6" />
          <line x1="3" y1="10" x2="21" y2="10" />
        </svg>
      </div>

      <h2 style={{ fontSize: 20, fontWeight: 700, color: "#0F172A", margin: 0 }}>
        No visits scheduled today
      </h2>

      {nd ? (
        <p style={{ fontSize: 14, color: "#64748b", margin: 0 }}>
          Your next visit is on{" "}
          <strong style={{ color: "#0F172A" }}>{formatDateFriendly(nd)}</strong>
        </p>
      ) : (
        <p style={{ fontSize: 14, color: "#64748b", margin: 0 }}>
          Check back tomorrow — your schedule will appear here.
        </p>
      )}

      <button
        type="button"
        onClick={() => router.push("/worklist")}
        className="huddle-btn-press huddle-focus"
        style={{
          marginTop: 8,
          padding: "10px 22px",
          borderRadius: 8,
          border: "1px solid #0EA5E9",
          background: "#F0F9FF",
          color: "#0369A1",
          fontSize: 14,
          fontWeight: 600,
          cursor: "pointer",
          transition: "background 0.15s",
        }}
        aria-label="Review last visit's notes in worklist"
      >
        Review last visit&apos;s notes
      </button>
    </div>
  );
}

// ---------- Loading skeleton ----------

function HuddleSkeleton() {
  return (
    <div
      className="grid gap-4"
      style={{ gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))" }}
      role="status"
      aria-label="Loading huddle cards"
      data-testid="huddle-skeleton"
    >
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          style={{
            background: "#fff",
            border: "1px solid #e2e8f0",
            borderRadius: 12,
            padding: 16,
            boxShadow: "0 1px 3px rgba(15,23,42,0.05)",
          }}
          aria-hidden="true"
        >
          {/* Patient header skeleton */}
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
            <div style={{ flex: 1 }}>
              <div
                className="huddle-shimmer-bar"
                style={{ height: 18, width: "60%", marginBottom: 8 }}
              />
              <div
                className="huddle-shimmer-bar"
                style={{ height: 12, width: "40%" }}
              />
            </div>
            <div
              className="huddle-shimmer-bar"
              style={{ height: 26, width: 80, borderRadius: 999 }}
            />
          </div>

          {/* MEAT checkbox skeleton */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
            <div
              className="huddle-shimmer-bar"
              style={{ height: 18, width: 18, borderRadius: 4 }}
            />
            <div
              className="huddle-shimmer-bar"
              style={{ height: 14, width: "55%" }}
            />
          </div>

          {/* Gap rows skeleton */}
          {[0, 1, 2].map((j) => (
            <div
              key={j}
              style={{
                borderTop: "1px solid #f1f5f9",
                paddingTop: 10,
                paddingBottom: 10,
                display: "flex",
                justifyContent: "space-between",
                gap: 10,
              }}
            >
              <div style={{ flex: 1 }}>
                <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
                  <div
                    className="huddle-shimmer-bar"
                    style={{ height: 18, width: 56, borderRadius: 4 }}
                  />
                  <div
                    className="huddle-shimmer-bar"
                    style={{ height: 18, width: 60, borderRadius: 4 }}
                  />
                </div>
                <div
                  className="huddle-shimmer-bar"
                  style={{ height: 13, width: "80%" }}
                />
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <div
                  className="huddle-shimmer-bar"
                  style={{ height: 32, width: 64, borderRadius: 6 }}
                />
                <div
                  className="huddle-shimmer-bar"
                  style={{ height: 32, width: 64, borderRadius: 6 }}
                />
              </div>
            </div>
          ))}
        </div>
      ))}
      <span className="sr-only">Loading today&apos;s huddle, please wait…</span>
    </div>
  );
}

// ---------- Summary stat tile ----------

function SummaryStat({
  label,
  value,
  glow,
}: {
  label: string;
  value: string | number;
  glow?: boolean;
}) {
  return (
    <div
      className={`flex flex-col items-end${glow ? " huddle-revenue-glow" : ""}`}
      style={{
        borderRadius: 8,
        padding: glow ? "4px 8px" : undefined,
        transition: "box-shadow 0.3s",
      }}
    >
      <div style={{ fontSize: 18, fontWeight: 700, color: "#0F172A" }}>
        {value}
      </div>
      <div style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase" }}>
        {label}
      </div>
    </div>
  );
}

// ---------- Huddle card ----------

function HuddleCard({
  b,
  cardIndex,
  focused,
  meatChecked,
  setMeatChecked,
  onAccept,
  onDecline,
  onReviewed,
}: {
  b: Briefing;
  cardIndex: number;
  focused: boolean;
  meatChecked: boolean;
  setMeatChecked: (v: boolean) => void;
  onAccept: (g: HCCGap) => void;
  onDecline: (g: HCCGap) => void;
  onReviewed: () => void;
}) {
  const gaps = gapsOf(b);
  const patientName = nameOf(b);

  return (
    <article
      tabIndex={0}
      className="huddle-card-anim huddle-focus print-page-break"
      style={{
        background: "#fff",
        border: `1px solid ${focused ? "#0EA5E9" : "#e2e8f0"}`,
        outline: focused ? "2px solid #0EA5E9" : "none",
        outlineOffset: -2,
        borderRadius: 12,
        padding: 16,
        boxShadow: "0 1px 3px rgba(15,23,42,0.05)",
        position: "relative",
        opacity: b.reviewed ? 0.7 : 1,
        transition: "opacity 0.2s ease",
        animationDelay: `${cardIndex * 80}ms`,
      }}
      aria-label={`Huddle card for ${patientName}`}
    >
      {/* Reviewed green check overlay */}
      {b.reviewed && (
        <div
          className="huddle-check-overlay"
          style={{
            position: "absolute",
            top: 12,
            right: 12,
            width: 28,
            height: 28,
            borderRadius: "50%",
            background: "#10B981",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
          aria-hidden="true"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
            <polyline
              points="2,7 6,11 12,3"
              stroke="#fff"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>
      )}

      {/* Print-only patient header */}
      <div
        className="hidden print-show"
        style={{ display: "none", marginBottom: 8, fontSize: 11, color: "#64748b" }}
      >
        Patient Huddle — {patientName}
      </div>

      {/* Patient header */}
      <div className="flex items-start justify-between gap-2">
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: "#0F172A" }}>
            {patientName}
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
              marginRight: b.reviewed ? 32 : 0,
            }}
          >
            Reviewed
          </span>
        ) : (
          <button
            type="button"
            onClick={onReviewed}
            className="huddle-btn-press huddle-focus print-hide text-xs px-2 py-1 rounded border border-slate-300 hover:bg-slate-100"
            style={{ transition: "background 0.15s" }}
            aria-label={`Mark ${patientName} reviewed`}
          >
            Mark reviewed
          </button>
        )}
      </div>

      {/* MEAT checkbox — screen only */}
      <label
        className="flex items-center gap-2 mt-3 mb-2 text-sm cursor-pointer print-hide"
        style={{ color: "#0F172A" }}
      >
        <input
          type="checkbox"
          checked={meatChecked}
          onChange={(e) => setMeatChecked(e.target.checked)}
          aria-label="I documented MEAT in today's note"
          className="huddle-focus"
          style={{ width: 18, height: 18, cursor: "pointer" }}
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
                  borderTop: "1px solid #f1f5f9",
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
                        title={`Estimated annual revenue at V28 base rate (RAF ${g.raf_coefficient ?? "—"})`}
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

                  {/* Lab evidence chips */}
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
                          const lc = labStatusColor(lab.status);
                          return (
                            <li
                              key={`${lab.loinc}-${li}`}
                              title={`${lab.label} ${lab.value} ${lab.units} on ${
                                lab.date?.slice(0, 10) ?? "?"
                              } (ref ${lab.reference_range || "—"})`}
                              style={{
                                fontSize: 10,
                                fontWeight: 600,
                                background: lc.bg,
                                color: lc.fg,
                                padding: "2px 6px",
                                borderRadius: 4,
                                fontVariantNumeric: "tabular-nums",
                              }}
                            >
                              {lab.label.replace(/Hemoglobin /i, "")}{" "}
                              {lab.value}
                              {lab.units}
                            </li>
                          );
                        })}
                    </ul>
                  )}

                  {/* Coder-use-only footer — screen hidden, print visible */}
                  {g.suspect_id && (
                    <div
                      className="print-coder-footer"
                      style={{
                        display: "none",
                        marginTop: 6,
                        gap: 6,
                        alignItems: "center",
                        borderTop: "1px dashed #cbd5e1",
                        paddingTop: 4,
                      }}
                      aria-hidden="true"
                    >
                      <span
                        style={{
                          fontSize: 9,
                          fontWeight: 700,
                          color: "#64748b",
                          textTransform: "uppercase",
                          letterSpacing: "0.05em",
                        }}
                      >
                        Coder use only:
                      </span>
                      <span
                        style={{
                          fontSize: 9,
                          background: "#F1F5F9",
                          color: "#475569",
                          padding: "1px 5px",
                          borderRadius: 3,
                          fontFamily: "monospace",
                        }}
                      >
                        ID #{g.suspect_id}
                      </span>
                      <span
                        style={{
                          fontSize: 9,
                          background: sig.bg,
                          color: sig.color,
                          padding: "1px 5px",
                          borderRadius: 3,
                          fontWeight: 700,
                        }}
                      >
                        {sig.label} ({(c * 100).toFixed(0)}%)
                      </span>
                    </div>
                  )}
                </div>

                {/* Action buttons — screen only */}
                <div className="flex flex-col gap-1 print-hide">
                  <button
                    type="button"
                    onClick={() => onAccept(g)}
                    disabled={!g.suspect_id}
                    className="huddle-btn-press huddle-focus"
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
                      transition: "opacity 0.15s",
                    }}
                    aria-label={`Accept ${hccLabel(g)} for ${patientName}`}
                  >
                    Accept
                  </button>
                  <button
                    type="button"
                    onClick={() => onDecline(g)}
                    disabled={!g.suspect_id}
                    className="huddle-btn-press huddle-focus"
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
                      transition: "opacity 0.15s",
                    }}
                    aria-label={`Decline ${hccLabel(g)} for ${patientName}`}
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

// ---------- Keyboard shortcuts banner ----------

function ShortcutsBanner({
  showHelp,
  onDismissHelp,
}: {
  showHelp: boolean;
  onDismissHelp: () => void;
}) {
  return (
    <footer
      className="print-hide"
      style={{
        position: "fixed",
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 20,
        background: "rgba(15,23,42,0.93)",
        color: "#CBD5E1",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 20,
        padding: "10px 20px",
        fontSize: 12,
        backdropFilter: "blur(6px)",
        borderTop: "1px solid rgba(255,255,255,0.06)",
      }}
      aria-label="Keyboard shortcuts"
    >
      <ShortcutKey keys="↑↓" label="navigate" />
      <ShortcutKey keys="A" label="accept" />
      <ShortcutKey keys="D" label="decline" />
      <ShortcutKey keys="R" label="review" />
      <button
        type="button"
        onClick={onDismissHelp}
        className="huddle-focus"
        style={{
          background: "transparent",
          border: "none",
          color: "#94A3B8",
          cursor: "pointer",
          fontSize: 12,
          display: "flex",
          alignItems: "center",
          gap: 4,
          padding: "2px 4px",
        }}
        aria-label="Toggle keyboard help"
        aria-expanded={showHelp}
      >
        <kbd
          style={{
            background: "rgba(255,255,255,0.12)",
            border: "1px solid rgba(255,255,255,0.2)",
            borderRadius: 4,
            padding: "0px 5px",
            fontFamily: "monospace",
            fontSize: 11,
          }}
        >
          ?
        </kbd>{" "}
        help
      </button>
    </footer>
  );
}

function ShortcutKey({ keys, label }: { keys: string; label: string }) {
  return (
    <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
      <kbd
        style={{
          background: "rgba(255,255,255,0.12)",
          border: "1px solid rgba(255,255,255,0.2)",
          borderRadius: 4,
          padding: "1px 6px",
          fontFamily: "monospace",
          fontSize: 11,
          color: "#F1F5F9",
        }}
      >
        {keys}
      </kbd>
      <span style={{ color: "#94A3B8" }}>{label}</span>
    </span>
  );
}
