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
import api from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { OrderLabButton } from "@/components/OrderLabButton";
import { Progress } from "@/components/ui/progress";
import { Separator } from "@/components/ui/separator";
import {
  ChevronDown,
  AlertTriangle,
  Sparkles,
  History,
  ClipboardCheck,
  DollarSign,
  Check,
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

export interface RAFCentralPayload {
  patient_id: number;
  measurement_year: number;
  generated_at: string;
  raf_score: LiveRAFBar;
  meat_gaps: MEATGap[];
  suspects: SuspectCard[];
  recapture: RecaptureCard[];
  coding_opt: unknown[];
  audit_readiness: AuditReadiness;
  financial_impact: FinancialImpact;
}

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
  const meatRef = useRef<HTMLDivElement>(null);

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
    return (
      <div className="flex flex-col min-h-full bg-muted/30 dark:bg-background">
        {/* ── Top strip: patient header + RAF metrics + controls ─────────── */}
        <header className="border-b bg-background px-6 py-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            {/* Left: identity */}
            <div>
              <div className="text-[10px] font-medium uppercase tracking-widest text-muted-foreground">
                RAF Intelligence
              </div>
              <div className="mt-0.5 text-lg font-bold text-foreground">
                Patient {data.patient_id}
                <span className="ml-2 text-sm font-normal text-muted-foreground">
                  · PY{data.measurement_year}
                </span>
              </div>
            </div>
            {/* Right: recalc button */}
            <div className="flex items-center gap-2">
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

          {/* Live RAF metrics bar — inline in header */}
          <div className="mt-4">
            <LiveRAFSection raf={data.raf_score} variant="inline" />
          </div>

          {/* Next Best Action banner */}
          {actionCount > 0 && (
            <button
              onClick={scrollToMeat}
              className="mt-3 flex w-full items-center justify-between gap-3 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-left hover:bg-emerald-100 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring dark:border-emerald-800 dark:bg-emerald-950/40 dark:hover:bg-emerald-950/60"
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
                Scroll to MEAT Gaps →
              </span>
            </button>
          )}
        </header>

        {/* ── Two-column body ─────────────────────────────────────────────── */}
        <div className="flex flex-1 flex-col lg:grid lg:grid-cols-[3fr_2fr] lg:items-start gap-6 p-6">
          {/* LEFT: primary workspace */}
          <div className="flex flex-col gap-6 min-w-0">
            {/* MEAT Gaps */}
            <div ref={meatRef} className="rounded-lg border bg-card shadow-sm border-l-4 border-l-red-500 overflow-hidden">
              <div className="flex items-center gap-2 px-5 py-3.5 border-b bg-card">
                <AlertTriangle className="h-4 w-4 text-red-500 flex-shrink-0" aria-hidden />
                <span className="text-sm font-semibold">MEAT Gaps</span>
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
              </div>
              <div className="px-5 py-4">
                <MEATSection
                  patientId={patientId}
                  year={year}
                  gaps={data.meat_gaps}
                  onChange={fetchPanel}
                />
              </div>
            </div>

            {/* Suspect Conditions */}
            <div className="rounded-lg border bg-card shadow-sm border-l-4 border-l-amber-400 overflow-hidden">
              <div className="flex items-center gap-2 px-5 py-3.5 border-b bg-card">
                <Sparkles className="h-4 w-4 text-amber-500 flex-shrink-0" aria-hidden />
                <span className="text-sm font-semibold">Suspect Conditions</span>
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

          {/* RIGHT: context / secondary */}
          <div className="flex flex-col gap-6 min-w-0">
            {/* HCC Recapture */}
            <div className="rounded-lg border bg-card shadow-sm overflow-hidden">
              <div className="flex items-center gap-2 px-5 py-3.5 border-b bg-card">
                <History className="h-4 w-4 text-blue-500 flex-shrink-0" aria-hidden />
                <span className="text-sm font-semibold">HCC Recapture</span>
                {data.recapture.length > 0 && (
                  <Badge className="ml-1 text-[10px] font-semibold border-0 bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300">
                    {data.recapture.length}
                  </Badge>
                )}
              </div>
              <div className="px-5 py-4">
                <RecaptureSection recapture={data.recapture} />
              </div>
            </div>

            {/* Audit Readiness */}
            <div className="rounded-lg border bg-card shadow-sm overflow-hidden">
              <div className="flex items-center gap-2 px-5 py-3.5 border-b bg-card">
                <ClipboardCheck className="h-4 w-4 text-slate-500 flex-shrink-0" aria-hidden />
                <span className="text-sm font-semibold">Audit Readiness</span>
                <span
                  className={cn(
                    "ml-auto text-[10px] font-bold uppercase tracking-wide",
                    data.audit_readiness.risk_level === "HIGH"
                      ? "text-red-600"
                      : data.audit_readiness.risk_level === "MEDIUM"
                      ? "text-amber-600"
                      : "text-emerald-600"
                  )}
                >
                  {data.audit_readiness.risk_level} RISK
                </span>
              </div>
              <div className="px-5 py-4">
                <AuditSection audit={data.audit_readiness} />
              </div>
            </div>

            {/* Financial Impact */}
            <div className="rounded-lg border bg-card shadow-sm overflow-hidden">
              <div className="flex items-center gap-2 px-5 py-3.5 border-b bg-card">
                <DollarSign className="h-4 w-4 text-slate-500 flex-shrink-0" aria-hidden />
                <span className="text-sm font-semibold">Financial Impact</span>
              </div>
              <div className="px-5 py-4">
                <FinancialSection financial={data.financial_impact} />
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
            Review →
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
// LIVE RAF — top strip with score + delta
// ---------------------------------------------------------------------------

function LiveRAFSection({
  raf,
  variant = "strip",
}: {
  raf: LiveRAFBar;
  /** strip: full-bleed row with border-b (panel layout)
   *  inline: no border/bg wrapper, just the metrics row (dashboard layout) */
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
}: {
  patientId: number;
  year?: number;
  gaps: MEATGap[];
  onChange: () => void;
}) {
  const [filter, setFilter] = useState<MeatFilter>("all");

  if (!gaps.length)
    return (
      <EmptyState
        title="No HCCs coded yet"
        subtitle="Accept a suspect below to start building evidence."
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

  const options: { id: MeatFilter; label: string }[] = [
    { id: "all", label: "All gaps" },
    { id: "incomplete", label: "Incomplete only" },
    { id: "high-impact", label: "High impact first" },
  ];
  const activeLabel = options.find((o) => o.id === filter)?.label ?? "All gaps";

  return (
    <div className="space-y-3">
      {/* Filter dropdown — right-aligned, single control */}
      <div className="flex items-center justify-end gap-2 pt-1">
        <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          Filter
        </span>
        <div className="relative">
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value as MeatFilter)}
            className="appearance-none rounded-md border border-border bg-background pl-2.5 pr-7 py-1 text-xs font-medium text-foreground hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring cursor-pointer"
            aria-label="Filter MEAT gaps"
          >
            {options.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-1.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden />
        </div>
      </div>

      {filtered.map((g) => (
        <MEATCard
          key={`${g.hcc}-${g.patient_hcc_id}`}
          gap={g}
          patientId={patientId}
          year={year}
          onChange={onChange}
        />
      ))}
    </div>
  );
}

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

  const markReviewed = async () => {
    if (!gap.patient_hcc_id) return;
    const missing = (Object.entries(gap.gaps) as [keyof MEATGap["gaps"], boolean][])
      .filter(([, on]) => !on)
      .map(([k]) => k);
    if (missing.length === 0) return;
    const missingLabel = missing
      .map((k) => k[0].toUpperCase() + k.slice(1))
      .join(", ");
    const attestation = window.prompt(
      `Attestation for HCC ${gap.hcc} — ${gap.label}\n` +
        `Missing elements: ${missingLabel}\n\n` +
        `Enter a clinician note documenting these elements. ` +
        `Already-documented MEAT letters will not be overwritten. ` +
        `Leave blank to cancel.`,
      "",
    );
    if (!attestation || !attestation.trim()) return;
    const note = attestation.trim();
    setBusy(true);
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

        {/* Status pill — emerald for COMPLETE (success), amber for PARTIAL, red for MISSING */}
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
    </Card>
  );
}

function LetterDots({
  gaps,
}: {
  gaps: MEATGap["gaps"];
}) {
  const items = [
    { key: "monitor", letter: "M", on: "bg-cyan-500", label: "Monitor" },
    { key: "evaluate", letter: "E", on: "bg-indigo-500", label: "Evaluate" },
    { key: "assess", letter: "A", on: "bg-amber-500", label: "Assess" },
    { key: "treat", letter: "T", on: "bg-emerald-500", label: "Treat" },
  ] as const;
  return (
    <div className="flex gap-1">
      {items.map(({ key, letter, on: onColor, label }) => {
        const on = gaps[key];
        return (
          <span
            key={key}
            title={on ? `${label} documented` : `${label} missing`}
            className={cn(
              "inline-flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold transition-colors",
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
// Suspects — confidence + accept/reject
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
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    // Trigger confidence bar animation on mount
    const t = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(t);
  }, []);

  const act = async (kind: "accept" | "dismiss") => {
    setBusy(kind);
    try {
      const path =
        kind === "accept"
          ? `/api/raf-central/${patientId}/actions/accept-suspect`
          : `/api/raf-central/${patientId}/actions/dismiss-suspect`;
      const body =
        kind === "accept"
          ? { suspect_id: suspect.id, push_to_emr: true }
          : { suspect_id: suspect.id, reason: "dismissed from raf-central panel" };
      await api.post(path, body);
      onChange();
    } finally {
      setBusy(null);
    }
  };

  const confPct = Math.round(suspect.confidence * 100);
  const confBarColor =
    confPct >= 85 ? "bg-emerald-500" : confPct >= 70 ? "bg-amber-500" : "bg-red-400";

  return (
    <Card className="p-3 hover:bg-muted/50 transition-colors dark:hover:bg-muted/20">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <span className="text-sm font-semibold leading-snug truncate block">{suspect.label}</span>
          <div className="mt-0.5 text-xs text-muted-foreground">
            HCC {suspect.hcc} · {suspect.icd10} · {suspect.trigger}
          </div>
        </div>
      </div>

      {/* Confidence bar with labels */}
      <div className="mt-2 space-y-0.5">
        <div className="flex items-center justify-between text-[11px]">
          <span className="text-muted-foreground font-medium">Confidence</span>
          <span className="font-semibold tabular-nums text-foreground">{confPct}%</span>
        </div>
        <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
          <div
            className={cn("h-full rounded-full transition-[width] duration-500", confBarColor)}
            style={{ width: mounted ? `${confPct}%` : "0%" }}
            role="progressbar"
            aria-valuenow={confPct}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`Confidence ${confPct}%`}
          />
        </div>
      </div>

      {/* Button hierarchy: Accept primary, Dismiss outline, Why? ghost */}
      <div className="mt-2.5 flex gap-2 items-center">
        <Button size="sm" onClick={() => act("accept")} disabled={busy !== null}>
          {busy === "accept" ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <><Check className="h-3 w-3 mr-1" aria-hidden /> Accept</>
          )}
        </Button>
        <Button size="sm" variant="outline" onClick={() => act("dismiss")} disabled={busy !== null}>
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
      <ExplainPanel
        patientId={patientId}
        suspectId={suspect.id}
        suspectLabel={suspect.label}
        open={showExplain}
        onClose={() => setShowExplain(false)}
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
        title="No recapture gaps"
        subtitle="Every prior-year HCC is documented this year."
      />
    );

  const totalRisk = recapture.reduce((acc, r) => acc + r.revenue_at_risk, 0);
  return (
    <div className="space-y-2">
      <div className="rounded-md bg-blue-50 p-2 text-xs text-blue-900 dark:bg-blue-950 dark:text-blue-200">
        <strong>${totalRisk.toLocaleString()}</strong> revenue at risk across {recapture.length} gaps
      </div>
      {recapture.map((r) => (
        <Card key={r.id} className="p-3 hover:bg-muted/50 transition-colors dark:hover:bg-muted/20">
          <div className="flex items-start justify-between gap-2">
            <div className="flex-1 min-w-0">
              <div className="text-sm font-semibold truncate">{r.label}</div>
              <div className="mt-0.5 text-xs text-muted-foreground">
                HCC {r.hcc} · {r.icd10} · last seen {r.last_encounter_date || r.prior_year}
              </div>
            </div>
            <div className="text-sm font-bold text-blue-600 tabular-nums">
              ${r.revenue_at_risk.toLocaleString()}
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Audit readiness — compliance % + progress bar
// ---------------------------------------------------------------------------

function AuditSection({ audit }: { audit: AuditReadiness }) {
  const riskColor =
    audit.risk_level === "HIGH"
      ? "text-red-600"
      : audit.risk_level === "MEDIUM"
      ? "text-amber-600"
      : "text-slate-600 dark:text-slate-400";
  return (
    <div className="space-y-2 pt-1">
      <div className="flex items-center justify-between text-sm">
        <span className="text-muted-foreground">MEAT compliance</span>
        <span className="font-bold tabular-nums">
          {audit.meat_compliance_pct}% ({audit.hccs_compliant}/{audit.hccs_total})
        </span>
      </div>
      <Progress value={audit.meat_compliance_pct} className="h-2" />
      <div className="flex items-center justify-between pt-1 text-xs">
        <span className="text-muted-foreground">Risk level</span>
        <span className={cn("font-semibold uppercase", riskColor)}>
          {audit.risk_level}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// EmptyState — consistent "nothing here" block for section bodies
// ---------------------------------------------------------------------------

function EmptyState({ title, subtitle }: { title: string; subtitle?: string }) {
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
// Financial — current vs projected
// ---------------------------------------------------------------------------

function FinancialSection({ financial }: { financial: FinancialImpact }) {
  const gain = financial.annual_delta;
  const pct = financial.current_raf ? ((financial.projected_raf - financial.current_raf) / financial.current_raf) * 100 : 0;
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
      {hasUplift ? (
        <>
          <Separator />
          <div className="rounded-md border border-slate-300 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-900">
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
