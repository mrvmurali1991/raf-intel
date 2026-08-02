"use client";

/**
 * HeroStrip — always-visible sticky patient identity bar.
 *
 * Full-mode layout (three-column snapshot card):
 *   LEFT   — back button + avatar + name + age/sex/DOB + MRN + privacy toggle
 *   CENTER — RAF score badge with risk level + V24/V28 breakdown
 *   RIGHT  — 3 mini stat cards: Open Suspects | Recapture Gaps | Revenue at Risk
 *   FAR RIGHT — primary CTA + More dropdown
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
 *     recaptureCount={recaptureQ.data?.gaps?.length ?? 0}
 *     revenueAtRisk={v28ImpactQ.data?.revenue_delta_annual ?? null}
 *     onAnalyzeAll={() => batchMutation.mutate()}
 *     onGenerateAudit={() => auditMutation.mutate()}
 *     onCalculateRAF={() => { ... }}
 *   />
 */

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import {
  Eye, EyeOff, Stethoscope,
  MoreHorizontal, Upload, Cpu, ClipboardList,
  FileText, Calculator, Printer, ChevronDown,
  AlertTriangle, RefreshCw, DollarSign,
} from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { C, formatDate, rafScoreColor, WithTooltip } from "./shared";
import { calculateAge } from "@/lib/utils";
import { formatCurrency } from "@/lib/format";
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

// ---- RAF Score Badge (inline, no external component needed) -----------------

function RafScoreBadge({
  rafScore,
  compact = false,
}: {
  rafScore: number | null | undefined;
  compact?: boolean;
}) {
  if (rafScore == null) {
    return (
      <div
        style={{
          display: "flex", flexDirection: "column", alignItems: "center",
          gap: 2, padding: compact ? "6px 14px" : "10px 20px",
        }}
      >
        <span className="text-slate-300 dark:text-slate-600" style={{ fontSize: compact ? 24 : 32, fontWeight: 800, fontFamily: "monospace", lineHeight: 1 }}>
          —
        </span>
        <span className="text-slate-500 dark:text-slate-400" style={{ fontSize: 10, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em" }}>
          RAF Score
        </span>
      </div>
    );
  }

  const color = rafScoreColor(rafScore);
  const riskLabel = rafScore >= 3.0 ? "High Risk" : rafScore >= 1.5 ? "Moderate Risk" : "Low Risk";
  const riskBgClass = rafScore >= 3.0 ? "bg-red-100 dark:bg-red-900" : rafScore >= 1.5 ? "bg-amber-100 dark:bg-amber-900" : "bg-emerald-100 dark:bg-emerald-900";

  return (
    <WithTooltip tip="CMS-HCC risk adjustment factor for the current measurement year. Scores above 1.0 indicate above-average predicted cost vs. the Medicare baseline. Higher scores reflect greater medical complexity.">
      <div
        style={{
          display: "flex", flexDirection: "column", alignItems: "center",
          gap: 3, padding: compact ? "6px 14px" : "10px 20px",
          cursor: "help",
        }}
      >
        <span
          style={{
            fontSize: compact ? 26 : 34,
            fontWeight: 800,
            color,
            fontFamily: "monospace",
            lineHeight: 1,
            letterSpacing: "-0.02em",
          }}
          aria-label={`RAF score ${Number(rafScore).toFixed(3)}`}
          data-testid="hero-raf-score"
        >
          {Number(rafScore).toFixed(3)}
        </span>
        <span
          className={riskBgClass}
          style={{
            display: "inline-flex", alignItems: "center",
            padding: "2px 8px", borderRadius: 999,
            fontSize: 10, fontWeight: 700,
            color,
            textTransform: "uppercase", letterSpacing: "0.04em",
          }}
        >
          {riskLabel}
        </span>
        <span className="text-slate-500 dark:text-slate-400" style={{ fontSize: 10, fontWeight: 500 }}>
          RAF Score
        </span>
      </div>
    </WithTooltip>
  );
}

// ---- Mini Stat Card ----------------------------------------------------------

function MiniStatCard({
  icon,
  count,
  label,
  borderColor,
  formatFn,
}: {
  icon: React.ReactNode;
  count: number | null;
  label: string;
  borderColor: string;
  formatFn?: (n: number) => string;
}) {
  const displayVal =
    count == null
      ? "—"
      : formatFn
      ? formatFn(count)
      : String(count);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-start",
        gap: 4,
        padding: "8px 12px",
        borderRadius: 8,
        borderLeft: `3px solid ${borderColor}`,
        background: `${borderColor}0d`,
        minWidth: 110,
        maxWidth: 130,
        flexShrink: 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 5, color: borderColor }}>
        {icon}
        <span
          className={count == null ? "text-slate-300 dark:text-slate-600" : ""}
          style={{
            fontSize: 20,
            fontWeight: 800,
            color: count == null ? undefined : borderColor,
            fontFamily: "monospace",
            lineHeight: 1,
            letterSpacing: "-0.02em",
          }}
        >
          {displayVal}
        </span>
      </div>
      <span className="text-slate-500 dark:text-slate-400" style={{ fontSize: 10, fontWeight: 600, lineHeight: 1.3, textTransform: "uppercase", letterSpacing: "0.04em" }}>
        {label}
      </span>
    </div>
  );
}

function DataQualityChip({ pct }: { pct: number }) {
  const color =
    pct >= 80 ? C.emerald600 : pct >= 50 ? C.amber600 : C.red600;
  const bg =
    pct >= 80 ? "#d1fae5" : pct >= 50 ? "#fef3c7" : "#fee2e2";
  return (
    <WithTooltip tip="Composite score of EMR data completeness across vitals / labs / notes / billing. Higher scores mean more complete clinical documentation for accurate RAF risk adjustment.">
      <span
        aria-label={`Data quality ${pct}%`}
        data-testid="data-quality-chip"
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
          cursor: "help",
        }}
      >
        DQ {pct}%
      </span>
    </WithTooltip>
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
  /** Current RAF score for compact header + center badge */
  rafScore?: number | null;
  /** Data quality 0–100 for compact header */
  dataQuality?: number;
  /** Open suspect count — drives "Open Review Queue" CTA + right stat card */
  suspectCount?: number;
  /** Open recapture gaps count — right stat card */
  recaptureCount?: number | null;
  /** Revenue at risk (annual, from V28 impact) — right stat card */
  revenueAtRisk?: number | null;
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
  recaptureCount = null,
  revenueAtRisk = null,
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

  // lastVisitDate + daysSince/lastVisitColor retained for future compact-mode staleness indicator

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

  const primaryBtnTip = {
    empty: "No clinical notes on file. Upload encounters to begin RAF analysis.",
    unanalyzed: "Clinical notes are loaded but not yet processed. Run Gemini AI analysis to extract diagnoses and populate the RAF score.",
    review: `${suspectCount} AI-detected suspect condition${suspectCount !== 1 ? "s" : ""} awaiting clinician attestation. Open the review queue to accept or dismiss each suspect before billing.`,
    complete: "All encounters analyzed and suspects resolved. Generate a CMS-ready audit package with attestation documentation.",
  }[patientState];

  const PrimaryBtn = () => {
    const btn = primaryAction.href ? (
      <Link
        href={primaryAction.href}
        style={primaryBtnStyle}
        aria-label={primaryAction.label}
        data-testid="hero-primary-cta"
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
        data-testid="hero-primary-cta"
        onClick={primaryAction.handler}
        onMouseEnter={(e) => (e.currentTarget.style.opacity = "0.88")}
        onMouseLeave={(e) => (e.currentTarget.style.opacity = "1")}
      >
        {primaryAction.icon}
        {primaryAction.label}
      </button>
    );
    return (
      <WithTooltip tip={primaryBtnTip} side="bottom">
        {btn}
      </WithTooltip>
    );
  };

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
                <WithTooltip tip="CMS-HCC V28 model output for current measurement year. This risk score drives Medicare Advantage premium payments — higher scores reflect greater predicted medical complexity.">
                  <span
                    data-testid="raf-score-pill"
                    className="text-teal-700 dark:text-teal-400 bg-blue-100 dark:bg-blue-900"
                    style={{
                      fontWeight: 700,
                      fontSize: 12,
                      padding: "2px 8px",
                      borderRadius: 999,
                      whiteSpace: "nowrap",
                      cursor: "help",
                    }}
                    aria-label={`RAF score ${Number(rafScore).toFixed(3)}`}
                  >
                    RAF {Number(rafScore).toFixed(3)}
                  </span>
                </WithTooltip>
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
              FULL MODE — three-column patient snapshot card
          ---------------------------------------------------------------- */
          <div
            style={{
              width: "100%",
              padding: "12px 20px",
              display: "flex",
              alignItems: "center",
              gap: 0,
              minHeight: 88,
              overflowX: "auto",
            }}
          >
            {/* ============================================================
                COLUMN A — Back button + Avatar + Identity
                ============================================================ */}
            <div style={{ display: "flex", alignItems: "center", gap: 12, flex: "1 1 auto", minWidth: 200 }}>
              {/* Back button */}
              <Link
                href="/patients"
                className="hover-lift hover:bg-slate-100 dark:hover:bg-slate-800"
                aria-label="Back to patient list"
                style={{
                  display: "flex", alignItems: "center", justifyContent: "center",
                  width: 36, height: 36, borderRadius: 8,
                  border: "1px solid", textDecoration: "none",
                  flexShrink: 0, transition: "background 0.15s, transform 0.2s",
                }}
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" strokeWidth="2"
                  strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M19 12H5M12 19l-7-7 7-7" />
                </svg>
              </Link>

              <InitialsAvatar name={patientName} pid={pid} />

              {/* Identity block */}
              <div style={{ minWidth: 0 }}>
                {/* Name + privacy toggle */}
                <div style={{ display: "flex", alignItems: "center", gap: 7, flexWrap: "wrap" }}>
                  <h1
                    className="gradient-text patient-name-h1 text-foreground"
                    style={{ margin: 0, fontSize: 20, fontWeight: 700, lineHeight: 1.2 }}
                  >
                    {displayName}
                  </h1>
                  {mbi && !privacyMode && (
                    <span
                      className="text-primary font-mono"
                      style={{ fontSize: 10, fontWeight: 600 }}
                    >
                      MBI: {mbi}
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
                    className="border border-slate-200 dark:border-slate-700"
                    style={{
                      background: "transparent",
                      borderRadius: 6, cursor: "pointer", width: 24, height: 24,
                      display: "inline-flex", alignItems: "center", justifyContent: "center",
                      flexShrink: 0,
                    }}
                  >
                    {privacyMode ? <EyeOff size={12} /> : <Eye size={12} />}
                  </button>
                </div>

                {/* Age · Sex · DOB — one compact line */}
                <div
                  className="text-muted-foreground"
                  style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 3, fontSize: 12, flexWrap: "wrap" }}
                >
                  {age !== null && <span style={{ fontWeight: 500 }}>{age} yrs</span>}
                  {age !== null && sex && <span className="text-slate-300 dark:text-slate-600">·</span>}
                  {sex && <span style={{ fontWeight: 500 }}>{sex.charAt(0).toUpperCase() + sex.slice(1)}</span>}
                  {(age !== null || sex) && dob && <span className="text-slate-300 dark:text-slate-600">·</span>}
                  {dob && <span>DOB {formatDate(dob)}</span>}
                  {insurancePlan && (
                    <>
                      <span className="text-slate-300 dark:text-slate-600">·</span>
                      <span
                        className="bg-muted text-muted-foreground"
                        style={{ padding: "0px 5px", borderRadius: 4, fontSize: 10, fontWeight: 600 }}
                      >
                        {insurancePlan}
                      </span>
                    </>
                  )}
                </div>

                {/* MRN + provider — second sub-line */}
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 2, flexWrap: "wrap" }}>
                  {mrn && (
                    <span className="text-slate-500 dark:text-slate-400" style={{ fontSize: 11, fontFamily: "monospace" }}>
                      MRN: {displayMrn}
                    </span>
                  )}
                  {primaryProvider && (
                    <span
                      className="text-muted-foreground"
                      style={{ display: "inline-flex", alignItems: "center", gap: 3, fontSize: 11 }}
                    >
                      <Stethoscope size={10} aria-hidden="true" />
                      {primaryProvider}
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* ============================================================
                DIVIDER A→B
                ============================================================ */}
            <div
              aria-hidden="true"
              className="bg-slate-200 dark:bg-slate-700"
              style={{ width: 1, alignSelf: "stretch", margin: "8px 14px", flexShrink: 0 }}
            />

            {/* ============================================================
                COLUMN B — RAF Score Badge (center spotlight)
                ============================================================ */}
            <div style={{ flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <RafScoreBadge rafScore={rafScore} />
            </div>

            {/* ============================================================
                DIVIDER B→C
                ============================================================ */}
            <div
              aria-hidden="true"
              className="bg-slate-200 dark:bg-slate-700"
              style={{ width: 1, alignSelf: "stretch", margin: "8px 14px", flexShrink: 0 }}
            />

            {/* ============================================================
                COLUMN C — Three mini stat cards
                ============================================================ */}
            <div style={{ display: "flex", gap: 8, flexShrink: 0, alignItems: "center" }}>
              <WithTooltip tip="AI-detected suspect conditions awaiting clinician review. Each accepted suspect can increase the patient's RAF score and Medicare Advantage revenue.">
                <div>
                  <MiniStatCard
                    icon={<AlertTriangle size={12} aria-hidden="true" />}
                    count={suspectCount}
                    label="Open Suspects"
                    borderColor={C.amber600}
                  />
                </div>
              </WithTooltip>

              <WithTooltip tip="Chronic conditions coded in prior years but not yet recaptured this measurement year. Uncaptured HCCs cause RAF score erosion before year-end close.">
                <div>
                  <MiniStatCard
                    icon={<RefreshCw size={12} aria-hidden="true" />}
                    count={recaptureCount}
                    label="Recapture Gaps"
                    borderColor={C.red600}
                  />
                </div>
              </WithTooltip>

              <WithTooltip tip="Estimated annual revenue delta from V24 to V28 model transition. Negative values indicate projected revenue erosion from HCC deletions in the new model.">
                <div>
                  <MiniStatCard
                    icon={<DollarSign size={12} aria-hidden="true" />}
                    count={revenueAtRisk}
                    label="Revenue at Risk"
                    borderColor="#0d9488"
                    formatFn={(n) => formatCurrency(Math.round(n), { compact: true, showSign: n > 0 })}
                  />
                </div>
              </WithTooltip>
            </div>

            {/* ============================================================
                DIVIDER C→D
                ============================================================ */}
            <div
              aria-hidden="true"
              className="bg-slate-200 dark:bg-slate-700"
              style={{ width: 1, alignSelf: "stretch", margin: "8px 14px", flexShrink: 0 }}
            />

            {/* ============================================================
                COLUMN D — Primary CTA + More actions
                ============================================================ */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
              <PrimaryBtn />
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
        className="text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-700"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          padding: compact ? "7px 10px" : "9px 12px",
          borderRadius: 10,
          background: "transparent",
          fontSize: 12,
          fontWeight: 600,
          cursor: "pointer",
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
