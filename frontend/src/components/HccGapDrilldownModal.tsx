"use client";

/**
 * HccGapDrilldownModal — patient-level gap drilldown for the per-HCC table
 * on the providers detail drawer.
 *
 * Opens when a coder clicks a row in the per-HCC performance table. Shows
 * the panel patients who are MISSING that HCC (open-suspect ∪ prior-year-
 * coded-but-not-current-year) with chart context to help the user close
 * the gap.
 */

import React, { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  X,
  Search,
  ExternalLink,
  AlertCircle,
  History,
  Sparkles,
  User,
} from "lucide-react";

import {
  getProviderHccGapPatients,
  type HccGapPatient,
  type HccGapPatientsResponse,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Local design tokens (match providers/page.tsx)
// ---------------------------------------------------------------------------

const C = {
  bg: "#F8FAFC",
  card: "#FFFFFF",
  border: "#E2E8F0",
  borderLight: "#F1F5F9",
  text: "#0F172A",
  textMuted: "#64748B",
  textSub: "#94A3B8",
  primary: "#2563EB",
  primaryLight: "#DBEAFE",
  primaryDark: "#1D4ED8",
  emerald: "#10B981",
  emeraldLight: "#D1FAE5",
  emeraldDark: "#065F46",
  amber: "#F59E0B",
  amberLight: "#FEF3C7",
  amberDark: "#92400E",
  red: "#EF4444",
  redLight: "#FEE2E2",
  redDark: "#991B1B",
  violet: "#8B5CF6",
  violetLight: "#EDE9FE",
  gray50: "#F9FAFB",
  gray100: "#F3F4F6",
  gray200: "#E5E7EB",
  gray300: "#D1D5DB",
  gray400: "#9CA3AF",
  gray600: "#4B5563",
  white: "#FFFFFF",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtAge(age: number | null | undefined, sex: string | null | undefined): string {
  const a = age != null ? `${age}y` : "??";
  const s = (sex ?? "").trim() || "—";
  return `${a} · ${s}`;
}

function confidenceTone(c: number): { bg: string; fg: string; label: string } {
  if (c >= 0.85) return { bg: C.redLight, fg: C.redDark, label: "High" };
  if (c >= 0.70) return { bg: C.amberLight, fg: C.amberDark, label: "Med" };
  if (c > 0)     return { bg: C.primaryLight, fg: C.primaryDark, label: "Low" };
  return { bg: C.gray100, fg: C.gray600, label: "—" };
}

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export type HccGapDrilldownModalProps = {
  open: boolean;
  onClose: () => void;
  providerId: number;
  providerName: string;
  hccCode: string;
  hccLabel: string;
  year?: number;
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function HccGapDrilldownModal(props: HccGapDrilldownModalProps) {
  const { open, onClose, providerId, providerName, hccCode, hccLabel, year } = props;

  const [search, setSearch] = useState("");
  const [minConfidence, setMinConfidence] = useState(0);

  const { data, isLoading, isError, error } = useQuery<HccGapPatientsResponse>({
    queryKey: ["hcc-gap-patients", providerId, hccCode, year],
    queryFn: () => getProviderHccGapPatients(providerId, hccCode, year, 200),
    enabled: open && !!providerId && !!hccCode,
    staleTime: 60_000,
  });

  const patients = data?.patients ?? [];

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return patients.filter((p) => {
      if (minConfidence > 0 && (p.confidence ?? 0) < minConfidence) return false;
      if (!q) return true;
      const hay = [
        p.patient_name,
        p.first_name,
        p.last_name,
        p.mrn ?? "",
      ]
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [patients, search, minConfidence]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`HCC ${hccCode} gap patients`}
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        background: "rgba(15, 23, 42, 0.55)",
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        padding: "60px 20px",
        overflowY: "auto",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "100%",
          maxWidth: 880,
          background: C.white,
          borderRadius: 14,
          boxShadow: "0 24px 60px rgba(15, 23, 42, 0.25)",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
          maxHeight: "calc(100vh - 120px)",
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "18px 22px",
            borderBottom: `1px solid ${C.borderLight}`,
            display: "flex",
            alignItems: "flex-start",
            gap: 16,
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                fontSize: 17,
                fontWeight: 700,
                color: C.text,
                marginBottom: 4,
                display: "flex",
                alignItems: "center",
                gap: 8,
                flexWrap: "wrap",
              }}
            >
              <span>HCC {hccCode}</span>
              <span style={{ color: C.textMuted, fontWeight: 500 }}>·</span>
              <span style={{ color: C.text, fontWeight: 600 }}>{hccLabel}</span>
              <span style={{ color: C.textMuted, fontWeight: 500 }}>—</span>
              <span style={{ color: C.redDark, fontWeight: 700 }}>
                {isLoading ? "…" : `${data?.missing_count ?? 0} patients missing`}
              </span>
            </div>
            <div style={{ fontSize: 12, color: C.textMuted }}>
              {providerName}
              {data?.panel_size != null && (
                <>
                  {" · "}
                  panel size {data.panel_size}
                </>
              )}
              {data?.year && (
                <>
                  {" · "}
                  measurement year {data.year}
                </>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            style={{
              border: "none",
              background: C.gray100,
              borderRadius: 8,
              padding: 6,
              cursor: "pointer",
              color: C.textMuted,
              display: "flex",
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Filters */}
        <div
          style={{
            padding: "14px 22px",
            display: "flex",
            gap: 12,
            alignItems: "center",
            borderBottom: `1px solid ${C.borderLight}`,
            background: C.gray50,
            flexWrap: "wrap",
          }}
        >
          <div
            style={{
              flex: "1 1 240px",
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "7px 11px",
              background: C.white,
              border: `1px solid ${C.border}`,
              borderRadius: 8,
            }}
          >
            <Search size={14} color={C.textMuted} />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter by name or MRN"
              style={{
                flex: 1,
                border: "none",
                outline: "none",
                fontSize: 13,
                background: "transparent",
                color: C.text,
              }}
            />
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12, color: C.textMuted }}>
            <span style={{ whiteSpace: "nowrap" }}>Min confidence</span>
            <input
              type="range"
              min={0}
              max={100}
              step={5}
              value={Math.round(minConfidence * 100)}
              onChange={(e) => setMinConfidence(Number(e.target.value) / 100)}
              style={{ width: 120 }}
              aria-label="Minimum confidence"
            />
            <span style={{ fontWeight: 600, color: C.text, minWidth: 32 }}>
              {Math.round(minConfidence * 100)}%
            </span>
          </div>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: "auto", padding: "8px 0" }}>
          {isLoading && (
            <div style={{ padding: 40, textAlign: "center", color: C.textMuted, fontSize: 13 }}>
              Loading gap patients…
            </div>
          )}

          {isError && (
            <div
              style={{
                margin: 22,
                padding: 14,
                background: C.redLight,
                color: C.redDark,
                borderRadius: 8,
                display: "flex",
                gap: 10,
                alignItems: "center",
                fontSize: 13,
              }}
            >
              <AlertCircle size={16} />
              <span>
                Failed to load gap patients. {(error as Error)?.message || ""}
              </span>
            </div>
          )}

          {!isLoading && !isError && filtered.length === 0 && (
            <div
              style={{
                margin: 22,
                padding: 32,
                textAlign: "center",
                color: C.textMuted,
                fontSize: 13,
                background: C.gray50,
                borderRadius: 10,
                border: `1px dashed ${C.border}`,
              }}
            >
              No gap patients match these filters.
            </div>
          )}

          {!isLoading && !isError && filtered.length > 0 && (
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {filtered.map((p) => (
                <PatientRow key={p.patient_id} patient={p} />
              ))}
            </ul>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: "12px 22px",
            borderTop: `1px solid ${C.borderLight}`,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            background: C.gray50,
            fontSize: 12,
            color: C.textMuted,
          }}
        >
          <span>
            Showing {filtered.length} of {patients.length} matching gap patients
          </span>
          <button
            onClick={onClose}
            style={{
              padding: "7px 14px",
              borderRadius: 8,
              border: `1px solid ${C.border}`,
              background: C.white,
              color: C.text,
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

function PatientRow({ patient }: { patient: HccGapPatient }) {
  const conf = patient.confidence ?? 0;
  const tone = confidenceTone(conf);
  const snippet = patient.evidence_snippet || patient.top_evidence_snippet || "";

  return (
    <li
      style={{
        padding: "12px 22px",
        borderBottom: `1px solid ${C.borderLight}`,
        display: "flex",
        gap: 14,
        alignItems: "flex-start",
      }}
    >
      <div
        style={{
          width: 34,
          height: 34,
          borderRadius: 8,
          background: C.primaryLight,
          color: C.primary,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
        }}
      >
        <User size={16} />
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexWrap: "wrap",
            marginBottom: 4,
          }}
        >
          <span style={{ fontSize: 14, fontWeight: 600, color: C.text }}>
            {patient.patient_name}
          </span>
          <span style={{ fontSize: 12, color: C.textMuted }}>
            {fmtAge(patient.age, patient.sex)}
          </span>
          {patient.dob && (
            <span style={{ fontSize: 11, color: C.textSub }}>DOB {patient.dob}</span>
          )}
          {patient.mrn && (
            <span
              style={{
                fontSize: 10,
                fontWeight: 600,
                padding: "2px 7px",
                background: C.gray100,
                color: C.gray600,
                borderRadius: 6,
                letterSpacing: "0.02em",
              }}
            >
              MRN {patient.mrn}
            </span>
          )}
        </div>

        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 6 }}>
          {patient.suspect_status === "open" && (
            <Chip
              icon={<Sparkles size={11} />}
              bg={C.amberLight}
              fg={C.amberDark}
              label="Open suspect"
            />
          )}
          {patient.prior_year_coded && (
            <Chip
              icon={<History size={11} />}
              bg={C.violetLight}
              fg={C.violet}
              label="Prior-year coded"
            />
          )}
          <Chip
            bg={tone.bg}
            fg={tone.fg}
            label={`${Math.round(conf * 100)}% · ${tone.label}`}
          />
          {patient.evidence_type && (
            <Chip
              bg={C.gray100}
              fg={C.gray600}
              label={String(patient.evidence_type)}
            />
          )}
          {patient.last_encounter_date && (
            <Chip
              bg={C.gray100}
              fg={C.gray600}
              label={`Last seen ${patient.last_encounter_date.slice(0, 10)}`}
            />
          )}
        </div>

        {snippet && (
          <div
            title={snippet}
            style={{
              fontSize: 12,
              color: C.textMuted,
              lineHeight: 1.5,
              maxWidth: "100%",
              overflow: "hidden",
              textOverflow: "ellipsis",
              display: "-webkit-box",
              WebkitLineClamp: 2,
              WebkitBoxOrient: "vertical",
            }}
          >
            {snippet}
          </div>
        )}
      </div>

      <Link
        href={`/patients/${patient.patient_id}`}
        style={{
          padding: "7px 12px",
          background: C.primary,
          color: C.white,
          borderRadius: 8,
          fontSize: 12,
          fontWeight: 600,
          textDecoration: "none",
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          flexShrink: 0,
        }}
      >
        Open chart
        <ExternalLink size={12} />
      </Link>
    </li>
  );
}

function Chip({
  icon,
  bg,
  fg,
  label,
}: {
  icon?: React.ReactNode;
  bg: string;
  fg: string;
  label: string;
}) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: 9999,
        fontSize: 11,
        fontWeight: 600,
        background: bg,
        color: fg,
      }}
    >
      {icon}
      {label}
    </span>
  );
}
