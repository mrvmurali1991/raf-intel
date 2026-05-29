"use client";

/**
 * KgGapBadge — small inline pill on suspect rows summarising the evidence
 * that fired ("Comorbidity", "Drug-class", "Lab signal", ...). Click opens
 * the full EvidenceChainPanel modal.
 */

import { useState, type CSSProperties, type MouseEvent } from "react";
import { EvidenceChainPanel } from "@/components/kg/EvidenceChainPanel";
import { humanizeEvidence } from "@/lib/evidence-labels";

export type KgEvidenceTypeRaw =
  | "kg-rule"
  | "kg_rule"
  | "comorbidity"
  | "drug-class"
  | "drug_class"
  | "lab"
  | "lab-signal"
  | "lab_signal"
  | "llm"
  | "rule"
  | string;

interface KgGapBadgeProps {
  /** The raw `evidence_type` string from the backend suspect row. */
  evidenceType?: string | null;
  /** Suspect id, used to fetch the evidence chain on click. */
  suspectId?: number;
  /** HCC code (used as fallback if suspectId is missing). */
  hccCode?: string;
  /** Patient id — required for HCC-only lookup. */
  patientId?: number;
  /** Render only the pill — disables the modal-on-click behaviour. */
  readOnly?: boolean;
  style?: CSSProperties;
}

interface BadgeStyle {
  label: string;
  bg: string;
  fg: string;
  border: string;
}

function classify(raw: string | null | undefined): BadgeStyle {
  const t = (raw ?? "").toLowerCase();
  if (t.includes("comorbid")) {
    return { label: "Comorbidity", bg: "#EDE9FE", fg: "#6D28D9", border: "#DDD6FE" };
  }
  if (t.includes("drug")) {
    return { label: "Drug-class", bg: "#D1FAE5", fg: "#047857", border: "#A7F3D0" };
  }
  if (t.includes("lab")) {
    return { label: "Lab signal", bg: "#FFEDD5", fg: "#C2410C", border: "#FED7AA" };
  }
  if (t === "llm" || t.includes("llm")) {
    return { label: "LLM", bg: "#FEF3C7", fg: "#92400E", border: "#FDE68A" };
  }
  if (t.includes("kg") || t.includes("rule")) {
    return { label: "KG-rule", bg: "#DBEAFE", fg: "#1D4ED8", border: "#BFDBFE" };
  }
  return { label: humanizeEvidence(raw) || "Evidence", bg: "#F1F5F9", fg: "#475569", border: "#E2E8F0" };
}

export function KgGapBadge({
  evidenceType,
  suspectId,
  hccCode,
  patientId,
  readOnly = false,
  style,
}: KgGapBadgeProps) {
  const [open, setOpen] = useState(false);
  const palette = classify(evidenceType);

  const handleClick = (e: MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    if (readOnly) return;
    setOpen(true);
  };

  return (
    <>
      <button
        type="button"
        onClick={handleClick}
        title={`Evidence type: ${palette.label}`}
        aria-label={`Open ${palette.label} evidence chain`}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          padding: "2px 8px",
          borderRadius: 999,
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: 0.4,
          textTransform: "uppercase",
          background: palette.bg,
          color: palette.fg,
          border: `1px solid ${palette.border}`,
          cursor: readOnly ? "default" : "pointer",
          ...style,
        }}
      >
        <span
          aria-hidden
          style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: palette.fg,
          }}
        />
        {palette.label}
      </button>

      {open && !readOnly ? (
        <KgGapBadgeModal onClose={() => setOpen(false)}>
          <EvidenceChainPanel
            suspectId={suspectId}
            hccCode={hccCode ?? ""}
            patientId={patientId}
          />
        </KgGapBadgeModal>
      ) : null}
    </>
  );
}

function KgGapBadgeModal({
  children,
  onClose,
}: {
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Evidence chain"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15, 23, 42, 0.45)",
        zIndex: 200,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "#FFFFFF",
          borderRadius: 14,
          maxWidth: 760,
          width: "100%",
          maxHeight: "90vh",
          overflow: "auto",
          boxShadow: "0 30px 60px rgba(15, 23, 42, 0.25)",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            padding: "12px 16px 0",
          }}
        >
          <button
            onClick={onClose}
            aria-label="Close evidence chain"
            style={{
              border: "none",
              background: "transparent",
              cursor: "pointer",
              fontSize: 22,
              color: "#64748B",
              lineHeight: 1,
            }}
          >
            &times;
          </button>
        </div>
        <div style={{ padding: "0 24px 24px" }}>{children}</div>
      </div>
    </div>
  );
}

export default KgGapBadge;
