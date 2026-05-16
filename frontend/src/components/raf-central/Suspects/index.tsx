"use client";

import type { SuspectCard } from "../_shared";
import { EmptyState } from "../common/EmptyState";
import { SuspectCardView } from "./SuspectCardView";

/**
 * SuspectsSection — renders the list of open suspect conditions.
 */
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

  // Rank suspects by a clinical-signal-aware score so high-confidence
  // suspects with strong MEAT evidence float above high-confidence
  // suspects with thin documentation. Trumped HCCs sink to the bottom
  // (Accept is disabled on them anyway). Patient-safety review round-5
  // blocker #1: backend now ships `meat_completeness` and
  // `trumped_by_hcc`; the UI must actually use them.
  const ranked = [...suspects].sort((a, b) => {
    const aTrumped = a.trumped_by_hcc != null;
    const bTrumped = b.trumped_by_hcc != null;
    if (aTrumped !== bTrumped) return aTrumped ? 1 : -1;
    const aMeat = a.meat_completeness ?? 0;
    const bMeat = b.meat_completeness ?? 0;
    const aConf = a.confidence ?? 0;
    const bConf = b.confidence ?? 0;
    // Combined priority: confidence weighted by (0.5 + 0.5 × meat_pct).
    // A suspect with 90% confidence + 100% MEAT outranks one with 90%
    // confidence + 0% MEAT (0.90 vs 0.45 in the combined score).
    const aScore = aConf * (0.5 + 0.5 * aMeat);
    const bScore = bConf * (0.5 + 0.5 * bMeat);
    return bScore - aScore;
  });

  return (
    <div className="space-y-2">
      {ranked.map((s) => (
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
  );
}
