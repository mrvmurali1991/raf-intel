"use client";

/**
 * DocumentExtractViewer
 * =====================
 * First-cut Apixio InstaVu / Cotiviti-style split viewer:
 *
 *   |  PDF (left)             |  Extracted HCC list (right)  |
 *   |  pages, zoom, prev/next |  clickable cards             |
 *
 * Clicking an extract on the right jumps the PDF on the left to its
 * `page_number`. The currently selected extract is reflected in the URL
 * (`?document_id=...&extract_id=...`) so the view is deep-linkable.
 *
 * NOTE: react-pdf's worker is configured at module load via a CDN URL that
 * matches the bundled pdfjs version. This avoids the bundler having to
 * resolve `pdfjs-dist/build/pdf.worker.min.mjs` (which fails under Next 16
 * webpack without extra config).
 */

import React, { useCallback, useMemo, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import {
  ChevronLeft,
  ChevronRight,
  ZoomIn,
  ZoomOut,
  FileText,
  Tag,
} from "lucide-react";

// Wire up the pdfjs worker via CDN — version pinned to the bundled API
// version so worker/main always match.
if (typeof window !== "undefined" && !pdfjs.GlobalWorkerOptions.workerSrc) {
  pdfjs.GlobalWorkerOptions.workerSrc = `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjs.version}/pdf.worker.min.mjs`;
}

export interface DocumentExtract {
  id: string;
  label: string;
  page_number: number;
  snippet: string;
  // Optional metadata for richer chips
  hcc_code?: string | null;
  icd10_code?: string | null;
  confidence?: number | null;
}

export interface DocumentExtractViewerProps {
  /** URL the PDF is fetched from (must support GET; can be presigned or
   *  a backend route serving the bytes). */
  fileUrl: string;
  /** Human-readable label shown in the header. */
  documentName?: string;
  /** Document identifier — written into the URL for deep-linking. */
  documentId: string;
  /** Extracts to render on the right pane. */
  extracts: DocumentExtract[];
  /** Initial extract id selected (overridden by the `extract_id` URL param). */
  initialExtractId?: string;
}

const C = {
  bg: "#f8fafc",
  panel: "#ffffff",
  border: "#e2e8f0",
  borderStrong: "#cbd5e1",
  text: "#0f172a",
  textMuted: "#64748b",
  primary: "#2563eb",
  primarySoft: "#dbeafe",
  amber: "#f59e0b",
  amberSoft: "#fef3c7",
  green: "#16a34a",
  greenSoft: "#dcfce7",
};

export default function DocumentExtractViewer({
  fileUrl,
  documentName,
  documentId,
  extracts,
  initialExtractId,
}: DocumentExtractViewerProps) {
  // Initial selection comes from the parent (which reads the URL); we keep
  // it in local state so subsequent clicks update without parent rerenders.
  const [numPages, setNumPages] = useState<number | null>(null);
  const [selectedExtractId, setSelectedExtractId] = useState<string | null>(
    initialExtractId ?? null,
  );
  // Derive initial page from the selected extract if we already have one.
  const [pageNumber, setPageNumber] = useState<number>(() => {
    if (!initialExtractId) return 1;
    const found = extracts.find((e) => e.id === initialExtractId);
    return found?.page_number || 1;
  });
  const [scale, setScale] = useState<number>(1.2);
  const [loadError, setLoadError] = useState<string | null>(null);

  // If extracts arrive after mount and we have a deep-linked selection that
  // wasn't resolvable on first render, align the page during render. Setting
  // state during render is allowed when the new value differs from the
  // current one — React converges immediately and warns only on infinite
  // loops, which can't happen here (the condition flips false after one set).
  const resolvedSelected =
    selectedExtractId && extracts.find((e) => e.id === selectedExtractId);
  if (
    resolvedSelected &&
    pageNumber === 1 &&
    resolvedSelected.page_number &&
    resolvedSelected.page_number !== 1
  ) {
    setPageNumber(resolvedSelected.page_number);
  }

  const updateUrl = useCallback(
    (extractId: string | null) => {
      if (typeof window === "undefined") return;
      const params = new URLSearchParams(window.location.search);
      params.set("document_id", documentId);
      if (extractId) {
        params.set("extract_id", extractId);
      } else {
        params.delete("extract_id");
      }
      const newUrl = `${window.location.pathname}?${params.toString()}`;
      window.history.replaceState({}, "", newUrl);
    },
    [documentId],
  );

  // ------------------------------------------------------------------
  // Handlers
  // ------------------------------------------------------------------
  const onDocLoad = useCallback(({ numPages: n }: { numPages: number }) => {
    setNumPages(n);
    setLoadError(null);
  }, []);

  const onDocError = useCallback((err: Error) => {
    setLoadError(err?.message || "Failed to load PDF");
  }, []);

  const handleSelectExtract = useCallback(
    (ex: DocumentExtract) => {
      setSelectedExtractId(ex.id);
      const page = Math.max(1, Math.min(ex.page_number || 1, numPages ?? 9999));
      setPageNumber(page);
      updateUrl(ex.id);
    },
    [numPages, updateUrl],
  );

  const totalPages = numPages ?? 0;

  const canPrev = pageNumber > 1;
  const canNext = totalPages > 0 && pageNumber < totalPages;

  const groupedExtracts = useMemo(() => {
    const byPage = new Map<number, DocumentExtract[]>();
    for (const e of extracts) {
      const p = e.page_number || 1;
      const arr = byPage.get(p) || [];
      arr.push(e);
      byPage.set(p, arr);
    }
    return Array.from(byPage.entries()).sort((a, b) => a[0] - b[0]);
  }, [extracts]);

  return (
    <div
      data-testid="document-extract-viewer"
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(0,1fr)",
        gap: 16,
        background: C.bg,
        minHeight: "calc(100vh - 120px)",
        padding: 16,
      }}
      className="dx-viewer-root"
    >
      <style>{`
        @media (min-width: 1024px) {
          .dx-viewer-root {
            grid-template-columns: minmax(0, 1fr) 400px !important;
          }
        }
        .dx-extract-card {
          cursor: pointer;
          transition: background 0.15s, border-color 0.15s, transform 0.05s;
        }
        .dx-extract-card:hover {
          background: ${C.primarySoft};
          border-color: ${C.primary};
        }
        .dx-extract-card[data-selected="true"] {
          background: ${C.primarySoft};
          border-color: ${C.primary};
          box-shadow: 0 0 0 2px ${C.primary}33;
        }
      `}</style>

      {/* ---------------- LEFT: PDF VIEWER ---------------- */}
      <div
        style={{
          background: C.panel,
          borderRadius: 12,
          border: `1px solid ${C.border}`,
          display: "flex",
          flexDirection: "column",
          minHeight: 600,
          overflow: "hidden",
        }}
      >
        {/* Toolbar */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "10px 14px",
            borderBottom: `1px solid ${C.border}`,
            gap: 12,
            flexWrap: "wrap",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
            <FileText size={16} color={C.primary} />
            <span
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: C.text,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
                maxWidth: 360,
              }}
              title={documentName || documentId}
            >
              {documentName || `Document ${documentId}`}
            </span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <button
              type="button"
              aria-label="Previous page"
              onClick={() => canPrev && setPageNumber((p) => p - 1)}
              disabled={!canPrev}
              style={iconBtn(!canPrev)}
            >
              <ChevronLeft size={14} />
            </button>
            <span
              className="tabular-nums"
              style={{ fontSize: 12, color: C.textMuted, minWidth: 80, textAlign: "center" }}
            >
              Page {pageNumber} / {totalPages || "?"}
            </span>
            <button
              type="button"
              aria-label="Next page"
              onClick={() => canNext && setPageNumber((p) => p + 1)}
              disabled={!canNext}
              style={iconBtn(!canNext)}
            >
              <ChevronRight size={14} />
            </button>

            <span style={{ width: 1, height: 18, background: C.border, margin: "0 4px" }} />

            <button
              type="button"
              aria-label="Zoom out"
              onClick={() => setScale((s) => Math.max(0.5, +(s - 0.2).toFixed(2)))}
              style={iconBtn(false)}
            >
              <ZoomOut size={14} />
            </button>
            <span
              className="tabular-nums"
              style={{ fontSize: 12, color: C.textMuted, minWidth: 44, textAlign: "center" }}
            >
              {Math.round(scale * 100)}%
            </span>
            <button
              type="button"
              aria-label="Zoom in"
              onClick={() => setScale((s) => Math.min(3, +(s + 0.2).toFixed(2)))}
              style={iconBtn(false)}
            >
              <ZoomIn size={14} />
            </button>
          </div>
        </div>

        {/* PDF body */}
        <div
          style={{
            flex: 1,
            overflow: "auto",
            background: "#1f2937",
            display: "flex",
            justifyContent: "center",
            alignItems: "flex-start",
            padding: 16,
          }}
        >
          {loadError ? (
            <div
              style={{
                color: "#fff",
                background: "#7f1d1d",
                padding: "16px 20px",
                borderRadius: 8,
                fontSize: 13,
                maxWidth: 480,
                textAlign: "center",
              }}
            >
              <strong>Could not load PDF</strong>
              <p style={{ margin: "6px 0 0", fontSize: 12, opacity: 0.85 }}>{loadError}</p>
            </div>
          ) : (
            <Document
              file={fileUrl}
              onLoadSuccess={onDocLoad}
              onLoadError={onDocError}
              loading={
                <div style={{ color: "#fff", padding: 40, fontSize: 13 }}>
                  Loading document...
                </div>
              }
              error={
                <div style={{ color: "#fff", padding: 40, fontSize: 13 }}>
                  Failed to load document.
                </div>
              }
            >
              <Page
                pageNumber={pageNumber}
                scale={scale}
                renderAnnotationLayer
                renderTextLayer
                loading={
                  <div style={{ color: "#fff", padding: 20, fontSize: 12 }}>
                    Rendering page {pageNumber}...
                  </div>
                }
              />
            </Document>
          )}
        </div>
      </div>

      {/* ---------------- RIGHT: EXTRACTS PANEL ---------------- */}
      <aside
        style={{
          background: C.panel,
          borderRadius: 12,
          border: `1px solid ${C.border}`,
          display: "flex",
          flexDirection: "column",
          minHeight: 600,
          overflow: "hidden",
        }}
        aria-label="Extracted findings"
      >
        <header
          style={{
            padding: "12px 14px",
            borderBottom: `1px solid ${C.border}`,
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          <Tag size={16} color={C.amber} />
          <h2 style={{ fontSize: 14, fontWeight: 700, color: C.text, margin: 0 }}>
            Extracted HCCs
          </h2>
          <span
            className="tabular-nums"
            style={{
              marginLeft: "auto",
              fontSize: 11,
              fontWeight: 700,
              background: C.primarySoft,
              color: C.primary,
              padding: "2px 8px",
              borderRadius: 10,
            }}
          >
            {extracts.length}
          </span>
        </header>

        <div style={{ flex: 1, overflow: "auto", padding: 12 }}>
          {extracts.length === 0 ? (
            <div
              style={{
                textAlign: "center",
                padding: "40px 12px",
                color: C.textMuted,
                fontSize: 13,
              }}
            >
              No extracts available for this document.
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {groupedExtracts.map(([page, items]) => (
                <section key={page} aria-label={`Page ${page} extracts`}>
                  <div
                    style={{
                      fontSize: 11,
                      fontWeight: 700,
                      color: C.textMuted,
                      textTransform: "uppercase",
                      letterSpacing: 0.5,
                      margin: "0 4px 6px",
                    }}
                  >
                    Page {page}
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {items.map((ex) => {
                      const selected = ex.id === selectedExtractId;
                      return (
                        <button
                          key={ex.id}
                          type="button"
                          onClick={() => handleSelectExtract(ex)}
                          className="dx-extract-card"
                          data-selected={selected}
                          data-testid={`extract-card-${ex.id}`}
                          style={{
                            textAlign: "left",
                            border: `1px solid ${C.border}`,
                            borderRadius: 10,
                            padding: "10px 12px",
                            background: C.panel,
                            display: "flex",
                            flexDirection: "column",
                            gap: 6,
                          }}
                        >
                          <div
                            style={{
                              display: "flex",
                              alignItems: "center",
                              gap: 6,
                              flexWrap: "wrap",
                            }}
                          >
                            <span
                              style={{
                                fontSize: 12,
                                fontWeight: 700,
                                color: C.text,
                              }}
                            >
                              {ex.label}
                            </span>
                            {ex.hcc_code && (
                              <span
                                style={{
                                  fontSize: 10,
                                  fontWeight: 700,
                                  background: C.amberSoft,
                                  color: C.amber,
                                  padding: "1px 6px",
                                  borderRadius: 6,
                                  fontFamily: "monospace",
                                }}
                              >
                                HCC {ex.hcc_code}
                              </span>
                            )}
                            {ex.icd10_code && (
                              <span
                                style={{
                                  fontSize: 10,
                                  fontWeight: 700,
                                  background: C.primarySoft,
                                  color: C.primary,
                                  padding: "1px 6px",
                                  borderRadius: 6,
                                  fontFamily: "monospace",
                                }}
                              >
                                {ex.icd10_code}
                              </span>
                            )}
                            {ex.confidence != null && (
                              <span
                                style={{
                                  fontSize: 10,
                                  fontWeight: 700,
                                  background: C.greenSoft,
                                  color: C.green,
                                  padding: "1px 6px",
                                  borderRadius: 6,
                                }}
                              >
                                {Math.round((ex.confidence ?? 0) * 100)}%
                              </span>
                            )}
                          </div>
                          {ex.snippet && (
                            <p
                              style={{
                                fontSize: 12,
                                color: C.textMuted,
                                margin: 0,
                                lineHeight: 1.45,
                                display: "-webkit-box",
                                WebkitLineClamp: 3,
                                WebkitBoxOrient: "vertical",
                                overflow: "hidden",
                              }}
                            >
                              &ldquo;{ex.snippet}&rdquo;
                            </p>
                          )}
                          <span
                            style={{
                              fontSize: 10,
                              color: C.primary,
                              fontWeight: 600,
                            }}
                          >
                            {selected ? "Selected" : "Jump to page →"}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </section>
              ))}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}

function iconBtn(disabled: boolean): React.CSSProperties {
  return {
    width: 28,
    height: 28,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    border: `1px solid ${C.border}`,
    background: disabled ? C.bg : C.panel,
    color: disabled ? C.borderStrong : C.text,
    borderRadius: 6,
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.5 : 1,
    padding: 0,
  };
}
