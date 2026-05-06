"use client";

/**
 * CFO export dropdown — CSV or JSON download of the monthly breakdown.
 */

import React, { useState } from "react";
import { Download, ChevronDown } from "lucide-react";

import { downloadCfoExport } from "@/lib/api";

const T = {
  white: "#FFFFFF",
  slate900: "#0F172A",
  slate700: "#334155",
  slate500: "#64748B",
  slate200: "#E2E8F0",
  slate100: "#F1F5F9",
  blue600: "#2563EB",
  blue700: "#1D4ED8",
};

interface Props {
  year?: number;
}

export default function CfoExportButton({ year }: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<"csv" | "json" | null>(null);
  const yr = year ?? new Date().getFullYear();

  async function exportAs(fmt: "csv" | "json") {
    try {
      setBusy(fmt);
      const blob = await downloadCfoExport(yr, fmt);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `recapture_cfo_${yr}.${fmt}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("CFO export failed", err);
    } finally {
      setBusy(null);
      setOpen(false);
    }
  }

  return (
    <div style={{ position: "relative" }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          padding: "8px 14px",
          borderRadius: 8,
          border: `1px solid ${T.slate200}`,
          background: T.white,
          color: T.slate900,
          fontSize: 13,
          fontWeight: 600,
          cursor: "pointer",
        }}
      >
        <Download size={14} />
        Export
        <ChevronDown size={12} />
      </button>
      {open && (
        <div
          style={{
            position: "absolute",
            right: 0,
            marginTop: 4,
            minWidth: 160,
            background: T.white,
            border: `1px solid ${T.slate200}`,
            borderRadius: 8,
            boxShadow: "0 4px 16px rgba(15,23,42,0.08)",
            zIndex: 20,
            overflow: "hidden",
          }}
        >
          <button
            type="button"
            onClick={() => exportAs("csv")}
            disabled={busy !== null}
            style={{
              width: "100%",
              textAlign: "left",
              padding: "10px 14px",
              border: "none",
              background: "transparent",
              cursor: busy ? "wait" : "pointer",
              fontSize: 13,
              color: T.slate900,
            }}
            onMouseEnter={(e) => (e.currentTarget.style.background = T.slate100)}
            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
          >
            {busy === "csv" ? "Exporting CSV…" : "Export CSV"}
          </button>
          <button
            type="button"
            onClick={() => exportAs("json")}
            disabled={busy !== null}
            style={{
              width: "100%",
              textAlign: "left",
              padding: "10px 14px",
              border: "none",
              background: "transparent",
              cursor: busy ? "wait" : "pointer",
              fontSize: 13,
              color: T.slate900,
              borderTop: `1px solid ${T.slate100}`,
            }}
            onMouseEnter={(e) => (e.currentTarget.style.background = T.slate100)}
            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
          >
            {busy === "json" ? "Exporting JSON…" : "Export JSON"}
          </button>
        </div>
      )}
    </div>
  );
}
