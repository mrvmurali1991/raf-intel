"use client";

/**
 * <RecaptureAuditExportButton /> — Download the RADV audit defense PDF.
 *
 * Hits GET /api/recapture/audit-report.pdf (optionally with ?year=YYYY)
 * via authenticated axios + responseType:"blob", then triggers a browser
 * download.
 */

import { useState } from "react";
import { Download, AlertTriangle } from "lucide-react";

import { downloadRecaptureAuditPdf } from "@/lib/api";

interface Props {
  year?: number;
  label?: string;
}

export function RecaptureAuditExportButton({ year, label = "Download RADV PDF" }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleClick() {
    setBusy(true);
    setError(null);
    try {
      await downloadRecaptureAuditPdf(year);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Download failed";
      setError(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ display: "inline-flex", flexDirection: "column", alignItems: "stretch", gap: 4 }}>
      <button
        type="button"
        onClick={handleClick}
        disabled={busy}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          padding: "10px 18px",
          borderRadius: 8,
          border: "none",
          background: busy
            ? "#94a3b8"
            : "linear-gradient(135deg, #1e3a8a, #1e40af)",
          color: "#fff",
          fontSize: 13,
          fontWeight: 600,
          cursor: busy ? "not-allowed" : "pointer",
          boxShadow: "0 2px 8px rgba(30,58,138,0.3)",
        }}
      >
        <Download size={14} />
        {busy ? "Generating PDF…" : label}
      </button>
      {error && (
        <div
          role="alert"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            color: "#b91c1c",
            fontSize: 12,
            marginTop: 4,
          }}
        >
          <AlertTriangle size={12} /> {error}
        </div>
      )}
    </div>
  );
}

export default RecaptureAuditExportButton;
