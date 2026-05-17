"use client";

/**
 * PatientHedisStrip — co-located HEDIS gap display on the patient chart.
 *
 * Renders open HEDIS quality gaps (BCS, CCS, HBD, CBP, FUM) alongside
 * HCC suspects so a PCP sees both during a single visit.  Each gap card
 * shows: measure name, last value, status, and a "Close gap" button that
 * routes to /hedis filtered to this patient.
 *
 * Usage (inside patients/[pid]/page.tsx):
 *   <PatientHedisStrip pid={pid} year={selectedYear} />
 */

import React from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { getPatientHedisGaps } from "@/lib/api";
import type { PatientHedisGap } from "@/lib/api";
import { C } from "./shared";

// ---------------------------------------------------------------------------
// Measure metadata: human-readable labels + icon colours
// ---------------------------------------------------------------------------

const MEASURE_META: Record<string, { short: string; color: string; bg: string }> = {
  BCS: { short: "Breast Cancer Screening", color: "#7C3AED", bg: "#EDE9FE" },
  CCS: { short: "Cervical Cancer Screening", color: "#BE185D", bg: "#FCE7F3" },
  HBD: { short: "A1c Control (Diabetes)", color: "#B45309", bg: "#FEF3C7" },
  CBP: { short: "Blood Pressure Control", color: "#0369A1", bg: "#E0F2FE" },
  FUM: { short: "Follow-Up (Mental Health ED)", color: "#065F46", bg: "#D1FAE5" },
};

function measureMeta(id: string) {
  return MEASURE_META[id] ?? { short: id, color: C.slate600, bg: C.slate100 };
}

// ---------------------------------------------------------------------------
// Single gap card
// ---------------------------------------------------------------------------

function GapCard({ gap, pid }: { gap: PatientHedisGap; pid: string | number }) {
  const router = useRouter();
  const meta = measureMeta(gap.measure_id);
  const isOpen = gap.status === "open";

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: "10px 14px",
        borderRadius: 10,
        border: `1px solid ${isOpen ? meta.color + "40" : C.slate200}`,
        background: isOpen ? meta.bg + "80" : C.slate100,
        minWidth: 180,
        maxWidth: 240,
        flexShrink: 0,
      }}
    >
      {/* Measure badge + name */}
      <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "2px 7px",
            borderRadius: 5,
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.04em",
            background: meta.color,
            color: "#fff",
            flexShrink: 0,
          }}
        >
          {gap.measure_id}
        </span>
        <span
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: C.slate700,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
          title={meta.short}
        >
          {meta.short}
        </span>
      </div>

      {/* Status row */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11 }}>
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: "50%",
            background: isOpen ? "#EF4444" : "#10B981",
            flexShrink: 0,
          }}
        />
        <span style={{ fontWeight: 600, color: isOpen ? "#DC2626" : "#059669" }}>
          {isOpen ? "Gap open" : "Met"}
        </span>
        {gap.last_value && (
          <span style={{ color: C.slate500, marginLeft: 4 }}>
            Last: {gap.last_value}
          </span>
        )}
      </div>

      {/* Close gap button (only for open gaps) */}
      {isOpen && (
        <button
          type="button"
          onClick={() =>
            router.push(`/hedis?patient_id=${pid}&measure=${gap.measure_id}`)
          }
          aria-label={`Close ${gap.measure_id} gap for this patient`}
          style={{
            marginTop: 2,
            padding: "5px 10px",
            borderRadius: 7,
            border: `1px solid ${meta.color}`,
            background: "transparent",
            color: meta.color,
            fontSize: 11,
            fontWeight: 700,
            cursor: "pointer",
            alignSelf: "flex-start",
            transition: "background 0.12s",
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = meta.bg;
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.background = "transparent";
          }}
        >
          Close gap
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Strip skeleton
// ---------------------------------------------------------------------------

function StripSkeleton() {
  return (
    <div style={{ display: "flex", gap: 10 }}>
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          style={{
            width: 200,
            height: 84,
            borderRadius: 10,
            background: "linear-gradient(90deg, #f1f5f9 25%, #e2e8f0 50%, #f1f5f9 75%)",
            backgroundSize: "200% 100%",
            animation: `shimmer 1.5s ${i * 120}ms infinite`,
            flexShrink: 0,
          }}
        />
      ))}
      <style>{`@keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}`}</style>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface PatientHedisStripProps {
  pid: string | number;
  year?: number;
}

export function PatientHedisStrip({ pid, year }: PatientHedisStripProps) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["patient-hedis-gaps", pid, year],
    queryFn: () => getPatientHedisGaps(pid, year),
    // Non-critical — don't block the page on error; silently skip on auth failure
    retry: 1,
  });

  // Don't render at all if there are no HEDIS gaps (all measures N/A for patient)
  if (!isLoading && !isError && (!data || data.all_gaps.length === 0)) {
    return null;
  }

  const openCount = data?.open_gaps.length ?? 0;
  const allGaps = data?.all_gaps ?? [];

  return (
    <section
      aria-label="HEDIS quality gaps"
      style={{
        marginTop: 20,
        padding: "14px 20px",
        background: C.white,
        border: `1px solid ${C.slate200}`,
        borderRadius: 12,
        boxShadow: "0 1px 3px rgba(15,23,42,0.05)",
      }}
    >
      {/* Section header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 12,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: 8,
              background: "linear-gradient(135deg, #7C3AED, #BE185D)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            {/* Star icon inline */}
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
            </svg>
          </div>
          <div>
            <span
              style={{
                fontSize: 13,
                fontWeight: 700,
                color: C.slate800,
                letterSpacing: "-0.01em",
              }}
            >
              HEDIS Quality Gaps
            </span>
            {!isLoading && (
              <span
                style={{
                  marginLeft: 8,
                  display: "inline-flex",
                  alignItems: "center",
                  padding: "2px 8px",
                  borderRadius: 999,
                  fontSize: 11,
                  fontWeight: 700,
                  background: openCount > 0 ? "#FEF3C7" : "#D1FAE5",
                  color: openCount > 0 ? "#B45309" : "#059669",
                }}
              >
                {openCount > 0 ? `${openCount} open` : "All met"}
              </span>
            )}
          </div>
        </div>
        <span style={{ fontSize: 11, color: C.slate400 }}>
          Co-located with HCC suspects — close gaps during this visit
        </span>
      </div>

      {/* Gap cards */}
      {isLoading && <StripSkeleton />}
      {isError && (
        <p style={{ fontSize: 12, color: C.slate500, margin: 0 }}>
          HEDIS gap data unavailable.
        </p>
      )}
      {!isLoading && !isError && allGaps.length > 0 && (
        <div
          style={{
            display: "flex",
            gap: 10,
            overflowX: "auto",
            paddingBottom: 4,
            scrollbarWidth: "thin" as React.CSSProperties["scrollbarWidth"],
          }}
        >
          {/* Open gaps first, then met */}
          {[...allGaps]
            .sort((a, b) => (a.status === "open" ? -1 : 1) - (b.status === "open" ? -1 : 1))
            .map((gap) => (
              <GapCard key={gap.measure_id} gap={gap} pid={pid} />
            ))}
        </div>
      )}
    </section>
  );
}
