"use client";

/**
 * WhatIfSimulator — interactive Pareto-style scenario simulator.
 *
 * Lets a coder slide two range inputs ("% of open suspects accepted" and
 * "% of recapture gaps closed") and see the projected end-of-year RAF
 * plus annual revenue with a confidence band, all calculated client-side.
 *
 * Math:
 *   projected_raf =
 *     current_raf
 *     + (suspect_pct / 100) * sum_of_open_suspect_coefficients
 *     + (recapture_pct / 100) * sum_of_recapture_raf_impact
 *
 *   projected_annual_revenue = projected_raf * revenue_per_raf_point
 *
 * Confidence band: ±15% scaled by (1 - mean_suspect_confidence). High
 * confidence (e.g. 0.9) → narrow band (~1.5%); low confidence (e.g. 0.3)
 * → near-full ±15% band. Recapture is treated as deterministic
 * (already-coded history) and doesn't widen the band.
 *
 * The component derives per-suspect coefficients from
 * `expected_dollar_impact / revenue_per_raf_point` since the raw model
 * coefficient is not currently shipped on SuspectCard. Recapture RAF
 * impact is derived from `revenue_at_risk / revenue_per_raf_point`.
 *
 * Accessibility: both sliders carry `aria-valuetext` that announces the
 * resulting projected RAF so screen-reader users hear the live impact
 * of each step.
 */

import { useMemo, useState, useCallback, useId } from "react";
import { Button } from "@/components/ui/button";
import { RefreshCcw, Sliders } from "lucide-react";
import { cn } from "@/lib/utils";
import type { SuspectCard, RecaptureCard } from "./_shared";

export interface WhatIfSimulatorProps {
  /** Engine RAF as of this panel render. */
  currentRaf: number;
  /** Suspect cards that have not been dismissed / accepted yet. */
  openSuspects: SuspectCard[];
  /** Recapture cards (prior-year HCCs not yet captured this year). */
  openRecaptures: RecaptureCard[];
  /** Dollar value of 1.0 RAF point — same constant used by the panel. */
  revenuePerRafPoint: number;
}

function fmtRaf(n: number): string {
  return Number.isFinite(n) ? (n ?? 0).toFixed(3) : "—";
}

function fmtUsd(n: number): string {
  if (!Number.isFinite(n)) return "—";
  return `$${Math.round(n).toLocaleString()}`;
}

/** Confidence-band half-width as a fraction of projected_raf. */
const MAX_BAND_FRACTION = 0.15;

export function WhatIfSimulator({
  currentRaf,
  openSuspects,
  openRecaptures,
  revenuePerRafPoint,
}: WhatIfSimulatorProps) {
  const [suspectPct, setSuspectPct] = useState<number>(0);
  const [recapturePct, setRecapturePct] = useState<number>(0);

  // Count suspects that have no expected_dollar_impact from the model.
  // Used to render the "Awaiting model coefficient" badge in the slider row.
  const missingDollarCount = useMemo(
    () => openSuspects.filter((s) => s.expected_dollar_impact == null).length,
    [openSuspects],
  );

  // Derive per-card RAF deltas client-side. Suspects ship dollar impact
  // (not raw coefficient) so we invert through revenue_per_raf_point.
  // Suspects with null/undefined expected_dollar_impact are excluded from
  // the sum rather than treated as $0 — we render "—" for those rows.
  // Guard against zero to avoid NaN when the constant isn't supplied yet.
  const sumSuspectCoefficients = useMemo(() => {
    if (!revenuePerRafPoint || revenuePerRafPoint <= 0) return 0;
    return openSuspects.reduce((acc, s) => {
      if (s.expected_dollar_impact == null) return acc; // excluded, not $0
      const dollar = Number(s.expected_dollar_impact);
      return acc + (dollar > 0 ? dollar / revenuePerRafPoint : 0);
    }, 0);
  }, [openSuspects, revenuePerRafPoint]);

  const sumRecaptureRafImpact = useMemo(() => {
    if (!revenuePerRafPoint || revenuePerRafPoint <= 0) return 0;
    return openRecaptures.reduce((acc, r) => {
      const dollar = Number(r.revenue_at_risk ?? 0);
      return acc + (dollar > 0 ? dollar / revenuePerRafPoint : 0);
    }, 0);
  }, [openRecaptures, revenuePerRafPoint]);

  const meanSuspectConfidence = useMemo(() => {
    if (openSuspects.length === 0) return 1; // no suspects → no uncertainty
    const total = openSuspects.reduce(
      (acc, s) => acc + Math.max(0, Math.min(1, Number(s.confidence ?? 0))),
      0,
    );
    return total / openSuspects.length;
  }, [openSuspects]);

  const projectedRaf =
    currentRaf +
    (suspectPct / 100) * sumSuspectCoefficients +
    (recapturePct / 100) * sumRecaptureRafImpact;

  const projectedAnnualRevenue = projectedRaf * revenuePerRafPoint;
  const currentAnnualRevenue = currentRaf * revenuePerRafPoint;
  const revenueDelta = projectedAnnualRevenue - currentAnnualRevenue;

  // Confidence band: scale ±15% by (1 - mean_confidence). When user has
  // not touched the suspect slider the suspect uncertainty doesn't apply,
  // so we proportionally damp the band by suspect_pct/100.
  const bandFraction =
    MAX_BAND_FRACTION * (1 - meanSuspectConfidence) * (suspectPct / 100);
  const bandHalfWidthRaf = projectedRaf * bandFraction;
  const bandLowRaf = projectedRaf - bandHalfWidthRaf;
  const bandHighRaf = projectedRaf + bandHalfWidthRaf;
  const bandLowRevenue = bandLowRaf * revenuePerRafPoint;
  const bandHighRevenue = bandHighRaf * revenuePerRafPoint;

  const reset = useCallback(() => {
    setSuspectPct(0);
    setRecapturePct(0);
  }, []);

  const suspectSliderId = useId();
  const recaptureSliderId = useId();

  const isDirty = suspectPct !== 0 || recapturePct !== 0;
  const hasLevers =
    sumSuspectCoefficients > 0 || sumRecaptureRafImpact > 0;

  // aria-valuetext describes both the % and the *resulting* projected RAF
  // so screen-reader users get the same live feedback the sighted user
  // gets from the value tiles.
  const suspectAriaValueText = `${suspectPct}% of open suspects accepted, projected RAF ${fmtRaf(projectedRaf)}`;
  const recaptureAriaValueText = `${recapturePct}% of recapture gaps closed, projected RAF ${fmtRaf(projectedRaf)}`;

  return (
    <section
      aria-labelledby="whatif-heading"
      className="rounded-md border border-indigo-200 bg-indigo-50/60 px-4 py-3 dark:border-indigo-900 dark:bg-indigo-950/30"
    >
      <header className="flex items-center gap-2">
        <Sliders className="h-3.5 w-3.5 text-indigo-600 dark:text-indigo-300" aria-hidden />
        <h3
          id="whatif-heading"
          className="text-[11px] font-semibold uppercase tracking-wide text-indigo-900 dark:text-indigo-200"
        >
          What-if scenario simulator
        </h3>
        <span className="ml-auto text-[10px] text-muted-foreground">
          Estimates only · client-side
        </span>
      </header>

      {!hasLevers ? (
        <p className="mt-2 text-xs italic text-muted-foreground">
          No open suspects or recapture gaps to simulate. The projection
          will match the current engine score.
        </p>
      ) : null}

      <div className="mt-3 space-y-3">
        <SliderRow
          id={suspectSliderId}
          label="% of suspects accepted"
          subLabel={
            sumSuspectCoefficients > 0
              ? `Lift if 100% accepted: +${fmtRaf(sumSuspectCoefficients)} RAF · ${fmtUsd(
                  sumSuspectCoefficients * revenuePerRafPoint,
                )}${missingDollarCount > 0 ? ` (${missingDollarCount} suspect${missingDollarCount === 1 ? "" : "s"} awaiting model coefficient)` : ""}`
              : missingDollarCount > 0
              ? `${missingDollarCount} suspect${missingDollarCount === 1 ? "" : "s"} awaiting model coefficient — slider shows % accepted only`
              : "No open suspects with dollar impact"
          }
          value={suspectPct}
          onChange={setSuspectPct}
          ariaValueText={suspectAriaValueText}
          disabled={sumSuspectCoefficients <= 0 && missingDollarCount === 0}
          tone="amber"
        />
        <SliderRow
          id={recaptureSliderId}
          label="% of recapture gaps closed"
          subLabel={
            sumRecaptureRafImpact > 0
              ? `Lift if 100% closed: +${fmtRaf(sumRecaptureRafImpact)} RAF · ${fmtUsd(
                  sumRecaptureRafImpact * revenuePerRafPoint,
                )}`
              : "No open recapture gaps"
          }
          value={recapturePct}
          onChange={setRecapturePct}
          ariaValueText={recaptureAriaValueText}
          disabled={sumRecaptureRafImpact <= 0}
          tone="blue"
        />
      </div>

      <div
        className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2"
        aria-live="polite"
        aria-atomic="true"
      >
        <ResultTile
          label="Projected EOY RAF"
          primary={fmtRaf(projectedRaf)}
          subtitle={
            bandHalfWidthRaf > 0
              ? `Confidence band: ${fmtRaf(bandLowRaf)} – ${fmtRaf(bandHighRaf)} (±${(bandFraction * 100).toFixed(1)}%)`
              : suspectPct === 0
              ? "Move the suspects slider to model confidence uncertainty"
              : "High-confidence suspects · narrow band"
          }
        />
        <ResultTile
          label="Projected annual revenue"
          primary={
            sumSuspectCoefficients <= 0 && missingDollarCount > 0 && suspectPct > 0
              ? "—"
              : fmtUsd(projectedAnnualRevenue)
          }
          subtitle={
            sumSuspectCoefficients <= 0 && missingDollarCount > 0 && suspectPct > 0
              ? "Awaiting model coefficient"
              : bandHalfWidthRaf > 0
              ? `Band: ${fmtUsd(bandLowRevenue)} – ${fmtUsd(bandHighRevenue)} · ${revenueDelta >= 0 ? "+" : ""}${fmtUsd(revenueDelta)} vs current`
              : `${revenueDelta >= 0 ? "+" : ""}${fmtUsd(revenueDelta)} vs current ${fmtUsd(currentAnnualRevenue)}`
          }
          tone={revenueDelta > 0 ? "emerald" : "muted"}
          awaiting={sumSuspectCoefficients <= 0 && missingDollarCount > 0 && suspectPct > 0}
        />
      </div>

      <footer className="mt-3 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <p className="text-[10px] text-muted-foreground">
            Band scales with mean suspect confidence (
            {(meanSuspectConfidence * 100).toFixed(0)}%) — higher confidence
            → narrower band.
          </p>
          <Button
            size="sm"
            variant="ghost"
            onClick={reset}
            disabled={!isDirty}
            aria-label="Reset what-if sliders to zero"
          >
            <RefreshCcw className="h-3 w-3 mr-1.5" aria-hidden />
            Reset
          </Button>
        </div>
        <p
          className="rounded-md border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 px-3 py-1.5 text-[10px] text-amber-800 dark:text-amber-300"
          role="note"
        >
          AI suggestions are decision aids — verify against the chart before accepting.
        </p>
      </footer>
    </section>
  );
}

// ---------------------------------------------------------------------------
// SliderRow — native <input type=range> with proper a11y wiring.
// We use the native control (instead of a custom widget) because it ships
// keyboard support, focus styling, aria-valuemin/max/now, and -- crucially
// -- screen-reader announcements of aria-valuetext for free.
// ---------------------------------------------------------------------------

function SliderRow({
  id,
  label,
  subLabel,
  value,
  onChange,
  ariaValueText,
  disabled,
  tone,
}: {
  id: string;
  label: string;
  subLabel: string;
  value: number;
  onChange: (n: number) => void;
  ariaValueText: string;
  disabled?: boolean;
  tone: "amber" | "blue";
}) {
  const accent =
    tone === "amber"
      ? "accent-amber-500"
      : "accent-sky-500";
  return (
    <div className={cn(disabled && "opacity-60")}>
      <div className="flex items-baseline justify-between gap-2">
        <label
          htmlFor={id}
          className="text-xs font-medium text-foreground"
        >
          {label}
        </label>
        <output
          htmlFor={id}
          className="text-xs font-semibold tabular-nums text-foreground"
        >
          {value}%
        </output>
      </div>
      <input
        id={id}
        type="range"
        min={0}
        max={100}
        step={1}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        disabled={disabled}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value}
        aria-valuetext={ariaValueText}
        className={cn(
          "mt-1 w-full cursor-pointer",
          accent,
          disabled && "cursor-not-allowed",
        )}
      />
      <p className="mt-0.5 text-[10px] text-muted-foreground">{subLabel}</p>
    </div>
  );
}

function ResultTile({
  label,
  primary,
  subtitle,
  tone = "muted",
  awaiting = false,
}: {
  label: string;
  primary: string;
  subtitle: string;
  tone?: "muted" | "emerald";
  /** When true, renders an "Awaiting model coefficient" badge next to the value. */
  awaiting?: boolean;
}) {
  const toneClass =
    tone === "emerald"
      ? "border-emerald-200 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/40"
      : "border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900/60";
  return (
    <div className={`rounded-md border px-3 py-2 ${toneClass}`}>
      <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 flex items-center gap-2">
        <span className="text-base font-bold tabular-nums leading-none text-foreground">
          {primary}
        </span>
        {awaiting && (
          <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-semibold border border-zinc-300 bg-zinc-100 text-zinc-600 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400">
            Awaiting model coefficient
          </span>
        )}
      </div>
      <div className="mt-1 text-[11px] text-muted-foreground">{subtitle}</div>
    </div>
  );
}
