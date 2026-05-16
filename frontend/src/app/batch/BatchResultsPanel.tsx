"use client";

/**
 * BatchResultsPanel — results summary section shown only after batch completes.
 * Extracted from batch/page.tsx to defer ~25 kB of results table + stat cards
 * that are invisible on initial page load.
 */

import { useCallback } from "react";
import { tokens } from "@/styles/tokens";
import { Download, BarChart3, Users, TrendingUp, FileText } from "lucide-react";

interface BatchResult {
  pid: number;
  patientName: string;
  newHccs: number;
  diagnoses: number;
  rafIncrease: number;
  revenue: number;
}

function formatMoney(n: number): string {
  return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

export interface BatchResultsPanelProps {
  results: BatchResult[];
  processed: number;
  newHccs: number;
}

export default function BatchResultsPanel({ results, processed, newHccs }: BatchResultsPanelProps) {
  const totalRevenue = results.reduce((s, r) => s + r.revenue, 0);
  const avgRaf = results.length > 0 ? results.reduce((s, r) => s + r.rafIncrease, 0) / results.length : 0;

  const downloadCSV = useCallback(() => {
    const header = "PID,Patient Name,New HCCs,Diagnoses,RAF Increase,Revenue\n";
    const rows = results.map((r) =>
      `${r.pid},"${r.patientName}",${r.newHccs},${r.diagnoses},${(r.rafIncrease ?? 0).toFixed(3)},${(r.revenue ?? 0).toFixed(2)}`
    ).join("\n");
    const blob = new Blob([header + rows], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `batch-analysis-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [results]);

  return (
    <div className="animate-fade-in">
      <div className="flex items-center gap-3 mb-5">
        <div className="w-1 h-6 rounded-full bg-gradient-to-b from-blue-600 to-blue-400" />
        <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">Results Summary</h3>
        <span className="text-xs text-slate-400 bg-slate-100 dark:bg-slate-800 px-2.5 py-1 rounded-full font-medium">
          {results.length} patients
        </span>
      </div>

      {/* Summary stat cards */}
      <div className="grid gap-4 mb-6" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))" }}>
        {[
          { label: "Total Patients Analyzed", value: processed, icon: <Users size={18} className="text-blue-500" />, color: tokens.primary },
          { label: "Total New HCCs Discovered", value: newHccs, icon: <TrendingUp size={18} className="text-emerald-500" />, color: tokens.success },
          { label: "Est. Revenue Opportunity", value: formatMoney(totalRevenue), icon: <BarChart3 size={18} className="text-blue-500" />, color: tokens.primary },
          { label: "Average RAF Increase", value: (avgRaf ?? 0).toFixed(3), icon: <TrendingUp size={18} className="text-amber-500" />, color: tokens.warningStrong },
        ].map((stat, i) => (
          <div key={stat.label} className={`premium-card hover-lift animate-slide-up stagger-${i + 1} card-glow-blue p-5`}>
            <div className="flex items-center gap-2 mb-2">
              {stat.icon}
              <span className="text-xs font-medium text-slate-500 dark:text-slate-400">{stat.label}</span>
            </div>
            <p className="text-2xl font-bold text-slate-900 dark:text-slate-100 tabular-nums">{stat.value}</p>
          </div>
        ))}
      </div>

      {/* Results table */}
      {results.length > 0 && (
        <div className="premium-card overflow-hidden mb-6 animate-slide-up stagger-5">
          <div className="px-5 py-3.5 border-b border-slate-100 dark:border-slate-800 flex items-center gap-2">
            <FileText size={14} className="text-slate-400" />
            <span className="text-[13px] font-semibold text-slate-900 dark:text-slate-100">Detailed Results</span>
          </div>
          <div className="overflow-x-auto">
            <table aria-label="Batch analysis results" className="w-full text-sm">
              <thead>
                <tr className="bg-slate-50 dark:bg-slate-800/50">
                  {["Patient", "PID", "Diagnoses", "New HCCs", "RAF +/-", "Revenue"].map((h, idx) => (
                    <th key={h} className={`${idx === 0 ? "text-left" : "text-right"} px-5 py-3 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {results.map((r, i) => (
                  <tr key={r.pid} className={`border-b border-slate-50 dark:border-slate-800/50 transition-colors duration-150 hover:bg-blue-50/50 dark:hover:bg-blue-950/20 ${i % 2 === 0 ? "bg-white dark:bg-transparent" : "bg-slate-50/40 dark:bg-slate-800/20"}`}>
                    <td className="px-5 py-3 font-medium text-slate-900 dark:text-slate-100">{r.patientName}</td>
                    <td className="px-5 py-3 text-right text-slate-500 tabular-nums">{r.pid}</td>
                    <td className="px-5 py-3 text-right text-slate-700 dark:text-slate-300 tabular-nums">{r.diagnoses}</td>
                    <td className="px-5 py-3 text-right">
                      <span className={`inline-flex items-center justify-center min-w-[28px] px-2 py-0.5 rounded-full text-xs font-semibold ${r.newHccs > 0 ? "bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400" : "bg-slate-100 dark:bg-slate-800 text-slate-400"}`}>
                        {r.newHccs}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-right tabular-nums">
                      <span className={r.rafIncrease > 0 ? "text-emerald-600 dark:text-emerald-400 font-medium" : "text-slate-400"}>
                        {r.rafIncrease > 0 ? "+" : ""}{(r.rafIncrease ?? 0).toFixed(3)}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-right font-semibold text-slate-900 dark:text-slate-100 tabular-nums">
                      {formatMoney(r.revenue)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Action buttons */}
      <div className="flex gap-3 animate-slide-up stagger-6">
        <a href="/reports" className="btn-press inline-flex items-center gap-2.5 px-6 py-2.5 rounded-xl bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-700 hover:to-blue-600 text-white text-sm font-semibold shadow-lg shadow-blue-500/25 hover:shadow-blue-500/40 transition-all duration-200 no-underline">
          <BarChart3 size={16} /> View Full Report
        </a>
        <button onClick={downloadCSV} className="btn-press inline-flex items-center gap-2.5 px-6 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 text-sm font-semibold hover:bg-slate-50 dark:hover:bg-slate-700 transition-all duration-200">
          <Download size={16} /> Download CSV
        </button>
      </div>
    </div>
  );
}
