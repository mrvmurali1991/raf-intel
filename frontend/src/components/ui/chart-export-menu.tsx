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
 *   <div style={{ display: "flex", justifyContent: "space-between" }}>
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

  // Close on Escape
  React.useEffect(() => {
    if (!open) return;
    function handle(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", handle);
    return () => document.removeEventListener("keydown", handle);
  }, [open]);

  function handleExportCSV() {
    if (csvData?.length) downloadCSV(csvData as Record<string, unknown>[], filename);
    setOpen(false);
  }

  async function handleExportPNG() {
    if (!chartRef?.current) return;
    setOpen(false);
    try {
      // Dynamically import html2canvas only when needed — keeps bundle small
      // @ts-expect-error: html2canvas has no @types package; dynamic import is safe at runtime
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
    <div ref={menuRef} style={{ position: "relative", display: "inline-block" }}>
      {/* Trigger */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="Chart options"
        aria-haspopup="menu"
        aria-expanded={open}
        className={className}
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: 30,
          height: 30,
          border: "1px solid #E2E8F0",
          borderRadius: 6,
          background: "white",
          color: "#64748B",
          cursor: "pointer",
          transition: "background 0.15s, border-color 0.15s",
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLButtonElement).style.background = "#F8FAFC";
          (e.currentTarget as HTMLButtonElement).style.borderColor = "#CBD5E1";
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLButtonElement).style.background = "white";
          (e.currentTarget as HTMLButtonElement).style.borderColor = "#E2E8F0";
        }}
      >
        <MoreHorizontal size={15} />
      </button>

      {/* Dropdown */}
      {open && (
        <div
          role="menu"
          aria-label="Chart export options"
          style={{
            position: "absolute",
            right: 0,
            top: "calc(100% + 4px)",
            zIndex: 50,
            background: "white",
            border: "1px solid #E2E8F0",
            borderRadius: 8,
            boxShadow: "0 4px 16px rgba(15,23,42,0.10), 0 1px 3px rgba(15,23,42,0.06)",
            minWidth: 170,
            padding: "4px 0",
            animation: "fadeInDown 0.12s ease",
          }}
        >
          <style>{`@keyframes fadeInDown { from { opacity:0; transform:translateY(-4px) } to { opacity:1; transform:translateY(0) } }`}</style>

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
          style={{
            position: "absolute",
            right: 0,
            top: "calc(100% + 36px)",
            zIndex: 49,
            background: "white",
            border: "1px solid #E2E8F0",
            borderRadius: 8,
            boxShadow: "0 4px 16px rgba(15,23,42,0.10)",
            maxHeight: 280,
            overflowY: "auto",
            minWidth: 300,
          }}
        >
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead style={{ background: "#F8FAFC", position: "sticky", top: 0 }}>
              <tr>
                {rawHeaders.map((h) => (
                  <th
                    key={h}
                    style={{
                      padding: "6px 10px",
                      textAlign: "left",
                      fontWeight: 600,
                      color: "#475569",
                      borderBottom: "1px solid #E2E8F0",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rawData.slice(0, 50).map((row, i) => (
                <tr key={i} style={{ borderBottom: "1px solid #F1F5F9" }}>
                  {rawHeaders.map((h) => (
                    <td
                      key={h}
                      style={{ padding: "5px 10px", color: "#0F172A", fontVariantNumeric: "tabular-nums" }}
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
                    style={{ padding: "6px 10px", color: "#64748B", textAlign: "center", fontStyle: "italic" }}
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
      onClick={onClick}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        width: "100%",
        padding: "8px 14px",
        background: "none",
        border: "none",
        cursor: "pointer",
        fontSize: 13,
        color: "#0F172A",
        textAlign: "left",
        transition: "background 0.1s",
      }}
      onMouseEnter={(e) => ((e.currentTarget as HTMLButtonElement).style.background = "#F8FAFC")}
      onMouseLeave={(e) => ((e.currentTarget as HTMLButtonElement).style.background = "none")}
    >
      <span style={{ color: "#64748B", display: "flex" }}>{icon}</span>
      {label}
    </button>
  );
}

export default ChartExportMenu;
