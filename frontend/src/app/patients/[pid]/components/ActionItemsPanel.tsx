"use client";

/**
 * ActionItemsPanel — "Today's action items" two-column layout.
 *
 * Left 3/4 column: top-5 HCC suspects with inline lab evidence,
 * 1-click Accept/Decline/Review, keyboard shortcuts (a/d/r), and
 * inline MEAT evidence expansion.
 *
 * Right 1/4 column: top-3 open HEDIS gaps.
 *
 * Source-document chip: when suspect has source_document_id, render a
 * "📄 filename (page N)" chip. Clicking opens a side drawer stub that
 * shows filename + page (no PDF viewer integration yet).
 *
 * Usage:
 *   <ActionItemsPanel pid={pid} year={year} suspects={suspectsQ.data}
 *     suspectsLoading={false} acceptMutation={...} dismissMutation={...} />
 */

import React, { useState, useCallback, useRef, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { getPatientHedisGaps } from "@/lib/api";
import type { PatientSuspectsResponse } from "@/lib/api";
import { C, formatDate, MeatDots, Card } from "./shared";
import type { SuspectItem } from "./shared";
import {
  AcceptConfirmDialog,
  type AcceptOverridePayload,
} from "@/components/AcceptConfirmDialog";
import { DismissReasonDialog } from "@/components/raf-central/Suspects/DismissReasonDialog";
import { ConfidencePill } from "@/components/healthcare-ui";

// ---- small helpers ----------------------------------------------------------

function SignalStrengthChip({ confidence }: { confidence: number }) {
  const pct = Math.round(confidence * 100);
  const color =
    pct >= 80 ? C.emerald600 : pct >= 50 ? C.amber600 : C.red600;
  const bg =
    pct >= 80 ? C.emerald100 : pct >= 50 ? C.amber100 : C.red100;
  const label = pct >= 80 ? "High" : pct >= 50 ? "Medium" : "Low";
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: 6,
        fontSize: 10,
        fontWeight: 700,
        background: bg,
        color,
        letterSpacing: "0.03em",
      }}
      aria-label={`Signal strength: ${label} (${pct}%)`}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: color,
          flexShrink: 0,
        }}
        aria-hidden="true"
      />
      {label}
    </span>
  );
}

function DollarPill({ coefficient }: { coefficient?: number | null }) {
  if (!coefficient) return null;
  const annual = Math.round(coefficient * 10_000);
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px 8px",
        borderRadius: 6,
        fontSize: 10,
        fontWeight: 700,
        background: C.emerald50,
        color: C.emerald600,
        border: `1px solid ${C.emerald100}`,
      }}
      aria-label={`Estimated annual value: $${annual.toLocaleString()}`}
    >
      ${annual.toLocaleString()}/yr
    </span>
  );
}

interface DocChipProps {
  documentId?: string | number | null;
  documentName?: string | null;
  documentPage?: number | null;
  onOpen: () => void;
}

function DocChip({ documentName, documentPage, onOpen }: DocChipProps) {
  if (!documentName) return null;
  const label = documentPage
    ? `${documentName} (page ${documentPage})`
    : documentName;
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onOpen();
      }}
      aria-label={`View source document: ${label}`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 8px",
        borderRadius: 6,
        fontSize: 10,
        fontWeight: 600,
        background: C.amber50,
        color: C.amber600,
        border: `1px solid ${C.amber100}`,
        cursor: "pointer",
        maxWidth: 220,
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
      }}
    >
      <svg
        width="11"
        height="11"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        style={{ flexShrink: 0 }}
      >
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
      </svg>
      {label}
    </button>
  );
}

// ---- Document side drawer stub ---------------------------------------------

function DocDrawer({
  open,
  onClose,
  documentName,
  documentPage,
}: {
  open: boolean;
  onClose: () => void;
  documentName?: string | null;
  documentPage?: number | null;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (open) closeRef.current?.focus();
  }, [open]);

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.35)",
          zIndex: 200,
        }}
        aria-hidden="true"
        onClick={onClose}
      />
      {/* Drawer */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Source document"
        style={{
          position: "fixed",
          right: 0,
          top: 0,
          bottom: 0,
          width: 380,
          background: C.white,
          boxShadow: "-4px 0 24px rgba(0,0,0,0.12)",
          zIndex: 201,
          display: "flex",
          flexDirection: "column",
          padding: 24,
          gap: 16,
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <h2
            style={{ margin: 0, fontSize: 16, fontWeight: 700, color: C.slate800 }}
          >
            Source Document
          </h2>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close document drawer"
            style={{
              background: "transparent",
              border: `1px solid ${C.slate200}`,
              borderRadius: 6,
              width: 32,
              height: 32,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: C.slate600,
            }}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        <div
          style={{
            padding: 16,
            background: C.amber50,
            border: `1px solid ${C.amber100}`,
            borderRadius: 10,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: 10,
            }}
          >
            <svg
              width="24"
              height="24"
              viewBox="0 0 24 24"
              fill="none"
              stroke={C.amber600}
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
              style={{ flexShrink: 0, marginTop: 2 }}
            >
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
              <polyline points="10 9 9 9 8 9" />
            </svg>
            <div>
              <div
                style={{
                  fontSize: 13,
                  fontWeight: 700,
                  color: C.slate800,
                  wordBreak: "break-all",
                }}
              >
                {documentName ?? "Unknown document"}
              </div>
              {documentPage && (
                <div
                  style={{
                    marginTop: 4,
                    fontSize: 12,
                    color: C.amber600,
                    fontWeight: 600,
                  }}
                >
                  Page {documentPage}
                </div>
              )}
            </div>
          </div>
        </div>

        <div
          style={{
            padding: 12,
            background: C.slate100,
            borderRadius: 8,
            fontSize: 12,
            color: C.slate500,
            lineHeight: 1.5,
          }}
        >
          PDF viewer integration coming soon. The evidence for this HCC suspect was
          extracted from the document above. Navigate to the Documents tab to view
          the full file.
        </div>
      </div>
    </>
  );
}

// ---- HCC suspect card -------------------------------------------------------

interface HccCardProps {
  suspect: SuspectItem;
  index: number;
  onAccept: () => void;
  onDismiss: () => void;
  acceptPending: boolean;
  dismissPending: boolean;
}

function HccCard({
  suspect: s,
  index,
  onAccept,
  onDismiss,
  acceptPending,
  dismissPending,
}: HccCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [docDrawerOpen, setDocDrawerOpen] = useState(false);

  const confidence = s.confidence_score ?? s.confidence ?? 0;
  const borderColor =
    confidence >= 0.8
      ? C.emerald600
      : confidence >= 0.5
      ? C.amber600
      : C.red600;

  // Source document metadata — handle various field names defensively
  const sAny = s as unknown as Record<string, unknown>;
  const sourceDocId = sAny.source_document_id as string | number | null | undefined;
  const sourceDocName = sAny.source_document_name as string | null | undefined;
  const sourceDocPage = sAny.source_document_page as number | null | undefined;

  // Keyboard handler: a=accept, d=dismiss, space/enter=expand
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>) => {
      if (e.target !== e.currentTarget) return; // don't steal from child buttons
      if (e.key === "a" || e.key === "A") {
        e.preventDefault();
        onAccept();
      } else if (e.key === "d" || e.key === "D") {
        e.preventDefault();
        onDismiss();
      } else if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        setExpanded((v) => !v);
      }
    },
    [onAccept, onDismiss]
  );

  return (
    <>
      <div
        tabIndex={0}
        role="article"
        aria-label={`HCC suspect ${index + 1}: ${s.suspected_condition || s.condition || "Unknown condition"}. Press A to accept, D to dismiss, Enter to expand.`}
        onKeyDown={handleKeyDown}
        style={{
          background: C.white,
          border: `1px solid ${C.slate200}`,
          borderLeft: `4px solid ${borderColor}`,
          borderRadius: 10,
          padding: "14px 16px",
          cursor: "pointer",
          outline: "none",
          transition: "box-shadow 0.15s",
        }}
        onFocus={(e) =>
          (e.currentTarget.style.boxShadow = `0 0 0 2px ${C.blue600}`)
        }
        onBlur={(e) => (e.currentTarget.style.boxShadow = "none")}
        onClick={() => setExpanded((v) => !v)}
      >
        {/* Top row: condition + chips */}
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 12,
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                fontSize: 13,
                fontWeight: 700,
                color: C.slate800,
                marginBottom: 6,
                lineHeight: 1.3,
              }}
            >
              {s.suspected_condition || s.condition || s.evidence_type || "—"}
            </div>

            {/* Chips row */}
            <div
              style={{
                display: "flex",
                flexWrap: "wrap",
                gap: 5,
                alignItems: "center",
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <SignalStrengthChip confidence={confidence} />
              <DollarPill coefficient={s.hcc_coefficient} />

              {(s.suspect_icd10 || s.icd10_code) && (
                <span
                  style={{
                    display: "inline-block",
                    padding: "2px 7px",
                    borderRadius: 4,
                    fontSize: 10,
                    fontWeight: 600,
                    fontFamily: "monospace",
                    background: C.slate100,
                    color: C.slate700,
                    border: `1px solid ${C.slate200}`,
                  }}
                >
                  {s.suspect_icd10 || s.icd10_code}
                </span>
              )}

              {s.suspect_hcc != null && (
                <span
                  style={{
                    display: "inline-block",
                    padding: "2px 7px",
                    borderRadius: 4,
                    fontSize: 10,
                    fontWeight: 600,
                    fontFamily: "monospace",
                    background: C.blue50,
                    color: C.blue600,
                    border: `1px solid ${C.blue100}`,
                  }}
                >
                  HCC {s.suspect_hcc}
                </span>
              )}

              {/* Source doc chip */}
              {(sourceDocId || sourceDocName) && (
                <DocChip
                  documentId={sourceDocId}
                  documentName={sourceDocName}
                  documentPage={sourceDocPage}
                  onOpen={() => setDocDrawerOpen(true)}
                />
              )}
            </div>
          </div>

          {/* Action buttons */}
          <div
            style={{ display: "flex", gap: 6, flexShrink: 0 }}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              onClick={onAccept}
              disabled={acceptPending}
              title="Accept (keyboard: A)"
              aria-label="Accept this HCC suspect"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                padding: "6px 12px",
                borderRadius: 7,
                border: `1px solid ${C.emerald500}`,
                background: C.emerald50,
                color: C.emerald600,
                fontSize: 11,
                fontWeight: 700,
                cursor: acceptPending ? "not-allowed" : "pointer",
                opacity: acceptPending ? 0.6 : 1,
              }}
            >
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <polyline points="20 6 9 17 4 12" />
              </svg>
              Accept
            </button>
            <button
              type="button"
              onClick={onDismiss}
              disabled={dismissPending}
              title="Dismiss (keyboard: D)"
              aria-label="Dismiss this HCC suspect"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                padding: "6px 12px",
                borderRadius: 7,
                border: `1px solid ${C.red500}`,
                background: C.red50,
                color: C.red600,
                fontSize: 11,
                fontWeight: 700,
                cursor: dismissPending ? "not-allowed" : "pointer",
                opacity: dismissPending ? 0.6 : 1,
              }}
            >
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
              Dismiss
            </button>
          </div>
        </div>

        {/* Expand toggle chevron */}
        <div
          style={{
            marginTop: 8,
            display: "flex",
            alignItems: "center",
            gap: 4,
            fontSize: 11,
            color: C.slate400,
            userSelect: "none",
          }}
        >
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
            style={{
              transform: expanded ? "rotate(180deg)" : "rotate(0deg)",
              transition: "transform 0.2s",
            }}
          >
            <polyline points="6 9 12 15 18 9" />
          </svg>
          {expanded ? "Hide" : "Show"} MEAT evidence
        </div>

        {/* Expanded: MEAT + evidence text */}
        {expanded && (
          <div
            style={{
              marginTop: 12,
              paddingTop: 12,
              borderTop: `1px solid ${C.slate100}`,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {s.meat_evidence && (
              <div style={{ marginBottom: 10 }}>
                <div
                  style={{
                    fontSize: 10,
                    fontWeight: 600,
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                    color: C.slate400,
                    marginBottom: 6,
                  }}
                >
                  MEAT Documentation
                </div>
                <MeatDots evidence={s.meat_evidence} />
              </div>
            )}

            {(s.evidence_detail || s.evidence || s.rationale) && (
              <div>
                <div
                  style={{
                    fontSize: 10,
                    fontWeight: 600,
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                    color: C.slate400,
                    marginBottom: 4,
                  }}
                >
                  Evidence
                </div>
                <div
                  style={{
                    fontSize: 12,
                    color: C.slate600,
                    lineHeight: 1.5,
                  }}
                >
                  {typeof s.evidence_detail === "object" && s.evidence_detail
                    ? `Prior ${
                        (
                          s.evidence_detail as {
                            prior_icd?: string;
                            prior_year?: string | number;
                          }
                        ).prior_icd || ""
                      } (${
                        (
                          s.evidence_detail as {
                            prior_icd?: string;
                            prior_year?: string | number;
                          }
                        ).prior_year || ""
                      })`
                    : typeof s.evidence_detail === "string"
                    ? s.evidence_detail
                    : s.evidence || s.rationale}
                </div>
              </div>
            )}

            {/* Source doc reference */}
            {sourceDocName && (
              <div style={{ marginTop: 10 }}>
                <div
                  style={{
                    fontSize: 10,
                    fontWeight: 600,
                    textTransform: "uppercase",
                    letterSpacing: "0.05em",
                    color: C.slate400,
                    marginBottom: 4,
                  }}
                >
                  Source Document
                </div>
                <DocChip
                  documentId={sourceDocId}
                  documentName={sourceDocName}
                  documentPage={sourceDocPage}
                  onOpen={() => setDocDrawerOpen(true)}
                />
              </div>
            )}

            {s.source && (
              <div
                style={{ marginTop: 8, fontSize: 11, color: C.slate400 }}
              >
                Source: {s.source}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Document drawer */}
      <DocDrawer
        open={docDrawerOpen}
        onClose={() => setDocDrawerOpen(false)}
        documentName={sourceDocName}
        documentPage={sourceDocPage}
      />
    </>
  );
}

// ---- HEDIS gap compact card -------------------------------------------------

interface HedisGapCardProps {
  measureId: string;
  measureName: string;
  color: string;
  bg: string;
  lastValue?: string;
  pid: string | number;
}

function HedisGapCard({
  measureId,
  measureName,
  color,
  bg,
  lastValue,
  pid,
}: HedisGapCardProps) {
  return (
    <a
      href={`/hedis?patient_id=${pid}&measure=${measureId}`}
      aria-label={`Close ${measureId} gap: ${measureName}`}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: "10px 14px",
        borderRadius: 10,
        border: `1px solid ${color}40`,
        background: `${bg}cc`,
        textDecoration: "none",
        transition: "box-shadow 0.15s",
      }}
      onFocus={(e) =>
        (e.currentTarget.style.boxShadow = `0 0 0 2px ${color}`)
      }
      onBlur={(e) => (e.currentTarget.style.boxShadow = "none")}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "2px 7px",
            borderRadius: 5,
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: "0.04em",
            background: color,
            color: "#fff",
            flexShrink: 0,
          }}
        >
          {measureId}
        </span>
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: C.slate700,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
          title={measureName}
        >
          {measureName}
        </span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span
          style={{
            width: 7,
            height: 7,
            borderRadius: "50%",
            background: "#EF4444",
            flexShrink: 0,
          }}
          aria-hidden="true"
        />
        <span style={{ fontSize: 11, fontWeight: 600, color: "#DC2626" }}>
          Gap open
        </span>
        {lastValue && (
          <span style={{ fontSize: 11, color: C.slate500 }}>
            · Last: {lastValue}
          </span>
        )}
      </div>
      <span
        style={{
          fontSize: 10,
          fontWeight: 700,
          color,
          marginTop: 2,
          display: "inline-flex",
          alignItems: "center",
          gap: 3,
        }}
      >
        Close gap
        <svg
          width="10"
          height="10"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <polyline points="9 18 15 12 9 6" />
        </svg>
      </span>
    </a>
  );
}

// ---- measure metadata -------------------------------------------------------

const MEASURE_META: Record<string, { short: string; color: string; bg: string }> =
  {
    BCS: { short: "Breast Cancer Screening", color: "#7C3AED", bg: "#EDE9FE" },
    CCS: { short: "Cervical Cancer Screening", color: "#BE185D", bg: "#FCE7F3" },
    HBD: { short: "A1c Control (Diabetes)", color: "#B45309", bg: "#FEF3C7" },
    CBP: { short: "Blood Pressure Control", color: "#0369A1", bg: "#E0F2FE" },
    FUM: {
      short: "Follow-Up (Mental Health ED)",
      color: "#065F46",
      bg: "#D1FAE5",
    },
  };

function measureMeta(id: string) {
  return (
    MEASURE_META[id] ?? { short: id, color: C.slate600, bg: C.slate100 }
  );
}

// ---- main component ---------------------------------------------------------

interface ActionItemsPanelProps {
  pid: string;
  year: number;
  suspects: PatientSuspectsResponse | undefined;
  suspectsLoading: boolean;
  acceptMutation: {
    mutate: (id: number) => void;
    isPending: boolean;
  };
  dismissMutation: {
    mutate: (id: number) => void;
    isPending: boolean;
  };
}

export function ActionItemsPanel({
  pid,
  year,
  suspects,
  suspectsLoading,
  acceptMutation,
  dismissMutation,
}: ActionItemsPanelProps) {
  const [confirmAccept, setConfirmAccept] = useState<SuspectItem | null>(null);
  const [confirmDismiss, setConfirmDismiss] = useState<SuspectItem | null>(null);

  // HEDIS gaps query — top-3 open gaps
  const hedisQ = useQuery({
    queryKey: ["patient-hedis-gaps", pid, year],
    queryFn: () => getPatientHedisGaps(pid, year),
    staleTime: 30_000,
    retry: 1,
  });

  const suspectList: SuspectItem[] = (suspects?.suspects ?? []) as SuspectItem[];
  // Top 5 open suspects
  const topSuspects = suspectList.slice(0, 5);

  const openHedisGaps = (hedisQ.data?.open_gaps ?? []).slice(0, 3);

  const handleAcceptConfirmed = (_payload: AcceptOverridePayload) => {
    if (!confirmAccept) return;
    acceptMutation.mutate(confirmAccept.id);
    setConfirmAccept(null);
  };

  const handleDismissConfirmed = (_reason: string) => {
    if (!confirmDismiss) return;
    dismissMutation.mutate(confirmDismiss.id);
    setConfirmDismiss(null);
  };

  const hasActions = topSuspects.length > 0 || openHedisGaps.length > 0;

  if (!hasActions && !suspectsLoading && !hedisQ.isLoading) {
    return null; // Nothing to show — section is omitted entirely
  }

  return (
    <section
      aria-label="Today's action items"
      style={{
        background: C.white,
        border: `1px solid ${C.slate200}`,
        borderRadius: 14,
        overflow: "hidden",
        marginBottom: 20,
      }}
    >
      {/* Section header */}
      <div
        style={{
          padding: "14px 20px",
          borderBottom: `1px solid ${C.slate100}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 8,
          background: `linear-gradient(135deg, ${C.blue50}, ${C.white})`,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div
            style={{
              width: 28,
              height: 28,
              borderRadius: 8,
              background: `linear-gradient(135deg, ${C.blue600}, ${C.emerald600})`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#fff"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
            </svg>
          </div>
          <h2
            style={{
              margin: 0,
              fontSize: 14,
              fontWeight: 700,
              color: C.slate800,
              letterSpacing: "-0.01em",
            }}
          >
            Today&rsquo;s Action Items
          </h2>
          {(topSuspects.length > 0 || openHedisGaps.length > 0) && (
            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                padding: "2px 8px",
                borderRadius: 999,
                fontSize: 11,
                fontWeight: 700,
                background: C.amber100,
                color: C.amber600,
              }}
              aria-label={`${topSuspects.length + openHedisGaps.length} items need attention`}
            >
              {topSuspects.length + openHedisGaps.length} items
            </span>
          )}
        </div>
        <span style={{ fontSize: 11, color: C.slate400 }}>
          Keyboard: A = accept &middot; D = dismiss &middot; Enter = expand
        </span>
      </div>

      {/* Two-column body: HCC suspects (3/4) + HEDIS gaps (1/4) */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "3fr 1fr",
          gap: 0,
          minHeight: 100,
        }}
        className="action-items-grid"
      >
        {/* ---- HCC Suspects ---- */}
        <div
          style={{
            padding: 16,
            borderRight: `1px solid ${C.slate100}`,
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          <div
            style={{
              fontSize: 11,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              color: C.slate400,
              marginBottom: 2,
            }}
          >
            HCC Suspects
            {topSuspects.length > 0 && (
              <span
                style={{
                  marginLeft: 6,
                  padding: "1px 6px",
                  borderRadius: 4,
                  background: C.amber100,
                  color: C.amber600,
                  fontSize: 10,
                }}
              >
                {topSuspects.length}
              </span>
            )}
          </div>

          {suspectsLoading && (
            <div
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 8,
              }}
            >
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  style={{
                    height: 68,
                    borderRadius: 10,
                    background:
                      "linear-gradient(90deg,#f1f5f9 25%,#e2e8f0 50%,#f1f5f9 75%)",
                    backgroundSize: "200% 100%",
                    animation: `shimmer 1.5s ${i * 120}ms infinite`,
                  }}
                />
              ))}
              <style>{`@keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}`}</style>
            </div>
          )}

          {!suspectsLoading && topSuspects.length === 0 && (
            <div
              style={{
                padding: "24px 0",
                textAlign: "center",
                color: C.slate400,
                fontSize: 13,
              }}
            >
              No open HCC suspects — all clear.
            </div>
          )}

          {!suspectsLoading &&
            topSuspects.map((s, idx) => (
              <HccCard
                key={s.id}
                suspect={s}
                index={idx}
                onAccept={() => setConfirmAccept(s)}
                onDismiss={() => setConfirmDismiss(s)}
                acceptPending={acceptMutation.isPending}
                dismissPending={dismissMutation.isPending}
              />
            ))}
        </div>

        {/* ---- HEDIS Gaps ---- */}
        <div
          style={{
            padding: 16,
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          <div
            style={{
              fontSize: 11,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              color: C.slate400,
              marginBottom: 2,
            }}
          >
            HEDIS Gaps
            {openHedisGaps.length > 0 && (
              <span
                style={{
                  marginLeft: 6,
                  padding: "1px 6px",
                  borderRadius: 4,
                  background: C.red100,
                  color: C.red600,
                  fontSize: 10,
                }}
              >
                {openHedisGaps.length}
              </span>
            )}
          </div>

          {hedisQ.isLoading && (
            <div
              style={{
                height: 70,
                borderRadius: 10,
                background:
                  "linear-gradient(90deg,#f1f5f9 25%,#e2e8f0 50%,#f1f5f9 75%)",
                backgroundSize: "200% 100%",
                animation: "shimmer 1.5s infinite",
              }}
            />
          )}

          {!hedisQ.isLoading && openHedisGaps.length === 0 && (
            <div
              style={{
                padding: "24px 0",
                textAlign: "center",
                color: C.emerald600,
                fontSize: 12,
                fontWeight: 600,
              }}
            >
              All HEDIS gaps met
            </div>
          )}

          {!hedisQ.isLoading &&
            openHedisGaps.map((gap) => {
              const meta = measureMeta(gap.measure_id);
              return (
                <HedisGapCard
                  key={gap.measure_id}
                  measureId={gap.measure_id}
                  measureName={meta.short}
                  color={meta.color}
                  bg={meta.bg}
                  lastValue={gap.last_value ?? undefined}
                  pid={pid}
                />
              );
            })}
        </div>
      </div>

      {/* Responsive: stack on small screens */}
      <style>{`
        @media (max-width: 640px) {
          .action-items-grid {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>

      {/* RADV dialogs */}
      <AcceptConfirmDialog
        open={confirmAccept !== null}
        onClose={() => setConfirmAccept(null)}
        onConfirm={handleAcceptConfirmed}
        suspect={{
          hcc_code:
            confirmAccept?.suspect_hcc ?? confirmAccept?.hcc_code ?? null,
          icd10_code:
            confirmAccept?.suspect_icd10 ?? confirmAccept?.icd10_code ?? null,
          confidence:
            confirmAccept?.confidence_score ??
            confirmAccept?.confidence ??
            null,
          meat_status: null,
          meat_count: null,
          clinical_rule_violation: null,
          expected_dollar_impact: null,
        }}
      />
      <DismissReasonDialog
        open={confirmDismiss !== null}
        suspectLabel={
          confirmDismiss
            ? [
                confirmDismiss.suspected_condition ||
                  confirmDismiss.condition ||
                  "",
                confirmDismiss.suspect_icd10 ||
                  confirmDismiss.icd10_code ||
                  "",
              ]
                .filter(Boolean)
                .join(" · ")
            : ""
        }
        onCancel={() => setConfirmDismiss(null)}
        onSubmit={handleDismissConfirmed}
      />
    </section>
  );
}
