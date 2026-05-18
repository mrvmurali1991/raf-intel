"use client";

import { useState, useMemo, Fragment } from "react";
import dynamic from "next/dynamic";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  getPatients,
  analyzeNote,
  analyzeEncounter,
  getPatientEncounters,
} from "@/lib/api";
import type { AnalysisResult, AIDiagnosis, AISuspect, Patient } from "@/types";
import { useToast } from "@/components/Toast";
import { tokens } from "@/styles/tokens";
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
  ClipboardPaste,
  ListChecks,
  ShieldCheck,
  TrendingUp,
  Sparkles,
  RotateCcw,
  User,
  Brain,
  Microscope,
} from "lucide-react";

// ── Dynamic import: defer heavy results panel until analysis completes (~40 kB) ──
const AnalysisResultsPanel = dynamic(
  () => import("./AnalysisResultsPanel"),
  {
    ssr: false,
    loading: () => (
      <div className="premium-card shimmer" style={{ height: 200, borderRadius: 12, marginTop: 8 }} />
    ),
  }
);

/* ───────────────────────── helpers ───────────────────────── */

function dxCondition(dx: AIDiagnosis): string {
  return dx.condition || dx.description || "Unknown condition";
}
function dxIcd10(dx: AIDiagnosis): string {
  return dx.icd10_code || dx.icd10 || "—";
}
function dxHcc(dx: AIDiagnosis): string | null | undefined {
  return dx.hcc_code || dx.hcc || dx.hcc_mapping?.hcc_code;
}
function dxCoeff(dx: AIDiagnosis): number | undefined {
  return dx.hcc_weight || dx.hcc_mapping?.coefficient;
}
function meatVal(
  dx: AIDiagnosis,
  key: "monitoring" | "evaluation" | "assessment" | "treatment"
): string {
  const short = { monitoring: "M", evaluation: "E", assessment: "A", treatment: "T" }[key] as "M" | "E" | "A" | "T";
  return dx.meat?.[key] || dx.meat?.[short] || "";
}
function suspIcd(s: AISuspect): string {
  return s.icd10_code || s.suspect_icd10 || s.icd10 || "—";
}
function suspConf(s: AISuspect): number {
  return s.confidence_score ?? s.confidence ?? 0;
}
function suspEvidence(s: AISuspect): string {
  return s.rationale || s.evidence || "";
}

function queryErrorMessage(error: unknown): string {
  return (
    (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
    (error as { message?: string })?.message ??
    "Something went wrong"
  );
}

function QueryLoading({ label }: { label: string }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: 16,
        color: tokens.slate500,
        fontSize: 14,
        border: `1px solid ${tokens.slate200}`,
        borderRadius: 10,
        background: tokens.slate50,
      }}
    >
      <Loader2 size={16} className="animate-spin" /> {label}
    </div>
  );
}

function QueryError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "12px 14px",
        borderRadius: 10,
        border: `1px solid ${tokens.riskHigh}33`,
        background: tokens.riskHighSoft,
        color: tokens.slate700,
        fontSize: 13,
      }}
    >
      <AlertTriangle size={16} color={tokens.riskHigh} style={{ flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 700, color: tokens.riskHigh, marginBottom: 2 }}>
          Failed to load
        </div>
        <div className="text-muted-foreground" style={{ wordBreak: "break-word" }}>
          {queryErrorMessage(error)}
        </div>
      </div>
      <button
        onClick={onRetry}
        style={{
          padding: "6px 12px",
          fontSize: 12,
          fontWeight: 600,
          borderRadius: 8,
          border: `1px solid ${tokens.riskHigh}`,
          background: `hsl(var(--card))`,
          color: tokens.riskHigh,
          cursor: "pointer",
          flexShrink: 0,
        }}
      >
        Retry
      </button>
    </div>
  );
}

/* ───────────────────────── sub-components ───────────────────────── */

function MeatPills({ dx }: { dx: AIDiagnosis }) {
  const keys = ["monitoring", "evaluation", "assessment", "treatment"] as const;
  const labels = ["M", "E", "A", "T"];
  const colors = [tokens.infoBlue, tokens.accentPurple, tokens.warningStrong, tokens.success];
  const bgColors = [tokens.primarySoft.replace("0.08", "0.12"), tokens.primarySoft, tokens.warningSoft, tokens.successSoft];
  return (
    <div style={{ display: "flex", gap: 5 }}>
      {keys.map((k, i) => {
        const present = !!meatVal(dx, k);
        return (
          <div
            key={k}
            title={`${labels[i]}: ${present ? meatVal(dx, k) : "Not documented"}`}
            aria-label={`${k}: ${present ? "documented" : "not documented"}`}
            style={{
              width: 28,
              height: 28,
              borderRadius: 8,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 11,
              fontWeight: 800,
              letterSpacing: "0.02em",
              background: present ? bgColors[i] : tokens.slate100,
              color: present ? colors[i] : tokens.slate300,
              border: `2px solid ${present ? colors[i] + "50" : tokens.slate200}`,
              transition: "all 0.2s ease",
              boxShadow: present ? `0 2px 8px ${colors[i]}20` : "none",
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
  const color = value >= 0.85 ? tokens.success : value >= 0.7 ? tokens.infoBlue : value >= 0.5 ? tokens.warningStrong : tokens.riskHigh;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 110 }}>
      <div style={{ flex: 1, height: 7, borderRadius: 4, background: tokens.slate100, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", borderRadius: 4, background: `linear-gradient(90deg, ${color}CC, ${color})`, transition: "width 0.5s cubic-bezier(0.4, 0, 0.2, 1)" }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 700, color, minWidth: 34, textAlign: "right", fontFamily: "monospace" }}>{pct}%</span>
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
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", borderRadius: 10, border: `1px solid ${tokens.slate200}`, background: tokens.slate50 }}>
        <div style={{ width: 32, height: 32, borderRadius: "50%", background: tokens.primarySoft, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <User size={14} color={tokens.primary} />
        </div>
        <div style={{ flex: 1 }}>
          <div className="text-foreground" style={{ fontSize: 14, fontWeight: 600 }}>{name(selected)}</div>
          <div className="text-muted-foreground" style={{ fontSize: 12 }}>PID: {selected.pid}</div>
        </div>
        <button onClick={() => { onSelect(null); setQ(""); }} aria-label="Change patient selection" style={{ fontSize: 12, color: tokens.primary, fontWeight: 600, background: "none", border: "none", cursor: "pointer" }}>
          Change
        </button>
      </div>
    );
  }

  return (
    <div style={{ position: "relative" }}>
      <div style={{ position: "relative" }}>
        <Search size={16} style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: tokens.slate400 }} />
        <input
          placeholder={loading ? "Loading patients..." : "Search patient by name or PID..."}
          value={q}
          onChange={(e) => { setQ(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          disabled={loading}
          style={{ width: "100%", padding: "10px 12px 10px 38px", fontSize: 14, borderRadius: 10, border: `1px solid hsl(var(--border))`, background: `hsl(var(--card))`, color: `hsl(var(--foreground))`, transition: "border-color 0.2s, box-shadow 0.2s" }}
        />
      </div>
      {open && filtered.length > 0 && (
        <>
          <div style={{ position: "fixed", inset: 0, zIndex: 40 }} onClick={() => setOpen(false)} />
          <div style={{ position: "absolute", zIndex: 50, top: "100%", marginTop: 4, width: "100%", borderRadius: 12, border: `1px solid hsl(var(--border))`, background: `hsl(var(--card))`, color: `hsl(var(--foreground))`, boxShadow: "0 8px 24px rgba(0,0,0,0.1)", maxHeight: 260, overflowY: "auto" }}>
            {filtered.map((p) => (
              <button
                key={p.pid}
                onClick={() => { onSelect(p); setOpen(false); }}
                style={{ width: "100%", textAlign: "left", padding: "10px 14px", display: "flex", alignItems: "center", gap: 10, fontSize: 14, border: "none", background: "none", cursor: "pointer", borderBottom: `1px solid ${tokens.slate100}` }}
                onMouseEnter={(e) => (e.currentTarget.style.background = tokens.slate50)}
                onMouseLeave={(e) => (e.currentTarget.style.background = "none")}
              >
                <div style={{ width: 28, height: 28, borderRadius: "50%", background: tokens.primarySoft, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: tokens.primary }}>
                  {(p.fname || p.first_name || "").trim()[0] || "\u2022"}
                </div>
                <span style={{ fontWeight: 500 }}>{name(p)}</span>
                <span style={{ marginLeft: "auto", fontSize: 12, color: tokens.slate400 }}>PID {p.pid}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/* ───────────────────────── loading animation ───────────────────────── */

function AnalyzingOverlay() {
  return (
    <div className="premium-card animate-fade-in" style={{ padding: "56px 24px", textAlign: "center", marginTop: 24, position: "relative", overflow: "hidden" }}>
      {/* Shimmer background effect */}
      <div className="shimmer" style={{ position: "absolute", inset: 0, opacity: 0.5 }} />
      <div style={{ position: "relative", zIndex: 1 }}>
        {/* Pulsing brain icon */}
        <div style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 72, height: 72, borderRadius: 20, background: `linear-gradient(135deg, ${tokens.primarySoft}, ${tokens.primarySoft})`, marginBottom: 20 }}>
          <div className="soft-pulse">
            <Brain size={36} style={{ color: tokens.primary }} />
          </div>
        </div>
        <div className="text-foreground" style={{ fontSize: 18, fontWeight: 700, marginBottom: 6 }}>Analyzing Clinical Note</div>
        <div className="text-muted-foreground" style={{ fontSize: 14, marginBottom: 20 }}>Extracting diagnoses, validating codes, and checking MEAT documentation</div>
        {/* Progress steps */}
        <div style={{ display: "inline-flex", gap: 24, padding: "14px 24px", borderRadius: 12, background: tokens.slate50, border: `1px solid ${tokens.slate100}` }}>
          {[
            { icon: <Microscope size={15} />, text: "Parsing" },
            { icon: <Stethoscope size={15} />, text: "Diagnosing" },
            { icon: <ShieldCheck size={15} />, text: "Validating" },
            { icon: <Sparkles size={15} />, text: "Scoring" },
          ].map((step, i) => (
            <div key={`step-${i}`} className={`stagger-${i + 1} text-muted-foreground`} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, fontWeight: 500 }}>
              <div className="soft-pulse" style={{ color: tokens.infoBlue, animationDelay: `${i * 0.4}s` }}>{step.icon}</div>
              {step.text}
            </div>
          ))}
        </div>
        <div className="text-muted-foreground" style={{ fontSize: 12, marginTop: 16 }}>Typically takes 60-90 seconds for complex notes</div>
      </div>
    </div>
  );
}

/* ───────────────────────── section header ───────────────────────── */

function SectionHeader({ icon, title, count, countColor, countBg }: {
  icon: React.ReactNode;
  title: string;
  count?: number;
  countColor?: string;
  countBg?: string;
}) {
  return (
    <div style={{ padding: "16px 20px", borderBottom: `1px solid ${tokens.slate100}`, display: "flex", alignItems: "center", gap: 10 }}>
      <div style={{ width: 32, height: 32, borderRadius: 8, background: countBg || tokens.primarySoft, display: "flex", alignItems: "center", justifyContent: "center" }}>
        {icon}
      </div>
      <span className="text-foreground" style={{ fontSize: 16, fontWeight: 700 }}>{title}</span>
      {count != null && (
        <span style={{ fontSize: 12, fontWeight: 700, background: countBg || tokens.primarySoft, color: countColor || tokens.primary, padding: "3px 10px", borderRadius: 10 }}>
          {count}
        </span>
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
  const [result, setResult] = useState<AnalysisResult | null>(null);

  const currentYear = new Date().getFullYear();

  const patientsQ = useQuery({ queryKey: ["patients"], queryFn: getPatients, staleTime: 5 * 60_000 });
  const {
    isLoading: patientsLoading,
    isError: patientsIsError,
    error: patientsError,
    refetch: refetchPatients,
    data: patientsData,
  } = patientsQ;
  const encountersQ = useQuery({
    queryKey: ["encounters", selectedPatient?.pid, currentYear],
    queryFn: () => getPatientEncounters(selectedPatient?.pid ?? 0, currentYear),
    enabled: !!selectedPatient && mode === "encounter",
  });
  const {
    isLoading: encountersLoading,
    isError: encountersIsError,
    error: encountersError,
    refetch: refetchEncounters,
    data: encountersData,
  } = encountersQ;

  const noteMut = useMutation({
    mutationFn: () => analyzeNote(pastePatientId || "0", noteText),
    onSuccess: (d) => { setResult(d); toast.success("Complete", "Clinical note analyzed"); },
    onError: (e: unknown) => toast.error("Failed", (e as { response?: { data?: { detail?: string } }; message?: string })?.response?.data?.detail ?? (e as { message?: string })?.message ?? "Error"),
  });
  const encMut = useMutation({
    mutationFn: () => {
      if (!selectedEnc) throw new Error("No encounter selected");
      return analyzeEncounter(selectedEnc, true, true);
    },
    onSuccess: (d) => { setResult(d); toast.success("Complete", "Encounter analyzed"); },
    onError: (e: unknown) => toast.error("Failed", (e as { response?: { data?: { detail?: string } }; message?: string })?.response?.data?.detail ?? (e as { message?: string })?.message ?? "Error"),
  });

  const analyzing = noteMut.isPending || encMut.isPending;

  function analyze() {
    setResult(null);
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
  }

  const label: React.CSSProperties = {
    fontSize: 13,
    fontWeight: 600,
    color: tokens.slate700,
    marginBottom: 6,
    display: "block",
  };

  const tabBtn = (active: boolean): string =>
    `inline-flex items-center gap-1.5 px-4 py-2 text-[13px] font-semibold rounded-lg border cursor-pointer transition-all duration-200 ${
      active
        ? "border-blue-500 bg-blue-50 text-blue-600 shadow-sm shadow-blue-500/10"
        : "border-border bg-card text-muted-foreground hover:border-border/80 hover:text-foreground"
    }`;

  return (
    <div className="rci-page-pad-desktop" style={{ maxWidth: 1100, margin: "0 auto", padding: "20px 16px" }}>
      {/* Header */}
      <div className="animate-fade-in" style={{ marginBottom: 32 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 6 }}>
          <div style={{ width: 42, height: 42, borderRadius: 12, background: `linear-gradient(135deg, ${tokens.primarySoft}, ${tokens.primarySoft})`, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 2px 8px rgba(37, 99, 235, 0.15)" }}>
            <Stethoscope size={20} color={tokens.primary} />
          </div>
          <div>
            <h1 className="gradient-text" style={{ fontSize: 24, fontWeight: 800, margin: 0, lineHeight: 1.2 }}>Clinical Note Analysis</h1>
            <p className="text-muted-foreground" style={{ fontSize: 14, margin: 0, marginTop: 2 }}>
              Extract diagnoses, validate HCC codes, and generate MEAT documentation
            </p>
          </div>
        </div>
      </div>

      {/* Input Card */}
      <div className="premium-card premium-shadow" style={{ marginBottom: result ? 28 : 0 }}>
        {/* Mode Tabs */}
        <div style={{ display: "flex", gap: 8, padding: "16px 20px", borderBottom: `1px solid ${tokens.slate100}`, alignItems: "center", flexWrap: "wrap" }}>
          <button onClick={() => setMode("paste")} className={tabBtn(mode === "paste")}>
            <ClipboardPaste size={14} /> Paste Note
          </button>
          <button onClick={() => setMode("encounter")} className={tabBtn(mode === "encounter")}>
            <ListChecks size={14} /> Select Encounter
          </button>
          {result && (
            <button onClick={reset} className={tabBtn(false)} style={{ marginLeft: "auto", fontSize: 12 }}>
              <RotateCcw size={12} /> New Analysis
            </button>
          )}
        </div>

        <div style={{ padding: 22 }}>
          {mode === "paste" ? (
            <div>
              <div style={{ display: "flex", gap: 16, marginBottom: 16 }}>
                <div style={{ flex: "0 0 180px" }}>
                  <label style={label}>Patient ID <span style={{ fontWeight: 400, color: tokens.slate400 }}>(optional)</span></label>
                  <input
                    value={pastePatientId}
                    onChange={(e) => setPastePatientId(e.target.value)}
                    placeholder="e.g. 1"
                    className="focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400"
                    style={{ width: "100%", padding: "9px 12px", fontSize: 14, borderRadius: 10, border: `1px solid ${tokens.slate200}`, transition: "border-color 0.2s, box-shadow 0.2s" }}
                  />
                </div>
              </div>
              <label style={label}>
                <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <FileText size={13} color={tokens.slate500} /> Clinical Note
                </span>
              </label>
              {/* Polished textarea with gutter */}
              <div style={{ position: "relative", borderRadius: 12, border: `1px solid ${tokens.slate200}`, overflow: "hidden", transition: "border-color 0.2s, box-shadow 0.2s" }}
                className="focus-within:ring-2 focus-within:ring-blue-500/20 focus-within:border-blue-400"
              >
                {/* Line number gutter */}
                <div style={{
                  position: "absolute",
                  left: 0,
                  top: 0,
                  bottom: 0,
                  width: 44,
                  background: tokens.slate50,
                  borderRight: `1px solid ${tokens.slate100}`,
                  pointerEvents: "none",
                  zIndex: 1,
                  paddingTop: 12,
                  display: "flex",
                  flexDirection: "column",
                }}>
                  {Array.from({ length: Math.max(noteText.split("\n").length, 12) }, (_, i) => (
                    <div key={i} style={{
                      fontSize: 11,
                      fontFamily: "'SF Mono', 'Monaco', 'Inconsolata', 'Fira Code', monospace",
                      color: tokens.slate300,
                      lineHeight: "22.1px",
                      textAlign: "right",
                      paddingRight: 10,
                      userSelect: "none",
                    }}>
                      {i + 1}
                    </div>
                  ))}
                </div>
                <textarea
                  value={noteText}
                  onChange={(e) => setNoteText(e.target.value)}
                  placeholder="Paste the full clinical note text here..."
                  style={{
                    width: "100%",
                    minHeight: 240,
                    padding: "12px 14px 12px 52px",
                    fontSize: 13,
                    fontFamily: "'SF Mono', 'Monaco', 'Inconsolata', 'Fira Code', monospace",
                    lineHeight: "22.1px",
                    border: "none",
                    background: tokens.slate50,
                    resize: "vertical",
                  }}
                />
              </div>
              {/* Character count */}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 10 }}>
                <button
                  onClick={analyze}
                  disabled={analyzing || !noteText.trim()}
                  className="hover-lift"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "11px 24px",
                    fontSize: 14,
                    fontWeight: 600,
                    borderRadius: 10,
                    border: "none",
                    background: (analyzing || !noteText.trim()) ? tokens.slate300 : `linear-gradient(135deg, ${tokens.primary}, ${tokens.primaryDark})`,
                    color: (analyzing || !noteText.trim()) ? tokens.slate400 : tokens.white,
                    cursor: (analyzing || !noteText.trim()) ? "not-allowed" : "pointer",
                    transition: "all 0.2s",
                    boxShadow: (analyzing || !noteText.trim()) ? "none" : "0 2px 8px rgba(37, 99, 235, 0.3)",
                  }}
                >
                  {analyzing ? <Loader2 size={16} className="animate-spin" /> : <Activity size={16} />}
                  {analyzing ? "Analyzing..." : "Analyze Note"}
                </button>
                <span style={{ fontSize: 12, color: tokens.slate400, fontFamily: "monospace" }}>
                  {noteText.length > 0 ? `${noteText.length.toLocaleString()} chars` : ""}
                </span>
              </div>
            </div>
          ) : (
            <div>
              <label style={label}>Patient</label>
              {patientsLoading ? (
                <QueryLoading label="Loading patients..." />
              ) : patientsIsError ? (
                <QueryError error={patientsError} onRetry={() => refetchPatients()} />
              ) : (
                <PatientDropdown
                  patients={patientsData ?? []}
                  loading={false}
                  selected={selectedPatient}
                  onSelect={(p) => { setSelectedPatient(p); setSelectedEnc(null); }}
                />
              )}

              {selectedPatient && (
                <div style={{ marginTop: 16 }}>
                  <label style={label}>Encounters</label>
                  {encountersLoading ? (
                    <QueryLoading label="Loading encounters..." />
                  ) : encountersIsError ? (
                    <QueryError error={encountersError} onRetry={() => refetchEncounters()} />
                  ) : encountersData?.encounters?.length ? (
                    <div style={{ border: `1px solid ${tokens.slate200}`, borderRadius: 10, maxHeight: 240, overflowY: "auto" }}>
                      {(encountersData?.encounters ?? []).map((enc) => (
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
                            background: selectedEnc === enc.encounter_id ? tokens.primarySoft : "transparent",
                            borderLeft: selectedEnc === enc.encounter_id ? `3px solid ${tokens.primary}` : "3px solid transparent",
                            borderBottom: `1px solid ${tokens.slate100}`,
                            borderTop: "none",
                            borderRight: "none",
                            cursor: "pointer",
                            fontSize: 14,
                            transition: "background 0.15s",
                          }}
                        >
                          <div style={{ flex: 1 }}>
                            <div className="text-foreground" style={{ fontWeight: 600 }}>Encounter #{enc.encounter_id}</div>
                            <div className="text-muted-foreground" style={{ fontSize: 12, marginTop: 2 }}>{enc.reason || "No reason recorded"}</div>
                          </div>
                          <div style={{ textAlign: "right" }}>
                            <div className="text-muted-foreground" style={{ fontSize: 12 }}>{enc.date}</div>
                            {enc.provider_lname && <div style={{ fontSize: 11, color: tokens.slate400 }}>Dr. {enc.provider_lname}</div>}
                          </div>
                          {selectedEnc === enc.encounter_id && <CheckCircle2 size={16} color={tokens.primary} />}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <p style={{ fontSize: 14, color: tokens.slate400, padding: 16 }}>No encounters found for this patient this year. Try the Paste Note tab to analyze a clinical note directly.</p>
                  )}
                </div>
              )}

              <div style={{ marginTop: 16 }}>
                <button
                  onClick={analyze}
                  disabled={analyzing || !selectedEnc}
                  className="hover-lift"
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "11px 24px",
                    fontSize: 14,
                    fontWeight: 600,
                    borderRadius: 10,
                    border: "none",
                    background: (analyzing || !selectedEnc) ? tokens.slate300 : `linear-gradient(135deg, ${tokens.primary}, ${tokens.primaryDark})`,
                    color: (analyzing || !selectedEnc) ? tokens.slate400 : tokens.white,
                    cursor: (analyzing || !selectedEnc) ? "not-allowed" : "pointer",
                    transition: "all 0.2s",
                    boxShadow: (analyzing || !selectedEnc) ? "none" : "0 2px 8px rgba(37, 99, 235, 0.3)",
                  }}
                >
                  {analyzing ? <Loader2 size={16} className="animate-spin" /> : <Activity size={16} />}
                  {analyzing ? "Analyzing..." : "Analyze Encounter"}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Analyzing State */}
      {analyzing && <AnalyzingOverlay />}

      {/* ══════════════ RESULTS ══════════════ */}
      {result && !analyzing && (
        // AnalysisResultsPanel is dynamically imported — deferred ~40 kB of
        // diagnoses table, MEAT grid, suspects list, and pipeline details.
        <AnalysisResultsPanel result={result} />
      )}
    </div>
  );
}