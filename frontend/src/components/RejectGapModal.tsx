"use client";

/**
 * RejectGapModal — Compliance-critical two-way HCC review.
 *
 * Reveleer 2026: "add-only = DOJ red flag."
 * Allows coders to reject a prior-year HCC gap with a required reason code.
 * On submit: POST /api/v1/hcc-rejections → immutable audit chain entry.
 *
 * Usage:
 *   <RejectGapModal
 *     patientName="Jane Doe"
 *     patientId={42}
 *     hccCode="19"
 *     paymentYear={2026}
 *     open={showModal}
 *     onClose={() => setShowModal(false)}
 *     onRejected={() => refetch()}
 *   />
 */

import { useState, useCallback, useId } from "react";
import { X, AlertTriangle, ShieldAlert } from "lucide-react";
import { tokens } from "@/styles/tokens";
import api from "@/lib/api";

export interface RejectGapModalProps {
  patientName: string;
  patientId: number;
  hccCode: string;
  paymentYear: number;
  open: boolean;
  onClose: () => void;
  /** Called after a successful rejection so the parent can refresh. */
  onRejected: (rejectionId: number) => void;
}

const REASON_OPTIONS = [
  { value: "not_supported_in_chart",     label: "Not supported in chart" },
  { value: "incorrect_specificity",      label: "Incorrect specificity" },
  { value: "resolved_condition",         label: "Resolved / inactive condition" },
  { value: "documentation_insufficient", label: "Documentation insufficient" },
  { value: "coder_error",                label: "Coder error" },
  { value: "provider_dispute",           label: "Provider dispute" },
] as const;

type ReasonCode = typeof REASON_OPTIONS[number]["value"];

export function RejectGapModal({
  patientName,
  patientId,
  hccCode,
  paymentYear,
  open,
  onClose,
  onRejected,
}: RejectGapModalProps) {
  const formId = useId();
  const [reasonCode, setReasonCode] = useState<ReasonCode | "">("");
  const [reasonText, setReasonText] = useState("");
  const [priorYearDocumented, setPriorYearDocumented] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = useCallback(() => {
    setReasonCode("");
    setReasonText("");
    setPriorYearDocumented(false);
    setError(null);
    setSubmitting(false);
  }, []);

  const handleClose = useCallback(() => {
    reset();
    onClose();
  }, [reset, onClose]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      if (!reasonCode) {
        setError("Reason code is required.");
        return;
      }
      setSubmitting(true);
      setError(null);
      try {
        const { data } = await api.post<{ id: number }>("/api/v1/hcc-rejections", {
          patient_id: patientId,
          hcc_code: hccCode,
          payment_year: paymentYear,
          reason_code: reasonCode,
          reason_text: reasonText.trim() || null,
          prior_year_documented: priorYearDocumented,
        });
        onRejected(data.id);
        reset();
        onClose();
      } catch (err: unknown) {
        const msg =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
          "Rejection failed. Please try again.";
        setError(msg);
      } finally {
        setSubmitting(false);
      }
    },
    [reasonCode, reasonText, priorYearDocumented, patientId, hccCode, paymentYear, onRejected, reset, onClose],
  );

  if (!open) return null;

  return (
    /* Backdrop */
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={`${formId}-title`}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1200,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "16px",
        background: "rgba(15,23,42,0.55)",
        backdropFilter: "blur(2px)",
      }}
      onClick={(e) => { if (e.target === e.currentTarget) handleClose(); }}
    >
      {/* Panel */}
      <div
        style={{
          width: "100%",
          maxWidth: 480,
          borderRadius: 12,
          background: tokens.white,
          boxShadow: "0 20px 60px rgba(15,23,42,0.22)",
          overflow: "hidden",
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: "16px 20px",
            borderBottom: `1px solid ${tokens.dangerBorder}`,
            background: tokens.dangerSoft,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <ShieldAlert size={20} color={tokens.danger} aria-hidden />
            <div>
              <h2
                id={`${formId}-title`}
                style={{ margin: 0, fontSize: 15, fontWeight: 700, color: tokens.danger }}
              >
                Reject HCC {hccCode}
              </h2>
              <p style={{ margin: 0, fontSize: 12, color: tokens.slate600 }}>
                {patientName} &middot; Payment year {paymentYear}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleClose}
            aria-label="Close rejection dialog"
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 4,
              borderRadius: 6,
              color: tokens.slate500,
              display: "flex",
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Compliance notice */}
        <div
          style={{
            margin: "16px 20px 0",
            padding: "10px 12px",
            borderRadius: 8,
            background: "#FFFBEB",
            border: "1px solid #FDE68A",
            fontSize: 12,
            color: "#92400E",
            lineHeight: 1.5,
          }}
        >
          <strong>Compliance notice:</strong> This action is permanently recorded in the
          immutable audit chain (RADV-style SHA-256 linked). Rejected gaps are excluded from
          the recapture queue for {paymentYear}.
        </div>

        {/* Form */}
        <form id={formId} onSubmit={handleSubmit} noValidate>
          <div style={{ padding: "16px 20px", display: "flex", flexDirection: "column", gap: 14 }}>

            {/* Reason code — REQUIRED */}
            <div>
              <label
                htmlFor={`${formId}-reason`}
                style={{ display: "block", fontSize: 13, fontWeight: 600, color: tokens.slate700, marginBottom: 6 }}
              >
                Rejection reason <span aria-hidden style={{ color: tokens.danger }}>*</span>
              </label>
              <select
                id={`${formId}-reason`}
                required
                value={reasonCode}
                onChange={(e) => setReasonCode(e.target.value as ReasonCode)}
                aria-required="true"
                aria-describedby={`${formId}-reason-hint`}
                style={{
                  width: "100%",
                  padding: "9px 12px",
                  borderRadius: 8,
                  border: `1px solid ${reasonCode ? tokens.slate300 : tokens.dangerBorder}`,
                  fontSize: 14,
                  color: reasonCode ? tokens.slate900 : tokens.slate400,
                  background: tokens.white,
                  outline: "none",
                  cursor: "pointer",
                }}
              >
                <option value="" disabled>Select a reason code…</option>
                {REASON_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
              <span id={`${formId}-reason-hint`} style={{ fontSize: 11, color: tokens.slate500 }}>
                Required — documented in audit log
              </span>
            </div>

            {/* Reason text — optional */}
            <div>
              <label
                htmlFor={`${formId}-text`}
                style={{ display: "block", fontSize: 13, fontWeight: 600, color: tokens.slate700, marginBottom: 6 }}
              >
                Additional notes{" "}
                <span style={{ fontSize: 11, fontWeight: 400, color: tokens.slate400 }}>(optional, max 500 chars)</span>
              </label>
              <textarea
                id={`${formId}-text`}
                value={reasonText}
                onChange={(e) => setReasonText(e.target.value.slice(0, 500))}
                rows={3}
                placeholder="Free-form clinical rationale…"
                style={{
                  width: "100%",
                  padding: "9px 12px",
                  borderRadius: 8,
                  border: `1px solid ${tokens.slate300}`,
                  fontSize: 13,
                  color: tokens.slate900,
                  background: tokens.white,
                  resize: "vertical",
                  fontFamily: "inherit",
                  outline: "none",
                  boxSizing: "border-box",
                }}
              />
              <span style={{ fontSize: 11, color: tokens.slate400 }}>
                {reasonText.length}/500
              </span>
            </div>

            {/* Prior year documented toggle */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "10px 12px",
                borderRadius: 8,
                background: tokens.slate50,
                border: `1px solid ${tokens.slate200}`,
                cursor: "pointer",
              }}
              onClick={() => setPriorYearDocumented((v) => !v)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === " " || e.key === "Enter") setPriorYearDocumented((v) => !v); }}
            >
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: tokens.slate800 }}>
                  Documented in prior year
                </div>
                <div style={{ fontSize: 11, color: tokens.slate500 }}>
                  Was this condition documented in {paymentYear - 1}?
                </div>
              </div>
              {/* Toggle */}
              <div
                role="switch"
                aria-checked={priorYearDocumented}
                aria-label="Prior year documented"
                style={{
                  width: 40,
                  height: 22,
                  borderRadius: 999,
                  background: priorYearDocumented ? tokens.primary : tokens.slate300,
                  position: "relative",
                  transition: "background 150ms",
                  flexShrink: 0,
                }}
              >
                <span
                  style={{
                    position: "absolute",
                    top: 3,
                    left: priorYearDocumented ? 21 : 3,
                    width: 16,
                    height: 16,
                    borderRadius: "50%",
                    background: tokens.white,
                    transition: "left 150ms",
                    boxShadow: "0 1px 3px rgba(0,0,0,0.2)",
                  }}
                />
              </div>
            </div>

            {/* Error */}
            {error && (
              <div
                role="alert"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  padding: "10px 12px",
                  borderRadius: 8,
                  background: tokens.dangerSoft,
                  border: `1px solid ${tokens.dangerBorder}`,
                  color: tokens.danger,
                  fontSize: 13,
                }}
              >
                <AlertTriangle size={15} aria-hidden />
                {error}
              </div>
            )}
          </div>

          {/* Footer */}
          <div
            style={{
              padding: "14px 20px",
              borderTop: `1px solid ${tokens.slate200}`,
              display: "flex",
              gap: 10,
              justifyContent: "flex-end",
            }}
          >
            <button
              type="button"
              onClick={handleClose}
              disabled={submitting}
              style={{
                padding: "8px 16px",
                borderRadius: 8,
                border: `1px solid ${tokens.slate300}`,
                background: tokens.white,
                color: tokens.slate700,
                fontSize: 13,
                fontWeight: 600,
                cursor: submitting ? "not-allowed" : "pointer",
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting || !reasonCode}
              aria-busy={submitting}
              style={{
                padding: "8px 18px",
                borderRadius: 8,
                border: "none",
                background: submitting || !reasonCode ? tokens.slate300 : tokens.danger,
                color: tokens.white,
                fontSize: 13,
                fontWeight: 700,
                cursor: submitting || !reasonCode ? "not-allowed" : "pointer",
                transition: "background 120ms",
              }}
            >
              {submitting ? "Recording…" : "Confirm Rejection"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
