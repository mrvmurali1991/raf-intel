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
import WorkflowProgressBar from "@/components/WorkflowProgressBar";
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

export default function EdiGenerationPage(): React.JSX.Element {
  const [tab, setTab] = useState<TabKey>("837");

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-900 p-6">
      <div className="max-w-[960px] mx-auto">
        <WorkflowProgressBar currentStage="edi-generation" />
        <header className="mb-5">
          <h1 className="text-2xl font-bold text-slate-900 dark:text-slate-50 m-0">
            EDI Generation
          </h1>
          <p className="text-slate-600 dark:text-slate-300 mt-1.5 text-sm">
            Outbound X12 5010 transactions — 837 (encounter) and 834
            (enrollment maintenance).
          </p>
        </header>

        {/* Tab bar */}
        <div className="flex gap-1 mb-4">
          {(["837", "834"] as const).map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => setTab(k)}
              className={`px-4 py-2.5 rounded-lg font-semibold cursor-pointer inline-flex items-center gap-2 border ${
                tab === k
                  ? "bg-blue-600 text-white border-blue-600"
                  : "bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-50 border-slate-200 dark:border-slate-700"
              }`}
            >
              <FileText size={16} />
              {k === "837" ? "837 Encounter" : "834 Enrollment"}
            </button>
          ))}
        </div>

        {tab === "837" ? (
          <section aria-labelledby="edi-837-heading">
            <h2
              id="edi-837-heading"
              className="text-base font-bold text-slate-900 dark:text-slate-50 mb-4"
            >
              837 Encounter Generation
            </h2>
            <Generate837 />
          </section>
        ) : (
          <section aria-labelledby="edi-834-heading">
            <h2
              id="edi-834-heading"
              className="text-base font-bold text-slate-900 dark:text-slate-50 mb-4"
            >
              834 Enrollment Generation
            </h2>
            <Generate834 />
          </section>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 837 form
// ---------------------------------------------------------------------------

function Generate837(): React.JSX.Element {
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
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-[10px] p-5 mb-4">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-semibold text-slate-600 dark:text-slate-300 mb-1 uppercase tracking-wide" htmlFor="payment_year">
            Payment Year
          </label>
          <input
            id="payment_year"
            type="number"
            min={2020}
            max={2030}
            value={paymentYear}
            onChange={(e) => setPaymentYear(Number(e.target.value))}
            className="w-full px-3 py-2.5 border border-slate-200 dark:border-slate-700 rounded-lg text-sm text-slate-900 dark:text-slate-50 bg-white dark:bg-slate-800"
          />
        </div>
        <div>
          <label className="block text-xs font-semibold text-slate-600 dark:text-slate-300 mb-1 uppercase tracking-wide">Validator Gate</label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={runValidator}
              onChange={(e) => setRunValidator(e.target.checked)}
            />
            <span className="text-[13px] text-slate-900 dark:text-slate-50">
              Run R1-R6 pre-submission validator
            </span>
          </label>
        </div>
      </div>

      <div className="mt-4">
        <label className="block text-xs font-semibold text-slate-600 dark:text-slate-300 mb-1 uppercase tracking-wide" htmlFor="patient_ids">
          Patient IDs (comma or space separated)
        </label>
        <textarea
          id="patient_ids"
          rows={3}
          value={patientIdsRaw}
          onChange={(e) => setPatientIdsRaw(e.target.value)}
          placeholder="e.g. 3, 4, 5"
          className="w-full px-3 py-2.5 border border-slate-200 dark:border-slate-700 rounded-lg text-sm text-slate-900 dark:text-slate-50 bg-white dark:bg-slate-800 font-mono"
        />
        <div className="text-xs text-slate-600 dark:text-slate-300 mt-1">
          {patientIds.length} patient{patientIds.length === 1 ? "" : "s"} parsed
        </div>
      </div>

      <div className="mt-4 flex justify-end">
        <button
          type="button"
          onClick={() => submit(false)}
          disabled={busy || patientIds.length === 0}
          className="bg-blue-600 text-white border-none rounded-lg px-[18px] py-2.5 font-semibold text-sm cursor-pointer inline-flex items-center gap-2 disabled:opacity-60"
        >
          {busy ? <Loader2 size={16} className="animate-spin" /> : <ShieldCheck size={16} />}
          Generate 837
        </button>
      </div>

      {error && (
        <div className="bg-red-50 dark:bg-red-950 border border-red-600 dark:border-red-500 rounded-[10px] p-5 mt-4">
          <div className="text-red-600 dark:text-red-400 flex items-center gap-2">
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

function Generate834(): React.JSX.Element {
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
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-[10px] p-5 mb-4">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-xs font-semibold text-slate-600 dark:text-slate-300 mb-1 uppercase tracking-wide" htmlFor="plan_year">Plan Year</label>
          <input
            id="plan_year"
            type="number"
            min={2020}
            max={2030}
            value={planYear}
            onChange={(e) => setPlanYear(Number(e.target.value))}
            className="w-full px-3 py-2.5 border border-slate-200 dark:border-slate-700 rounded-lg text-sm text-slate-900 dark:text-slate-50 bg-white dark:bg-slate-800"
          />
        </div>
      </div>

      <div className="mt-4">
        <label className="block text-xs font-semibold text-slate-600 dark:text-slate-300 mb-1 uppercase tracking-wide" htmlFor="patient_ids_834">
          Patient IDs to enroll
        </label>
        <textarea
          id="patient_ids_834"
          rows={3}
          value={patientIdsRaw}
          onChange={(e) => setPatientIdsRaw(e.target.value)}
          placeholder="e.g. 3, 4, 5"
          className="w-full px-3 py-2.5 border border-slate-200 dark:border-slate-700 rounded-lg text-sm text-slate-900 dark:text-slate-50 bg-white dark:bg-slate-800 font-mono"
        />
        <div className="text-xs text-slate-600 dark:text-slate-300 mt-1">
          {patientIds.length} patient{patientIds.length === 1 ? "" : "s"} parsed
        </div>
      </div>

      <div className="mt-4 flex justify-end">
        <button
          type="button"
          onClick={submit}
          disabled={busy || patientIds.length === 0}
          className="bg-blue-600 text-white border-none rounded-lg px-[18px] py-2.5 font-semibold text-sm cursor-pointer inline-flex items-center gap-2 disabled:opacity-60"
        >
          {busy ? <Loader2 size={16} className="animate-spin" /> : <FileText size={16} />}
          Generate 834
        </button>
      </div>

      {error && (
        <div className="bg-red-50 dark:bg-red-950 border border-red-600 dark:border-red-500 rounded-[10px] p-5 mt-4">
          <div className="text-red-600 dark:text-red-400 flex items-center gap-2">
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
}): React.JSX.Element {
  const { block, confirm, setConfirm, reason, setReason, onForce, onCancel, busy } = props;
  const ready = confirm.trim() === "OVERRIDE" && reason.trim().length >= 10;
  return (
    <div className="bg-amber-50 dark:bg-amber-950 border border-amber-600 dark:border-amber-500 rounded-[10px] p-5 mt-4">
      <h3 className="text-amber-600 dark:text-amber-400 text-base font-bold m-0 flex gap-2 items-center">
        <AlertTriangle size={18} /> HIGH-severity findings — override required
      </h3>
      <p className="text-slate-900 dark:text-slate-50 text-sm mt-2">
        {block.high_severity_total} HIGH-severity issue
        {block.high_severity_total === 1 ? "" : "s"} blocked these patient IDs:{" "}
        <code>{block.failed_patient_ids.join(", ")}</code>
      </p>
      <details className="mt-2">
        <summary className="cursor-pointer text-[13px] text-slate-600 dark:text-slate-300">
          View findings
        </summary>
        <ul className="text-[13px] text-slate-900 dark:text-slate-50">
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
      <div className="mt-3">
        <label className="block text-xs font-semibold text-slate-600 dark:text-slate-300 mb-1 uppercase tracking-wide" htmlFor="override_reason">Override Reason (≥ 10 chars)</label>
        <textarea
          id="override_reason"
          rows={2}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="w-full px-3 py-2.5 border border-slate-200 dark:border-slate-700 rounded-lg text-sm text-slate-900 dark:text-slate-50 bg-white dark:bg-slate-800"
        />
      </div>
      <div className="mt-3">
        <label className="block text-xs font-semibold text-slate-600 dark:text-slate-300 mb-1 uppercase tracking-wide" htmlFor="override_typed">
          Type <code>OVERRIDE</code> to confirm
        </label>
        <input
          id="override_typed"
          value={confirm}
          onChange={(e) => setConfirm(e.target.value)}
          className="w-full px-3 py-2.5 border border-slate-200 dark:border-slate-700 rounded-lg text-sm text-slate-900 dark:text-slate-50 bg-white dark:bg-slate-800"
        />
      </div>
      <div className="mt-3 flex gap-2 justify-end">
        <button
          type="button"
          onClick={onCancel}
          className="bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-50 border border-slate-200 dark:border-slate-700 rounded-lg px-3.5 py-2 cursor-pointer"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={onForce}
          disabled={!ready || busy}
          className="bg-red-600 text-white border-none rounded-lg px-4 py-2.5 font-semibold text-sm cursor-pointer inline-flex items-center gap-2 disabled:opacity-60"
        >
          {busy ? <Loader2 size={16} className="animate-spin" /> : <AlertTriangle size={16} />}
          Override &amp; Generate
        </button>
      </div>
    </div>
  );
}

function ResultPanel({ result }: { result: GenerateResponse }): React.JSX.Element {
  return (
    <div className="bg-green-50 dark:bg-green-950 border border-green-600 dark:border-green-500 rounded-[10px] p-5 mt-4">
      <h3 className="text-green-600 dark:text-green-400 text-base font-bold m-0 flex gap-2 items-center">
        <CheckCircle size={18} /> {result.transaction} generated
      </h3>
      <dl className="text-[13px] text-slate-900 dark:text-slate-50 mt-3">
        <div><strong>File ID:</strong> <code>{result.file_id}</code></div>
        <div><strong>Records:</strong> {result.total_encounters}</div>
        <div><strong>Size:</strong> {result.file_size.toLocaleString()} bytes</div>
        <div><strong>SHA-256:</strong> <code className="text-[11px]">{result.sha256}</code></div>
        {result.override_applied && (
          <div className="text-amber-600 dark:text-amber-400">
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
        className="inline-flex items-center gap-2 mt-3 px-[18px] py-2.5 bg-green-600 text-white rounded-lg font-semibold no-underline"
      >
        <Download size={16} /> Download {result.transaction} file
      </a>
    </div>
  );
}
