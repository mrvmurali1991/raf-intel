"use client";

/**
 * RAFReconciliationCard — three-way RAF variance view.
 *
 * Mirrors Optum Risk View's reconciliation pattern: clinicians and coders
 * see the difference between (a) what the engine currently computes,
 * (b) what was submitted to CMS in the last cycle, and (c) the projected
 * full-capture score if every open suspect were accepted with MEAT.
 *
 * Three-way variance reveals revenue leakage:
 *   - "current vs projected" gap = uncoded opportunity
 *   - "submitted vs current" gap = drift since last submission (new
 *     evidence, dropped diagnoses, hierarchy changes)
 *
 * The "CMS-accepted" leg is rendered when accepted_raf is supplied;
 * until we wire the EDPS feedback channel into the backend it stays
 * null and the card hides that column gracefully.
 */

import type { FinancialImpact } from "../_shared";
import { formatCurrency } from "@/lib/format";

export interface RAFReconciliationProps {
  /** Engine-calculated RAF as of this panel render (sum of accepted +
   *  active HCCs, applies V28 / blend weights). */
  currentRaf: number;
  /** Score last shipped to CMS via the encounter-data submission. May
   *  equal currentRaf for fresh tenants; lower than currentRaf when
   *  late-arriving documentation has lifted the score since the cycle
   *  locked. */
  submittedRaf?: number | null;
  /** What CMS has actually accepted via EDPS feedback. Null when no
   *  EDPS response has been ingested for this measurement year. */
  acceptedRaf?: number | null;
  /** Engine projection if every open suspect is accepted with
   *  MEAT-complete evidence. Lifted from FinancialImpact.projected_raf. */
  projectedRaf: number;
  /** Dollar value of 1.0 RAF point — CMS-MA benchmark used by the
   *  financial panel. */
  revenuePerRafPoint: number;
  /** Payment year for the score; surfaced in the header so coders know
   *  which cycle this variance applies to. */
  measurementYear: number;
}

function fmt(n: number, digits = 3): string {
  return Number(n || 0).toFixed(digits);
}

function fmtUsd(n: number): string {
  return formatCurrency(Math.round(n));
}

export function RAFReconciliationCard({
  currentRaf,
  submittedRaf,
  acceptedRaf,
  projectedRaf,
  revenuePerRafPoint,
  measurementYear,
}: RAFReconciliationProps) {
  const submitted = submittedRaf ?? currentRaf;
  const opportunityGap = Math.max(0, projectedRaf - currentRaf);
  const driftGap = Math.abs(currentRaf - submitted);
  const acceptedGap = acceptedRaf != null ? currentRaf - acceptedRaf : null;

  return (
    <div className="space-y-3">
      <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        RAF reconciliation · PY{measurementYear}
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <Tile
          label="Submitted to CMS"
          value={fmt(submitted)}
          subtitle="Last cycle"
          tone="muted"
        />
        <Tile
          label="Current (engine)"
          value={fmt(currentRaf)}
          subtitle={
            driftGap === 0
              ? "Matches submission"
              : `${currentRaf > submitted ? "+" : "-"}${fmt(driftGap, 3)} since submit`
          }
          tone={driftGap === 0 ? "muted" : "amber"}
        />
        <Tile
          label="Projected (full capture)"
          value={fmt(projectedRaf)}
          subtitle={
            opportunityGap > 0
              ? `+${fmt(opportunityGap, 3)} opportunity · ${fmtUsd(opportunityGap * revenuePerRafPoint)} · assumes MEAT-complete documentation`
              : "Already at projection"
          }
          tone={opportunityGap > 0 ? "emerald" : "muted"}
        />
      </div>
      {acceptedRaf != null && (
        <div className="rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-xs text-sky-900 dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-200">
          <strong>CMS-accepted:</strong> {fmt(acceptedRaf)} —{" "}
          {acceptedGap === 0
            ? "matches engine"
            : `${(acceptedGap as number) > 0 ? "engine is higher by " : "CMS is higher by "}${fmt(Math.abs(acceptedGap as number), 3)}`}
          {(acceptedGap ?? 0) > 0 && (
            <>
              {" "}({fmtUsd(((acceptedGap ?? 0) as number) * revenuePerRafPoint)} leakage). Review
              EDPS rejection log to reconcile.
            </>
          )}
        </div>
      )}
      {acceptedRaf == null && (
        <div className="rounded-md border border-zinc-200 bg-zinc-50 px-3 py-1.5 text-[11px] italic text-muted-foreground dark:border-zinc-800 dark:bg-zinc-900/40">
          CMS-accepted RAF will appear here once EDPS feedback is ingested
          for PY{measurementYear}.
        </div>
      )}
    </div>
  );
}

/** Helper: derive props from the panel's FinancialImpact + measurement_year. */
export function buildReconciliationProps(
  financial: FinancialImpact,
  measurementYear: number,
  submittedRaf?: number | null,
  acceptedRaf?: number | null,
): RAFReconciliationProps {
  return {
    currentRaf: financial.current_raf,
    submittedRaf,
    acceptedRaf,
    projectedRaf: financial.projected_raf,
    revenuePerRafPoint: financial.revenue_per_raf_point,
    measurementYear,
  };
}

function Tile({
  label,
  value,
  subtitle,
  tone,
}: {
  label: string;
  value: string;
  subtitle: string;
  tone: "muted" | "amber" | "emerald";
}) {
  const toneClass =
    tone === "emerald"
      ? "border-emerald-200 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/40"
      : tone === "amber"
      ? "border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/40"
      : "border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-900/40";
  return (
    <div className={`rounded-md border px-3 py-2 ${toneClass}`}>
      <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 text-lg font-bold tabular-nums leading-none text-foreground">
        {value}
      </div>
      <div className="mt-1 text-[11px] text-muted-foreground">{subtitle}</div>
    </div>
  );
}
