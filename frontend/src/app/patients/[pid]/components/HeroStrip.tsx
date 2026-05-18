"use client";

/**
 * HeroStrip — always-visible sticky patient identity bar.
 *
 * State-aware primary CTA:
 *   - encounters.length === 0            → "Import Clinical Notes"  → /uploads?patient=X
 *   - encounters.length > 0 && !analyzed → "Analyze Encounters"     → calls onAnalyzeAll
 *   - analyzed && review_pending > 0     → "Open Review Queue"      → /review-queue?patient=X
 *   - complete (analyzed, no pending)    → "Generate Audit"         → calls onGenerateAudit
 *
 * Secondary actions (Generate Audit, Calculate RAF, Print) collapse into a
 * "More" DropdownMenu so the primary CTA always dominates visually.
 *
 * Compact-after-scroll: after scrolling > 120 px the strip shrinks to
 *   name + RAF score + data-quality chip + primary CTA only.
 *
 * Usage:
 *   <HeroStrip
 *     patient={patient} profile={profile} pid={pid}
 *     privacyMode={false} onPrivacyToggle={fn}
 *     lastVisitDate={lastVisitDate}
 *     encounters={encountersQ.data?.encounters ?? []}
 *     rafScore={rafScore} dataQuality={dataQuality}
 *     suspectCount={suspectCount}
 *     onAnalyzeAll={() => batchMutation.mutate()}
 *     onGenerateAudit={() => auditMutation.mutate()}
 *     onCalculateRAF={() => { ... }}
 *   />
 */

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import {
  Eye, EyeOff, CalendarClock, Stethoscope,
  MoreHorizontal, Upload, Cpu, ClipboardList,
  FileText, Calculator, Printer, ChevronDown,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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

function DataQualityChip({ pct }: { pct: number }) {
  const color =
    pct >= 80 ? C.emerald600 : pct >= 50 ? C.amber600 : C.red600;
  const bg =
    pct >= 80 ? "#d1fae5" : pct >= 50 ? "#fef3c7" : "#fee2e2";
  return (
    <span
      aria-label={`Data quality ${pct}%`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 700,
        color,
        background: bg,
        border: `1px solid ${color}40`,
        whiteSpace: "nowrap",
      }}
    >
      DQ {pct}%
    </span>
  );
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
        color: "#fff",
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

// ---- types ------------------------------------------------------------------

export interface HeroStripEncounter {
  cached_analysis?: unknown;
  analysis?: unknown;
  encounter_date?: string;
  date?: string;
}

interface HeroStripProps {
  patient: Patient | undefined;
  profile: PatientProfile | undefined;
  pid: string;
  privacyMode: boolean;
  onPrivacyToggle: () => void;
  /** Last encounter date string (ISO or locale) */
  lastVisitDate?: string | null;
  /** Encounter list to derive patient state */
  encounters?: HeroStripEncounter[];
  /** Current RAF score for compact header */
  rafScore?: number | null;
  /** Data quality 0–100 for compact header */
  dataQuality?: number;
  /** Open suspect count — drives "Open Review Queue" CTA */
  suspectCount?: number;
  /** Called when primary action is "Analyze Encounters" */
  onAnalyzeAll?: () => void;
  /** Called when primary action is "Generate Audit" */
  onGenerateAudit?: () => void;
  /** Called from More menu "Calculate RAF" */
  onCalculateRAF?: () => void;
}

// ---- component --------------------------------------------------------------

export function HeroStrip({
  patient,
  profile,
  pid,
  privacyMode,
  onPrivacyToggle,
  lastVisitDate,
  encounters = [],
  rafScore,
  dataQuality,
  suspectCount = 0,
  onAnalyzeAll,
  onGenerateAudit,
  onCalculateRAF,
}: HeroStripProps) {
  // ---- compact-on-scroll state ----
  const [compact, setCompact] = useState(false);
  const sentinelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onScroll = () => {
      setCompact(window.scrollY > 120);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    // set initial
    onScroll();
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // ---- derived identity ----
  const patientName = patient
    ? `${patient.fname || patient.first_name || ""} ${patient.lname || patient.last_name || ""}`.trim()
    : "";

  const dob = patient?.DOB || patient?.dob || "";
  const sex = patient?.sex || patient?.gender || "";
  const age = dob ? calculateAge(dob) : null;
  const mrn = patient?.mrn ?? null;

  const mbi =
    (profile?.enrollment as { mbi?: string } | undefined)?.mbi ?? null;

  const insurancePlan =
    (profile?.enrollment as { plan_name?: string; payer?: string } | undefined)
      ?.plan_name ??
    (profile?.enrollment as { plan_name?: string; payer?: string } | undefined)
      ?.payer ??
    null;

  const primaryProvider =
    (profile as { primary_provider?: string; provider?: string } | undefined)
      ?.primary_provider ??
    (profile as { primary_provider?: string; provider?: string } | undefined)
      ?.provider ??
    null;

  const days = daysSince(lastVisitDate);
  const visitColor = lastVisitColor(days);

  // ---- privacy helpers ----
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

  // ---- primary CTA derivation ----
  const analyzed = encounters.length > 0 && encounters.every(
    (e) => e.cached_analysis || e.analysis
  );

  type PatientState = "empty" | "unanalyzed" | "review" | "complete";
  const patientState: PatientState = (() => {
    if (encounters.length === 0) return "empty";
    if (!analyzed) return "unanalyzed";
    if (suspectCount > 0) return "review";
    return "complete";
  })();

  const primaryAction = {
    empty: {
      label: "Import Clinical Notes",
      icon: <Upload size={15} aria-hidden="true" />,
      href: `/uploads?patient=${pid}`,
      handler: undefined as (() => void) | undefined,
    },
    unanalyzed: {
      label: "Analyze Encounters",
      icon: <Cpu size={15} aria-hidden="true" />,
      href: undefined as string | undefined,
      handler: onAnalyzeAll,
    },
    review: {
      label: "Open Review Queue",
      icon: <ClipboardList size={15} aria-hidden="true" />,
      href: `/review-queue?patient=${pid}`,
      handler: undefined as (() => void) | undefined,
    },
    complete: {
      label: "Generate Audit",
      icon: <FileText size={15} aria-hidden="true" />,
      href: undefined as string | undefined,
      handler: onGenerateAudit,
    },
  }[patientState];

  // Shared primary button styles
  const primaryBtnStyle: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 7,
    padding: compact ? "7px 14px" : "9px 18px",
    borderRadius: 10,
    background: "var(--primary, #0f766e)",
    color: "#fff",
    fontSize: compact ? 12 : 13,
    fontWeight: 700,
    border: "none",
    cursor: "pointer",
    textDecoration: "none",
    transition: "opacity 0.15s, transform 0.2s",
    whiteSpace: "nowrap",
    minHeight: compact ? 36 : 40,
    flexShrink: 0,
    boxShadow: "0 2px 8px rgba(15,118,110,0.3)",
  };

  const PrimaryBtn = () =>
    primaryAction.href ? (
      <Link
        href={primaryAction.href}
        style={primaryBtnStyle}
        aria-label={primaryAction.label}
        onMouseEnter={(e) => (e.currentTarget.style.opacity = "0.88")}
        onMouseLeave={(e) => (e.currentTarget.style.opacity = "1")}
      >
        {primaryAction.icon}
        {primaryAction.label}
      </Link>
    ) : (
      <button
        type="button"
        style={primaryBtnStyle}
        aria-label={primaryAction.label}
        onClick={primaryAction.handler}
        onMouseEnter={(e) => (e.currentTarget.style.opacity = "0.88")}
        onMouseLeave={(e) => (e.currentTarget.style.opacity = "1")}
      >
        {primaryAction.icon}
        {primaryAction.label}
      </button>
    );

  // ---- More dropdown items ----
  // "Generate Audit" only appears in More menu when it is NOT the primary CTA
  const moreItems: Array<{
    label: string;
    icon: React.ReactNode;
    onClick?: () => void;
    href?: string;
  }> = [
    ...(patientState !== "complete"
      ? [
          {
            label: "Generate Audit",
            icon: <FileText size={14} aria-hidden="true" />,
            onClick: onGenerateAudit,
          },
        ]
      : []),
    {
      label: "Calculate RAF",
      icon: <Calculator size={14} aria-hidden="true" />,
      onClick: onCalculateRAF,
    },
    {
      label: "Print",
      icon: <Printer size={14} aria-hidden="true" />,
      onClick: () => window.print(),
    },
  ];

  // ---- render ----
  return (
    <>
      {/* Scroll sentinel — sits at page top, IntersectionObserver alternative
          not needed since we use a scroll listener above */}
      <div ref={sentinelRef} aria-hidden="true" style={{ height: 0 }} />

      <header
        className="premium-card animate-fade-in patient-sticky-header bg-card border-b border-border"
        style={{
          position: "sticky",
          top: 0,
          zIndex: 30,
          borderRadius: 0,
          transition: "min-height 0.2s ease, padding 0.2s ease",
        }}
      >
        {/* ----------------------------------------------------------------
            COMPACT MODE — visible only after scrolling > 120 px
        ---------------------------------------------------------------- */}
        {compact ? (
          <div
            style={{
              width: "100%",
              padding: "6px 16px",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
              minHeight: 52,
              flexWrap: "wrap",
            }}
          >
            {/* Left: back + name + RAF + DQ */}
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <Link
                href="/patients"
                className="hover-lift"
                aria-label="Back to patient list"
                style={{
                  display: "flex", alignItems: "center", justifyContent: "center",
                  width: 32, height: 32, borderRadius: 6,
                  border: "1px solid", textDecoration: "none", flexShrink: 0,
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" strokeWidth="2"
                  strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M19 12H5M12 19l-7-7 7-7" />
                </svg>
              </Link>

              <span
                className="text-foreground"
                style={{ fontWeight: 700, fontSize: 14, whiteSpace: "nowrap" }}
              >
                {displayName}
              </span>

              {rafScore != null && (
                <span
                  style={{
                    fontWeight: 700,
                    fontSize: 12,
                    color: C.blue600,
                    background: "#dbeafe",
                    padding: "2px 8px",
                    borderRadius: 999,
                    whiteSpace: "nowrap",
                  }}
                  aria-label={`RAF score ${Number(rafScore).toFixed(3)}`}
                >
                  RAF {Number(rafScore).toFixed(3)}
                </span>
              )}

              {dataQuality != null && <DataQualityChip pct={dataQuality} />}
            </div>

            {/* Right: primary CTA + More */}
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <PrimaryBtn />
              <MoreMenu items={moreItems} compact />
            </div>
          </div>
        ) : (
          /* ----------------------------------------------------------------
              FULL MODE
          ---------------------------------------------------------------- */
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
                  display: "flex", alignItems: "center", justifyContent: "center",
                  width: 44, height: 44, borderRadius: 8,
                  border: "1px solid", textDecoration: "none",
                  flexShrink: 0, transition: "background 0.15s, transform 0.2s",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = C.slate100)}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" strokeWidth="2"
                  strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M19 12H5M12 19l-7-7 7-7" />
                </svg>
              </Link>

              <InitialsAvatar name={patientName} pid={pid} />

              {/* Identity block */}
              <div>
                {/* Name row */}
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <h1
                    className="gradient-text patient-name-h1 text-foreground"
                    style={{ margin: 0, fontSize: 22, fontWeight: 700, lineHeight: 1.2 }}
                  >
                    {displayName}
                  </h1>

                  {mrn && (
                    <span
                      className="bg-muted text-muted-foreground font-mono"
                      style={{
                        display: "inline-flex", alignItems: "center",
                        padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 600,
                      }}
                    >
                      MRN {displayMrn}
                    </span>
                  )}

                  {mbi && !privacyMode && (
                    <span
                      className="text-primary bg-primary/10 border border-primary/20 font-mono"
                      style={{
                        display: "inline-flex", alignItems: "center",
                        padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 600,
                      }}
                    >
                      MBI {mbi}
                    </span>
                  )}

                  {/* Privacy toggle */}
                  <button
                    type="button"
                    onClick={onPrivacyToggle}
                    aria-label={privacyMode ? "Disable privacy mode" : "Enable privacy mode"}
                    aria-pressed={privacyMode}
                    title={
                      privacyMode
                        ? "Privacy mode ON — name + MRN masked. Ctrl/Cmd+Shift+P"
                        : "Privacy mode OFF — Toggle with Ctrl/Cmd+Shift+P"
                    }
                    style={{
                      background: "transparent", border: `1px solid ${C.slate200}`,
                      borderRadius: 6, cursor: "pointer", width: 28, height: 28,
                      display: "inline-flex", alignItems: "center", justifyContent: "center",
                      flexShrink: 0,
                    }}
                  >
                    {privacyMode ? <EyeOff size={14} /> : <Eye size={14} />}
                  </button>
                </div>

                {/* Demographics row */}
                <div
                  className="text-muted-foreground"
                  style={{
                    display: "flex", alignItems: "center", gap: 12,
                    marginTop: 4, fontSize: 12, flexWrap: "wrap",
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
                      className="bg-muted text-muted-foreground"
                      style={{
                        display: "inline-flex", alignItems: "center", gap: 4,
                        padding: "2px 8px", borderRadius: 6, fontSize: 11, fontWeight: 600,
                      }}
                    >
                      {insurancePlan}
                    </span>
                  )}
                  {primaryProvider && (
                    <span
                      className="text-muted-foreground"
                      style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 11 }}
                    >
                      <Stethoscope size={11} aria-hidden="true" />
                      {primaryProvider}
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* ---- Right: last visit + PRIMARY CTA + More ---- */}
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              {/* Last visit indicator */}
              {lastVisitDate && (
                <div
                  style={{
                    display: "flex", alignItems: "center", gap: 6,
                    padding: "6px 12px", borderRadius: 8,
                    border: `1px solid ${visitColor}40`, background: `${visitColor}0d`,
                    fontSize: 12, color: visitColor, fontWeight: 600,
                  }}
                  title={`Last visit: ${formatDate(lastVisitDate)}`}
                >
                  <CalendarClock size={13} aria-hidden="true" />
                  {days !== null ? (
                    <span>
                      Last visit{" "}
                      <strong>
                        {days === 0 ? "today" : days === 1 ? "yesterday" : `${days}d ago`}
                      </strong>
                    </span>
                  ) : (
                    formatDate(lastVisitDate)
                  )}
                </div>
              )}

              {/* Primary CTA — state-aware, dominant */}
              <PrimaryBtn />

              {/* More dropdown — secondary actions */}
              <MoreMenu items={moreItems} compact={false} />
            </div>
          </div>
        )}
      </header>
    </>
  );
}

// ---- More dropdown sub-component --------------------------------------------

interface MoreMenuItem {
  label: string;
  icon: React.ReactNode;
  onClick?: () => void;
  href?: string;
}

function MoreMenu({
  items,
  compact,
}: {
  items: MoreMenuItem[];
  compact: boolean;
}) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          padding: compact ? "7px 10px" : "9px 12px",
          borderRadius: 10,
          background: "transparent",
          border: `1px solid ${C.slate200}`,
          fontSize: 12,
          fontWeight: 600,
          cursor: "pointer",
          color: C.slate600,
          transition: "background 0.15s",
          minHeight: compact ? 36 : 40,
          whiteSpace: "nowrap",
          flexShrink: 0,
        }}
        aria-label="More actions"
      >
        <MoreHorizontal size={14} aria-hidden="true" />
        More
        <ChevronDown size={12} aria-hidden="true" />
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" style={{ minWidth: 180, zIndex: 50 }}>
        {items.map((item) => (
          <DropdownMenuItem
            key={item.label}
            onClick={item.href ? undefined : item.onClick}
            style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, cursor: "pointer" }}
          >
            {item.href ? (
              <Link
                href={item.href}
                style={{ display: "flex", alignItems: "center", gap: 8, width: "100%", textDecoration: "none", color: "inherit" }}
              >
                {item.icon}
                {item.label}
              </Link>
            ) : (
              <>
                {item.icon}
                {item.label}
              </>
            )}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
