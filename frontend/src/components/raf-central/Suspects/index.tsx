"use client";

import { useMemo, useState } from "react";
import type { SuspectCard } from "../_shared";
import { EmptyState } from "../common/EmptyState";
import { SuspectCardView } from "./SuspectCardView";

/**
 * SuspectsSection — renders the list of open suspect conditions.
 *
 * Layout mirrors Inovalon's "Converged Risk" opportunity ranking:
 * suspects are bucketed by confidence tier (Very High / High / Moderate /
 * Low) with a count badge per bucket. Within each bucket, suspects are
 * still sorted by the meat-completeness-aware combined score so well-
 * documented items float to the top of their tier. Trumped suspects
 * collapse into a dedicated tail bucket because Accept is disabled there
 * — they shouldn't clutter the actionable buckets.
 *
 * Above the confidence buckets we render a row of specialty filter chips
 * (the "ForeSee" pattern): a nephrologist viewing the patient can click
 * "Nephrology" to see only CKD-related suspects; a cardiologist clicks
 * "Cardiology" to see only CHF/MI/AMI; "All" is selected by default.
 * The specialty is derived on the backend from the HCC code (see
 * app/services/specialty_routing.py and SuspectCard.specialty).
 */

type ConfidenceTier = "very_high" | "high" | "moderate" | "low";

interface TierMeta {
  key: ConfidenceTier;
  label: string;
  min: number;
  badge: string; // tailwind class for the count chip background
  rail: string;  // tailwind class for the bucket left rail
}

const TIERS: TierMeta[] = [
  { key: "very_high", label: "Very high confidence", min: 0.85, badge: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200", rail: "border-l-4 border-l-emerald-500" },
  { key: "high",      label: "High confidence",      min: 0.70, badge: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-200",                   rail: "border-l-4 border-l-sky-500" },
  { key: "moderate",  label: "Moderate confidence",  min: 0.50, badge: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",          rail: "border-l-4 border-l-amber-500" },
  { key: "low",       label: "Low confidence",       min: 0.00, badge: "bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200",              rail: "border-l-4 border-l-rose-500" },
];

function tierFor(conf: number): ConfidenceTier {
  for (const t of TIERS) if (conf >= t.min) return t.key;
  return "low";
}

// Canonical specialty bucket vocabulary — mirrors
// app/services/specialty_routing.py:SPECIALTY_BUCKETS. Keep order roughly in
// line with chronic-disease prevalence (cardio / nephro / endo / pulm / onc /
// behavioral) so the chip row reads naturally for a PCP.
const SPECIALTY_ORDER = [
  "cardiology",
  "nephrology",
  "endocrinology",
  "pulmonology",
  "oncology",
  "behavioral",
  "general",
] as const;

type SpecialtyKey = (typeof SPECIALTY_ORDER)[number];

const SPECIALTY_LABELS: Record<SpecialtyKey, string> = {
  cardiology: "Cardiology",
  nephrology: "Nephrology",
  endocrinology: "Endocrinology",
  pulmonology: "Pulmonology",
  oncology: "Oncology",
  behavioral: "Behavioral",
  general: "General",
};

function specialtyOf(s: SuspectCard): SpecialtyKey {
  const raw = (s.specialty || "general").toLowerCase();
  return (SPECIALTY_ORDER as readonly string[]).includes(raw)
    ? (raw as SpecialtyKey)
    : "general";
}

export function SuspectsSection({
  patientId,
  suspects,
  onChange,
  modelVersion,
  measurementYear,
}: {
  patientId: number;
  suspects: SuspectCard[];
  onChange: () => void;
  /** Forwarded to AcceptConfirmDialog so clinicians see which CMS-HCC model
   *  governs the diagnosis they are about to attest under. */
  modelVersion?: string | null;
  measurementYear?: number | null;
}) {
  // "all" = no filter (default). Otherwise restrict to a single specialty
  // bucket. The chip row is rendered as toggles so clicking the active chip
  // returns to "all" — matches the ForeSee UX clinicians are used to.
  const [activeSpecialty, setActiveSpecialty] = useState<SpecialtyKey | "all">("all");

  // Per-bucket counts across the *full* (unfiltered) suspect list so the
  // chip badges don't change as you click around. A chip with count 0 is
  // hidden — no point letting clinicians click into an empty bucket.
  const specialtyCounts = useMemo(() => {
    const counts: Record<SpecialtyKey, number> = {
      cardiology: 0, nephrology: 0, endocrinology: 0, pulmonology: 0,
      oncology: 0, behavioral: 0, general: 0,
    };
    for (const s of suspects) counts[specialtyOf(s)] += 1;
    return counts;
  }, [suspects]);

  if (!suspects.length)
    return (
      <EmptyState
        variant="default"
        title="No open suspects"
        subtitle="The engine has not flagged any unbilled HCC opportunities for this patient at the moment."
      />
    );

  // Apply the active specialty filter before bucketing by confidence.
  const visible =
    activeSpecialty === "all"
      ? suspects
      : suspects.filter((s) => specialtyOf(s) === activeSpecialty);

  // Combined priority used to rank suspects *within* each tier — the same
  // meat-completeness-aware score the previous flat sort used. Trumped
  // suspects always sink so they cannot mask actionable items.
  const score = (s: SuspectCard) => (s.confidence ?? 0) * (0.5 + 0.5 * (s.meat_completeness ?? 0));

  const trumped: SuspectCard[] = [];
  const byTier: Record<ConfidenceTier, SuspectCard[]> = {
    very_high: [], high: [], moderate: [], low: [],
  };
  for (const s of visible) {
    if (s.trumped_by_hcc != null) {
      trumped.push(s);
      continue;
    }
    byTier[tierFor(s.confidence ?? 0)].push(s);
  }
  for (const k of Object.keys(byTier) as ConfidenceTier[]) {
    byTier[k].sort((a, b) => score(b) - score(a));
  }
  trumped.sort((a, b) => score(b) - score(a));

  const renderBucket = (tier: TierMeta, items: SuspectCard[]) => {
    if (!items.length) return null;
    return (
      <section key={tier.key} aria-label={`${tier.label} suspects`} className="space-y-2">
        <div className={`flex items-center gap-2 pl-3 ${tier.rail}`}>
          <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            {tier.label}
          </h3>
          <span className={`inline-flex h-5 min-w-[20px] items-center justify-center rounded-full px-1.5 text-[10px] font-semibold tabular-nums ${tier.badge}`}>
            {items.length}
          </span>
        </div>
        <div className="space-y-2 pl-3">
          {items.map((s) => (
            <SuspectCardView
              key={s.id}
              suspect={s}
              patientId={patientId}
              onChange={onChange}
              modelVersion={modelVersion}
              measurementYear={measurementYear}
            />
          ))}
        </div>
      </section>
    );
  };

  // Chip styling — emulates a segmented control. The active chip uses the
  // primary tone; idle chips use neutral muted tones. Counts sit in a
  // tabular-nums badge so the row doesn't reflow when filtering.
  const chipBase =
    "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[11px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-1 focus-visible:ring-sky-500";
  const chipIdle =
    "border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300 dark:hover:bg-zinc-800";
  const chipActive =
    "border-sky-600 bg-sky-600 text-white hover:bg-sky-600 dark:border-sky-500 dark:bg-sky-500";
  const countIdle =
    "inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-zinc-100 px-1 text-[10px] font-semibold tabular-nums text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300";
  const countActive =
    "inline-flex h-4 min-w-[16px] items-center justify-center rounded-full bg-white/25 px-1 text-[10px] font-semibold tabular-nums text-white";

  const visibleSpecialties = SPECIALTY_ORDER.filter(
    (key) => specialtyCounts[key] > 0,
  );

  return (
    <div className="space-y-4">
      {/* Specialty filter chips — only render when there's more than one
          specialty represented (otherwise the row would be a single chip
          plus "All" which is just noise). */}
      {visibleSpecialties.length > 1 && (
        <div
          role="toolbar"
          aria-label="Filter suspects by specialty"
          className="flex flex-wrap items-center gap-1.5"
        >
          <button
            type="button"
            onClick={() => setActiveSpecialty("all")}
            aria-pressed={activeSpecialty === "all"}
            className={`${chipBase} ${activeSpecialty === "all" ? chipActive : chipIdle}`}
          >
            <span>All</span>
            <span className={activeSpecialty === "all" ? countActive : countIdle}>
              {suspects.length}
            </span>
          </button>
          {visibleSpecialties.map((key) => {
            const isActive = activeSpecialty === key;
            return (
              <button
                key={key}
                type="button"
                onClick={() => setActiveSpecialty(isActive ? "all" : key)}
                aria-pressed={isActive}
                className={`${chipBase} ${isActive ? chipActive : chipIdle}`}
              >
                <span>{SPECIALTY_LABELS[key]}</span>
                <span className={isActive ? countActive : countIdle}>
                  {specialtyCounts[key]}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {/* Empty-state for an over-narrow filter — keeps the chip row visible
          so the clinician can click back to "All" without losing context. */}
      {visible.length === 0 ? (
        <EmptyState
          variant="neutral"
          title={`No ${activeSpecialty === "all" ? "" : SPECIALTY_LABELS[activeSpecialty as SpecialtyKey].toLowerCase() + " "}suspects`}
          subtitle="Try clearing the specialty filter to see all open suspects."
        />
      ) : (
        <>
          {TIERS.map((t) => renderBucket(t, byTier[t.key]))}
          {trumped.length > 0 && (
            <section aria-label="Hierarchically trumped suspects" className="space-y-2 opacity-70">
              <div className="flex items-center gap-2 pl-3 border-l-4 border-l-zinc-400">
                <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Trumped by hierarchy
                </h3>
                <span className="inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-zinc-200 px-1.5 text-[10px] font-semibold tabular-nums text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                  {trumped.length}
                </span>
                <span className="text-[10px] text-muted-foreground italic">— Accept disabled; V28 will drop these at scoring time</span>
              </div>
              <div className="space-y-2 pl-3">
                {trumped.map((s) => (
                  <SuspectCardView
                    key={s.id}
                    suspect={s}
                    patientId={patientId}
                    onChange={onChange}
                    modelVersion={modelVersion}
                    measurementYear={measurementYear}
                  />
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
