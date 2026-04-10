"use client";

import { useState, useMemo, Fragment } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  getPatients,
  analyzeNote,
  analyzeEncounter,
  getPatientEncounters,
} from "@/lib/api";
import type { AnalysisResult, GeminiDiagnosis, Patient } from "@/types";
import { useToast } from "@/components/Toast";
import {
  Loader2,
  FileText,
  Activity,
  ChevronDown,
  ChevronRight,
  Search,
  Stethoscope,
  Clock,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  ArrowRight,
  ClipboardPaste,
  ListChecks,
  ShieldCheck,
  TrendingUp,
  Sparkles,
  RotateCcw,
  User,
} from "lucide-react";

/* ───────────────────────── helpers ───────────────────────── */

function dxCondition(dx: GeminiDiagnosis): string {
  return dx.condition || dx.description || "Unknown condition";
}
function dxIcd10(dx: GeminiDiagnosis): string {
  return dx.icd10_code || dx.icd10 || "—";
}
function dxHcc(dx: GeminiDiagnosis): string | null | undefined {
  return dx.hcc_code || dx.hcc || dx.hcc_mapping?.hcc_code;
}
function dxCoeff(dx: GeminiDiagnosis): number | undefined {
  return dx.hcc_weight || dx.hcc_mapping?.coefficient;
}
function meatVal(
  dx: GeminiDiagnosis,
  key: "monitoring" | "evaluation" | "assessment" | "treatment"
): string {
  const short = { monitoring: "M", evaluation: "E", assessment: "A", treatment: "T" }[key] as "M" | "E" | "A" | "T";
  return dx.meat?.[key] || dx.meat?.[short] || "";
}
function suspIcd(s: any): string {
  return s.icd10_code || s.suspect_icd10 || s.icd10 || "—";
}
function suspConf(s: any): number {
  return s.confidence_score ?? s.confidence ?? 0;
}
function suspEvidence(s: any): string {
  return s.rationale || s.evidence || "";
}

/* ───────────────────────── styles ───────────────────────── */

const card: React.CSSProperties = {
  background: "#fff",
  border: "1px solid #E5E7EB",
  borderRadius: 12,
};
const cardDark: React.CSSProperties = { ...card, background: "#F8FAFC" };
const label: React.CSSProperties = {
  fontSize: 13,
  fontWeight: 600,
  color: "#374151",
  marginBottom: 6,
  display: "block",
};
const btn = (primary = true, disabled = false): React.CSSProperties => ({
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  padding: "10px 20px",
  fontSize: 14,
  fontWeight: 600,
  borderRadius: 8,
  border: primary ? "none" : "1px solid #D1D5DB",
  background: disabled ? "#D1D5DB" : primary ? "#2563EB" : "#fff",
  color: disabled ? "#9CA3AF" : primary ? "#fff" : "#374151",
  cursor: disabled ? "not-allowed" : "pointer",
  transition: "all 0.15s",
});
const pill = (active: boolean): React.CSSProperties => ({
  padding: "8px 16px",
  fontSize: 13,
  fontWeight: 600,
  borderRadius: 8,
  border: "1px solid",
  borderColor: active ? "#2563EB" : "#E5E7EB",
  background: active ? "#EFF6FF" : "#fff",
  color: active ? "#2563EB" : "#6B7280",
  cursor: "pointer",
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
  transition: "all 0.15s",
});

/* ───────────────────────── sub-components ───────────────────────── */

function MeatDots({ dx }: { dx: GeminiDiagnosis }) {
  const keys = ["monitoring", "evaluation", "assessment", "treatment"] as const;
  const labels = ["M", "E", "A", "T"];
  const colors = ["#3B82F6", "#8B5CF6", "#F59E0B", "#10B981"];
  return (
    <div style={{ display: "flex", gap: 4 }}>
      {keys.map((k, i) => {
        const present = !!meatVal(dx, k);
        return (
          <div
            key={k}
            title={`${labels[i]}: ${present ? meatVal(dx, k) : "Not documented"}`}
            style={{
              width: 24,
              height: 24,
              borderRadius: 6,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 11,
              fontWeight: 700,
              background: present ? colors[i] + "18" : "#F3F4F6",
              color: present ? colors[i] : "#D1D5DB",
              border: `1.5px solid ${present ? colors[i] + "40" : "#E5E7EB"}`,
            }}
          >
            {labels[i]}
          </div>
        );
      })}
    </div>
  );
}

function ConfBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = value >= 0.85 ? "#10B981" : value >= 0.7 ? "#3B82F6" : value >= 0.5 ? "#F59E0B" : "#EF4444";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 100 }}>
      <div style={{ flex: 1, height: 6, borderRadius: 3, background: "#F3F4F6", overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", borderRadius: 3, background: color, transition: "width 0.3s" }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 600, color, minWidth: 32, textAlign: "right" }}>{pct}%</span>
    </div>
  );
}

function PatientDropdown({
  patients,
  loading,
  selected,
  onSelect,
}: {
  patients: Patient[];
  loading: boolean;
  selected: Patient | null;
  onSelect: (p: Patient | null) => void;
}) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const filtered = useMemo(() => {
    if (!q.trim()) return patients.slice(0, 25);
    const low = q.toLowerCase();
    return patients.filter((p) => {
      const name = `${p.fname || p.first_name} ${p.lname || p.last_name}`.toLowerCase();
      return name.includes(low) || String(p.pid).includes(low);
    }).slice(0, 25);
  }, [patients, q]);
  const name = (p: Patient) => `${p.fname || p.first_name || ""} ${p.lname || p.last_name || ""}`.trim();

  if (selected) {
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", borderRadius: 8, border: "1px solid #E5E7EB", background: "#F9FAFB" }}>
        <div style={{ width: 32, height: 32, borderRadius: "50%", background: "#DBEAFE", display: "flex", alignItems: "center", justifyContent: "center" }}>
          <User size={14} color="#2563EB" />
        </div>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: "#111827" }}>{name(selected)}</div>
          <div style={{ fontSize: 12, color: "#6B7280" }}>PID: {selected.pid}</div>
        </div>
        <button onClick={() => { onSelect(null); setQ(""); }} style={{ fontSize: 12, color: "#2563EB", fontWeight: 600, background: "none", border: "none", cursor: "pointer" }}>
          Change
        </button>
      </div>
    );
  }

  return (
    <div style={{ position: "relative" }}>
      <div style={{ position: "relative" }}>
        <Search size={16} style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "#9CA3AF" }} />
        <input
          placeholder={loading ? "Loading patients..." : "Search patient by name or PID..."}
          value={q}
          onChange={(e) => { setQ(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          disabled={loading}
          style={{ width: "100%", padding: "10px 12px 10px 38px", fontSize: 14, borderRadius: 8, border: "1px solid #E5E7EB", outline: "none", background: "#fff" }}
        />
      </div>
      {open && filtered.length > 0 && (
        <>
          <div style={{ position: "fixed", inset: 0, zIndex: 40 }} onClick={() => setOpen(false)} />
          <div style={{ position: "absolute", zIndex: 50, top: "100%", marginTop: 4, width: "100%", borderRadius: 10, border: "1px solid #E5E7EB", background: "#fff", boxShadow: "0 8px 24px rgba(0,0,0,0.1)", maxHeight: 260, overflowY: "auto" }}>
            {filtered.map((p) => (
              <button
                key={p.pid}
                onClick={() => { onSelect(p); setOpen(false); }}
                style={{ width: "100%", textAlign: "left", padding: "10px 14px", display: "flex", alignItems: "center", gap: 10, fontSize: 14, border: "none", background: "none", cursor: "pointer", borderBottom: "1px solid #F3F4F6" }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "#F9FAFB")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "none")}
              >
                <div style={{ width: 28, height: 28, borderRadius: "50%", background: "#DBEAFE", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: "#2563EB" }}>
                  {(p.fname || p.first_name || "?")[0]}
                </div>
                <span style={{ fontWeight: 500 }}>{name(p)}</span>
                <span style={{ marginLeft: "auto", fontSize: 12, color: "#9CA3AF" }}>PID {p.pid}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/* ───────────────────────── main page ───────────────────────── */

export default function AnalysisPage() {
  const toast = useToast();
  const [mode, setMode] = useState<"paste" | "encounter">("paste");
  const [noteText, setNoteText] = useState("");
  const [pastePatientId, setPastePatientId] = useState("");
  const [selectedPatient, setSelectedPatient] = useState<Patient | null>(null);
  const [selectedEnc, setSelectedEnc] = useState<number | null>(null);
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());
  const [pipelineOpen, setPipelineOpen] = useState(false);
  const [result, setResult] = useState<AnalysisResult | null>(null);

  const patientsQ = useQuery({ queryKey: ["patients"], queryFn: getPatients, staleTime: 5 * 60_000 });
  const encountersQ = useQuery({
    queryKey: ["encounters", selectedPatient?.pid],
    queryFn: () => getPatientEncounters(selectedPatient!.pid),
    enabled: !!selectedPatient && mode === "encounter",
  });

  const noteMut = useMutation({
    mutationFn: () => analyzeNote(pastePatientId || "0", noteText),
    onSuccess: (d) => { setResult(d); toast.success("Complete", "Clinical note analyzed"); },
    onError: (e: any) => toast.error("Failed", e?.response?.data?.detail || e?.message || "Error"),
  });
  const encMut = useMutation({
    mutationFn: () => analyzeEncounter(selectedEnc!, true, true),
    onSuccess: (d) => { setResult(d); toast.success("Complete", "Encounter analyzed"); },
    onError: (e: any) => toast.error("Failed", e?.response?.data?.detail || e?.message || "Error"),
  });

  const analyzing = noteMut.isPending || encMut.isPending;
  const diagnoses = result?.diagnoses ?? [];
  const hccCount = diagnoses.filter((d) => !!dxHcc(d)).length;
  const suspects = result?.suspect_conditions ?? [];
  const confidence = result?.overall_confidence ?? 0;
  const routing = result?.confidence_routing;
  const meta = result?._meta;

  function toggle(i: number) {
    setExpandedRows((prev) => { const n = new Set(prev); n.has(i) ? n.delete(i) : n.add(i); return n; });
  }

  function analyze() {
    setResult(null);
    setExpandedRows(new Set());
    if (mode === "paste") {
      if (!noteText.trim()) { toast.warning("Input", "Enter a clinical note"); return; }
      noteMut.mutate();
    } else {
      if (!selectedEnc) { toast.warning("Input", "Select an encounter"); return; }
      encMut.mutate();
    }
  }

  function reset() {
    setResult(null);
    setNoteText("");
    setPastePatientId("");
    setSelectedPatient(null);
    setSelectedEnc(null);
    setExpandedRows(new Set());
  }

  const meatCount = diagnoses.reduce((sum, dx) => {
    const keys = ["monitoring", "evaluation", "assessment", "treatment"] as const;
    return sum + keys.filter((k) => !!meatVal(dx, k)).length;
  }, 0);
  const meatTotal = diagnoses.length * 4;

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", padding: "24px 16px" }}>
      {/* Header */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <div style={{ width: 36, height: 36, borderRadius: 10, background: "#EFF6FF", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <Stethoscope size={18} color="#2563EB" />
          </div>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: "#111827", margin: 0 }}>Clinical Note Analysis</h1>
        </div>
        <p style={{ fontSize: 14, color: "#6B7280", margin: 0, paddingLeft: 46 }}>
          Extract diagnoses, validate HCC codes, and generate MEAT documentation from clinical notes
        </p>
      </div>

      {/* Input Card */}
      <div style={{ ...card, marginBottom: result ? 24 : 0 }}>
        {/* Mode Tabs */}
        <div style={{ display: "flex", gap: 8, padding: "16px 20px", borderBottom: "1px solid #F3F4F6" }}>
          <button onClick={() => setMode("paste")} style={pill(mode === "paste")}>
            <ClipboardPaste size={14} /> Paste Note
          </button>
          <button onClick={() => setMode("encounter")} style={pill(mode === "encounter")}>
            <ListChecks size={14} /> Select Encounter
          </button>
          {result && (
            <button onClick={reset} style={{ ...pill(false), marginLeft: "auto", fontSize: 12 }}>
              <RotateCcw size={12} /> New Analysis
            </button>
          )}
        </div>

        <div style={{ padding: 20 }}>
          {mode === "paste" ? (
            <div>
              <div style={{ display: "flex", gap: 16, marginBottom: 14 }}>
                <div style={{ flex: "0 0 180px" }}>
                  <label style={label}>Patient ID <span style={{ fontWeight: 400, color: "#9CA3AF" }}>(optional)</span></label>
                  <input
                    value={pastePatientId}
                    onChange={(e) => setPastePatientId(e.target.value)}
                    placeholder="e.g. 1"
                    style={{ width: "100%", padding: "9px 12px", fontSize: 14, borderRadius: 8, border: "1px solid #E5E7EB", outline: "none" }}
                  />
                </div>
              </div>
              <label style={label}>Clinical Note</label>
              <textarea
                value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
                placeholder="Paste the full clinical note text here..."
                style={{
                  width: "100%",
                  minHeight: 220,
                  padding: "12px 14px",
                  fontSize: 13,
                  fontFamily: "'SF Mono', 'Monaco', 'Inconsolata', 'Fira Code', monospace",
                  lineHeight: 1.7,
                  borderRadius: 8,
                  border: "1px solid #E5E7EB",
                  background: "#FAFBFC",
                  outline: "none",
                  resize: "vertical",
                }}
              />
              <div style={{ marginTop: 14 }}>
                <button onClick={analyze} disabled={analyzing || !noteText.trim()} style={btn(true, analyzing || !noteText.trim())}>
                  {analyzing ? <Loader2 size={16} className="animate-spin" /> : <Activity size={16} />}
                  {analyzing ? "Analyzing..." : "Analyze Note"}
                </button>
              </div>
            </div>
          ) : (
            <div>
              <label style={label}>Patient</label>
              <PatientDropdown
                patients={patientsQ.data ?? []}
                loading={patientsQ.isLoading}
                selected={selectedPatient}
                onSelect={(p) => { setSelectedPatient(p); setSelectedEnc(null); }}
              />

              {selectedPatient && (
                <div style={{ marginTop: 16 }}>
                  <label style={label}>Encounters</label>
                  {encountersQ.isLoading ? (
                    <div style={{ display: "flex", alignItems: "center", gap: 8, padding: 16, color: "#6B7280", fontSize: 14 }}>
                      <Loader2 size={16} className="animate-spin" /> Loading encounters...
                    </div>
                  ) : encountersQ.data?.encounters?.length ? (
                    <div style={{ border: "1px solid #E5E7EB", borderRadius: 8, maxHeight: 240, overflowY: "auto" }}>
                      {encountersQ.data.encounters.map((enc) => (
                        <button
                          key={enc.encounter_id}
                          onClick={() => setSelectedEnc(enc.encounter_id)}
                          style={{
                            width: "100%",
                            textAlign: "left",
                            padding: "12px 14px",
                            display: "flex",
                            alignItems: "center",
                            gap: 12,
                            background: selectedEnc === enc.encounter_id ? "#EFF6FF" : "transparent",
                            borderLeft: selectedEnc === enc.encounter_id ? "3px solid #2563EB" : "3px solid transparent",
                            borderBottom: "1px solid #F3F4F6",
                            border: "none",
                            borderBottomStyle: "solid",
                            borderBottomWidth: 1,
                            borderBottomColor: "#F3F4F6",
                            cursor: "pointer",
                            fontSize: 14,
                            transition: "background 0.1s",
                          }}
                        >
                          <div style={{ flex: 1 }}>
                            <div style={{ fontWeight: 600, color: "#111827" }}>Encounter #{enc.encounter_id}</div>
                            <div style={{ fontSize: 12, color: "#6B7280", marginTop: 2 }}>{enc.reason || "No reason recorded"}</div>
                          </div>
                          <div style={{ textAlign: "right" }}>
                            <div style={{ fontSize: 12, color: "#6B7280" }}>{enc.date}</div>
                            {enc.provider_lname && <div style={{ fontSize: 11, color: "#9CA3AF" }}>Dr. {enc.provider_lname}</div>}
                          </div>
                          {selectedEnc === enc.encounter_id && <CheckCircle2 size={16} color="#2563EB" />}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <p style={{ fontSize: 14, color: "#9CA3AF", padding: 16 }}>No encounters found.</p>
                  )}
                </div>
              )}

              <div style={{ marginTop: 16 }}>
                <button onClick={analyze} disabled={analyzing || !selectedEnc} style={btn(true, analyzing || !selectedEnc)}>
                  {analyzing ? <Loader2 size={16} className="animate-spin" /> : <Activity size={16} />}
                  {analyzing ? "Analyzing..." : "Analyze Encounter"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Analyzing State */}
      {analyzing && (
        <div style={{ ...card, padding: "48px 24px", textAlign: "center", borderStyle: "dashed", marginTop: 24 }}>
          <Loader2 size={36} className="animate-spin" style={{ color: "#2563EB", margin: "0 auto 12px" }} />
          <div style={{ fontSize: 16, fontWeight: 600, color: "#111827" }}>Analyzing clinical note...</div>
          <div style={{ fontSize: 13, color: "#6B7280", marginTop: 4 }}>Extracting diagnoses, validating codes, and checking MEAT documentation</div>
          <div style={{ fontSize: 12, color: "#9CA3AF", marginTop: 12 }}>This typically takes 60–90 seconds for complex notes</div>
        </div>
      )}

      {/* ══════════════ RESULTS ══════════════ */}
      {result && !analyzing && (
        <div>
          {/* Summary Stats */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}>
            {[
              { label: "Diagnoses", value: diagnoses.length, icon: <FileText size={18} />, color: "#3B82F6", bg: "#EFF6FF" },
              { label: "HCC Codes", value: hccCount, icon: <ShieldCheck size={18} />, color: "#10B981", bg: "#ECFDF5" },
              { label: "Confidence", value: `${Math.round(confidence * 100)}%`, icon: <TrendingUp size={18} />, color: confidence >= 0.7 ? "#10B981" : "#F59E0B", bg: confidence >= 0.7 ? "#ECFDF5" : "#FFFBEB" },
              { label: "MEAT Score", value: `${meatCount}/${meatTotal}`, icon: <Sparkles size={18} />, color: "#8B5CF6", bg: "#F5F3FF" },
            ].map((s, i) => (
              <div key={i} style={{ ...card, padding: "16px 18px", display: "flex", alignItems: "center", gap: 14 }}>
                <div style={{ width: 40, height: 40, borderRadius: 10, background: s.bg, display: "flex", alignItems: "center", justifyContent: "center", color: s.color }}>
                  {s.icon}
                </div>
                <div>
                  <div style={{ fontSize: 22, fontWeight: 700, color: "#111827", lineHeight: 1 }}>{s.value}</div>
                  <div style={{ fontSize: 12, color: "#6B7280", marginTop: 2 }}>{s.label}</div>
                </div>
              </div>
            ))}
          </div>

          {/* Routing Banner */}
          {routing && (
            <div style={{
              ...card,
              padding: "12px 18px",
              marginBottom: 20,
              display: "flex",
              alignItems: "center",
              gap: 10,
              borderLeft: `4px solid ${confidence >= 0.85 ? "#10B981" : confidence >= 0.6 ? "#F59E0B" : "#EF4444"}`,
            }}>
              {confidence >= 0.85 ? <CheckCircle2 size={18} color="#10B981" /> : confidence >= 0.6 ? <AlertTriangle size={18} color="#F59E0B" /> : <XCircle size={18} color="#EF4444" />}
              <div style={{ flex: 1 }}>
                <span style={{ fontSize: 14, fontWeight: 600, color: "#111827" }}>
                  {confidence >= 0.85 ? "Auto-Accept" : confidence >= 0.6 ? "Needs Review" : "Full Audit Required"}
                </span>
                <span style={{ fontSize: 13, color: "#6B7280", marginLeft: 8 }}>
                  Overall confidence: {Math.round(confidence * 100)}%
                </span>
              </div>
            </div>
          )}

          {/* Diagnoses Table */}
          {diagnoses.length > 0 && (
            <div style={{ ...card, marginBottom: 20 }}>
              <div style={{ padding: "14px 18px", borderBottom: "1px solid #F3F4F6", display: "flex", alignItems: "center", gap: 8 }}>
                <FileText size={16} color="#374151" />
                <span style={{ fontSize: 15, fontWeight: 700, color: "#111827" }}>Extracted Diagnoses</span>
                <span style={{ fontSize: 12, fontWeight: 600, background: "#EFF6FF", color: "#2563EB", padding: "2px 8px", borderRadius: 10 }}>
                  {diagnoses.length}
                </span>
              </div>
              <div style={{ overflowX: "auto" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
                  <thead>
                    <tr style={{ background: "#F9FAFB", borderBottom: "1px solid #E5E7EB" }}>
                      <th style={{ width: 32, padding: "10px 8px" }} />
                      <th style={{ padding: "10px 12px", textAlign: "left", fontWeight: 600, color: "#6B7280", fontSize: 12, textTransform: "uppercase", letterSpacing: "0.05em" }}>ICD-10</th>
                      <th style={{ padding: "10px 12px", textAlign: "left", fontWeight: 600, color: "#6B7280", fontSize: 12, textTransform: "uppercase", letterSpacing: "0.05em" }}>Description</th>
                      <th style={{ padding: "10px 12px", textAlign: "left", fontWeight: 600, color: "#6B7280", fontSize: 12, textTransform: "uppercase", letterSpacing: "0.05em" }}>HCC</th>
                      <th style={{ padding: "10px 12px", textAlign: "right", fontWeight: 600, color: "#6B7280", fontSize: 12, textTransform: "uppercase", letterSpacing: "0.05em" }}>Coeff</th>
                      <th style={{ padding: "10px 12px", textAlign: "left", fontWeight: 600, color: "#6B7280", fontSize: 12, textTransform: "uppercase", letterSpacing: "0.05em", minWidth: 120 }}>Confidence</th>
                      <th style={{ padding: "10px 12px", textAlign: "left", fontWeight: 600, color: "#6B7280", fontSize: 12, textTransform: "uppercase", letterSpacing: "0.05em" }}>MEAT</th>
                    </tr>
                  </thead>
                  <tbody>
                    {diagnoses.map((dx, i) => {
                      const hcc = dxHcc(dx);
                      const exp = expandedRows.has(i);
                      return (
                        <Fragment key={i}>
                          <tr
                            onClick={() => toggle(i)}
                            style={{
                              cursor: "pointer",
                              borderBottom: "1px solid #F3F4F6",
                              borderLeft: hcc ? "3px solid #3B82F6" : "3px solid transparent",
                              transition: "background 0.1s",
                            }}
                            onMouseEnter={(e) => (e.currentTarget.style.background = "#F9FAFB")}
                            onMouseLeave={(e) => (e.currentTarget.style.background = "")}
                          >
                            <td style={{ padding: "10px 8px", textAlign: "center" }}>
                              {exp ? <ChevronDown size={14} color="#9CA3AF" /> : <ChevronRight size={14} color="#9CA3AF" />}
                            </td>
                            <td style={{ padding: "10px 12px" }}>
                              <code style={{ fontSize: 12, fontWeight: 700, background: "#F3F4F6", padding: "3px 7px", borderRadius: 4 }}>{dxIcd10(dx)}</code>
                            </td>
                            <td style={{ padding: "10px 12px", fontWeight: 500, color: "#111827", maxWidth: 280 }}>
                              <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{dxCondition(dx)}</div>
                            </td>
                            <td style={{ padding: "10px 12px" }}>
                              {hcc ? (
                                <span style={{ fontSize: 11, fontWeight: 700, background: "#DBEAFE", color: "#1D4ED8", padding: "3px 8px", borderRadius: 6 }}>{hcc}</span>
                              ) : (
                                <span style={{ color: "#D1D5DB" }}>—</span>
                              )}
                            </td>
                            <td style={{ padding: "10px 12px", textAlign: "right", fontFamily: "monospace", fontWeight: 600, color: "#374151" }}>
                              {dxCoeff(dx) != null ? dxCoeff(dx)!.toFixed(3) : "—"}
                            </td>
                            <td style={{ padding: "10px 12px" }}><ConfBar value={dx.confidence} /></td>
                            <td style={{ padding: "10px 12px" }}><MeatDots dx={dx} /></td>
                          </tr>
                          {exp && (
                            <tr style={{ background: "#F8FAFC" }}>
                              <td colSpan={7} style={{ padding: "14px 20px 14px 48px" }}>
                                {dx.supporting_text && (
                                  <div style={{ marginBottom: 12 }}>
                                    <span style={{ fontSize: 12, fontWeight: 600, color: "#6B7280" }}>Evidence: </span>
                                    <span style={{ fontSize: 13, color: "#374151", fontStyle: "italic" }}>&ldquo;{dx.supporting_text}&rdquo;</span>
                                  </div>
                                )}
                                <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
                                  {(["monitoring", "evaluation", "assessment", "treatment"] as const).map((k) => {
                                    const v = meatVal(dx, k);
                                    return (
                                      <div key={k}>
                                        <div style={{ fontSize: 11, fontWeight: 700, color: "#6B7280", textTransform: "uppercase", marginBottom: 3 }}>{k}</div>
                                        <div style={{ fontSize: 12, color: v ? "#374151" : "#D1D5DB", fontStyle: v ? "normal" : "italic" }}>
                                          {v || "Not documented"}
                                        </div>
                                      </div>
                                    );
                                  })}
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Suspect Conditions */}
          {suspects.length > 0 && (
            <div style={{ ...card, marginBottom: 20 }}>
              <div style={{ padding: "14px 18px", borderBottom: "1px solid #F3F4F6", display: "flex", alignItems: "center", gap: 8 }}>
                <AlertTriangle size={16} color="#F59E0B" />
                <span style={{ fontSize: 15, fontWeight: 700, color: "#111827" }}>Suspect Conditions</span>
                <span style={{ fontSize: 12, fontWeight: 600, background: "#FFFBEB", color: "#D97706", padding: "2px 8px", borderRadius: 10 }}>
                  {suspects.length}
                </span>
              </div>
              {suspects.map((s, i) => (
                <div key={i} style={{ padding: "14px 18px", borderBottom: "1px solid #F3F4F6", display: "flex", alignItems: "center", gap: 14 }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 14, fontWeight: 600, color: "#111827" }}>{s.condition || "Unknown"}</span>
                      <code style={{ fontSize: 11, fontWeight: 700, background: "#F3F4F6", padding: "2px 6px", borderRadius: 4 }}>{suspIcd(s)}</code>
                      {(s.hcc_code || s.suspect_hcc) && (
                        <span style={{ fontSize: 11, fontWeight: 700, background: "#DBEAFE", color: "#1D4ED8", padding: "2px 7px", borderRadius: 5 }}>
                          {s.hcc_code || s.suspect_hcc}
                        </span>
                      )}
                    </div>
                    {suspEvidence(s) && (
                      <div style={{ fontSize: 12, color: "#6B7280", marginTop: 4, lineHeight: 1.5 }}>{suspEvidence(s)}</div>
                    )}
                  </div>
                  <div style={{ width: 110, flexShrink: 0 }}><ConfBar value={suspConf(s)} /></div>
                </div>
              ))}
            </div>
          )}

          {/* Pipeline Details (collapsible) */}
          {meta && (
            <div style={card}>
              <button
                onClick={() => setPipelineOpen(!pipelineOpen)}
                style={{
                  width: "100%",
                  padding: "14px 18px",
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  borderBottom: pipelineOpen ? "1px solid #F3F4F6" : "none",
                }}
              >
                <Clock size={16} color="#6B7280" />
                <span style={{ fontSize: 14, fontWeight: 600, color: "#374151" }}>Pipeline Details</span>
                <ChevronDown size={14} color="#9CA3AF" style={{ marginLeft: "auto", transform: pipelineOpen ? "none" : "rotate(-90deg)", transition: "transform 0.2s" }} />
              </button>
              {pipelineOpen && (
                <div style={{ padding: "16px 18px" }}>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 16 }}>
                    {meta.pipeline_version && (
                      <div>
                        <div style={{ fontSize: 11, fontWeight: 700, color: "#9CA3AF", textTransform: "uppercase", marginBottom: 4 }}>Version</div>
                        <div style={{ fontSize: 13, fontFamily: "monospace", color: "#374151" }}>{meta.pipeline_version}</div>
                      </div>
                    )}
                    {meta.total_time_seconds != null && (
                      <div>
                        <div style={{ fontSize: 11, fontWeight: 700, color: "#9CA3AF", textTransform: "uppercase", marginBottom: 4 }}>Total Time</div>
                        <div style={{ fontSize: 13, fontFamily: "monospace", color: "#374151" }}>{meta.total_time_seconds.toFixed(1)}s</div>
                      </div>
                    )}
                    {meta.turns != null && (
                      <div>
                        <div style={{ fontSize: 11, fontWeight: 700, color: "#9CA3AF", textTransform: "uppercase", marginBottom: 4 }}>Turns</div>
                        <div style={{ fontSize: 13, fontFamily: "monospace", color: "#374151" }}>{meta.turns}</div>
                      </div>
                    )}
                  </div>
                  {(meta.stages?.length ?? 0) > 0 && (
                    <div style={{ marginTop: 14 }}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: "#9CA3AF", textTransform: "uppercase", marginBottom: 6 }}>Stages</div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                        {meta.stages!.map((s: string, i: number) => (
                          <span key={i} style={{ fontSize: 11, fontFamily: "monospace", padding: "3px 8px", borderRadius: 5, border: "1px solid #E5E7EB", color: "#6B7280" }}>{s}</span>
                        ))}
                      </div>
                    </div>
                  )}
                  {meta.timings && Object.keys(meta.timings).length > 0 && (
                    <div style={{ marginTop: 14 }}>
                      <div style={{ fontSize: 11, fontWeight: 700, color: "#9CA3AF", textTransform: "uppercase", marginBottom: 6 }}>Timing</div>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 6 }}>
                        {Object.entries(meta.timings).map(([k, v]) => (
                          <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "5px 10px", borderRadius: 6, background: "#F9FAFB", fontSize: 12 }}>
                            <span style={{ fontFamily: "monospace", color: "#6B7280" }}>{k}</span>
                            <span style={{ fontFamily: "monospace", fontWeight: 600, color: "#374151" }}>
                              {typeof v === "number" ? `${(v as number).toFixed(2)}s` : String(v)}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Coding Notes */}
          {result.coding_notes && (
            <div style={{ ...cardDark, padding: "16px 18px", marginTop: 20 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#374151", marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
                <FileText size={14} /> Coding Notes
              </div>
              <div style={{ fontSize: 13, color: "#6B7280", lineHeight: 1.7, whiteSpace: "pre-wrap" }}>{result.coding_notes}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
