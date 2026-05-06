/**
 * ProviderReportButton.tsx
 *
 * "Download PDF Report" button for the provider detail drawer.
 *
 * Why this isn't a plain <a href>
 * --------------------------------
 * The backend endpoint requires a JWT Bearer token (see
 * `backend/app/routers/provider_pdf_report.py`). Our access token lives in
 * memory (not in a cookie), so a direct anchor link would 401.
 *
 * Instead we go through the shared authenticated axios instance, fetch the
 * PDF as a Blob, and trigger the download with an in-memory object URL.
 * This is the same pattern used by `downloadRadvPacket` and
 * `downloadAuditPackage` elsewhere in this codebase.
 */
"use client";

import React, { useState } from "react";
import { FileDown, Loader2 } from "lucide-react";
import api from "@/lib/api";

type Props = {
  providerId: number;
  year?: number;
  /** Last name used to suggest the saved filename. Falls back to id. */
  providerLastName?: string;
  /** Optional className/style passthrough so callers can match local styling. */
  className?: string;
  style?: React.CSSProperties;
};

export default function ProviderReportButton({
  providerId,
  year = new Date().getFullYear(),
  providerLastName,
  className,
  style,
}: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onClick() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.get(`/api/providers/${providerId}/report.pdf`, {
        params: { year },
        responseType: "blob",
      });

      const blob = res.data as Blob;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const safeName =
        (providerLastName || `${providerId}`)
          .toLowerCase()
          .replace(/[^a-z0-9_-]+/g, "-")
          .replace(/^-+|-+$/g, "") || `${providerId}`;
      a.download = `provider-${safeName}-${year}.pdf`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err: unknown) {
      // Axios error bodies arrive as Blobs when responseType is 'blob' —
      // extract the JSON `detail` so we can surface a useful message.
      const axiosErr = err as {
        response?: { data?: unknown };
        message?: string;
      };
      const responseData = axiosErr.response?.data;
      let msg = axiosErr.message || "Failed to download PDF.";
      if (responseData instanceof Blob) {
        try {
          const text = await responseData.text();
          try {
            const parsed = JSON.parse(text);
            if (parsed?.detail) msg = parsed.detail;
          } catch {
            if (text) msg = text;
          }
        } catch {
          /* ignore */
        }
      }
      setError(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={onClick}
        disabled={busy}
        aria-busy={busy}
        title="Download a single-page PDF scorecard for this provider"
        className={className}
        style={{
          padding: "7px 14px",
          border: "1px solid #1d4ed8",
          borderRadius: 8,
          background: busy ? "#dbeafe" : "#1d4ed8",
          color: busy ? "#1d4ed8" : "#ffffff",
          fontSize: 13,
          fontWeight: 600,
          cursor: busy ? "wait" : "pointer",
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          ...style,
        }}
      >
        {busy ? (
          <Loader2
            size={13}
            style={{ animation: "spin 0.8s linear infinite" }}
          />
        ) : (
          <FileDown size={13} />
        )}
        {busy ? "Generating…" : "Download PDF Report"}
      </button>
      {error ? (
        <span
          role="alert"
          style={{
            marginLeft: 8,
            fontSize: 12,
            color: "#b91c1c",
          }}
        >
          {error}
        </span>
      ) : null}
    </>
  );
}
