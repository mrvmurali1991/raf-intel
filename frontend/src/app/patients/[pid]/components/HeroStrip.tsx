"use client";

/**
 * HeroStrip — always-visible patient identity bar.
 *
 * Shows: initials avatar, name, MRN, MBI, age/sex, insurance plan, primary
 * provider, last-visit date with staleness indicator, privacy toggle, and
 * "Pre-visit huddle" CTA.
 *
 * Usage:
 *   <HeroStrip patient={patient} profile={profile} pid={pid} privacyMode={false} onPrivacyToggle={fn} />
 */

import React from "react";
import Link from "next/link";
import { Eye, EyeOff, CalendarClock, Stethoscope } from "lucide-react";
import { C, formatDate } from "./shared";
import { calculateAge } from "@/lib/utils";
import type { Patient } from "@/types";
import type { PatientProfile } from "@/lib/api";

// ---- helpers ----------------------------------------------------------------

function daysSince(dateStr?: string | null): number | null {
  if (!dateStr) return null;
  const ms = Date.now() - new Date(dateStr).getTime();
  return Math.floor(ms / 86_400_000);
}

function lastVisitColor(days: number | null): string {
  if (days === null) return C.slate400;
  if (days > 365) return C.red600;
  if (days > 180) return C.amber600;
  return C.emerald600;
}

function InitialsAvatar({ name, pid }: { name: string; pid: string }) {
  const parts = name.trim().split(/\s+/);
  const initials =
    parts.length >= 2
      ? `${parts[0].charAt(0)}${parts[parts.length - 1].charAt(0)}`
      : parts[0]?.charAt(0) ?? "?";

  return (
    <div
      title={`PID ${pid}`}
      aria-hidden="true"
      style={{
        width: 52,
        height: 52,
        borderRadius: 14,
        background: `linear-gradient(135deg, ${C.blue600}, ${C.emerald600})`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: C.white,
        fontSize: 20,
        fontWeight: 800,
        letterSpacing: "-0.03em",
        flexShrink: 0,
        boxShadow: "0 3px 10px rgba(15,118,110,0.28)",
        userSelect: "none",
      }}
    >
      {initials.toUpperCase()}
    </div>
  );
}

// ---- component --------------------------------------------------------------

interface HeroStripProps {
  patient: Patient | undefined;
  profile: PatientProfile | undefined;
  pid: string;
  privacyMode: boolean;
  onPrivacyToggle: () => void;
  /** Last encounter date string (ISO or locale) */
  lastVisitDate?: string | null;
}

export function HeroStrip({
  patient,
  profile,
  pid,
  privacyMode,
  onPrivacyToggle,
  lastVisitDate,
}: HeroStripProps) {
  const patientName = patient
    ? `${patient.fname || patient.first_name || ""} ${patient.lname || patient.last_name || ""}`.trim()
    : "";

  const dob = patient?.DOB || patient?.dob || "";
  const sex = patient?.sex || patient?.gender || "";
  const age = dob ? calculateAge(dob) : null;
  const mrn = patient?.mrn ?? null;

  // MBI from profile enrollment
  const mbi =
    (profile?.enrollment as { mbi?: string } | undefined)?.mbi ?? null;

  // Insurance plan name
  const insurancePlan =
    (profile?.enrollment as { plan_name?: string; payer?: string } | undefined)
      ?.plan_name ??
    (profile?.enrollment as { plan_name?: string; payer?: string } | undefined)
      ?.payer ??
    null;

  // Primary provider
  const primaryProvider =
    (
      profile as
        | { primary_provider?: string; provider?: string }
        | undefined
    )?.primary_provider ??
    (
      profile as
        | { primary_provider?: string; provider?: string }
        | undefined
    )?.provider ??
    null;

  const days = daysSince(lastVisitDate);
  const visitColor = lastVisitColor(days);

  // Masked display helpers
  const displayName = (() => {
    if (!privacyMode) return patientName || `Patient ${pid}`;
    const parts = (patientName || "").trim().split(/\s+/);
    const f = parts[0]?.charAt(0) || "?";
    const l = parts.length > 1 ? parts[parts.length - 1].charAt(0) : "";
    return `${f}${l ? ". " + l + "." : "."}`;
  })();

  const displayMrn = privacyMode
    ? `••••${String(mrn ?? "").slice(-4)}`
    : String(mrn ?? "");

  return (
    <header
      className="premium-card animate-fade-in patient-sticky-header"
      style={{
        position: "sticky",
        top: 0,
        zIndex: 30,
        background: C.white,
        borderBottom: `1px solid ${C.slate200}`,
        borderRadius: 0,
      }}
    >
      <div
        style={{
          width: "100%",
          padding: "10px 20px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 12,
          minHeight: 72,
        }}
      >
        {/* ---- Left: back + avatar + identity ---- */}
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          {/* Back button */}
          <Link
            href="/patients"
            className="hover-lift"
            aria-label="Back to patient list"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: 44,
              height: 44,
              borderRadius: 8,
              border: `1px solid ${C.slate200}`,
              color: C.slate600,
              textDecoration: "none",
              flexShrink: 0,
              transition: "background 0.15s, transform 0.2s",
            }}
            onMouseEnter={(e) =>
              (e.currentTarget.style.background = C.slate100)
            }
            onMouseLeave={(e) =>
              (e.currentTarget.style.background = "transparent")
            }
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M19 12H5M12 19l-7-7 7-7" />
            </svg>
          </Link>

          {/* Avatar */}
          <InitialsAvatar name={patientName} pid={pid} />

          {/* Identity block */}
          <div>
            {/* Name row */}
            <div
              style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}
            >
              <h1
                className="gradient-text patient-name-h1"
                style={{
                  margin: 0,
                  fontSize: 22,
                  fontWeight: 700,
                  color: C.slate800,
                  lineHeight: 1.2,
                }}
              >
                {displayName}
              </h1>

              {mrn && (
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    padding: "3px 10px",
                    borderRadius: 999,
                    fontSize: 11,
                    fontWeight: 600,
                    fontFamily: "monospace",
                    background: C.slate100,
                    color: C.slate600,
                  }}
                >
                  MRN {displayMrn}
                </span>
              )}

              {mbi && !privacyMode && (
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    padding: "3px 10px",
                    borderRadius: 999,
                    fontSize: 11,
                    fontWeight: 600,
                    fontFamily: "monospace",
                    background: C.blue50,
                    color: C.blue600,
                    border: `1px solid ${C.blue100}`,
                  }}
                >
                  MBI {mbi}
                </span>
              )}

              {/* Privacy toggle */}
              <button
                type="button"
                onClick={onPrivacyToggle}
                aria-label={
                  privacyMode ? "Disable privacy mode" : "Enable privacy mode"
                }
                aria-pressed={privacyMode}
                title={
                  privacyMode
                    ? "Privacy mode ON — name + MRN masked. Ctrl/Cmd+Shift+P"
                    : "Privacy mode OFF — Toggle with Ctrl/Cmd+Shift+P"
                }
                style={{
                  background: "transparent",
                  border: `1px solid ${C.slate200}`,
                  borderRadius: 6,
                  cursor: "pointer",
                  width: 28,
                  height: 28,
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: privacyMode ? C.blue600 : C.slate500,
                  flexShrink: 0,
                }}
              >
                {privacyMode ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>

            {/* Demographics row */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                marginTop: 4,
                fontSize: 12,
                color: C.slate500,
                flexWrap: "wrap",
              }}
            >
              {age !== null && (
                <span>
                  {age} yrs
                  {sex ? `, ${sex.charAt(0).toUpperCase() + sex.slice(1)}` : ""}
                </span>
              )}
              {dob && <span>{formatDate(dob)}</span>}
              {insurancePlan && (
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 4,
                    padding: "2px 8px",
                    borderRadius: 6,
                    fontSize: 11,
                    fontWeight: 600,
                    background: C.slate100,
                    color: C.slate600,
                  }}
                >
                  {insurancePlan}
                </span>
              )}
              {primaryProvider && (
                <span
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 4,
                    fontSize: 11,
                    color: C.slate500,
                  }}
                >
                  <Stethoscope size={11} aria-hidden="true" />
                  {primaryProvider}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* ---- Right: last visit + pre-visit huddle ---- */}
        <div
          style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}
        >
          {/* Last visit indicator */}
          {lastVisitDate && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                padding: "6px 12px",
                borderRadius: 8,
                border: `1px solid ${visitColor}40`,
                background: `${visitColor}0d`,
                fontSize: 12,
                color: visitColor,
                fontWeight: 600,
              }}
              title={`Last visit: ${formatDate(lastVisitDate)}`}
            >
              <CalendarClock size={13} aria-hidden="true" />
              {days !== null ? (
                <span>
                  Last visit{" "}
                  <strong>
                    {days === 0
                      ? "today"
                      : days === 1
                      ? "yesterday"
                      : `${days}d ago`}
                  </strong>
                </span>
              ) : (
                formatDate(lastVisitDate)
              )}
            </div>
          )}

          {/* Pre-visit huddle CTA */}
          <Link
            href={`/md/today?pid=${pid}`}
            className="hover-lift"
            aria-label="Open pre-visit huddle for this patient"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 7,
              padding: "9px 16px",
              borderRadius: 10,
              border: `1px solid ${C.blue600}`,
              background: C.blue600,
              color: C.white,
              fontSize: 12,
              fontWeight: 700,
              textDecoration: "none",
              transition: "opacity 0.15s, transform 0.2s",
              minHeight: 40,
              whiteSpace: "nowrap",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.opacity = "0.88")}
            onMouseLeave={(e) => (e.currentTarget.style.opacity = "1")}
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2z" />
              <polyline points="12 6 12 12 16 14" />
            </svg>
            Pre-visit Huddle
          </Link>
        </div>
      </div>
    </header>
  );
}
