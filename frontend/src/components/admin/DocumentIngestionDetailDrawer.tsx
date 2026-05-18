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
// Design tokens (match existing palette)
// ---------------------------------------------------------------------------

const T = {
  bg: "#FFFFFF",
  border: "#E2E8F0",
  text: "#0F172A",
  muted: "#64748B",
  subtle: "#94A3B8",
  accent: "#2563EB",
  accentBg: "#EFF6FF",
  success: "#10B981",
  warning: "#F59E0B",
  danger: "#DC2626",
  overlay: "rgba(15, 23, 42, 0.55)",
  badgeBg: "#F1F5F9",
} as const;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function confidenceColor(score: number): string {
  if (score >= 0.8) return T.success;
  if (score >= 0.5) return T.warning;
  return T.danger;
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
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "flex-start",
        padding: "8px 0",
        borderBottom: `1px solid ${T.border}`,
        gap: 12,
      }}
    >
      <span style={{ fontSize: 12, color: T.muted, fontWeight: 500, flexShrink: 0 }}>
        {label}
      </span>
      <span
        style={{
          fontSize: 13,
          color: T.text,
          textAlign: "right",
          wordBreak: "break-all",
        }}
      >
        {value ?? "—"}
      </span>
    </div>
  );
}

function SuspectRow({ suspect, idx }: { suspect: Suspect; idx: number }) {
  const pct = Math.round(suspect.confidence_score * 100);
  return (
    <tr
      style={{
        backgroundColor: idx % 2 === 0 ? T.bg : T.badgeBg,
      }}
    >
      <td style={{ padding: "8px 10px", fontSize: 12, fontFamily: "monospace", color: T.accent }}>
        {suspect.hcc_code || "—"}
      </td>
      <td style={{ padding: "8px 10px", fontSize: 12, fontFamily: "monospace" }}>
        {suspect.icd10_code || "—"}
      </td>
      <td style={{ padding: "8px 10px", fontSize: 12 }}>
        <span
          style={{
            fontWeight: 600,
            color: confidenceColor(suspect.confidence_score),
          }}
          aria-label={`Confidence ${pct}%`}
        >
          {pct}%
        </span>
      </td>
      <td
        style={{
          padding: "8px 10px",
          fontSize: 11,
          color: T.muted,
          maxWidth: 260,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
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

  // Focus trap: focus close button on open
  useEffect(() => {
    if (open) {
      setTimeout(() => closeRef.current?.focus(), 50);
    }
  }, [open]);

  // ESC to close
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape" && open) onClose();
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  // Prevent body scroll while open
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

  // Pick display fields present in the record
  const displayEntries = DISPLAY_FIELDS.filter((k) => k in record).map(
    (k) => [k, record[k]] as [string, unknown]
  );

  // Also show remaining fields not in display list
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
        style={{
          position: "fixed",
          inset: 0,
          zIndex: 40,
          backgroundColor: T.overlay,
          backdropFilter: "blur(2px)",
        }}
        aria-hidden="true"
      />

      {/* Drawer panel */}
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Document detail"
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          bottom: 0,
          zIndex: 50,
          width: "min(560px, 100vw)",
          backgroundColor: T.bg,
          borderLeft: `1px solid ${T.border}`,
          display: "flex",
          flexDirection: "column",
          boxShadow: "-4px 0 24px rgba(0,0,0,0.12)",
          overflowY: "auto",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "16px 20px",
            borderBottom: `1px solid ${T.border}`,
            position: "sticky",
            top: 0,
            backgroundColor: T.bg,
            zIndex: 1,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <FileText style={{ width: 18, height: 18, color: T.accent }} aria-hidden="true" />
            <div>
              <div style={{ fontSize: 15, fontWeight: 600, color: T.text }}>
                Document Detail
              </div>
              <div style={{ fontSize: 11, color: T.muted, marginTop: 2 }}>
                {sourceId} &nbsp;
                <ChevronRight
                  style={{ width: 10, height: 10, display: "inline", verticalAlign: "middle" }}
                  aria-hidden="true"
                />
                &nbsp;{documentId}
              </div>
            </div>
          </div>
          <button
            ref={closeRef}
            onClick={onClose}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 6,
              borderRadius: 6,
              color: T.muted,
              display: "flex",
              alignItems: "center",
            }}
            aria-label="Close document detail drawer"
          >
            <X style={{ width: 18, height: 18 }} />
          </button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, padding: "20px", overflowY: "auto" }}>
          {isLoading && (
            <div
              style={{ textAlign: "center", padding: "40px 0", color: T.muted }}
              role="status"
              aria-live="polite"
            >
              Loading document…
            </div>
          )}

          {isError && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "16px",
                backgroundColor: "#FEF2F2",
                border: `1px solid #FECACA`,
                borderRadius: 8,
                color: T.danger,
              }}
              role="alert"
            >
              <AlertCircle style={{ width: 16, height: 16, flexShrink: 0 }} aria-hidden="true" />
              <span style={{ fontSize: 13 }}>
                Failed to load document details. The source table may not exist yet.
              </span>
            </div>
          )}

          {data && (
            <>
              {/* Processing engine badge */}
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  backgroundColor: T.accentBg,
                  border: `1px solid #BFDBFE`,
                  borderRadius: 14,
                  padding: "4px 12px",
                  marginBottom: 20,
                }}
                aria-label={`Processing engine: ${processingEngine}`}
              >
                <Cpu style={{ width: 13, height: 13, color: T.accent }} aria-hidden="true" />
                <span style={{ fontSize: 12, fontWeight: 600, color: T.accent }}>
                  {processingEngine}
                </span>
              </div>

              {/* Metadata section */}
              <section aria-label="Document metadata">
                <h2
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    textTransform: "uppercase",
                    letterSpacing: "0.07em",
                    color: T.subtle,
                    marginBottom: 4,
                  }}
                >
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
                <section aria-label="Extracted suspects" style={{ marginTop: 24 }}>
                  <h2
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      textTransform: "uppercase",
                      letterSpacing: "0.07em",
                      color: T.subtle,
                      marginBottom: 8,
                    }}
                  >
                    Suspects extracted ({suspects.length})
                  </h2>
                  <div style={{ overflowX: "auto", borderRadius: 8, border: `1px solid ${T.border}` }}>
                    <table
                      style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}
                      aria-label="Extracted suspect conditions"
                    >
                      <thead>
                        <tr style={{ backgroundColor: T.badgeBg }}>
                          <th
                            scope="col"
                            style={{ padding: "8px 10px", textAlign: "left", fontWeight: 600, color: T.muted, fontSize: 11 }}
                          >
                            HCC
                          </th>
                          <th
                            scope="col"
                            style={{ padding: "8px 10px", textAlign: "left", fontWeight: 600, color: T.muted, fontSize: 11 }}
                          >
                            ICD-10
                          </th>
                          <th
                            scope="col"
                            style={{ padding: "8px 10px", textAlign: "left", fontWeight: 600, color: T.muted, fontSize: 11 }}
                          >
                            Confidence
                          </th>
                          <th
                            scope="col"
                            style={{ padding: "8px 10px", textAlign: "left", fontWeight: 600, color: T.muted, fontSize: 11 }}
                          >
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
                <div
                  style={{
                    marginTop: 24,
                    padding: "16px",
                    backgroundColor: T.badgeBg,
                    borderRadius: 8,
                    textAlign: "center",
                    color: T.muted,
                    fontSize: 13,
                  }}
                >
                  No suspects extracted from this document.
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer: Re-process action (admin only) */}
        {isAdmin && data && (
          <div
            style={{
              padding: "16px 20px",
              borderTop: `1px solid ${T.border}`,
              backgroundColor: T.bg,
              position: "sticky",
              bottom: 0,
            }}
          >
            <div style={{ fontSize: 12, color: T.muted, marginBottom: 8 }}>
              Re-process with different engine:
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {["gemini_vision", "ocr_fallback", "clinical_nlp"].map((engine) => (
                <button
                  key={engine}
                  disabled={reprocessMutation.isPending}
                  onClick={() => reprocessMutation.mutate(engine)}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 5,
                    padding: "6px 14px",
                    backgroundColor:
                      processingEngine === engine ? T.accentBg : T.badgeBg,
                    border: `1px solid ${processingEngine === engine ? T.accent : T.border}`,
                    borderRadius: 6,
                    fontSize: 12,
                    fontWeight: 500,
                    color: processingEngine === engine ? T.accent : T.text,
                    cursor: reprocessMutation.isPending ? "not-allowed" : "pointer",
                    opacity: reprocessMutation.isPending ? 0.6 : 1,
                  }}
                  aria-label={`Re-process with ${engine}`}
                  aria-pressed={processingEngine === engine}
                >
                  <RotateCcw style={{ width: 12, height: 12 }} aria-hidden="true" />
                  {engine}
                </button>
              ))}
            </div>
            {reprocessMutation.isSuccess && (
              <div
                role="status"
                aria-live="polite"
                style={{ marginTop: 8, fontSize: 12, color: T.success }}
              >
                Re-processing queued successfully.
              </div>
            )}
            {reprocessMutation.isError && (
              <div
                role="alert"
                style={{ marginTop: 8, fontSize: 12, color: T.danger }}
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
