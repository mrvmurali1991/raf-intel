"use client";

/**
 * ExplainPanel
 * ------------
 * "Why was this flagged?" drill-down for a single suspect condition.
 *
 *   GET /api/raf-central/{patientId}/suspect/{suspectId}/explain
 *
 * Right-anchored drawer. Optional Accept / Dismiss footer lets the reviewer
 * act on the suspect without closing the drawer first.
 */

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { FocusTrap } from "@/components/ui/focus-trap";
import {
  AlertCircle,
  Check,
  FileText,
  FlaskConical,
  History,
  Info,
  Loader2,
  Pill,
  Sparkles,
  X,
  XCircle,
} from "lucide-react";

import api from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { CONFIDENCE_METHODOLOGY, confidenceTier } from "@/lib/confidence";

export interface ExplainPanelProps {
  patientId: number;
  suspectId: number;
  suspectLabel: string;
  open: boolean;
  onClose: () => void;
  onAccept?: () => void | Promise<void>;
  onRequestDismiss?: () => void;
  busy?: "accept" | "dismiss" | null;
}

interface ContributingSignal {
  source: "medication" | "lab" | "history" | "nlp" | "note" | "other";
  label: string;
  value?: string | null;
  timestamp?: string | null;
}

// Expected backend fields (not yet sent — added in a future batch).
// Backend shape: clinical_rule_adjustments?: ClinicalRuleAdjustment[]
//                context_classification?: ContextClassification
//                evidence_date?: string   (ISO-8601 date of the source note)
interface ClinicalRuleAdjustment {
  rule_id: string;
  rule_name: string;
  explanation: string;
  confidence_delta: number; // e.g. -0.40
  failed: boolean;
}

type ContextClassification =
  | "positive"
  | "negated"
  | "hypothetical"
  | "historical"
  | "family"
  | "resolved";

interface ExplainResponse {
  suspect_id: number;
  patient_id: number;
  suspect_icd10: string;
  suspect_hcc: string;
  confidence: number;
  evidence_type: string;
  contributing_signals: ContributingSignal[];
  summary: string;
  // Optional — backend will populate in a future release
  clinical_rule_adjustments?: ClinicalRuleAdjustment[];
  context_classification?: ContextClassification;
  evidence_date?: string; // ISO-8601; used for stale-evidence banner
}

type SourceKey = ContributingSignal["source"];

const SOURCE_META: Record<
  SourceKey,
  { icon: typeof Pill; label: string; accent: string }
> = {
  medication: {
    icon: Pill,
    label: "Medication",
    accent:
      "text-indigo-600 dark:text-indigo-400 bg-indigo-500/10 border-indigo-500/20",
  },
  lab: {
    icon: FlaskConical,
    label: "Lab result",
    accent:
      "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
  },
  history: {
    icon: History,
    label: "History",
    accent:
      "text-amber-600 dark:text-amber-400 bg-amber-500/10 border-amber-500/20",
  },
  nlp: {
    icon: FileText,
    label: "Clinical note",
    accent:
      "text-sky-600 dark:text-sky-400 bg-sky-500/10 border-sky-500/20",
  },
  note: {
    icon: FileText,
    label: "Clinical note",
    accent:
      "text-sky-600 dark:text-sky-400 bg-sky-500/10 border-sky-500/20",
  },
  other: {
    icon: FileText,
    label: "Other",
    accent: "text-muted-foreground bg-muted border-border",
  },
};

function ConfidenceHero({ pct }: { pct: number }) {
  const tier = confidenceTier(pct);

  return (
    <div className={cn("rounded-xl border bg-card p-4 ring-1", tier.ring)}>
      <div className="flex items-baseline justify-between gap-3">
        <div className="flex items-center gap-1.5">
          <span
            className={cn(
              "text-xs font-semibold uppercase tracking-wider",
              tier.text,
            )}
          >
            {tier.label}
          </span>
          <TooltipProvider delay={150}>
            <Tooltip>
              <TooltipTrigger
                render={<button type="button" />}
                className="inline-flex h-4 w-4 items-center justify-center rounded-full text-muted-foreground/70 transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                aria-label="How is confidence calculated?"
              >
                <Info className="h-3 w-3" aria-hidden />
              </TooltipTrigger>
              <TooltipContent
                side="bottom"
                align="start"
                className="max-w-xs whitespace-normal text-xs leading-relaxed"
              >
                {CONFIDENCE_METHODOLOGY}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
        <span className="text-2xl font-bold tabular-nums leading-none">
          {pct}
          <span className="ml-0.5 text-sm font-medium text-muted-foreground">
            %
          </span>
        </span>
      </div>
      <div
        className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Confidence ${pct}%`}
      >
        <div
          className={cn(
            "h-full rounded-full transition-all duration-500",
            tier.bar,
          )}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function SignalCard({ sig }: { sig: ContributingSignal }) {
  const meta = SOURCE_META[sig.source] ?? SOURCE_META.other;
  const Icon = meta.icon;
  return (
    <li className="rounded-lg border bg-card p-3 transition-colors hover:border-foreground/20">
      <div className="flex items-start gap-3">
        <span
          className={cn(
            "flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md border",
            meta.accent,
          )}
        >
          <Icon className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              {meta.label}
            </span>
            {sig.timestamp && (
              <span className="text-[11px] tabular-nums text-muted-foreground/70">
                {sig.timestamp}
              </span>
            )}
          </div>
          <p className="break-words text-sm font-medium leading-snug">
            {sig.label}
          </p>
          {sig.value && (
            <p className="break-words text-xs leading-relaxed text-muted-foreground">
              {sig.value}
            </p>
          )}
        </div>
      </div>
    </li>
  );
}

function LoadingSkeleton() {
  return (
    <div className="animate-pulse space-y-4" aria-hidden>
      <div className="flex gap-2">
        <div className="h-5 w-16 rounded-full bg-muted" />
        <div className="h-5 w-14 rounded-full bg-muted" />
      </div>
      <div className="h-24 rounded-xl bg-muted" />
      <div className="h-16 rounded-lg bg-muted" />
      <div className="space-y-2">
        <div className="h-20 rounded-lg bg-muted" />
        <div className="h-20 rounded-lg bg-muted" />
      </div>
    </div>
  );
}

export function ExplainPanel({
  patientId,
  suspectId,
  suspectLabel,
  open,
  onClose,
  onAccept,
  onRequestDismiss,
  busy = null,
}: ExplainPanelProps) {
  const [mounted, setMounted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<ExplainResponse | null>(null);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .get<ExplainResponse>(
        `/api/raf-central/${patientId}/suspect/${suspectId}/explain`,
      )
      .then((r) => {
        if (!cancelled) setData(r.data);
      })
      .catch((e) => {
        if (!cancelled)
          setError(
            e?.response?.data?.detail ||
              e?.message ||
              "Failed to load evidence",
          );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, patientId, suspectId]);

  useEffect(() => {
    if (open) {
      previouslyFocusedRef.current = document.activeElement as HTMLElement;
    } else {
      previouslyFocusedRef.current?.focus();
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener("keydown", handleKeyDown, true);
    return () => document.removeEventListener("keydown", handleKeyDown, true);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  if (!open || !mounted) return null;

  const confPct = data ? Math.round(data.confidence * 100) : null;
  const showFooter = Boolean(onAccept || onRequestDismiss);
  const footerDisabled = busy !== null || loading;

  return createPortal(
    <div
      className="fixed inset-0 z-50 animate-in fade-in bg-black/75 duration-150"
      onClick={onClose}
      aria-hidden="true"
    >
      <FocusTrap enabled restoreFocus={false}>
        <div
          className="absolute right-0 top-0 flex h-full w-full animate-in slide-in-from-right flex-col border-l bg-white dark:bg-zinc-900 shadow-2xl duration-200 sm:max-w-[460px] lg:max-w-[520px]"
          onClick={(e) => e.stopPropagation()}
          role="dialog"
          aria-modal="true"
          aria-label={`Evidence for ${suspectLabel}`}
        >
          <header className="flex-shrink-0 border-b bg-white dark:bg-zinc-900">
            <div className="flex items-start justify-between gap-3 px-5 pt-4 pb-3">
              <div className="min-w-0 flex-1">
                <div className="mb-1 flex items-center gap-1.5 text-primary">
                  <Sparkles className="h-3.5 w-3.5" aria-hidden />
                  <span className="text-[11px] font-semibold uppercase tracking-wider">
                    Why was this flagged?
                  </span>
                </div>
                <h2 className="text-base font-bold leading-snug">
                  {suspectLabel}
                </h2>
                {data && (
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <Badge variant="secondary" className="font-semibold">
                      HCC {data.suspect_hcc}
                    </Badge>
                    <Badge variant="outline" className="font-mono">
                      {data.suspect_icd10}
                    </Badge>
                    <Badge
                      variant="ghost"
                      className="capitalize text-muted-foreground"
                    >
                      {data.evidence_type.replace(/_/g, " ")}
                    </Badge>
                  </div>
                )}
              </div>
              <Button
                size="icon"
                variant="ghost"
                className="-mr-2 -mt-1 h-8 w-8 flex-shrink-0 rounded-full"
                aria-label="Close evidence panel (Esc)"
                onClick={onClose}
                title="Close (Esc)"
              >
                <X className="h-4 w-4" />
              </Button>
            </div>
          </header>

          <div
            className="flex-1 overflow-y-auto"
            aria-live="polite"
            aria-busy={loading}
          >
            <div className="space-y-4 p-5">
              {loading && <LoadingSkeleton />}

              {error && (
                <div
                  className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
                  role="alert"
                >
                  <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
                  <div className="space-y-1">
                    <p className="font-medium">Couldn&apos;t load evidence</p>
                    <p className="text-xs opacity-90">{error}</p>
                  </div>
                </div>
              )}

              {!loading && !error && data && (
                <>
                  {/* ── Stale-evidence banner ──────────────────────────── */}
                  {(() => {
                    if (!data.evidence_date) return null;
                    const ageMs =
                      Date.now() - new Date(data.evidence_date).getTime();
                    const ageMonths = ageMs / (1000 * 60 * 60 * 24 * 30.44);
                    if (ageMonths <= 6) return null;
                    const ageRounded = Math.round(ageMonths);
                    return (
                      <div
                        role="alert"
                        className="flex items-start gap-2 rounded-lg border border-red-300 bg-red-50 px-3 py-2.5 text-sm text-red-800 dark:border-red-800 dark:bg-red-950/60 dark:text-red-300"
                      >
                        <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" aria-hidden />
                        <span>
                          Evidence is{" "}
                          <span className="font-semibold">
                            {ageRounded} month{ageRounded !== 1 ? "s" : ""} old
                          </span>{" "}
                          — consider refreshing before attestation.
                        </span>
                      </div>
                    );
                  })()}

                  {/* ── Context-classification warning banner ──────────── */}
                  {data.context_classification &&
                    data.context_classification !== "positive" && (
                      <div
                        role="alert"
                        className="flex items-start gap-2 rounded-lg border border-pink-300 bg-pink-50 px-3 py-2.5 text-sm text-pink-800 dark:border-pink-800/60 dark:bg-pink-950/50 dark:text-pink-300"
                      >
                        <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" aria-hidden />
                        <span>
                          This evidence was classified as{" "}
                          <span className="font-semibold capitalize">
                            {data.context_classification}
                          </span>{" "}
                          in the source note. Accepting may expose the practice
                          to RADV risk.
                        </span>
                      </div>
                    )}

                  {confPct !== null && <ConfidenceHero pct={confPct} />}

                  {data.summary && (
                    <div className="rounded-lg border-l-2 border-primary/40 bg-muted px-4 py-3">
                      <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                        Summary
                      </p>
                      <p className="text-sm leading-relaxed text-foreground">
                        {data.summary}
                      </p>
                    </div>
                  )}

                  <div>
                    <div className="mb-2 flex items-baseline justify-between">
                      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                        Contributing signals
                      </p>
                      {data.contributing_signals.length > 0 && (
                        <span className="text-[11px] tabular-nums text-muted-foreground/70">
                          {data.contributing_signals.length} found
                        </span>
                      )}
                    </div>
                    {data.contributing_signals.length === 0 ? (
                      <div className="rounded-lg border border-dashed bg-muted/20 px-4 py-8 text-center">
                        <div className="mx-auto mb-2 flex h-10 w-10 items-center justify-center rounded-full bg-muted">
                          <FileText className="h-5 w-5 text-muted-foreground" />
                        </div>
                        <p className="text-sm font-medium text-foreground">
                          No supporting signals linked
                        </p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          This suspect was flagged from header-level evidence
                          only.
                        </p>
                      </div>
                    ) : (
                      <ul className="space-y-2">
                        {data.contributing_signals.map((sig, i) => (
                          <SignalCard key={i} sig={sig} />
                        ))}
                      </ul>
                    )}
                  </div>

                  {/* ── Clinical-rule adjustments ──────────────────────── */}
                  {data.clinical_rule_adjustments &&
                    data.clinical_rule_adjustments.length > 0 && (
                      <div>
                        <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                          Clinical-rule adjustments
                        </p>
                        <ul className="space-y-2">
                          {data.clinical_rule_adjustments.map((adj) => {
                            const deltaPct = Math.round(
                              Math.abs(adj.confidence_delta) * 100,
                            );
                            const sign = adj.confidence_delta < 0 ? "−" : "+";
                            return (
                              <li
                                key={adj.rule_id}
                                className="rounded-lg border border-amber-200 bg-amber-50/60 p-3 dark:border-amber-800/50 dark:bg-amber-950/30"
                              >
                                <p className="text-xs font-semibold text-amber-900 dark:text-amber-300">
                                  {adj.rule_name}
                                </p>
                                <p className="mt-0.5 text-sm leading-snug text-foreground">
                                  {adj.explanation}
                                </p>
                                <p className="mt-1 text-[11px] font-medium tabular-nums text-amber-700 dark:text-amber-400">
                                  {sign}
                                  {deltaPct}% confidence
                                </p>
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                    )}
                </>
              )}
            </div>
          </div>

          {showFooter && !error && (
            <footer className="flex-shrink-0 border-t bg-muted px-5 py-3">
              <div className="flex items-center gap-2">
                {onRequestDismiss && (
                  <Button
                    variant="outline"
                    className="flex-1"
                    onClick={onRequestDismiss}
                    disabled={footerDisabled}
                  >
                    {busy === "dismiss" ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <>
                        <XCircle className="mr-1.5 h-4 w-4" aria-hidden />
                        Dismiss
                      </>
                    )}
                  </Button>
                )}
                {onAccept && (() => {
                  // Hard gate: disable Accept entirely when the source-note
                  // context classification flags this evidence as
                  // negated/family-history/hypothetical — these are the
                  // four RADV "killers" that cannot be billed even with a
                  // clinician override. Banner alone is not a safety
                  // control (patient-safety review #3 / round-3 #C).
                  const blockedContexts = new Set([
                    "negated",
                    "family",
                    "hypothetical",
                    "resolved",
                  ]);
                  const ctx = (data?.context_classification ?? "").toLowerCase();
                  const contextBlocked = blockedContexts.has(ctx);
                  return (
                    <Button
                      className="flex-1"
                      onClick={() => void onAccept()}
                      disabled={footerDisabled || contextBlocked}
                      title={
                        contextBlocked
                          ? `Accept disabled — source note classifies this evidence as ${ctx}. RADV-uncodeable.`
                          : undefined
                      }
                    >
                      {busy === "accept" ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <>
                          <Check className="mr-1.5 h-4 w-4" aria-hidden />
                          {contextBlocked ? "Accept blocked" : "Accept"}
                        </>
                      )}
                    </Button>
                  );
                })()}
              </div>
              <p className="mt-2 text-center text-[11px] text-muted-foreground/70">
                {loading
                  ? "Loading evidence..."
                  : busy
                  ? "Saving..."
                  : "Press Esc to close"}
              </p>
            </footer>
          )}
        </div>
      </FocusTrap>
    </div>,
    document.body,
  );
}

export default ExplainPanel;
