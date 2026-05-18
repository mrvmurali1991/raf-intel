"use client";

import { useState, useEffect, useMemo, useRef } from "react";
import dynamic from "next/dynamic";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getPatients, getAuditPackages, generateAudit, getAuditDownloadUrl, getAuditChainStatus, verifyAuditChain } from "@/lib/api";
import { downloadCSV } from "@/lib/csv-export";
import { PageHeader, EmptyState } from "@/components/healthcare-ui";
import { useToast } from "@/components/Toast";
import AuditReadinessCard from "@/components/AuditReadinessCard";
import { Shield, FileDown, Loader2, CheckCircle2, Search, X, ChevronDown, Package, Hash, RefreshCw, AlertTriangle, Download } from "lucide-react";
import { usePaymentYear, PAYMENT_YEARS } from "@/contexts/payment-year-context";
import { HistoricalPYBanner } from "@/components/HistoricalPYBanner";

const RadvScenariosCard = dynamic(() => import("./AuditRadvScenariosCard"), {
  ssr: false,
  loading: () => (
    <div style={{ backgroundColor: "#fff", borderRadius: 10, border: "1px solid #E2E8F0", marginBottom: 24, padding: "32px 24px" }}>
      <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 16 }}>
        <div style={{ width: 32, height: 32, borderRadius: 8, backgroundColor: "#F1F5F9" }} />
        <div style={{ width: 140, height: 14, borderRadius: 6, backgroundColor: "#F1F5F9" }} />
      </div>
      {[1, 2, 3].map((i) => (
        <div key={i} style={{ height: 52, backgroundColor: "#F8FAFC", borderRadius: 8, marginBottom: 8 }} />
      ))}
    </div>
  ),
});

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


/* ------------------------------------------------------------------ */
/*  Patient Search Dropdown                                           */
/* ------------------------------------------------------------------ */

function PatientSelect({
  patients,
  value,
  onChange,
}: {
  patients: any[];
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
    return patients.filter((p: any) => {
      const name = `${p.first_name ?? p.fname} ${p.last_name ?? p.lname}`.toLowerCase();
      return name.includes(q) || String(p.pid).includes(q);
    });
  }, [patients, search]);

  const selected = patients.find((p: any) => String(p.pid) === value);
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
          color: selectedLabel ? "#0F172A" : "#64748B",
          cursor: "pointer",
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
              style={{ flex: 1, border: "none", fontSize: 14, color: "#0F172A", backgroundColor: "transparent" }}
            />
          </div>
          <div style={{ maxHeight: 200, overflowY: "auto" }}>
            {filtered.length === 0 ? (
              <div style={{ padding: "24px 12px", textAlign: "center", fontSize: 14, color: "#64748B" }}>No patients found</div>
            ) : (
              filtered.map((p: any) => {
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
                    <span style={{ fontSize: 12, color: "#64748B", fontFamily: "monospace" }}>PID {Math.round(Number(p.pid))}</span>
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
/*  Hash Tooltip                                                      */
/* ------------------------------------------------------------------ */

function HashTooltip({ currentHash, previousHash }: { currentHash?: string; previousHash?: string }) {
  const [visible, setVisible] = useState(false);

  if (!currentHash && !previousHash) return null;

  return (
    <div style={{ position: "relative", display: "inline-flex", alignItems: "center" }}>
      <button
        type="button"
        aria-label="Show SHA-256 hashes"
        onMouseEnter={() => setVisible(true)}
        onMouseLeave={() => setVisible(false)}
        onFocus={() => setVisible(true)}
        onBlur={() => setVisible(false)}
        style={{
          border: "none",
          background: "none",
          cursor: "pointer",
          padding: "2px 4px",
          borderRadius: 4,
          display: "inline-flex",
          alignItems: "center",
          color: "#94A3B8",
        }}
      >
        <Hash size={13} />
      </button>

      {visible && (
        <div
          role="tooltip"
          style={{
            position: "absolute",
            left: "calc(100% + 8px)",
            top: "50%",
            transform: "translateY(-50%)",
            zIndex: 100,
            backgroundColor: "#1E293B",
            color: "#F1F5F9",
            borderRadius: 8,
            padding: "10px 12px",
            width: 340,
            boxShadow: "0 8px 24px rgba(0,0,0,0.25)",
            fontSize: 11,
            fontFamily: "monospace",
            lineHeight: 1.6,
            pointerEvents: "none",
          }}
        >
          <div style={{ marginBottom: 6, fontFamily: "sans-serif", fontSize: 11, fontWeight: 600, color: "#94A3B8", textTransform: "uppercase", letterSpacing: 0.5 }}>
            Cryptographic Hash Chain
          </div>
          {currentHash && (
            <div style={{ marginBottom: 4 }}>
              <span style={{ color: "#64748B" }}>SHA-256 (this): </span>
              <span style={{ color: "#7DD3FC", wordBreak: "break-all" }}>{currentHash}</span>
            </div>
          )}
          {previousHash && (
            <div>
              <span style={{ color: "#64748B" }}>SHA-256 (prev): </span>
              <span style={{ color: "#A78BFA", wordBreak: "break-all" }}>{previousHash}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Audit Chain Integrity Card                                        */
/* ------------------------------------------------------------------ */

function AuditChainIntegrityCard() {
  const [verifyResult, setVerifyResult] = useState<{
    ok: boolean; total_entries: number; integrity_pct: number;
    first_break_line: number | null; errors: string[];
  } | null>(null);
  const [verifying, setVerifying] = useState(false);

  const { data: chainStatus, isLoading: statusLoading } = useQuery({
    queryKey: ["audit-chain-status"],
    queryFn: getAuditChainStatus,
    staleTime: 30_000,
  });

  const handleVerify = async () => {
    setVerifying(true);
    try {
      const result = await verifyAuditChain();
      setVerifyResult(result);
    } catch (e) {
      setVerifyResult({ ok: false, total_entries: 0, integrity_pct: 0, first_break_line: null, errors: ["Verification request failed"] });
    } finally {
      setVerifying(false);
    }
  };

  const handleExportCSV = () => {
    try {
      // Use shared downloadCSV utility — handles BOM, quoting, filename pattern,
      // and CSV injection prevention. Filename becomes raf-audit-chain-custody-YYYY-MM-DD.csv.
      downloadCSV(
        [
          {
            "Total Entries": chainStatus?.total_entries ?? 0,
            "Last Entry Hash": chainStatus?.last_hash ?? "",
            "Exported At": new Date().toISOString().slice(0, 10),
            "Integrity Status": verifyResult
              ? (verifyResult.ok ? "INTACT" : "BREACH DETECTED")
              : "Not verified",
            "Integrity Pct": verifyResult?.integrity_pct ?? "",
            "First Break Line": verifyResult?.first_break_line ?? "",
          },
        ],
        "audit-chain-custody"
      );
    } catch {
      // silently fail — no toast dependency needed here
    }
  };

  const verified = verifyResult?.ok;
  const pct = verifyResult?.integrity_pct ?? null;

  return (
    <div
      style={{
        backgroundColor: "#fff",
        borderRadius: 10,
        border: "2px solid #2563EB",
        overflow: "hidden",
        marginBottom: 24,
        boxShadow: "0 0 0 4px rgba(37,99,235,0.07)",
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: "16px 24px",
          background: "linear-gradient(135deg, #EFF6FF 0%, #F8FAFC 100%)",
          borderBottom: "1px solid #DBEAFE",
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <div
          style={{
            width: 36, height: 36, borderRadius: 10,
            backgroundColor: "#2563EB", display: "flex", alignItems: "center", justifyContent: "center",
          }}
        >
          <Shield size={18} color="#fff" />
        </div>
        <div>
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "#1E3A8A" }}>
            Audit Chain Integrity
          </h2>
          <p style={{ margin: 0, fontSize: 12, color: "#3B82F6", marginTop: 1 }}>
            SHA-256 hash-chained tamper-evident log — HIPAA §164.312(b)
          </p>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <button
            type="button"
            onClick={handleExportCSV}
            style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              padding: "7px 14px", borderRadius: 7,
              border: "1px solid #BFDBFE", backgroundColor: "#EFF6FF",
              color: "#1D4ED8", fontSize: 13, fontWeight: 600, cursor: "pointer",
            }}
            aria-label="Export chain of custody report"
            data-testid="export-csv-audit-chain"
          >
            <Download size={14} /> Export Chain of Custody
          </button>
          <button
            type="button"
            onClick={handleVerify}
            disabled={verifying}
            style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              padding: "7px 14px", borderRadius: 7,
              border: "none", backgroundColor: verifying ? "#E2E8F0" : "#2563EB",
              color: verifying ? "#94A3B8" : "#fff", fontSize: 13, fontWeight: 600,
              cursor: verifying ? "not-allowed" : "pointer",
            }}
            aria-label="Verify chain integrity"
          >
            {verifying ? <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> : <RefreshCw size={14} />}
            {verifying ? "Verifying..." : "Verify Chain Integrity"}
          </button>
        </div>
      </div>

      {/* Stats row */}
      <div style={{ padding: "16px 24px", display: "flex", gap: 32, alignItems: "center", flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: "#64748B", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 2 }}>
            Total Entries
          </div>
          <div style={{ fontSize: 26, fontWeight: 700, color: "#0F172A", fontFamily: "monospace" }}>
            {statusLoading ? "—" : (chainStatus?.total_entries ?? 0).toLocaleString()}
          </div>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: "#64748B", textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 }}>
            Last Entry Hash
          </div>
          <div
            style={{
              fontFamily: "monospace", fontSize: 12, color: "#1D4ED8",
              backgroundColor: "#EFF6FF", padding: "6px 10px", borderRadius: 6,
              border: "1px solid #BFDBFE", wordBreak: "break-all",
              maxWidth: 480,
            }}
          >
            {statusLoading ? "loading..." : (chainStatus?.last_hash ?? "No entries yet")}
          </div>
        </div>

        {/* Verify result badge */}
        {verifyResult && (
          <div
            style={{
              display: "flex", alignItems: "center", gap: 8,
              padding: "10px 16px", borderRadius: 8,
              backgroundColor: verified ? "#F0FDF4" : "#FEF2F2",
              border: `1px solid ${verified ? "#BBF7D0" : "#FECACA"}`,
            }}
          >
            {verified
              ? <CheckCircle2 size={18} color="#16A34A" />
              : <AlertTriangle size={18} color="#DC2626" />}
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, color: verified ? "#166534" : "#991B1B" }}>
                {verified ? "Chain Intact" : "Integrity Breach"}
              </div>
              <div style={{ fontSize: 12, color: verified ? "#15803D" : "#B91C1C" }}>
                {pct}% integrity
                {verifyResult.first_break_line && ` · Break at line ${verifyResult.first_break_line}`}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Error list */}
      {verifyResult && !verified && verifyResult.errors.length > 0 && (
        <div style={{ padding: "0 24px 16px" }}>
          <div style={{ backgroundColor: "#FEF2F2", borderRadius: 8, padding: "10px 14px", border: "1px solid #FECACA" }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "#991B1B", marginBottom: 6 }}>
              Chain Errors ({verifyResult.errors.length})
            </div>
            {verifyResult.errors.map((e, i) => (
              <div key={i} style={{ fontSize: 11, fontFamily: "monospace", color: "#7F1D1D", marginBottom: 2 }}>{e}</div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Page                                                              */
/* ------------------------------------------------------------------ */

export default function AuditPage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { paymentYear: selectedYear, setPaymentYear: setSelectedYear } = usePaymentYear();
  const [selectedPid, setSelectedPid] = useState("");
  const [includeSuspects, setIncludeSuspects] = useState(false);
  const [recalculate, setRecalculate] = useState(false);

  const { data: patients } = useQuery({ queryKey: ["patients"], queryFn: getPatients });
  const { data: packagesData } = useQuery({ queryKey: ["audit-packages"], queryFn: () => getAuditPackages() });

  const packages = useMemo(() => {
    const raw = packagesData?.packages ?? [];
    return [...raw].sort((a: any, b: any) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
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

  const cardStyle: React.CSSProperties = {
    backgroundColor: "#fff",
    borderRadius: 10,
    border: "1px solid #E2E8F0",
    overflow: "hidden",
  };

  return (
    <div style={{ maxWidth: 960, margin: "0 auto" }}>
      <HistoricalPYBanner paymentYear={selectedYear} />
      <PageHeader
        title="Compliance & Audit"
        subtitle="Generate and download audit documentation packages"
        icon={<Shield size={22} />}
      />

      {/* ---- Audit Chain Integrity ---- */}
      <AuditChainIntegrityCard />

      {/* ---- IRR / Kappa tile ---- */}
      <div style={{ marginBottom: 24 }}>
        <AuditReadinessCard />
      </div>

      {/* ---- RADV Scenarios ---- */}
      <RadvScenariosCard />

      {/* ---- Generate Audit Package ---- */}
      <div id="generate-audit-section" style={{ ...cardStyle, marginBottom: 24 }}>
        <div style={{ padding: "20px 24px", borderBottom: "1px solid #F1F5F9" }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: "#0F172A" }}>Generate Audit Package</h2>
        </div>
        <div style={{ padding: 24, display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Patient + Year row */}
          <div className="audit-form-row" style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 12 }}>
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
                  cursor: "pointer",
                }}
              >
                {PAYMENT_YEARS.map((y) => (
                  <option key={y} value={y}>{y}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Toggles */}
          <div className="audit-form-row" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
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
              borderRadius: 8,
              border: "none",
              backgroundColor: selectedPid && !generateMutation.isPending ? "#2563EB" : "#E2E8F0",
              color: selectedPid && !generateMutation.isPending ? "#fff" : "#94A3B8",
              fontSize: 15,
              fontWeight: 600,
              cursor: selectedPid && !generateMutation.isPending ? "pointer" : "not-allowed",
              transition: "background-color 0.2s",
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
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "14px 16px",
                borderRadius: 8,
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
              <a
                href={getAuditDownloadUrl(generateMutation.data.package_id)}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "6px 14px",
                  borderRadius: 6,
                  backgroundColor: "#16A34A",
                  color: "#fff",
                  fontSize: 13,
                  fontWeight: 600,
                  textDecoration: "none",
                }}
              >
                <FileDown size={14} /> Download
              </a>
            </div>
          )}
        </div>
      </div>

      {/* ---- Audit History ---- */}
      <div style={cardStyle}>
        <div style={{ padding: "20px 24px", borderBottom: "1px solid #F1F5F9" }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: "#0F172A" }}>Audit History</h2>
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
                <tr style={{ borderBottom: "1px solid #F1F5F9" }}>
                  {["#", "Patient", "Year", "Generated", "Size", "", "Download"].map((h) => (
                    <th
                      key={h}
                      style={{
                        padding: "10px 16px",
                        textAlign: h === "Download" ? "right" : "left",
                        fontSize: 12,
                        fontWeight: 600,
                        color: "#64748B",
                        textTransform: "uppercase",
                        letterSpacing: 0.5,
                        width: h === "" ? 32 : undefined,
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {packages.map((pkg: any, idx: number) => {
                  const patient = patientList.find((p: any) => Number(p.pid) === (pkg.patient_id ?? pkg.pid));
                  const patientLabel = patient
                    ? `${patient.first_name ?? patient.fname} ${patient.last_name ?? patient.lname}`
                    : (pkg.patient_id ?? pkg.pid) != null
                      ? `PID ${pkg.patient_id ?? pkg.pid}`
                      : "—";

                  return (
                    <tr key={pkg.id} style={{ borderBottom: idx < packages.length - 1 ? "1px solid #F8FAFC" : "none" }}>
                      <td style={{ padding: "12px 16px", color: "#64748B", fontFamily: "monospace", fontSize: 13 }}>
                        {pkg.id}
                      </td>
                      <td style={{ padding: "12px 16px", fontWeight: 500, color: "#0F172A" }}>
                        {patientLabel}
                      </td>
                      <td style={{ padding: "12px 16px", color: "#475569" }}>
                        {pkg.measurement_year ?? pkg.year ?? "—"}
                      </td>
                      <td style={{ padding: "12px 16px", color: "#64748B", fontSize: 13 }}>
                        {fmtDate(pkg.created_at)}
                      </td>
                      <td style={{ padding: "12px 16px", color: "#475569" }}>
                        {formatBytes(pkg.file_size_bytes)}
                      </td>
                      <td style={{ padding: "12px 16px", textAlign: "center", width: 32 }}>
                        <HashTooltip
                          currentHash={pkg.current_hash ?? pkg.hash_self ?? undefined}
                          previousHash={pkg.previous_hash ?? pkg.hash_prev ?? undefined}
                        />
                      </td>
                      <td style={{ padding: "12px 16px", textAlign: "right" }}>
                        <a
                          href={getAuditDownloadUrl(pkg.id)}
                          download
                          style={{
                            display: "inline-flex",
                            alignItems: "center",
                            gap: 6,
                            padding: "6px 12px",
                            borderRadius: 6,
                            border: "1px solid #E2E8F0",
                            backgroundColor: "#fff",
                            color: "#475569",
                            fontSize: 13,
                            fontWeight: 500,
                            textDecoration: "none",
                            cursor: "pointer",
                          }}
                        >
                          <FileDown size={14} /> Download
                        </a>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Spinner keyframe + responsive overrides */}
      <style>{`
        @keyframes spin { to { transform: rotate(360deg) } }
        @media (max-width: 640px) {
          .audit-form-row {
            grid-template-columns: 1fr !important;
          }
        }
      `}</style>
    </div>
  );
}
