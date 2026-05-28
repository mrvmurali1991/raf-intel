"use client";

/**
 * StatusIndicator — unified status chip for every status surface in RAF Intelligence.
 *
 * Usage examples:
 *   <StatusIndicator status="open" />
 *   <StatusIndicator status="recaptured" variant="pill" showIcon />
 *   <StatusIndicator status="at_risk" variant="dot" />
 *   <StatusIndicator status="rejected" size="sm" variant="badge" showIcon />
 *   <StatusIndicator status="some_unknown_value" />   // graceful fallback
 */

import {
  AlertTriangle,
  CheckCircle2,
  CircleDot,
  Clock,
  MinusCircle,
  XCircle,
} from "lucide-react";

import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export type StatusType =
  // active / pending
  | "open"
  | "pending"
  | "in_progress"
  | "processing"
  | "queued"
  | "scheduled"
  | "draft"
  // success
  | "accepted"
  | "approved"
  | "completed"
  | "sent"
  | "delivered"
  | "recaptured"
  // error
  | "rejected"
  | "failed"
  | "error"
  // dismissed
  | "dismissed"
  | "expired"
  // at-risk
  | "at_risk"
  | "overdue";

export interface StatusIndicatorProps {
  /** Any StatusType string. Unknown values render as gray with the raw string. */
  status: StatusType | string;
  /** Visual size. Defaults to "md". */
  size?: "sm" | "md";
  /**
   * badge  — rounded rectangle: bg + colored text + optional icon (default)
   * dot    — 8 px circle only; useful in tight table cells
   * pill   — larger pill with icon + label; for emphasis areas
   */
  variant?: "badge" | "dot" | "pill";
  /** Render an icon to the left of the label. Ignored for the "dot" variant. */
  showIcon?: boolean;
  className?: string;
}

// ---------------------------------------------------------------------------
// Internal config
// ---------------------------------------------------------------------------

type ColorGroup = "amber" | "green" | "red" | "gray" | "orange";

interface StatusMeta {
  label: string;
  color: ColorGroup;
  /** Whether the dot should pulse. */
  pulse: boolean;
  Icon: React.ElementType;
}

// Special-case human-readable labels; everything else is auto-converted from
// snake_case → Title Case at runtime.
const LABEL_MAP: Partial<Record<string, string>> = {
  in_progress: "In Progress",
  at_risk: "At Risk",
  recaptured: "Recaptured",
  open: "Open",
  pending: "Pending",
  processing: "Processing",
  queued: "Queued",
  scheduled: "Scheduled",
  draft: "Draft",
  accepted: "Accepted",
  approved: "Approved",
  completed: "Completed",
  sent: "Sent",
  delivered: "Delivered",
  rejected: "Rejected",
  failed: "Failed",
  error: "Error",
  dismissed: "Dismissed",
  expired: "Expired",
  overdue: "Overdue",
};

const STATUS_META: Record<string, StatusMeta> = {
  // ---- active / pending (amber) -------------------------------------------
  open:        { label: LABEL_MAP.open!,        color: "amber",  pulse: false, Icon: CircleDot    },
  pending:     { label: LABEL_MAP.pending!,      color: "amber",  pulse: false, Icon: Clock        },
  in_progress: { label: LABEL_MAP.in_progress!,  color: "amber",  pulse: false, Icon: Clock        },
  processing:  { label: LABEL_MAP.processing!,   color: "amber",  pulse: false, Icon: Clock        },
  queued:      { label: LABEL_MAP.queued!,        color: "amber",  pulse: false, Icon: Clock        },
  scheduled:   { label: LABEL_MAP.scheduled!,    color: "amber",  pulse: false, Icon: Clock        },
  draft:       { label: LABEL_MAP.draft!,         color: "amber",  pulse: false, Icon: CircleDot    },
  // ---- success (green) -----------------------------------------------------
  accepted:    { label: LABEL_MAP.accepted!,     color: "green",  pulse: false, Icon: CheckCircle2 },
  approved:    { label: LABEL_MAP.approved!,     color: "green",  pulse: false, Icon: CheckCircle2 },
  completed:   { label: LABEL_MAP.completed!,    color: "green",  pulse: false, Icon: CheckCircle2 },
  sent:        { label: LABEL_MAP.sent!,          color: "green",  pulse: false, Icon: CheckCircle2 },
  delivered:   { label: LABEL_MAP.delivered!,    color: "green",  pulse: false, Icon: CheckCircle2 },
  recaptured:  { label: LABEL_MAP.recaptured!,   color: "green",  pulse: false, Icon: CheckCircle2 },
  // ---- error (red) ---------------------------------------------------------
  rejected:    { label: LABEL_MAP.rejected!,     color: "red",    pulse: false, Icon: XCircle      },
  failed:      { label: LABEL_MAP.failed!,        color: "red",    pulse: false, Icon: XCircle      },
  error:       { label: LABEL_MAP.error!,         color: "red",    pulse: false, Icon: XCircle      },
  // ---- dismissed (gray) ----------------------------------------------------
  dismissed:   { label: LABEL_MAP.dismissed!,    color: "gray",   pulse: false, Icon: MinusCircle  },
  expired:     { label: LABEL_MAP.expired!,       color: "gray",   pulse: false, Icon: MinusCircle  },
  // ---- at-risk (orange) ----------------------------------------------------
  at_risk:     { label: LABEL_MAP.at_risk!,       color: "orange", pulse: true,  Icon: AlertTriangle },
  overdue:     { label: LABEL_MAP.overdue!,       color: "orange", pulse: true,  Icon: AlertTriangle },
};

// ---------------------------------------------------------------------------
// Color → Tailwind class maps
// ---------------------------------------------------------------------------

// dot circle
const DOT_COLOR: Record<ColorGroup, string> = {
  amber:  "bg-amber-400  dark:bg-amber-400",
  green:  "bg-green-500  dark:bg-green-400",
  red:    "bg-red-500    dark:bg-red-400",
  gray:   "bg-gray-400   dark:bg-gray-500",
  orange: "bg-orange-500 dark:bg-orange-400",
};

// badge / pill background
const BG_COLOR: Record<ColorGroup, string> = {
  amber:  "bg-amber-50   dark:bg-amber-950/50",
  green:  "bg-green-50   dark:bg-green-950/50",
  red:    "bg-red-50     dark:bg-red-950/50",
  gray:   "bg-gray-100   dark:bg-gray-800/60",
  orange: "bg-orange-50  dark:bg-orange-950/50",
};

// text
const TEXT_COLOR: Record<ColorGroup, string> = {
  amber:  "text-amber-700  dark:text-amber-300",
  green:  "text-green-700  dark:text-green-300",
  red:    "text-red-700    dark:text-red-400",
  gray:   "text-gray-600   dark:text-gray-400",
  orange: "text-orange-700 dark:text-orange-300",
};

// ring / border used on badge + pill
const RING_COLOR: Record<ColorGroup, string> = {
  amber:  "ring-amber-200  dark:ring-amber-800/60",
  green:  "ring-green-200  dark:ring-green-800/60",
  red:    "ring-red-200    dark:ring-red-800/60",
  gray:   "ring-gray-200   dark:ring-gray-700",
  orange: "ring-orange-200 dark:ring-orange-800/60",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Convert arbitrary snake_case or kebab-case string to Title Case. */
function toTitleCase(raw: string): string {
  return raw
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function resolveMeta(status: string): StatusMeta {
  const key = status.toLowerCase().trim();
  if (STATUS_META[key]) return STATUS_META[key];
  // Graceful fallback for unknown statuses
  return {
    label: toTitleCase(key),
    color: "gray",
    pulse: false,
    Icon: CircleDot,
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function StatusIndicator({
  status,
  size = "md",
  variant = "badge",
  showIcon = false,
  className,
}: StatusIndicatorProps) {
  const meta = resolveMeta(status);
  const { label, color, pulse, Icon } = meta;

  // -- DOT variant ----------------------------------------------------------
  if (variant === "dot") {
    return (
      <span
        role="img"
        aria-label={label}
        title={label}
        className={cn(
          "relative inline-flex shrink-0 rounded-full",
          size === "sm" ? "size-2" : "size-2.5",
          DOT_COLOR[color],
          pulse && "animate-pulse",
          className
        )}
      />
    );
  }

  // -- Shared text + icon size for badge / pill -----------------------------
  const textSize  = size === "sm" ? "text-xs" : "text-xs";
  const iconSize  = size === "sm" ? "size-3"  : "size-3.5";
  // Dot inside badge/pill
  const dotSize   = "size-1.5";

  // -- BADGE variant --------------------------------------------------------
  if (variant === "badge") {
    return (
      <span
        role="status"
        aria-label={label}
        className={cn(
          "inline-flex items-center gap-1 rounded-md font-medium ring-1 ring-inset",
          size === "sm" ? "px-1.5 py-0.5" : "px-2 py-0.5",
          textSize,
          BG_COLOR[color],
          TEXT_COLOR[color],
          RING_COLOR[color],
          className
        )}
      >
        {showIcon ? (
          <Icon
            className={cn(iconSize, "shrink-0")}
            aria-hidden="true"
          />
        ) : (
          <span
            className={cn(
              "inline-block shrink-0 rounded-full",
              dotSize,
              DOT_COLOR[color],
              pulse && "animate-pulse"
            )}
            aria-hidden="true"
          />
        )}
        {label}
      </span>
    );
  }

  // -- PILL variant ---------------------------------------------------------
  return (
    <span
      role="status"
      aria-label={label}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full font-medium ring-1 ring-inset",
        size === "sm" ? "px-2 py-0.5" : "px-2.5 py-1",
        size === "sm" ? "text-xs" : "text-sm",
        BG_COLOR[color],
        TEXT_COLOR[color],
        RING_COLOR[color],
        className
      )}
    >
      <Icon
        className={cn(
          size === "sm" ? "size-3" : "size-4",
          "shrink-0",
          pulse && "animate-pulse"
        )}
        aria-hidden="true"
      />
      {label}
    </span>
  );
}
