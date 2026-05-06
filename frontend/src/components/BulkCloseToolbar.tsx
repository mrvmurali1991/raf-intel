"use client";

/**
 * BulkCloseToolbar
 * ----------------
 * Sticky bar that appears when 2+ recapture-gap rows are checkbox-selected.
 * Click "Close N selected" → opens a shared evidence dialog → calls
 * ``/api/recapture/gaps/bulk-close`` and reports back.
 */

import { useState } from "react";
import { CheckSquare, X, Loader2, AlertTriangle, CheckCircle2 } from "lucide-react";
import { bulkCloseGaps, type BulkCloseResult } from "@/lib/api";

interface Props {
  selectedIds: number[];
  onCleared: () => void;
  onClosed: (result: BulkCloseResult) => void;
}

export default function BulkCloseToolbar({ selectedIds, onCleared, onClosed }: Props) {
  const [open, setOpen] = useState(false);
  const [evidence, setEvidence] = useState("");
  const [meat, setMeat] = useState<"M" | "E" | "A" | "T">("M");
  const [writeHcc, setWriteHcc] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (selectedIds.length < 2) return null;

  async function submit() {
    if (!evidence.trim()) {
      setError("Evidence phrase is required.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await bulkCloseGaps({
        gap_ids: selectedIds,
        evidence_phrase: evidence.trim(),
        meat_element: meat,
        write_to_raf_hcc: writeHcc,
      });
      onClosed(result);
      setOpen(false);
      setEvidence("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Bulk close failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <>
      {/* Sticky toolbar */}
      <div
        role="toolbar"
        aria-label="Bulk recapture-gap actions"
        style={{
          position: "sticky", top: 16, zIndex: 50,
          margin: "12px 0",
          padding: "12px 16px",
          borderRadius: 10,
          background: "linear-gradient(135deg, #1E40AF, #2563EB)",
          color: "#fff",
          display: "flex", alignItems: "center", justifyContent: "space-between",
          boxShadow: "0 8px 24px rgba(37,99,235,0.3)",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13, fontWeight: 600 }}>
          <CheckSquare size={16} />
          {selectedIds.length} gaps selected
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            onClick={() => setOpen(true)}
            style={{
              padding: "7px 14px", borderRadius: 8, border: "none",
              background: "#fff", color: "#1E40AF",
              fontSize: 13, fontWeight: 600, cursor: "pointer",
            }}
          >
            Close {selectedIds.length} with shared evidence
          </button>
          <button
            type="button"
            aria-label="Clear selection"
            onClick={onCleared}
            style={{
              padding: "7px 10px", borderRadius: 8,
              border: "1px solid rgba(255,255,255,0.4)", background: "transparent",
              color: "#fff", cursor: "pointer", display: "flex", alignItems: "center",
            }}
          >
            <X size={14} />
          </button>
        </div>
      </div>

      {/* Modal */}
      {open && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: "fixed", inset: 0, zIndex: 1000,
            background: "rgba(15,23,42,0.55)",
            display: "flex", alignItems: "center", justifyContent: "center",
            padding: 16,
          }}
          onClick={() => !submitting && setOpen(false)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: "100%", maxWidth: 560, background: "#fff",
              borderRadius: 14, boxShadow: "0 20px 60px rgba(15,23,42,0.25)",
              overflow: "hidden",
            }}
          >
            <div style={{
              padding: "18px 22px", borderBottom: "1px solid #E2E8F0",
              display: "flex", alignItems: "center", justifyContent: "space-between",
            }}>
              <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "#0F172A" }}>
                Close {selectedIds.length} gaps with shared evidence
              </h2>
              <button
                aria-label="Cancel"
                onClick={() => setOpen(false)}
                disabled={submitting}
                style={{ background: "transparent", border: "none", cursor: "pointer", color: "#64748B" }}
              >
                <X size={18} />
              </button>
            </div>

            <div style={{ padding: "20px 22px", display: "flex", flexDirection: "column", gap: 16 }}>
              <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: "#0F172A" }}>
                  Shared evidence phrase <span style={{ color: "#DC2626" }}>*</span>
                </span>
                <textarea
                  value={evidence}
                  onChange={(e) => setEvidence(e.target.value)}
                  rows={4}
                  placeholder="Applies to all selected gaps. e.g. 'Reviewed and re-documented during today's annual wellness visit.'"
                  style={{
                    resize: "vertical", padding: "10px 12px",
                    borderRadius: 8, border: "1px solid #CBD5E1",
                    fontSize: 13, fontFamily: "inherit", color: "#0F172A",
                  }}
                />
              </label>

              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <span style={{ fontSize: 12, fontWeight: 600, color: "#0F172A" }}>MEAT:</span>
                {(["M", "E", "A", "T"] as const).map((k) => (
                  <button
                    key={k}
                    type="button"
                    onClick={() => setMeat(k)}
                    style={{
                      padding: "5px 14px", borderRadius: 16,
                      border: meat === k ? "2px solid #2563EB" : "1px solid #E2E8F0",
                      background: meat === k ? "#EFF6FF" : "#fff",
                      color: "#0F172A", fontSize: 12, fontWeight: 600,
                      cursor: "pointer",
                    }}
                  >
                    {k}
                  </button>
                ))}
              </div>

              <label style={{
                display: "flex", alignItems: "center", gap: 8,
                fontSize: 13, color: "#0F172A",
              }}>
                <input
                  type="checkbox"
                  checked={writeHcc}
                  onChange={(e) => setWriteHcc(e.target.checked)}
                />
                Also write each HCC to the current-year RAF score
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

            <div style={{
              padding: "14px 22px", borderTop: "1px solid #E2E8F0",
              display: "flex", justifyContent: "flex-end", gap: 8,
              background: "#F8FAFC",
            }}>
              <button
                onClick={() => setOpen(false)}
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
                onClick={submit}
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
                {submitting ? "Closing…" : `Close ${selectedIds.length} gaps`}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
