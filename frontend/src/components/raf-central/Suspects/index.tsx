"use client";

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
  if (!suspects.length)
    return (
      <EmptyState
        variant="default"
        title="No open suspects"
        subtitle="The engine has not flagged any unbilled HCC opportunities for this patient at the moment."
      />
    );

  // Combined priority used to rank suspects *within* each tier — the same
  // meat-completeness-aware score the previous flat sort used. Trumped
  // suspects always sink so they cannot mask actionable items.
  const score = (s: SuspectCard) => (s.confidence ?? 0) * (0.5 + 0.5 * (s.meat_completeness ?? 0));

  const trumped: SuspectCard[] = [];
  const byTier: Record<ConfidenceTier, SuspectCard[]> = {
    very_high: [], high: [], moderate: [], low: [],
  };
  for (const s of suspects) {
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

  return (
    <div className="space-y-4">
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
    </div>
  );
}
