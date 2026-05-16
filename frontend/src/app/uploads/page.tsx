"use client";

import { useCallback, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Upload,
  FileText,
  FileSpreadsheet,
  Trash2,
  CheckCircle,
  AlertTriangle,
  Download,
  Eye,
  EyeOff,
  RefreshCw,
} from "lucide-react";
import {
  uploadPatientFile,
  listUploads,
  deleteUpload,
  downloadUploadTemplate,
  type UploadResult,
  type UploadRecord,
} from "@/lib/api";
import { tokens } from "@/styles/tokens";
import { FONT_SYS } from "@/lib/ui-utils";
import { ConfirmDialog } from "@/components/ConfirmDialog";

// Match the patients page palette so the upload page blends with the rest of
// the product without introducing a new design system.
const C = {
  text:       tokens.slate900,
  textMuted:  tokens.slate600,
  textSubtle: tokens.slate500,
  label:      tokens.slate400,
  border:     tokens.slate200,
  borderSoft: tokens.slate100,
  rowDivider: tokens.slate100,
  bgPage:     tokens.slate50,
  bgCard:     tokens.white,
  bgSubtle:   tokens.slate50,
  brand:      tokens.riskLow,            // #059669 emerald
  brandSoft:  tokens.riskLowSoft,
  brandRing:  `${tokens.riskLow}2E`,
  danger:     tokens.riskHigh,
  warning:    tokens.riskMedium,
  success:    tokens.successDark,
};

function formatBytes(n: number | null | undefined): string {
  if (!n || n <= 0) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) +
      ", " + d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
  } catch {
    return iso;
  }
}

function statusPillStyle(status: string): React.CSSProperties {
  const base: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "3px 10px",
    borderRadius: 999,
    fontSize: 12,
    fontWeight: 600,
    border: "1px solid",
  };
  if (status === "completed")
    return { ...base, background: tokens.riskLowSoft, color: C.success, borderColor: tokens.emerald100 };
  if (status === "partial")
    return { ...base, background: tokens.riskMediumSoft, color: C.warning, borderColor: tokens.warningBorder };
  if (status === "failed")
    return { ...base, background: tokens.riskHighSoft, color: C.danger, borderColor: tokens.dangerBorder };
  return { ...base, background: tokens.slate100, color: C.textMuted, borderColor: C.border };
}

export default function UploadsPage() {
  const qc = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [lastResult, setLastResult] = useState<UploadResult | null>(null);
  const [showErrors, setShowErrors] = useState(false);
  // Track which upload the user is about to delete. Set by the Delete button,
  // cleared on confirm / cancel. Drives the ConfirmDialog below.
  const [deleteTarget, setDeleteTarget] = useState<UploadRecord | null>(null);

  const { data: history, isLoading: histLoading, refetch } = useQuery({
    queryKey: ["uploads-list"],
    queryFn: listUploads,
    refetchInterval: 30000,
  });

  const uploadMut = useMutation({
    mutationFn: (file: File) => uploadPatientFile(file),
    onSuccess: (data) => {
      setLastResult(data);
      setShowErrors(false);
      qc.invalidateQueries({ queryKey: ["uploads-list"] });
      qc.invalidateQueries({ queryKey: ["patients"] });
      qc.invalidateQueries({ queryKey: ["emr-status"] });
    },
    onError: (err: any) => {
      const detail =
        err?.response?.data?.detail ||
        err?.response?.data?.message ||
        err?.message ||
        "Upload failed";
      setLastResult({
        upload_id: 0,
        filename: "",
        file_type: "csv",
        row_count_total: 0,
        row_count_imported: 0,
        row_count_failed: 0,
        status: "failed",
        errors: [typeof detail === "string" ? detail : JSON.stringify(detail)],
      });
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => deleteUpload(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["uploads-list"] });
      qc.invalidateQueries({ queryKey: ["patients"] });
    },
  });

  const handleFiles = useCallback(
    (files: FileList | null) => {
      if (!files || files.length === 0) return;
      const f = files[0];
      const name = f.name.toLowerCase();
      if (!name.endsWith(".csv") && !name.endsWith(".xlsx")) {
        setLastResult({
          upload_id: 0,
          filename: f.name,
          file_type: "csv",
          row_count_total: 0,
          row_count_imported: 0,
          row_count_failed: 0,
          status: "failed",
          errors: ["Only .csv or .xlsx files are accepted."],
        });
        return;
      }
      const MAX_SIZE = 10 * 1024 * 1024; // 10 MB
      if (f.size > MAX_SIZE) {
        setLastResult({
          upload_id: 0,
          filename: f.name,
          file_type: "csv",
          row_count_total: 0,
          row_count_imported: 0,
          row_count_failed: 0,
          status: "failed",
          errors: [`File is too large (${(f.size / (1024 * 1024)).toFixed(1)} MB). Maximum allowed is 10 MB.`],
        });
        return;
      }
      uploadMut.mutate(f);
    },
    [uploadMut],
  );

  const onDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragOver(false);
      handleFiles(e.dataTransfer?.files ?? null);
    },
    [handleFiles],
  );

  return (
    <div style={{ fontFamily: FONT_SYS, padding: "28px 32px", maxWidth: 1120, margin: "0 auto" }}>
      <style>{`@media (max-width: 1024px) { .uploads-header { padding-left: 56px !important; } }`}</style>
      <header className="uploads-header" style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, color: C.text, margin: 0 }}>
          Patient Data Uploads
        </h1>
        <p style={{ marginTop: 6, fontSize: 14, color: C.textSubtle }}>
          Upload a CSV or Excel file of patients to run the full RAF analysis — scoring, HCC mapping,
          audit packages and dashboards — without connecting an EMR.
        </p>
      </header>

      {/* Drop zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => fileInputRef.current?.click()}
        role="button"
        tabIndex={0}
        aria-label="Drop a CSV or Excel file here, or press Enter to open file picker"
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") fileInputRef.current?.click();
        }}
        style={{
          border: `2px dashed ${dragOver ? C.brand : C.border}`,
          borderRadius: 16,
          background: dragOver ? C.brandSoft : C.bgCard,
          padding: "48px 24px",
          textAlign: "center",
          cursor: "pointer",
          transition: "all 120ms",
        }}
      >
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: 56,
            height: 56,
            borderRadius: 14,
            background: C.brandSoft,
            color: C.brand,
            marginBottom: 14,
          }}
        >
          <Upload size={26} />
        </div>
        <div style={{ fontSize: 16, fontWeight: 600, color: C.text }}>
          Drag a CSV or Excel file here, or click to browse
        </div>
        <div style={{ marginTop: 6, fontSize: 13, color: C.textSubtle }}>
          Accepted formats: .csv, .xlsx — max 10 MB
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept=".csv,.xlsx"
          style={{ display: "none" }}
          onChange={(e) => handleFiles(e.target.files)}
        />
      </div>

      {/* Templates row */}
      <div style={{ marginTop: 14, display: "flex", gap: 10, flexWrap: "wrap" }}>
        <button
          type="button"
          onClick={() => downloadUploadTemplate("csv")}
          style={btnSecondary}
        >
          <Download size={14} /> Download CSV template
        </button>
        <button
          type="button"
          onClick={() => downloadUploadTemplate("xlsx")}
          style={btnSecondary}
        >
          <Download size={14} /> Download Excel template
        </button>
      </div>

      {/* Upload progress / result */}
      {uploadMut.isPending && (
        <div style={card}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, color: C.textMuted }}>
            <RefreshCw size={16} className="animate-spin" />
            <span>Uploading and processing file…</span>
          </div>
        </div>
      )}

      {lastResult && !uploadMut.isPending && (
        <div style={card}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {lastResult.status === "completed" ? (
              <CheckCircle size={20} color={C.success} />
            ) : lastResult.status === "failed" ? (
              <AlertTriangle size={20} color={C.danger} />
            ) : (
              <AlertTriangle size={20} color={C.warning} />
            )}
            <div style={{ fontWeight: 600, color: C.text }}>
              {lastResult.status === "completed"
                ? "Upload complete"
                : lastResult.status === "failed"
                  ? "Upload failed"
                  : "Upload finished with some errors"}
            </div>
            <span style={{ marginLeft: "auto", ...statusPillStyle(lastResult.status) }}>
              {lastResult.status.charAt(0).toUpperCase() + lastResult.status.slice(1)}
            </span>
          </div>
          <div
            style={{
              marginTop: 14,
              display: "grid",
              gridTemplateColumns: "repeat(3, 1fr)",
              gap: 12,
            }}
          >
            <MiniStat label="Imported" value={lastResult.row_count_imported} color={C.success} />
            <MiniStat label="Failed" value={lastResult.row_count_failed} color={C.danger} />
            <MiniStat label="Total rows" value={lastResult.row_count_total} color={C.textMuted} />
          </div>
          {lastResult.errors && lastResult.errors.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <button
                type="button"
                style={btnLink}
                onClick={() => setShowErrors((s) => !s)}
              >
                {showErrors ? <EyeOff size={14} /> : <Eye size={14} />}{" "}
                {showErrors ? "Hide" : "View"} errors ({lastResult.errors.length})
              </button>
              {showErrors && (
                <ul
                  style={{
                    marginTop: 8,
                    padding: "10px 14px",
                    listStyle: "none",
                    background: tokens.riskHighSoft,
                    border: `1px solid ${tokens.dangerBorder}`,
                    borderRadius: 10,
                    maxHeight: 220,
                    overflow: "auto",
                    fontSize: 12,
                    color: tokens.danger,
                  }}
                >
                  {lastResult.errors.map((e, i) => (
                    <li key={i} style={{ padding: "2px 0" }}>
                      {e}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}

      {/* Upload history */}
      <section style={{ marginTop: 32 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
          <h2 style={{ fontSize: 16, fontWeight: 700, color: C.text, margin: 0 }}>
            Upload history
          </h2>
          <button type="button" onClick={() => refetch()} style={btnLink}>
            <RefreshCw size={14} /> Refresh
          </button>
        </div>

        <div
          style={{
            background: C.bgCard,
            border: `1px solid ${C.border}`,
            borderRadius: 14,
            overflow: "hidden",
          }}
        >
          {histLoading ? (
            <div style={{ padding: 16 }}>
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="raf-skel"
                  style={{
                    height: 44,
                    borderRadius: 8,
                    marginBottom: i === 2 ? 0 : 8,
                    background: `linear-gradient(90deg, ${C.bgSubtle} 0%, ${C.borderSoft} 50%, ${C.bgSubtle} 100%)`,
                    backgroundSize: "200% 100%",
                    animation: "rafSkelShimmer 1.4s ease-in-out infinite",
                  }}
                />
              ))}
              <style>{`@keyframes rafSkelShimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }`}</style>
            </div>
          ) : !history?.uploads?.length ? (
            <div style={{ padding: "44px 24px", textAlign: "center" }}>
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: 52,
                  height: 52,
                  borderRadius: 14,
                  background: C.brandSoft,
                  color: C.brand,
                  marginBottom: 12,
                }}
              >
                <FileSpreadsheet size={24} />
              </div>
              <div style={{ fontSize: 14, fontWeight: 600, color: C.text, marginBottom: 4 }}>
                No uploads yet
              </div>
              <div style={{ fontSize: 13, color: C.textSubtle, marginBottom: 14 }}>
                Drop a CSV or Excel file above to import your first batch of patients.
              </div>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                style={{
                  ...btnSecondary,
                  borderColor: C.brand,
                  color: C.brand,
                  background: C.brandSoft,
                }}
              >
                <Upload size={14} /> Upload a file
              </button>
            </div>
          ) : (
            <table aria-label="Upload history" style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: C.bgSubtle, color: C.label, textAlign: "left" }}>
                  <th style={th}>Filename</th>
                  <th style={th}>Date</th>
                  <th style={{ ...th, textAlign: "right" }}>Rows imported</th>
                  <th style={th}>Status</th>
                  <th style={{ ...th, textAlign: "right" }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {history.uploads.map((u: UploadRecord) => (
                  <tr key={u.id} style={{ borderTop: `1px solid ${C.rowDivider}` }}>
                    <td style={td}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        {u.file_type === "xlsx" ? (
                          <FileSpreadsheet size={16} color={C.brand} />
                        ) : (
                          <FileText size={16} color={C.brand} />
                        )}
                        <div>
                          <div style={{ color: C.text, fontWeight: 500 }}>{u.filename}</div>
                          <div style={{ fontSize: 11, color: C.textSubtle }}>
                            {formatBytes(u.file_size_bytes)}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td style={{ ...td, color: C.textMuted }}>{formatDate(u.created_at)}</td>
                    <td style={{ ...td, textAlign: "right", color: C.text, fontWeight: 600 }}>
                      {u.row_count_imported.toLocaleString("en-US")}
                      <span style={{ color: C.textSubtle, fontWeight: 400 }}>
                        {" "}
                        / {u.row_count_total.toLocaleString("en-US")}
                      </span>
                    </td>
                    <td style={td}>
                      <span style={statusPillStyle(u.status)}>
                        {u.status.charAt(0).toUpperCase() + u.status.slice(1)}
                      </span>
                    </td>
                    <td style={{ ...td, textAlign: "right" }}>
                      <button
                        type="button"
                        disabled={deleteMut.isPending}
                        onClick={() => setDeleteTarget(u)}
                        style={{
                          ...btnSecondary,
                          color: C.danger,
                          borderColor: tokens.dangerBorder,
                        }}
                      >
                        <Trash2 size={14} /> Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      {/* Delete-upload confirmation — replaces window.confirm so we get
          consistent styling, proper focus management (Cancel is autofocused),
          and a visible destructive button the user must click explicitly. */}
      <ConfirmDialog
        open={!!deleteTarget}
        title="Delete this upload?"
        description={
          deleteTarget
            ? `This will delete the upload "${deleteTarget.filename}" and deactivate all ${deleteTarget.row_count_imported.toLocaleString("en-US")} imported patients. This action cannot be undone.`
            : ""
        }
        confirmLabel="Delete upload"
        destructive
        onConfirm={() => {
          if (deleteTarget) deleteMut.mutate(deleteTarget.id);
        }}
        onClose={() => setDeleteTarget(null)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tiny helpers
// ---------------------------------------------------------------------------

function MiniStat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div
      style={{
        padding: "10px 12px",
        borderRadius: 10,
        border: `1px solid ${C.border}`,
        background: C.bgSubtle,
      }}
    >
      <div style={{ fontSize: 11, color: C.label, textTransform: "uppercase", letterSpacing: 0.5 }}>
        {label}
      </div>
      <div style={{ fontSize: 20, fontWeight: 700, color, marginTop: 2 }}>
        {value.toLocaleString("en-US")}
      </div>
    </div>
  );
}

const card: React.CSSProperties = {
  marginTop: 20,
  background: C.bgCard,
  border: `1px solid ${C.border}`,
  borderRadius: 14,
  padding: 18,
};

const btnSecondary: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  padding: "8px 14px",
  borderRadius: 10,
  border: `1px solid ${C.border}`,
  background: C.bgCard,
  color: C.textMuted,
  fontSize: 13,
  fontWeight: 500,
  cursor: "pointer",
};

const btnLink: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  padding: "4px 8px",
  border: "none",
  background: "transparent",
  color: C.brand,
  fontSize: 13,
  fontWeight: 500,
  cursor: "pointer",
};

const th: React.CSSProperties = {
  padding: "10px 14px",
  fontSize: 11,
  fontWeight: 600,
  textTransform: "uppercase",
  letterSpacing: 0.5,
};

const td: React.CSSProperties = {
  padding: "12px 14px",
  verticalAlign: "middle",
};
