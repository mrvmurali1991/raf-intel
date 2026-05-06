"use client";

import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getPatients, getAuditPackages, generateAudit, downloadAuditPackage } from "@/lib/api";
import { PageHeader, EmptyState } from "@/components/healthcare-ui";
import { DataQualityBanner } from "@/components/DataQualityBanner";
import { useToast } from "@/components/Toast";
import type { Patient, AuditPackage } from "@/types";
import { tokens } from "@/styles/tokens";
import {
  Shield, FileDown, Loader2, CheckCircle2, Search, X, ChevronDown,
  Package, Printer, ShieldCheck, Clock, Calendar, HardDrive, AlertTriangle, RefreshCw,
} from "lucide-react";

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

const formatBytes = (bytes?: number) => {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

const fmtDate = (iso?: string) =>
  iso
    ? new Date(iso).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";

const fmtRelative = (iso?: string) => {
  if (!iso) return "";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
};

const currentYear = new Date().getFullYear();
const yearOptions = Array.from({ length: 5 }, (_, i) => currentYear - i);

/* ------------------------------------------------------------------ */
/*  Skeleton shimmer                                                  */
/* ------------------------------------------------------------------ */
function SkeletonRow() {
  return (
    <tr aria-hidden="true">
      {[40, 160, 60, 100, 160, 80, 100].map((w, i) => (
        <td key={i} style={{ padding: "14px 16px" }}>
          <div
            style={{
              height: 14,
              width: w,
              borderRadius: 6,
              background: `linear-gradient(90deg, ${tokens.slate100} 25%, ${tokens.slate200} 50%, ${tokens.slate100} 75%)`,
              backgroundSize: "200% 100%",
              animation: "audit-shimmer 1.4s infinite",
            }}
          />
        </td>
      ))}
    </tr>
  );
}

/* ------------------------------------------------------------------ */
/*  Patient Search Dropdown                                           */
/* ------------------------------------------------------------------ */

function PatientSelect({
  patients,
  value,
  onChange,
}: {
  patients: Patient[];
  value: string;
  onChange: (pid: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  const listId = "patient-select-list";

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // ESC closes the dropdown
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open]);

  const filtered = useMemo(() => {
    if (!search) return patients;
    const q = search.toLowerCase();
    return patients.filter((p: Patient) => {
      const name = `${p.first_name ?? p.fname} ${p.last_name ?? p.lname}`.toLowerCase();
      return name.includes(q) || String(p.pid).includes(q);
    });
  }, [patients, search]);

  const selected = patients.find((p: Patient) => String(p.pid) === value);
  const selectedLabel = selected
    ? `${selected.first_name ?? selected.fname} ${selected.last_name ?? selected.lname} (PID ${Math.round(Number(selected.pid))})`
    : null;

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-label="Select patient for audit"
        onClick={() => setOpen(!open)}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          width: "100%",
          padding: "10px 12px",
          borderRadius: 8,
          border: open ? `2px solid ${tokens.primary}` : `1px solid ${tokens.slate200}`,
          backgroundColor: tokens.white,
          fontSize: 14,
          color: selectedLabel ? tokens.slate900 : tokens.slate400,
          cursor: "pointer",
          outline: "none",
          outlineOffset: 2,
        }}
        onFocus={(e) => { e.currentTarget.style.outline = `2px solid ${tokens.primary}`; e.currentTarget.style.outlineOffset = "2px"; }}
        onBlur={(e) => { e.currentTarget.style.outline = "none"; }}
      >
        <span>{selectedLabel ?? "Search and select a patient..."}</span>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {value && (
            <span
              role="button"
              aria-label="Clear patient selection"
              tabIndex={0}
              onClick={(e) => { e.stopPropagation(); onChange(""); setSearch(""); }}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.stopPropagation(); onChange(""); setSearch(""); }}}
              style={{ padding: 2, borderRadius: 4, cursor: "pointer", display: "flex" }}
            >
              <X size={14} color={tokens.slate400} />
            </span>
          )}
          <ChevronDown
            size={16}
            color={tokens.slate400}
            style={{ transition: "transform 0.2s", transform: open ? "rotate(180deg)" : "none" }}
          />
        </div>
      </button>

      {open && (
        <div
          id={listId}
          role="listbox"
          aria-label="Patient list"
          style={{
            position: "absolute",
            zIndex: 50,
            marginTop: 4,
            width: "100%",
            borderRadius: 8,
            border: `1px solid ${tokens.slate200}`,
            backgroundColor: tokens.white,
            boxShadow: "0 4px 16px rgba(0,0,0,0.1)",
            overflow: "hidden",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", borderBottom: `1px solid ${tokens.slate100}` }}>
            <Search size={16} color={tokens.slate400} />
            <input
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Type to search..."
              aria-label="Search patients"
              style={{ flex: 1, border: "none", outline: "none", fontSize: 14, color: tokens.slate900, backgroundColor: "transparent" }}
            />
          </div>
          <div style={{ maxHeight: 200, overflowY: "auto" }}>
            {filtered.length === 0 ? (
              <div style={{ padding: "24px 12px", textAlign: "center", fontSize: 14, color: tokens.slate400 }}>No patients found</div>
            ) : (
              filtered.map((p: Patient) => {
                const label = `${p.first_name ?? p.fname} ${p.last_name ?? p.lname}`;
                const isSelected = String(p.pid) === value;
                return (
                  <button
                    key={p.pid}
                    type="button"
                    role="option"
                    aria-selected={isSelected}
                    onClick={() => { onChange(String(p.pid)); setOpen(false); setSearch(""); }}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      width: "100%",
                      padding: "8px 12px",
                      border: "none",
                      backgroundColor: isSelected ? tokens.primarySoft : "transparent",
                      fontSize: 14,
                      cursor: "pointer",
                      textAlign: "left",
                    }}
                    onMouseEnter={(e) => { if (!isSelected) e.currentTarget.style.backgroundColor = tokens.slate50; }}
                    onMouseLeave={(e) => { if (!isSelected) e.currentTarget.style.backgroundColor = "transparent"; }}
                  >
                    <span style={{ fontWeight: 500, color: tokens.slate900 }}>{label}</span>
                    <span style={{ fontSize: 12, color: tokens.slate400, fontFamily: "monospace" }}>PID {Math.round(Number(p.pid))}</span>
                  </button>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Toggle                                                            */
/* ------------------------------------------------------------------ */

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "10px 14px",
        borderRadius: 8,
        border: `1px solid ${tokens.slate200}`,
        backgroundColor: tokens.white,
        cursor: "pointer",
        width: "100%",
        textAlign: "left",
        outline: "none",
      }}
      onFocus={(e) => { e.currentTarget.style.outline = `2px solid ${tokens.primary}`; e.currentTarget.style.outlineOffset = "2px"; }}
      onBlur={(e) => { e.currentTarget.style.outline = "none"; }}
    >
      <div
        style={{
          width: 36,
          height: 20,
          borderRadius: 10,
          backgroundColor: checked ? tokens.primary : tokens.slate300,
          position: "relative",
          flexShrink: 0,
          transition: "background-color 0.2s",
        }}
      >
        <div
          style={{
            width: 16,
            height: 16,
            borderRadius: 8,
            backgroundColor: tokens.white,
            position: "absolute",
            top: 2,
            left: checked ? 18 : 2,
            transition: "left 0.2s",
            boxShadow: "0 1px 2px rgba(0,0,0,0.15)",
          }}
        />
      </div>
      <span style={{ fontSize: 14, fontWeight: 500, color: tokens.slate900 }}>{label}</span>
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  Status Badge                                                      */
/* ------------------------------------------------------------------ */

function ComplianceBadge({ status }: { status: "complete" | "pending" | "error" }) {
  const config = {
    complete: { bg: tokens.successSoft, border: tokens.emerald300, color: tokens.successDark, icon: <ShieldCheck size={14} />, label: "Compliant" },
    pending:  { bg: tokens.warningSoft, border: tokens.warningBorder, color: tokens.warningText, icon: <Clock size={14} />, label: "Pending" },
    error:    { bg: tokens.dangerSoft,  border: tokens.dangerBorder,  color: tokens.danger,       icon: <Shield size={14} />, label: "Needs Review" },
  }[status];

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        padding: "3px 10px",
        borderRadius: 9999,
        backgroundColor: config.bg,
        border: `1px solid ${config.border}`,
        color: config.color,
        fontSize: 12,
        fontWeight: 600,
        lineHeight: "18px",
      }}
    >
      {config.icon} {config.label}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Year Filter Pills                                                 */
/* ------------------------------------------------------------------ */

function YearFilterPills({
  years,
  selected,
  onChange,
}: {
  years: number[];
  selected: number | null;
  onChange: (y: number | null) => void;
}) {
  return (
    <div role="group" aria-label="Filter by year" style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
      <button
        onClick={() => onChange(null)}
        aria-pressed={selected === null}
        style={{
          padding: "5px 14px",
          borderRadius: 9999,
          border: selected === null ? `2px solid ${tokens.primary}` : `1px solid ${tokens.slate200}`,
          backgroundColor: selected === null ? tokens.primarySoft : tokens.white,
          color: selected === null ? tokens.primary : tokens.slate500,
          fontSize: 13,
          fontWeight: 600,
          cursor: "pointer",
          transition: "all 0.15s ease",
          outline: "none",
        }}
        onFocus={(e) => { e.currentTarget.style.outline = `2px solid ${tokens.primary}`; e.currentTarget.style.outlineOffset = "2px"; }}
        onBlur={(e) => { e.currentTarget.style.outline = "none"; }}
      >
        All
      </button>
      {years.map((y) => (
        <button
          key={y}
          onClick={() => onChange(y)}
          aria-pressed={selected === y}
          style={{
            padding: "5px 14px",
            borderRadius: 9999,
            border: selected === y ? `2px solid ${tokens.primary}` : `1px solid ${tokens.slate200}`,
            backgroundColor: selected === y ? tokens.primarySoft : tokens.white,
            color: selected === y ? tokens.primary : tokens.slate500,
            fontSize: 13,
            fontWeight: 600,
            cursor: "pointer",
            transition: "all 0.15s ease",
            outline: "none",
          }}
          onFocus={(e) => { e.currentTarget.style.outline = `2px solid ${tokens.primary}`; e.currentTarget.style.outlineOffset = "2px"; }}
          onBlur={(e) => { e.currentTarget.style.outline = "none"; }}
        >
          {y}
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Page                                                              */
/* ------------------------------------------------------------------ */

export default function AuditPage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [selectedPid, setSelectedPid] = useState("");
  const [selectedYear, setSelectedYear] = useState(new Date().getFullYear());
  const [includeSuspects, setIncludeSuspects] = useState(false);
  const [recalculate, setRecalculate] = useState(false);
  const [filterYear, setFilterYear] = useState<number | null>(null);

  const patientsQuery = useQuery({ queryKey: ["patients"], queryFn: getPatients });
  const packagesQuery = useQuery({ queryKey: ["audit-packages"], queryFn: () => getAuditPackages() });

  const packages = useMemo(() => {
    const raw = packagesQuery.data?.packages ?? [];
    const sorted = [...raw].sort((a: AuditPackage, b: AuditPackage) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
    if (filterYear) return sorted.filter((p: AuditPackage) => p.year === filterYear);
    return sorted;
  }, [packagesQuery.data, filterYear]);

  const availableYears = useMemo(() => {
    const raw = packagesQuery.data?.packages ?? [];
    const yrs = [...new Set(raw.map((p: AuditPackage) => p.year))].sort((a: number, b: number) => b - a);
    return yrs as number[];
  }, [packagesQuery.data]);

  const patientList = patientsQuery.data ?? [];

  const generateMutation = useMutation({
    mutationFn: (pid: number) =>
      generateAudit(pid, { recalculate, include_suspects: includeSuspects, year: selectedYear }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["audit-packages"] });
      toast.success("Audit Generated", `Package "${data.filename}" created successfully.`);
    },
    onError: (err: Error) => {
      toast.error("Generation Failed", err?.message ?? "Unknown error");
    },
  });

  const handleRetryPackages = useCallback(() => packagesQuery.refetch(), [packagesQuery]);

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: "20px 16px" }} className="rci-page-pad-desktop">
      <DataQualityBanner />
      <PageHeader
        title="Compliance & Audit"
        subtitle="Generate and download RADV audit documentation packages"
        icon={<Shield size={22} />}
      />

      {/* ---- Generate Audit Package ---- */}
      <div
        className="premium-card animate-slide-up"
        style={{ marginBottom: 24, overflow: "hidden" }}
      >
        <div
          style={{
            padding: "20px 24px",
            borderBottom: `1px solid ${tokens.slate100}`,
            display: "flex",
            alignItems: "center",
            gap: 10,
            background: `linear-gradient(135deg, ${tokens.primarySoft} 0%, ${tokens.slate50} 100%)`,
          }}
        >
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: 8,
              backgroundColor: tokens.primary,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            <ShieldCheck size={16} color={tokens.white} />
          </div>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: tokens.slate900 }}>Generate Audit Package</h2>
        </div>
        <div style={{ padding: 24, display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Patient + Year row */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
            <div>
              <label
                htmlFor="audit-patient"
                style={{ display: "block", fontSize: 13, fontWeight: 500, color: tokens.slate600, marginBottom: 6 }}
              >
                Patient
              </label>
              <PatientSelect patients={patientList} value={selectedPid} onChange={setSelectedPid} />
            </div>
            <div>
              <label
                htmlFor="audit-year"
                style={{ display: "block", fontSize: 13, fontWeight: 500, color: tokens.slate600, marginBottom: 6 }}
              >
                Year
              </label>
              <select
                id="audit-year"
                value={selectedYear}
                onChange={(e) => setSelectedYear(Number(e.target.value))}
                style={{
                  width: "100%",
                  padding: "10px 12px",
                  borderRadius: 8,
                  border: `1px solid ${tokens.slate200}`,
                  fontSize: 14,
                  color: tokens.slate900,
                  backgroundColor: tokens.white,
                  outline: "none",
                  cursor: "pointer",
                }}
              >
                {yearOptions.map((y) => (
                  <option key={y} value={y}>{y}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Toggles */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
            <Toggle checked={includeSuspects} onChange={setIncludeSuspects} label="Include suspect conditions" />
            <Toggle checked={recalculate} onChange={setRecalculate} label="Recalculate RAF before generating" />
          </div>

          {/* Generate Button */}
          <button
            disabled={!selectedPid || generateMutation.isPending}
            onClick={() => generateMutation.mutate(Number(selectedPid))}
            aria-label="Generate audit package for selected patient"
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
              width: "100%",
              padding: "12px 16px",
              borderRadius: 10,
              border: "none",
              backgroundColor: selectedPid && !generateMutation.isPending ? tokens.primary : tokens.slate200,
              color: selectedPid && !generateMutation.isPending ? tokens.white : tokens.slate400,
              fontSize: 15,
              fontWeight: 600,
              cursor: selectedPid && !generateMutation.isPending ? "pointer" : "not-allowed",
              transition: "all 0.2s ease",
              boxShadow: selectedPid && !generateMutation.isPending ? `0 2px 8px rgba(37,99,235,0.3)` : "none",
              outline: "none",
            }}
            onFocus={(e) => { e.currentTarget.style.outline = `2px solid ${tokens.primary}`; e.currentTarget.style.outlineOffset = "2px"; }}
            onBlur={(e) => { e.currentTarget.style.outline = "none"; }}
          >
            {generateMutation.isPending ? (
              <><Loader2 size={18} style={{ animation: "spin 1s linear infinite" }} /> Generating...</>
            ) : (
              "Generate Package"
            )}
          </button>

          {/* Success banner */}
          {generateMutation.data && (
            <div
              className="animate-fade-in"
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "14px 16px",
                borderRadius: 10,
                backgroundColor: tokens.successSoft,
                border: `1px solid ${tokens.emerald300}`,
                gap: 12,
                flexWrap: "wrap",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <CheckCircle2 size={18} color={tokens.success} />
                <span style={{ fontSize: 14, fontWeight: 500, color: tokens.successDark }}>
                  {generateMutation.data.filename}
                </span>
                <span style={{ fontSize: 13, color: tokens.success }}>{formatBytes(generateMutation.data.size_bytes)}</span>
              </div>
              <button
                type="button"
                aria-label={`Download audit package ${generateMutation.data.filename}`}
                onClick={() =>
                  downloadAuditPackage(
                    generateMutation.data.package_id,
                    generateMutation.data.filename,
                  ).catch((err) => alert(err?.response?.data?.detail || err?.message || "Download failed"))
                }
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "6px 14px",
                  borderRadius: 8,
                  backgroundColor: tokens.successDark,
                  color: tokens.white,
                  fontSize: 13,
                  fontWeight: 600,
                  border: "none",
                  cursor: "pointer",
                  transition: "background-color 0.15s",
                  outline: "none",
                }}
                onFocus={(e) => { e.currentTarget.style.outline = `2px solid ${tokens.primary}`; e.currentTarget.style.outlineOffset = "2px"; }}
                onBlur={(e) => { e.currentTarget.style.outline = "none"; }}
              >
                <FileDown size={14} /> Download
              </button>
            </div>
          )}
        </div>
      </div>

      {/* ---- Audit History ---- */}
      <div
        className="premium-card animate-slide-up"
        style={{ overflow: "hidden", animationDelay: "80ms" }}
      >
        <div
          style={{
            padding: "20px 24px",
            borderBottom: `1px solid ${tokens.slate100}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: 12,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div
              style={{
                width: 32,
                height: 32,
                borderRadius: 8,
                backgroundColor: tokens.accentPurple,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              <Package size={16} color={tokens.white} />
            </div>
            <div>
              <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: tokens.slate900 }}>Audit History</h2>
              {packages.length > 0 && (
                <span style={{ fontSize: 12, color: tokens.slate400 }}>
                  {packages.length} package{packages.length !== 1 ? "s" : ""}
                </span>
              )}
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {availableYears.length > 1 && (
              <YearFilterPills years={availableYears} selected={filterYear} onChange={setFilterYear} />
            )}
            <button
              onClick={() => window.print()}
              className="no-print"
              aria-label="Print audit history"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "7px 14px",
                borderRadius: 9999,
                border: `1px solid ${tokens.slate200}`,
                backgroundColor: tokens.white,
                color: tokens.slate600,
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
                transition: "all 0.15s ease",
                outline: "none",
              }}
              onFocus={(e) => { e.currentTarget.style.outline = `2px solid ${tokens.primary}`; e.currentTarget.style.outlineOffset = "2px"; }}
              onBlur={(e) => { e.currentTarget.style.outline = "none"; }}
            >
              <Printer size={14} /> Print
            </button>
          </div>
        </div>

        {/* Error state */}
        {packagesQuery.isError && (
          <div
            role="alert"
            style={{
              margin: 20,
              padding: "14px 16px",
              borderRadius: 10,
              backgroundColor: tokens.dangerSoft,
              border: `1px solid ${tokens.dangerBorder}`,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: 12,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <AlertTriangle size={16} style={{ color: tokens.danger, flexShrink: 0 }} />
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, color: tokens.danger }}>
                  Failed to load audit packages
                </div>
                <div style={{ fontSize: 12, color: tokens.danger, marginTop: 2 }}>
                  Audit history is unavailable — this is a critical compliance signal. Verify the pipeline is running.
                </div>
              </div>
            </div>
            <button
              onClick={handleRetryPackages}
              aria-label="Retry loading audit packages"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "6px 12px",
                borderRadius: 6,
                border: `1px solid ${tokens.dangerBorder}`,
                backgroundColor: tokens.white,
                color: tokens.danger,
                fontSize: 12,
                fontWeight: 600,
                cursor: "pointer",
                flexShrink: 0,
              }}
            >
              <RefreshCw size={13} /> Retry
            </button>
          </div>
        )}

        {/* Loading skeleton */}
        {packagesQuery.isLoading && (
          <div style={{ overflowX: "auto" }}>
            <table
              aria-label="Audit history loading"
              aria-busy="true"
              style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}
            >
              <thead>
                <tr style={{ borderBottom: `2px solid ${tokens.slate100}`, backgroundColor: tokens.slate50 }}>
                  {["#", "Patient", "Year", "Status", "Generated", "Size", "Download"].map((h) => (
                    <th
                      key={h}
                      scope="col"
                      style={{
                        padding: "12px 16px",
                        textAlign: h === "Download" ? "right" : "left",
                        fontSize: 11,
                        fontWeight: 700,
                        color: tokens.slate400,
                        textTransform: "uppercase",
                        letterSpacing: 0.8,
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: 4 }).map((_, i) => <SkeletonRow key={i} />)}
              </tbody>
            </table>
          </div>
        )}

        {/* Empty state */}
        {!packagesQuery.isLoading && !packagesQuery.isError && packages.length === 0 && (
          packagesQuery.data?.packages && packagesQuery.data.packages.length > 0 ? (
            // Filtered to nothing
            <EmptyState
              icon={<Package size={24} />}
              title="No packages for this year"
              description="Try selecting a different year or clear the filter."
            />
          ) : (
            // No packages at all — caution for compliance
            <div
              style={{
                margin: 20,
                padding: "16px 20px",
                borderRadius: 10,
                backgroundColor: tokens.warningSoft,
                border: `1px solid ${tokens.warningBorder}`,
                display: "flex",
                alignItems: "flex-start",
                gap: 12,
              }}
            >
              <AlertTriangle size={18} style={{ color: tokens.warningStrong, flexShrink: 0, marginTop: 1 }} />
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, color: tokens.warningText }}>
                  No audit packages yet — this is unusual
                </div>
                <div style={{ fontSize: 13, color: tokens.warningText, marginTop: 4 }}>
                  RADV defense requires documented audit packages. Generate your first package above,
                  or verify the audit pipeline is configured and running.
                </div>
              </div>
            </div>
          )
        )}

        {/* Table */}
        {!packagesQuery.isLoading && !packagesQuery.isError && packages.length > 0 && (
          <div style={{ overflowX: "auto" }}>
            <table
              aria-label="Audit package history"
              style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}
            >
              <thead>
                <tr style={{ borderBottom: `2px solid ${tokens.slate100}`, backgroundColor: tokens.slate50 }}>
                  {["#", "Patient", "Year", "Status", "Generated by / When", "Size", "Download"].map((h) => (
                    <th
                      key={h}
                      scope="col"
                      style={{
                        padding: "12px 16px",
                        textAlign: h === "Download" ? "right" : "left",
                        fontSize: 11,
                        fontWeight: 700,
                        color: tokens.slate400,
                        textTransform: "uppercase",
                        letterSpacing: 0.8,
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {packages.map((pkg: AuditPackage, idx: number) => {
                  const patient = patientList.find((p: Patient) => Number(p.pid) === pkg.pid);
                  const patientLabel = patient
                    ? `${patient.first_name ?? patient.fname} ${patient.last_name ?? patient.lname}`
                    : `PID ${pkg.pid}`;
                  // Audit-trail: who generated + when (surface inline for RADV defense)
                  const generatedBy = (pkg as AuditPackage & { generated_by?: string }).generated_by ?? "System";

                  return (
                    <tr
                      key={pkg.id}
                      className="animate-fade-in"
                      style={{
                        borderBottom: idx < packages.length - 1 ? `1px solid ${tokens.slate100}` : "none",
                        backgroundColor: idx % 2 === 0 ? tokens.white : tokens.slate50,
                        transition: "background-color 0.15s ease",
                        animationDelay: `${Math.min(idx * 40, 400)}ms`,
                      }}
                      onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = tokens.primarySoft; }}
                      onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = idx % 2 === 0 ? tokens.white : tokens.slate50; }}
                    >
                      <td style={{ padding: "14px 16px", color: tokens.slate400, fontFamily: "monospace", fontSize: 13 }}>
                        {pkg.id}
                      </td>
                      <td style={{ padding: "14px 16px" }}>
                        <span style={{ fontWeight: 600, color: tokens.slate900 }}>{patientLabel}</span>
                      </td>
                      <td style={{ padding: "14px 16px" }}>
                        <span
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 4,
                            padding: "2px 10px",
                            borderRadius: 9999,
                            backgroundColor: tokens.slate100,
                            color: tokens.slate600,
                            fontSize: 13,
                            fontWeight: 600,
                          }}
                        >
                          <Calendar size={12} /> {pkg.year}
                        </span>
                      </td>
                      <td style={{ padding: "14px 16px" }}>
                        <ComplianceBadge status="complete" />
                      </td>
                      {/* Audit trail: actor + timestamp inline */}
                      <td style={{ padding: "14px 16px" }}>
                        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                          <span style={{ color: tokens.slate700, fontSize: 13, fontWeight: 500 }}>{fmtDate(pkg.created_at)}</span>
                          <span style={{ color: tokens.slate400, fontSize: 11 }}>
                            {fmtRelative(pkg.created_at)} &middot; by {generatedBy}
                          </span>
                        </div>
                      </td>
                      <td style={{ padding: "14px 16px" }}>
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 4, color: tokens.slate600, fontSize: 13 }}>
                          <HardDrive size={12} color={tokens.slate400} /> {formatBytes(pkg.file_size_bytes)}
                        </span>
                      </td>
                      <td style={{ padding: "14px 16px", textAlign: "right" }}>
                        <button
                          type="button"
                          aria-label={`Download audit package for PID ${pkg.pid}, year ${pkg.year}`}
                          onClick={() =>
                            downloadAuditPackage(pkg.id).catch((err) =>
                              alert(err?.response?.data?.detail || err?.message || "Download failed"),
                            )
                          }
                          className="hover-lift"
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 6,
                            padding: "7px 14px",
                            borderRadius: 8,
                            border: `1px solid ${tokens.slate200}`,
                            backgroundColor: tokens.white,
                            color: tokens.slate600,
                            fontSize: 13,
                            fontWeight: 600,
                            cursor: "pointer",
                            boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
                            outline: "none",
                          }}
                          onFocus={(e) => { e.currentTarget.style.outline = `2px solid ${tokens.primary}`; e.currentTarget.style.outlineOffset = "2px"; }}
                          onBlur={(e) => { e.currentTarget.style.outline = "none"; }}
                        >
                          <FileDown size={14} /> Download
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg) } }
        @keyframes audit-shimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
        @media (max-width: 640px) {
          .rci-page-pad-desktop { padding: 20px 16px !important; }
        }
      `}</style>
    </div>
  );
}
