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
 *   - MEAT gaps      (🔴 compliance risk, top priority)
 *   - Suspect conds  (🟡 RAF lift opportunity)
 *   - HCC recapture  (🔵 prior-year loss)
 *   - Audit readiness (🧾 documentation risk score)
 *   - Financial impact (📈 revenue breakdown)
 *
 * Every interactive button calls an action endpoint, re-fetches the panel
 * on success, and keeps the user in context — no page reload, no modal.
 */

import { useCallback, useEffect, useState } from "react";
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
// Main panel
// ---------------------------------------------------------------------------

export function RAFCentralPanel({
  patientId,
  year,
  embedded = false,
  onClose,
}: {
  patientId: number;
  year?: number;
  embedded?: boolean;
  onClose?: () => void;
}) {
  const [data, setData] = useState<RAFCentralPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [recalcing, setRecalcing] = useState(false);

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
            title="Force RAF recalculation"
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

      <div className="flex-1 overflow-y-auto divide-y">
        <Section
          title="MEAT Gaps"
          icon={<AlertTriangle className="h-4 w-4 text-red-500" />}
          count={data.meat_gaps.filter((g) => g.status !== "COMPLETE").length}
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
          icon={<ClipboardCheck className="h-4 w-4 text-emerald-600" />}
          severity={data.audit_readiness.risk_level === "HIGH" ? "high" : "low"}
        >
          <AuditSection audit={data.audit_readiness} />
        </Section>

        <Section
          title="Financial Impact"
          icon={<DollarSign className="h-4 w-4 text-emerald-600" />}
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
      ? "border-l-amber-500"
      : "border-l-emerald-500";
  return (
    <div className={cn("border-l-4 bg-background", rail)}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-muted/40"
      >
        <div className="flex items-center gap-2">
          {icon}
          <span className="text-sm font-semibold">{title}</span>
          {count !== undefined && count > 0 ? (
            <Badge variant="outline" className="text-xs">
              {count}
            </Badge>
          ) : null}
        </div>
        <ChevronDown
          className={cn(
            "h-4 w-4 text-muted-foreground transition-transform",
            open && "rotate-180"
          )}
        />
      </button>
      {open ? <div className="px-4 pb-4">{children}</div> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// LIVE RAF — top strip with score + delta
// ---------------------------------------------------------------------------

function LiveRAFSection({ raf }: { raf: LiveRAFBar }) {
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
  return (
    <div className="grid grid-cols-2 gap-2 border-b bg-muted/30 px-4 py-3 sm:grid-cols-4">
      <Metric label={`PY${raf.year}`} value={raf.current.toFixed(3)} />
      <Metric
        label="vs. prior"
        value={
          raf.delta === null ? "—" : `${deltaSign}${raf.delta.toFixed(3)}`
        }
        valueClassName={deltaColor}
        icon={<TrendIcon className={cn("h-3.5 w-3.5", deltaColor)} aria-hidden />}
      />
      <Metric label="HCCs" value={String(raf.hcc_count)} />
      <Metric
        label="Model"
        value={`${raf.model_segment} · ${raf.model_version.toUpperCase()}`}
      />
    </div>
  );
}

function Metric({
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
      <div className={cn("flex items-center gap-1 text-lg font-bold tabular-nums", valueClassName)}>
        {icon}
        <span className="truncate">{value}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// MEAT Gaps — per-HCC card with 4 letter-dots + "Mark Reviewed" button
// ---------------------------------------------------------------------------

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
  if (!gaps.length)
    return (
      <EmptyState
        title="No HCCs coded yet"
        subtitle="Accept a suspect below to start building evidence."
      />
    );

  return (
    <div className="space-y-3">
      {gaps.map((g) => (
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
    setBusy(true);
    try {
      await api.post(`/api/raf-central/${patientId}/actions/mark-meat-reviewed`, {
        patient_hcc_id: gap.patient_hcc_id,
        monitor_note: "Reviewed during encounter",
        evaluate_note: "Reviewed during encounter",
        assess_note: "Reviewed during encounter",
        treat_note: "Reviewed during encounter",
      });
      onChange();
    } finally {
      setBusy(false);
    }
  };

  const statusColor = gap.status === "COMPLETE"
    ? "text-emerald-600"
    : gap.status === "PARTIAL"
    ? "text-amber-600"
    : "text-red-600";

  return (
    <Card className="p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold">HCC {gap.hcc}</span>
            <span className="text-xs text-muted-foreground">
              {gap.icd10_codes.slice(0, 3).join(", ")}
            </span>
          </div>
          <div className="mt-0.5 truncate text-xs text-muted-foreground">{gap.label}</div>
        </div>
        <Badge
          variant={gap.status === "COMPLETE" ? "default" : "outline"}
          className={cn("text-[10px]", statusColor)}
        >
          {gap.status}
        </Badge>
      </div>

      <div className="mt-2 flex items-center gap-3">
        <LetterDots gaps={gap.gaps} />
        <span className="text-xs text-muted-foreground">
          coef {gap.coefficient.toFixed(3)}
        </span>
      </div>

      {gap.status !== "COMPLETE" && gap.patient_hcc_id ? (
        <div className="mt-3 flex flex-wrap gap-2">
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
    { key: "monitor", letter: "M", color: "bg-teal-500" },
    { key: "evaluate", letter: "E", color: "bg-purple-500" },
    { key: "assess", letter: "A", color: "bg-amber-500" },
    { key: "treat", letter: "T", color: "bg-green-500" },
  ] as const;
  return (
    <div className="flex gap-1">
      {items.map(({ key, letter, color }) => {
        const on = gaps[key];
        return (
          <span
            key={key}
            title={on ? `${letter} documented` : `${letter} missing`}
            className={cn(
              "inline-flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-bold",
              on ? `${color} text-white` : "bg-muted text-muted-foreground"
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
  const confColor =
    confPct >= 85 ? "text-emerald-600" : confPct >= 70 ? "text-amber-600" : "text-muted-foreground";

  return (
    <Card className="p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold truncate">{suspect.label}</span>
          </div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            HCC {suspect.hcc} · {suspect.icd10} · {suspect.trigger}
          </div>
        </div>
        <div className={cn("text-sm font-bold tabular-nums", confColor)}>
          {confPct}%
        </div>
      </div>
      <div className="mt-3 flex gap-2">
        <Button size="sm" onClick={() => act("accept")} disabled={busy !== null}>
          {busy === "accept" ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <>
              <CheckCircle2 className="h-3 w-3 mr-1" /> Accept
            </>
          )}
        </Button>
        <Button size="sm" variant="outline" onClick={() => act("dismiss")} disabled={busy !== null}>
          {busy === "dismiss" ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <>
              <XCircle className="h-3 w-3 mr-1" /> Dismiss
            </>
          )}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setShowExplain(true)}
          disabled={busy !== null}
          aria-label="Why was this flagged?"
        >
          <HelpCircle className="h-3 w-3 mr-1" /> Why?
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
        <Card key={r.id} className="p-3">
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
      : "text-emerald-600";
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
          <div className="rounded-md border border-emerald-500/30 bg-emerald-50 p-3 dark:bg-emerald-950">
            <div className="text-[10px] font-medium uppercase tracking-wide text-emerald-700 dark:text-emerald-200">
              Potential uplift
            </div>
            <div className="text-lg font-bold text-emerald-700 tabular-nums dark:text-emerald-100">
              +${gain.toLocaleString()}
              <span className="ml-2 text-xs font-medium text-emerald-700/70 dark:text-emerald-300/80">
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
