"use client";

/**
 * <PageAlerts> — collapsible notice strip that replaces stacked banner clutter.
 *
 * Usage:
 *   <PageAlerts defaultOpen={hasActionable}>
 *     <DataQualityBanner />
 *     <HistoricalPYBanner />
 *     <WorkflowProgressBar currentStage="suspects" />
 *     <WorkflowHandoffBanner ... />
 *   </PageAlerts>
 *
 * - Counts non-null rendered children to build "X notices" chip.
 * - `defaultOpen` controls initial state; pass true when actionable banners
 *   are expected (e.g. when count > 0 from a data query).
 * - Auto-collapses when all children render null (banner components return
 *   null when they have nothing to show — container detects via ResizeObserver).
 * - Keyboard accessible: Enter/Space toggles expand/collapse.
 */

import React, { useRef, useState, useEffect, useId } from "react";
import { ChevronDown } from "lucide-react";
import { tokens } from "@/styles/tokens";

interface PageAlertsProps {
  children: React.ReactNode;
  /** Start expanded. Pass true when actionable banners are likely. Default: true. */
  defaultOpen?: boolean;
  /** Override label, e.g. "3 notices". Auto-computed when omitted. */
  label?: string;
  className?: string;
}

export function PageAlerts({
  children,
  defaultOpen = true,
  label,
  className,
}: PageAlertsProps) {
  const [open, setOpen] = useState(defaultOpen);
  const [childCount, setChildCount] = useState(0);
  const bodyRef = useRef<HTMLDivElement>(null);
  const id = useId();
  const panelId = `page-alerts-panel-${id}`;

  // Count visible children by measuring rendered height of each direct child.
  // Each banner component returns null when inactive; this observer catches it.
  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;

    const countVisible = () => {
      const kids = Array.from(el.children) as HTMLElement[];
      const visible = kids.filter((k) => k.offsetHeight > 0).length;
      setChildCount(visible);
      // Auto-collapse when nothing is visible
      if (visible === 0) setOpen(false);
    };

    countVisible();
    const ro = new ResizeObserver(countVisible);
    ro.observe(el);
    // Also observe each child separately so null→visible transitions fire
    Array.from(el.children).forEach((c) => ro.observe(c));
    return () => ro.disconnect();
  }, [children]);

  const chipLabel = label ?? (childCount === 1 ? "1 notice" : `${childCount} notices`);

  // If all children returned null, don't render the container at all
  if (childCount === 0) {
    return (
      <div ref={bodyRef} aria-hidden="true" style={{ position: "absolute", visibility: "hidden", pointerEvents: "none" }}>
        {children}
      </div>
    );
  }

  return (
    <div
      className={className}
      style={{ marginBottom: 16 }}
      role="region"
      aria-label="Page notices"
    >
      {/* Header strip */}
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setOpen((v) => !v);
          }
        }}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          width: "100%",
          padding: "7px 14px",
          border: `1px solid ${tokens.slate200}`,
          borderBottom: open ? `1px solid ${tokens.slate200}` : `1px solid ${tokens.slate200}`,
          borderRadius: open ? "10px 10px 0 0" : 10,
          background: tokens.slate50,
          cursor: "pointer",
          transition: "background 0.15s, border-radius 0.15s",
        }}
      >
        {/* Chip */}
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            padding: "2px 10px",
            borderRadius: 99,
            fontSize: 11,
            fontWeight: 700,
            background: tokens.warningSoft,
            color: tokens.warningText,
            letterSpacing: "0.02em",
          }}
        >
          {chipLabel}
        </span>
        <span
          style={{
            flex: 1,
            fontSize: 12,
            color: tokens.slate500,
            fontWeight: 500,
            textAlign: "left",
          }}
        >
          {open ? "Click to collapse" : "Click to expand"}
        </span>
        <ChevronDown
          size={15}
          aria-hidden="true"
          style={{
            color: tokens.slate400,
            transition: "transform 0.2s",
            transform: open ? "rotate(180deg)" : "rotate(0deg)",
            flexShrink: 0,
          }}
        />
      </button>

      {/* Collapsible body */}
      <div
        id={panelId}
        ref={bodyRef}
        style={{
          overflow: "hidden",
          maxHeight: open ? 600 : 0,
          opacity: open ? 1 : 0,
          transition: "max-height 0.25s cubic-bezier(0.4,0,0.2,1), opacity 0.2s ease",
          border: open ? `1px solid ${tokens.slate200}` : "none",
          borderTop: "none",
          borderRadius: "0 0 10px 10px",
          background: tokens.white,
          padding: open ? "12px 14px 4px" : "0 14px",
        }}
        aria-hidden={!open}
      >
        {children}
      </div>
    </div>
  );
}

export default PageAlerts;
