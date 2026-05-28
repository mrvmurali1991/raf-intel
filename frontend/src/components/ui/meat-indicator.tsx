"use client";

/**
 * MeatIndicator — visualizes MEAT criteria (Monitor, Evaluate, Assess, Treat)
 * for RAF Intelligence suspect cards, tables, and detail views.
 *
 * Usage examples:
 *
 *   // sm — inline in a table row
 *   <MeatIndicator
 *     criteria={{ monitor: true, evaluate: "HbA1c 9.2%", assess: false, treat: false }}
 *     size="sm"
 *   />
 *
 *   // md — on a suspect card
 *   <MeatIndicator
 *     criteria={{ monitor: true, evaluate: "HbA1c 9.2%", assess: true, treat: false }}
 *     size="md"
 *   />
 *
 *   // md with expandable popover showing lg-style evidence detail
 *   <MeatIndicator
 *     criteria={{ monitor: "Lab orders on 2024-03-15", evaluate: true, assess: true, treat: false }}
 *     size="md"
 *     expandable
 *   />
 *
 *   // lg — in a suspect detail view
 *   <MeatIndicator
 *     criteria={{
 *       monitor: "Lab orders for HbA1c on 2024-03-15, follow-up scheduled",
 *       evaluate: "HbA1c result: 9.2% — above threshold for DM complications",
 *       assess: "Provider documented 'uncontrolled diabetes' in progress note",
 *       treat: false,
 *     }}
 *     size="lg"
 *   />
 *
 *   // Standalone score badge
 *   <MeatScore criteria={{ monitor: true, evaluate: true, assess: false, treat: false }} />
 */

import * as React from "react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface MeatCriteria {
  monitor: boolean | string;
  evaluate: boolean | string;
  assess: boolean | string;
  treat: boolean | string;
}

export interface MeatIndicatorProps {
  criteria: MeatCriteria;
  size?: "sm" | "md" | "lg";
  /** Show letter labels under circles (sm) or text counts (md). Always shown for lg. */
  showLabels?: boolean;
  /** md only: clicking opens a popover with lg-style evidence rows. */
  expandable?: boolean;
  className?: string;
}

// ---------------------------------------------------------------------------
// Internal constants
// ---------------------------------------------------------------------------

const LETTERS = ["M", "E", "A", "T"] as const;
type MeatLetter = (typeof LETTERS)[number];

const FULL_NAMES: Record<MeatLetter, string> = {
  M: "Monitor",
  E: "Evaluate",
  A: "Assess",
  T: "Treat",
};

/** Order of criteria keys mapped to their letter. */
const CRITERIA_KEYS: Array<{ key: keyof MeatCriteria; letter: MeatLetter }> = [
  { key: "monitor",  letter: "M" },
  { key: "evaluate", letter: "E" },
  { key: "assess",   letter: "A" },
  { key: "treat",    letter: "T" },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isMet(value: boolean | string): boolean {
  return Boolean(value);
}

function evidenceText(value: boolean | string): string | null {
  return typeof value === "string" && value.trim().length > 0 ? value : null;
}

function countMet(criteria: MeatCriteria): number {
  return CRITERIA_KEYS.filter(({ key }) => isMet(criteria[key])).length;
}

// ---------------------------------------------------------------------------
// Check / X icons — pure SVG, no external dep
// ---------------------------------------------------------------------------

function CheckIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      <circle cx="8" cy="8" r="7" fill="currentColor" opacity="0.15" />
      <path
        d="M4.5 8.5L7 11L11.5 5.5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function CrossIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      <circle cx="8" cy="8" r="7" fill="currentColor" opacity="0.12" />
      <path
        d="M5.5 5.5L10.5 10.5M10.5 5.5L5.5 10.5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Size: sm — four small circles with optional letter labels below
// ---------------------------------------------------------------------------

/**
 * Simple tooltip rendered as a `title` attribute on each circle. No external
 * library needed; the browser's native tooltip is sufficient at this small size.
 */
function SmIndicator({
  criteria,
  showLabels,
  className,
}: {
  criteria: MeatCriteria;
  showLabels?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn("inline-flex items-center gap-1", className)}
      role="img"
      aria-label={`MEAT criteria: ${CRITERIA_KEYS.map(({ key, letter }) => `${FULL_NAMES[letter]} ${isMet(criteria[key]) ? "met" : "not met"}`).join(", ")}`}
    >
      {CRITERIA_KEYS.map(({ key, letter }) => {
        const met = isMet(criteria[key]);
        return (
          <span
            key={letter}
            className="inline-flex flex-col items-center gap-0.5"
          >
            <span
              title={`${FULL_NAMES[letter]} ${met ? "✓" : "✗"}`}
              aria-hidden="true"
              className={cn(
                "inline-block size-2.5 rounded-full ring-1 ring-inset transition-colors",
                met
                  ? "bg-emerald-500 ring-emerald-400/60 dark:bg-emerald-400 dark:ring-emerald-500/40"
                  : "bg-slate-200 ring-slate-300/60 dark:bg-slate-700 dark:ring-slate-600/40",
              )}
            />
            {showLabels && (
              <span
                aria-hidden="true"
                className={cn(
                  "text-[8px] font-semibold leading-none",
                  met
                    ? "text-emerald-600 dark:text-emerald-400"
                    : "text-slate-400 dark:text-slate-500",
                )}
              >
                {letter}
              </span>
            )}
          </span>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Size: lg — stacked evidence rows
// ---------------------------------------------------------------------------

function LgIndicator({
  criteria,
  className,
}: {
  criteria: MeatCriteria;
  className?: string;
}) {
  return (
    <div
      className={cn("flex flex-col gap-2", className)}
      role="list"
      aria-label="MEAT criteria details"
    >
      {CRITERIA_KEYS.map(({ key, letter }) => {
        const met = isMet(criteria[key]);
        const evidence = evidenceText(criteria[key]);

        return (
          <div
            key={letter}
            role="listitem"
            className={cn(
              "flex items-start gap-3 rounded-lg border px-3 py-2.5 transition-colors",
              met
                ? "border-emerald-200 bg-emerald-50/60 dark:border-emerald-800/50 dark:bg-emerald-950/30"
                : "border-slate-200 bg-slate-50/60 dark:border-slate-700/50 dark:bg-slate-900/30",
            )}
          >
            {/* Icon */}
            {met ? (
              <CheckIcon
                className={cn(
                  "mt-0.5 size-4 shrink-0 text-emerald-600 dark:text-emerald-400",
                )}
              />
            ) : (
              <CrossIcon
                className={cn(
                  "mt-0.5 size-4 shrink-0 text-red-500 dark:text-red-400",
                )}
              />
            )}

            {/* Letter + full word */}
            <div className="flex min-w-0 flex-1 flex-col gap-0.5">
              <span
                className={cn(
                  "text-sm font-semibold leading-none",
                  met
                    ? "text-emerald-800 dark:text-emerald-300"
                    : "text-slate-600 dark:text-slate-400",
                )}
              >
                <span className="mr-1 font-black">{letter}</span>
                {FULL_NAMES[letter]}
              </span>

              {/* Evidence text */}
              <span
                className={cn(
                  "text-xs leading-snug",
                  evidence
                    ? "text-slate-600 dark:text-slate-400"
                    : "italic text-slate-400 dark:text-slate-600",
                )}
              >
                {evidence ?? "Not documented"}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Expandable popover — used by md when expandable=true
// ---------------------------------------------------------------------------

function MdExpandablePopover({
  criteria,
  trigger,
}: {
  criteria: MeatCriteria;
  trigger: React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  const popoverRef = React.useRef<HTMLDivElement>(null);
  const triggerRef = React.useRef<HTMLButtonElement>(null);
  const popoverId = React.useId();

  // Close on outside click
  React.useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target as Node) &&
        triggerRef.current &&
        !triggerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  // Close on Escape
  React.useEffect(() => {
    if (!open) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open]);

  return (
    <div className="relative inline-block">
      <button
        ref={triggerRef}
        type="button"
        aria-expanded={open}
        aria-controls={popoverId}
        aria-haspopup="dialog"
        onClick={() => setOpen((v) => !v)}
        className="cursor-pointer rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-1"
      >
        {trigger}
      </button>

      {open && (
        <div
          ref={popoverRef}
          id={popoverId}
          role="dialog"
          aria-label="MEAT criteria details"
          className={cn(
            "absolute left-0 top-full z-50 mt-2 w-80 rounded-xl border border-slate-200 bg-white p-3 shadow-lg",
            "dark:border-slate-700 dark:bg-slate-900",
            // Animate in
            "animate-in fade-in-0 zoom-in-95 duration-150",
          )}
        >
          {/* Header */}
          <div className="mb-2.5 flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              MEAT Evidence
            </span>
            <button
              type="button"
              aria-label="Close MEAT details"
              onClick={() => {
                setOpen(false);
                triggerRef.current?.focus();
              }}
              className="rounded p-0.5 text-slate-400 transition-colors hover:text-slate-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 dark:hover:text-slate-200"
            >
              <svg
                viewBox="0 0 16 16"
                fill="none"
                className="size-3.5"
                aria-hidden="true"
              >
                <path
                  d="M4 4L12 12M12 4L4 12"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          </div>
          <LgIndicator criteria={criteria} />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Size: md — letter badges with count summary
// ---------------------------------------------------------------------------

function MdIndicator({
  criteria,
  expandable,
  className,
}: {
  criteria: MeatCriteria;
  expandable?: boolean;
  className?: string;
}) {
  const met = countMet(criteria);

  const badges = (
    <div className="inline-flex flex-col items-start gap-1.5">
      {/* Letter badge row */}
      <div
        className="flex items-center gap-1"
        role="img"
        aria-label={`MEAT criteria: ${met} of 4 met`}
      >
        {CRITERIA_KEYS.map(({ key, letter }) => {
          const criteriaMet = isMet(criteria[key]);
          return (
            <span
              key={letter}
              aria-label={`${FULL_NAMES[letter]}: ${criteriaMet ? "met" : "not met"}`}
              className={cn(
                "inline-flex size-6 items-center justify-center rounded text-[11px] font-bold leading-none transition-colors",
                criteriaMet
                  ? "bg-emerald-500 text-white dark:bg-emerald-600"
                  : "bg-slate-100 text-slate-400 dark:bg-slate-800 dark:text-slate-500",
              )}
            >
              {letter}
            </span>
          );
        })}
      </div>

      {/* Count summary */}
      <span
        aria-hidden="true"
        className={cn(
          "text-xs leading-none",
          met === 4
            ? "text-emerald-600 dark:text-emerald-400"
            : met >= 2
            ? "text-amber-600 dark:text-amber-400"
            : "text-red-500 dark:text-red-400",
        )}
      >
        {met} of 4 criteria met
      </span>
    </div>
  );

  if (expandable) {
    return (
      <div className={className}>
        <MdExpandablePopover criteria={criteria} trigger={badges} />
      </div>
    );
  }

  return <div className={cn("inline-block", className)}>{badges}</div>;
}

// ---------------------------------------------------------------------------
// MeatScore — standalone score badge export
// ---------------------------------------------------------------------------

/**
 * Compact "3/4 MEAT" score badge.
 * Color: 4/4 = emerald, 3/4 = amber, 2/4 = orange, 0–1/4 = red.
 *
 * @example
 *   <MeatScore criteria={suspect.meat_criteria} />
 */
export function MeatScore({
  criteria,
  className,
}: {
  criteria: MeatCriteria;
  className?: string;
}) {
  const met = countMet(criteria);

  const colorClass =
    met === 4
      ? "bg-emerald-50 text-emerald-700 ring-emerald-300/60 dark:bg-emerald-950/50 dark:text-emerald-300 dark:ring-emerald-700/50"
      : met === 3
      ? "bg-amber-50 text-amber-700 ring-amber-300/60 dark:bg-amber-950/50 dark:text-amber-300 dark:ring-amber-700/50"
      : met === 2
      ? "bg-orange-50 text-orange-700 ring-orange-300/60 dark:bg-orange-950/50 dark:text-orange-300 dark:ring-orange-700/50"
      : "bg-red-50 text-red-700 ring-red-300/60 dark:bg-red-950/50 dark:text-red-400 dark:ring-red-800/60";

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-semibold ring-1 ring-inset",
        colorClass,
        className,
      )}
      aria-label={`MEAT score: ${met} of 4 criteria met`}
    >
      <span className="tabular-nums">{met}/4</span>
      <span className="font-bold tracking-widest">MEAT</span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// MeatIndicator — main export
// ---------------------------------------------------------------------------

/**
 * MeatIndicator — unified MEAT criteria visualization.
 *
 * Sizes:
 *   sm  — four small circles; intended for table rows
 *   md  — four letter badges with count summary; intended for suspect cards
 *   lg  — stacked evidence rows; intended for suspect detail views
 *
 * Set `expandable` on `md` to allow clicking to open a popover with full
 * evidence text.
 */
export function MeatIndicator({
  criteria,
  size = "md",
  showLabels = false,
  expandable = false,
  className,
}: MeatIndicatorProps) {
  if (size === "sm") {
    return (
      <SmIndicator
        criteria={criteria}
        showLabels={showLabels}
        className={className}
      />
    );
  }

  if (size === "lg") {
    return <LgIndicator criteria={criteria} className={className} />;
  }

  // md (default)
  return (
    <MdIndicator
      criteria={criteria}
      expandable={expandable}
      className={className}
    />
  );
}

export default MeatIndicator;
