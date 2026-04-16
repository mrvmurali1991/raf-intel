"use client";

import React, { useState, useEffect, useCallback, useMemo } from "react";
import { Loader2, Download, AlertCircle, Info } from "lucide-react";
import { calculateRAFFull, RAFCalcResponse } from "@/lib/api";
import { FONT_SYS, FONT_MONO } from "@/lib/ui-utils";
import { MA_PAYMENT_PER_RAF } from "@/lib/constants";

/* ================================================================== */
/*  Design tokens — match patients / suspects pages                    */
/* ================================================================== */

const C = {
  text: "#0F172A",
  textMuted: "#475569",
  textSubtle: "#64748B",
  label: "#94A3B8",
  border: "#E2E8F0",
  borderSoft: "#EEF2F6",
  rowDivider: "#F1F5F9",
  bgPage: "#F8FAFC",
  bgCard: "#FFFFFF",
  bgSubtle: "#F8FAFC",
  brand: "#0F766E",
  brandSoft: "rgba(15, 118, 110, 0.06)",
  accent: "#4F46E5",
  accentSoft: "rgba(79, 70, 229, 0.08)",
  sectionBand: "#EEF0FF",
  high: "#DC2626",
  low: "#059669",
  white: "#FFFFFF",
};

/* ================================================================== */
/*  Constants                                                          */
/* ================================================================== */

const SAMPLE_CODES = "I50.30, E11.22, J44.9, N18.6";

const RISK_MODELS = [
  // ----- V28 -----
  { value: "v28-ce-2026", label: "CMS-HCC V28 Continuing Enrollee · PY 2026" },
  { value: "v28-ne-2026", label: "CMS-HCC V28 New Enrollee · PY 2026" },
  { value: "v28-csnp-2026", label: "CMS-HCC V28 C-SNP · PY 2026" },
  { value: "v28-ce-2025", label: "CMS-HCC V28 Continuing Enrollee · PY 2025" },
  { value: "v28-ne-2025", label: "CMS-HCC V28 New Enrollee · PY 2025" },
  { value: "v28-csnp-2025", label: "CMS-HCC V28 C-SNP · PY 2025" },
  { value: "v28-ce-2027p", label: "CMS-HCC V28 Continuing Enrollee · PY 2027 (proposed)" },
  // ----- V24 -----
  { value: "v24-ce-2026", label: "CMS-HCC V24 Continuing Enrollee · PY 2026" },
  { value: "v24-ne-2026", label: "CMS-HCC V24 New Enrollee · PY 2026" },
  { value: "v24-csnp-2026", label: "CMS-HCC V24 C-SNP · PY 2026" },
  { value: "v24-ce-2025", label: "CMS-HCC V24 Continuing Enrollee · PY 2025" },
  { value: "v24-ne-2025", label: "CMS-HCC V24 New Enrollee · PY 2025" },
];

const RISK_FACTORS = [
  "Community NonDual Aged",
  "Community NonDual Disabled",
  "Community PBDual Aged",
  "Community PBDual Disabled",
  "Community FBDual Aged",
  "Community FBDual Disabled",
  "Institutional Not-Disabled",
  "Institutional Disabled",
];

/* ================================================================== */
/*  Helpers                                                            */
/* ================================================================== */

function fmt3(v: number | null | undefined): string {
  if (v == null) return "—";
  return Number(v).toFixed(3);
}

function fmtMoney(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return "$ " + Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function toCSV(rows: (string | number)[][]): string {
  return rows
    .map((r) =>
      r
        .map((c) => {
          const s = String(c ?? "");
          return s.includes(",") || s.includes('"') || s.includes("\n")
            ? `"${s.replace(/"/g, '""')}"`
            : s;
        })
        .join(",")
    )
    .join("\n");
}

function downloadFile(csv: string, filename: string) {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function prettyInteractionName(name: string): string {
  return name
    .replace(/_V28$/, "")
    .replace(/_V24$/, "")
    .replace(/_/g, " · ");
}

/* ================================================================== */
/*  Component                                                          */
/* ================================================================== */

export default function CrosswalkPage() {
  const [riskModel, setRiskModel] = useState<string>("v28-ce-2026");
  const [riskFactor, setRiskFactor] = useState<string>(RISK_FACTORS[0]);
  const [gender, setGender] = useState<"Male" | "Female">("Male");
  const [age, setAge] = useState<number>(65);
  const [input, setInput] = useState<string>(SAMPLE_CODES);
  const [result, setResult] = useState<RAFCalcResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isV28 = riskModel.startsWith("v28");

  const runCalculation = useCallback(
    async (raw: string) => {
      const codes = raw
        .split(/[,\n\s]+/)
        .map((c) => c.trim())
        .filter(Boolean);
      if (codes.length === 0) {
        setResult(null);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const data = await calculateRAFFull({
          codes,
          age,
          gender,
          risk_factor: riskFactor,
          model: riskModel,
        });
        setResult(data);
      } catch (err: unknown) {
        const e = err as { response?: { data?: { detail?: string } }; message?: string };
        setError(e?.response?.data?.detail || e?.message || "Calculation failed");
        setResult(null);
      } finally {
        setLoading(false);
      }
    },
    [age, gender, riskFactor, riskModel]
  );

  // Auto-run on mount
  useEffect(() => {
    runCalculation(SAMPLE_CODES);
    // runCalculation is intentionally omitted: its deps (age/gender/riskFactor/
    // riskModel) have deterministic initial values, and we only want a single
    // mount-time invocation here; the effect below handles re-runs on change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-run whenever the demographic/model controls or the input text change.
  useEffect(() => {
    if (input.trim()) runCalculation(input);
  }, [age, gender, riskFactor, riskModel, input, runCalculation]);

  const baseRate = result?.base_rate ?? MA_PAYMENT_PER_RAF;
  const normFactor = result?.norm_factor ?? 1.199;
  const maci = result?.maci ?? 0.059;
  // Payment = coefficient × baseRate × adjustmentFactor
  // adjustmentFactor accounts for CMS normalization and coding intensity
  const adjustmentFactor = (1 - maci) / normFactor;

  function handleCalculate() {
    runCalculation(input);
  }

  function handleSample() {
    setInput(SAMPLE_CODES);
    runCalculation(SAMPLE_CODES);
  }

  function handleExport() {
    if (!result) return;
    const header = [
      "Category/ICD10",
      "Diagnosis Description",
      isV28 ? "CMS-HCC-V28" : "CMS-HCC-V24",
      "RAF Score",
      "MA Payment",
    ];
    const rows: (string | number)[][] = [header];
    const csvAdj = adjustmentFactor;
    rows.push([
      "Demographic",
      result.demographic.category || "—",
      "—",
      fmt3(result.demographic.coefficient),
      fmtMoney(result.demographic.coefficient * baseRate * csvAdj),
    ]);
    result.hcc_details.forEach((h) => {
      rows.push([
        h.diagnosis_codes.join(", "),
        h.label,
        `HCC ${h.hcc}`,
        fmt3(h.coefficient),
        fmtMoney(h.coefficient * baseRate * csvAdj),
      ]);
    });
    if (result.interactions.length > 0) {
      result.interactions.forEach((iac) => {
        rows.push([
          prettyInteractionName(iac.name),
          "—",
          "—",
          fmt3(iac.coefficient),
          fmtMoney(iac.coefficient * baseRate * csvAdj),
        ]);
      });
    }
    rows.push([
      "Grand Total",
      "—",
      "—",
      fmt3(result.totals.grand_total),
      fmtMoney(result.totals.ma_cp_adjusted * baseRate),
    ]);
    rows.push([
      "Normalized",
      "—",
      "—",
      fmt3(result.totals.normalized),
      fmtMoney(result.totals.ma_cp_adjusted * baseRate),
    ]);
    rows.push([
      "Payment_RAF",
      "—",
      "—",
      fmt3(result.totals.ma_cp_adjusted),
      fmtMoney(result.totals.ma_cp_adjusted * baseRate),
    ]);
    downloadFile(toCSV(rows), `raf-score-${Date.now()}.csv`);
  }

  /* ================================================================== */
  /*  Styles                                                             */
  /* ================================================================== */

  const labelStyle: React.CSSProperties = {
    fontSize: 11,
    fontWeight: 600,
    color: C.textMuted,
    marginBottom: 6,
    display: "block",
  };

  const inputStyle: React.CSSProperties = {
    width: "100%",
    height: 42,
    padding: "0 14px",
    borderRadius: 10,
    border: `1px solid ${C.border}`,
    backgroundColor: C.white,
    fontSize: 14,
    color: C.text,
    fontFamily: FONT_SYS,
    outline: "none",
    transition: "border-color 0.15s ease, box-shadow 0.15s ease",
  };

  const selectStyle: React.CSSProperties = {
    ...inputStyle,
    appearance: "none",
    backgroundImage:
      "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12' fill='none'><path d='M2.5 4.5L6 8L9.5 4.5' stroke='%230F766E' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round'/></svg>\")",
    backgroundRepeat: "no-repeat",
    backgroundPosition: "right 12px center",
    paddingRight: 36,
    cursor: "pointer",
  };

  const thStyle: React.CSSProperties = {
    padding: "14px 18px",
    fontSize: 12,
    fontWeight: 700,
    color: C.white,
    textAlign: "left",
    letterSpacing: "0.02em",
    backgroundColor: C.accent,
    whiteSpace: "nowrap",
  };

  const tdStyle: React.CSSProperties = {
    padding: "14px 18px",
    fontSize: 13,
    color: C.text,
    borderBottom: `1px solid ${C.rowDivider}`,
    verticalAlign: "middle",
  };

  const sectionBandStyle: React.CSSProperties = {
    padding: "10px 18px",
    fontSize: 12,
    fontWeight: 700,
    color: C.text,
    backgroundColor: C.sectionBand,
    letterSpacing: "0.01em",
    textAlign: "center",
    borderBottom: `1px solid ${C.rowDivider}`,
  };

  const totalRowStyle: React.CSSProperties = {
    backgroundColor: "#F0EEFE",
  };

  const hccDetails = result?.hcc_details ?? [];
  const interactions = result?.interactions ?? [];

  /* ================================================================== */
  /*  Render                                                             */
  /* ================================================================== */

  return (
    <div
      style={{
        minHeight: "100vh",
        backgroundColor: C.bgPage,
        padding: "28px 32px 40px",
        fontFamily: FONT_SYS,
        color: C.text,
      }}
    >
      <div style={{ maxWidth: 1280, margin: "0 auto" }}>
        {/* Header */}
        <div style={{ marginBottom: 18 }}>
          <h1
            style={{
              fontSize: 22,
              fontWeight: 700,
              color: C.text,
              margin: 0,
              letterSpacing: "-0.015em",
            }}
          >
            RAF Score Calculator
          </h1>
          <p
            style={{
              fontSize: 13,
              color: C.textSubtle,
              margin: "4px 0 0 0",
            }}
          >
            Score a patient instantly — pick a risk model, enter ICD-10 codes, and see the full RAF
            build + MA payment.
          </p>
        </div>

        {/* Form card */}
        <div
          style={{
            backgroundColor: C.bgCard,
            borderRadius: 14,
            border: `1px solid ${C.border}`,
            boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)",
            padding: 22,
            marginBottom: 20,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 18,
            }}
          >
            <div
              style={{
                fontSize: 11,
                color: C.low,
                fontWeight: 700,
                letterSpacing: "0.01em",
              }}
            >
              Use for DOS on or after Jan 1, 2026
            </div>
            <div
              style={{
                padding: "4px 12px",
                borderRadius: 999,
                border: `1px solid ${C.low}`,
                color: C.low,
                fontSize: 11,
                fontWeight: 700,
              }}
            >
              Norm × {normFactor.toFixed(3)} · MACI {(maci * 100).toFixed(1)}%
            </div>
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1.6fr 1.6fr 1fr 0.7fr",
              gap: 16,
              marginBottom: 18,
            }}
          >
            <div>
              <label style={labelStyle}>Risk Model</label>
              <select
                value={riskModel}
                onChange={(e) => setRiskModel(e.target.value)}
                style={selectStyle}
              >
                {RISK_MODELS.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label style={labelStyle}>Risk Factor</label>
              <select
                value={riskFactor}
                onChange={(e) => setRiskFactor(e.target.value)}
                style={selectStyle}
              >
                {RISK_FACTORS.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label style={labelStyle}>Gender</label>
              <select
                value={gender}
                onChange={(e) => setGender(e.target.value as "Male" | "Female")}
                style={selectStyle}
              >
                <option value="Male">Male</option>
                <option value="Female">Female</option>
              </select>
            </div>

            <div>
              <label style={labelStyle}>Age</label>
              <input
                type="number"
                min={0}
                max={120}
                value={age}
                onChange={(e) => setAge(Number(e.target.value) || 0)}
                style={inputStyle}
              />
            </div>
          </div>

          <div>
            <label style={labelStyle}>Diagnosis codes</label>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "minmax(0, 1fr) auto",
                gap: 12,
                alignItems: "stretch",
              }}
            >
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") handleCalculate();
                }}
                placeholder="e.g. E11.22, I50.30, J44.9, N18.6"
                rows={3}
                style={{
                  ...inputStyle,
                  height: "auto",
                  padding: "12px 14px",
                  resize: "vertical",
                  minHeight: 84,
                  fontFamily: FONT_MONO,
                  fontSize: 13,
                  lineHeight: 1.5,
                }}
              />
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <button
                  onClick={handleCalculate}
                  disabled={loading}
                  style={{
                    height: 42,
                    minWidth: 160,
                    padding: "0 22px",
                    borderRadius: 10,
                    border: "none",
                    backgroundColor: C.accent,
                    color: C.white,
                    fontSize: 14,
                    fontWeight: 700,
                    cursor: loading ? "default" : "pointer",
                    opacity: loading ? 0.6 : 1,
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: 8,
                    letterSpacing: "0.01em",
                    boxShadow: "0 2px 4px rgba(79, 70, 229, 0.18)",
                  }}
                >
                  {loading ? (
                    <>
                      <Loader2 size={15} className="spin" /> Calculating…
                    </>
                  ) : (
                    <>Get Risk Score</>
                  )}
                </button>
                <button
                  onClick={handleSample}
                  style={{
                    height: 36,
                    padding: "0 14px",
                    borderRadius: 10,
                    border: `1px solid ${C.border}`,
                    backgroundColor: C.bgSubtle,
                    color: C.textMuted,
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: "pointer",
                    display: "inline-flex",
                    alignItems: "center",
                    justifyContent: "center",
                    gap: 6,
                  }}
                  title={`Load sample: ${SAMPLE_CODES}`}
                >
                  <Info size={12} /> Use sample data
                </button>
              </div>
            </div>
            <div
              style={{
                marginTop: 8,
                fontSize: 11,
                color: C.label,
                fontFamily: FONT_MONO,
              }}
            >
              Tip: separate codes with commas, spaces, or new lines. ⌘/Ctrl + Enter to calculate.
            </div>
          </div>

          {error && (
            <div
              style={{
                marginTop: 14,
                padding: "10px 14px",
                borderRadius: 10,
                backgroundColor: "#FEF2F2",
                border: "1px solid #FECACA",
                color: C.high,
                fontSize: 12,
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              <AlertCircle size={14} /> {error}
            </div>
          )}

          {result && result.unmapped_codes.length > 0 && (
            <div
              style={{
                marginTop: 14,
                padding: "10px 14px",
                borderRadius: 10,
                backgroundColor: "#FFFBEB",
                border: "1px solid #FDE68A",
                color: "#92400E",
                fontSize: 12,
                display: "flex",
                alignItems: "center",
                gap: 8,
                fontFamily: FONT_MONO,
              }}
            >
              <AlertCircle size={14} />
              <span>
                Not risk-adjusting: <strong>{result.unmapped_codes.join(", ")}</strong>
              </span>
            </div>
          )}
        </div>

        {/* Results table */}
        <div
          style={{
            backgroundColor: C.bgCard,
            borderRadius: 14,
            border: `1px solid ${C.border}`,
            boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)",
            overflow: "hidden",
          }}
        >
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: 13,
            }}
          >
            <thead>
              <tr>
                <th style={{ ...thStyle, width: "22%", textAlign: "center" }}>Category/ICD10</th>
                <th style={{ ...thStyle, width: "42%", textAlign: "center" }}>
                  Diagnosis Description
                </th>
                <th style={{ ...thStyle, width: "14%", textAlign: "center" }}>
                  {isV28 ? "CMS-HCC-V28" : "CMS-HCC-V24"}
                </th>
                <th style={{ ...thStyle, width: "10%", textAlign: "center" }}>RAF Score</th>
                <th style={{ ...thStyle, width: "12%", textAlign: "right", paddingRight: 22 }}>
                  * MA Payment
                </th>
              </tr>
            </thead>
            <tbody>
              {/* Demographic row */}
              <tr>
                <td style={{ ...tdStyle, textAlign: "center", fontWeight: 600 }}>Demographic</td>
                <td
                  style={{
                    ...tdStyle,
                    textAlign: "center",
                    color: C.textSubtle,
                    fontFamily: FONT_MONO,
                    fontSize: 12,
                  }}
                >
                  {result?.demographic.category || "—"}
                </td>
                <td style={{ ...tdStyle, textAlign: "center", color: C.label }}>—</td>
                <td
                  style={{
                    ...tdStyle,
                    textAlign: "center",
                    fontWeight: 700,
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {fmt3(result?.demographic.coefficient)}
                </td>
                <td
                  style={{
                    ...tdStyle,
                    textAlign: "right",
                    paddingRight: 22,
                    fontWeight: 600,
                    fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {fmtMoney((result?.demographic.coefficient ?? 0) * baseRate * adjustmentFactor)}
                </td>
              </tr>

              {/* Diagnosis section band */}
              <tr>
                <td colSpan={5} style={sectionBandStyle}>
                  Diagnosis
                </td>
              </tr>

              {loading && hccDetails.length === 0 && (
                <tr>
                  <td
                    colSpan={5}
                    style={{ ...tdStyle, textAlign: "center", color: C.textSubtle, padding: 20 }}
                  >
                    <Loader2
                      size={16}
                      className="spin"
                      style={{ verticalAlign: "middle", marginRight: 8 }}
                    />
                    Calculating…
                  </td>
                </tr>
              )}

              {!loading && hccDetails.length === 0 && (
                <tr>
                  <td
                    colSpan={5}
                    style={{ ...tdStyle, textAlign: "center", color: C.textSubtle, padding: 24 }}
                  >
                    No risk-adjusting diagnoses.
                  </td>
                </tr>
              )}

              {hccDetails.map((h, i) => (
                <tr key={`${h.hcc}-${i}`}>
                  <td
                    style={{
                      ...tdStyle,
                      textAlign: "center",
                      fontFamily: FONT_MONO,
                      fontWeight: 600,
                    }}
                  >
                    {h.diagnosis_codes.join(", ") || "—"}
                  </td>
                  <td style={{ ...tdStyle, textAlign: "center" }}>{h.label}</td>
                  <td
                    style={{
                      ...tdStyle,
                      textAlign: "center",
                      fontFamily: FONT_MONO,
                      fontWeight: 600,
                    }}
                  >
                    HCC {h.hcc}
                  </td>
                  <td
                    style={{
                      ...tdStyle,
                      textAlign: "center",
                      fontWeight: 700,
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    {fmt3(h.coefficient)}
                  </td>
                  <td
                    style={{
                      ...tdStyle,
                      textAlign: "right",
                      paddingRight: 22,
                      fontWeight: 600,
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    {fmtMoney(h.coefficient * baseRate * adjustmentFactor)}
                  </td>
                </tr>
              ))}

              {/* Disease Interactions */}
              {interactions.length > 0 && (
                <>
                  <tr>
                    <td colSpan={5} style={sectionBandStyle}>
                      Disease Interactions
                    </td>
                  </tr>
                  {interactions.map((iac, i) => (
                    <tr key={`${iac.name}-${i}`}>
                      <td
                        style={{
                          ...tdStyle,
                          textAlign: "center",
                          fontFamily: FONT_MONO,
                          fontWeight: 600,
                          color: C.accent,
                        }}
                      >
                        {prettyInteractionName(iac.name)}
                      </td>
                      <td style={{ ...tdStyle, color: C.label, textAlign: "center" }}>—</td>
                      <td style={{ ...tdStyle, color: C.label, textAlign: "center" }}>—</td>
                      <td
                        style={{
                          ...tdStyle,
                          textAlign: "center",
                          fontWeight: 700,
                          fontVariantNumeric: "tabular-nums",
                        }}
                      >
                        {fmt3(iac.coefficient)}
                      </td>
                      <td
                        style={{
                          ...tdStyle,
                          textAlign: "right",
                          paddingRight: 22,
                          fontWeight: 600,
                          fontVariantNumeric: "tabular-nums",
                        }}
                      >
                        {fmtMoney(iac.coefficient * baseRate * adjustmentFactor)}
                      </td>
                    </tr>
                  ))}
                </>
              )}

              {/* Totals */}
              <tr style={totalRowStyle}>
                <td style={{ ...tdStyle, textAlign: "center", fontWeight: 700 }}>Grand Total</td>
                <td style={{ ...tdStyle, color: C.label, textAlign: "center" }}>—</td>
                <td style={{ ...tdStyle, color: C.label, textAlign: "center" }}>—</td>
                <td
                  style={{
                    ...tdStyle,
                    textAlign: "center",
                    fontWeight: 800,
                    fontVariantNumeric: "tabular-nums",
                    color: C.accent,
                  }}
                >
                  {fmt3(result?.totals.grand_total)}
                </td>
                <td
                  style={{
                    ...tdStyle,
                    textAlign: "right",
                    paddingRight: 22,
                    fontWeight: 800,
                    fontVariantNumeric: "tabular-nums",
                    color: C.accent,
                  }}
                >
                  {fmtMoney((result?.totals.ma_cp_adjusted ?? 0) * baseRate)}
                </td>
              </tr>
              <tr style={totalRowStyle}>
                <td style={{ ...tdStyle, textAlign: "center", fontWeight: 700 }}>
                  Normalized
                  <div style={{ fontSize: 10, fontWeight: 600, color: C.textSubtle }}>
                    ÷ {normFactor.toFixed(3)}
                  </div>
                </td>
                <td style={{ ...tdStyle, color: C.label, textAlign: "center" }}>—</td>
                <td style={{ ...tdStyle, color: C.label, textAlign: "center" }}>—</td>
                <td
                  style={{
                    ...tdStyle,
                    textAlign: "center",
                    fontWeight: 800,
                    fontVariantNumeric: "tabular-nums",
                    color: C.accent,
                  }}
                >
                  {fmt3(result?.totals.normalized)}
                </td>
                <td
                  style={{
                    ...tdStyle,
                    textAlign: "right",
                    paddingRight: 22,
                    fontWeight: 800,
                    fontVariantNumeric: "tabular-nums",
                    color: C.accent,
                  }}
                >
                  {fmtMoney((result?.totals.ma_cp_adjusted ?? 0) * baseRate)}
                </td>
              </tr>
              <tr style={totalRowStyle}>
                <td style={{ ...tdStyle, textAlign: "center", fontWeight: 700 }}>
                  Payment RAF
                  <div style={{ fontSize: 10, fontWeight: 600, color: C.textSubtle }}>
                    × {(1 - maci).toFixed(3)} coding intensity
                  </div>
                </td>
                <td style={{ ...tdStyle, color: C.label, textAlign: "center" }}>—</td>
                <td style={{ ...tdStyle, color: C.label, textAlign: "center" }}>—</td>
                <td
                  style={{
                    ...tdStyle,
                    textAlign: "center",
                    fontWeight: 800,
                    fontVariantNumeric: "tabular-nums",
                    color: C.brand,
                  }}
                >
                  {fmt3(result?.totals.ma_cp_adjusted)}
                </td>
                <td
                  style={{
                    ...tdStyle,
                    textAlign: "right",
                    paddingRight: 22,
                    fontWeight: 800,
                    fontVariantNumeric: "tabular-nums",
                    color: C.brand,
                  }}
                >
                  {fmtMoney((result?.totals.ma_cp_adjusted ?? 0) * baseRate)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        {/* Footer */}
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "space-between",
            gap: 16,
            marginTop: 16,
            fontSize: 11,
            color: C.textSubtle,
          }}
        >
          <div style={{ maxWidth: 760, lineHeight: 1.55, fontStyle: "italic" }}>
            * MA payment is indicative and may vary based on clinical documentation quality,
            provider-payor contracts, and CMS agreements. Base rate: {fmtMoney(baseRate)} per RAF
            point.
          </div>
          <button
            onClick={handleExport}
            disabled={!result}
            style={{
              height: 36,
              padding: "0 16px",
              borderRadius: 10,
              border: `1px solid ${C.brand}`,
              backgroundColor: C.brandSoft,
              color: C.brand,
              fontSize: 12,
              fontWeight: 700,
              cursor: result ? "pointer" : "default",
              opacity: result ? 1 : 0.5,
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              flexShrink: 0,
              letterSpacing: "0.01em",
            }}
          >
            <Download size={13} /> Download
          </button>
        </div>
      </div>

      <style>{`
        .spin { animation: spin 0.9s linear infinite; }
        @keyframes spin { to { transform: rotate(360deg); } }
        select:focus, input:focus, textarea:focus {
          border-color: ${C.accent} !important;
          box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.15) !important;
        }
      `}</style>
    </div>
  );
}
