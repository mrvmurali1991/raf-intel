"use client";

/**
 * DocumentPdfPane
 * ===============
 * Isolated component that imports react-pdf (pdf.js ~300 kB).
 * Loaded lazily by DocumentExtractViewer via next/dynamic so the heavy
 * bundle is excluded from the initial JS payload.
 *
 * This module MUST remain the only file in the frontend that imports
 * "react-pdf" — all pdf.js cost is gated behind the dynamic() boundary.
 */

import React from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

// Wire up the pdfjs worker via CDN — version pinned to the bundled API
// version so worker/main always match.
if (typeof window !== "undefined" && !pdfjs.GlobalWorkerOptions.workerSrc) {
  pdfjs.GlobalWorkerOptions.workerSrc = `https://cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjs.version}/pdf.worker.min.mjs`;
}

export interface DocumentPdfPaneProps {
  fileUrl: string;
  pageNumber: number;
  scale: number;
  loadError: string | null;
  onDocLoad: (data: { numPages: number }) => void;
  onDocError: (err: Error) => void;
}

export default function DocumentPdfPane({
  fileUrl,
  pageNumber,
  scale,
  loadError,
  onDocLoad,
  onDocError,
}: DocumentPdfPaneProps) {
  if (loadError) {
    return (
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
    );
  }

  return (
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
            Rendering page {pageNumber}…
          </div>
        }
      />
    </Document>
  );
}
