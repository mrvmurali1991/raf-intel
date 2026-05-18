"use client";

/**
 * ProvidersModals — lazy-loaded modal dialogs for the Providers page.
 *
 * Contains AddProviderDialog and AutoDiscoverDialog.
 * Dynamically imported from providers/page.tsx so modal code is excluded
 * from the initial paint bundle.
 */

import React, { useState, useRef, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import api from "@/lib/api";
import { tokens } from "@/styles/tokens";
import { initialsColor } from "@/lib/ui-utils";
import { fmtCurrencySmart } from "@/lib/format";
import { SectionHeader } from "@/components/healthcare-ui";
import FeatureFlag from "@/components/FeatureFlag";
import { HccChipWithPopover } from "@/components/kg/HccExplainCard";
import ProviderSuspectHotlist from "@/components/ProviderSuspectHotlist";
import ProviderFeaturesSettings from "@/components/ProviderFeaturesSettings";
import TopHccOpportunities from "@/components/TopHccOpportunities";
import ProviderRevenueBreakdown from "@/components/ProviderRevenueBreakdown";
import ProviderTrendCard from "@/components/ProviderTrendCard";
import PeerPercentileRibbon from "@/components/PeerPercentileRibbon";
import MeatAuditRiskBadge from "@/components/MeatAuditRiskBadge";
import PreVisitBriefingPanel from "@/components/PreVisitBriefingPanel";
import ProviderReportButton from "@/components/ProviderReportButton";
import {
  Users, TrendingUp, DollarSign, Plus, Search, ChevronDown, ChevronUp,
  RefreshCw, X, AlertCircle, CheckCircle, Bell, BellOff, Zap,
  ArrowUpDown, FileDown,
} from "lucide-react";

// ── Design Tokens ─────────────────────────────────────────────────────────────
const C = {
  bg: tokens.slate50,
  card: tokens.white,
  border: tokens.slate200,
  borderLight: tokens.slate100,
  text: tokens.slate900,
  textMuted: tokens.slate500,
  textSub: tokens.slate400,
  primary: tokens.primary,
  primaryLight: "rgba(37,99,235,0.10)",
  primaryDark: tokens.primaryDark,
  emerald: tokens.success,
  emeraldLight: tokens.successSoft,
  emeraldDark: tokens.emerald800,
  amber: tokens.warningStrong,
  amberLight: tokens.warningSoft,
  amberDark: tokens.warningText,
  red: tokens.riskHigh,
  redLight: tokens.riskHighSoft,
  redDark: tokens.danger,
  violet: tokens.accentPurple,
  gray50: tokens.slate50,
  gray100: tokens.slate100,
  gray200: tokens.slate200,
  gray300: tokens.slate300,
  gray400: tokens.slate400,
  gray600: tokens.slate600,
  white: tokens.white,
};

// ── Types ─────────────────────────────────────────────────────────────────────
type HccPerformance = { hcc_code: string; description: string; patients_at_risk: number; coded: number; uncoded: number; capture_pct: number; revenue_at_stake: number };
type ProviderAlert = { alert_id: number; type: string; message: string; severity: "high" | "medium" | "low"; acknowledged: boolean; created_at: string };
type ProviderDetail = { provider_id: number; first_name: string; last_name: string; credential: string; specialty: string; specialty_category: string; practice_name: string | null; npi: string | null; email: string | null; patient_count: number; scorecard: { capture_rate: number; recapture_rate: number; meat_score: number; documentation_quality: number; revenue_capture: number }; hcc_performance: HccPerformance[]; alerts: ProviderAlert[] };
type ProviderForm = { npi: string; first_name: string; last_name: string; credential: string; specialty: string; specialty_category: string; practice_name: string; email: string };
type DiscoveredProvider = { user_id: number; first_name: string; last_name: string; username: string; specialty?: string | null; npi?: string | null; email?: string | null };

// ── API helpers ───────────────────────────────────────────────────────────────
async function getProviderDetail(providerId: number) {
  const { data } = await api.get(`/api/providers/${providerId}/scorecard`);
  return data as ProviderDetail;
}
async function createProvider(body: ProviderForm) {
  const { data } = await api.post("/api/providers", body);
  return data;
}
async function discoverProviders() {
  const { data } = await api.post("/api/providers/auto-discover");
  return data as { discovered: DiscoveredProvider[] };
}
async function importProviders(ids: number[]) {
  const results = await Promise.all(ids.map((id) => api.post(`/api/providers/${id}/import`).then((r) => r.data)));
  return results;
}
async function acknowledgeAlert(payload: { providerId: number; alertId: number }) {
  const { data } = await api.put(`/api/providers/${payload.providerId}/alerts/${payload.alertId}/acknowledge`);
  return data;
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmt$(v: number | null | undefined): string { return v == null ? "$0" : fmtCurrencySmart(v); }
function fmtPct(v: number | null | undefined): string { return v == null ? "--" : `${Math.round(v * 100)}%`; }
function providerName(p: { first_name: string; last_name: string; credential: string }) { return `${p.first_name} ${p.last_name}${p.credential ? `, ${p.credential}` : ""}`; }
function captureColor(rate: number | null) { if (rate == null) return C.gray400; if (rate >= 0.85) return C.emerald; if (rate >= 0.70) return C.amber; return C.red; }

function CaptureBadge({ rate }: { rate: number | null }) {
  const pct = rate == null ? null : Math.round(rate * 100);
  const color = captureColor(rate);
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "2px 8px", borderRadius: 14, fontSize: 12, fontWeight: 700, color, background: `${color}18` }}>
      {pct == null ? "—" : `${pct}%`}
    </span>
  );
}

function SpecialtyTag({ cat }: { cat: string }) {
  const map: Record<string, { bg: string; color: string }> = {
    PCP: { bg: tokens.primarySoft, color: tokens.primary },
    Specialist: { bg: tokens.warningSoft, color: tokens.warningText },
    Hospitalist: { bg: tokens.successSoft, color: tokens.emerald800 },
  };
  const style = map[cat] ?? { bg: C.gray100, color: C.gray600 };
  return <span style={{ padding: "2px 8px", borderRadius: 6, fontSize: 11, fontWeight: 600, ...style }}>{cat}</span>;
}

// ── SVG Radar Chart ───────────────────────────────────────────────────────────
function RadarChart({ scores }: { scores: Record<string, number> }) {
  const labels = Object.keys(scores);
  const values = Object.values(scores);
  const n = labels.length;
  const cx = 130, cy = 130, r = 80;
  function point(i: number, pct: number) {
    const angle = (i / n) * 2 * Math.PI - Math.PI / 2;
    return { x: cx + r * pct * Math.cos(angle), y: cy + r * pct * Math.sin(angle) };
  }
  const gridLevels = [0.25, 0.5, 0.75, 1.0];
  const axes = labels.map((_, i) => point(i, 1));
  const dataPoints = values.map((v, i) => point(i, Math.min(1, Math.max(0, v))));
  const polygonPoints = dataPoints.map((p) => `${p.x},${p.y}`).join(" ");
  return (
    <svg width={260} height={260} viewBox="0 0 260 260" style={{ overflow: "visible" }}>
      {gridLevels.map((lvl) => {
        const pts = labels.map((_, i) => point(i, lvl));
        return <polygon key={lvl} points={pts.map((p) => `${p.x},${p.y}`).join(" ")} fill="none" stroke={C.border} strokeWidth={1} />;
      })}
      {axes.map((pt, i) => <line key={i} x1={cx} y1={cy} x2={pt.x} y2={pt.y} stroke={C.border} strokeWidth={1} />)}
      <polygon points={polygonPoints} fill={`${C.primary}30`} stroke={C.primary} strokeWidth={2} strokeLinejoin="round" />
      {dataPoints.map((pt, i) => <circle key={`pt-${i}`} cx={pt.x} cy={pt.y} r={4} fill={C.primary} stroke={C.white} strokeWidth={2} />)}
      {labels.map((label, i) => {
        const pt = point(i, 1.22);
        return <text key={`label-${i}`} x={pt.x} y={pt.y} textAnchor="middle" dominantBaseline="middle" fontSize={9} fontWeight="600" fill={C.textMuted}>{label}</text>;
      })}
    </svg>
  );
}

// ── Modal wrapper ─────────────────────────────────────────────────────────────
function Modal({ open, onClose, title, children, width = 560 }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode; width?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    ref.current?.focus();
    function handle(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    window.addEventListener("keydown", handle);
    return () => window.removeEventListener("keydown", handle);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div role="dialog" aria-modal="true" aria-label={title}
      style={{ position: "fixed", inset: 0, zIndex: 1000, display: "flex", alignItems: "center", justifyContent: "center", background: "rgba(15,23,42,0.45)", padding: 24 }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div ref={ref} tabIndex={-1} style={{ background: C.card, borderRadius: 14, width: "100%", maxWidth: width, maxHeight: "90vh", overflowY: "auto", boxShadow: "0 20px 60px rgba(0,0,0,0.15)" }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "20px 24px 16px", borderBottom: `1px solid ${C.border}`, position: "sticky", top: 0, background: C.card, zIndex: 1 }}>
          <h2 style={{ margin: 0, fontSize: 17, fontWeight: 700, color: C.text }}>{title}</h2>
          <button onClick={onClose} aria-label="Close dialog" style={{ border: "none", background: "transparent", cursor: "pointer", color: C.textMuted, padding: 4, display: "flex" }}><X size={20} /></button>
        </div>
        <div style={{ padding: "20px 24px 24px" }}>{children}</div>
      </div>
    </div>
  );
}

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <label style={{ fontSize: 12, fontWeight: 600, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.04em" }}>
        {label}{required && <span style={{ color: C.red, marginLeft: 3 }}>*</span>}
      </label>
      {children}
    </div>
  );
}

const inputStyle: React.CSSProperties = { padding: "9px 12px", border: `1px solid ${C.border}`, borderRadius: 8, fontSize: 14, color: C.text, background: C.white, width: "100%", boxSizing: "border-box" };
const selectStyle: React.CSSProperties = { ...inputStyle, cursor: "pointer" };

// ══════════════════════════════════════════════════════════════════════════════
// Add Provider Dialog
// ══════════════════════════════════════════════════════════════════════════════
export function AddProviderDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState<ProviderForm>({ npi: "", first_name: "", last_name: "", credential: "MD", specialty: "", specialty_category: "PCP", practice_name: "", email: "" });
  const [errors, setErrors] = useState<Partial<Record<keyof ProviderForm, string>>>({});

  const mutation = useMutation({
    mutationFn: createProvider,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["provider-leaderboard"] });
      qc.invalidateQueries({ queryKey: ["provider-summary"] });
      onClose();
      setForm({ npi: "", first_name: "", last_name: "", credential: "MD", specialty: "", specialty_category: "PCP", practice_name: "", email: "" });
    },
  });

  function validate(): boolean {
    const e: typeof errors = {};
    if (!form.first_name.trim()) e.first_name = "Required";
    if (!form.last_name.trim()) e.last_name = "Required";
    if (!form.specialty.trim()) e.specialty = "Required";
    setErrors(e);
    return Object.keys(e).length === 0;
  }

  function handleSubmit(e: React.FormEvent) { e.preventDefault(); if (validate()) mutation.mutate(form); }
  function set(key: keyof ProviderForm, val: string) { setForm((f) => ({ ...f, [key]: val })); setErrors((er) => { const n = { ...er }; delete n[key]; return n; }); }

  return (
    <Modal open={open} onClose={onClose} title="Add Provider">
      <form onSubmit={handleSubmit}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 16 }}>
          <Field label="First Name" required>
            <input style={{ ...inputStyle, borderColor: errors.first_name ? C.red : C.border }} value={form.first_name} onChange={(e) => set("first_name", e.target.value)} placeholder="Jane" />
            {errors.first_name && <span className="text-[11px] text-destructive">{errors.first_name}</span>}
          </Field>
          <Field label="Last Name" required>
            <input style={{ ...inputStyle, borderColor: errors.last_name ? C.red : C.border }} value={form.last_name} onChange={(e) => set("last_name", e.target.value)} placeholder="Smith" />
            {errors.last_name && <span className="text-[11px] text-destructive">{errors.last_name}</span>}
          </Field>
          <Field label="Credential">
            <select style={selectStyle} value={form.credential} onChange={(e) => set("credential", e.target.value)}>
              {["MD", "DO", "NP", "PA", "PharmD", "RN", "Other"].map((c) => <option key={c}>{c}</option>)}
            </select>
          </Field>
          <Field label="NPI">
            <input style={inputStyle} value={form.npi} onChange={(e) => set("npi", e.target.value)} placeholder="1234567890" maxLength={10} />
          </Field>
          <Field label="Specialty" required>
            <input style={{ ...inputStyle, borderColor: errors.specialty ? C.red : C.border }} value={form.specialty} onChange={(e) => set("specialty", e.target.value)} placeholder="Internal Medicine" />
            {errors.specialty && <span className="text-[11px] text-destructive">{errors.specialty}</span>}
          </Field>
          <Field label="Category">
            <select style={selectStyle} value={form.specialty_category} onChange={(e) => set("specialty_category", e.target.value)}>
              <option value="PCP">PCP</option>
              <option value="Specialist">Specialist</option>
              <option value="Hospitalist">Hospitalist</option>
            </select>
          </Field>
          <div style={{ gridColumn: "1 / -1" }}>
            <Field label="Practice Name">
              <input style={inputStyle} value={form.practice_name} onChange={(e) => set("practice_name", e.target.value)} placeholder="Sunrise Medical Group" />
            </Field>
          </div>
          <div style={{ gridColumn: "1 / -1" }}>
            <Field label="Email">
              <input style={inputStyle} type="email" value={form.email} onChange={(e) => set("email", e.target.value)} placeholder="jsmith@example.com" />
            </Field>
          </div>
        </div>
        {mutation.isError && (
          <div style={{ marginTop: 16, padding: "10px 14px", background: C.redLight, borderRadius: 8, fontSize: 13, color: C.redDark, display: "flex", alignItems: "center", gap: 8 }}>
            <AlertCircle size={15} /> Failed to create provider. Please try again.
          </div>
        )}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 24 }}>
          <button type="button" onClick={onClose} style={{ padding: "9px 20px", border: `1px solid ${C.border}`, borderRadius: 8, background: C.white, color: C.textMuted, fontSize: 14, fontWeight: 500, cursor: "pointer" }}>Cancel</button>
          <button type="submit" disabled={mutation.isPending} style={{ padding: "9px 20px", border: "none", borderRadius: 8, background: mutation.isPending ? C.gray300 : C.primary, color: C.white, fontSize: 14, fontWeight: 600, cursor: mutation.isPending ? "not-allowed" : "pointer", display: "flex", alignItems: "center", gap: 8 }}>
            {mutation.isPending && <RefreshCw size={14} style={{ animation: "spin 1s linear infinite" }} />}
            Add Provider
          </button>
        </div>
      </form>
    </Modal>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Auto-Discover Dialog
// ══════════════════════════════════════════════════════════════════════════════
export function AutoDiscoverDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [phase, setPhase] = useState<"idle" | "scanning" | "done">("idle");

  const discoverQuery = useQuery({ queryKey: ["discover-providers"], queryFn: discoverProviders, enabled: phase === "scanning" });
  const importMutation = useMutation({
    mutationFn: importProviders,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["provider-leaderboard"] });
      qc.invalidateQueries({ queryKey: ["provider-summary"] });
      onClose(); setPhase("idle"); setSelected(new Set());
    },
  });

  const discovered = discoverQuery.data?.discovered ?? [];
  const effectivePhase = discoverQuery.isSuccess && phase === "scanning" ? "done" : phase;

  function toggleSelect(id: number) { setSelected((s) => { const n = new Set(s); if (n.has(id)) { n.delete(id); } else { n.add(id); } return n; }); }
  function handleClose() { onClose(); setPhase("idle"); setSelected(new Set()); }

  return (
    <Modal open={open} onClose={handleClose} title="Auto-Discover Providers from EMR" width={600}>
      {effectivePhase === "idle" && (
        <div style={{ textAlign: "center", padding: "24px 0" }}>
          <div style={{ width: 64, height: 64, borderRadius: 14, background: C.primaryLight, display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 16px" }}>
            <Zap size={28} color={C.primary} />
          </div>
          <h3 style={{ margin: "0 0 8px", fontSize: 16, fontWeight: 700, color: C.text }}>Scan OpenEMR Users</h3>
          <p style={{ margin: "0 0 24px", fontSize: 14, color: C.textMuted, lineHeight: 1.6 }}>This will scan your OpenEMR instance for provider-level users and suggest them for import.</p>
          <button onClick={() => setPhase("scanning")} style={{ padding: "10px 28px", background: C.primary, color: C.white, border: "none", borderRadius: 8, fontSize: 14, fontWeight: 600, cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 8 }}>
            <Search size={16} /> Start Scan
          </button>
        </div>
      )}
      {effectivePhase === "scanning" && !discoverQuery.isSuccess && (
        <div style={{ textAlign: "center", padding: "40px 0" }}>
          <div style={{ width: 48, height: 48, borderRadius: "50%", border: `4px solid ${C.primaryLight}`, borderTop: `4px solid ${C.primary}`, margin: "0 auto 16px", animation: "spin 0.8s linear infinite" }} />
          <p className="text-sm text-muted-foreground">Scanning OpenEMR for provider users...</p>
        </div>
      )}
      {effectivePhase === "done" && (
        <>
          {discovered.length === 0 ? (
            <div style={{ textAlign: "center", padding: "32px 0" }}>
              <CheckCircle size={40} color={C.emerald} style={{ margin: "0 auto 12px", display: "block" }} />
              <p className="text-sm text-muted-foreground">No new providers found in OpenEMR (all may already be imported).</p>
            </div>
          ) : (
            <>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
                <span className="text-sm text-muted-foreground">Found <strong className="text-foreground">{discovered.length}</strong> providers</span>
                <button onClick={() => selected.size === discovered.length ? setSelected(new Set()) : setSelected(new Set(discovered.map((d) => d.user_id)))}
                  style={{ fontSize: 12, color: C.primary, background: "none", border: "none", cursor: "pointer", fontWeight: 600 }}>
                  {selected.size === discovered.length ? "Deselect All" : "Select All"}
                </button>
              </div>
              <div style={{ border: `1px solid ${C.border}`, borderRadius: 10, overflow: "hidden", marginBottom: 20 }}>
                {discovered.map((p, i) => (
                  <div key={p.user_id} onClick={() => toggleSelect(p.user_id)}
                    style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 16px", borderBottom: i < discovered.length - 1 ? `1px solid ${C.borderLight}` : "none", cursor: "pointer", background: selected.has(p.user_id) ? C.primaryLight : C.white, transition: "background 0.12s" }}>
                    <input type="checkbox" readOnly checked={selected.has(p.user_id)} style={{ width: 16, height: 16, cursor: "pointer", accentColor: C.primary }} aria-label={`Select ${p.first_name} ${p.last_name}`} />
                    <div style={{ width: 36, height: 36, borderRadius: 10, background: initialsColor(`${p.first_name} ${p.last_name}`), color: C.white, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 700, flexShrink: 0 }}>
                      {((p.first_name || "").trim()[0] || (p.last_name || "").trim()[0] || "•").toUpperCase()}{(p.first_name && p.last_name ? (p.last_name || "").trim()[0] : "").toUpperCase()}
                    </div>
                    <div>
                      <div className="text-sm font-semibold text-foreground">{p.first_name} {p.last_name}</div>
                      <div className="text-xs text-muted-foreground">@{p.username}{p.specialty ? ` · ${p.specialty}` : ""}</div>
                    </div>
                  </div>
                ))}
              </div>
              {importMutation.isError && (
                <div style={{ marginBottom: 16, padding: "10px 14px", background: C.redLight, borderRadius: 8, fontSize: 13, color: C.redDark, display: "flex", alignItems: "center", gap: 8 }}>
                  <AlertCircle size={15} /> Import failed. Please try again.
                </div>
              )}
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
                <button onClick={handleClose} style={{ padding: "9px 20px", border: `1px solid ${C.border}`, borderRadius: 8, background: C.white, color: C.textMuted, fontSize: 14, fontWeight: 500, cursor: "pointer" }}>Cancel</button>
                <button disabled={selected.size === 0 || importMutation.isPending} onClick={() => importMutation.mutate(Array.from(selected))}
                  style={{ padding: "9px 20px", background: selected.size === 0 || importMutation.isPending ? C.gray300 : C.emerald, color: C.white, border: "none", borderRadius: 8, fontSize: 14, fontWeight: 600, cursor: selected.size === 0 || importMutation.isPending ? "not-allowed" : "pointer", display: "flex", alignItems: "center", gap: 8 }}>
                  {importMutation.isPending && <RefreshCw size={14} style={{ animation: "spin 1s linear infinite" }} />}
                  Import {selected.size > 0 ? `(${selected.size})` : ""} Selected
                </button>
              </div>
            </>
          )}
        </>
      )}
    </Modal>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Provider Detail Panel
// ══════════════════════════════════════════════════════════════════════════════
export function ProviderDetailPanel({ providerId, onClose }: { providerId: number; onClose: () => void }) {
  const qc = useQueryClient();
  const { data, isLoading, refetch } = useQuery({ queryKey: ["provider-detail", providerId], queryFn: () => getProviderDetail(providerId) });

  const ackMutation = useMutation({
    mutationFn: (alertId: number) => acknowledgeAlert({ providerId, alertId }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["provider-detail", providerId] }); },
  });

  if (isLoading) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: C.textMuted, fontSize: 14 }}>
        <div style={{ width: 32, height: 32, borderRadius: "50%", border: `3px solid ${C.primaryLight}`, borderTop: `3px solid ${C.primary}`, margin: "0 auto 12px", animation: "spin 0.8s linear infinite" }} />
        Loading scorecard...
      </div>
    );
  }
  if (!data) return <div style={{ padding: 40, textAlign: "center", color: C.textMuted, fontSize: 14 }}>Provider details not available.</div>;

  const radarScores: Record<string, number> = { "Capture": data.scorecard.capture_rate, "Recapture": data.scorecard.recapture_rate, "MEAT": data.scorecard.meat_score, "Doc Quality": data.scorecard.documentation_quality, "Rev Capture": data.scorecard.revenue_capture };
  const openAlerts = data.alerts.filter((a) => !a.acknowledged);

  return (
    <div className="premium-card premium-shadow" style={{ background: C.bg, borderRadius: 14, overflow: "hidden", marginTop: 2 }}>
      {/* Header */}
      <div style={{ background: C.card, padding: "16px 20px", borderBottom: `1px solid ${C.border}`, display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <div style={{ width: 52, height: 52, borderRadius: 14, background: initialsColor(providerName(data)), color: C.white, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, fontWeight: 700, flexShrink: 0 }}>
            {((data.first_name || "").trim()[0] || (data.last_name || "").trim()[0] || "•").toUpperCase()}{(data.first_name && data.last_name ? (data.last_name || "").trim()[0] : "").toUpperCase()}
          </div>
          <div>
            <div style={{ fontSize: 17, fontWeight: 700, color: C.text }}>{providerName(data)}</div>
            <div style={{ fontSize: 13, color: C.textMuted, marginTop: 2 }}>{data.specialty}{data.npi && ` · NPI: ${data.npi}`}{data.practice_name && ` · ${data.practice_name}`}</div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button onClick={() => refetch()} style={{ padding: "7px 14px", border: `1px solid ${C.border}`, borderRadius: 8, background: C.white, color: C.textMuted, fontSize: 13, fontWeight: 500, cursor: "pointer", display: "flex", alignItems: "center", gap: 6 }}><RefreshCw size={13} /> Refresh Scorecard</button>
          <Link href={`/patients?provider=${providerId}`} style={{ padding: "7px 14px", border: `1px solid ${C.primary}`, borderRadius: 8, background: C.primaryLight, color: C.primary, fontSize: 13, fontWeight: 600, cursor: "pointer", display: "flex", alignItems: "center", gap: 6, textDecoration: "none" }}><Users size={13} /> View Patient Panel</Link>
          <button onClick={onClose} style={{ border: "none", background: "transparent", cursor: "pointer", color: C.textMuted, padding: 4, display: "flex" }} aria-label="Close detail panel"><X size={18} /></button>
        </div>
      </div>

      {/* Body */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 0 }}>
        {/* Left: radar + scores */}
        <div style={{ padding: 24, borderRight: `1px solid ${C.border}`, background: C.card }}>
          <div className="provider-radar-wrap" style={{ textAlign: "center", marginBottom: 20 }}>
            <RadarChart scores={radarScores} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {[
              { label: "Capture Rate", value: fmtPct(data.scorecard.capture_rate), color: captureColor(data.scorecard.capture_rate) },
              { label: "Recapture Rate", value: fmtPct(data.scorecard.recapture_rate), color: captureColor(data.scorecard.recapture_rate) },
              { label: "MEAT Score", value: fmtPct(data.scorecard.meat_score), color: C.violet },
              { label: "Doc Quality", value: fmtPct(data.scorecard.documentation_quality), color: C.primary },
              { label: "Revenue Capture", value: fmtPct(data.scorecard.revenue_capture), color: C.emerald },
            ].map((item) => (
              <div key={item.label} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span className="text-xs text-muted-foreground">{item.label}</span>
                <span style={{ fontSize: 13, fontWeight: 700, color: item.color }}>{item.value}</span>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 20, padding: "12px 0", borderTop: `1px solid ${C.border}` }}>
            {[
              { label: "Patients", value: data.patient_count.toLocaleString() },
              { label: "Category", value: <SpecialtyTag cat={data.specialty_category} /> },
              { label: "Email", value: data.email ?? "—" },
            ].map((item) => (
              <div key={item.label} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "7px 0", borderBottom: `1px solid ${C.borderLight}`, fontSize: 12 }}>
                <span className="text-muted-foreground">{item.label}</span>
                <span className="text-foreground font-semibold">{item.value}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Right: alerts + HCC table */}
        <div style={{ padding: 24 }}>
          {openAlerts.length > 0 && (
            <div style={{ marginBottom: 24 }}>
              <SectionHeader title="Active Alerts" icon={<Bell size={16} />} count={openAlerts.length} />
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {openAlerts.map((alert) => {
                  const sev = { high: { bg: C.redLight, fg: C.redDark, border: C.red }, medium: { bg: C.amberLight, fg: C.amberDark, border: C.amber }, low: { bg: C.primaryLight, fg: C.primary, border: C.primary } }[alert.severity] ?? { bg: C.gray100, fg: C.gray600, border: C.gray300 };
                  return (
                    <div key={alert.alert_id} style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10, padding: "10px 14px", background: sev.bg, border: `1px solid ${sev.border}30`, borderRadius: 8 }}>
                      <div>
                        <div style={{ fontSize: 12, fontWeight: 700, textTransform: "uppercase", color: sev.fg, marginBottom: 2 }}>{alert.type}</div>
                        <div className="text-[13px] text-foreground">{alert.message}</div>
                      </div>
                      <button onClick={() => ackMutation.mutate(alert.alert_id)} disabled={ackMutation.isPending} title="Acknowledge alert" style={{ border: "none", background: "transparent", cursor: "pointer", color: sev.fg, flexShrink: 0, padding: 4, display: "flex" }} aria-label="Acknowledge alert"><BellOff size={15} /></button>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          <SectionHeader title="Per-HCC Performance" icon={<TrendingUp size={16} />} count={data.hcc_performance?.length ?? 0} />
          {!data.hcc_performance || data.hcc_performance.length === 0 ? (
            <div style={{ padding: "32px", textAlign: "center", color: C.textMuted, fontSize: 13, background: C.gray50, borderRadius: 10, border: `1px dashed ${C.border}` }}>
              No HCC performance data available for this provider.
            </div>
          ) : (
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: `2px solid ${C.border}` }}>
                    {["HCC Code", "Description", "At Risk", "Coded", "Uncoded", "Capture %", "Revenue at Stake"].map((h) => (
                      <th key={h} style={{ padding: "8px 10px", textAlign: "left", fontSize: 11, fontWeight: 600, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.04em", whiteSpace: "nowrap" }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.hcc_performance.map((row) => {
                    const isMissed = row.capture_pct < 0.7;
                    return (
                      <tr key={row.hcc_code} style={{ borderBottom: `1px solid ${C.borderLight}`, background: isMissed ? `${C.redLight}60` : "transparent" }}>
                        <td style={{ padding: "9px 10px" }}>
                          <FeatureFlag flagKey="kg_evidence_panel" fallback={<span style={{ fontSize: 12, fontWeight: 700, color: isMissed ? C.redDark : C.primary }}>{row.hcc_code}</span>}>
                            <HccChipWithPopover hccCode={String(row.hcc_code)}>
                              <span style={{ fontSize: 12, fontWeight: 700, color: isMissed ? C.redDark : C.primary }}>{row.hcc_code}</span>
                            </HccChipWithPopover>
                          </FeatureFlag>
                        </td>
                        <td style={{ padding: "9px 10px", color: C.text, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {row.description}{isMissed && <span style={{ marginLeft: 8, fontSize: 10, fontWeight: 700, color: C.red, textTransform: "uppercase" }}>Top Missed</span>}
                        </td>
                        <td style={{ padding: "9px 10px", color: C.textMuted }}>{row.patients_at_risk}</td>
                        <td style={{ padding: "9px 10px", color: C.emeraldDark, fontWeight: 600 }}>{row.coded}</td>
                        <td style={{ padding: "9px 10px", color: isMissed ? C.redDark : C.textMuted, fontWeight: isMissed ? 700 : 400 }}>{row.uncoded}</td>
                        <td style={{ padding: "9px 10px" }}><CaptureBadge rate={row.capture_pct} /></td>
                        <td style={{ padding: "9px 10px", fontWeight: 600, color: C.emeraldDark }}>{fmt$(row.revenue_at_stake)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          <FeatureFlag flagKey="provider_top_hcc_opportunities"><div style={{ marginTop: 24 }}><TopHccOpportunities providerId={providerId} /></div></FeatureFlag>
          <FeatureFlag flagKey="provider_revenue_breakdown"><div style={{ marginTop: 24 }}><ProviderRevenueBreakdown providerId={providerId} /></div></FeatureFlag>
          <FeatureFlag flagKey="provider_yoy_trend"><div style={{ marginTop: 24 }}><ProviderTrendCard providerId={providerId} /></div></FeatureFlag>
          <FeatureFlag flagKey="provider_previsit_briefing"><div style={{ marginTop: 24 }}><PreVisitBriefingPanel providerId={providerId} /></div></FeatureFlag>
          <FeatureFlag flagKey="provider_suspect_hotlist"><div style={{ marginTop: 24 }}><ProviderSuspectHotlist providerId={providerId} /></div></FeatureFlag>
          <FeatureFlag flagKey="provider_pdf_report"><div style={{ marginTop: 24, display: "flex", justifyContent: "flex-end" }}><ProviderReportButton providerId={providerId} providerLastName="" /></div></FeatureFlag>
        </div>
      </div>
    </div>
  );
}

// ── Default export: composite wrapper ─────────────────────────────────────────
export default function ProvidersModals({ showAdd, showDiscover, onCloseAdd, onCloseDiscover }: { showAdd: boolean; showDiscover: boolean; onCloseAdd: () => void; onCloseDiscover: () => void }) {
  return (
    <>
      <AddProviderDialog open={showAdd} onClose={onCloseAdd} />
      <AutoDiscoverDialog open={showDiscover} onClose={onCloseDiscover} />
    </>
  );
}
