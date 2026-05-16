"use client";

/**
 * ClaimsUploadDialog — lazy-loaded file upload modal for claims.
 * Extracted from claims/page.tsx to defer upload dialog code from initial paint.
 */

import React, { useState, useRef } from "react";
import api from "@/lib/api";
import { tokens } from "@/styles/tokens";
import { Upload, X, FileText, AlertTriangle, Loader2, Database } from "lucide-react";

const ACCEPTED_EXT = [".csv", ".txt", ".837", ".edi", ".x12"];

const C = {
  white:      tokens.white,
  slate50:    tokens.slate50,
  slate100:   tokens.slate100,
  slate200:   tokens.slate200,
  slate300:   tokens.slate300,
  slate400:   tokens.slate400,
  slate500:   tokens.slate500,
  slate600:   tokens.slate600,
  teal:       "#0F766E",
  tealSoft:   "rgba(15,118,110,0.08)",
  tealBorder: "rgba(15,118,110,0.22)",
  emerald:    tokens.riskLow,
  emeraldSoft: tokens.successSoft,
  red:        tokens.danger,
  redSoft:    tokens.dangerSoft,
};

const errMsg = (e: unknown, fallback = "Something went wrong."): string => {
  const ex = e as { response?: { data?: { detail?: string; message?: string } }; message?: string };
  return ex?.response?.data?.detail ?? ex?.response?.data?.message ?? ex?.message ?? fallback;
};

interface ClaimsUploadDialogProps {
  onClose: () => void;
  onUploaded: (batchId: number, filename: string) => void;
}

export default function ClaimsUploadDialog({ onClose, onUploaded }: ClaimsUploadDialogProps) {
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const pick = (f: File | undefined) => {
    if (!f) return;
    const ext = "." + (f.name.split(".").pop() ?? "").toLowerCase();
    if (!ACCEPTED_EXT.includes(ext)) { setError(`Unsupported file type "${ext}". Accepted: ${ACCEPTED_EXT.join(", ")}`); return; }
    setError(null); setFile(f);
  };

  const submit = async () => {
    if (!file) return;
    setUploading(true); setProgress(0); setError(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const { data } = await api.post("/api/claims/upload", form, {
        headers: { "Content-Type": "multipart/form-data" },
        onUploadProgress: (e) => { if (e.total) setProgress(Math.round((e.loaded / e.total) * 100)); },
      });
      onUploaded(data?.batch_id, data?.filename ?? file.name);
      onClose();
    } catch (e) {
      setError(errMsg(e, "Upload failed. Please try again."));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div
      role="dialog" aria-modal="true" aria-label="Upload Claims File"
      onClick={(e) => { if (e.target === e.currentTarget && !uploading) onClose(); }}
      style={{ position: "fixed", inset: 0, zIndex: 100, padding: 16, background: "rgba(15,23,42,0.55)", backdropFilter: "blur(4px)", display: "flex", alignItems: "center", justifyContent: "center" }}
    >
      <div className="animate-scale-in" style={{ width: "100%", maxWidth: 540, background: C.white, borderRadius: 16, boxShadow: "0 25px 60px rgba(0,0,0,0.22)", overflow: "hidden" }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "18px 22px", borderBottom: `1px solid ${C.slate200}` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ width: 40, height: 40, borderRadius: 10, background: C.tealSoft, color: C.teal, display: "flex", alignItems: "center", justifyContent: "center" }}><Upload size={18} /></div>
            <div>
              <h2 className="text-foreground" style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Upload Claims File</h2>
              <p className="text-muted-foreground" style={{ margin: 0, fontSize: 12 }}>CSV, X12 837P / 837I, or EDI — up to 100 MB</p>
            </div>
          </div>
          <button onClick={onClose} disabled={uploading} aria-label="Close dialog" style={{ width: 32, height: 32, borderRadius: 8, border: `1px solid ${C.slate200}`, background: C.white, color: C.slate500, cursor: uploading ? "not-allowed" : "pointer", display: "inline-flex", alignItems: "center", justifyContent: "center" }}><X size={16} /></button>
        </div>

        {/* Body */}
        <div style={{ padding: 22, display: "flex", flexDirection: "column", gap: 18 }}>
          {/* Drop zone */}
          <div
            role="button" tabIndex={0}
            aria-label="Claims file drop zone"
            onClick={() => !uploading && inputRef.current?.click()}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") inputRef.current?.click(); }}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); pick(e.dataTransfer.files[0]); }}
            style={{ position: "relative", borderRadius: 14, padding: "36px 22px", textAlign: "center", cursor: uploading ? "default" : "pointer", background: dragOver ? C.tealSoft : file ? C.emeraldSoft : C.slate50, border: `2px dashed ${dragOver ? C.teal : file ? C.emerald : C.slate300}`, transition: "all 0.18s ease" }}
          >
            <input ref={inputRef} type="file" accept={ACCEPTED_EXT.join(",")} onChange={(e) => pick(e.target.files?.[0])} style={{ display: "none" }} />
            {file ? (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
                <div style={{ width: 48, height: 48, borderRadius: 12, background: `${C.emerald}1A`, color: C.emerald, display: "flex", alignItems: "center", justifyContent: "center" }}><FileText size={22} /></div>
                <div className="text-foreground" style={{ fontSize: 14, fontWeight: 600 }}>{file.name}</div>
                <div className="text-muted-foreground" style={{ fontSize: 12 }}>{(file.size / 1024).toFixed(1)} KB</div>
                {!uploading && <button onClick={(e) => { e.stopPropagation(); setFile(null); }} style={{ marginTop: 4, background: "none", border: "none", fontSize: 12, color: C.slate500, cursor: "pointer", textDecoration: "underline" }}>Replace file</button>}
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
                <div style={{ width: 48, height: 48, borderRadius: 12, background: C.slate100, color: C.slate400, display: "flex", alignItems: "center", justifyContent: "center" }}><Upload size={22} /></div>
                <div>
                  <p className="text-foreground" style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>Drop a claims file here</p>
                  <p className="text-muted-foreground" style={{ margin: "4px 0 0", fontSize: 12 }}>or click to browse — {ACCEPTED_EXT.join(", ")}</p>
                </div>
              </div>
            )}
          </div>

          {uploading && (
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: C.slate500, marginBottom: 6 }}>
                <span>Uploading…</span>
                <span style={{ fontWeight: 700, color: C.teal }}>{progress}%</span>
              </div>
              <div style={{ height: 6, borderRadius: 3, background: C.slate200, overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${progress}%`, background: C.teal, transition: "width 0.2s ease" }} />
              </div>
            </div>
          )}

          {error && (
            <div role="alert" style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "10px 12px", borderRadius: 8, background: C.redSoft, border: `1px solid ${C.red}30` }}>
              <AlertTriangle size={15} className="text-destructive" style={{ flexShrink: 0, marginTop: 1 }} />
              <span className="text-destructive" style={{ fontSize: 13 }}>{error}</span>
            </div>
          )}

          <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 12px", borderRadius: 8, background: C.slate50, border: `1px solid ${C.slate200}` }}>
            <Database size={14} className="text-muted-foreground" />
            <span className="text-muted-foreground" style={{ fontSize: 12, lineHeight: 1.5 }}>
              After upload, the batch is <strong>parsed</strong>. Run <em>Process</em> to match patients to OpenEMR records and map ICD-10 codes to HCC categories.
            </span>
          </div>
        </div>

        {/* Footer */}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, padding: "14px 22px", borderTop: `1px solid ${C.slate200}`, background: C.slate50 }}>
          <button onClick={onClose} disabled={uploading} style={{ height: 38, padding: "0 18px", borderRadius: 8, border: `1px solid ${C.slate200}`, background: C.white, color: C.slate600, fontSize: 13, fontWeight: 500, cursor: uploading ? "not-allowed" : "pointer", opacity: uploading ? 0.5 : 1 }}>Cancel</button>
          <button onClick={submit} disabled={!file || uploading} style={{ height: 38, padding: "0 20px", borderRadius: 8, border: "none", background: !file || uploading ? C.slate300 : `linear-gradient(135deg, ${C.teal} 0%, ${tokens.successDark} 100%)`, color: C.white, fontSize: 13, fontWeight: 600, cursor: !file || uploading ? "not-allowed" : "pointer", display: "inline-flex", alignItems: "center", gap: 6, boxShadow: !file || uploading ? "none" : "0 2px 10px rgba(15,118,110,0.35)" }}>
            {uploading ? <><Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> Uploading…</> : <><Upload size={14} /> Upload Claims</>}
          </button>
        </div>
      </div>
    </div>
  );
}
