"use client";

import React, { useState } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

export type SweepPeriod = "initial" | "midyear" | "final" | "none";
export type PlanType    = "MA" | "PACE" | "FIDE_SNP" | "SNP" | "MAPD";

export interface ADLData {
  bathing:      boolean;
  dressing:     boolean;
  eating:       boolean;
  toileting:    boolean;
  transferring: boolean;
  continence:   boolean;
}

export interface AdvancedRAFOptions {
  enrollmentMonths: number;
  sweepPeriod:      SweepPeriod | null;
  planType:         PlanType;
  adlData:          ADLData | null;
  orec:             "0" | "1" | "2" | "3";
}

interface Props {
  onChange?: (options: AdvancedRAFOptions) => void;
  onCalculate?: (options: AdvancedRAFOptions) => void;
  isCalculating?: boolean;
  rafResult?: {
    raf_score?: number;
    frailty_addend?: number;
    is_new_enrollee?: boolean;
    model_segment?: string;
    sweep_period?: string;
    v24_score?: number;
    v28_score?: number;
    hcc_count?: number;
  } | null;
}

const ADL_LABELS: { key: keyof ADLData; label: string; icon: string }[] = [
  { key: "bathing",      label: "Bathing",      icon: "🚿" },
  { key: "dressing",     label: "Dressing",     icon: "👔" },
  { key: "eating",       label: "Eating",       icon: "🍽️" },
  { key: "toileting",    label: "Toileting",    icon: "🚽" },
  { key: "transferring", label: "Transferring", icon: "🛏️" },
  { key: "continence",   label: "Continence",   icon: "💊" },
];

const SWEEP_OPTIONS: { value: SweepPeriod; label: string; badge: string; desc: string }[] = [
  { value: "none",    label: "No Filter",   badge: "—",    desc: "All year ICD codes included" },
  { value: "initial", label: "Initial",     badge: "Q1",   desc: "Jan–Mar date-of-service window" },
  { value: "midyear", label: "Midyear",     badge: "H1",   desc: "Jan–Jun date-of-service window" },
  { value: "final",   label: "Final",       badge: "Full", desc: "Full year date-of-service window" },
];

const PLAN_OPTIONS: { value: PlanType; label: string; desc: string }[] = [
  { value: "MA",       label: "Medicare Advantage",   desc: "Standard MA — no frailty adjustment" },
  { value: "MAPD",     label: "MA + Part D",          desc: "MAPD plan — no frailty adjustment" },
  { value: "SNP",      label: "Special Needs Plan",   desc: "Chronic/Dual SNP — no frailty" },
  { value: "FIDE_SNP", label: "FIDE-SNP",             desc: "Frailty eligible when ≥3 ADLs" },
  { value: "PACE",     label: "PACE",                 desc: "Frailty eligible when ≥3 ADLs" },
];

const OREC_OPTIONS = [
  { value: "0", label: "Aged (not disabled)",       badge: "0" },
  { value: "1", label: "Disabled",                  badge: "1" },
  { value: "2", label: "ESRD",                      badge: "2" },
  { value: "3", label: "Disabled + ESRD",           badge: "3" },
];

const DEFAULT_ADL: ADLData = {
  bathing: false, dressing: false, eating: false,
  toileting: false, transferring: false, continence: false,
};

// ─── Component ────────────────────────────────────────────────────────────────

export function AdvancedRAFPanel({ onChange, onCalculate, isCalculating, rafResult }: Props) {
  const [enrollmentMonths, setEnrollmentMonths] = useState(12);
  const [sweepPeriod, setSweepPeriod]           = useState<SweepPeriod>("none");
  const [planType, setPlanType]                 = useState<PlanType>("MA");
  const [orec, setOrec]                         = useState<"0"|"1"|"2"|"3">("0");
  const [adlData, setAdlData]                   = useState<ADLData>({ ...DEFAULT_ADL });
  const [showADL, setShowADL]                   = useState(false);

  const isFrailtyEligible = planType === "PACE" || planType === "FIDE_SNP";
  const isNewEnrollee     = enrollmentMonths < 12;
  const isESRD            = orec === "2" || orec === "3";
  const adlCount          = Object.values(adlData).filter(Boolean).length;
  const isFrail           = isFrailtyEligible && adlCount >= 3;

  function toggleADL(key: keyof ADLData) {
    const next = { ...adlData, [key]: !adlData[key] };
    setAdlData(next);
    const opts = buildOptions(next);
    onChange?.(opts);
  }

  function buildOptions(adl = adlData): AdvancedRAFOptions {
    return {
      enrollmentMonths,
      sweepPeriod: sweepPeriod === "none" ? null : sweepPeriod,
      planType,
      orec,
      adlData: isFrailtyEligible ? adl : null,
    };
  }

  function handleChange<T>(setter: React.Dispatch<React.SetStateAction<T>>, val: T) {
    setter(val);
    // Use setTimeout to allow state to update before reading
    setTimeout(() => onChange?.(buildOptions()), 0);
  }

  function handleCalculate() {
    onCalculate?.(buildOptions());
  }

  return (
    <div style={styles.container}>
      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div style={styles.header}>
        <div>
          <h3 style={styles.title}>Advanced RAF Options</h3>
          <p style={styles.subtitle}>CMS-compliant model routing, sweep periods & frailty</p>
        </div>
        <div style={styles.badges}>
          {isNewEnrollee && <Chip color="#7c3aed" bg="#ede9fe">NE Model</Chip>}
          {isESRD        && <Chip color="#d97706" bg="#fef3c7">ESRD Routing</Chip>}
          {isFrail       && <Chip color="#059669" bg="#d1fae5">Frailty Eligible</Chip>}
        </div>
      </div>

      {/* ── Enrollment Months ────────────────────────────────────────────────── */}
      <Section title="Enrollment Months" icon="📅">
        <p style={styles.fieldDesc}>
          Months of Part B coverage this year.{" "}
          <strong style={{ color: isNewEnrollee ? "#7c3aed" : "#6b7280" }}>
            {isNewEnrollee
              ? `New Enrollee model (${enrollmentMonths} months) — demographic-only`
              : "Full HCC model applies"}
          </strong>
        </p>
        <div style={styles.sliderWrap}>
          <input
            id="enrollment-months"
            type="range" min={1} max={12} value={enrollmentMonths}
            onChange={e => handleChange(setEnrollmentMonths, Number(e.target.value))}
            style={styles.slider}
          />
          <span style={{ ...styles.sliderValue, color: isNewEnrollee ? "#7c3aed" : "#374151" }}>
            {enrollmentMonths} mo
          </span>
        </div>
        <div style={styles.monthPips}>
          {Array.from({ length: 12 }, (_, i) => i + 1).map(m => (
            <div key={m}
              style={{
                ...styles.pip,
                background: m <= enrollmentMonths ? "#7c3aed" : "#e5e7eb",
                opacity: m === 12 ? 1 : undefined,
              }}
              title={`${m} month${m > 1 ? "s" : ""}`}
            />
          ))}
        </div>
        {isNewEnrollee && (
          <div style={styles.infoBox}>
            ℹ️ Patients with &lt;12 months Part B coverage use the <strong>New Enrollee (NE)</strong> demographic-only
            model. HCC codes are ignored; only age/sex/dual-status factors apply.
          </div>
        )}
      </Section>

      {/* ── OREC / ESRD ──────────────────────────────────────────────────────── */}
      <Section title="Original Reason for Entitlement (OREC)" icon="🏥">
        <p style={styles.fieldDesc}>Drives model segment routing (Community/Institutional/ESRD).</p>
        <div style={styles.buttonGroup}>
          {OREC_OPTIONS.map(o => (
            <button key={o.value} id={`orec-${o.value}`}
              onClick={() => handleChange(setOrec, o.value as any)}
              style={{
                ...styles.segBtn,
                ...(orec === o.value ? styles.segBtnActive : {}),
                borderColor: orec === o.value
                  ? (isESRD ? "#d97706" : "#6366f1")
                  : "#d1d5db",
              }}>
              <span style={styles.badgeCircle}>{o.badge}</span>
              {o.label}
            </button>
          ))}
        </div>
        {isESRD && (
          <div style={{ ...styles.infoBox, borderColor: "#fbbf24", background: "#fffbeb" }}>
            🏥 OREC {orec} — Patient will be routed to <strong>ESRD</strong> segment:
            ESRD_DLY (dialysis), ESRD_FG (graft), or ESRD_NE (new enrollee).
          </div>
        )}
      </Section>

      {/* ── Sweep Period ─────────────────────────────────────────────────────── */}
      <Section title="CMS Sweep Period" icon="📋">
        <p style={styles.fieldDesc}>Filter ICD codes by CMS date-of-service window.</p>
        <div style={styles.sweepGrid}>
          {SWEEP_OPTIONS.map(sw => (
            <button key={sw.value} id={`sweep-${sw.value}`}
              onClick={() => handleChange(setSweepPeriod, sw.value)}
              style={{
                ...styles.sweepCard,
                ...(sweepPeriod === sw.value ? styles.sweepCardActive : {}),
              }}>
              <div style={styles.sweepBadge}>{sw.badge}</div>
              <div style={styles.sweepLabel}>{sw.label}</div>
              <div style={styles.sweepDesc}>{sw.desc}</div>
            </button>
          ))}
        </div>
      </Section>

      {/* ── Plan Type ────────────────────────────────────────────────────────── */}
      <Section title="Plan Type" icon="💼">
        <p style={styles.fieldDesc}>
          PACE and FIDE-SNP plans receive a <strong>frailty addend</strong> when ≥3 ADLs impaired.
        </p>
        <div style={styles.buttonGroup}>
          {PLAN_OPTIONS.map(p => (
            <button key={p.value} id={`plan-${p.value}`}
              onClick={() => {
                handleChange(setPlanType, p.value as PlanType);
                if (p.value === "PACE" || p.value === "FIDE_SNP") setShowADL(true);
              }}
              title={p.desc}
              style={{
                ...styles.segBtn,
                ...(planType === p.value ? styles.segBtnActive : {}),
                borderColor: planType === p.value
                  ? (isFrailtyEligible ? "#059669" : "#6366f1")
                  : "#d1d5db",
              }}>
              {p.label}
            </button>
          ))}
        </div>
      </Section>

      {/* ── ADL Assessment ──────────────────────────────────────────────────── */}
      {isFrailtyEligible && (
        <Section title={`ADL Frailty Assessment (${adlCount}/6 impaired${isFrail ? " ✓ Frailty" : ""})`}
          icon="🧓"
          highlight={isFrail}>
          <p style={styles.fieldDesc}>
            Mark impaired Activities of Daily Living. CMS frailty threshold is <strong>≥3 impairments</strong>.
          </p>
          <div style={styles.adlGrid}>
            {ADL_LABELS.map(({ key, label, icon }) => {
              const checked = adlData[key];
              return (
                <button key={key} id={`adl-${key}`}
                  onClick={() => toggleADL(key)}
                  style={{
                    ...styles.adlCard,
                    ...(checked ? styles.adlCardChecked : {}),
                  }}>
                  <div style={styles.adlCheckbox}>
                    {checked && <span>✓</span>}
                  </div>
                  <span style={styles.adlIcon}>{icon}</span>
                  <span style={styles.adlLabel}>{label}</span>
                </button>
              );
            })}
          </div>
          {isFrail && (
            <div style={{ ...styles.infoBox, borderColor: "#34d399", background: "#f0fdf4" }}>
              ✅ <strong>Frailty designated</strong> — {adlCount} ADL impairments meet CMS ≥3 threshold.
              A frailty addend will be applied to the RAF score for this {planType} enrollee.
            </div>
          )}
          {!isFrail && adlCount > 0 && (
            <div style={{ ...styles.infoBox, borderColor: "#fbbf24", background: "#fffbeb" }}>
              ⚠️ {adlCount} ADL impairment{adlCount > 1 ? "s" : ""} documented —
              need {3 - adlCount} more to reach CMS frailty threshold for {planType}.
            </div>
          )}
        </Section>
      )}

      {/* ── RAF Result Summary ───────────────────────────────────────────────── */}
      {rafResult && (
        <div style={styles.resultBox}>
          <div style={styles.resultHeader}>Calculation Result</div>
          <div style={styles.resultGrid}>
            <ResultStat label="Final RAF" value={rafResult.raf_score?.toFixed(4) ?? "—"} accent />
            <ResultStat label="V24 Score"  value={rafResult.v24_score?.toFixed(4) ?? "—"} />
            <ResultStat label="V28 Score"  value={rafResult.v28_score?.toFixed(4) ?? "—"} />
            <ResultStat label="HCCs"       value={String(rafResult.hcc_count ?? "—")} />
            <ResultStat label="Segment"    value={rafResult.model_segment ?? "—"} />
            {rafResult.frailty_addend != null && rafResult.frailty_addend > 0 && (
              <ResultStat label="Frailty Addend" value={`+${rafResult.frailty_addend.toFixed(4)}`} color="#059669" />
            )}
            {rafResult.is_new_enrollee && (
              <ResultStat label="Model" value="New Enrollee (NE)" color="#7c3aed" />
            )}
          </div>
        </div>
      )}

      {/* ── Calculate Button ─────────────────────────────────────────────────── */}
      <button id="adv-raf-calculate"
        onClick={handleCalculate}
        disabled={isCalculating}
        style={{ ...styles.calcBtn, opacity: isCalculating ? 0.7 : 1 }}>
        {isCalculating ? (
          <><span style={styles.spinner} /> Calculating…</>
        ) : (
          "Calculate RAF Score"
        )}
      </button>
    </div>
  );
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function Section({ title, icon, children, highlight }: {
  title: string; icon: string; children: React.ReactNode; highlight?: boolean;
}) {
  return (
    <div style={{
      ...styles.section,
      borderColor: highlight ? "#34d399" : "#e5e7eb",
      background:  highlight ? "#f0fdf4" : "#fff",
    }}>
      <div style={styles.sectionTitle}>
        <span>{icon}</span> {title}
      </div>
      {children}
    </div>
  );
}

function Chip({ children, color, bg }: { children: React.ReactNode; color: string; bg: string }) {
  return (
    <span style={{ ...styles.chip, color, background: bg, border: `1px solid ${color}` }}>
      {children}
    </span>
  );
}

function ResultStat({ label, value, accent, color }: {
  label: string; value: string; accent?: boolean; color?: string;
}) {
  return (
    <div style={styles.resultStat}>
      <div style={styles.resultStatLabel}>{label}</div>
      <div style={{
        ...styles.resultStatValue,
        ...(accent ? { fontSize: 22, color: "#1e40af", fontWeight: 800 } : {}),
        ...(color ? { color } : {}),
      }}>
        {value}
      </div>
    </div>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────────

const styles: Record<string, React.CSSProperties> = {
  container: {
    fontFamily: "'Inter', -apple-system, sans-serif",
    maxWidth: 720, margin: "0 auto",
    display: "flex", flexDirection: "column", gap: 16,
  },
  header: {
    display: "flex", justifyContent: "space-between", alignItems: "flex-start",
    padding: "16px 20px", background: "linear-gradient(135deg,#1e3a5f,#1e40af)",
    borderRadius: 10, color: "#fff",
  },
  title:    { margin: 0, fontSize: 18, fontWeight: 700 },
  subtitle: { margin: "4px 0 0", fontSize: 13, opacity: 0.8 },
  badges:   { display: "flex", gap: 6, flexWrap: "wrap" },
  chip: {
    padding: "3px 10px", borderRadius: 99, fontSize: 11,
    fontWeight: 600, whiteSpace: "nowrap",
  },

  section: {
    border: "1px solid #e5e7eb", borderRadius: 10,
    padding: "14px 18px", transition: "border-color .2s",
  },
  sectionTitle: {
    fontSize: 13, fontWeight: 700, color: "#374151",
    marginBottom: 10, display: "flex", gap: 6, alignItems: "center",
    textTransform: "uppercase", letterSpacing: ".04em",
  },
  fieldDesc: { margin: "0 0 10px", fontSize: 13, color: "#6b7280", lineHeight: 1.5 },

  sliderWrap: { display: "flex", alignItems: "center", gap: 12 },
  slider:     { flex: 1, accentColor: "#7c3aed", height: 4 },
  sliderValue: { fontSize: 18, fontWeight: 700, minWidth: 48, textAlign: "right" },
  monthPips: { display: "flex", gap: 3, marginTop: 6 },
  pip:       { flex: 1, height: 4, borderRadius: 2, transition: "background .15s" },

  buttonGroup: { display: "flex", flexWrap: "wrap", gap: 8 },
  segBtn: {
    display: "flex", alignItems: "center", gap: 6,
    padding: "6px 14px", borderRadius: 8,
    border: "1.5px solid #d1d5db", background: "#fff",
    fontSize: 13, cursor: "pointer", fontWeight: 500, transition: "all .15s",
    color: "#374151",
  },
  segBtnActive: { background: "#eff6ff", fontWeight: 700, color: "#1e40af" },
  badgeCircle: {
    width: 22, height: 22, borderRadius: "50%",
    background: "#dbeafe", color: "#1e40af",
    display: "flex", alignItems: "center", justifyContent: "center",
    fontSize: 11, fontWeight: 700,
  },

  sweepGrid:       { display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 8 },
  sweepCard: {
    border: "1.5px solid #e5e7eb", borderRadius: 8,
    padding: "10px 14px", background: "#fff",
    cursor: "pointer", textAlign: "left", transition: "all .15s",
  },
  sweepCardActive: { border: "1.5px solid #6366f1", background: "#eef2ff" },
  sweepBadge: { fontSize: 16, fontWeight: 800, color: "#4f46e5", marginBottom: 2 },
  sweepLabel: { fontSize: 13, fontWeight: 600, color: "#1f2937" },
  sweepDesc:  { fontSize: 11, color: "#6b7280", marginTop: 2 },

  adlGrid: { display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 },
  adlCard: {
    display: "flex", flexDirection: "column", alignItems: "center", gap: 4,
    padding: "10px 8px", border: "1.5px solid #e5e7eb",
    borderRadius: 8, background: "#fff", cursor: "pointer",
    transition: "all .15s", position: "relative",
  },
  adlCardChecked: { border: "1.5px solid #10b981", background: "#ecfdf5" },
  adlCheckbox: {
    position: "absolute", top: 6, right: 6,
    width: 18, height: 18, borderRadius: 4,
    border: "1.5px solid #10b981", background: "#10b981",
    display: "flex", alignItems: "center", justifyContent: "center",
    color: "#fff", fontSize: 11, fontWeight: 800,
  },
  adlIcon:  { fontSize: 22 },
  adlLabel: { fontSize: 11, fontWeight: 600, color: "#374151" },

  infoBox: {
    marginTop: 10, padding: "10px 14px", borderRadius: 8,
    border: "1px solid #c7d2fe", background: "#eef2ff",
    fontSize: 13, color: "#374151", lineHeight: 1.5,
  },

  resultBox: {
    border: "1.5px solid #bfdbfe", borderRadius: 10,
    background: "#eff6ff", padding: "14px 18px",
  },
  resultHeader: {
    fontSize: 12, fontWeight: 700, color: "#1e40af",
    textTransform: "uppercase", letterSpacing: ".05em", marginBottom: 12,
  },
  resultGrid: { display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 },
  resultStat: { textAlign: "center" },
  resultStatLabel: { fontSize: 11, color: "#6b7280", fontWeight: 600 },
  resultStatValue: { fontSize: 15, fontWeight: 700, color: "#1f2937", marginTop: 2 },

  calcBtn: {
    padding: "13px 0", background: "linear-gradient(135deg,#1e40af,#6366f1)",
    border: "none", borderRadius: 10, color: "#fff",
    fontSize: 15, fontWeight: 700, cursor: "pointer",
    display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
    transition: "opacity .15s",
  },
  spinner: {
    width: 16, height: 16,
    border: "2px solid rgba(255,255,255,.3)",
    borderTopColor: "#fff",
    borderRadius: "50%",
    animation: "spin 0.7s linear infinite",
    display: "inline-block",
  },
};
