"use client";

/**
 * Bulk FHIR ingest console.
 *
 * Two ways to onboard a panel:
 *
 *   1. Paste a FHIR Bulk Data $export URL — the backend kicks off the
 *      async $export → poll → NDJSON download → ingest pipeline.
 *   2. Drop an NDJSON file (≤ 1 GB) onto the upload card — the backend
 *      streams it straight into the ingest pipeline.
 *
 * Both flows hand off to a Celery task and stream live progress back
 * over SSE.  This page is the operator-facing surface for Gap #6 of
 * COMPETITIVE-GAP-ANALYSIS.md — onboarding a 50K–500K member panel.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  CheckCircle,
  Cloud,
  CloudUpload,
  Loader2,
  RefreshCw,
  XCircle,
} from "lucide-react";
import api, { API_BASE } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types — kept inline because the bulk-ingest endpoints are stable and don't
// warrant a re-generated openapi client for the MVP.
// ---------------------------------------------------------------------------

type IngestStatus =
  | "pending"
  | "downloading"
  | "ingesting"
  | "completed"
  | "failed";

interface IngestJob {
  id: string;
  tenant_id: string;
  source_type: "fhir_bulk_export" | "ndjson_upload";
  source_url: string | null;
  status: IngestStatus;
  total_resources: number;
  ingested_resources: number;
  errors_count: number;
  patient_count: number;
  condition_count: number;
  encounter_count: number;
  observation_count: number;
  started_at: string | null;
  completed_at: string | null;
  errors: string[];
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function listJobs(): Promise<IngestJob[]> {
  const { data } = await api.get<IngestJob[]>("/api/bulk-ingest/jobs", {
    params: { limit: 50 },
  });
  return data;
}

async function getJob(jobId: string): Promise<IngestJob> {
  const { data } = await api.get<IngestJob>(`/api/bulk-ingest/jobs/${jobId}`);
  return data;
}

async function startExport(payload: {
  source_url: string;
  resource_types: string[];
}): Promise<{ job_id: string }> {
  const { data } = await api.post("/api/bulk-ingest/start", {
    source_url: payload.source_url,
    source_type: "fhir_bulk_export",
    resource_types: payload.resource_types,
  });
  return data;
}

async function uploadNdjson(file: File, resourceTypes: string[]): Promise<{ job_id: string }> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("resource_types", JSON.stringify(resourceTypes));
  const { data } = await api.post("/api/bulk-ingest/upload", fd, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

// ---------------------------------------------------------------------------
// UI bits
// ---------------------------------------------------------------------------

const ALL_RESOURCE_TYPES = ["Patient", "Condition", "Encounter", "Observation"] as const;

function StatusBadge({ status }: { status: IngestStatus }) {
  const map: Record<IngestStatus, { label: string; cls: string; icon: ReactElement }> = {
    pending: {
      label: "Pending",
      cls: "bg-slate-100 text-slate-700",
      icon: <Loader2 className="h-3 w-3 animate-spin" />,
    },
    downloading: {
      label: "Downloading",
      cls: "bg-blue-50 text-blue-700",
      icon: <Cloud className="h-3 w-3" />,
    },
    ingesting: {
      label: "Ingesting",
      cls: "bg-amber-50 text-amber-700",
      icon: <Activity className="h-3 w-3 animate-pulse" />,
    },
    completed: {
      label: "Completed",
      cls: "bg-emerald-50 text-emerald-700",
      icon: <CheckCircle className="h-3 w-3" />,
    },
    failed: {
      label: "Failed",
      cls: "bg-rose-50 text-rose-700",
      icon: <XCircle className="h-3 w-3" />,
    },
  };
  const s = map[status];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${s.cls}`}>
      {s.icon}
      {s.label}
    </span>
  );
}

function ProgressBar({ ingested, total }: { ingested: number; total: number }) {
  // Bulk Data manifests give us file counts, not row counts, so we display
  // "ingested" as the authoritative number and use total only when the
  // worker has stamped it in (uploads start with total=0 until first batch).
  const pct = total > 0 ? Math.min(100, Math.round((ingested / Math.max(total, ingested)) * 100)) : 0;
  return (
    <div className="space-y-1">
      <div className="h-2 w-full rounded-full bg-slate-100 overflow-hidden">
        <div
          className="h-full bg-emerald-500 transition-all duration-500"
          style={{ width: total > 0 ? `${pct}%` : ingested > 0 ? "100%" : "0%" }}
        />
      </div>
      <div className="text-xs text-slate-500">
        {ingested.toLocaleString()} resources ingested
        {total > 0 ? ` of ${total.toLocaleString()}` : ""}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function BulkIngestPage() {
  const qc = useQueryClient();
  const [exportUrl, setExportUrl] = useState("");
  const [selectedTypes, setSelectedTypes] = useState<string[]>([...ALL_RESOURCE_TYPES]);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  const jobsQuery = useQuery({
    queryKey: ["bulk-ingest", "jobs"],
    queryFn: listJobs,
    // Poll every 4 s as a backstop in case the SSE stream is blocked by a
    // proxy.  SSE is the primary signal; this just guarantees the list
    // converges even without server-push.
    refetchInterval: 4000,
  });

  const detailQuery = useQuery({
    queryKey: ["bulk-ingest", "job", activeJobId],
    queryFn: () => (activeJobId ? getJob(activeJobId) : Promise.resolve(null as never)),
    enabled: !!activeJobId,
    refetchInterval: 3000,
  });

  const startExportMut = useMutation({
    mutationFn: startExport,
    onSuccess: ({ job_id }) => {
      setExportUrl("");
      setActiveJobId(job_id);
      void qc.invalidateQueries({ queryKey: ["bulk-ingest", "jobs"] });
    },
  });

  const uploadMut = useMutation({
    mutationFn: ({ file, types }: { file: File; types: string[] }) =>
      uploadNdjson(file, types),
    onSuccess: ({ job_id }) => {
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      setActiveJobId(job_id);
      void qc.invalidateQueries({ queryKey: ["bulk-ingest", "jobs"] });
    },
  });

  // SSE — when a job is selected, subscribe to live progress events.
  useEffect(() => {
    if (!activeJobId) return;
    const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    if (!token) return;
    const url = `${API_BASE}/api/bulk-ingest/jobs/${activeJobId}/stream?token=${encodeURIComponent(token)}`;
    const es = new EventSource(url);
    es.onmessage = () => {
      // Cheaper than parsing: just invalidate; the polling query refetches.
      void qc.invalidateQueries({ queryKey: ["bulk-ingest", "job", activeJobId] });
      void qc.invalidateQueries({ queryKey: ["bulk-ingest", "jobs"] });
    };
    es.onerror = () => {
      // Browser EventSource auto-retries; we just log and let the polling
      // queries cover any gaps.
      console.warn("bulk-ingest SSE error — falling back to polling");
    };
    return () => es.close();
  }, [activeJobId, qc]);

  const toggleType = useCallback((t: string) => {
    setSelectedTypes((prev) =>
      prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t],
    );
  }, []);

  const totalAcrossAll = useMemo(() => {
    const rows = jobsQuery.data ?? [];
    return rows.reduce(
      (acc, r) => ({
        patients: acc.patients + r.patient_count,
        conditions: acc.conditions + r.condition_count,
      }),
      { patients: 0, conditions: 0 },
    );
  }, [jobsQuery.data]);

  const activeJob = detailQuery.data ?? null;

  return (
    <div className="mx-auto max-w-7xl space-y-6 p-6">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold text-slate-900">Bulk FHIR ingest</h1>
        <p className="text-sm text-slate-500">
          Onboard 50K–500K-member panels in a single shot via FHIR Bulk Data
          ($export) or a one-time NDJSON drop.
        </p>
      </header>

      {/* Summary strip */}
      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="text-xs uppercase tracking-wider text-slate-500">Jobs (last 50)</div>
          <div className="mt-1 text-2xl font-semibold">{jobsQuery.data?.length ?? "—"}</div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="text-xs uppercase tracking-wider text-slate-500">Patients ingested</div>
          <div className="mt-1 text-2xl font-semibold">{totalAcrossAll.patients.toLocaleString()}</div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="text-xs uppercase tracking-wider text-slate-500">Conditions mapped</div>
          <div className="mt-1 text-2xl font-semibold">{totalAcrossAll.conditions.toLocaleString()}</div>
        </div>
      </section>

      {/* New ingest forms */}
      <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* $export URL */}
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="mb-3 flex items-center gap-2">
            <Cloud className="h-4 w-4 text-blue-600" />
            <h2 className="font-medium text-slate-900">FHIR $export URL</h2>
          </div>
          <input
            type="url"
            placeholder="https://payer.example.com/fhir/Group/123/$export"
            value={exportUrl}
            onChange={(e) => setExportUrl(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
          <ResourceTypePicker selected={selectedTypes} onToggle={toggleType} />
          <button
            type="button"
            onClick={() =>
              startExportMut.mutate({
                source_url: exportUrl.trim(),
                resource_types: selectedTypes,
              })
            }
            disabled={!exportUrl.trim() || selectedTypes.length === 0 || startExportMut.isPending}
            className="mt-3 inline-flex items-center gap-2 rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {startExportMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Cloud className="h-4 w-4" />}
            Start $export
          </button>
          {startExportMut.isError ? (
            <ErrorBanner err={startExportMut.error as Error} />
          ) : null}
        </div>

        {/* NDJSON upload */}
        <div className="rounded-lg border border-slate-200 bg-white p-4">
          <div className="mb-3 flex items-center gap-2">
            <CloudUpload className="h-4 w-4 text-emerald-600" />
            <h2 className="font-medium text-slate-900">NDJSON upload (≤ 1 GB)</h2>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".ndjson,.jsonl,application/x-ndjson"
            onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)}
            className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:text-sm file:font-medium hover:file:bg-slate-200"
          />
          <ResourceTypePicker selected={selectedTypes} onToggle={toggleType} />
          <button
            type="button"
            onClick={() =>
              selectedFile && uploadMut.mutate({ file: selectedFile, types: selectedTypes })
            }
            disabled={!selectedFile || selectedTypes.length === 0 || uploadMut.isPending}
            className="mt-3 inline-flex items-center gap-2 rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {uploadMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <CloudUpload className="h-4 w-4" />}
            Upload NDJSON
          </button>
          {uploadMut.isError ? <ErrorBanner err={uploadMut.error as Error} /> : null}
        </div>
      </section>

      {/* Active job detail */}
      {activeJob ? (
        <section className="rounded-lg border border-emerald-300 bg-emerald-50/50 p-4">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs uppercase tracking-wider text-emerald-700">
                Active job
              </div>
              <div className="font-mono text-sm text-slate-700">{activeJob.id}</div>
            </div>
            <StatusBadge status={activeJob.status} />
          </div>
          <div className="mt-3">
            <ProgressBar
              ingested={activeJob.ingested_resources}
              total={activeJob.total_resources}
            />
          </div>
          <div className="mt-3 grid grid-cols-4 gap-3 text-xs">
            <StatBox label="Patients" v={activeJob.patient_count} />
            <StatBox label="Conditions" v={activeJob.condition_count} />
            <StatBox label="Encounters" v={activeJob.encounter_count} />
            <StatBox label="Observations" v={activeJob.observation_count} />
          </div>
          {activeJob.errors && activeJob.errors.length > 0 ? (
            <details className="mt-3">
              <summary className="cursor-pointer text-xs text-rose-600">
                {activeJob.errors_count} errors — show first {Math.min(activeJob.errors.length, 20)}
              </summary>
              <ul className="mt-2 max-h-40 overflow-y-auto rounded border border-rose-200 bg-white p-2 text-xs">
                {activeJob.errors.slice(0, 20).map((e, i) => (
                  <li key={i} className="border-b border-slate-100 py-1 last:border-0">
                    <code className="text-rose-700">{e}</code>
                  </li>
                ))}
              </ul>
            </details>
          ) : null}
        </section>
      ) : null}

      {/* Job history */}
      <section className="rounded-lg border border-slate-200 bg-white">
        <header className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h2 className="font-medium text-slate-900">Recent jobs</h2>
          <button
            type="button"
            onClick={() => jobsQuery.refetch()}
            className="inline-flex items-center gap-1 text-xs text-slate-600 hover:text-slate-900"
          >
            <RefreshCw className="h-3 w-3" />
            Refresh
          </button>
        </header>
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wider text-slate-500">
            <tr>
              <th className="px-4 py-2 text-left">Job</th>
              <th className="px-4 py-2 text-left">Source</th>
              <th className="px-4 py-2 text-left">Status</th>
              <th className="px-4 py-2 text-left">Progress</th>
              <th className="px-4 py-2 text-right">Started</th>
            </tr>
          </thead>
          <tbody>
            {(jobsQuery.data ?? []).map((row) => (
              <tr
                key={row.id}
                onClick={() => setActiveJobId(row.id)}
                className={`cursor-pointer border-t border-slate-100 hover:bg-slate-50 ${
                  activeJobId === row.id ? "bg-emerald-50/40" : ""
                }`}
              >
                <td className="px-4 py-2 font-mono text-xs text-slate-700">{row.id}</td>
                <td className="px-4 py-2 text-slate-600">
                  {row.source_type === "ndjson_upload" ? "NDJSON" : "$export"}
                </td>
                <td className="px-4 py-2">
                  <StatusBadge status={row.status} />
                </td>
                <td className="px-4 py-2">
                  <ProgressBar ingested={row.ingested_resources} total={row.total_resources} />
                </td>
                <td className="px-4 py-2 text-right text-xs text-slate-500">
                  {row.started_at ? new Date(row.started_at).toLocaleString() : "—"}
                </td>
              </tr>
            ))}
            {!jobsQuery.isLoading && (jobsQuery.data ?? []).length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-12 text-center text-sm text-slate-500">
                  No jobs yet — start one above.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ResourceTypePicker({
  selected,
  onToggle,
}: {
  selected: string[];
  onToggle: (t: string) => void;
}) {
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {ALL_RESOURCE_TYPES.map((t) => {
        const on = selected.includes(t);
        return (
          <button
            key={t}
            type="button"
            onClick={() => onToggle(t)}
            className={`rounded-full px-3 py-1 text-xs ${
              on
                ? "bg-emerald-600 text-white"
                : "bg-slate-100 text-slate-700 hover:bg-slate-200"
            }`}
          >
            {t}
          </button>
        );
      })}
    </div>
  );
}

function StatBox({ label, v }: { label: string; v: number }) {
  return (
    <div className="rounded border border-emerald-200 bg-white p-2 text-center">
      <div className="text-[10px] uppercase tracking-wider text-emerald-700">{label}</div>
      <div className="mt-0.5 text-sm font-semibold text-slate-900">{v.toLocaleString()}</div>
    </div>
  );
}

function ErrorBanner({ err }: { err: Error }) {
  // Try to extract a useful FastAPI detail message if it came back as JSON.
  let msg = err.message;
  // @ts-expect-error AxiosError has .response
  const detail = err?.response?.data?.detail;
  if (typeof detail === "string") msg = detail;
  return (
    <div className="mt-3 flex items-start gap-2 rounded-md border border-rose-200 bg-rose-50 p-2 text-xs text-rose-700">
      <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
      <span>{msg}</span>
    </div>
  );
}
