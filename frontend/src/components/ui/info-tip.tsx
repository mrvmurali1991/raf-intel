"use client";

/**
 * InfoTip — tiny inline Info icon with a hover/focus tooltip.
 *
 * Intentionally minimal: drop it next to any column header, metric label, or
 * button label to surface a one-line explanation without adding visual weight.
 *
 * Uses the project's base-ui Tooltip primitives (same as FieldTooltip and
 * MetricMetaTooltip) so it inherits portal rendering, viewport-edge flipping,
 * and the project-wide animation tokens — no raw CSS hover hacks.
 *
 * Usage:
 *   import { InfoTip } from "@/components/ui/info-tip";
 *
 *   // Next to a column header
 *   <th>RAF Score <InfoTip text="Risk Adjustment Factor — higher = sicker patient = higher payment." /></th>
 *
 *   // Next to a metric label
 *   <span>Revenue at Risk <InfoTip text="Projected loss if open gaps are not captured before deadline." /></span>
 *
 *   // Larger icon, custom alignment
 *   <InfoTip text="Explains this button." size={16} className="align-middle" />
 */

import { Info } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface InfoTipProps {
  /** The explanation shown inside the tooltip. */
  text: string;
  /** Icon size in px. Defaults to 14. */
  size?: number;
  /** Extra classes applied to the outermost wrapper span. */
  className?: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function InfoTip({ text, size = 14, className }: InfoTipProps) {
  return (
    <span className={`inline-flex items-center${className ? ` ${className}` : ""}`}>
      <TooltipProvider delay={150}>
        <Tooltip>
          <TooltipTrigger
            // Rendered as a button so keyboard users can reach the tooltip
            // with Tab and trigger it with Enter / Space.
            type="button"
            aria-label={text}
            className="
              inline-flex items-center justify-center
              rounded
              text-muted-foreground/50 hover:text-muted-foreground
              focus-visible:outline-none focus-visible:ring-2
              focus-visible:ring-blue-500/50
              transition-colors duration-150
              cursor-help
              ml-1
            "
          >
            <Info size={size} aria-hidden />
          </TooltipTrigger>

          <TooltipContent
            side="top"
            sideOffset={6}
            className="max-w-[280px] rounded-lg px-3 py-2 text-xs leading-relaxed"
          >
            {text}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    </span>
  );
}
