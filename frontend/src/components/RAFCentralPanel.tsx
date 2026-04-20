"use client";

/**
 * RAFCentralPanel
 * ---------------
 * Unified RAF intelligence side-panel consumed by:
 *   - the patient detail page (inline)
 *   - the /embed/raf-central/[pid] route (iframed into OpenEMR)
 *
 * Single source of data: GET /api/raf-central/{pid}
 *
 * Renders six action-first accordions:
 *   - LIVE RAF bar (top strip, always visible)
 *   - MEAT gaps      (compliance risk, top priority)
 *   - Suspect conds  (RAF lift opportunity)
 *   - HCC recapture  (prior-year loss)
 *   - Audit readiness (documentation risk score)
 *   - Financial impact (revenue breakdown)
 *
 * Every interactive button calls an action endpoint, re-fetches the panel
 * on success, and keeps the user in context — no page reload, no modal.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useToast } from "@/components/Toast";
import api from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { OrderLabButton } from "@/components/OrderLabButton";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  ChevronDown,
  AlertTriangle,
  Sparkles,
  History,
  ClipboardCheck,
  DollarSign,
  Check,
  CheckCircle2,
  XCircle,
  RefreshCcw,
  Loader2,
  HelpCircle,
  X,
  TrendingUp,
  TrendingDown,
  Minus,
  Inbox,
  Info,
  MoreHorizontal,
  ArrowRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import StartTreatmentButton from "@/components/StartTreatmentButton";
import ExplainPanel from "@/components/ExplainPanel";

// ---------------------------------------------------------------------------
// Types — mirror backend response (see app/routers/raf_central.py)
// ---------------------------------------------------------------------------

export interface LiveRAFBar {
  current: number;
  prior_year: number | null;
  delta: number | null;
  hcc_count: number;
  model_segment: string;
  model_version: string;
  year: number;
}

export interface MEATGap {
  patient_hcc_id: number | null;
  hcc: string;
  icd10_codes: string[];
  label: string;
  coefficient: number;
  status: "COMPLETE" | "PARTIAL" | "MISSING" | "NOT_COMPLIANT";
  gaps: { monitor: boolean; evaluate: boolean; assess: boolean; treat: boolean };
}

export interface SuspectCard {
  id: number;
  hcc: number;
  icd10: string;
  label: string;
  confidence: number;
  evidence_type: string;
  trigger: string;
  status: string;
}

export interface RecaptureCard {
  id: number;
  hcc: string;
  icd10: string;
  label: string;
  prior_year: number;
  current_year: number;
  revenue_at_risk: number;
  last_encounter_date: string | null;
}

export interface AuditReadiness {
  meat_compliance_pct: number;
  hccs_compliant: number;
  hccs_total: number;
  risk_level: "LOW" | "MEDIUM" | "HIGH";
}

export interface FinancialImpact {
  current_raf: number;
  projected_raf: number;
  current_annual: number;
  projected_annual: number;
  pmpm_delta: number;
  annual_delta: number;
  revenue_per_raf_point: number;
}

/** Mirrors backend CodingOptCard Pydantic model (app/routers/raf_central.py). */
export interface CodingOptCard {
  current_icd10: string;
  current_label: string;
  suggested_icd10: string;
  suggested_label: string;
  raf_impact: number;
  source: string;
}

export interface RAFCentralPayload {
  patient_id: number;
  measurement_year: number;
  generated_at: string;
  raf_score: LiveRAFBar;
  meat_gaps: MEATGap[];
  suspects: SuspectCard[];
  recapture: RecaptureCard[];
  coding_opt: CodingOptCard[];
  audit_readiness: AuditReadiness;
  financial_impact: FinancialImpact;
}

// ---------------------------------------------------------------------------
// Dismiss reason codes — single source of truth for UI labels ↔ API values
// ---------------------------------------------------------------------------

export const DISMISS_REASONS = {
  not_clinically_supported: "Not clinically supported",
  already_documented: "Already documented under different code",
  patient_transferred: "Patient transferred",
  clinical_override: "Clinical judgment override",
  other: "Other",
} as const;

export type DismissReasonCode = keyof typeof DISMISS_REASONS;

// ---------------------------------------------------------------------------
// Tooltip — lightweight, no extra dependency
// ---------------------------------------------------------------------------
function Tooltip({ text, children }: { text: string; children: React.ReactNode }) {
  const [show, setShow] = useState(false);
  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
      onFocus={() => setShow(true)}
      onBlur={() => setShow(false)}
    >
      {children}
      {show && (
        <span className="pointer-events-none absolute bottom-full left-1/2 z-50 mb-1.5 -translate-x-1/2 whitespace-nowrap rounded bg-popover px-2 py-1 text-[11px] text-popover-foreground shadow-md border">
          {text}
        </span>
      )}
    </span>
  );
}

// ---------------------------------------------------------------------------
// MEATAttestationDialog — replaces window.prompt for MEAT attestation
// ---------------------------------------------------------------------------

interface MEATAttestationDialogProps {
  open: boolean;
  hcc: string;
  label: string;
  missingLabel: string;
  placeholder?: string;
  onCancel: () => void;
  onSubmit: (note: string) => void;
}

function MEATAttestationDialog({
  open,
  hcc,
  label,
  missingLabel,
  placeholder,
  onCancel,
  onSubmit,
}: MEATAttestationDialogProps) {
  const [note, setNote] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Reset note when dialog opens; autofocus textarea
  useEffect(() => {
    if (open) {
      setNote("");
      requestAnimationFrame(() => textareaRef.current?.focus());
    }
  }, [open]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      const trimmed = note.trim();
      if (trimmed) onSubmit(trimmed);
    }
  };

  const handleSubmit = () => {
    const trimmed = note.trim();
    if (trimmed) onSubmit(trimmed);
  };

  const defaultPlaceholder =
    placeholder ||
    `e.g., Patient on medication for HCC ${hcc}, condition monitored quarterly, no acute complications.`;

  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onCancel(); }}>
      <DialogContent showCloseButton={false} className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>MEAT Attestation — HCC {hcc}</DialogTitle>
        </DialogHeader>
        <div className="space-y-2 py-1">
          <p className="text-xs text-muted-foreground">
            <span className="font-semibold">{label}</span>
            {missingLabel && (
              <> — missing: <span className="font-medium">{missingLabel}</span></>
            )}
          </p>
          <textarea
            ref={textareaRef}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={defaultPlaceholder}
            rows={4}
            className="w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label="Clinician attestation note"
          />
          <p className="text-[10px] text-muted-foreground">
            Cmd+Enter / Ctrl+Enter to submit. Already-documented MEAT letters will not be overwritten.
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={!note.trim()}>
            Submit attestation
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// DismissReasonDialog — structured reason picker before dismissing a suspect
// ---------------------------------------------------------------------------

interface DismissReasonDialogProps {
  open: boolean;
  suspectLabel: string;
  onCancel: () => void;
  onSubmit: (reason: string) => void;
}

function DismissReasonDialog({ open, suspectLabel, onCancel, onSubmit }: DismissReasonDialogProps) {
  const [selected, setSelected] = useState<DismissReasonCode>("not_clinically_supported");
  const [otherText, setOtherText] = useState("");
  const otherTextareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (open) {
      setSelected("not_clinically_supported");
      setOtherText("");
    }
  }, [open]);

  useEffect(() => {
    if (selected === "other") {
      requestAnimationFrame(() => otherTextareaRef.current?.focus());
    }
  }, [selected]);

  const isValid = selected !== "other" || otherText.trim().length > 0;

  const handleSubmit = () => {
    if (!isValid) return;
    const reason =
      selected === "other"
        ? `other: ${otherText.trim()}`
        : `${selected}: ${DISMISS_REASONS[selected]}`;
    onSubmit(reason);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onCancel(); }}>
      <DialogContent showCloseButton={false} className="sm:max-w-sm" onKeyDown={handleKeyDown}>
        <DialogHeader>
          <DialogTitle>Dismiss reason</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 py-1">
          <p className="text-xs text-muted-foreground line-clamp-1">{suspectLabel}</p>
          <fieldset className="space-y-2">
            <legend className="sr-only">Select a dismiss reason</legend>
            {(Object.entries(DISMISS_REASONS) as [DismissReasonCode, string][]).map(([code, label]) => (
              <label
                key={code}
                className={cn(
                  "flex items-center gap-2.5 rounded-md border px-3 py-2 text-sm cursor-pointer transition-colors",
                  selected === code
                    ? "border-primary bg-primary/5"
                    : "border-border hover:bg-muted/50"
                )}
              >
                <input
                  type="radio"
                  name="dismiss-reason"
                  value={code}
                  checked={selected === code}
                  onChange={() => setSelected(code)}
                  className="accent-primary"
                />
                {label}
              </label>
            ))}
          </fieldset>
          {selected === "other" && (
            <textarea
              ref={otherTextareaRef}
              value={otherText}
              onChange={(e) => setOtherText(e.target.value)}
              placeholder="Describe the reason…"
              rows={3}
              className="w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label="Other dismiss reason"
            />
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={handleSubmit} disabled={!isValid}>
            Dismiss suspect
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// RAFGauge — SVG circular progress ring (point 1)
// ---------------------------------------------------------------------------
function RAFGauge({
  score,
  delta,
  year,
}: {
  score: number;
  delta: number | null;
  year: number;
}) {
  const [animated, setAnimated] = useState(false);
  useEffect(() => {
    const t = requestAnimationFrame(() => setAnimated(true));
    return () => cancelAnimationFrame(t);
  }, []);

  const size = 140;
  const strokeWidth = 10;
  const r = (size - strokeWidth) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * r;
  // Max displayable score is 2.5
  const pct = Math.min(score / 2.5, 1);
  const dashOffset = circumference * (1 - (animated ? pct : 0));

  const deltaSign = delta !== null && delta >= 0 ? "+" : "";
  const deltaColor =
    delta === null ? "text-muted-foreground" : delta > 0 ? "text-emerald-500" : "text-red-500";

  return (
    <div className="flex flex-col items-center gap-1" aria-label={`RAF score ${score.toFixed(3)}`}>
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
          <defs>
            <linearGradient id="rafRingGrad" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor="#06b6d4" />
              <stop offset="100%" stopColor="#10b981" />
            </linearGradient>
          </defs>
          {/* Track */}
          <circle
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            stroke="currentColor"
            strokeWidth={strokeWidth}
            className="text-muted/40"
          />
          {/* Progress arc */}
          <circle
            cx={cx}
            cy={cy}
            r={r}
            fill="none"
            stroke="url(#rafRingGrad)"
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
            style={{ transition: "stroke-dashoffset 1s cubic-bezier(0.34,1.56,0.64,1)" }}
          />
        </svg>
        {/* Center text — rotated back upright */}
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-[10px] font-medium uppercase tracking-widest text-muted-foreground leading-none">
            PY{year}
          </span>
          <span className="text-4xl font-bold tabular-nums leading-tight text-foreground">
            {score.toFixed(2)}
          </span>
          <span className="text-[11px] tabular-nums text-muted-foreground leading-none">
            {score.toFixed(3)}
          </span>
        </div>
      </div>
      {/* Delta pill below ring */}
      {delta !== null && (
        <span
          className={cn(
            "inline-flex items-center gap-0.5 rounded-full px-2.5 py-0.5 text-xs font-semibold tabular-nums",
            delta > 0
              ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300"
              : delta < 0
              ? "bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300"
              : "bg-muted text-muted-foreground"
          )}
        >
          {delta > 0 ? (
            <TrendingUp className="h-3 w-3" aria-hidden />
          ) : delta < 0 ? (
            <TrendingDown className="h-3 w-3" aria-hidden />
          ) : (
            <Minus className="h-3 w-3" aria-hidden />
          )}
          <span className={deltaColor}>
            {deltaSign}{delta.toFixed(3)} vs prior
          </span>
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SparklineTrend — 3-point SVG sparkline (point 10)
// ---------------------------------------------------------------------------
function SparklineTrend({
  prior,
  current,
  projected,
}: {
  prior: number;
  current: number;
  projected: number;
}) {
  const w = 44;
  const h = 20;
  const values = [prior, current, projected];
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const xs = [0, w / 2, w];
  const ys = values.map((v) => h - ((v - min) / range) * (h - 4) - 2);
  const polyline = xs.map((x, i) => `${x},${ys[i]}`).join(" ");
  const areaPath = `M${xs[0]},${ys[0]} L${xs[1]},${ys[1]} L${xs[2]},${ys[2]} L${w},${h} L0,${h} Z`;

  return (
    <svg
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      aria-label="RAF trend sparkline"
      className="flex-shrink-0"
    >
      <defs>
        <linearGradient id="sparkFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#64748b" stopOpacity="0.25" />
          <stop offset="100%" stopColor="#64748b" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill="url(#sparkFill)" />
      <polyline
        points={polyline}
        fill="none"
        stroke="#64748b"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {/* terminal dot */}
      <circle cx={xs[2]} cy={ys[2]} r="2" fill="#64748b" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// AuditDonut — SVG donut chart (point 2)
// ---------------------------------------------------------------------------
function AuditDonut({
  compliant,
  total,
  riskLevel,
}: {
  compliant: number;
  total: number;
  riskLevel: "LOW" | "MEDIUM" | "HIGH";
}) {
  const [animated, setAnimated] = useState(false);
  useEffect(() => {
    const t = requestAnimationFrame(() => setAnimated(true));
    return () => cancelAnimationFrame(t);
  }, []);

  const size = 88;
  const strokeWidth = 9;
  const r = (size - strokeWidth) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * r;
  const pct = total > 0 ? compliant / total : 0;
  const pctNum = Math.round(pct * 100);
  const dashOffset = circumference * (1 - (animated ? pct : 0));

  // Color semantics: emerald ≥90%, amber 70–89%, red <70%
  const arcColor =
    pctNum >= 90 ? "#10b981" : pctNum >= 70 ? "#f59e0b" : "#ef4444";
  const riskBg =
    pctNum >= 90
      ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300"
      : pctNum >= 70
      ? "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300"
      : "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300";

  return (
    <div className="flex items-center gap-4">
      <div className="relative flex-shrink-0" style={{ width: size, height: size }}>
        <svg width={size} height={size} className="-rotate-90" aria-hidden="true">
          <circle
            cx={cx} cy={cy} r={r}
            fill="none" stroke="currentColor"
            strokeWidth={strokeWidth}
            className="text-muted/40"
          />
          <circle
            cx={cx} cy={cy} r={r}
            fill="none"
            stroke={arcColor}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
            style={{ transition: "stroke-dashoffset 0.9s ease-out" }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-lg font-bold tabular-nums text-foreground leading-none">
            {pctNum}%
          </span>
          <span className="text-[10px] text-muted-foreground leading-tight">
            {compliant}/{total}
          </span>
        </div>
      </div>
      <div className="flex flex-col gap-1.5">
        <div className="text-xs text-muted-foreground">MEAT compliance</div>
        <div className="text-sm font-bold text-foreground">
          {compliant}/{total} HCCs
        </div>
        <span className={cn("inline-flex w-fit rounded-full px-2.5 py-0.5 text-[10px] font-bold uppercase tracking-wide", riskBg)}>
          {pctNum >= 90 ? "LOW" : pctNum >= 70 ? "MEDIUM" : "HIGH"} RISK
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// FinancialAreaChart — 2-point SVG area chart (point 3)
// ---------------------------------------------------------------------------
function FinancialAreaChart({
  current,
  projected,
}: {
  current: number;
  projected: number;
}) {
  const w = 100;
  const h = 44;
  const pad = 4;
  const min = Math.min(current, projected) * 0.97;
  const max = projected * 1.02;
  const range = max - min || 1;
  const toY = (v: number) => h - pad - ((v - min) / range) * (h - pad * 2);

  const x0 = pad;
  const x1 = w - pad;
  const y0 = toY(current);
  const y1 = toY(projected);

  const path = `M${x0},${y0} C${(x0 + x1) / 2},${y0} ${(x0 + x1) / 2},${y1} ${x1},${y1}`;
  const area = `M${x0},${y0} C${(x0 + x1) / 2},${y0} ${(x0 + x1) / 2},${y1} ${x1},${y1} L${x1},${h} L${x0},${h} Z`;

  return (
    <svg
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      aria-label="Financial uplift area chart"
      className="w-full"
    >
      <defs>
        <linearGradient id="finAreaGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#64748b" stopOpacity="0.18" />
          <stop offset="100%" stopColor="#64748b" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <path d={area} fill="url(#finAreaGrad)" />
      <path d={path} fill="none" stroke="#64748b" strokeWidth="2" strokeLinecap="round" />
      <circle cx={x0} cy={y0} r="3" fill="#94a3b8" />
      <circle cx={x1} cy={y1} r="3" fill="#475569" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// SemiGauge — semicircle SVG confidence gauge (point 4)
// ---------------------------------------------------------------------------
function SemiGauge({
  value,
  color,
}: {
  value: number; // 0-100
  color: "emerald" | "amber" | "red";
}) {
  const [animated, setAnimated] = useState(false);
  useEffect(() => {
    const t = requestAnimationFrame(() => setAnimated(true));
    return () => cancelAnimationFrame(t);
  }, []);

  const w = 80;
  const h = 44;
  const strokeWidth = 8;
  const r = (w - strokeWidth) / 2;
  const cx = w / 2;
  const cy = h - 2;
  // Semicircle: from 180° to 0° (top arc)
  const circumference = Math.PI * r; // half circle
  const pct = value / 100;
  const dashOffset = circumference * (1 - (animated ? pct : 0));

  const strokeColor =
    color === "emerald" ? "#10b981" : color === "amber" ? "#f59e0b" : "#ef4444";

  return (
    <div className="flex flex-col items-center" style={{ width: w }}>
      <svg
        width={w}
        height={h}
        viewBox={`0 0 ${w} ${h}`}
        aria-label={`Confidence ${value}%`}
        aria-valuenow={value}
      >
        {/* Track — semicircle */}
        <path
          d={`M${strokeWidth / 2},${cy} A${r},${r} 0 0,1 ${w - strokeWidth / 2},${cy}`}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          className="text-muted/40"
          strokeLinecap="round"
        />
        {/* Arc fill */}
        <path
          d={`M${strokeWidth / 2},${cy} A${r},${r} 0 0,1 ${w - strokeWidth / 2},${cy}`}
          fill="none"
          stroke={strokeColor}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          style={{ transition: "stroke-dashoffset 0.8s ease-out" }}
        />
      </svg>
      <span
        className="text-base font-bold tabular-nums -mt-2 leading-none"
        style={{ color: strokeColor }}
      >
        {value}%
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// MEATProgressBar — thin completion bar per HCC card (point 5)
// ---------------------------------------------------------------------------
function MEATProgressBar({ gaps }: { gaps: MEATGap["gaps"] }) {
  const total = 4;
  const done = [gaps.monitor, gaps.evaluate, gaps.assess, gaps.treat].filter(Boolean).length;
  const pct = (done / total) * 100;
  const barColor =
    done === 4
      ? "bg-emerald-500"
      : done >= 1
      ? "bg-amber-500"
      : "bg-red-400";

  return (
    <div className="mt-2">
      <div className="h-1 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-[width] duration-700", barColor)}
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={done}
          aria-valuemin={0}
          aria-valuemax={total}
          aria-label={`MEAT completion ${done}/4`}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export function RAFCentralPanel({
  patientId,
  year,
  embedded = false,
  onClose,
  layout = "panel",
}: {
  patientId: number;
  year?: number;
  embedded?: boolean;
  onClose?: () => void;
  layout?: "dashboard" | "panel";
}) {
  const [data, setData] = useState<RAFCentralPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [recalcing, setRecalcing] = useState(false);
  const [cardsVisible, setCardsVisible] = useState(false);
  const meatRef = useRef<HTMLDivElement>(null);
  // Track first mount for stagger animation (point 8)
  const mountedOnce = useRef(false);

  // Persist dashMeatFilter via URL search param "meatFilter"
  const router = useRouter();
  const searchParams = useSearchParams();
  const MEAT_FILTER_PARAM = "meatFilter";
  const VALID_MEAT_FILTERS: MeatFilter[] = ["all", "incomplete", "high-impact"];

  const initialFilter = (() => {
    const raw = searchParams.get(MEAT_FILTER_PARAM);
    return VALID_MEAT_FILTERS.includes(raw as MeatFilter) ? (raw as MeatFilter) : "all";
  })();

  const [dashMeatFilter, setDashMeatFilterState] = useState<MeatFilter>(initialFilter);

  const setDashMeatFilter = useCallback(
    (f: MeatFilter) => {
      setDashMeatFilterState(f);
      const params = new URLSearchParams(searchParams.toString());
      params.set(MEAT_FILTER_PARAM, f);
      router.replace(`?${params.toString()}`, { scroll: false });
    },
    [router, searchParams]
  );

  const fetchPanel = useCallback(async () => {
    try {
      setError(null);
      const url = `/api/raf-central/${patientId}${year ? `?year=${year}` : ""}`;
      const res = await api.get<RAFCentralPayload>(url);
      setData(res.data);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to load RAF Central";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [patientId, year]);

  useEffect(() => {
    fetchPanel();
  }, [fetchPanel]);

  // Trigger stagger only on first data load
  useEffect(() => {
    if (data && !mountedOnce.current) {
      mountedOnce.current = true;
      requestAnimationFrame(() => setCardsVisible(true));
    }
  }, [data]);

  const recalc = useCallback(async () => {
    setRecalcing(true);
    try {
      await api.post(`/api/raf-central/${patientId}/actions/recalculate${year ? `?year=${year}` : ""}`);
      await fetchPanel();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Recalculation failed";
      setError(msg);
    } finally {
      setRecalcing(false);
    }
  }, [patientId, year, fetchPanel]);

  if (loading && !data) {
    return (
      <div className={cn("flex h-full items-center justify-center", embedded && "min-h-[200px]")}>
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="p-4 text-sm text-red-600">
        <AlertTriangle className="inline h-4 w-4 mr-1" />
        {error}
      </div>
    );
  }

  if (!data) return null;

  const incompleteGaps = data.meat_gaps.filter((g) => g.status !== "COMPLETE");
  const openSuspects = data.suspects.filter((s) => s.status !== "dismissed");

  const actionCount = incompleteGaps.length + openSuspects.length;

  const scrollToMeat = () => {
    meatRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  // ── Dashboard layout (in-app tab, ≥1024px two-column) ─────────────────────
  if (layout === "dashboard") {
    // Stagger helper (point 8)
    const stagger = (delay: string) =>
      cn(
        "transition-all duration-500",
        cardsVisible
          ? "opacity-100 translate-y-0"
          : "opacity-0 translate-y-3",
        delay
      );

    return (
      <div className="flex flex-col min-h-full bg-muted/30 dark:bg-background">
        {/* ── Top strip: patient header + RAF gauge + controls ─────────── */}
        {/* point 9: subtle gradient on header */}
        <header className="border-b bg-gradient-to-br from-background to-muted/40 dark:from-background dark:to-muted/20 px-6 py-5 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-4">
            {/* Left: RAF gauge hero (point 1) + identity */}
            <div className="flex items-center gap-6">
              <RAFGauge
                score={data.raf_score.current}
                delta={data.raf_score.delta}
                year={data.raf_score.year}
              />
              <div>
                <div className="text-[10px] font-medium uppercase tracking-widest text-muted-foreground">
                  RAF Intelligence
                </div>
                {/* point 6: ~20% bigger patient identity */}
                <div className="mt-0.5 text-xl font-bold text-foreground">
                  Patient {data.patient_id}
                  <span className="ml-2 text-base font-normal text-muted-foreground">
                    · PY{data.measurement_year}
                  </span>
                </div>
                {/* Sparkline trend (point 10) */}
                {data.raf_score.prior_year !== null && (
                  <div className="mt-2 flex items-center gap-2">
                    <SparklineTrend
                      prior={data.raf_score.prior_year}
                      current={data.raf_score.current}
                      projected={data.financial_impact.projected_raf}
                    />
                    <span className="text-[11px] text-muted-foreground">
                      prior → current → projected
                    </span>
                  </div>
                )}
                <div className="mt-2 flex items-center gap-3 text-xs text-muted-foreground">
                  <span className="font-medium">{data.raf_score.hcc_count} HCCs</span>
                  <span className="text-border">·</span>
                  <span>{data.raf_score.model_segment}</span>
                  <span className="text-border">·</span>
                  <span className="uppercase">{data.raf_score.model_version}</span>
                </div>
              </div>
            </div>

            {/* Right: recalc button */}
            <div className="flex items-center gap-2 self-start">
              <Button
                size="sm"
                variant="outline"
                onClick={recalc}
                disabled={recalcing}
                aria-label="Force RAF recalculation"
              >
                <RefreshCcw className={cn("h-4 w-4 mr-1.5", recalcing && "animate-spin")} />
                Recalculate
              </Button>
              {onClose ? (
                <Button size="sm" variant="ghost" onClick={onClose} aria-label="Close panel">
                  <X className="h-4 w-4" />
                </Button>
              ) : null}
            </div>
          </div>

          {/* Next Best Action banner */}
          {actionCount > 0 && (
            <button
              onClick={scrollToMeat}
              className="mt-4 flex w-full items-center justify-between gap-3 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-left hover:bg-emerald-100 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:border-emerald-800 dark:bg-emerald-950/40 dark:hover:bg-emerald-950/60"
              aria-label={`Review ${actionCount} documentation gaps`}
            >
              <span className="flex items-center gap-2.5 min-w-0">
                <span className="inline-flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-emerald-500 text-white shadow-sm">
                  <Check className="h-3.5 w-3.5" aria-hidden />
                </span>
                <span className="text-sm font-semibold text-emerald-800 dark:text-emerald-200">
                  {actionCount} gap{actionCount !== 1 ? "s" : ""} require
                  {actionCount === 1 ? "s" : ""} documentation review
                </span>
              </span>
              <span className="flex-shrink-0 text-xs font-semibold text-emerald-700 dark:text-emerald-300">
                Scroll to MEAT Gaps
              </span>
            </button>
          )}
        </header>

        {/* ── Two-column body ─────────────────────────────────────────────── */}
        <div className="flex flex-1 flex-col lg:grid lg:grid-cols-[3fr_2fr] lg:items-start gap-6 p-6">
          {/* LEFT: primary workspace */}
          <div className="flex flex-col gap-6 min-w-0">
            {/* ── MEAT Gaps — primary workspace card ──────────────────── */}
            <div
              ref={meatRef}
              className={cn(
                "rounded-lg border border-t-[3px] border-t-red-500 bg-card shadow-sm hover:shadow-md transition-shadow overflow-hidden",
                stagger("delay-100")
              )}
            >
              {/* Header with filter in-line — Issue #5 */}
              <div className="flex items-center gap-2 px-5 py-3.5 border-b bg-card">
                <AlertTriangle className="h-4 w-4 text-red-500 flex-shrink-0" aria-hidden />
                <span className="text-base font-bold">MEAT Gaps</span>
                <Badge
                  className={cn(
                    "ml-1 text-[10px] font-semibold border-0",
                    data.meat_gaps.length === 0
                      ? "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400"
                      : "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300"
                  )}
                >
                  {data.meat_gaps.length}
                </Badge>
                {/* Filter moved into header row */}
                <div className="ml-auto relative">
                  <select
                    value={dashMeatFilter}
                    onChange={(e) => setDashMeatFilter(e.target.value as MeatFilter)}
                    className="appearance-none rounded-md border border-border bg-background pl-2.5 pr-7 py-1 text-xs font-medium text-foreground hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
                    aria-label="Filter MEAT gaps"
                  >
                    <option value="all">All gaps</option>
                    <option value="incomplete">Incomplete only</option>
                    <option value="high-impact">High impact first</option>
                  </select>
                  <ChevronDown className="pointer-events-none absolute right-1.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
                </div>
              </div>
              <div className="px-4 py-4">
                <MEATSection
                  patientId={patientId}
                  year={year}
                  gaps={data.meat_gaps}
                  onChange={fetchPanel}
                  filter={dashMeatFilter}
                  onFilterChange={setDashMeatFilter}
                />
              </div>
            </div>

            {/* ── Suspect Conditions ───────────────────────────────────── */}
            <div
              className={cn(
                "rounded-lg border border-t-[3px] border-t-amber-400 bg-card shadow-sm hover:shadow-md transition-shadow overflow-hidden",
                stagger("delay-200")
              )}
            >
              <div className="flex items-center gap-2 px-5 py-3.5 border-b bg-card">
                <Sparkles className="h-4 w-4 text-amber-500 flex-shrink-0" aria-hidden />
                <span className="text-sm font-semibold text-muted-foreground">Suspect Conditions</span>
                <Badge
                  className={cn(
                    "ml-1 text-[10px] font-semibold border-0",
                    data.suspects.length === 0
                      ? "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400"
                      : "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300"
                  )}
                >
                  {data.suspects.length}
                </Badge>
              </div>
              <div className="px-5 py-4">
                <SuspectsSection
                  patientId={patientId}
                  suspects={data.suspects}
                  onChange={fetchPanel}
                />
              </div>
            </div>
          </div>

          {/* ── RIGHT: secondary context (quieter) ──────────────────────── */}
          <div className="flex flex-col gap-4 min-w-0">
            {/* HCC Recapture — flat card, border-b only separators — Issue #1, #4 */}
            <div className={cn("rounded-lg bg-card overflow-hidden", stagger("delay-100"))}>
              <div className="flex items-center gap-2 px-4 py-3 border-b border-muted/40">
                <History className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" aria-hidden />
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">HCC Recapture</span>
                {data.recapture.length > 0 && (
                  <Badge className="ml-1 text-[10px] font-semibold border-0 bg-muted text-muted-foreground">
                    {data.recapture.length}
                  </Badge>
                )}
              </div>
              <div className="px-4 py-3">
                <RecaptureSection recapture={data.recapture} />
              </div>
            </div>

            {/* ── Performance card (merged Audit + Financial) — Issue #4 ── */}
            <div
              className={cn(
                "rounded-lg border bg-card shadow-sm overflow-hidden",
                stagger("delay-200")
              )}
            >
              <div className="flex items-center gap-2 px-4 py-3 border-b bg-card">
                <ClipboardCheck className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" aria-hidden />
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Performance</span>
              </div>
              <div className="px-4 py-3 space-y-4">
                {/* Top: MEAT compliance donut */}
                <AuditSection audit={data.audit_readiness} />
                {/* Divider */}
                <div className="border-t border-muted/40" />
                {/* Middle: current → projected with arrow */}
                <div className="flex items-center gap-3">
                  <div>
                    <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">Current annual</div>
                    <div className="text-sm font-bold tabular-nums">${data.financial_impact.current_annual.toLocaleString()}</div>
                  </div>
                  <ArrowRight className="h-4 w-4 text-muted-foreground flex-shrink-0" aria-hidden />
                  <div>
                    <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">Projected annual</div>
                    <div className="text-sm font-bold tabular-nums">${data.financial_impact.projected_annual.toLocaleString()}</div>
                  </div>
                </div>
                {/* Area chart */}
                {data.financial_impact.annual_delta > 0 && (
                  <FinancialAreaChart
                    current={data.financial_impact.current_annual}
                    projected={data.financial_impact.projected_annual}
                  />
                )}
                {/* Potential uplift callout */}
                {data.financial_impact.annual_delta > 0 && (
                  <div className="rounded-md border border-emerald-200 bg-emerald-50 dark:border-emerald-800 dark:bg-emerald-950/30 px-3 py-2">
                    <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">Potential uplift</div>
                    <div className="text-base font-bold tabular-nums text-foreground">
                      +${data.financial_impact.annual_delta.toLocaleString()}
                      <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                        {(
                          data.financial_impact.current_raf
                            ? ((data.financial_impact.projected_raf - data.financial_impact.current_raf) /
                                data.financial_impact.current_raf) *
                              100
                            : 0
                        ).toFixed(1)}
                        % · ${data.financial_impact.pmpm_delta.toLocaleString()}/mo
                      </span>
                    </div>
                  </div>
                )}
                <div className="text-[10px] text-muted-foreground">
                  ${data.financial_impact.revenue_per_raf_point.toLocaleString()}/RAF point · CMS MA benchmark
                </div>
              </div>
            </div>
          </div>
        </div>

        <footer className="border-t px-6 py-3 text-[10px] text-muted-foreground bg-background">
          Generated {new Date(data.generated_at).toLocaleString()}
        </footer>
      </div>
    );
  }

  // ── Panel layout (default — iframe embed, single-column accordion) ─────────
  return (
    <div className={cn("flex h-full flex-col", embedded ? "bg-background" : "")}>
      {/* Header */}
      <header className="flex items-center justify-between border-b px-4 py-3">
        <div>
          <div className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            RAF Intelligence
          </div>
          <div className="text-sm text-muted-foreground">
            Patient {data.patient_id} · PY{data.measurement_year}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="ghost"
            onClick={recalc}
            disabled={recalcing}
            aria-label="Force RAF recalculation"
          >
            <RefreshCcw className={cn("h-4 w-4", recalcing && "animate-spin")} />
          </Button>
          {onClose ? (
            <Button size="sm" variant="ghost" onClick={onClose} aria-label="Close panel">
              <X className="h-4 w-4" />
            </Button>
          ) : null}
        </div>
      </header>

      {/* LIVE RAF bar */}
      <LiveRAFSection raf={data.raf_score} />

      {/* Next Best Action banner — informational, subtle */}
      {actionCount > 0 && (
        <button
          onClick={scrollToMeat}
          className="mx-4 my-2 flex items-center justify-between gap-3 rounded-md border bg-card px-3 py-2 text-left hover:bg-muted/50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={`Review ${actionCount} documentation gaps`}
        >
          <span className="flex items-center gap-2 min-w-0">
            <span className="inline-flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-emerald-500 text-white">
              <Check className="h-3 w-3" aria-hidden />
            </span>
            <span className="text-xs font-medium text-foreground truncate">
              {actionCount} gap{actionCount !== 1 ? "s" : ""} require{actionCount === 1 ? "s" : ""} documentation review
            </span>
          </span>
          <span className="flex-shrink-0 text-[11px] font-medium text-muted-foreground">
            Review
          </span>
        </button>
      )}

      <div className="flex-1 overflow-y-auto divide-y">
        <div ref={meatRef}>
          <Section
            title="MEAT Gaps"
            icon={<AlertTriangle className="h-4 w-4 text-red-500" />}
            count={data.meat_gaps.length}
            severity="high"
            defaultOpen
          >
            <MEATSection
              patientId={patientId}
              year={year}
              gaps={data.meat_gaps}
              onChange={fetchPanel}
            />
          </Section>
        </div>

        <Section
          title="Suspect Conditions"
          icon={<Sparkles className="h-4 w-4 text-amber-500" />}
          count={data.suspects.length}
          severity="medium"
          defaultOpen
        >
          <SuspectsSection
            patientId={patientId}
            suspects={data.suspects}
            onChange={fetchPanel}
          />
        </Section>

        <Section
          title="HCC Recapture"
          icon={<History className="h-4 w-4 text-blue-500" />}
          count={data.recapture.length}
          severity="medium"
        >
          <RecaptureSection recapture={data.recapture} />
        </Section>

        <Section
          title="Audit Readiness"
          icon={<ClipboardCheck className="h-4 w-4 text-slate-500" />}
          severity={data.audit_readiness.risk_level === "HIGH" ? "high" : "low"}
        >
          <AuditSection audit={data.audit_readiness} />
        </Section>

        <Section
          title="Financial Impact"
          icon={<DollarSign className="h-4 w-4 text-slate-500" />}
          severity="low"
        >
          <FinancialSection financial={data.financial_impact} />
        </Section>
      </div>

      <footer className="border-t px-4 py-2 text-[10px] text-muted-foreground">
        Generated {new Date(data.generated_at).toLocaleString()}
      </footer>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section shell — collapsible, with count badge + severity color rail
// ---------------------------------------------------------------------------

function Section({
  title,
  icon,
  count,
  severity,
  defaultOpen = false,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  count?: number;
  severity: "high" | "medium" | "low";
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const rail =
    severity === "high"
      ? "border-l-red-500"
      : severity === "medium"
      ? "border-l-amber-400"
      : "border-l-slate-300 dark:border-l-slate-600";
  return (
    <div className={cn("border-l-4 bg-background", rail)}>
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center justify-between px-4 py-2.5 text-left hover:bg-muted/50 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
      >
        <div className="flex items-center gap-2">
          {icon}
          <span className="text-sm font-semibold">{title}</span>
          {count !== undefined ? (
            <Badge
              className={cn(
                "text-[10px] font-semibold border-0",
                count === 0
                  ? "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400"
                  : severity === "high"
                  ? "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300"
                  : severity === "medium"
                  ? "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300"
                  : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"
              )}
            >
              {count}
            </Badge>
          ) : null}
        </div>
        <ChevronDown
          className={cn(
            "h-4 w-4 text-muted-foreground transition-transform duration-200",
            open && "rotate-180"
          )}
        />
      </button>
      {open ? <div className="px-4 pb-4 pt-1 bg-muted/20 dark:bg-muted/10">{children}</div> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// LIVE RAF — top strip with score + delta (panel layout only)
// ---------------------------------------------------------------------------

function LiveRAFSection({
  raf,
  variant = "strip",
}: {
  raf: LiveRAFBar;
  variant?: "strip" | "inline";
}) {
  const deltaColor =
    raf.delta === null
      ? "text-muted-foreground"
      : raf.delta > 0
      ? "text-emerald-600"
      : raf.delta < 0
      ? "text-red-600"
      : "text-muted-foreground";
  const deltaSign = raf.delta !== null && raf.delta >= 0 ? "+" : "";
  const TrendIcon =
    raf.delta === null || raf.delta === 0
      ? Minus
      : raf.delta > 0
      ? TrendingUp
      : TrendingDown;

  const metrics = (
    <>
      {/* PY score — dominant */}
      <div className="flex-shrink-0">
        <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
          PY{raf.year}
        </div>
        <div className="text-2xl font-bold tabular-nums leading-tight">
          {raf.current.toFixed(3)}
        </div>
      </div>

      <Separator orientation="vertical" className="h-8 hidden sm:block" />

      {/* Secondary metrics — smaller */}
      <div className="flex gap-4 flex-wrap text-sm">
        <SmallMetric
          label="vs prior"
          value={raf.delta === null ? "—" : `${deltaSign}${raf.delta.toFixed(3)}`}
          valueClassName={deltaColor}
          icon={<TrendIcon className={cn("h-3 w-3", deltaColor)} aria-hidden />}
        />
        <SmallMetric label="HCCs" value={String(raf.hcc_count)} />
        <SmallMetric
          label="Model"
          value={`${raf.model_segment} · ${raf.model_version.toUpperCase()}`}
        />
      </div>
    </>
  );

  if (variant === "inline") {
    return (
      <div className="flex items-center gap-4 flex-wrap rounded-lg border bg-muted/40 px-4 py-3 dark:bg-muted/20">
        {metrics}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-4 border-b bg-muted/30 px-4 py-3 flex-wrap">
      {metrics}
    </div>
  );
}

function SmallMetric({
  label,
  value,
  valueClassName,
  icon,
}: {
  label: string;
  value: string;
  valueClassName?: string;
  icon?: React.ReactNode;
}) {
  return (
    <div>
      <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className={cn("flex items-center gap-0.5 text-sm font-semibold tabular-nums text-foreground", valueClassName)}>
        {icon}
        <span className="truncate">{value}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// MEAT Gaps — per-HCC card with 4 letter-dots + filter chips
// ---------------------------------------------------------------------------

type MeatFilter = "all" | "incomplete" | "high-impact";

function MEATSection({
  patientId,
  year,
  gaps,
  onChange,
  filter: filterProp,
  onFilterChange,
}: {
  patientId: number;
  year?: number;
  gaps: MEATGap[];
  onChange: () => void;
  filter?: MeatFilter;
  onFilterChange?: (f: MeatFilter) => void;
}) {
  const [filterInternal, setFilterInternal] = useState<MeatFilter>("all");
  const filter = filterProp ?? filterInternal;
  const setFilter = onFilterChange ?? setFilterInternal;

  if (!gaps.length)
    return (
      <EmptyState
        variant="success"
        title="All MEAT elements documented"
        subtitle="Accept a suspect below to add conditions requiring evidence."
      />
    );

  const filtered = gaps
    .filter((g) => {
      if (filter === "incomplete") return g.status !== "COMPLETE";
      return true;
    })
    .sort((a, b) => {
      if (filter === "high-impact") return b.coefficient - a.coefficient;
      return 0;
    });

  // Priority buckets: High ≥0.4, Medium 0.15–0.4, Low <0.15
  const high = filtered.filter((g) => g.coefficient >= 0.4);
  const medium = filtered.filter((g) => g.coefficient >= 0.15 && g.coefficient < 0.4);
  const low = filtered.filter((g) => g.coefficient < 0.15);

  const options: { id: MeatFilter; label: string }[] = [
    { id: "all", label: "All gaps" },
    { id: "incomplete", label: "Incomplete only" },
    { id: "high-impact", label: "High impact first" },
  ];

  function PriorityGroup({
    label,
    dotColor,
    items,
  }: {
    label: string;
    dotColor: string;
    items: MEATGap[];
  }) {
    if (items.length === 0) return null;
    return (
      <div>
        <div className="flex items-center gap-1.5 px-1 py-2">
          <span className={cn("h-2 w-2 rounded-full flex-shrink-0", dotColor)} aria-hidden />
          <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
            {label}
          </span>
        </div>
        <div className="rounded-md overflow-hidden border border-border/40">
          {items.map((g, idx) => (
            <MEATRow
              key={`${g.hcc}-${g.patient_hcc_id}`}
              gap={g}
              patientId={patientId}
              year={year}
              onChange={onChange}
              isOdd={idx % 2 === 1}
            />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <PriorityGroup label="High Priority" dotColor="bg-red-500" items={high} />
      <PriorityGroup label="Medium Priority" dotColor="bg-amber-500" items={medium} />
      <PriorityGroup label="Low Priority" dotColor="bg-slate-400" items={low} />
    </div>
  );
}

function MEATRow({
  gap,
  patientId,
  year,
  onChange,
  isOdd,
}: {
  gap: MEATGap;
  patientId: number;
  year?: number;
  onChange: () => void;
  isOdd: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [overflowOpen, setOverflowOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<"review" | "notes" | null>(null);

  const railColor =
    gap.coefficient >= 0.4
      ? "bg-red-500"
      : gap.coefficient >= 0.15
      ? "bg-amber-500"
      : "bg-slate-400";

  const doneCount = [gap.gaps.monitor, gap.gaps.evaluate, gap.gaps.assess, gap.gaps.treat].filter(
    Boolean
  ).length;
  const isComplete = gap.status === "COMPLETE";

  const statusLabel = isComplete
    ? "Complete"
    : gap.status === "PARTIAL"
    ? `Partial (${doneCount}/4)`
    : "Missing";
  const statusClass = isComplete
    ? "text-emerald-700 dark:text-emerald-400"
    : gap.status === "PARTIAL"
    ? "text-amber-700 dark:text-amber-400"
    : "text-red-700 dark:text-red-400";

  const missing = (Object.entries(gap.gaps) as [keyof MEATGap["gaps"], boolean][])
    .filter(([, on]) => !on)
    .map(([k]) => k);
  const missingLabel = missing.map((k) => k[0].toUpperCase() + k.slice(1)).join(", ");

  const submitMeat = async (note: string) => {
    if (!gap.patient_hcc_id) return;
    setBusy(true);
    setDialogMode(null);
    try {
      await api.post(`/api/raf-central/${patientId}/actions/mark-meat-reviewed`, {
        patient_hcc_id: gap.patient_hcc_id,
        monitor_note: gap.gaps.monitor ? null : note,
        evaluate_note: gap.gaps.evaluate ? null : note,
        assess_note: gap.gaps.assess ? null : note,
        treat_note: gap.gaps.treat ? null : note,
      });
      onChange();
    } finally {
      setBusy(false);
    }
  };

  const markReviewed = () => {
    if (!gap.patient_hcc_id || missing.length === 0) return;
    setDialogMode("review");
  };

  const addNotes = () => {
    if (!gap.patient_hcc_id) return;
    setDialogMode("notes");
  };

  return (
    <div
      className={cn(
        "relative flex items-center gap-3 py-3 pr-3 pl-0 transition-colors",
        isOdd ? "bg-muted/20 dark:bg-muted/10" : "bg-card"
      )}
    >
      {/* 4px severity rail */}
      <div className={cn("absolute left-0 top-0 bottom-0 w-1 rounded-sm flex-shrink-0", railColor)} aria-hidden />

      {/* MEAT dots — smaller */}
      <div className="ml-3 flex-shrink-0">
        <LetterDots gaps={gap.gaps} size="sm" />
      </div>

      {/* Identity + status */}
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-1.5 flex-wrap">
          <Tooltip text={`HCC ${gap.hcc} — ${gap.label}`}>
            <span className="text-xs font-bold cursor-default">HCC {gap.hcc}</span>
          </Tooltip>
          <span className="text-[11px] text-muted-foreground truncate max-w-[20ch]">{gap.label}</span>
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          <span className={cn("text-[11px] font-semibold", statusClass)}>{statusLabel}</span>
          <Tooltip text="Model coefficient contribution to RAF score">
            <span className="text-[10px] text-muted-foreground/70 tabular-nums cursor-default">
              coef {gap.coefficient.toFixed(3)}
            </span>
          </Tooltip>
        </div>
      </div>

      {/* Right-aligned actions */}
      <div className="flex items-center gap-1.5 flex-shrink-0">
        {!isComplete && gap.patient_hcc_id && (
          <>
            <Button
              size="sm"
              variant="default"
              onClick={markReviewed}
              disabled={busy}
              className="h-7 px-2.5 text-xs"
              aria-label={`Review HCC ${gap.hcc}`}
            >
              {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : "Review"}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={addNotes}
              disabled={busy}
              className="h-7 px-2.5 text-xs"
              aria-label={`Add notes for HCC ${gap.hcc}`}
            >
              Add Notes
            </Button>
            {/* Overflow: Order Lab + Start Treatment */}
            <div className="relative">
              <Button
                size="sm"
                variant="ghost"
                className="h-7 w-7 p-0"
                onClick={() => setOverflowOpen((o) => !o)}
                aria-label="More actions"
                aria-expanded={overflowOpen}
                aria-haspopup="menu"
              >
                <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
              </Button>
              {overflowOpen && (
                <div
                  className="absolute right-0 top-full mt-1 z-20 rounded-md border border-border bg-popover shadow-md py-1 min-w-[140px]"
                  role="menu"
                >
                  {!gap.gaps.monitor && (
                    <div role="menuitem" className="px-1 py-0.5">
                      <OrderLabButton
                        patientId={patientId}
                        hccCode={gap.hcc}
                        icd10={gap.icd10_codes[0] || ""}
                        onOrdered={() => { setOverflowOpen(false); onChange(); }}
                      />
                    </div>
                  )}
                  {!gap.gaps.treat && (
                    <div role="menuitem" className="px-1 py-0.5">
                      <StartTreatmentButton
                        patientId={patientId}
                        hccCode={gap.hcc}
                        icd10={gap.icd10_codes[0] ?? ""}
                        onStarted={() => { setOverflowOpen(false); onChange(); }}
                      />
                    </div>
                  )}
                  {gap.gaps.monitor && gap.gaps.treat && (
                    <div className="px-3 py-2 text-xs text-muted-foreground">No additional actions</div>
                  )}
                </div>
              )}
            </div>
          </>
        )}
        {isComplete && (
          <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-700 dark:text-emerald-400">
            <Check className="h-3 w-3" aria-hidden />
          </span>
        )}
      </div>

      {/* MEAT attestation dialog — replaces window.prompt */}
      <MEATAttestationDialog
        open={dialogMode !== null}
        hcc={gap.hcc}
        label={gap.label}
        missingLabel={dialogMode === "review" ? missingLabel : ""}
        onCancel={() => setDialogMode(null)}
        onSubmit={submitMeat}
      />
    </div>
  );
}

// MEATCard is kept for the panel layout (unchanged)
function MEATCard({
  gap,
  patientId,
  year,
  onChange,
}: {
  gap: MEATGap;
  patientId: number;
  year?: number;
  onChange: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);

  const missing = (Object.entries(gap.gaps) as [keyof MEATGap["gaps"], boolean][])
    .filter(([, on]) => !on)
    .map(([k]) => k);
  const missingLabel = missing.map((k) => k[0].toUpperCase() + k.slice(1)).join(", ");

  const submitMeat = async (note: string) => {
    if (!gap.patient_hcc_id) return;
    setBusy(true);
    setDialogOpen(false);
    try {
      await api.post(`/api/raf-central/${patientId}/actions/mark-meat-reviewed`, {
        patient_hcc_id: gap.patient_hcc_id,
        monitor_note: gap.gaps.monitor ? null : note,
        evaluate_note: gap.gaps.evaluate ? null : note,
        assess_note: gap.gaps.assess ? null : note,
        treat_note: gap.gaps.treat ? null : note,
      });
      onChange();
    } finally {
      setBusy(false);
    }
  };

  const markReviewed = () => {
    if (!gap.patient_hcc_id || missing.length === 0) return;
    setDialogOpen(true);
  };

  const isComplete = gap.status === "COMPLETE";

  return (
    <Card className="p-3 hover:bg-muted/50 transition-colors dark:hover:bg-muted/20">
      {/* Row 1: HCC code + ICD + label + status pill */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <Tooltip text={`HCC ${gap.hcc} — ${gap.label}`}>
              <span className="text-sm font-bold cursor-default">HCC {gap.hcc}</span>
            </Tooltip>
            <span className="text-muted-foreground select-none">·</span>
            <span className="text-xs text-muted-foreground font-normal">
              {gap.icd10_codes.slice(0, 3).join(", ")}
            </span>
          </div>
          <div className="mt-0.5 text-xs font-medium leading-relaxed text-foreground/80 truncate">
            {gap.label}
          </div>
        </div>

        {/* Status pill */}
        {isComplete ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300 flex-shrink-0">
            <Check className="h-3 w-3" aria-hidden /> Complete
          </span>
        ) : (
          <Badge
            className={cn(
              "text-[10px] font-semibold border-0 flex-shrink-0",
              gap.status === "PARTIAL"
                ? "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300"
                : "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300"
            )}
          >
            {gap.status}
          </Badge>
        )}
      </div>

      {/* Row 2: MEAT dots + coef */}
      <div className="mt-2 flex items-center gap-3">
        <LetterDots gaps={gap.gaps} />
        <Tooltip text="Model coefficient contribution to RAF score">
          <span className="inline-flex items-center gap-0.5 text-xs text-muted-foreground tabular-nums cursor-default">
            <Info className="h-3 w-3 text-muted-foreground/60" aria-hidden />
            coef {gap.coefficient.toFixed(3)}
          </span>
        </Tooltip>
      </div>

      {/* MEAT completion progress bar */}
      <MEATProgressBar gaps={gap.gaps} />

      {/* Actions */}
      {!isComplete && gap.patient_hcc_id ? (
        <div className="mt-2.5 flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={markReviewed} disabled={busy}>
            {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : "Mark reviewed"}
          </Button>
          {!gap.gaps.monitor ? (
            <OrderLabButton
              patientId={patientId}
              hccCode={gap.hcc}
              icd10={gap.icd10_codes[0] || ""}
              onOrdered={onChange}
            />
          ) : null}
          {!gap.gaps.treat ? (
            <StartTreatmentButton
              patientId={patientId}
              hccCode={gap.hcc}
              icd10={gap.icd10_codes[0] ?? ""}
              onStarted={onChange}
            />
          ) : null}
        </div>
      ) : null}

      {/* MEAT attestation dialog */}
      <MEATAttestationDialog
        open={dialogOpen}
        hcc={gap.hcc}
        label={gap.label}
        missingLabel={missingLabel}
        onCancel={() => setDialogOpen(false)}
        onSubmit={submitMeat}
      />
    </Card>
  );
}

function LetterDots({
  gaps,
  size = "md",
}: {
  gaps: MEATGap["gaps"];
  size?: "sm" | "md";
}) {
  const items = [
    { key: "monitor", letter: "M", on: "bg-cyan-500", label: "Monitor" },
    { key: "evaluate", letter: "E", on: "bg-indigo-500", label: "Evaluate" },
    { key: "assess", letter: "A", on: "bg-amber-500", label: "Assess" },
    { key: "treat", letter: "T", on: "bg-emerald-500", label: "Treat" },
  ] as const;
  const dim = size === "sm" ? "h-4 w-4 text-[9px]" : "h-5 w-5 text-[10px]";
  return (
    <div className="flex gap-1">
      {items.map(({ key, letter, on: onColor, label }) => {
        const on = gaps[key];
        return (
          <span
            key={key}
            title={on ? `${label} documented` : `${label} missing`}
            className={cn(
              "inline-flex items-center justify-center rounded-full font-bold transition-colors",
              dim,
              on
                ? `${onColor} text-white shadow-sm`
                : "bg-muted text-muted-foreground/60 ring-1 ring-inset ring-border"
            )}
          >
            {letter}
          </span>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Suspects — confidence semicircle gauge + accept/reject
// ---------------------------------------------------------------------------

function SuspectsSection({
  patientId,
  suspects,
  onChange,
}: {
  patientId: number;
  suspects: SuspectCard[];
  onChange: () => void;
}) {
  if (!suspects.length)
    return (
      <EmptyState
        variant="success"
        title="No open suspects"
        subtitle="Run a suspect scan from the patient page to discover HCC lift."
      />
    );

  return (
    <div className="space-y-2">
      {suspects.map((s) => (
        <SuspectCardView
          key={s.id}
          suspect={s}
          patientId={patientId}
          onChange={onChange}
        />
      ))}
    </div>
  );
}

function SuspectCardView({
  suspect,
  patientId,
  onChange,
}: {
  suspect: SuspectCard;
  patientId: number;
  onChange: () => void;
}) {
  const [busy, setBusy] = useState<"accept" | "dismiss" | null>(null);
  const [showExplain, setShowExplain] = useState(false);
  const [showDismissDialog, setShowDismissDialog] = useState(false);
  const toast = useToast();

  const acceptSuspect = async () => {
    setBusy("accept");
    try {
      await api.post(`/api/raf-central/${patientId}/actions/accept-suspect`, {
        suspect_id: suspect.id,
        push_to_emr: true,
      });
      onChange();
    } finally {
      setBusy(null);
    }
  };

  const dismissSuspect = async (reason: string) => {
    setShowDismissDialog(false);
    setBusy("dismiss");
    try {
      await api.post(`/api/raf-central/${patientId}/actions/dismiss-suspect`, {
        suspect_id: suspect.id,
        reason,
      });
      onChange();
      // TODO: No restore endpoint exists yet — Undo button closes the toast without action.
      // When a restore endpoint is added, call it here instead of just closing.
      toast.success(
        "Suspect dismissed",
        suspect.label,
        {
          duration: 10_000,
          action: {
            label: "Undo",
            onClick: () => {
              // No restore endpoint available yet — dismiss the toast only.
              // TODO: POST /api/raf-central/{pid}/actions/restore-suspect when endpoint exists.
            },
          },
        }
      );
    } finally {
      setBusy(null);
    }
  };

  const confPct = Math.round(suspect.confidence * 100);
  const gaugeColor: "emerald" | "amber" | "red" =
    confPct >= 85 ? "emerald" : confPct >= 70 ? "amber" : "red";

  return (
    <Card className="p-3 hover:bg-muted/50 transition-colors dark:hover:bg-muted/20">
      <div className="flex items-start gap-3">
        {/* point 4: semicircle confidence gauge */}
        <SemiGauge value={confPct} color={gaugeColor} />

        <div className="flex-1 min-w-0">
          <span className="text-sm font-semibold leading-snug truncate block">{suspect.label}</span>
          <div className="mt-0.5 text-xs text-muted-foreground">
            HCC {suspect.hcc} · {suspect.icd10} · {suspect.trigger}
          </div>

          {/* Button hierarchy: Accept primary, Dismiss outline, Why? ghost */}
          <div className="mt-2.5 flex gap-2 items-center flex-wrap">
            <Button size="sm" onClick={acceptSuspect} disabled={busy !== null}>
              {busy === "accept" ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <><Check className="h-3 w-3 mr-1" aria-hidden /> Accept</>
              )}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setShowDismissDialog(true)}
              disabled={busy !== null}
            >
              {busy === "dismiss" ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <><XCircle className="h-3 w-3 mr-1" aria-hidden /> Dismiss</>
              )}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setShowExplain(true)}
              disabled={busy !== null}
              aria-label="Why was this flagged?"
              className="text-muted-foreground hover:text-foreground px-2"
            >
              <HelpCircle className="h-3 w-3 mr-1" aria-hidden /> Why?
            </Button>
          </div>
        </div>
      </div>
      <ExplainPanel
        patientId={patientId}
        suspectId={suspect.id}
        suspectLabel={suspect.label}
        open={showExplain}
        onClose={() => setShowExplain(false)}
      />
      <DismissReasonDialog
        open={showDismissDialog}
        suspectLabel={suspect.label}
        onCancel={() => setShowDismissDialog(false)}
        onSubmit={dismissSuspect}
      />
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Recapture — prior-year HCCs missing this year
// ---------------------------------------------------------------------------

function RecaptureSection({ recapture }: { recapture: RecaptureCard[] }) {
  if (!recapture.length)
    return (
      <EmptyState
        variant="success"
        title="All recapture gaps closed"
        subtitle="Every prior-year HCC is re-documented this year."
      />
    );

  const totalRisk = recapture.reduce((acc, r) => acc + r.revenue_at_risk, 0);
  return (
    <div className="space-y-2">
      <div className="rounded-md bg-amber-50 dark:bg-amber-950/30 p-2 text-xs text-amber-900 dark:text-amber-200">
        <strong>${totalRisk.toLocaleString()}</strong> revenue at risk across {recapture.length} gaps
      </div>
      {recapture.map((r) => (
        <div key={r.id} className="flex items-start justify-between gap-2 py-2 border-b border-muted/40 last:border-0">
          <div className="flex-1 min-w-0">
            <div className="text-xs font-semibold truncate">{r.label}</div>
            <div className="mt-0.5 text-[11px] text-muted-foreground">
              HCC {r.hcc} · {r.icd10} · last seen {r.last_encounter_date || r.prior_year}
            </div>
          </div>
          <div className="text-xs font-bold text-amber-700 dark:text-amber-400 tabular-nums flex-shrink-0">
            ${r.revenue_at_risk.toLocaleString()}
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Audit readiness — donut chart (point 2)
// ---------------------------------------------------------------------------

function AuditSection({ audit }: { audit: AuditReadiness }) {
  return (
    <div className="pt-1">
      <AuditDonut
        compliant={audit.hccs_compliant}
        total={audit.hccs_total}
        riskLevel={audit.risk_level}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// EmptyState — consistent "nothing here" block for section bodies
// ---------------------------------------------------------------------------

function EmptyState({
  title,
  subtitle,
  variant = "neutral",
}: {
  title: string;
  subtitle?: string;
  variant?: "neutral" | "success";
}) {
  if (variant === "success") {
    return (
      <div className="flex flex-col items-center gap-2 py-6 text-center rounded-md bg-emerald-50 dark:bg-emerald-950/30 px-4">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-emerald-100 dark:bg-emerald-900/50 text-emerald-600 dark:text-emerald-400">
          <CheckCircle2 className="h-5 w-5" aria-hidden />
        </div>
        <div className="text-sm font-semibold text-emerald-800 dark:text-emerald-200">{title}</div>
        {subtitle ? (
          <div className="max-w-[36ch] text-xs text-emerald-700 dark:text-emerald-300">{subtitle}</div>
        ) : null}
      </div>
    );
  }
  return (
    <div className="flex flex-col items-center gap-2 py-6 text-center">
      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <Inbox className="h-5 w-5" aria-hidden />
      </div>
      <div className="text-sm font-medium text-foreground">{title}</div>
      {subtitle ? (
        <div className="max-w-[32ch] text-xs text-muted-foreground">{subtitle}</div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Financial — current vs projected + area chart (point 3)
// ---------------------------------------------------------------------------

function FinancialSection({ financial }: { financial: FinancialImpact }) {
  const gain = financial.annual_delta;
  const pct = financial.current_raf
    ? ((financial.projected_raf - financial.current_raf) / financial.current_raf) * 100
    : 0;
  const hasUplift = gain > 0;
  return (
    <div className="space-y-3 pt-1">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            Current annual
          </div>
          <div className="text-sm font-bold tabular-nums">
            ${financial.current_annual.toLocaleString()}
          </div>
        </div>
        <div>
          <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            Projected annual
          </div>
          <div className="text-sm font-bold tabular-nums">
            ${financial.projected_annual.toLocaleString()}
          </div>
        </div>
      </div>

      {/* point 3: area chart */}
      {hasUplift && (
        <FinancialAreaChart
          current={financial.current_annual}
          projected={financial.projected_annual}
        />
      )}

      {hasUplift ? (
        <>
          <Separator />
          <div className="rounded-md border border-emerald-200 bg-emerald-50 p-3 dark:border-emerald-800 dark:bg-emerald-950/30">
            <div className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
              Potential uplift
            </div>
            <div className="text-lg font-bold tabular-nums text-foreground">
              +${gain.toLocaleString()}
              <span className="ml-2 text-xs font-medium text-muted-foreground">
                {pct.toFixed(1)}% · ${financial.pmpm_delta.toLocaleString()}/mo
              </span>
            </div>
          </div>
        </>
      ) : null}
      <div className="text-[10px] text-muted-foreground">
        ${financial.revenue_per_raf_point.toLocaleString()}/RAF point · CMS MA benchmark
      </div>
    </div>
  );
}
