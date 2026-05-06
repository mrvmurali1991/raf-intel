"use client";

/**
 * AWVSuggestionDialog
 *
 * Opens when the user clicks "Suggest AWV" on a recurring recapture gap.
 * Loads the read-only AWV recommendation for the patient and displays
 * eligibility, last AWV date, suggested provider, and suggested visit date.
 *
 * Two CTAs:
 *   - "Schedule on EHR" — calls /mark-awv-scheduled (metadata only).
 *   - "Dismiss"          — closes the dialog with no side effects.
 *
 * NEVER calls any AWV scheduling endpoint directly.
 */

import { useEffect, useState } from "react";
import { CalendarPlus, X, AlertTriangle, CheckCircle2 } from "lucide-react";
import {
  suggestAwvForGap,
  markGapAwvScheduled,
  type AWVSuggestion,
} from "@/lib/api";

interface AWVSuggestionDialogProps {
  gapId: number | null;
  open: boolean;
  onClose: () => void;
  /** Called after the user clicks "Schedule on EHR" so the parent can refresh. */
  onScheduled?: (gapId: number, visitDate: string) => void;
}

export function AWVSuggestionDialog({
  gapId,
  open,
  onClose,
  onScheduled,
}: AWVSuggestionDialogProps) {
  const [suggestion, setSuggestion] = useState<AWVSuggestion | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [encounterId, setEncounterId] = useState("");
  const [visitDate, setVisitDate] = useState("");

  useEffect(() => {
    if (!open || gapId == null) {
      setSuggestion(null);
      setError(null);
      setEncounterId("");
      setVisitDate("");
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    suggestAwvForGap(gapId)
      .then((s) => {
        if (cancelled) return;
        setSuggestion(s);
        setVisitDate(s.suggested_visit_date);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load suggestion");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, gapId]);

  if (!open) return null;

  async function handleSchedule() {
    if (gapId == null || !visitDate) return;
    setSubmitting(true);
    setError(null);
    try {
      await markGapAwvScheduled(gapId, { visit_date: visitDate, encounter_id: encounterId || undefined });
      onScheduled?.(gapId, visitDate);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to record schedule");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="awv-suggestion-title"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15,23,42,0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
        padding: 16,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: "#FFFFFF",
          borderRadius: 14,
          padding: 24,
          maxWidth: 540,
          width: "100%",
          boxShadow: "0 24px 48px rgba(15,23,42,0.25)",
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
          <h2
            id="awv-suggestion-title"
            style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "#0F172A", display: "flex", alignItems: "center", gap: 8 }}
          >
            <CalendarPlus size={20} color="#2563EB" />
            Suggest AWV for Recurring Gap
          </h2>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            style={{
              border: "none",
              background: "transparent",
              cursor: "pointer",
              padding: 4,
              borderRadius: 6,
              color: "#475569",
            }}
          >
            <X size={18} />
          </button>
        </div>

        {loading && (
          <div style={{ padding: 32, textAlign: "center", color: "#64748B", fontSize: 14 }}>
            Loading recommendation…
          </div>
        )}

        {error && !loading && (
          <div
            role="alert"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "10px 14px",
              borderRadius: 8,
              background: "#FEF2F2",
              border: "1px solid #FECACA",
              color: "#B91C1C",
              fontSize: 13,
              marginBottom: 12,
            }}
          >
            <AlertTriangle size={16} />
            {error}
          </div>
        )}

        {suggestion && !loading && (
          <>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
              <SummaryRow label="Patient ID" value={String(suggestion.patient_id)} />
              <SummaryRow
                label="AWV Eligible"
                value={
                  suggestion.eligible ? (
                    <span style={{ color: "#10B981", fontWeight: 600, display: "inline-flex", alignItems: "center", gap: 4 }}>
                      <CheckCircle2 size={14} /> Yes
                    </span>
                  ) : (
                    <span style={{ color: "#F59E0B", fontWeight: 600 }}>Not currently</span>
                  )
                }
              />
              <SummaryRow
                label="Last AWV / Encounter"
                value={suggestion.last_awv_date ?? "Unknown"}
              />
              <SummaryRow
                label="Days Since"
                value={suggestion.days_since != null ? String(suggestion.days_since) : "—"}
              />
              <SummaryRow
                label="Recommended Provider"
                value={
                  suggestion.recommended_provider_id != null
                    ? `Provider #${suggestion.recommended_provider_id}`
                    : "Unassigned"
                }
              />
              <SummaryRow
                label="HCC Code"
                value={suggestion.hcc_code ?? "—"}
              />
            </div>

            {suggestion.reason && (
              <p style={{ fontSize: 13, color: "#475569", margin: "0 0 16px", lineHeight: 1.5 }}>
                {suggestion.reason}
              </p>
            )}

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 18 }}>
              <label style={{ fontSize: 12, fontWeight: 600, color: "#475569" }}>
                Suggested Visit Date
                <input
                  type="date"
                  value={visitDate}
                  onChange={(e) => setVisitDate(e.target.value)}
                  style={{
                    marginTop: 4,
                    width: "100%",
                    padding: "8px 10px",
                    borderRadius: 8,
                    border: "1px solid #E2E8F0",
                    fontSize: 13,
                    color: "#0F172A",
                  }}
                />
              </label>
              <label style={{ fontSize: 12, fontWeight: 600, color: "#475569" }}>
                EHR Encounter ID (optional)
                <input
                  type="text"
                  value={encounterId}
                  onChange={(e) => setEncounterId(e.target.value)}
                  placeholder="e.g. ENC-12345"
                  style={{
                    marginTop: 4,
                    width: "100%",
                    padding: "8px 10px",
                    borderRadius: 8,
                    border: "1px solid #E2E8F0",
                    fontSize: 13,
                    color: "#0F172A",
                  }}
                />
              </label>
            </div>

            <p style={{ fontSize: 11, color: "#94A3B8", margin: "0 0 16px", lineHeight: 1.5 }}>
              "Schedule on EHR" only logs metadata in the RAF system — no AWV record
              is created automatically.  Please book the actual appointment in your EHR.
            </p>

            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button
                type="button"
                onClick={onClose}
                disabled={submitting}
                style={{
                  padding: "8px 16px",
                  borderRadius: 8,
                  border: "1px solid #E2E8F0",
                  background: "#FFFFFF",
                  color: "#475569",
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: submitting ? "not-allowed" : "pointer",
                }}
              >
                Dismiss
              </button>
              <button
                type="button"
                onClick={handleSchedule}
                disabled={submitting || !visitDate}
                style={{
                  padding: "8px 16px",
                  borderRadius: 8,
                  border: "none",
                  background: submitting ? "#94A3B8" : "linear-gradient(135deg,#2563EB,#1D4ED8)",
                  color: "#FFFFFF",
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: submitting || !visitDate ? "not-allowed" : "pointer",
                }}
              >
                {submitting ? "Saving…" : "Schedule on EHR"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 11, fontWeight: 600, color: "#94A3B8", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 2 }}>
        {label}
      </div>
      <div style={{ fontSize: 13, color: "#0F172A", fontWeight: 500 }}>{value}</div>
    </div>
  );
}

export default AWVSuggestionDialog;
