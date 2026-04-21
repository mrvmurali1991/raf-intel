"use client";

import { useState } from "react";

/**
 * Tooltip — lightweight hover/focus tooltip, no extra dependency.
 * Distinct from shadcn Tooltip (which requires a Provider).
 */
export function Tooltip({ text, children }: { text: string; children: React.ReactNode }) {
  const [show, setShow] = useState(false);
  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
      onFocus={() => setShow(true)}
      onBlur={() => setShow(false)}
    >
      {children}
      {show && (
        <span className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-1.5 -translate-x-1/2 whitespace-nowrap rounded bg-popover px-2 py-1 text-[11px] text-popover-foreground shadow-md border">
          {text}
        </span>
      )}
    </span>
  );
}
