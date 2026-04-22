"use client";

/**
 * MEATBadge — renders the M / E / A / T evidence circles for a condition.
 *
 * Optional provenance props (all undefined-safe; existing callers need no changes):
 *   - `source`        — who produced the evidence: "llm" | "regex" | "manual"
 *   - `confidence`    — float 0–1; rendered as colour-coded percentage in the tooltip
 *   - `evidence_date` — ISO-8601 date string; rendered as a human-readable age ("2 days ago", "stale (>6mo)")
 */

import type { MEATEvidence } from "@/types";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Returns a human-readable age string from an ISO-8601 date, or null if the
 *  input is absent / unparseable. Uses only built-in Date arithmetic. */
function evidenceAge(dateStr: string | undefined | null): string | null {
  if (!dateStr) return null;
  const then = new Date(dateStr);
  if (isNaN(then.getTime())) return null;
  const diffMs = Date.now() - then.getTime();
  const days = Math.floor(diffMs / 86_400_000);
  if (days < 0) return null;
  if (days === 0) return "today";
  if (days === 1) return "1 day ago";
  if (days < 7) return `${days} days ago`;
  const weeks = Math.floor(days / 7);
  if (weeks < 5) return weeks === 1 ? "1 week ago" : `${weeks} weeks ago`;
  const months = Math.floor(days / 30);
  if (months < 6) return months === 1 ? "1 month ago" : `${months} months ago`;
  return "stale (>6mo)";
}

/** Maps a 0–1 confidence value to a Tailwind colour class set. */
function confidenceColors(confidence: number): { bg: string; text: string } {
  if (confidence >= 0.8) return { bg: "bg-green-100 dark:bg-green-900", text: "text-green-800 dark:text-green-200" };
  if (confidence >= 0.5) return { bg: "bg-amber-100 dark:bg-amber-900", text: "text-amber-800 dark:text-amber-200" };
  return { bg: "bg-red-100 dark:bg-red-900", text: "text-red-800 dark:text-red-200" };
}

const SOURCE_LABEL: Record<string, string> = {
  llm: "AI",
  regex: "Rule",
  manual: "Manual",
};

// ---------------------------------------------------------------------------
// Letters config
// ---------------------------------------------------------------------------

const letters: {
  key: keyof MEATEvidence;
  label: string;
  full: string;
  filledColor: string;
  filledBg: string;
}[] = [
  { key: "monitor", label: "M", full: "Monitor",  filledColor: "text-teal-700 dark:text-teal-200",   filledBg: "bg-teal-500 dark:bg-teal-600"   },
  { key: "evaluate", label: "E", full: "Evaluate", filledColor: "text-purple-700 dark:text-purple-200", filledBg: "bg-purple-500 dark:bg-purple-600" },
  { key: "assess",   label: "A", full: "Addressed",filledColor: "text-amber-700 dark:text-amber-200",  filledBg: "bg-amber-500 dark:bg-amber-600"  },
  { key: "treat",    label: "T", full: "Treat",    filledColor: "text-green-700 dark:text-green-200",  filledBg: "bg-green-500 dark:bg-green-600"  },
];

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface MEATBadgeProps {
  evidence?: MEATEvidence | null;
  /** Who produced the evidence. "llm" shows as "AI", "regex" as "Rule". */
  source?: "llm" | "regex" | "manual";
  /** Model / rule confidence, 0–1. Rendered as a colour-coded percentage. */
  confidence?: number;
  /** ISO-8601 date of the underlying clinical note. Shown as relative age. */
  evidence_date?: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function MEATBadge({
  evidence,
  source,
  confidence,
  evidence_date,
}: MEATBadgeProps) {
  const rawExcerpt = evidence?.raw_note_excerpt;
  const ageLabel = evidenceAge(evidence_date);
  const sourceLabel = source ? SOURCE_LABEL[source] : undefined;
  const confColors = confidence !== undefined ? confidenceColors(confidence) : undefined;
  const confPct = confidence !== undefined ? Math.round(confidence * 100) : undefined;

  // Build a combined a11y description for the provenance chips
  const provenanceAriaLabel = [
    sourceLabel ? `${sourceLabel}-validated evidence` : null,
    confPct !== undefined ? `confidence ${confPct}%` : null,
    ageLabel ? `evidence ${ageLabel}` : null,
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <div className="flex gap-1">
      {letters.map(({ key, label, full, filledBg }) => {
        const filled = evidence && evidence[key];
        return (
          <Tooltip key={key}>
            <TooltipTrigger
              className={cn(
                "inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold transition-all duration-150 hover:scale-110",
                filled
                  ? `${filledBg} text-white shadow-sm`
                  : "bg-muted text-muted-foreground"
              )}
            >
              {label}
            </TooltipTrigger>
            <TooltipContent>
              {/* ── Evidence text ── */}
              <p className="font-medium">{full}</p>
              {filled ? (
                <p className="max-w-xs text-xs">{evidence[key]}</p>
              ) : (
                <p className="text-xs text-muted-foreground">No evidence</p>
              )}

              {/* ── Provenance chips (only when props are present) ── */}
              {(sourceLabel || confPct !== undefined || ageLabel) && (
                <div
                  className="mt-2 flex flex-wrap gap-1"
                  aria-label={provenanceAriaLabel || undefined}
                >
                  {/* Source chip */}
                  {sourceLabel && (
                    <span
                      aria-label={`${sourceLabel}-validated evidence`}
                      className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium bg-muted text-muted-foreground"
                    >
                      {sourceLabel}
                    </span>
                  )}

                  {/* Confidence chip */}
                  {confPct !== undefined && confColors && (
                    <span
                      aria-label={`confidence ${confPct}%`}
                      className={cn(
                        "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold",
                        confColors.bg,
                        confColors.text
                      )}
                    >
                      {confPct}%
                    </span>
                  )}

                  {/* Evidence age chip */}
                  {ageLabel && (
                    <span
                      aria-label={`evidence ${ageLabel}`}
                      className={cn(
                        "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-medium",
                        ageLabel === "stale (>6mo)"
                          ? "bg-red-100 dark:bg-red-900 text-red-700 dark:text-red-300"
                          : "bg-muted text-muted-foreground"
                      )}
                    >
                      {ageLabel}
                    </span>
                  )}
                </div>
              )}

              {/* ── Raw note excerpt ── */}
              {rawExcerpt ? (
                <>
                  <p className="mt-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                    Source note
                  </p>
                  <p className="max-w-xs text-xs italic opacity-80">"{rawExcerpt}"</p>
                </>
              ) : null}
            </TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
}
