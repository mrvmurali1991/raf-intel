"use client";

/**
 * FieldTooltip — lightweight wrapper around the project's base-ui Tooltip.
 *
 * Usage:
 *   <FieldTooltip content="Description here">
 *     <label>...</label>           // or any trigger element
 *   </FieldTooltip>
 *
 * Keyboard: trigger is focusable (tabIndex=0) when the child is not already
 * interactive, so screen-reader / keyboard users can invoke the tooltip.
 * Delay: 200 ms per spec.
 */

import React from "react";
import {
  TooltipProvider,
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from "@/components/ui/tooltip";
import { Info } from "lucide-react";

interface FieldTooltipProps {
  /** The tooltip text shown on hover / focus. */
  content: string;
  /** The element that triggers the tooltip. If omitted, a small ⓘ icon is rendered. */
  children?: React.ReactNode;
  /** Tooltip placement. Defaults to "top". */
  side?: "top" | "bottom" | "left" | "right";
}

export function FieldTooltip({
  content,
  children,
  side = "top",
}: FieldTooltipProps) {
  return (
    <TooltipProvider delay={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          {children ? (
            // Wrap non-interactive children in a focusable span so keyboard
            // users can reach the tooltip.
            <span tabIndex={0} className="inline-flex cursor-default outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 rounded">
              {children}
            </span>
          ) : (
            <button
              type="button"
              aria-label={content}
              className="inline-flex items-center justify-center h-4 w-4 rounded-full text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-blue-500/50 outline-none transition-colors"
            >
              <Info className="h-3.5 w-3.5" aria-hidden />
            </button>
          )}
        </TooltipTrigger>
        <TooltipContent side={side} className="max-w-[240px] text-xs leading-relaxed">
          {content}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
