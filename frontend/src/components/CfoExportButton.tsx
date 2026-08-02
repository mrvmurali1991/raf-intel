"use client";

/**
 * CFO export dropdown — CSV or JSON download of the monthly breakdown.
 */

import React, { useState } from "react";
import { Download, ChevronDown } from "lucide-react";

import { downloadCfoExport } from "@/lib/api";

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
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-50 text-[13px] font-semibold cursor-pointer"
      >
        <Download size={14} />
        Export
        <ChevronDown size={12} />
      </button>
      {open && (
        <div className="absolute right-0 mt-1 min-w-[160px] bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-lg shadow-lg z-20 overflow-hidden">
          <button
            type="button"
            onClick={() => exportAs("csv")}
            disabled={busy !== null}
            className="w-full text-left px-3.5 py-2.5 border-none bg-transparent text-[13px] text-slate-900 dark:text-slate-50 hover:bg-slate-100 dark:hover:bg-slate-800 cursor-pointer disabled:cursor-wait"
          >
            {busy === "csv" ? "Exporting CSV…" : "Export CSV"}
          </button>
          <button
            type="button"
            onClick={() => exportAs("json")}
            disabled={busy !== null}
            className="w-full text-left px-3.5 py-2.5 border-none border-t border-t-slate-100 dark:border-t-slate-800 bg-transparent text-[13px] text-slate-900 dark:text-slate-50 hover:bg-slate-100 dark:hover:bg-slate-800 cursor-pointer disabled:cursor-wait"
          >
            {busy === "json" ? "Exporting JSON…" : "Export JSON"}
          </button>
        </div>
      )}
    </div>
  );
}
