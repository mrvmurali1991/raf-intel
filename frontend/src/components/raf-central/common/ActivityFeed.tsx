"use client";

/**
 * ActivityFeed
 * ------------
 * Renders a vertical timeline of recent audit-log rows for a patient.
 * Backed by `GET /api/patients/{pid}/activity?limit={n}`.
 *
 * Expected response shape (matches the audit_log columns plus a joined
 * actor email — confirmed by the audit router patterns in
 * backend/app/routers/audit.py):
 *
 *   {
 *     "items": [
 *       {
 *         "id":            123,
 *         "actor_email":   "clinician@example.com" | null,
 *         "action":        "raf.recalculate" | "meat.evidence.attach" | …,
 *         "resource_type": "patient" | "meat_gap" | …,
 *         "resource_id":   "42",
 *         "created_at":    "2026-05-16T12:34:56Z",
 *         "details":       { … } | null
 *       },
 *       …
 *     ]
 *   }
 *
 * Graceful degradation:
 *   - 404 → caller hides the wrapping section entirely (`onMissing`).
 *   - 401/403/5xx → render "Unable to load activity." inline.
 *   - Empty list → render "No activity recorded yet."
 *
 * Implementation uses React Query so the fetch state is owned outside
 * the render path — this avoids the `react-hooks/set-state-in-effect`
 * lint rule and lets the worklist hover-card share the same cache when
 * the user opens the panel for a patient they just hovered.
 */

import { useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";
import api from "@/lib/api";
import { cn } from "@/lib/utils";

export interface ActivityItem {
  id: number;
  actor_email: string | null;
  action: string;
  resource_type?: string | null;
  resource_id?: string | null;
  created_at: string;
  details?: Record<string, unknown> | null;
}

interface ActivityResponse {
  items: ActivityItem[];
}

/**
 * Tagged error so React Query consumers can distinguish "endpoint not
 * deployed" (hide the surface) from "endpoint exists but failed" (show
 * a small inline message).
 */
export class ActivityEndpointMissingError extends Error {
  constructor() {
    super("activity endpoint missing (404)");
    this.name = "ActivityEndpointMissingError";
  }
}

/**
 * Human-readable label for an action key. Falls back to the raw key if
 * not recognised so new server-side actions still render.
 */
export function formatActionLabel(action: string): string {
  const known: Record<string, string> = {
    "raf.recalculate":          "Recalculated RAF",
    "raf.score.calculated":     "RAF score calculated",
    "meat.evidence.attach":     "Attached MEAT evidence",
    "meat.evidence.remove":     "Removed MEAT evidence",
    "meat.gap.complete":        "Closed MEAT gap",
    "suspect.accept":           "Accepted suspect condition",
    "suspect.dismiss":          "Dismissed suspect condition",
    "suspect.restore":          "Restored suspect condition",
    "patient.view":             "Viewed patient",
    "patient.update":           "Updated patient",
    "encounter.create":         "Created encounter",
    "attestation.signed":       "Signed attestation",
    "audit.package.generated":  "Generated audit package",
  };
  if (known[action]) return known[action];
  // Fallback — turn "foo.bar_baz" into "Foo bar baz"
  const pretty = action.replace(/[._]/g, " ").trim();
  return pretty.charAt(0).toUpperCase() + pretty.slice(1);
}

/** Compact relative-time formatter mirroring AdminDashboard.tsx `timeAgo`. */
export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = Date.now() - t;
  if (diff < 0) return "just now";
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return `${sec}s ago`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day}d ago`;
  const mo = Math.floor(day / 30);
  if (mo < 12) return `${mo}mo ago`;
  return `${Math.floor(mo / 12)}y ago`;
}

export const PATIENT_ACTIVITY_QUERY_KEY = (pid: number, limit: number) =>
  ["patient-activity", pid, limit] as const;

async function fetchActivity(pid: number, limit: number): Promise<ActivityItem[]> {
  try {
    const { data } = await api.get<ActivityResponse>(
      `/api/patients/${pid}/activity`,
      { params: { limit } },
    );
    return Array.isArray(data?.items) ? data.items : [];
  } catch (err) {
    if (isAxiosError(err) && err.response?.status === 404) {
      throw new ActivityEndpointMissingError();
    }
    throw err;
  }
}

/**
 * Shared React Query hook used by both the panel timeline and the
 * worklist hover card. Disabled until `enabled` is true so the
 * hover-card can pre-stage the call but only kick it off after the
 * dwell timer fires. 404 is treated as a permanent miss — retry=false
 * so a missing endpoint doesn't generate three network round-trips.
 */
export function usePatientActivity(pid: number | null | undefined, limit: number, enabled = true) {
  return useQuery<ActivityItem[]>({
    queryKey: PATIENT_ACTIVITY_QUERY_KEY(Number(pid), limit),
    queryFn: () => fetchActivity(Number(pid), limit),
    enabled: enabled && typeof pid === "number" && pid > 0,
    // Audit rows only grow; a 30s freshness window is plenty for a
    // sidebar/hover surface and avoids hammering the API as the user
    // scrubs through the worklist.
    staleTime: 30_000,
    retry: (failureCount, error) => {
      if (error instanceof ActivityEndpointMissingError) return false;
      return failureCount < 1;
    },
  });
}

/**
 * Vertical-timeline renderer used by RAFCentralPanel. Renders the last
 * `limit` rows, or "No activity recorded yet." when empty. The wrapping
 * Section in the panel is responsible for deciding whether to render
 * this component at all (it removes itself entirely on 404), so we
 * simply render nothing if the missing-endpoint error slips through.
 */
export function PatientActivityTimeline({
  patientId,
  limit = 10,
}: {
  patientId: number;
  limit?: number;
}) {
  const { data, isLoading, isError, error } = usePatientActivity(patientId, limit);
  const missing = isError && error instanceof ActivityEndpointMissingError;

  if (missing) {
    return null;
  }
  if (isLoading) {
    return (
      <div className="py-3 text-xs text-muted-foreground" aria-live="polite">
        Loading activity…
      </div>
    );
  }
  if (isError) {
    return (
      <div className="py-3 text-xs text-muted-foreground">
        Unable to load activity.
      </div>
    );
  }
  if (!data || data.length === 0) {
    return (
      <div className="py-3 text-xs text-muted-foreground">
        No activity recorded yet.
      </div>
    );
  }

  return (
    <ol className="relative ml-2 border-l border-border pl-4 pt-1" aria-label="Recent patient activity">
      {data.map((it, idx) => (
        <li
          key={it.id}
          className={cn(
            "relative pb-3 last:pb-0",
            idx === 0 && "pt-0",
          )}
        >
          {/* Timeline dot */}
          <span
            aria-hidden
            className="absolute -left-[21px] top-1 inline-block h-2 w-2 rounded-full border border-background bg-slate-400 dark:bg-slate-500"
          />
          <div className="text-xs font-medium text-foreground leading-tight">
            {formatActionLabel(it.action)}
          </div>
          <div className="mt-0.5 text-[11px] text-muted-foreground leading-tight">
            <span className="truncate">{it.actor_email || "system"}</span>
            <span className="mx-1.5 text-border">·</span>
            <span title={new Date(it.created_at).toLocaleString()}>
              {formatRelativeTime(it.created_at)}
            </span>
          </div>
        </li>
      ))}
    </ol>
  );
}
