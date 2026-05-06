"use client";

import React, { useState, useRef, useCallback, useEffect } from "react";
import { tokens } from "@/styles/tokens";
import { Activity, Download, BarChart3, AlertCircle, Clock, Users, TrendingUp, Zap, CheckCircle2, XCircle, FileText } from "lucide-react";
import { PageHeader, EmptyState } from "@/components/healthcare-ui";
import {
  searchPatients,
  batchAnalysis,
  getJobStatus,
  getPatientsWithEncounters,
} from "@/lib/api";

// ─── Types ───────────────────────────────────────────────────────────────────

interface LogEntry {
  timestamp: string;
  patientName: string;
  pid: number;
  diagnoses: number;
  hccs: number;
  status: "success" | "error";
  message?: string;
}

interface BatchResult {
  pid: number;
  patientName: string;
  newHccs: number;
  diagnoses: number;
  rafIncrease: number;
  revenue: number;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function ts(): string {
  return new Date().toLocaleTimeString("en-US", { hour12: false });
}

function formatMoney(n: number): string {
  return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function BatchAnalysisPage() {
  const [patientLimit, setPatientLimit] = useState(25);
  const [isRunning, setIsRunning] = useState(false);
  const [isComplete, setIsComplete] = useState(false);

  // Progress
  const [total, setTotal] = useState(0);
  const [processed, setProcessed] = useState(0);
  const [newHccs, setNewHccs] = useState(0);
  const [errors, setErrors] = useState(0);
  const [avgTime, setAvgTime] = useState(0);
  const [, setStartTime] = useState<number>(0);

  // Log + results
  const [log, setLog] = useState<LogEntry[]>([]);
  const [results, setResults] = useState<BatchResult[]>([]);
  const logRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef(false);

  // ─── Auto-scroll log when entries change ────────────────────────────────────

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log]);

  const appendLog = useCallback((entry: LogEntry) => {
    setLog((prev) => [...prev, entry]);
  }, []);

  // ─── Run analysis ───────────────────────────────────────────────────────────

  const startAnalysis = useCallback(async () => {
    // Reset
    abortRef.current = false;
    setIsRunning(true);
    setIsComplete(false);
    setProcessed(0);
    setNewHccs(0);
    setErrors(0);
    setLog([]);
    setResults([]);
    setAvgTime(0);

    const began = Date.now();
    setStartTime(began);

    try {
      // Fetch patients with encounters
      let patients: any[] = [];
      try {
        patients = await getPatientsWithEncounters();
      } catch {
        // Fallback to search
        const res = await searchPatients({ limit: patientLimit });
        patients = res.patients || [];
      }

      // Limit
      patients = patients.slice(0, patientLimit);
      setTotal(patients.length);

      if (patients.length === 0) {
        setIsRunning(false);
        return;
      }

      let completedCount = 0;
      let hccTotal = 0;
      let errorCount = 0;
      const allResults: BatchResult[] = [];

      for (const patient of patients) {
        if (abortRef.current) break;

        const pid = patient.pid ?? patient.id;
        const name =
          [patient.fname, patient.lname].filter(Boolean).join(" ") ||
          patient.name ||
          `Patient ${pid}`;

        try {
          const { job_id } = await batchAnalysis(pid);

          // Poll job status
          let jobDone = false;
          let jobResult: any = {};
          let pollAttempts = 0;
          while (!jobDone && pollAttempts < 60) {
            if (abortRef.current) break;
            await sleep(1500);
            if (abortRef.current) break;
            try {
              jobResult = await getJobStatus(job_id);
            } catch {
              pollAttempts++;
              continue;
            }
            const s = String(jobResult.status).toLowerCase();
            if (s === "completed" || s === "complete" || s === "done" || s === "failed" || s === "error") {
              jobDone = true;
            }
            pollAttempts++;
          }

          const status = String(jobResult.status ?? "").toLowerCase();
          const isFailed = status === "failed" || status === "error";

          const diagCount = Number(jobResult.processed ?? jobResult.diagnoses ?? 0);
          const hccCount = Number(jobResult.new_hccs ?? jobResult.hccs ?? 0);
          const rafInc = Number(jobResult.raf_increase ?? 0);
          const rev = Number(jobResult.revenue ?? 0);

          if (isFailed) {
            errorCount++;
            setErrors(errorCount);
            appendLog({ timestamp: ts(), patientName: name, pid, diagnoses: 0, hccs: 0, status: "error", message: String(jobResult.error ?? "Analysis failed") });
          } else {
            hccTotal += hccCount;
            setNewHccs(hccTotal);
            allResults.push({ pid, patientName: name, newHccs: hccCount, diagnoses: diagCount, rafIncrease: rafInc, revenue: rev });
            setResults([...allResults]);
            appendLog({ timestamp: ts(), patientName: name, pid, diagnoses: diagCount, hccs: hccCount, status: "success" });
          }
        } catch (err: unknown) {
          errorCount++;
          setErrors(errorCount);
          appendLog({ timestamp: ts(), patientName: name, pid, diagnoses: 0, hccs: 0, status: "error", message: (err as { message?: string })?.message ?? "Request failed" });
        }

        completedCount++;
        setProcessed(completedCount);
        const elapsed = Date.now() - began;
        setAvgTime(elapsed / completedCount);
      }
    } catch (err: unknown) {
      appendLog({ timestamp: ts(), patientName: "System", pid: 0, diagnoses: 0, hccs: 0, status: "error", message: (err as { message?: string })?.message ?? "Failed to fetch patients" });
    }

    setIsRunning(false);
    setIsComplete(true);
  }, [patientLimit, appendLog]);

  const stopAnalysis = useCallback(() => {
    abortRef.current = true;
  }, []);

  // ─── CSV download ──────────────────────────────────────────────────────────

  const downloadCSV = useCallback(() => {
    const header = "PID,Patient Name,New HCCs,Diagnoses,RAF Increase,Revenue\n";
    const rows = results.map((r) => `${r.pid},"${r.patientName}",${r.newHccs},${r.diagnoses},${(r.rafIncrease ?? 0).toFixed(3)},${(r.revenue ?? 0).toFixed(2)}`).join("\n");
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

  // ─── Computed values ───────────────────────────────────────────────────────

  const pct = total > 0 ? Math.round((processed / total) * 100) : 0;
  const remaining = total - processed;
  const etaMs = avgTime > 0 ? remaining * avgTime : 0;
  const etaStr =
    etaMs > 0
      ? etaMs > 60000
        ? `${Math.ceil(etaMs / 60000)}m`
        : `${Math.ceil(etaMs / 1000)}s`
      : "--";
  const totalRevenue = results.reduce((s, r) => s + r.revenue, 0);
  const avgRaf = results.length > 0 ? results.reduce((s, r) => s + r.rafIncrease, 0) / results.length : 0;
  const limits = [10, 25, 50, 100] as const;

  // ─── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="max-w-[1200px] mx-auto rci-page-pad-desktop" style={{ padding: "20px 16px" }}>
      <div className="animate-fade-in">
        <PageHeader
          title="Batch Analysis"
          subtitle="Analyze patient encounters in bulk to identify HCC conditions and revenue opportunities"
          icon={<Activity size={24} className="text-blue-600" />}
        />
      </div>

      {/* Section 1: Controls — Upload/Input Area */}
      <div className="premium-card hover-lift animate-slide-up stagger-1 mb-6 relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-r from-blue-500/5 via-transparent to-emerald-500/5 pointer-events-none" />
        <div className="relative p-6">
          {/* Dashed upload-style border area */}
          <div className="border-2 border-dashed border-slate-200 dark:border-slate-700 rounded-xl p-6 mb-5 transition-all duration-300 hover:border-blue-400 hover:bg-blue-50/50 dark:hover:bg-blue-950/20 group">
            <div className="flex items-center justify-center gap-3 mb-3">
              <div className="w-10 h-10 rounded-full bg-blue-100 dark:bg-blue-900/40 flex items-center justify-center group-hover:scale-110 transition-transform duration-300">
                <Zap size={20} className="text-blue-600 group-hover:animate-pulse" />
              </div>
              <div>
                <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  Analyze patients with clinical notes
                </p>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Select batch size and start processing encounters at scale
                </p>
              </div>
              <span className="text-[11px] bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400 px-2.5 py-1 rounded-full font-semibold tracking-wide uppercase">
                Recommended
              </span>
            </div>
          </div>

          <div className="flex items-center gap-4 flex-wrap">
            {/* Patient limit selector */}
            <div className="flex items-center gap-1.5 bg-slate-50 dark:bg-slate-800/50 rounded-xl p-1.5">
              {limits.map((n) => (
                <button
                  key={n}
                  onClick={() => !isRunning && setPatientLimit(n)}
                  className={`btn-press px-4 py-2 rounded-lg text-[13px] font-semibold transition-all duration-200 ${
                    patientLimit === n
                      ? "bg-gradient-to-r from-blue-600 to-blue-500 text-white shadow-md shadow-blue-500/25"
                      : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-white dark:hover:bg-slate-700"
                  } ${isRunning ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}
                >
                  {n}
                </button>
              ))}
              <span className="text-xs text-slate-400 ml-2 font-medium">patients</span>
            </div>

            {/* Action buttons */}
            <div className="flex gap-3 ml-auto">
              <button
                onClick={startAnalysis}
                disabled={isRunning}
                className={`btn-press inline-flex items-center gap-2.5 px-6 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 ${
                  isRunning
                    ? "bg-slate-100 dark:bg-slate-800 text-slate-400 cursor-not-allowed"
                    : "bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-700 hover:to-blue-600 text-white shadow-lg shadow-blue-500/25 hover:shadow-blue-500/40"
                }`}
              >
                <Activity size={16} aria-hidden="true" className={isRunning ? "" : "animate-pulse"} />
                Start Analysis
              </button>

              {isRunning && (
                <button
                  onClick={stopAnalysis}
                  className="btn-press px-5 py-2.5 rounded-xl border-2 border-red-500/50 text-red-600 dark:text-red-400 text-sm font-semibold hover:bg-red-50 dark:hover:bg-red-950/30 transition-all duration-200"
                >
                  Stop
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Section 2: Progress Dashboard */}
      {(isRunning || isComplete) && (
        <div className="mb-6 animate-fade-in">
          {/* Progress bar card */}
          <div className="premium-card animate-slide-up stagger-2 mb-4 overflow-hidden">
            <div className="p-6">
              <div className="flex justify-between items-center mb-3">
                <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
                  {processed} / {total} patients complete
                </span>
                <span className="text-sm font-bold tabular-nums bg-gradient-to-r from-blue-600 to-blue-400 bg-clip-text text-transparent">
                  {pct}%
                </span>
              </div>
              {/* Custom animated progress bar */}
              <div className="relative h-3 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                <div
                  className="absolute inset-y-0 left-0 rounded-full transition-all duration-700 ease-out"
                  style={{
                    width: `${pct}%`,
                    background: isComplete
                      ? `linear-gradient(90deg, ${tokens.success}, ${tokens.emerald300})`
                      : `linear-gradient(90deg, ${tokens.primary}, ${tokens.infoBlue})`,
                  }}
                >
                  {isRunning && (
                    <div className="absolute inset-0 shimmer" />
                  )}
                </div>
              </div>
              {isRunning && (
                <p className="text-xs text-slate-400 mt-2 tabular-nums">
                  Estimated time remaining: {etaStr}
                </p>
              )}
            </div>
          </div>

          {/* Stat cards */}
          <div className="grid gap-4 mb-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))" }}>
            {[
              { label: "Patients Analyzed", value: processed, icon: <Users size={18} />, colorClass: "card-glow-blue", delay: "stagger-2" },
              { label: "New HCCs Found", value: newHccs, icon: <TrendingUp size={18} />, colorClass: "card-glow-emerald", delay: "stagger-3" },
              { label: "Errors", value: errors, icon: <AlertCircle size={18} />, colorClass: errors > 0 ? "card-glow-rose" : "card-glow-emerald", delay: "stagger-4" },
              { label: "Est. Time Left", value: isRunning ? etaStr : "Done", icon: <Clock size={18} />, colorClass: "card-glow-amber", delay: "stagger-5" },
            ].map((stat) => (
              <div key={stat.label} className={`premium-card hover-lift animate-slide-up ${stat.delay} ${stat.colorClass} p-5`}>
                <div className="flex items-center gap-3 mb-2">
                  <div className="w-9 h-9 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center text-slate-500">
                    {stat.icon}
                  </div>
                  <span className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                    {stat.label}
                  </span>
                </div>
                <p className="text-2xl font-bold text-slate-900 dark:text-slate-100 tabular-nums">
                  {stat.value}
                </p>
              </div>
            ))}
          </div>

          {/* Live log */}
          <div className="premium-card animate-slide-up stagger-6 overflow-hidden">
            <div className="px-5 py-3.5 border-b border-slate-100 dark:border-slate-800 flex items-center gap-3">
              <BarChart3 size={14} className="text-slate-400" />
              <span className="text-[13px] font-semibold text-slate-900 dark:text-slate-100">
                Live Analysis Log
              </span>
              {isRunning && (
                <span className="relative flex h-2.5 w-2.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500" />
                </span>
              )}
              <span className="ml-auto text-[11px] text-slate-400 tabular-nums">{log.length} entries</span>
            </div>
            <div
              ref={logRef}
              className="max-h-[300px] overflow-y-auto"
              style={{ fontFamily: "ui-monospace, monospace" }}
            >
              {log.length === 0 && (
                <div className="p-8 text-center">
                  <div className="inline-flex items-center gap-2 text-slate-400 text-sm">
                    <div className="w-4 h-4 border-2 border-slate-300 border-t-blue-500 rounded-full animate-spin" />
                    Waiting for results...
                  </div>
                </div>
              )}
              {log.map((entry, i) => (
                <div
                  key={i}
                  className={`flex items-center gap-3 px-5 py-2.5 text-xs border-b border-slate-50 dark:border-slate-800/50 transition-colors duration-150 hover:bg-slate-50/80 dark:hover:bg-slate-800/30 ${
                    entry.status === "error"
                      ? "bg-red-50/60 dark:bg-red-950/20"
                      : i % 2 === 0
                        ? "bg-white dark:bg-transparent"
                        : "bg-slate-50/40 dark:bg-slate-800/20"
                  }`}
                >
                  <span className="text-slate-400 min-w-[70px] tabular-nums">{entry.timestamp}</span>
                  <span className={`font-semibold min-w-[160px] ${entry.status === "error" ? "text-red-600 dark:text-red-400" : "text-slate-800 dark:text-slate-200"}`}>
                    {entry.patientName}
                  </span>
                  {entry.status === "success" ? (
                    <span className="inline-flex items-center gap-1.5 text-emerald-600 dark:text-emerald-400">
                      <CheckCircle2 size={13} />
                      {entry.diagnoses} diagnoses, {entry.hccs} HCCs
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 text-red-600 dark:text-red-400">
                      <XCircle size={13} />
                      {entry.message ?? "Error"}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Section 3: Results Summary */}
      {isComplete && results.length > 0 && (
        <div className="animate-fade-in">
          <div className="flex items-center gap-3 mb-5">
            <div className="w-1 h-6 rounded-full bg-gradient-to-b from-blue-600 to-blue-400" />
            <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">
              Results Summary
            </h3>
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
                      <th className="text-left px-5 py-3 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">Patient</th>
                      <th className="text-right px-5 py-3 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">PID</th>
                      <th className="text-right px-5 py-3 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">Diagnoses</th>
                      <th className="text-right px-5 py-3 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">New HCCs</th>
                      <th className="text-right px-5 py-3 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">RAF +/-</th>
                      <th className="text-right px-5 py-3 text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider">Revenue</th>
                    </tr>
                  </thead>
                  <tbody>
                    {results.map((r, i) => (
                      <tr
                        key={r.pid}
                        className={`border-b border-slate-50 dark:border-slate-800/50 transition-colors duration-150 hover:bg-blue-50/50 dark:hover:bg-blue-950/20 ${
                          i % 2 === 0 ? "bg-white dark:bg-transparent" : "bg-slate-50/40 dark:bg-slate-800/20"
                        }`}
                      >
                        <td className="px-5 py-3 font-medium text-slate-900 dark:text-slate-100">{r.patientName}</td>
                        <td className="px-5 py-3 text-right text-slate-500 tabular-nums">{r.pid}</td>
                        <td className="px-5 py-3 text-right text-slate-700 dark:text-slate-300 tabular-nums">{r.diagnoses}</td>
                        <td className="px-5 py-3 text-right">
                          <span className={`inline-flex items-center justify-center min-w-[28px] px-2 py-0.5 rounded-full text-xs font-semibold ${
                            r.newHccs > 0
                              ? "bg-emerald-50 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400"
                              : "bg-slate-100 dark:bg-slate-800 text-slate-400"
                          }`}>
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
            <a
              href="/reports"
              className="btn-press inline-flex items-center gap-2.5 px-6 py-2.5 rounded-xl bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-700 hover:to-blue-600 text-white text-sm font-semibold shadow-lg shadow-blue-500/25 hover:shadow-blue-500/40 transition-all duration-200 no-underline"
            >
              <BarChart3 size={16} />
              View Full Report
            </a>
            <button
              onClick={downloadCSV}
              className="btn-press inline-flex items-center gap-2.5 px-6 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 text-sm font-semibold hover:bg-slate-50 dark:hover:bg-slate-700 transition-all duration-200"
            >
              <Download size={16} />
              Download CSV
            </button>
          </div>
        </div>
      )}

      {/* Empty state if nothing has been run yet */}
      {!isRunning && !isComplete && (
        <div className="animate-fade-in stagger-2">
          <EmptyState
            icon={<Activity size={40} className="text-slate-400" />}
            title="No analysis running"
            description="Select your patient count and click Start Analysis to begin identifying HCC conditions and revenue opportunities."
          />
        </div>
      )}
    </div>
  );
}
