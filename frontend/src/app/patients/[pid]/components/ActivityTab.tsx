"use client";

import React, { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { getPatientActivity, type PatientActivityEntry } from "@/lib/api";
import { C, Card } from "./shared";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Humanise a SCREAMING_SNAKE_CASE audit action into a coder-friendly phrase.
 *
 * Designed for the patient activity feed (PCP review #8 carry-over).  The
 * map covers the actions we emit today; unknown actions fall back to a
 * "Title Cased" rendering of the underscored words so a new action never
 * shows up as raw UPPERCASE in the timeline.
 */
const ACTION_LABEL: Record<string, string> = {
  CLINICAL_QUERY_CREATED: "asked for documentation",
  CLINICAL_QUERY_REPLIED: "answered a documentation query",
  CLINICAL_QUERY_CLOSED: "closed a documentation query",
  CLINICAL_QUERY_CANCELLED: "withdrew a documentation query",
  SUSPECT_ACCEPTED: "accepted a suspect condition",
  SUSPECT_DISMISSED: "dismissed a suspect condition",
  SUSPECT_DEFERRED: "deferred a suspect condition",
  AUDIT_PACKAGE_GENERATED: "generated an audit package",
  RADV_PACKET_DOWNLOADED: "downloaded a RADV packet",
  RAF_RECALCULATED: "recalculated the RAF score",
  ENCOUNTER_ANALYZED: "ran AI analysis on an encounter",
  ATTESTATION_CREATED: "created an attestation",
  ATTESTATION_SIGNED: "signed an attestation",
  DISPUTE_FILED: "filed a dispute",
  // PHI access (audit_log writes "phi_view", "phi_analyze", etc.)
  phi_view: "viewed PHI",
  phi_analyze: "ran AI analysis",
  phi_export: "exported PHI",
  phi_search: "searched PHI",
  phi_list: "listed PHI",
  phi_batch_analyze: "ran batch AI analysis",
};

function humaniseAction(action: string): string {
  if (ACTION_LABEL[action]) return ACTION_LABEL[action];
  // Title-case fallback: CLINICAL_QUERY_CREATED → "Clinical Query Created"
  return action
    .toLowerCase()
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/**
 * Build a "MK" style initials avatar string from a display name or email.
 * Falls back to a single bullet so the avatar slot is never empty.
 */
function initialsFor(name: string | null | undefined, email: string | null | undefined): string {
  const source = (name && name.trim()) || (email ? email.split("@", 1)[0] : "");
  if (!source) return "•";
  const parts = source.split(/[\s._-]+/).filter(Boolean);
  if (parts.length === 0) return source.charAt(0).toUpperCase();
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0].charAt(0) + parts[parts.length - 1].charAt(0)).toUpperCase();
}

/**
 * Deterministic colour pick for an avatar.  Hash the display string so the
 * same actor always lands on the same swatch.  Five-colour palette tuned
 * to the rest of the patient-detail page.
 */
const AVATAR_PALETTE = [
  { bg: "#DBEAFE", fg: "#1D4ED8" }, // blue
  { bg: "#D1FAE5", fg: "#047857" }, // emerald
  { bg: "#FEF3C7", fg: "#B45309" }, // amber
  { bg: "#F3E8FF", fg: "#7E22CE" }, // purple
  { bg: "#FECACA", fg: "#B91C1C" }, // red
];
function avatarColor(seed: string): { bg: string; fg: string } {
  let h = 0;
  for (let i = 0; i < seed.length; i++) {
    h = (h * 31 + seed.charCodeAt(i)) & 0xffffffff;
  }
  return AVATAR_PALETTE[Math.abs(h) % AVATAR_PALETTE.length];
}

/**
 * Relative-time formatter (e.g. "2 min ago", "3 hr ago").  Falls back to a
 * locale date string beyond ~30 days so a 2-year-old row doesn't show as
 * "750 days ago".
 */
function relativeTime(iso: string): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const now = Date.now();
  const diffSec = Math.round((now - then) / 1000);
  if (diffSec < 0) return "in the future";
  if (diffSec < 45) return "just now";
  if (diffSec < 90) return "a minute ago";
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 45) return `${diffMin} min ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr} hr ago`;
  const diffDay = Math.round(diffHr / 24);
  if (diffDay < 30) return `${diffDay} day${diffDay === 1 ? "" : "s"} ago`;
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/** Group key: YYYY-MM-DD (UTC). Stable across timezones for the header label. */
function dayKey(iso: string): string {
  if (!iso) return "Unknown";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10) || "Unknown";
  return d.toISOString().slice(0, 10);
}

/** Friendly day header — "Today", "Yesterday", or e.g. "Tue, May 14, 2026". */
function dayHeaderLabel(key: string): string {
  if (key === "Unknown") return "Unknown date";
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  const todayKey = today.toISOString().slice(0, 10);
  const yesterdayKey = yesterday.toISOString().slice(0, 10);
  if (key === todayKey) return "Today";
  if (key === yesterdayKey) return "Yesterday";
  const d = new Date(key + "T00:00:00Z");
  return d.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ActorAvatar({
  name,
  email,
}: {
  name: string | null | undefined;
  email: string | null | undefined;
}) {
  const seed = (name || email || "?").toLowerCase();
  const swatch = avatarColor(seed);
  return (
    <div
      aria-hidden
      style={{
        width: 36,
        height: 36,
        borderRadius: "50%",
        background: swatch.bg,
        color: swatch.fg,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 12,
        fontWeight: 700,
        flexShrink: 0,
        border: `2px solid ${C.white}`,
        boxShadow: `0 0 0 2px ${C.slate200}`,
        zIndex: 1,
      }}
    >
      {initialsFor(name, email)}
    </div>
  );
}

/**
 * Render a compact "k=v" chip strip from the metadata blob.  Filters keys
 * that don't add user-facing signal (hashes, subject_id duplicates) and caps
 * each value at ~32 chars so the row doesn't overflow.
 */
function MetadataChips({ metadata }: { metadata: Record<string, unknown> }) {
  const items = useMemo(() => {
    const HIDE = new Set([
      "subject_id",
      "hash_prev",
      "hash_self",
      "previous_hash",
      "current_hash",
      "tenant_id",
      "details",
      "raw",
    ]);
    const out: Array<{ key: string; value: string }> = [];
    for (const [k, v] of Object.entries(metadata || {})) {
      if (HIDE.has(k)) continue;
      if (v === null || v === undefined || v === "") continue;
      let str: string;
      if (typeof v === "object") {
        try {
          str = JSON.stringify(v);
        } catch {
          str = String(v);
        }
      } else {
        str = String(v);
      }
      if (str.length > 32) str = str.slice(0, 32) + "…";
      out.push({ key: k, value: str });
      if (out.length >= 4) break;
    }
    return out;
  }, [metadata]);

  if (items.length === 0) return null;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
      {items.map((c) => (
        <span
          key={c.key}
          style={{
            display: "inline-flex",
            alignItems: "center",
            padding: "2px 8px",
            borderRadius: 6,
            background: C.slate100,
            color: C.slate600,
            fontSize: 11,
            fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
            border: `1px solid ${C.slate200}`,
          }}
        >
          <span style={{ color: C.slate500, fontWeight: 600 }}>{c.key}</span>
          <span style={{ margin: "0 4px", color: C.slate400 }}>=</span>
          <span>{c.value}</span>
        </span>
      ))}
    </div>
  );
}

/**
 * Loading skeleton — three faux rows matching the real row layout so the
 * tab doesn't shift when data arrives.
 */
function LoadingSkeleton() {
  return (
    <div
      role="status"
      aria-label="Loading patient activity"
      style={{ display: "flex", flexDirection: "column", gap: 16 }}
    >
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          style={{
            display: "flex",
            gap: 12,
            alignItems: "flex-start",
            padding: "12px 0",
          }}
        >
          <div
            className="skeleton-shimmer"
            style={{
              width: 36,
              height: 36,
              borderRadius: "50%",
              background: C.slate100,
              flexShrink: 0,
            }}
          />
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6 }}>
            <div
              className="skeleton-shimmer"
              style={{ height: 12, width: "60%", background: C.slate100, borderRadius: 4 }}
            />
            <div
              className="skeleton-shimmer"
              style={{ height: 10, width: "30%", background: C.slate100, borderRadius: 4 }}
            />
          </div>
        </div>
      ))}
      <style>{`
        .skeleton-shimmer {
          background: linear-gradient(90deg, ${C.slate100} 0%, ${C.slate200} 50%, ${C.slate100} 100%);
          background-size: 200% 100%;
          animation: shimmer 1.4s ease-in-out infinite;
        }
        @keyframes shimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
      `}</style>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main tab
// ---------------------------------------------------------------------------

export function ActivityTab({ pid }: { pid: string | number }) {
  // react-query with a 30 s stale window — the feed is append-only so a
  // short cache doesn't risk staleness, and we still refresh on focus so
  // a coder coming back to the tab gets the latest events.
  const activityQ = useQuery({
    queryKey: ["patient-activity", String(pid)],
    queryFn: () => getPatientActivity(pid, { limit: 100 }),
    staleTime: 30_000,
    refetchOnWindowFocus: true,
  });

  // Group events by ISO day key for the date headers.
  const grouped = useMemo(() => {
    const items: PatientActivityEntry[] = activityQ.data?.items ?? [];
    const map = new Map<string, PatientActivityEntry[]>();
    for (const item of items) {
      const key = dayKey(item.created_at);
      const bucket = map.get(key);
      if (bucket) bucket.push(item);
      else map.set(key, [item]);
    }
    // Map insertion order matches the server's DESC ordering — preserve it.
    return Array.from(map.entries());
  }, [activityQ.data]);

  return (
    <div style={{ maxWidth: 820 }}>
      <Card className="animate-slide-up stagger-1">
        <header style={{ marginBottom: 20 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: C.slate900 }}>
            Activity feed
          </h3>
          <p style={{ margin: "4px 0 0", fontSize: 13, color: C.slate500 }}>
            Who touched this chart, and when.  Sourced from the immutable
            audit log — read-only.
          </p>
        </header>

        {activityQ.isLoading ? (
          <LoadingSkeleton />
        ) : activityQ.isError ? (
          <div
            role="alert"
            style={{
              padding: 16,
              borderRadius: 8,
              border: `1px solid ${C.amber500}`,
              background: C.amber50,
              color: C.amber600,
              fontSize: 13,
            }}
          >
            Could not load activity for this patient. Try refreshing the page.
          </div>
        ) : (activityQ.data?.items.length ?? 0) === 0 ? (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              padding: "48px 0",
              gap: 12,
              color: C.slate500,
            }}
          >
            <svg
              width="36"
              height="36"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden
            >
              <circle cx="12" cy="12" r="9" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <div style={{ fontSize: 14, fontWeight: 600, color: C.slate700 }}>
              No activity recorded yet for this patient
            </div>
            <div style={{ fontSize: 12, color: C.slate400, maxWidth: 360, textAlign: "center" }}>
              Documentation queries, suspect decisions, and chart accesses will
              appear here as they happen.
            </div>
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
            {grouped.map(([day, rows]) => (
              <section key={day} aria-label={dayHeaderLabel(day)}>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    marginBottom: 8,
                  }}
                >
                  <h4
                    style={{
                      margin: 0,
                      fontSize: 11,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      letterSpacing: "0.06em",
                      color: C.slate500,
                    }}
                  >
                    {dayHeaderLabel(day)}
                  </h4>
                  <div
                    style={{
                      flex: 1,
                      height: 1,
                      background: C.slate200,
                    }}
                    aria-hidden
                  />
                  <span style={{ fontSize: 11, color: C.slate400, fontWeight: 500 }}>
                    {rows.length} event{rows.length === 1 ? "" : "s"}
                  </span>
                </div>
                <ol
                  style={{
                    listStyle: "none",
                    margin: 0,
                    padding: 0,
                    position: "relative",
                  }}
                >
                  {/* Spine — drawn behind each row's avatar. */}
                  <div
                    aria-hidden
                    style={{
                      position: "absolute",
                      left: 17,
                      top: 18,
                      bottom: 18,
                      width: 2,
                      background: C.slate200,
                    }}
                  />
                  {rows.map((event) => {
                    const display =
                      event.actor_display_name || event.actor_email || "system";
                    const verb = humaniseAction(event.action);
                    return (
                      <li
                        key={event.id}
                        style={{
                          display: "flex",
                          gap: 12,
                          alignItems: "flex-start",
                          padding: "8px 0",
                        }}
                      >
                        <ActorAvatar
                          name={event.actor_display_name}
                          email={event.actor_email}
                        />
                        <div style={{ flex: 1, minWidth: 0, paddingTop: 2 }}>
                          <div
                            style={{
                              display: "flex",
                              flexWrap: "wrap",
                              alignItems: "baseline",
                              gap: 6,
                            }}
                          >
                            <span
                              style={{
                                fontSize: 13,
                                fontWeight: 600,
                                color: C.slate900,
                              }}
                            >
                              {display}
                            </span>
                            <span style={{ fontSize: 13, color: C.slate600 }}>
                              {verb}
                            </span>
                            {event.resource_type && (
                              <span
                                style={{
                                  fontSize: 11,
                                  fontWeight: 600,
                                  color: C.slate500,
                                  padding: "1px 6px",
                                  borderRadius: 4,
                                  background: C.slate100,
                                  border: `1px solid ${C.slate200}`,
                                }}
                              >
                                {event.resource_type}
                                {event.resource_id ? ` #${event.resource_id}` : ""}
                              </span>
                            )}
                          </div>
                          <div
                            style={{
                              fontSize: 12,
                              color: C.slate400,
                              marginTop: 2,
                            }}
                            title={event.created_at}
                          >
                            <time dateTime={event.created_at}>
                              {relativeTime(event.created_at)}
                            </time>
                          </div>
                          <MetadataChips metadata={event.metadata} />
                        </div>
                      </li>
                    );
                  })}
                </ol>
              </section>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
