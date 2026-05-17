"use client";

/**
 * RecentActivitySection
 * ---------------------
 * Wraps the audit-log activity timeline in a collapsible Section for the
 * RAF Central panel. Self-hides when the upstream
 * `GET /api/patients/{pid}/activity` endpoint returns 404 so the panel
 * doesn't show a stale, empty card before agent A4's backend ships.
 *
 * Owning the visibility state inside this leaf component (rather than
 * threading it back up to RAFCentralPanel via a callback) lets the
 * parent stay declarative — render the component, key it by patientId
 * for natural reset — and keeps lint clean (no setState-in-effect in
 * the parent).
 */

import { type ReactNode } from "react";
import { Section } from "./Section";
import {
  PatientActivityTimeline,
  usePatientActivity,
  ActivityEndpointMissingError,
} from "./ActivityFeed";

export function RecentActivitySection({
  patientId,
  icon,
  limit = 10,
}: {
  patientId: number;
  icon?: ReactNode;
  limit?: number;
}) {
  // Pre-flight the query so the section can decide whether to render
  // *before* mounting the timeline. React Query dedupes — the timeline
  // mounts and re-uses the same cache entry.
  //
  // `hidden` is derived synchronously from React Query state — no local
  // useState/useEffect required. When `patientId` changes the consumer
  // is expected to key this component on patientId (see RAFCentralPanel),
  // which gives a fresh React Query instance with isError=false.
  const { isError, error } = usePatientActivity(patientId, limit);
  const hidden = isError && error instanceof ActivityEndpointMissingError;

  if (hidden) return null;

  return (
    <Section title="Recent activity" icon={icon} severity="low">
      <PatientActivityTimeline patientId={patientId} limit={limit} />
    </Section>
  );
}
