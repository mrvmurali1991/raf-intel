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
 *
 * Design language matches the rest of the providers page (slate / blue /
 * emerald palette, inline styles, no Tailwind dependency).
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
// Design tokens (mirrors providers page)
// ---------------------------------------------------------------------------
const T = {
  white: "#FFFFFF",
  slate900: "#0F172A",
  slate700: "#334155",
  slate600: "#475569",
  slate500: "#64748B",
  slate400: "#64748B",
  slate300: "#CBD5E1",
  slate200: "#E2E8F0",
  slate100: "#F1F5F9",
  slate50: "#F8FAFC",
  blue700: "#1D4ED8",
  blue600: "#2563EB",
  blue100: "#DBEAFE",
  blue50: "#EFF6FF",
  emerald700: "#065F46",
  emerald600: "#059669",
  emerald100: "#D1FAE5",
  emerald50: "#ECFDF5",
  amber700: "#92400E",
  amber600: "#D97706",
  amber100: "#FEF3C7",
  amber50: "#FFFBEB",
  violet700: "#5B21B6",
  violet100: "#EDE9FE",
  violet50: "#F5F3FF",
};

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
// Status palette
// ---------------------------------------------------------------------------

function statusStyle(status: PreVisitHccStatus): {
  bg: string;
  fg: string;
  label: string;
} {
  switch (status) {
    case "suspect":
      return { bg: T.blue100, fg: T.blue700, label: "Suspect" };
    case "recapture":
      return { bg: T.amber100, fg: T.amber700, label: "Recapture" };
    case "meat_weak":
      return { bg: T.violet100, fg: T.violet700, label: "MEAT gap" };
    default:
      return { bg: T.slate100, fg: T.slate700, label: status };
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
    <div
      style={{
        background: T.white,
        border: `1px solid ${T.slate200}`,
        borderRadius: 14,
        padding: 20,
      }}
    >
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
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
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
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        marginBottom: 16,
      }}
      className="pvb-no-print"
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: 10,
            background: T.blue50,
            color: T.blue600,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Calendar size={18} />
        </div>
        <div>
          <div
            style={{
              fontSize: 15,
              fontWeight: 700,
              color: T.slate900,
              lineHeight: 1.2,
            }}
          >
            Upcoming visits (next {days} day{days !== 1 ? "s" : ""})
          </div>
          <div style={{ fontSize: 12, color: T.slate500, marginTop: 2 }}>
            Top HCC gaps to address during each huddle
          </div>
        </div>
      </div>
      <div
        style={{
          padding: "5px 10px",
          background: T.slate100,
          color: T.slate700,
          borderRadius: 999,
          fontSize: 12,
          fontWeight: 600,
        }}
      >
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
    // setTimeout lets the class apply before the print dialog snapshots the DOM
    setTimeout(() => {
      window.print();
      ref.current?.classList.remove("pvb-print-target");
    }, 50);
  }

  return (
    <div
      ref={ref}
      style={{
        background: T.white,
        border: `1px solid ${T.slate200}`,
        borderRadius: 12,
        padding: 16,
      }}
    >
      {/* Patient + visit row */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 12,
          marginBottom: 14,
          paddingBottom: 14,
          borderBottom: `1px solid ${T.slate100}`,
        }}
      >
        <div style={{ minWidth: 0, flex: 1 }}>
          <div
            style={{
              fontSize: 16,
              fontWeight: 700,
              color: T.slate900,
              marginBottom: 4,
            }}
          >
            {briefing.patient_name}
          </div>
          <div
            style={{
              fontSize: 12,
              color: T.slate500,
              display: "flex",
              flexWrap: "wrap",
              gap: 10,
            }}
          >
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
        <div style={{ textAlign: "right", flexShrink: 0 }}>
          <div
            style={{
              fontSize: 13,
              fontWeight: 600,
              color: T.blue700,
              marginBottom: 2,
            }}
          >
            {formatVisitDate(briefing.visit_date, briefing.visit_time ?? "")}
          </div>
          {briefing.encounter_reason && (
            <div
              style={{
                fontSize: 12,
                color: T.slate600,
                fontStyle: "italic",
                maxWidth: 220,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
              title={briefing.encounter_reason}
            >
              CC: {briefing.encounter_reason}
            </div>
          )}
        </div>
      </div>

      {/* Top HCCs */}
      {briefing.top_hccs.length === 0 ? (
        <div
          style={{
            fontSize: 13,
            color: T.slate500,
            padding: "12px 0",
            textAlign: "center",
            fontStyle: "italic",
          }}
        >
          No open HCC gaps for this patient — code the visit as documented.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {briefing.top_hccs.map((h, i) => (
            <HccRow key={`${h.hcc_code}-${i}`} hcc={h} />
          ))}
        </div>
      )}

      {/* Footer: total + print */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginTop: 14,
          paddingTop: 14,
          borderTop: `1px solid ${T.slate100}`,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <Sparkles size={14} color={T.emerald600} />
          <span style={{ fontSize: 12, color: T.slate600 }}>
            Total potential
          </span>
          <span
            style={{
              fontSize: 14,
              fontWeight: 700,
              color: T.emerald700,
              marginLeft: 4,
            }}
          >
            {formatUSD(briefing.total_potential_dollars)}
          </span>
        </div>
        <button
          type="button"
          onClick={handlePrint}
          className="pvb-no-print"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "6px 12px",
            background: T.white,
            color: T.slate700,
            border: `1px solid ${T.slate300}`,
            borderRadius: 8,
            fontSize: 12,
            fontWeight: 600,
            cursor: "pointer",
          }}
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
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "10px 12px",
        background: T.slate50,
        borderRadius: 10,
        border: `1px solid ${T.slate100}`,
      }}
    >
      {/* Code chip */}
      <div
        style={{
          padding: "3px 8px",
          background: T.slate900,
          color: T.white,
          borderRadius: 6,
          fontSize: 11,
          fontWeight: 700,
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          flexShrink: 0,
        }}
      >
        HCC {hcc.hcc_code}
      </div>

      {/* Label + evidence */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: T.slate900,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
          title={hcc.hcc_label}
        >
          {hcc.hcc_label}
        </div>
        <div
          style={{
            fontSize: 11,
            color: T.slate500,
            display: "flex",
            alignItems: "center",
            gap: 4,
            marginTop: 2,
          }}
        >
          <FileText size={10} />
          <span
            style={{
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
            title={hcc.evidence_snippet ?? undefined}
          >
            {hcc.evidence_snippet}
          </span>
        </div>
      </div>

      {/* Status pill */}
      <div
        style={{
          padding: "3px 8px",
          background: sty.bg,
          color: sty.fg,
          borderRadius: 999,
          fontSize: 10,
          fontWeight: 700,
          textTransform: "uppercase",
          letterSpacing: "0.04em",
          flexShrink: 0,
        }}
      >
        {sty.label}
      </div>

      {/* $ pill */}
      <div
        style={{
          padding: "3px 8px",
          background: T.emerald50,
          color: T.emerald700,
          borderRadius: 999,
          fontSize: 11,
          fontWeight: 700,
          flexShrink: 0,
          minWidth: 50,
          textAlign: "center",
        }}
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
    <div
      style={{
        padding: "32px 20px",
        textAlign: "center",
        background: T.slate50,
        borderRadius: 12,
        border: `1px dashed ${T.slate200}`,
      }}
    >
      <Calendar
        size={28}
        color={T.slate400}
        style={{ marginBottom: 10 }}
      />
      <div
        style={{
          fontSize: 14,
          fontWeight: 600,
          color: T.slate700,
          marginBottom: 4,
        }}
      >
        No upcoming visits in next {days} day{days !== 1 ? "s" : ""}
      </div>
      <div style={{ fontSize: 12, color: T.slate500, lineHeight: 1.5 }}>
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
    <div
      style={{
        padding: 32,
        textAlign: "center",
        color: T.slate500,
        fontSize: 13,
      }}
    >
      Loading upcoming visits…
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div
      style={{
        padding: 20,
        background: T.amber50,
        border: `1px solid ${T.amber100}`,
        borderRadius: 12,
        display: "flex",
        gap: 10,
        alignItems: "flex-start",
      }}
    >
      <AlertCircle size={16} color={T.amber600} style={{ flexShrink: 0 }} />
      <div>
        <div
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: T.amber700,
            marginBottom: 2,
          }}
        >
          Pre-visit briefing unavailable
        </div>
        <div style={{ fontSize: 12, color: T.slate600 }}>{message}</div>
      </div>
    </div>
  );
}
