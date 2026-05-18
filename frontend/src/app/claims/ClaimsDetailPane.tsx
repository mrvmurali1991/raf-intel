"use client";

/**
 * ClaimsDetailPane — lazy-loaded tabbed detail panel for a claims batch.
 *
 * Extracted from claims/page.tsx to defer the per-batch tab content
 * (Claims, Diagnoses, HCC Mapping, Unmatched Patients) from the initial bundle.
 */

import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { tokens } from "@/styles/tokens";
import { EmptyState } from "@/components/healthcare-ui";
import {
  FileText, RefreshCw, AlertTriangle, Tag, Layers, Users, CheckCircle, Upload,
} from "lucide-react";

// ── Design tokens ─────────────────────────────────────────────────────────────
const C = {
  white:      tokens.white,
  slate50:    tokens.slate50,
  slate100:   tokens.slate100,
  slate200:   tokens.slate200,
  slate400:   tokens.slate400,
  slate500:   tokens.slate500,
  slate600:   tokens.slate600,
  slate700:   tokens.slate700,
  slate800:   tokens.slate800,
  slate900:   tokens.slate900,
  teal:       "#0F766E",
  tealSoft:   "rgba(15,118,110,0.08)",
  tealBorder: "rgba(15,118,110,0.22)",
  emerald:    tokens.riskLow,
  emeraldSoft: tokens.successSoft,
  red:        tokens.danger,
};

// ── Types ─────────────────────────────────────────────────────────────────────
type DetailTab = "claims" | "diagnoses" | "hcc" | "unmapped";

interface ClaimRecord { id: number; patient_name?: string; patient_dob?: string; patient_gender?: string; member_id?: string; provider_name?: string; provider_npi?: string; date_of_service?: string; icd10_codes?: string[] | string; cpt_codes?: string[] | string; charges?: number; openemr_pid?: number | null; claim_type?: string }
interface DiagnosisRow { icd10_code: string; hcc_code?: string | null; hcc_label?: string | null; claim_count?: number; patient_count?: number }
interface HccRow { hcc_code: string; hcc_label: string; diagnosis_count?: number; patient_count?: number; claim_count?: number }
interface UnmappedRow { patient_name?: string; patient_dob?: string; patient_gender?: string; member_id?: string; claim_count?: number }
type QState<T> = { isLoading: boolean; isError: boolean; data?: T; refetch: () => void };

// ── Utilities ─────────────────────────────────────────────────────────────────
const fmtN = (v: number | string | undefined | null) => { const n = v == null ? 0 : typeof v === "number" ? v : Number(v); return (Number.isFinite(n) ? n : 0).toLocaleString("en-US"); };
const toList = (v: string[] | string | undefined): string[] => {
  if (!v) return [];
  if (Array.isArray(v)) return v;
  try { const p = JSON.parse(v); return Array.isArray(p) ? p : []; } catch { return String(v).split(",").map((s) => s.trim()).filter(Boolean); }
};

// ── API helpers ───────────────────────────────────────────────────────────────
async function fetchBatchClaims(id: number) { const { data } = await api.get(`/api/claims/batches/${id}/claims`, { params: { limit: 100 } }); return { claims: data?.claims ?? [], total: data?.total ?? 0 }; }
async function fetchBatchDiagnoses(id: number) { const { data } = await api.get(`/api/claims/batches/${id}/diagnoses`, { params: { limit: 500 } }); return data?.diagnoses ?? []; }
async function fetchHccSummary(id: number) { const { data } = await api.get(`/api/claims/batches/${id}/hcc-summary`, { params: { limit: 200 } }); return data?.hcc_summary ?? []; }
async function fetchUnmapped(id: number) { const { data } = await api.get(`/api/claims/batches/${id}/unmapped-patients`, { params: { limit: 500 } }); return data?.patients ?? []; }

// ── Skeleton ──────────────────────────────────────────────────────────────────
function Skeleton({ w, h = 12, r = 6 }: { w: number | string; h?: number; r?: number }) {
  return <div style={{ width: w, height: h, borderRadius: r, backgroundColor: C.slate100, flexShrink: 0 }} />;
}

// ── Tab Loading / Error ───────────────────────────────────────────────────────
function TabLoading() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} w="100%" h={36} r={8} />)}
    </div>
  );
}
function TabError({ onRetry }: { onRetry: () => void }) {
  return (
    <div style={{ textAlign: "center", padding: "28px 0" }}>
      <AlertTriangle size={24} style={{ color: C.red, marginBottom: 8 }} />
      <p style={{ margin: "0 0 12px", fontSize: 13, color: C.slate500 }}>Failed to load data.</p>
      <button onClick={onRetry} style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, fontWeight: 600, padding: "6px 12px", borderRadius: 999, border: `1px solid ${C.teal}33`, background: C.tealSoft, color: C.teal, cursor: "pointer" }}>
        <RefreshCw size={12} /> Retry
      </button>
    </div>
  );
}

function TableShell({ cols, header, children }: { cols: string; header: string[]; children: React.ReactNode }) {
  return (
    <div style={{ border: `1px solid ${C.slate200}`, borderRadius: 10, overflow: "hidden" }}>
      <div style={{ display: "grid", gridTemplateColumns: cols, gap: 8, padding: "10px 16px", background: C.slate50, borderBottom: `1px solid ${C.slate200}` }}>
        {header.map((h) => <span key={h} style={{ fontSize: 11, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.05em", color: C.slate500 }}>{h}</span>)}
      </div>
      {children}
    </div>
  );
}

// ── Tab content components ────────────────────────────────────────────────────
function ClaimsTabContent({ q }: { q: QState<{ claims: ClaimRecord[]; total: number }> }) {
  if (q.isLoading) return <TabLoading />;
  if (q.isError) return <TabError onRetry={q.refetch} />;
  const rows = q.data?.claims ?? [];
  if (!rows.length) return <EmptyState icon={<FileText size={24} />} title="No claim records" description="This batch has no parsed claims yet." />;
  const cols = "2fr 1.1fr 1.5fr 2fr 100px";
  return (
    <TableShell cols={cols} header={["Patient", "DOS", "Provider", "ICD-10 Codes", "Charges"]}>
      {rows.slice(0, 100).map((c, i) => {
        const codes = toList(c.icd10_codes);
        const matched = !!c.openemr_pid;
        return (
          <div key={c.id} className="claims-row" style={{ display: "grid", gridTemplateColumns: cols, gap: 8, padding: "11px 16px", alignItems: "flex-start", borderBottom: i < rows.length - 1 ? `1px solid ${C.slate100}` : "none", background: i % 2 === 1 ? C.slate50 : C.white, transition: "background 0.12s ease" }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: C.slate800, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", display: "flex", alignItems: "center", gap: 6 }}>
                {c.patient_name ?? "—"}
                {matched && <span title={`Matched to OpenEMR pid ${c.openemr_pid}`} style={{ fontSize: 9, fontWeight: 700, padding: "1px 6px", borderRadius: 999, background: C.emeraldSoft, color: C.emerald, border: `1px solid ${C.emerald}33` }}>Matched</span>}
              </div>
              {c.member_id && <div style={{ fontSize: 11, color: C.slate400, fontFamily: "ui-monospace, monospace" }}>{c.member_id}</div>}
            </div>
            <span style={{ fontSize: 12, color: C.slate600 }}>{c.date_of_service ?? "—"}</span>
            <span style={{ fontSize: 12, color: C.slate600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.provider_name ?? "—"}</span>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {codes.slice(0, 5).map((code) => <span key={code} style={{ padding: "2px 6px", borderRadius: 4, fontSize: 10, fontFamily: "ui-monospace, monospace", fontWeight: 600, background: C.tealSoft, color: C.teal, border: `1px solid ${C.tealBorder}` }}>{code}</span>)}
              {codes.length > 5 && <span style={{ fontSize: 10, color: C.slate400, alignSelf: "center" }}>+{codes.length - 5}</span>}
              {codes.length === 0 && <span style={{ fontSize: 11, color: C.slate400 }}>—</span>}
            </div>
            <span className="tabular-nums" style={{ fontSize: 12, fontWeight: 600, color: C.slate700, textAlign: "right", fontFamily: "ui-monospace, monospace" }}>${(c.charges ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2 })}</span>
          </div>
        );
      })}
      {(q.data?.total ?? 0) > 100 && <div style={{ padding: "10px 16px", textAlign: "center", fontSize: 12, color: C.slate500, background: C.slate50, borderTop: `1px solid ${C.slate200}` }}>Showing first 100 of {fmtN(q.data?.total)} claims</div>}
    </TableShell>
  );
}

function DiagnosesTabContent({ q }: { q: QState<DiagnosisRow[]> }) {
  if (q.isLoading) return <TabLoading />;
  if (q.isError) return <TabError onRetry={q.refetch} />;
  const rows = q.data ?? [];
  if (!rows.length) return <EmptyState icon={<Tag size={24} />} title="No diagnoses" description="Process the batch to extract ICD-10 codes." />;
  const cols = "140px 1fr 160px 90px 90px";
  return (
    <TableShell cols={cols} header={["ICD-10", "HCC Label", "HCC", "Claims", "Patients"]}>
      {rows.map((d, i) => (
        <div key={`${d.icd10_code}-${d.hcc_code ?? ""}-${i}`} style={{ display: "grid", gridTemplateColumns: cols, gap: 8, padding: "10px 16px", alignItems: "center", borderBottom: i < rows.length - 1 ? `1px solid ${C.slate100}` : "none", background: i % 2 === 1 ? C.slate50 : C.white }}>
          <span style={{ fontSize: 12, fontFamily: "ui-monospace, monospace", fontWeight: 700, color: C.slate700, padding: "3px 8px", background: C.slate100, borderRadius: 5, display: "inline-block", justifySelf: "start" }}>{d.icd10_code}</span>
          <span style={{ fontSize: 12, color: C.slate600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.hcc_label ?? "—"}</span>
          {d.hcc_code ? <span style={{ fontSize: 11, fontWeight: 700, padding: "3px 9px", borderRadius: 999, background: C.tealSoft, color: C.teal, border: `1px solid ${C.tealBorder}`, justifySelf: "start" }}>HCC {d.hcc_code}</span> : <span style={{ fontSize: 11, fontWeight: 600, padding: "3px 9px", borderRadius: 999, background: C.slate100, color: C.slate500, justifySelf: "start" }}>Unmapped</span>}
          <span className="tabular-nums" style={{ fontSize: 12, fontWeight: 600, color: C.slate700 }}>{fmtN(d.claim_count)}</span>
          <span className="tabular-nums" style={{ fontSize: 12, fontWeight: 600, color: C.slate700 }}>{fmtN(d.patient_count)}</span>
        </div>
      ))}
    </TableShell>
  );
}

function HccTabContent({ q }: { q: QState<HccRow[]> }) {
  if (q.isLoading) return <TabLoading />;
  if (q.isError) return <TabError onRetry={q.refetch} />;
  const rows = q.data ?? [];
  if (!rows.length) return <EmptyState icon={<Layers size={24} />} title="No HCC data" description="Process the batch to see HCC distribution." />;
  const max = Math.max(...rows.map((r) => r.patient_count ?? 0), 1);
  return (
    <div>
      <p style={{ margin: "0 0 14px", fontSize: 13, color: C.slate500 }}>Ranked HCC distribution — top categories by unique patient count.</p>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {rows.slice(0, 15).map((h) => {
          const pct = ((h.patient_count ?? 0) / max) * 100;
          return (
            <div key={h.hcc_code} style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <span style={{ width: 74, fontSize: 11, fontWeight: 700, padding: "3px 9px", borderRadius: 999, background: C.tealSoft, color: C.teal, border: `1px solid ${C.tealBorder}`, textAlign: "center", flexShrink: 0 }}>HCC {h.hcc_code}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, color: C.slate700, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginBottom: 4 }} title={h.hcc_label}>{h.hcc_label || "—"}</div>
                <div style={{ height: 8, borderRadius: 4, background: C.slate100, overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${pct}%`, borderRadius: 4, background: `linear-gradient(90deg, ${C.teal}, ${C.emerald})`, transition: "width 0.4s ease" }} />
                </div>
              </div>
              <span className="tabular-nums" style={{ width: 120, fontSize: 11, color: C.slate500, textAlign: "right", flexShrink: 0 }}>
                <strong style={{ color: C.slate800 }}>{fmtN(h.patient_count)}</strong> pts · {fmtN(h.diagnosis_count)} dx
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function UnmappedTabContent({ q }: { q: QState<UnmappedRow[]> }) {
  if (q.isLoading) return <TabLoading />;
  if (q.isError) return <TabError onRetry={q.refetch} />;
  const rows = q.data ?? [];
  if (!rows.length) return <EmptyState icon={<CheckCircle size={24} />} title="All patients matched" description="Every patient in this batch is linked to an OpenEMR record." />;
  const cols = "2fr 120px 80px 1fr 90px";
  return (
    <div>
      <p style={{ margin: "0 0 12px", fontSize: 13, color: C.slate500 }}>{rows.length} distinct patient{rows.length === 1 ? "" : "s"} could not be auto-matched to an OpenEMR record.</p>
      <TableShell cols={cols} header={["Patient Name", "DOB", "Sex", "Member ID", "Claims"]}>
        {rows.map((p, i) => (
          <div key={`${p.patient_name}-${p.member_id}-${i}`} style={{ display: "grid", gridTemplateColumns: cols, gap: 8, padding: "10px 16px", alignItems: "center", borderBottom: i < rows.length - 1 ? `1px solid ${C.slate100}` : "none", background: i % 2 === 1 ? C.slate50 : C.white }}>
            <span style={{ fontSize: 13, color: C.slate800, fontWeight: 500 }}>{p.patient_name || "—"}</span>
            <span style={{ fontSize: 12, color: C.slate600 }}>{p.patient_dob || "—"}</span>
            <span style={{ fontSize: 12, color: C.slate600 }}>{p.patient_gender || "—"}</span>
            <span style={{ fontSize: 12, color: C.slate600, fontFamily: "ui-monospace, monospace", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.member_id || "—"}</span>
            <span className="tabular-nums" style={{ fontSize: 12, fontWeight: 600, color: C.slate700 }}>{fmtN(p.claim_count)}</span>
          </div>
        ))}
      </TableShell>
    </div>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Main export: DetailPane
// ══════════════════════════════════════════════════════════════════════════════
export default function ClaimsDetailPane({ batchId }: { batchId: number }) {
  const [tab, setTab] = useState<DetailTab>("claims");

  const claimsQ = useQuery({ queryKey: ["claims-batch-claims", batchId], queryFn: () => fetchBatchClaims(batchId), enabled: tab === "claims" });
  const diagQ   = useQuery({ queryKey: ["claims-batch-diagnoses", batchId], queryFn: () => fetchBatchDiagnoses(batchId), enabled: tab === "diagnoses" || tab === "hcc" });
  const hccQ    = useQuery({ queryKey: ["claims-batch-hcc", batchId], queryFn: () => fetchHccSummary(batchId), enabled: tab === "hcc" });
  const unmapQ  = useQuery({ queryKey: ["claims-batch-unmapped", batchId], queryFn: () => fetchUnmapped(batchId), enabled: tab === "unmapped" });

  const tabs: { key: DetailTab; label: string; icon: React.ReactNode; count?: number }[] = [
    { key: "claims",    label: "Claims",             icon: <FileText size={13} />, count: claimsQ.data?.total },
    { key: "diagnoses", label: "Diagnoses",          icon: <Tag size={13} />,      count: diagQ.data?.length },
    { key: "hcc",       label: "HCC Mapping",        icon: <Layers size={13} />,   count: hccQ.data?.length },
    { key: "unmapped",  label: "Unmatched Patients", icon: <Users size={13} />,    count: unmapQ.data?.length },
  ];

  return (
    <div style={{ background: C.white, borderRadius: 10, border: `1px solid ${C.slate200}`, overflow: "hidden" }}>
      {/* Tab bar */}
      <div style={{ display: "flex", borderBottom: `1px solid ${C.slate200}`, background: C.slate50, overflowX: "auto" }}>
        {tabs.map((t) => {
          const active = tab === t.key;
          return (
            <button key={t.key} onClick={() => setTab(t.key)} style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "12px 18px", fontSize: 13, fontWeight: active ? 700 : 500, color: active ? C.teal : C.slate500, background: active ? C.white : "transparent", border: "none", borderBottom: active ? `2px solid ${C.teal}` : "2px solid transparent", cursor: "pointer", whiteSpace: "nowrap" }}>
              {t.icon}
              {t.label}
              {t.count != null && <span style={{ marginLeft: 2, padding: "1px 7px", borderRadius: 999, fontSize: 10, fontWeight: 700, background: active ? C.tealSoft : C.slate100, color: active ? C.teal : C.slate500 }}>{t.count}</span>}
            </button>
          );
        })}
      </div>

      {/* Content */}
      <div style={{ padding: 18, minHeight: 200 }}>
        {tab === "claims"    && <ClaimsTabContent q={claimsQ} />}
        {tab === "diagnoses" && <DiagnosesTabContent q={diagQ} />}
        {tab === "hcc"       && <HccTabContent q={hccQ} />}
        {tab === "unmapped"  && <UnmappedTabContent q={unmapQ} />}
      </div>
    </div>
  );
}
