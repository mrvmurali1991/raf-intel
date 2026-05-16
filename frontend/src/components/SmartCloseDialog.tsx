"use client";

/**
 * SmartCloseDialog
 * ----------------
 * Modal that captures the documentation evidence + MEAT element (M/E/A/T) and
 * the "also write HCC to current year" toggle before invoking the
 * ``/api/recapture/gaps/{id}/smart-close`` endpoint.
 *
 * Triggered from the recapture worklist row close button.
 *
 * Props:
 *   - open:        whether the dialog is visible
 *   - gap:         the gap being closed (used for the dialog header)
 *   - onClose:     close handler (cancels)
 *   - onClosed:    callback invoked with the API result on success — caller
 *                  should refetch the recapture worklist.
 */

import { useState } from "react";
import { X, CheckCircle2, AlertTriangle, Loader2 } from "lucide-react";
import {
  smartCloseGap,
  type RecaptureGapRow,
  type SmartCloseResult,
} from "@/lib/api";

const MEAT_OPTIONS: Array<{ key: "M" | "E" | "A" | "T"; label: string; hint: string }> = [
  { key: "M", label: "Monitor",  hint: "Signs, symptoms, disease progression / regression" },
  { key: "E", label: "Evaluate", hint: "Test results, response to treatment, exam findings" },
  { key: "A", label: "Assess",   hint: "Discussion, review, ordering tests / referrals" },
  { key: "T", label: "Treat",    hint: "Medications, therapies, plan changes" },
];

interface Props {
  open: boolean;
  gap: RecaptureGapRow | null;
  onClose: () => void;
  onClosed: (result: SmartCloseResult) => void;
}

export default function SmartCloseDialog({ open, gap, onClose, onClosed }: Props) {
  const [evidence, setEvidence] = useState("");
  const [meat, setMeat] = useState<"M" | "E" | "A" | "T">("M");
  const [writeHcc, setWriteHcc] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open || !gap) return null;

  async function handleSubmit() {
    if (!gap) return;
    if (!evidence.trim()) {
      setError("Evidence phrase is required.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await smartCloseGap(gap.id, {
        evidence_phrase: evidence.trim(),
        meat_element: meat,
        write_to_raf_hcc: writeHcc,
      });
      onClosed(result);
      // reset for next open
      setEvidence("");
      setMeat("M");
      setWriteHcc(true);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to close the gap.";
      setError(msg);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Close recapture gap with evidence"
      style={{
        position: "fixed", inset: 0, zIndex: 1000,
        background: "rgba(15,23,42,0.55)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 16,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: "100%", maxWidth: 560, background: "#fff",
          borderRadius: 14, boxShadow: "0 20px 60px rgba(15,23,42,0.25)",
          overflow: "hidden",
        }}
      >
        {/* Header */}
        <div style={{
          padding: "18px 22px", borderBottom: "1px solid #E2E8F0",
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "#0F172A" }}>
              Close gap with evidence
            </h2>
            <p style={{ margin: "4px 0 0", fontSize: 12, color: "#64748B" }}>
              HCC {gap.hcc_code}{gap.hcc_description ? ` · ${gap.hcc_description}` : ""}
              {" · "}Patient {gap.patient_name || gap.patient_id}
            </p>
          </div>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            style={{
              background: "transparent", border: "none", cursor: "pointer",
              padding: 4, color: "#64748B", display: "flex",
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: "20px 22px", display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Evidence */}
          <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: "#0F172A" }}>
              Evidence quote from chart <span style={{ color: "#DC2626" }}>*</span>
            </span>
            <textarea
              value={evidence}
              onChange={(e) => setEvidence(e.target.value)}
              placeholder="e.g. Patient with CHF NYHA II — currently on lisinopril and metoprolol; BNP 480 on 2026-04-12."
              rows={4}
              style={{
                resize: "vertical", padding: "10px 12px",
                borderRadius: 8, border: "1px solid #CBD5E1",
                fontSize: 13, fontFamily: "inherit", color: "#0F172A",
              }}
            />
          </label>

          {/* MEAT element */}
          <fieldset style={{ border: "none", padding: 0, margin: 0 }}>
            <legend style={{ fontSize: 12, fontWeight: 600, color: "#0F172A", marginBottom: 8 }}>
              MEAT element
            </legend>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 8 }}>
              {MEAT_OPTIONS.map((opt) => (
                <label
                  key={opt.key}
                  style={{
                    display: "flex", flexDirection: "column", gap: 2,
                    padding: "10px 12px", borderRadius: 8,
                    border: meat === opt.key ? "2px solid #2563EB" : "1px solid #E2E8F0",
                    background: meat === opt.key ? "#EFF6FF" : "#fff",
                    cursor: "pointer", transition: "all 0.15s",
                  }}
                >
                  <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 600, color: "#0F172A" }}>
                    <input
                      type="radio"
                      name="meat-element"
                      checked={meat === opt.key}
                      onChange={() => setMeat(opt.key)}
                      style={{ margin: 0 }}
                    />
                    {opt.key} — {opt.label}
                  </span>
                  <span style={{ fontSize: 11, color: "#64748B", paddingLeft: 22 }}>
                    {opt.hint}
                  </span>
                </label>
              ))}
            </div>
          </fieldset>

          {/* Write HCC toggle */}
          <label
            style={{
              display: "flex", alignItems: "flex-start", gap: 10,
              padding: "10px 12px", borderRadius: 8,
              background: "#F8FAFC", border: "1px solid #E2E8F0",
            }}
          >
            <input
              type="checkbox"
              checked={writeHcc}
              onChange={(e) => setWriteHcc(e.target.checked)}
              style={{ marginTop: 2 }}
            />
            <span style={{ fontSize: 13, color: "#0F172A" }}>
              <strong>Also write HCC to current-year RAF score.</strong>{" "}
              <span style={{ color: "#64748B" }}>
                Inserts a row into ``raf_patient_hcc`` (source=recapture) so the HCC
                counts toward this year's RAF. Skipped automatically if already present.
              </span>
            </span>
          </label>

          {error && (
            <div style={{
              display: "flex", alignItems: "center", gap: 8,
              padding: "10px 12px", borderRadius: 8,
              background: "#FEF2F2", border: "1px solid #FECACA",
              color: "#B91C1C", fontSize: 13,
            }}>
              <AlertTriangle size={16} /> {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{
          padding: "14px 22px", borderTop: "1px solid #E2E8F0",
          display: "flex", justifyContent: "flex-end", gap: 8,
          background: "#F8FAFC",
        }}>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            style={{
              padding: "8px 14px", borderRadius: 8,
              border: "1px solid #CBD5E1", background: "#fff",
              fontSize: 13, fontWeight: 600, color: "#0F172A",
              cursor: submitting ? "not-allowed" : "pointer",
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting || !evidence.trim()}
            style={{
              padding: "8px 16px", borderRadius: 8, border: "none",
              background: submitting || !evidence.trim() ? "#94A3B8" : "#2563EB",
              color: "#fff", fontSize: 13, fontWeight: 600,
              cursor: submitting || !evidence.trim() ? "not-allowed" : "pointer",
              display: "inline-flex", alignItems: "center", gap: 6,
            }}
          >
            {submitting ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
            {submitting ? "Closing…" : "Close gap"}
          </button>
        </div>
      </div>
    </div>
  );
}
