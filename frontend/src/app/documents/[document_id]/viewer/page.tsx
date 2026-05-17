"use client";

/**
 * /documents/[document_id]/viewer
 * ================================
 * Apixio InstaVu / Cotiviti-style split viewer page.
 *
 * Fetches:
 *   - GET /api/documents/{document_id}            → metadata (name, mime, etc.)
 *   - GET /api/documents/{document_id}/extracts   → extract list
 *
 * The PDF binary is loaded by the viewer itself via
 *   GET /api/documents/{document_id}/view
 * which streams the file (and forwards auth cookies, since the axios instance
 * already runs with withCredentials).
 *
 * Deep-linking: ?extract_id=<id> opens the viewer focused on that extract.
 */

import React, { use, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import api, { API_BASE } from "@/lib/api";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import type { DocumentExtract } from "@/components/DocumentExtractViewer";

// react-pdf bundles pdfjs which uses browser-only APIs; load client-only.
const DocumentExtractViewer = dynamic(
  () => import("@/components/DocumentExtractViewer"),
  { ssr: false },
);

interface DocumentMeta {
  id: string | number;
  document_name?: string;
  filename?: string;
  mime_type?: string;
  patient_id?: string | number | null;
}

interface ExtractsResponse {
  document_id: string;
  count: number;
  extracts: DocumentExtract[];
  source: "raf_suspect_conditions" | "mock";
}

interface ViewerPageProps {
  params: Promise<{ document_id: string }>;
}

export default function DocumentViewerPage({ params }: ViewerPageProps) {
  const { document_id: documentId } = use(params);
  const searchParams = useSearchParams();
  const initialExtractId = searchParams?.get("extract_id") || undefined;

  const [meta, setMeta] = useState<DocumentMeta | null>(null);
  const [extracts, setExtracts] = useState<DocumentExtract[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!documentId) return;
    let cancelled = false;

    (async () => {
      try {
        const [metaResp, extractsResp] = await Promise.all([
          api
            .get<DocumentMeta>(`/api/documents/${documentId}`)
            .then((r) => r.data)
            .catch(() => null),
          api
            .get<ExtractsResponse>(`/api/documents/${documentId}/extracts`)
            .then((r) => r.data)
            .catch(
              () =>
                ({
                  document_id: documentId,
                  count: 0,
                  extracts: [],
                  source: "mock",
                } as ExtractsResponse),
            ),
        ]);
        if (cancelled) return;
        if (!metaResp) {
          setError("Document not found.");
        } else {
          setMeta(metaResp);
          setError(null);
        }
        setExtracts(extractsResp?.extracts ?? []);
      } catch (e) {
        if (cancelled) return;
        setError((e as Error)?.message || "Failed to load document.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [documentId]);

  const fileUrl = useMemo(
    () => `${API_BASE}/api/documents/${documentId}/view`,
    [documentId],
  );

  const documentName = meta?.document_name || meta?.filename || `Document ${documentId}`;

  return (
    <div style={{ background: "#f1f5f9", minHeight: "100vh" }}>
      {/* Page header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "14px 20px",
          background: "#ffffff",
          borderBottom: "1px solid #e2e8f0",
        }}
      >
        <Link
          href="/documents"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            color: "#475569",
            fontSize: 13,
            fontWeight: 600,
            textDecoration: "none",
            padding: "6px 10px",
            borderRadius: 8,
            border: "1px solid #e2e8f0",
            background: "#f8fafc",
          }}
        >
          <ArrowLeft size={14} /> Documents
        </Link>
        <h1 style={{ fontSize: 16, fontWeight: 700, color: "#0f172a", margin: 0 }}>
          {documentName}
        </h1>
        <span
          style={{
            marginLeft: "auto",
            fontSize: 11,
            fontWeight: 700,
            color: "#64748b",
            padding: "3px 10px",
            background: "#f1f5f9",
            border: "1px solid #e2e8f0",
            borderRadius: 999,
          }}
        >
          Split View
        </span>
      </div>

      {loading ? (
        <div
          style={{
            padding: 60,
            textAlign: "center",
            color: "#64748b",
            fontSize: 14,
          }}
        >
          Loading viewer...
        </div>
      ) : error ? (
        <div
          style={{
            margin: 24,
            padding: 24,
            background: "#fef2f2",
            border: "1px solid #fecaca",
            borderRadius: 12,
            color: "#991b1b",
            fontSize: 14,
            fontWeight: 600,
          }}
        >
          {error}
        </div>
      ) : (
        <DocumentExtractViewer
          fileUrl={fileUrl}
          documentName={documentName}
          documentId={documentId}
          extracts={extracts}
          initialExtractId={initialExtractId}
        />
      )}
    </div>
  );
}
