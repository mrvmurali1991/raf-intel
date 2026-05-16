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
import { useRAFCentralPanel } from "@/hooks/queries/useRAFCentralPanel";
import { useRecalculateRAF } from "@/hooks/mutations/useRAFCentralMutations";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  ChevronDown,
  AlertTriangle,
  Sparkles,
  History,
  ClipboardCheck,
  DollarSign,
  RefreshCcw,
  Loader2,
  X,
  TrendingUp,
  TrendingDown,
  Minus,
} from "lucide-react";
import { cn } from "@/lib/utils";

// raf-central subcomponents
import type {
  LiveRAFBar,
  MeatFilter,
} from "./raf-central/_shared";

// Re-export all public types so existing importers of RAFCentralPanel keep working
export type {
  LiveRAFBar,
  MEATGap,
  SuspectCard,
  RecaptureCard,
  AuditReadiness,
  FinancialImpact,
  CodingOptCard,
  RAFCentralPayload,
  DismissReasonCode,
  MeatFilter,
} from "./raf-central/_shared";
export { DISMISS_REASONS } from "./raf-central/_shared";

import { RAFGauge } from "./raf-central/RAFGauge";
import { SparklineTrend } from "./raf-central/SparklineTrend";
import { NextBestActionBanner } from "./raf-central/NextBestAction";
import { Section } from "./raf-central/common/Section";
import { MEATSection } from "./raf-central/MEATGaps";
import { SuspectsSection } from "./raf-central/Suspects";
import { RecaptureSection } from "./raf-central/Recapture";
import { AuditSection } from "./raf-central/Performance/PerformanceCard";
import { FinancialSection } from "./raf-central/Performance/FinancialCard";
import { HCCRecaptureCard } from "./raf-central/Performance/HCCRecaptureCard";

// ---------------------------------------------------------------------------
// LiveRAFSection — top strip with score + delta (panel layout only)
// ---------------------------------------------------------------------------

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
  // ---------------------------------------------------------------------------
  // Data — React Query
  // ---------------------------------------------------------------------------
  const {
    data,
    isLoading: loading,
    isError,
    error: queryError,
    refetch: refetchPanel,
  } = useRAFCentralPanel(patientId, year);

  const error =
    isError && queryError
      ? queryError instanceof Error
        ? queryError.message
        : "Failed to load RAF Central"
      : null;

  // Recalculate mutation
  const recalcMutation = useRecalculateRAF(patientId, year);
  const recalcing = recalcMutation.isPending;

  // onChange forwarded to sub-sections — mutations already invalidate the query
  // key; this explicit refetch is a safety-net for any code path that still
  // calls onChange() directly.
  const fetchPanel = useCallback(() => {
    void refetchPanel();
  }, [refetchPanel]);

  const recalc = useCallback(async () => {
    await recalcMutation.mutateAsync();
  }, [recalcMutation]);

  const [cardsVisible, setCardsVisible] = useState(false);
  const meatRef = useRef<HTMLDivElement>(null);
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

  // Trigger stagger only on first data load
  useEffect(() => {
    if (data && !mountedOnce.current) {
      mountedOnce.current = true;
      requestAnimationFrame(() => setCardsVisible(true));
    }
  }, [data]);

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

  const meatGaps = data.meat_gaps ?? [];
  const suspectsList = data.suspects ?? [];
  const recaptureList = data.recapture ?? [];
  const incompleteGaps = meatGaps.filter((g) => g.status !== "COMPLETE");
  const openSuspects = suspectsList.filter((s) => s.status !== "dismissed");
  const actionCount = incompleteGaps.length + openSuspects.length;

  const scrollToMeat = () => {
    meatRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  // ── Dashboard layout (in-app tab, >=1024px two-column) ────────────────────
  if (layout === "dashboard") {
    const stagger = (delay: string) =>
      cn(
        "transition-all duration-500",
        cardsVisible ? "opacity-100 translate-y-0" : "opacity-0 translate-y-3",
        delay
      );

    return (
      <div className="flex flex-col min-h-full bg-muted/30 dark:bg-background">
        {/* Persistent AI disclaimer — RADV trust requirement, must stay visible */}
        <div
          className="bg-muted/50 px-3 py-1.5 text-[11px] text-muted-foreground border-b border-border"
          role="note"
        >
          AI suggestions are decision aids — clinician review and attestation are required before billing.
        </div>
        {/* ── Top strip: patient header + RAF gauge + controls ─────────── */}
        <header className="border-b bg-gradient-to-br from-background to-muted/40 dark:from-background dark:to-muted/20 px-6 py-5 shadow-sm">
          <div className="flex flex-wrap items-start justify-between gap-4">
            {/* Left: compact score + identity (gauge replaced to save vertical space) */}
            <div className="flex items-center gap-6">
              <div>
                <div className="text-[10px] font-medium uppercase tracking-widest text-muted-foreground">
                  RAF Intelligence
                </div>
                {/* Score as large plain text alongside sparkline */}
                <div className="mt-1 flex items-end gap-3">
                  <span className="text-4xl font-extrabold tabular-nums leading-none text-foreground">
                    {Number(data.raf_score?.current ?? 0).toFixed(2)}
                  </span>
                  {data.raf_score?.prior_year != null && (
                    <div className="flex flex-col gap-0.5 pb-0.5">
                      <SparklineTrend
                        prior={data.raf_score.prior_year}
                        current={data.raf_score.current}
                        projected={data.financial_impact.projected_raf}
                      />
                      <span className="text-[10px] text-muted-foreground">
                        prior → now → projected
                      </span>
                    </div>
                  )}
                </div>
                <div className="mt-0.5 text-sm font-normal text-muted-foreground">
                  Patient {data.patient_id}
                  <span className="ml-2">· PY{data.measurement_year}</span>
                </div>
                <div className="mt-1 flex items-center gap-3 text-xs text-muted-foreground">
                  <span className="font-medium">{data.raf_score?.hcc_count ?? 0} HCCs</span>
                  <span className="text-border">·</span>
                  <span>{data.raf_score?.model_segment ?? "—"}</span>
                  <span className="text-border">·</span>
                  <span className="uppercase">{data.raf_score?.model_version ?? ""}</span>
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
            <NextBestActionBanner
              actionCount={actionCount}
              onClick={scrollToMeat}
              variant="dashboard"
            />
          )}
        </header>

        {/* ── Two-column body ─────────────────────────────────────────────── */}
        <div className="flex flex-1 flex-col lg:grid lg:grid-cols-[3fr_2fr] lg:items-start gap-6 p-6">
          {/* LEFT: primary workspace */}
          <div className="flex flex-col gap-6 min-w-0">
            {/* ── MEAT Gaps ───────────────────────────────────────────────── */}
            <div
              ref={meatRef}
              className={cn(
                "rounded-lg border border-t-[3px] border-t-red-500 bg-card shadow-sm hover:shadow-md transition-shadow overflow-hidden",
                stagger("delay-100")
              )}
            >
              <div className="flex items-center gap-2 px-5 py-3.5 border-b bg-card">
                <AlertTriangle className="h-4 w-4 text-red-500 flex-shrink-0" aria-hidden />
                <span className="text-base font-bold">MEAT Gaps</span>
                <Badge
                  className={cn(
                    "ml-1 text-[10px] font-semibold border-0",
                    meatGaps.length === 0
                      ? "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400"
                      : "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300"
                  )}
                >
                  {meatGaps.length}
                </Badge>
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
                  gaps={meatGaps}
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
                    suspectsList.length === 0
                      ? "bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400"
                      : "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300"
                  )}
                >
                  {suspectsList.length}
                </Badge>
              </div>
              <div className="px-5 py-4">
                <SuspectsSection
                  patientId={patientId}
                  suspects={suspectsList}
                  onChange={fetchPanel}
                  modelVersion={data.raf_score?.model_version ?? null}
                  measurementYear={data.measurement_year ?? null}
                />
              </div>
            </div>
          </div>

          {/* ── RIGHT: secondary context ─────────────────────────────────── */}
          <div className="flex flex-col gap-4 min-w-0">
            {/* HCC Recapture */}
            <div className={cn("rounded-lg border border-t-[3px] border-t-amber-400 bg-card overflow-hidden", stagger("delay-100"))}>
              <div className="flex items-center gap-2 px-4 py-3 border-b border-muted/40">
                <History className="h-3.5 w-3.5 text-muted-foreground flex-shrink-0" aria-hidden />
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">HCC Recapture</span>
                {recaptureList.length > 0 && (
                  <Badge className="ml-1 text-[10px] font-semibold border-0 bg-muted text-muted-foreground">
                    {recaptureList.length}
                  </Badge>
                )}
              </div>
              <div className="px-4 py-3">
                <RecaptureSection recapture={recaptureList} />
              </div>
            </div>

            {/* Performance card (merged Audit + Financial) */}
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
              <HCCRecaptureCard
                audit={data.audit_readiness}
                financial={data.financial_impact}
              />
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
      {/* Persistent AI disclaimer — RADV trust requirement */}
      <div
        className="bg-muted/50 px-3 py-1.5 text-[11px] text-muted-foreground border-b border-border"
        role="note"
      >
        AI suggestions are decision aids — clinician review and attestation are required before billing.
      </div>
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
        <NextBestActionBanner
          actionCount={actionCount}
          onClick={scrollToMeat}
          variant="panel"
        />
      )}

      <div className="flex-1 overflow-y-auto divide-y">
        <div ref={meatRef}>
          <Section
            title="MEAT Gaps"
            icon={<AlertTriangle className="h-4 w-4 text-red-500" />}
            count={meatGaps.length}
            severity="high"
            defaultOpen
          >
            <MEATSection
              patientId={patientId}
              year={year}
              gaps={meatGaps}
              onChange={fetchPanel}
            />
          </Section>
        </div>

        <Section
          title="Suspect Conditions"
          icon={<Sparkles className="h-4 w-4 text-amber-500" />}
          count={suspectsList.length}
          severity="medium"
          defaultOpen
        >
          <SuspectsSection
            patientId={patientId}
            suspects={suspectsList}
            onChange={fetchPanel}
            modelVersion={data.raf_score?.model_version ?? null}
            measurementYear={data.measurement_year ?? null}
          />
        </Section>

        <Section
          title="HCC Recapture"
          icon={<History className="h-4 w-4 text-blue-500" />}
          count={recaptureList.length}
          severity="medium"
        >
          <RecaptureSection recapture={recaptureList} />
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
