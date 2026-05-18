"use client";

/**
 * ProblemListWriteBackModal
 *
 * Shown after a suspect is accepted. Prompts the provider to send the
 * attested HCC condition to the patient EHR Problem List via the
 * SMART-on-FHIR write-back queue.
 *
 * Usage:
 *   <ProblemListWriteBackModal
 *     open={showWriteBack}
 *     patientId={suspect.patient_id}
 *     patientName={suspect.patient_name}
 *     icd10={suspect.suspect_icd10}
 *     hccCode={String(suspect.suspect_hcc)}
 *     evidenceText={suspect.evidence_detail?.rationale}
 *     onClose={() => setShowWriteBack(false)}
 *   />
 */

import React, { useCallback, useState } from "react";
import { Activity, X } from "lucide-react";
import { enqueueEhrWriteBack } from "@/lib/api";
import { useToast } from "@/components/Toast";

interface Props {
  open: boolean;
  patientId: number;
  patientName?: string;
  icd10: string;
  hccCode?: string | null;
  evidenceText?: string | null;
  onClose: () => void;
}

export default function ProblemListWriteBackModal({
  open,
  patientId,
  patientName,
  icd10,
  hccCode,
  evidenceText,
  onClose,
}: Props) {
  const toast = useToast();
  const [sending, setSending] = useState(false);

  const handleSend = useCallback(async () => {
    setSending(true);
    try {
      await enqueueEhrWriteBack(patientId, {
        icd10,
        hcc_code: hccCode,
        evidence_text: evidenceText,
        attested_at: new Date().toISOString(),
      });
      toast.success("Queued for EHR write-back", `${icd10} queued for Problem List.`);
    } catch {
      toast.error("Queue Failed", "Could not queue EHR write-back. Try again.");
    } finally {
      setSending(false);
      onClose();
    }
  }, [patientId, icd10, hccCode, evidenceText, toast, onClose]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="wb-modal-title"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1200,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(15,23,42,0.55)",
        backdropFilter: "blur(2px)",
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          background: "#fff",
          borderRadius: 14,
          boxShadow: "0 20px 60px rgba(0,0,0,0.18)",
          width: "min(480px, 94vw)",
          padding: "28px 28px 24px",
          position: "relative",
        }}
      >
        {/* Close */}
        <button
          onClick={onClose}
          aria-label="Close"
          style={{
            position: "absolute",
            top: 14,
            right: 14,
            background: "none",
            border: "none",
            cursor: "pointer",
            color: "#64748b",
            lineHeight: 0,
            padding: 4,
            borderRadius: 6,
          }}
        >
          <X size={18} />
        </button>

        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
          <span
            style={{
              background: "#eff6ff",
              borderRadius: 8,
              padding: 8,
              lineHeight: 0,
              color: "#2563eb",
            }}
          >
            <Activity size={20} />
          </span>
          <h2
            id="wb-modal-title"
            style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "#0f172a" }}
          >
            Suggest adding to Problem List?
          </h2>
        </div>

        {/* Body */}
        <p style={{ margin: "0 0 18px", fontSize: 13.5, color: "#475569", lineHeight: 1.6 }}>
          This condition was just accepted. Would you like to queue it for write-back to the
          patient's EHR Problem List?
        </p>

        <div
          style={{
            background: "#f8fafc",
            border: "1px solid #e2e8f0",
            borderRadius: 10,
            padding: "14px 16px",
            marginBottom: 22,
            display: "grid",
            gap: 6,
          }}
        >
          <Row label="Patient" value={patientName ?? `#${patientId}`} />
          <Row label="ICD-10" value={icd10} mono />
          {hccCode && <Row label="HCC" value={`HCC ${hccCode}`} />}
          {evidenceText && (
            <Row
              label="Context"
              value={
                evidenceText.length > 120
                  ? evidenceText.slice(0, 117) + "..."
                  : evidenceText
              }
            />
          )}
        </div>

        {/* Actions */}
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button
            onClick={onClose}
            disabled={sending}
            style={{
              padding: "9px 18px",
              borderRadius: 8,
              border: "1.5px solid #e2e8f0",
              background: "#fff",
              color: "#475569",
              fontSize: 13.5,
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            Skip
          </button>
          <button
            onClick={handleSend}
            disabled={sending}
            aria-busy={sending}
            style={{
              padding: "9px 20px",
              borderRadius: 8,
              border: "none",
              background: sending ? "#93c5fd" : "#2563eb",
              color: "#fff",
              fontSize: 13.5,
              fontWeight: 600,
              cursor: sending ? "not-allowed" : "pointer",
              transition: "background 0.15s",
            }}
          >
            {sending ? "Sending..." : "Send to EHR"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
      <span
        style={{
          fontSize: 11.5,
          fontWeight: 600,
          color: "#94a3b8",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          minWidth: 60,
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontSize: 13,
          color: "#1e293b",
          fontFamily: mono ? "var(--font-mono, monospace)" : undefined,
          fontWeight: mono ? 600 : 400,
        }}
      >
        {value}
      </span>
    </div>
  );
}
