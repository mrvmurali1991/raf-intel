"use client";

/**
 * DocumentIngestionDetailDrawer
 *
 * Side drawer showing full detail for a single ingested document.
 *
 * Usage:
 *   <DocumentIngestionDetailDrawer
 *     open={!!selected}
 *     onClose={() => setSelected(null)}
 *     sourceId={selected?.source}
 *     documentId={selected?.document_id}
 *     isAdmin={user?.role === "admin"}
 *   />
 */

import React, { useEffect, useRef } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  X,
  FileText,
  Cpu,
  RotateCcw,
  AlertCircle,
  ChevronRight,
} from "lucide-react";
import { getDocumentDetail, reprocessDocument } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Suspect {
  hcc_code: string;
  icd10_code: string;
  confidence_score: number;
  evidence_sentence: string;
}

interface DocumentRecord {
  [key: string]: unknown;
}

interface DrawerProps {
  open: boolean;
  onClose: () => void;
  sourceId: string | null | undefined;
  documentId: string | null | undefined;
  isAdmin?: boolean;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function confidenceColorClass(score: number): string {
  if (score >= 0.8) return "text-emerald-500 dark:text-emerald-400";
  if (score >= 0.5) return "text-amber-500 dark:text-amber-400";
  return "text-red-600 dark:text-red-400";
}

function formatBytes(n: number | null | undefined): string {
  if (!n) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function prettyKey(k: string): string {
  return k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

const DISPLAY_FIELDS = [
  "source",
  "filename",
  "mimetype",
  "file_size_bytes",
  "processing_engine",
  "status",
  "patient_id",
  "ingested_at",
  "processed_at",
  "received_at",
  "pulled_at",
  "queried_at",
];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function MetaRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between items-start py-2 border-b border-slate-200 dark:border-slate-700 gap-3">
      <span className="text-xs text-slate-500 dark:text-slate-400 font-medium shrink-0">
        {label}
      </span>
      <span className="text-[13px] text-slate-900 dark:text-slate-50 text-right break-all">
        {value ?? "—"}
      </span>
    </div>
  );
}

function SuspectRow({ suspect, idx }: { suspect: Suspect; idx: number }) {
  const pct = Math.round(suspect.confidence_score * 100);
  return (
    <tr
      className={
        idx % 2 === 0
          ? "bg-white dark:bg-slate-900"
          : "bg-slate-100 dark:bg-slate-800"
      }
    >
      <td className="px-2.5 py-2 text-xs font-mono text-blue-600 dark:text-blue-400">
        {suspect.hcc_code || "—"}
      </td>
      <td className="px-2.5 py-2 text-xs font-mono text-slate-900 dark:text-slate-100">
        {suspect.icd10_code || "—"}
      </td>
      <td className="px-2.5 py-2 text-xs">
        <span
          className={`font-semibold ${confidenceColorClass(suspect.confidence_score)}`}
          aria-label={`Confidence ${pct}%`}
        >
          {pct}%
        </span>
      </td>
      <td
        className="px-2.5 py-2 text-[11px] text-slate-500 dark:text-slate-400 max-w-[260px] overflow-hidden text-ellipsis whitespace-nowrap"
        title={suspect.evidence_sentence}
      >
        {suspect.evidence_sentence || "—"}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Main drawer
// ---------------------------------------------------------------------------

export function DocumentIngestionDetailDrawer({
  open,
  onClose,
  sourceId,
  documentId,
  isAdmin = false,
}: DrawerProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (open) {
      setTimeout(() => closeRef.current?.focus(), 50);
    }
  }, [open]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape" && open) onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["doc-detail", sourceId, documentId],
    queryFn: () => getDocumentDetail(sourceId!, documentId!),
    enabled: open && !!sourceId && !!documentId,
    staleTime: 30_000,
  });

  const reprocessMutation = useMutation({
    mutationFn: (engine: string) =>
      reprocessDocument(sourceId!, documentId!, engine),
  });

  if (!open) return null;

  const record = (data?.record ?? {}) as DocumentRecord;
  const suspects: Suspect[] = data?.suspects ?? [];

  const displayEntries = DISPLAY_FIELDS.filter((k) => k in record).map(
    (k) => [k, record[k]] as [string, unknown]
  );

  const extraEntries = Object.entries(record).filter(
    ([k]) => !DISPLAY_FIELDS.includes(k)
  );

  const processingEngine =
    (record["processing_engine"] as string) || "unknown";

  return (
    <>
      {/* Overlay */}
      <div
        ref={overlayRef}
        onClick={onClose}
        className="fixed inset-0 z-40 backdrop-blur-sm"
        style={{ backgroundColor: "rgba(15, 23, 42, 0.55)" }}
        aria-hidden="true"
      />

      {/* Drawer panel */}
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Document detail"
        className="fixed top-0 right-0 bottom-0 z-50 bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-slate-700 flex flex-col shadow-[-4px_0_24px_rgba(0,0,0,0.12)] overflow-y-auto"
        style={{ width: "min(560px, 100vw)" }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 dark:border-slate-700 sticky top-0 bg-white dark:bg-slate-900 z-[1]">
          <div className="flex items-center gap-2.5">
            <FileText className="w-[18px] h-[18px] text-blue-600 dark:text-blue-400" aria-hidden="true" />
            <div>
              <div className="text-[15px] font-semibold text-slate-900 dark:text-slate-50">
                Document Detail
              </div>
              <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-0.5">
                {sourceId} &nbsp;
                <ChevronRight
                  className="w-2.5 h-2.5 inline align-middle"
                  aria-hidden="true"
                />
                &nbsp;{documentId}
              </div>
            </div>
          </div>
          <button
            ref={closeRef}
            onClick={onClose}
            className="bg-transparent border-none cursor-pointer p-1.5 rounded-md text-slate-500 dark:text-slate-400 flex items-center hover:bg-slate-100 dark:hover:bg-slate-800"
            aria-label="Close document detail drawer"
          >
            <X className="w-[18px] h-[18px]" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 p-5 overflow-y-auto">
          {isLoading && (
            <div
              className="text-center py-10 text-slate-500 dark:text-slate-400"
              role="status"
              aria-live="polite"
            >
              Loading document…
            </div>
          )}

          {isError && (
            <div
              className="flex items-center gap-2 p-4 bg-red-50 dark:bg-red-950 border border-red-200 dark:border-red-800 rounded-lg text-red-600 dark:text-red-400"
              role="alert"
            >
              <AlertCircle className="w-4 h-4 shrink-0" aria-hidden="true" />
              <span className="text-[13px]">
                Failed to load document details. The source table may not exist yet.
              </span>
            </div>
          )}

          {data && (
            <>
              {/* Processing engine badge */}
              <div
                className="inline-flex items-center gap-1.5 bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-800 rounded-[14px] px-3 py-1 mb-5"
                aria-label={`Processing engine: ${processingEngine}`}
              >
                <Cpu className="w-[13px] h-[13px] text-blue-600 dark:text-blue-400" aria-hidden="true" />
                <span className="text-xs font-semibold text-blue-600 dark:text-blue-400">
                  {processingEngine}
                </span>
              </div>

              {/* Metadata section */}
              <section aria-label="Document metadata">
                <h2 className="text-[11px] font-semibold uppercase tracking-[0.07em] text-slate-400 dark:text-slate-500 mb-1">
                  Metadata
                </h2>
                <div>
                  {displayEntries.map(([k, v]) => (
                    <MetaRow
                      key={k}
                      label={prettyKey(k)}
                      value={
                        k === "file_size_bytes"
                          ? formatBytes(v as number)
                          : String(v ?? "")
                      }
                    />
                  ))}
                  {extraEntries.map(([k, v]) => (
                    <MetaRow key={k} label={prettyKey(k)} value={String(v ?? "")} />
                  ))}
                </div>
              </section>

              {/* Suspects section */}
              {suspects.length > 0 && (
                <section aria-label="Extracted suspects" className="mt-6">
                  <h2 className="text-[11px] font-semibold uppercase tracking-[0.07em] text-slate-400 dark:text-slate-500 mb-2">
                    Suspects extracted ({suspects.length})
                  </h2>
                  <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700">
                    <table
                      className="w-full border-collapse text-xs"
                      aria-label="Extracted suspect conditions"
                    >
                      <thead>
                        <tr className="bg-slate-100 dark:bg-slate-800">
                          <th scope="col" className="px-2.5 py-2 text-left font-semibold text-slate-500 dark:text-slate-400 text-[11px]">
                            HCC
                          </th>
                          <th scope="col" className="px-2.5 py-2 text-left font-semibold text-slate-500 dark:text-slate-400 text-[11px]">
                            ICD-10
                          </th>
                          <th scope="col" className="px-2.5 py-2 text-left font-semibold text-slate-500 dark:text-slate-400 text-[11px]">
                            Confidence
                          </th>
                          <th scope="col" className="px-2.5 py-2 text-left font-semibold text-slate-500 dark:text-slate-400 text-[11px]">
                            Evidence
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {suspects.map((s, i) => (
                          <SuspectRow key={i} suspect={s} idx={i} />
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}

              {suspects.length === 0 && !isLoading && (
                <div className="mt-6 p-4 bg-slate-100 dark:bg-slate-800 rounded-lg text-center text-slate-500 dark:text-slate-400 text-[13px]">
                  No suspects extracted from this document.
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer: Re-process action (admin only) */}
        {isAdmin && data && (
          <div className="px-5 py-4 border-t border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 sticky bottom-0">
            <div className="text-xs text-slate-500 dark:text-slate-400 mb-2">
              Re-process with different engine:
            </div>
            <div className="flex gap-2 flex-wrap">
              {["gemini_vision", "ocr_fallback", "clinical_nlp"].map((engine) => (
                <button
                  key={engine}
                  disabled={reprocessMutation.isPending}
                  onClick={() => reprocessMutation.mutate(engine)}
                  className={`inline-flex items-center gap-[5px] px-3.5 py-1.5 rounded-md text-xs font-medium ${
                    processingEngine === engine
                      ? "bg-blue-50 dark:bg-blue-950 border border-blue-600 dark:border-blue-400 text-blue-600 dark:text-blue-400"
                      : "bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-900 dark:text-slate-50"
                  } ${
                    reprocessMutation.isPending
                      ? "cursor-not-allowed opacity-60"
                      : "cursor-pointer"
                  }`}
                  aria-label={`Re-process with ${engine}`}
                  aria-pressed={processingEngine === engine}
                >
                  <RotateCcw className="w-3 h-3" aria-hidden="true" />
                  {engine}
                </button>
              ))}
            </div>
            {reprocessMutation.isSuccess && (
              <div
                role="status"
                aria-live="polite"
                className="mt-2 text-xs text-emerald-500 dark:text-emerald-400"
              >
                Re-processing queued successfully.
              </div>
            )}
            {reprocessMutation.isError && (
              <div
                role="alert"
                className="mt-2 text-xs text-red-600 dark:text-red-400"
              >
                Failed to queue re-processing. Try again.
              </div>
            )}
          </div>
        )}
      </aside>
    </>
  );
}
