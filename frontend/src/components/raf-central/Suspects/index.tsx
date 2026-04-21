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
}: {
  patientId: number;
  suspects: SuspectCard[];
  onChange: () => void;
}) {
  if (!suspects.length)
    return (
      <EmptyState
        variant="success"
        title="No open suspects"
        subtitle="Run a suspect scan from the patient page to discover HCC lift."
      />
    );

  return (
    <div className="space-y-2">
      {suspects.map((s) => (
        <SuspectCardView
          key={s.id}
          suspect={s}
          patientId={patientId}
          onChange={onChange}
        />
      ))}
    </div>
  );
}
