"use client";

/**
 * ChartExportMenu — "..." overflow menu attached to any chart card.
 *
 * Usage:
 *   <ChartExportMenu
 *     filename="hcc-distribution"
 *     csvData={[{ hcc_code: "HCC 18", count: 14 }, ...]}
 *     chartRef={containerRef}     // optional – enables PNG export
 *     rawData={top20}             // optional – enables View Raw Data
 *   />
 *
 * Place it inside the chart card header row:
 *   <div className="flex justify-between">
 *     <h3>My Chart</h3>
 *     <ChartExportMenu filename="my-chart" csvData={rows} />
 *   </div>
 */

import * as React from "react";
import { MoreHorizontal, Download, Image, Table } from "lucide-react";
import { downloadCSV } from "@/lib/csv-export";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ChartExportMenuProps {
  /** Base filename for CSV/PNG downloads (date suffix appended automatically) */
  filename: string;
  /** Rows to export as CSV. Required for CSV export option. */
  csvData?: Record<string, unknown>[];
  /** Ref to the DOM node that will be captured for PNG. If omitted PNG option is hidden. */
  chartRef?: React.RefObject<HTMLElement | null>;
  /** Raw data passed to View Raw Data inline table. If omitted that option is hidden. */
  rawData?: Record<string, unknown>[];
  /** Extra class names for the trigger button */
  className?: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ChartExportMenu({
  filename,
  csvData,
  chartRef,
  rawData,
  className,
}: ChartExportMenuProps) {
  const [open, setOpen] = React.useState(false);
  const [showRaw, setShowRaw] = React.useState(false);
  const menuRef = React.useRef<HTMLDivElement>(null);
  const dropdownRef = React.useRef<HTMLDivElement>(null);
  const triggerRef = React.useRef<HTMLButtonElement>(null);

  // Close on outside click
  React.useEffect(() => {
    if (!open) return;
    function handle(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [open]);

  // Auto-focus first menuitem when dropdown opens
  React.useEffect(() => {
    if (!open) return;
    const first = dropdownRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]');
    first?.focus();
  }, [open]);

  function getMenuItems(): HTMLButtonElement[] {
    if (!dropdownRef.current) return [];
    return Array.from(dropdownRef.current.querySelectorAll<HTMLButtonElement>('[role="menuitem"]'));
  }

  function handleMenuKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    const items = getMenuItems();
    if (!items.length) return;
    const focused = document.activeElement as HTMLButtonElement;
    const idx = items.indexOf(focused);

    switch (e.key) {
      case "ArrowDown": {
        e.preventDefault();
        const next = idx < items.length - 1 ? idx + 1 : 0;
        items[next].focus();
        break;
      }
      case "ArrowUp": {
        e.preventDefault();
        const prev = idx > 0 ? idx - 1 : items.length - 1;
        items[prev].focus();
        break;
      }
      case "Home": {
        e.preventDefault();
        items[0].focus();
        break;
      }
      case "End": {
        e.preventDefault();
        items[items.length - 1].focus();
        break;
      }
      case "Escape": {
        e.preventDefault();
        setOpen(false);
        triggerRef.current?.focus();
        break;
      }
    }
  }

  function handleExportCSV() {
    if (csvData?.length) downloadCSV(csvData as Record<string, unknown>[], filename);
    setOpen(false);
  }

  async function handleExportPNG() {
    if (!chartRef?.current) return;
    setOpen(false);
    try {
      // Dynamically import html2canvas only when needed — keeps bundle small
      const { default: html2canvas } = await import("html2canvas");
      const canvas = await html2canvas(chartRef.current as HTMLElement, { useCORS: true, scale: 2 });
      const link = document.createElement("a");
      link.download = `${filename}_${new Date().toISOString().slice(0, 10)}.png`;
      link.href = canvas.toDataURL("image/png");
      link.click();
    } catch {
      // html2canvas not available — silent no-op (dependency optional)
    }
  }

  function handleViewRaw() {
    setShowRaw((v) => !v);
    setOpen(false);
  }

  const hasCsv = Boolean(csvData?.length);
  const hasPng = Boolean(chartRef);
  const hasRaw = Boolean(rawData?.length);

  if (!hasCsv && !hasPng && !hasRaw) return null;

  const rawHeaders = rawData?.length ? Object.keys(rawData[0]) : [];

  return (
    <div ref={menuRef} className="relative inline-block">
      {/* Trigger */}
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="Chart options"
        aria-haspopup="menu"
        aria-expanded={open}
        data-testid="chart-export-menu"
        className={[
          "inline-flex items-center justify-center w-[30px] h-[30px]",
          "border border-border rounded-md bg-card text-muted-foreground",
          "cursor-pointer transition-colors duration-150",
          "hover:bg-accent hover:border-border/70",
          className,
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <MoreHorizontal size={15} />
      </button>

      {/* Dropdown */}
      {open && (
        <div
          ref={dropdownRef}
          role="menu"
          aria-label="Chart export options"
          data-testid="chart-export-menu-content"
          onKeyDown={handleMenuKeyDown}
          className="absolute right-0 top-[calc(100%+4px)] z-50 bg-card border border-border rounded-lg shadow-lg min-w-[170px] py-1 animate-dropdown-in"
        >
          {hasCsv && (
            <MenuItem icon={<Download size={13} />} label="Export CSV" onClick={handleExportCSV} />
          )}
          {hasPng && (
            <MenuItem icon={<Image size={13} />} label="Export PNG" onClick={handleExportPNG} />
          )}
          {hasRaw && (
            <MenuItem
              icon={<Table size={13} />}
              label={showRaw ? "Hide Raw Data" : "View Raw Data"}
              onClick={handleViewRaw}
            />
          )}
        </div>
      )}

      {/* Inline Raw Data table */}
      {showRaw && rawData?.length && (
        <div
          aria-label="Raw chart data"
          className="absolute right-0 top-[calc(100%+36px)] z-[49] bg-card border border-border rounded-lg shadow-lg max-h-[280px] overflow-y-auto min-w-[300px]"
        >
          <table className="w-full border-collapse text-xs">
            <thead className="bg-muted sticky top-0">
              <tr>
                {rawHeaders.map((h) => (
                  <th
                    key={h}
                    className="px-[10px] py-[6px] text-left font-semibold text-muted-foreground border-b border-border whitespace-nowrap"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rawData.slice(0, 50).map((row, i) => (
                <tr key={i} className="border-b border-border/50">
                  {rawHeaders.map((h) => (
                    <td
                      key={h}
                      className="px-[10px] py-[5px] text-foreground tabular-nums"
                    >
                      {String(row[h] ?? "")}
                    </td>
                  ))}
                </tr>
              ))}
              {rawData.length > 50 && (
                <tr>
                  <td
                    colSpan={rawHeaders.length}
                    className="px-[10px] py-[6px] text-muted-foreground text-center italic"
                  >
                    Showing first 50 of {rawData.length} rows
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Internal MenuItem
// ---------------------------------------------------------------------------

function MenuItem({
  icon,
  label,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      role="menuitem"
      type="button"
      tabIndex={-1}
      onClick={onClick}
      className="flex items-center gap-2 w-full px-[14px] py-[8px] bg-transparent border-none cursor-pointer text-[13px] text-foreground text-left transition-colors duration-100 hover:bg-accent focus:bg-accent focus:outline-none"
    >
      <span className="text-muted-foreground flex">{icon}</span>
      {label}
    </button>
  );
}

export default ChartExportMenu;
