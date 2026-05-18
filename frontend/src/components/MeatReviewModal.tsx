"use client";

/**
 * <MeatReviewModal /> — Dual-coder review modal for a single recapture gap.
 *
 * Two columns:
 *   Left  — original evidence (phrase + source link, read-only)
 *   Right — MEAT element radio + reviewer notes textarea
 *
 * Bottom — Approve / Reject buttons. Reject reveals a required reason field.
 *
 * On success the modal calls onChange() so the parent can refetch the queue.
 */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { X, ExternalLink, Check, AlertTriangle } from "lucide-react";

import {
  approveGapReview,
  rejectGapReview,
  type MeatElement,
  type RecaptureGapAudit,
} from "@/lib/api";

interface MeatReviewModalProps {
  gap: RecaptureGapAudit;
  onClose: () => void;
  onChange?: (updated: RecaptureGapAudit) => void;
}

const MEAT_LABELS: Record<MeatElement, string> = {
  M: "Monitor",
  E: "Evaluate",
  A: "Assess",
  T: "Treat",
  MULTI: "Multiple",
};

export function MeatReviewModal({ gap, onClose, onChange }: MeatReviewModalProps) {
  const [reviewerNotes, setReviewerNotes] = useState("");
  const [rejectMode, setRejectMode] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const approveMut = useMutation({
    mutationFn: () => approveGapReview(gap.id, reviewerNotes || undefined),
    onSuccess: (updated) => {
      onChange?.(updated);
      onClose();
    },
    onError: (err: Error) => setError(err.message || "Approval failed"),
  });

  const rejectMut = useMutation({
    mutationFn: () => rejectGapReview(gap.id, rejectReason),
    onSuccess: (updated) => {
      onChange?.(updated);
      onClose();
    },
    onError: (err: Error) => setError(err.message || "Reject failed"),
  });

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="meat-review-title"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15, 23, 42, 0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
        padding: 16,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#fff",
          borderRadius: 10,
          width: "100%",
          maxWidth: 880,
          maxHeight: "90vh",
          overflowY: "auto",
          boxShadow: "0 20px 60px rgba(15,23,42,0.3)",
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "16px 24px",
            borderBottom: "1px solid #e2e8f0",
          }}
        >
          <div>
            <h2 id="meat-review-title" style={{ margin: 0, fontSize: 18, color: "#0f172a" }}>
              MEAT Review — HCC {gap.hcc_code} ({gap.icd10_code})
            </h2>
            <p style={{ margin: "4px 0 0", fontSize: 12, color: "#64748b" }}>
              Patient {gap.patient_id}
              {gap.patient_name ? ` · ${gap.patient_name}` : ""} ·{" "}
              ${(Number(gap.revenue_impact) || 0).toLocaleString()} revenue
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            style={{
              border: "none", background: "transparent", cursor: "pointer",
              color: "#64748b", padding: 4,
            }}
          >
            <X size={20} />
          </button>
        </div>

        {/* Body — 2-column layout */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 24,
            padding: 24,
          }}
        >
          {/* Left: original evidence */}
          <div>
            <h3 style={{ margin: "0 0 8px", fontSize: 13, color: "#475569", textTransform: "uppercase", letterSpacing: "0.05em" }}>
              Primary Evidence
            </h3>
            <div
              style={{
                padding: 14,
                borderLeft: "3px solid #2563eb",
                background: "#eff6ff",
                borderRadius: 4,
                fontSize: 13.5,
                color: "#1e3a8a",
                fontStyle: "italic",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                minHeight: 100,
              }}
            >
              {gap.evidence_phrase || "(no phrase recorded — return to primary coder)"}
            </div>
            <div style={{ marginTop: 10, fontSize: 12, color: "#475569" }}>
              <strong>MEAT Element:</strong>{" "}
              {gap.meat_element ? `${gap.meat_element} (${MEAT_LABELS[gap.meat_element]})` : "—"}
            </div>
            {gap.evidence_source_url && (
              <a
                href={gap.evidence_source_url}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                  marginTop: 8,
                  fontSize: 12,
                  color: "#2563eb",
                  textDecoration: "none",
                }}
              >
                <ExternalLink size={12} /> Open chart source
              </a>
            )}
            <div
              style={{
                marginTop: 14,
                fontSize: 12,
                color: "#64748b",
                paddingTop: 10,
                borderTop: "1px solid #e2e8f0",
              }}
            >
              <div>
                <strong>Primary coder:</strong>{" "}
                {gap.primary_coder_name || (gap.primary_coder_id ? `Coder #${gap.primary_coder_id}` : "—")}
              </div>
              <div>
                <strong>Coded at:</strong> {gap.primary_coded_at || "—"}
              </div>
            </div>
          </div>

          {/* Right: reviewer notes / reject reason */}
          <div>
            <h3 style={{ margin: "0 0 8px", fontSize: 13, color: "#475569", textTransform: "uppercase", letterSpacing: "0.05em" }}>
              Reviewer Notes
            </h3>
            <textarea
              value={reviewerNotes}
              onChange={(e) => setReviewerNotes(e.target.value)}
              placeholder="Optional — add context for downstream auditors"
              rows={6}
              style={{
                width: "100%",
                padding: 10,
                borderRadius: 6,
                border: "1px solid #cbd5e1",
                fontFamily: "inherit",
                fontSize: 13,
                resize: "vertical",
              }}
              disabled={rejectMode}
            />

            {rejectMode && (
              <>
                <h3 style={{ margin: "16px 0 8px", fontSize: 13, color: "#b91c1c", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  Rejection Reason (required)
                </h3>
                <textarea
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  placeholder="Why is this evidence insufficient?"
                  rows={4}
                  style={{
                    width: "100%",
                    padding: 10,
                    borderRadius: 6,
                    border: "1px solid #fecaca",
                    background: "#fef2f2",
                    fontFamily: "inherit",
                    fontSize: 13,
                    resize: "vertical",
                  }}
                  autoFocus
                />
              </>
            )}
          </div>
        </div>

        {error && (
          <div
            style={{
              margin: "0 24px 12px",
              padding: 10,
              borderRadius: 6,
              background: "#fef2f2",
              border: "1px solid #fecaca",
              color: "#b91c1c",
              fontSize: 13,
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <AlertTriangle size={14} /> {error}
          </div>
        )}

        {/* Footer actions */}
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 10,
            padding: "12px 24px",
            borderTop: "1px solid #e2e8f0",
            background: "#f8fafc",
          }}
        >
          {!rejectMode ? (
            <>
              <button
                type="button"
                onClick={() => setRejectMode(true)}
                disabled={approveMut.isPending}
                style={{
                  padding: "8px 16px",
                  borderRadius: 6,
                  border: "1px solid #fecaca",
                  background: "#fff",
                  color: "#b91c1c",
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Reject
              </button>
              <button
                type="button"
                onClick={() => approveMut.mutate()}
                disabled={approveMut.isPending}
                style={{
                  padding: "8px 16px",
                  borderRadius: 6,
                  border: "none",
                  background: "#16a34a",
                  color: "#fff",
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: "pointer",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                <Check size={14} /> {approveMut.isPending ? "Approving…" : "Approve"}
              </button>
            </>
          ) : (
            <>
              <button
                type="button"
                onClick={() => { setRejectMode(false); setRejectReason(""); }}
                disabled={rejectMut.isPending}
                style={{
                  padding: "8px 16px",
                  borderRadius: 6,
                  border: "1px solid #cbd5e1",
                  background: "#fff",
                  color: "#475569",
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => rejectMut.mutate()}
                disabled={rejectMut.isPending || !rejectReason.trim()}
                style={{
                  padding: "8px 16px",
                  borderRadius: 6,
                  border: "none",
                  background: rejectReason.trim() ? "#dc2626" : "#cbd5e1",
                  color: "#fff",
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: rejectReason.trim() ? "pointer" : "not-allowed",
                }}
              >
                {rejectMut.isPending ? "Rejecting…" : "Confirm Reject"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default MeatReviewModal;
