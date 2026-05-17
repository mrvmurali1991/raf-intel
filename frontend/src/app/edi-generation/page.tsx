"use client";

/**
 * EDI Generation Page — outbound 837 (encounter) and 834 (enrollment).
 *
 * Two tabs:
 *   • 837 Encounter   — pick payment year + patient IDs, optional R1-R6 gate.
 *   • 834 Enrollment  — pick plan year + patient IDs.
 *
 * The 837 path enforces a typed-confirmation override when the pre-submission
 * validator flags HIGH-severity findings.  This mirrors the backend gate at
 * POST /api/edi/837/generate.
 */

import React, { useCallback, useMemo, useState } from "react";
import api from "@/lib/api";
import { tokens } from "@/styles/tokens";
import {
  FileText,
  Download,
  AlertTriangle,
  CheckCircle,
  Loader2,
  ShieldCheck,
} from "lucide-react";

type TabKey = "837" | "834";

interface GenerateResponse {
  file_id: string;
  transaction: "837" | "834";
  total_encounters: number;
  file_size: number;
  sha256: string;
  download_url: string;
  errors?: Array<{
    patient_id: number;
    findings: Array<{ rule: string; severity: string; message: string }>;
  }>;
  excluded_patient_ids?: number[];
  override_applied?: boolean;
}

interface ValidatorBlock {
  failed_patient_ids: number[];
  high_severity_total: number;
  per_patient: Array<{
    patient_id: number;
    passed: boolean;
    findings: Array<{ rule: string; severity: string; message: string }>;
  }>;
}

const T = {
  bg: tokens.slate50,
  white: tokens.white,
  border: tokens.slate200,
  text: tokens.slate900,
  muted: tokens.slate600,
  primary: tokens.primary || "#2563EB",
  danger: tokens.danger || "#DC2626",
  warning: "#D97706",
  success: tokens.success || "#16A34A",
};

const card: React.CSSProperties = {
  background: T.white,
  border: `1px solid ${T.border}`,
  borderRadius: 12,
  padding: 20,
  marginBottom: 16,
};

const labelStyle: React.CSSProperties = {
  display: "block",
  fontSize: 12,
  fontWeight: 600,
  color: T.muted,
  marginBottom: 4,
  textTransform: "uppercase",
  letterSpacing: 0.4,
};

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "10px 12px",
  border: `1px solid ${T.border}`,
  borderRadius: 8,
  fontSize: 14,
  color: T.text,
  background: T.white,
};

const primaryButton: React.CSSProperties = {
  background: T.primary,
  color: T.white,
  border: "none",
  borderRadius: 8,
  padding: "10px 18px",
  fontWeight: 600,
  fontSize: 14,
  cursor: "pointer",
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
};

function parsePatientIds(raw: string): number[] {
  return Array.from(
    new Set(
      raw
        .split(/[,\s]+/)
        .map((s) => s.trim())
        .filter(Boolean)
        .map((s) => Number(s))
        .filter((n) => Number.isFinite(n) && n > 0),
    ),
  );
}

export default function EdiGenerationPage(): JSX.Element {
  const [tab, setTab] = useState<TabKey>("837");

  return (
    <div style={{ minHeight: "100vh", background: T.bg, padding: 24 }}>
      <div style={{ maxWidth: 960, margin: "0 auto" }}>
        <header style={{ marginBottom: 20 }}>
          <h1 style={{ fontSize: 24, fontWeight: 700, color: T.text, margin: 0 }}>
            EDI Generation
          </h1>
          <p style={{ color: T.muted, marginTop: 6 }}>
            Outbound X12 5010 transactions — 837 (encounter) and 834
            (enrollment maintenance).
          </p>
        </header>

        {/* Tab bar */}
        <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
          {(["837", "834"] as const).map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => setTab(k)}
              style={{
                padding: "10px 16px",
                background: tab === k ? T.primary : T.white,
                color: tab === k ? T.white : T.text,
                border: `1px solid ${tab === k ? T.primary : T.border}`,
                borderRadius: 8,
                fontWeight: 600,
                cursor: "pointer",
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              <FileText size={16} />
              {k === "837" ? "837 Encounter" : "834 Enrollment"}
            </button>
          ))}
        </div>

        {tab === "837" ? <Generate837 /> : <Generate834 />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 837 form
// ---------------------------------------------------------------------------

function Generate837(): JSX.Element {
  const [paymentYear, setPaymentYear] = useState<number>(
    new Date().getFullYear(),
  );
  const [patientIdsRaw, setPatientIdsRaw] = useState<string>("");
  const [runValidator, setRunValidator] = useState<boolean>(true);
  const [busy, setBusy] = useState<boolean>(false);
  const [result, setResult] = useState<GenerateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [validatorBlock, setValidatorBlock] =
    useState<ValidatorBlock | null>(null);
  const [overrideOpen, setOverrideOpen] = useState<boolean>(false);
  const [overrideConfirm, setOverrideConfirm] = useState<string>("");
  const [overrideReason, setOverrideReason] = useState<string>("");

  const patientIds = useMemo(
    () => parsePatientIds(patientIdsRaw),
    [patientIdsRaw],
  );

  const submit = useCallback(
    async (forceOverride: boolean) => {
      setBusy(true);
      setError(null);
      setValidatorBlock(null);
      try {
        const body = {
          patient_ids: patientIds,
          payment_year: paymentYear,
          run_pre_submission_validator: runValidator,
          confirm_override: forceOverride,
          override_reason: forceOverride ? overrideReason.trim() : null,
        };
        const { data } = await api.post<GenerateResponse>(
          "/api/edi/837/generate",
          body,
        );
        setResult(data);
        setOverrideOpen(false);
        setOverrideConfirm("");
        setOverrideReason("");
      } catch (e: any) {
        const detail = e?.response?.data?.detail;
        if (
          detail &&
          typeof detail === "object" &&
          detail.error === "pre_submission_high_severity"
        ) {
          setValidatorBlock({
            failed_patient_ids: detail.failed_patient_ids,
            high_severity_total: detail.high_severity_total,
            per_patient: detail.per_patient || [],
          });
          setOverrideOpen(true);
        } else {
          const msg =
            typeof detail === "string"
              ? detail
              : detail?.message ||
                e?.message ||
                "837 generation failed";
          setError(msg);
        }
      } finally {
        setBusy(false);
      }
    },
    [patientIds, paymentYear, runValidator, overrideReason],
  );

  return (
    <div style={card}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div>
          <label style={labelStyle} htmlFor="payment_year">
            Payment Year
          </label>
          <input
            id="payment_year"
            type="number"
            min={2020}
            max={2030}
            value={paymentYear}
            onChange={(e) => setPaymentYear(Number(e.target.value))}
            style={inputStyle}
          />
        </div>
        <div>
          <label style={labelStyle}>Validator Gate</label>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input
              type="checkbox"
              checked={runValidator}
              onChange={(e) => setRunValidator(e.target.checked)}
            />
            <span style={{ fontSize: 13, color: T.text }}>
              Run R1-R6 pre-submission validator
            </span>
          </label>
        </div>
      </div>

      <div style={{ marginTop: 16 }}>
        <label style={labelStyle} htmlFor="patient_ids">
          Patient IDs (comma or space separated)
        </label>
        <textarea
          id="patient_ids"
          rows={3}
          value={patientIdsRaw}
          onChange={(e) => setPatientIdsRaw(e.target.value)}
          placeholder="e.g. 3, 4, 5"
          style={{ ...inputStyle, fontFamily: "monospace" }}
        />
        <div style={{ fontSize: 12, color: T.muted, marginTop: 4 }}>
          {patientIds.length} patient{patientIds.length === 1 ? "" : "s"} parsed
        </div>
      </div>

      <div style={{ marginTop: 16, display: "flex", justifyContent: "flex-end" }}>
        <button
          type="button"
          onClick={() => submit(false)}
          disabled={busy || patientIds.length === 0}
          style={{
            ...primaryButton,
            opacity: busy || patientIds.length === 0 ? 0.6 : 1,
          }}
        >
          {busy ? <Loader2 size={16} className="animate-spin" /> : <ShieldCheck size={16} />}
          Generate 837
        </button>
      </div>

      {error && (
        <div
          style={{
            ...card,
            background: "#FEF2F2",
            borderColor: T.danger,
            marginTop: 16,
            marginBottom: 0,
          }}
        >
          <div style={{ color: T.danger, display: "flex", alignItems: "center", gap: 8 }}>
            <AlertTriangle size={16} /> {error}
          </div>
        </div>
      )}

      {overrideOpen && validatorBlock && (
        <OverridePrompt
          block={validatorBlock}
          onCancel={() => {
            setOverrideOpen(false);
            setValidatorBlock(null);
          }}
          confirm={overrideConfirm}
          setConfirm={setOverrideConfirm}
          reason={overrideReason}
          setReason={setOverrideReason}
          onForce={() => submit(true)}
          busy={busy}
        />
      )}

      {result && <ResultPanel result={result} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// 834 form
// ---------------------------------------------------------------------------

function Generate834(): JSX.Element {
  const [planYear, setPlanYear] = useState<number>(new Date().getFullYear());
  const [patientIdsRaw, setPatientIdsRaw] = useState<string>("");
  const [busy, setBusy] = useState<boolean>(false);
  const [result, setResult] = useState<GenerateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const patientIds = useMemo(
    () => parsePatientIds(patientIdsRaw),
    [patientIdsRaw],
  );

  const submit = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const { data } = await api.post<GenerateResponse>(
        "/api/edi/834/generate",
        { patient_ids: patientIds, plan_year: planYear },
      );
      setResult(data);
    } catch (e: any) {
      const d = e?.response?.data?.detail;
      setError(typeof d === "string" ? d : e?.message || "834 generation failed");
    } finally {
      setBusy(false);
    }
  }, [patientIds, planYear]);

  return (
    <div style={card}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <div>
          <label style={labelStyle} htmlFor="plan_year">Plan Year</label>
          <input
            id="plan_year"
            type="number"
            min={2020}
            max={2030}
            value={planYear}
            onChange={(e) => setPlanYear(Number(e.target.value))}
            style={inputStyle}
          />
        </div>
      </div>

      <div style={{ marginTop: 16 }}>
        <label style={labelStyle} htmlFor="patient_ids_834">
          Patient IDs to enroll
        </label>
        <textarea
          id="patient_ids_834"
          rows={3}
          value={patientIdsRaw}
          onChange={(e) => setPatientIdsRaw(e.target.value)}
          placeholder="e.g. 3, 4, 5"
          style={{ ...inputStyle, fontFamily: "monospace" }}
        />
        <div style={{ fontSize: 12, color: T.muted, marginTop: 4 }}>
          {patientIds.length} patient{patientIds.length === 1 ? "" : "s"} parsed
        </div>
      </div>

      <div style={{ marginTop: 16, display: "flex", justifyContent: "flex-end" }}>
        <button
          type="button"
          onClick={submit}
          disabled={busy || patientIds.length === 0}
          style={{
            ...primaryButton,
            opacity: busy || patientIds.length === 0 ? 0.6 : 1,
          }}
        >
          {busy ? <Loader2 size={16} className="animate-spin" /> : <FileText size={16} />}
          Generate 834
        </button>
      </div>

      {error && (
        <div
          style={{
            ...card,
            background: "#FEF2F2",
            borderColor: T.danger,
            marginTop: 16,
            marginBottom: 0,
          }}
        >
          <div style={{ color: T.danger, display: "flex", alignItems: "center", gap: 8 }}>
            <AlertTriangle size={16} /> {error}
          </div>
        </div>
      )}

      {result && <ResultPanel result={result} />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared sub-components
// ---------------------------------------------------------------------------

function OverridePrompt(props: {
  block: ValidatorBlock;
  confirm: string;
  setConfirm: (v: string) => void;
  reason: string;
  setReason: (v: string) => void;
  onForce: () => void;
  onCancel: () => void;
  busy: boolean;
}): JSX.Element {
  const { block, confirm, setConfirm, reason, setReason, onForce, onCancel, busy } = props;
  const ready = confirm.trim() === "OVERRIDE" && reason.trim().length >= 10;
  return (
    <div
      style={{
        ...card,
        background: "#FFFBEB",
        borderColor: T.warning,
        marginTop: 16,
        marginBottom: 0,
      }}
    >
      <h3 style={{ color: T.warning, fontSize: 16, margin: 0, display: "flex", gap: 8, alignItems: "center" }}>
        <AlertTriangle size={18} /> HIGH-severity findings — override required
      </h3>
      <p style={{ color: T.text, fontSize: 14, marginTop: 8 }}>
        {block.high_severity_total} HIGH-severity issue
        {block.high_severity_total === 1 ? "" : "s"} blocked these patient IDs:{" "}
        <code>{block.failed_patient_ids.join(", ")}</code>
      </p>
      <details style={{ marginTop: 8 }}>
        <summary style={{ cursor: "pointer", fontSize: 13, color: T.muted }}>
          View findings
        </summary>
        <ul style={{ fontSize: 13, color: T.text }}>
          {block.per_patient
            .filter((p) => p.findings && p.findings.length)
            .map((p) => (
              <li key={p.patient_id}>
                Patient {p.patient_id}:
                <ul>
                  {p.findings.map((f, i) => (
                    <li key={i}>
                      <strong>{f.rule}</strong> [{f.severity}] — {f.message}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
        </ul>
      </details>
      <div style={{ marginTop: 12 }}>
        <label style={labelStyle} htmlFor="override_reason">Override Reason (≥ 10 chars)</label>
        <textarea
          id="override_reason"
          rows={2}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          style={inputStyle}
        />
      </div>
      <div style={{ marginTop: 12 }}>
        <label style={labelStyle} htmlFor="override_typed">
          Type <code>OVERRIDE</code> to confirm
        </label>
        <input
          id="override_typed"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          style={inputStyle}
        />
      </div>
      <div style={{ marginTop: 12, display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button
          type="button"
          onClick={onCancel}
          style={{
            background: T.white,
            color: T.text,
            border: `1px solid ${T.border}`,
            borderRadius: 8,
            padding: "8px 14px",
            cursor: "pointer",
          }}
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={onForce}
          disabled={!ready || busy}
          style={{
            ...primaryButton,
            background: T.danger,
            opacity: !ready || busy ? 0.6 : 1,
          }}
        >
          {busy ? <Loader2 size={16} className="animate-spin" /> : <AlertTriangle size={16} />}
          Override &amp; Generate
        </button>
      </div>
    </div>
  );
}

function ResultPanel({ result }: { result: GenerateResponse }): JSX.Element {
  return (
    <div
      style={{
        ...card,
        background: "#F0FDF4",
        borderColor: T.success,
        marginTop: 16,
        marginBottom: 0,
      }}
    >
      <h3 style={{ color: T.success, fontSize: 16, margin: 0, display: "flex", gap: 8, alignItems: "center" }}>
        <CheckCircle size={18} /> {result.transaction} generated
      </h3>
      <dl style={{ fontSize: 13, color: T.text, marginTop: 12 }}>
        <div><strong>File ID:</strong> <code>{result.file_id}</code></div>
        <div><strong>Records:</strong> {result.total_encounters}</div>
        <div><strong>Size:</strong> {result.file_size.toLocaleString()} bytes</div>
        <div><strong>SHA-256:</strong> <code style={{ fontSize: 11 }}>{result.sha256}</code></div>
        {result.override_applied && (
          <div style={{ color: T.warning }}>
            <strong>Override applied:</strong> HIGH-severity gate bypassed.
          </div>
        )}
        {result.excluded_patient_ids && result.excluded_patient_ids.length > 0 && (
          <div>
            <strong>Excluded by validator:</strong>{" "}
            {result.excluded_patient_ids.join(", ")}
          </div>
        )}
      </dl>
      <a
        href={result.download_url}
        download
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
          marginTop: 12,
          padding: "10px 18px",
          background: T.success,
          color: T.white,
          borderRadius: 8,
          fontWeight: 600,
          textDecoration: "none",
        }}
      >
        <Download size={16} /> Download {result.transaction} file
      </a>
    </div>
  );
}
