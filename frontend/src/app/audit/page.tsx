"use client";

import { useState, useEffect, useMemo, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getPatients, getAuditPackages, generateAudit, downloadAuditPackage } from "@/lib/api";
import { PageHeader, EmptyState } from "@/components/healthcare-ui";
import { useToast } from "@/components/Toast";
import type { Patient, AuditPackage } from "@/types";
import { Shield, FileDown, Loader2, CheckCircle2, Search, X, ChevronDown, Package, Printer, ShieldCheck, Clock, Calendar, HardDrive } from "lucide-react";

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

const formatBytes = (bytes?: number) => {
  if (!bytes) return "\u2014";
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
    : "\u2014";

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

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

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
        onClick={() => setOpen(!open)}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          width: "100%",
          padding: "10px 12px",
          borderRadius: 8,
          border: open ? "2px solid #2563EB" : "1px solid #E2E8F0",
          backgroundColor: "#fff",
          fontSize: 14,
          color: selectedLabel ? "#0F172A" : "#94A3B8",
          cursor: "pointer",
          outline: "none",
        }}
      >
        <span>{selectedLabel ?? "Search and select a patient..."}</span>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {value && (
            <span
              onClick={(e) => { e.stopPropagation(); onChange(""); setSearch(""); }}
              style={{ padding: 2, borderRadius: 4, cursor: "pointer", display: "flex" }}
            >
              <X size={14} color="#94A3B8" />
            </span>
          )}
          <ChevronDown
            size={16}
            color="#94A3B8"
            style={{ transition: "transform 0.2s", transform: open ? "rotate(180deg)" : "none" }}
          />
        </div>
      </button>

      {open && (
        <div
          style={{
            position: "absolute",
            zIndex: 50,
            marginTop: 4,
            width: "100%",
            borderRadius: 8,
            border: "1px solid #E2E8F0",
            backgroundColor: "#fff",
            boxShadow: "0 4px 16px rgba(0,0,0,0.1)",
            overflow: "hidden",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", borderBottom: "1px solid #F1F5F9" }}>
            <Search size={16} color="#94A3B8" />
            <input
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Type to search..."
              style={{ flex: 1, border: "none", outline: "none", fontSize: 14, color: "#0F172A", backgroundColor: "transparent" }}
            />
          </div>
          <div style={{ maxHeight: 200, overflowY: "auto" }}>
            {filtered.length === 0 ? (
              <div style={{ padding: "24px 12px", textAlign: "center", fontSize: 14, color: "#94A3B8" }}>No patients found</div>
            ) : (
              filtered.map((p: Patient) => {
                const label = `${p.first_name ?? p.fname} ${p.last_name ?? p.lname}`;
                const isSelected = String(p.pid) === value;
                return (
                  <button
                    key={p.pid}
                    type="button"
                    onClick={() => { onChange(String(p.pid)); setOpen(false); setSearch(""); }}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "space-between",
                      width: "100%",
                      padding: "8px 12px",
                      border: "none",
                      backgroundColor: isSelected ? "#EFF6FF" : "transparent",
                      fontSize: 14,
                      cursor: "pointer",
                      textAlign: "left",
                    }}
                    onMouseEnter={(e) => { if (!isSelected) e.currentTarget.style.backgroundColor = "#F8FAFC"; }}
                    onMouseLeave={(e) => { if (!isSelected) e.currentTarget.style.backgroundColor = "transparent"; }}
                  >
                    <span style={{ fontWeight: 500, color: "#0F172A" }}>{label}</span>
                    <span style={{ fontSize: 12, color: "#94A3B8", fontFamily: "monospace" }}>PID {Math.round(Number(p.pid))}</span>
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
      onClick={() => onChange(!checked)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "10px 14px",
        borderRadius: 8,
        border: "1px solid #E2E8F0",
        backgroundColor: "#fff",
        cursor: "pointer",
        width: "100%",
        textAlign: "left",
      }}
    >
      <div
        style={{
          width: 36,
          height: 20,
          borderRadius: 10,
          backgroundColor: checked ? "#2563EB" : "#CBD5E1",
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
            backgroundColor: "#fff",
            position: "absolute",
            top: 2,
            left: checked ? 18 : 2,
            transition: "left 0.2s",
            boxShadow: "0 1px 2px rgba(0,0,0,0.15)",
          }}
        />
      </div>
      <span style={{ fontSize: 14, fontWeight: 500, color: "#0F172A" }}>{label}</span>
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  Status Badge                                                      */
/* ------------------------------------------------------------------ */

function ComplianceBadge({ status }: { status: "complete" | "pending" | "error" }) {
  const config = {
    complete: { bg: "#F0FDF4", border: "#BBF7D0", color: "#166534", icon: <ShieldCheck size={14} />, label: "Compliant" },
    pending: { bg: "#FFFBEB", border: "#FDE68A", color: "#92400E", icon: <Clock size={14} />, label: "Pending" },
    error: { bg: "#FEF2F2", border: "#FECACA", color: "#991B1B", icon: <Shield size={14} />, label: "Needs Review" },
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
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
      <button
        onClick={() => onChange(null)}
        style={{
          padding: "5px 14px",
          borderRadius: 9999,
          border: selected === null ? "2px solid #2563EB" : "1px solid #E2E8F0",
          backgroundColor: selected === null ? "#EFF6FF" : "#fff",
          color: selected === null ? "#2563EB" : "#64748B",
          fontSize: 13,
          fontWeight: 600,
          cursor: "pointer",
          transition: "all 0.15s ease",
        }}
      >
        All
      </button>
      {years.map((y) => (
        <button
          key={y}
          onClick={() => onChange(y)}
          style={{
            padding: "5px 14px",
            borderRadius: 9999,
            border: selected === y ? "2px solid #2563EB" : "1px solid #E2E8F0",
            backgroundColor: selected === y ? "#EFF6FF" : "#fff",
            color: selected === y ? "#2563EB" : "#64748B",
            fontSize: 13,
            fontWeight: 600,
            cursor: "pointer",
            transition: "all 0.15s ease",
          }}
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

  const { data: patients } = useQuery({ queryKey: ["patients"], queryFn: getPatients });
  const { data: packagesData } = useQuery({ queryKey: ["audit-packages"], queryFn: () => getAuditPackages() });

  const packages = useMemo(() => {
    const raw = packagesData?.packages ?? [];
    const sorted = [...raw].sort((a: AuditPackage, b: AuditPackage) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
    if (filterYear) return sorted.filter((p: AuditPackage) => p.year === filterYear);
    return sorted;
  }, [packagesData, filterYear]);

  const availableYears = useMemo(() => {
    const raw = packagesData?.packages ?? [];
    const yrs = [...new Set(raw.map((p: AuditPackage) => p.year))].sort((a: number, b: number) => b - a);
    return yrs as number[];
  }, [packagesData]);

  const patientList = patients ?? [];

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

  return (
    <div style={{ maxWidth: 960, margin: "0 auto" }}>
      <PageHeader
        title="Compliance & Audit"
        subtitle="Generate and download audit documentation packages"
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
            borderBottom: "1px solid #F1F5F9",
            display: "flex",
            alignItems: "center",
            gap: 10,
            background: "linear-gradient(135deg, #EFF6FF 0%, #F8FAFC 100%)",
          }}
        >
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: 8,
              backgroundColor: "#2563EB",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            <ShieldCheck size={16} color="#fff" />
          </div>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: "#0F172A" }}>Generate Audit Package</h2>
        </div>
        <div style={{ padding: 24, display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Patient + Year row */}
          <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 12 }}>
            <div>
              <label style={{ display: "block", fontSize: 13, fontWeight: 500, color: "#475569", marginBottom: 6 }}>Patient</label>
              <PatientSelect patients={patientList} value={selectedPid} onChange={setSelectedPid} />
            </div>
            <div>
              <label style={{ display: "block", fontSize: 13, fontWeight: 500, color: "#475569", marginBottom: 6 }}>Year</label>
              <select
                value={selectedYear}
                onChange={(e) => setSelectedYear(Number(e.target.value))}
                style={{
                  width: "100%",
                  padding: "10px 12px",
                  borderRadius: 8,
                  border: "1px solid #E2E8F0",
                  fontSize: 14,
                  color: "#0F172A",
                  backgroundColor: "#fff",
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
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Toggle checked={includeSuspects} onChange={setIncludeSuspects} label="Include suspect conditions" />
            <Toggle checked={recalculate} onChange={setRecalculate} label="Recalculate RAF before generating" />
          </div>

          {/* Generate Button */}
          <button
            disabled={!selectedPid || generateMutation.isPending}
            onClick={() => generateMutation.mutate(Number(selectedPid))}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
              width: "100%",
              padding: "12px 16px",
              borderRadius: 10,
              border: "none",
              backgroundColor: selectedPid && !generateMutation.isPending ? "#2563EB" : "#E2E8F0",
              color: selectedPid && !generateMutation.isPending ? "#fff" : "#94A3B8",
              fontSize: 15,
              fontWeight: 600,
              cursor: selectedPid && !generateMutation.isPending ? "pointer" : "not-allowed",
              transition: "all 0.2s ease",
              boxShadow: selectedPid && !generateMutation.isPending ? "0 2px 8px rgba(37,99,235,0.3)" : "none",
            }}
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
                backgroundColor: "#F0FDF4",
                border: "1px solid #BBF7D0",
                gap: 12,
                flexWrap: "wrap",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <CheckCircle2 size={18} color="#16A34A" />
                <span style={{ fontSize: 14, fontWeight: 500, color: "#166534" }}>
                  {generateMutation.data.filename}
                </span>
                <span style={{ fontSize: 13, color: "#4ADE80" }}>{formatBytes(generateMutation.data.size_bytes)}</span>
              </div>
              <button
                type="button"
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
                  backgroundColor: "#16A34A",
                  color: "#fff",
                  fontSize: 13,
                  fontWeight: 600,
                  border: "none",
                  cursor: "pointer",
                  transition: "background-color 0.15s",
                }}
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
            borderBottom: "1px solid #F1F5F9",
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
                backgroundColor: "#7C3AED",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              <Package size={16} color="#fff" />
            </div>
            <div>
              <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: "#0F172A" }}>Audit History</h2>
              {packages.length > 0 && (
                <span style={{ fontSize: 12, color: "#94A3B8" }}>
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
                border: "1px solid #E2E8F0",
                backgroundColor: "#fff",
                color: "#475569",
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
                transition: "all 0.15s ease",
              }}
            >
              <Printer size={14} /> Print
            </button>
          </div>
        </div>

        {packages.length === 0 ? (
          <EmptyState
            icon={<Package size={24} />}
            title="No audit packages yet"
            description="Generate your first audit package above to see it listed here."
          />
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
              <thead>
                <tr style={{ borderBottom: "2px solid #F1F5F9", backgroundColor: "#FAFBFC" }}>
                  {["#", "Patient", "Year", "Status", "Generated", "Size", "Download"].map((h) => (
                    <th
                      key={h}
                      style={{
                        padding: "12px 16px",
                        textAlign: h === "Download" ? "right" : "left",
                        fontSize: 11,
                        fontWeight: 700,
                        color: "#94A3B8",
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

                  return (
                    <tr
                      key={pkg.id}
                      className="animate-fade-in"
                      style={{
                        borderBottom: idx < packages.length - 1 ? "1px solid #F1F5F9" : "none",
                        backgroundColor: idx % 2 === 0 ? "#fff" : "#FAFBFD",
                        transition: "background-color 0.15s ease",
                        animationDelay: `${Math.min(idx * 40, 400)}ms`,
                      }}
                      onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = "#F0F4FF"; }}
                      onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = idx % 2 === 0 ? "#fff" : "#FAFBFD"; }}
                    >
                      <td style={{ padding: "14px 16px", color: "#94A3B8", fontFamily: "monospace", fontSize: 13 }}>
                        {pkg.id}
                      </td>
                      <td style={{ padding: "14px 16px" }}>
                        <span style={{ fontWeight: 600, color: "#0F172A" }}>{patientLabel}</span>
                      </td>
                      <td style={{ padding: "14px 16px" }}>
                        <span
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 4,
                            padding: "2px 10px",
                            borderRadius: 9999,
                            backgroundColor: "#F1F5F9",
                            color: "#475569",
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
                      <td style={{ padding: "14px 16px" }}>
                        <div style={{ display: "flex", flexDirection: "column", gap: 1 }}>
                          <span style={{ color: "#334155", fontSize: 13, fontWeight: 500 }}>{fmtDate(pkg.created_at)}</span>
                          <span style={{ color: "#94A3B8", fontSize: 11 }}>{fmtRelative(pkg.created_at)}</span>
                        </div>
                      </td>
                      <td style={{ padding: "14px 16px" }}>
                        <span style={{ display: "inline-flex", alignItems: "center", gap: 4, color: "#475569", fontSize: 13 }}>
                          <HardDrive size={12} color="#94A3B8" /> {formatBytes(pkg.file_size_bytes)}
                        </span>
                      </td>
                      <td style={{ padding: "14px 16px", textAlign: "right" }}>
                        <button
                          type="button"
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
                            border: "1px solid #E2E8F0",
                            backgroundColor: "#fff",
                            color: "#475569",
                            fontSize: 13,
                            fontWeight: 600,
                            cursor: "pointer",
                            boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
                          }}
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

      {/* Spinner keyframe */}
      <style>{`@keyframes spin { to { transform: rotate(360deg) } }`}</style>
    </div>
  );
}
