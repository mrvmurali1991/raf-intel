"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { FocusTrap } from "@/components/ui/focus-trap";
import {
  AlertCircle,
  Check,
  ChevronRight,
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

import {
  useExplainSuspect,
  type ContributingSignal,
} from "@/hooks/queries/useExplainSuspect";
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
import { MA_PAYMENT_PER_RAF } from "@/lib/constants";

export interface ExplainPanelProps {
  patientId: number;
  suspectId: number;
  suspectLabel: string;
  open: boolean;
  onClose: () => void;
  onAccept?: () => void | Promise<void>;
  onRequestDismiss?: () => void;
  busy?: "accept" | "dismiss" | null;
  /** HCC coefficient (RAF weight) for this suspect, used to compute revenue impact. */
  coefficient?: number;
}

export type {
  ContributingSignal,
  ExplainResponse,
} from "@/hooks/queries/useExplainSuspect";

/**
 * ExplainResponse fields that the billing gate may attach but are not yet
 * in the hook's schema.  Cast `data` through this when needed.
 */
interface ExplainDataExtended {
  block_reasons?: string[] | null;
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
    <div className={cn("rounded-xl border bg-card p-5 ring-1", tier.ring)}>
      <div className="flex flex-col items-center gap-1">
        <span
          className={cn(
            "text-xs font-bold uppercase tracking-widest",
            tier.text,
          )}
        >
          {tier.label}
        </span>
        <div className="flex items-baseline">
          <span className={cn("text-5xl font-extrabold tabular-nums leading-none", tier.text)}>
            {pct}
          </span>
          <span className={cn("ml-1 text-xl font-semibold", tier.text)}>
            %
          </span>
        </div>
        <TooltipProvider delay={150}>
          <Tooltip>
            <TooltipTrigger
              render={<button type="button" />}
              className="mt-1 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] text-muted-foreground/70 transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label="How is confidence calculated?"
            >
              <Info className="h-3 w-3" aria-hidden />
              How is this calculated?
            </TooltipTrigger>
            <TooltipContent
              side="bottom"
              align="center"
              className="max-w-xs whitespace-normal text-xs leading-relaxed"
            >
              {CONFIDENCE_METHODOLOGY}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>
      <div
        className="mt-4 h-2 w-full overflow-hidden rounded-full bg-muted"
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
    <li className="group rounded-lg border bg-card p-4 transition-all hover:border-foreground/20 hover:shadow-sm">
      <div className="flex items-start gap-3">
        <span
          className={cn(
            "flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg border",
            meta.accent,
          )}
        >
          <Icon className="h-4.5 w-4.5" />
        </span>
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-bold uppercase tracking-wider text-foreground/60">
              {meta.label}
            </span>
            {sig.timestamp && (
              <span className="text-xs tabular-nums text-foreground/45">
                {sig.timestamp}
              </span>
            )}
          </div>
          <p className="text-[15px] font-medium leading-snug text-foreground break-words">
            {sig.label}
          </p>
          {sig.value && (
            <p className="text-sm leading-relaxed text-foreground/65 break-words">
              {sig.value}
            </p>
          )}
        </div>
        <ChevronRight className="mt-1 h-4 w-4 flex-shrink-0 text-muted-foreground/40 transition-colors group-hover:text-foreground/60" />
      </div>
    </li>
  );
}

function LoadingSkeleton() {
  return (
    <div className="animate-pulse space-y-6" aria-hidden>
      <div className="flex gap-2">
        <div className="h-5 w-16 rounded-full bg-muted" />
        <div className="h-5 w-14 rounded-full bg-muted" />
      </div>
      <div className="h-32 rounded-xl bg-muted" />
      <div className="h-20 rounded-lg bg-muted" />
      <div className="space-y-3">
        <div className="h-24 rounded-lg bg-muted" />
        <div className="h-24 rounded-lg bg-muted" />
      </div>
    </div>
  );
}

/** Default number of days ahead for the defer date. */
const DEFER_DEFAULT_DAYS = 60;

function addDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
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
  coefficient,
}: ExplainPanelProps) {
  const [mounted, setMounted] = useState(false);
  const previouslyFocusedRef = useRef<HTMLElement | null>(null);

  // Defer popover state
  const [deferOpen, setDeferOpen] = useState(false);
  const [deferReason, setDeferReason] = useState("");
  const [deferUntil, setDeferUntil] = useState(() => addDays(DEFER_DEFAULT_DAYS));
  const DEFER_NOT_WIRED = true; // no /api/suspects/{id}/defer endpoint exists yet

  const {
    data,
    isLoading: loading,
    isError,
    error: queryError,
  } = useExplainSuspect(patientId, suspectId, open);

  const error = isError
    ? queryError instanceof Error
      ? queryError.message
      : "Failed to load evidence"
    : null;

  useEffect(() => {
    setMounted(true);
  }, []);

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
  const signalCount = data?.contributing_signals.length ?? 0;

  // RAF financial impact
  const rafImpact =
    typeof coefficient === "number" && coefficient > 0
      ? {
          raf: coefficient.toFixed(3),
          dollars: Math.round(coefficient * MA_PAYMENT_PER_RAF).toLocaleString("en-US"),
        }
      : null;

  // Clinical-rule gate block reasons (field may arrive in future API versions)
  const extData = data as (typeof data & ExplainDataExtended) | undefined;
  const blockReasons =
    extData?.block_reasons && extData.block_reasons.length > 0
      ? extData.block_reasons
      : null;

  return createPortal(
    <div
      className="fixed inset-0 z-[9999] animate-in fade-in bg-black/60 duration-150"
      onClick={onClose}
      aria-hidden="true"
    >
      <FocusTrap enabled restoreFocus={false}>
        <div
          className="absolute right-0 top-0 flex h-full w-full animate-in slide-in-from-right flex-col bg-background duration-200 sm:max-w-[460px] lg:max-w-[520px]"
          style={{ boxShadow: "-16px 0 48px rgba(0,0,0,0.4), -4px 0 12px rgba(0,0,0,0.2)" }}
          onClick={(e) => e.stopPropagation()}
          role="dialog"
          aria-modal="true"
          aria-label={`Evidence for ${suspectLabel}`}
        >
          {/* ── Header ────────────────────────────────────────────────── */}
          <header className="flex-shrink-0 border-b bg-background px-6 pt-5 pb-4">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0 flex-1">
                <div className="mb-2 flex items-center gap-1.5 text-primary">
                  <Sparkles className="h-3.5 w-3.5" aria-hidden />
                  <span className="text-[11px] font-bold uppercase tracking-widest">
                    Why was this flagged?
                  </span>
                </div>
                <h2 className="text-xl font-bold leading-tight tracking-tight">
                  {suspectLabel}
                </h2>
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
            {data && (
              <div className="mt-3 flex flex-wrap items-center gap-2">
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
          </header>

          {/* ── Body ──────────────────────────────────────────────────── */}
          <div className="flex-1 overflow-y-auto">
            <div className="space-y-6 p-6">
              {loading && <LoadingSkeleton />}

              {error && (
                <div
                  className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
                  role="alert"
                >
                  <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
                  <div className="space-y-1">
                    <p className="font-semibold">Couldn&apos;t load evidence</p>
                    <p className="text-xs opacity-90">{error}</p>
                  </div>
                </div>
              )}

              {!loading && !error && data && (
                <>
                  {confPct !== null && <ConfidenceHero pct={confPct} />}

                  {/* RAF financial impact row */}
                  {rafImpact && (
                    <div className="flex items-center gap-2 rounded-md bg-muted/40 px-4 py-2.5 text-sm text-muted-foreground">
                      <Sparkles className="h-3.5 w-3.5 flex-shrink-0 text-primary/70" aria-hidden />
                      <span>
                        If accepted:{" "}
                        <span className="font-semibold text-foreground">
                          +{rafImpact.raf} RAF
                        </span>{" "}
                        &rarr;{" "}
                        <span className="font-semibold text-foreground">
                          ~${rafImpact.dollars}/yr
                        </span>
                      </span>
                    </div>
                  )}

                  {/* Clinical-rule gate block reasons */}
                  {blockReasons && (
                    <div
                      className="flex items-start gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
                      role="alert"
                    >
                      <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" aria-hidden />
                      <div className="space-y-1">
                        <p className="font-semibold">Billing gate — blocked</p>
                        <ul className="list-disc list-inside space-y-0.5 text-xs opacity-90">
                          {blockReasons.map((r, i) => (
                            <li key={i}>{r}</li>
                          ))}
                        </ul>
                      </div>
                    </div>
                  )}

                  {data.summary && (
                    <div className="rounded-lg border-l-[3px] border-primary/50 bg-muted/50 px-5 py-4">
                      <p className="mb-2 text-xs font-bold uppercase tracking-widest text-foreground/50">
                        Summary
                      </p>
                      <p className="text-[15px] leading-relaxed text-foreground">
                        {data.summary.replace(
                          /signal\(s\)/g,
                          signalCount === 1 ? "signal" : "signals",
                        )}
                      </p>
                    </div>
                  )}

                  <div className="border-t border-border/60" />

                  <div>
                    <div className="mb-3 flex items-baseline justify-between">
                      <p className="text-sm font-bold uppercase tracking-wider text-foreground/50">
                        Contributing signals
                      </p>
                      {signalCount > 0 && (
                        <Badge variant="secondary" className="text-[11px] font-semibold tabular-nums">
                          {signalCount} found
                        </Badge>
                      )}
                    </div>
                    {signalCount === 0 ? (
                      <div className="rounded-lg border border-dashed bg-muted/20 px-5 py-10 text-center">
                        <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-muted">
                          <FileText className="h-6 w-6 text-muted-foreground" />
                        </div>
                        <p className="text-sm font-semibold text-foreground">
                          No supporting signals linked
                        </p>
                        <p className="mt-1 text-sm text-foreground/55">
                          This suspect was flagged from header-level evidence
                          only.
                        </p>
                      </div>
                    ) : (
                      <ul className="space-y-3">
                        {data.contributing_signals.map((sig, i) => (
                          <SignalCard key={i} sig={sig} />
                        ))}
                      </ul>
                    )}
                  </div>
                </>
              )}
            </div>
          </div>

          {showFooter && !error && (
            <footer className="flex-shrink-0 border-t bg-muted/80 px-6 py-4">
              {/* Defer inline popover — shown when deferOpen is true */}
              {deferOpen && (
                <div
                  className="mb-4 rounded-lg border bg-background p-4 shadow-md"
                  role="group"
                  aria-label="Defer options"
                >
                  <p className="mb-3 text-sm font-semibold text-foreground">
                    Defer this suspect
                  </p>
                  <div className="space-y-3">
                    <div>
                      <label
                        htmlFor="defer-reason"
                        className="mb-1 block text-xs font-medium text-foreground/60"
                      >
                        Reason
                      </label>
                      <textarea
                        id="defer-reason"
                        rows={3}
                        className="w-full resize-none rounded-md border bg-muted/30 px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        placeholder="e.g. Awaiting specialist consultation"
                        value={deferReason}
                        onChange={(e) => setDeferReason(e.target.value)}
                      />
                    </div>
                    <div>
                      <label
                        htmlFor="defer-until"
                        className="mb-1 block text-xs font-medium text-foreground/60"
                      >
                        Defer until
                      </label>
                      <input
                        id="defer-until"
                        type="date"
                        className="w-full rounded-md border bg-muted/30 px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        value={deferUntil}
                        onChange={(e) => setDeferUntil(e.target.value)}
                        min={new Date().toISOString().slice(0, 10)}
                      />
                    </div>
                  </div>
                  <div className="mt-3 flex items-center gap-2">
                    {DEFER_NOT_WIRED ? (
                      <TooltipProvider delay={100}>
                        <Tooltip>
                          <TooltipTrigger
                            render={<button type="button" />}
                            className="flex-1 cursor-not-allowed rounded-md bg-amber-100 px-3 py-2 text-sm font-medium text-amber-700 opacity-70 dark:bg-amber-950 dark:text-amber-300"
                            disabled
                            aria-disabled="true"
                            onClick={() => {
                              console.warn(
                                "[ExplainPanel] Defer endpoint not wired — POST /api/suspects/{id}/defer does not exist yet",
                              );
                            }}
                          >
                            Submit defer
                          </TooltipTrigger>
                          <TooltipContent side="top" className="text-xs">
                            Defer endpoint not wired
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    ) : null}
                    <Button
                      variant="ghost"
                      size="sm"
                      className="flex-1"
                      onClick={() => {
                        setDeferOpen(false);
                        setDeferReason("");
                        setDeferUntil(addDays(DEFER_DEFAULT_DAYS));
                      }}
                    >
                      Cancel
                    </Button>
                  </div>
                </div>
              )}

              <div className="flex items-center gap-3">
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

                {/* Defer button — always shown when Accept or Dismiss is present */}
                {(onAccept || onRequestDismiss) && (
                  <Button
                    variant="outline"
                    className="flex-1"
                    onClick={() => setDeferOpen((v) => !v)}
                    disabled={footerDisabled}
                    aria-pressed={deferOpen}
                  >
                    <History className="mr-1.5 h-4 w-4" aria-hidden />
                    Defer
                  </Button>
                )}

                {onAccept && (
                  <Button
                    className="flex-1"
                    onClick={() => void onAccept()}
                    disabled={footerDisabled}
                  >
                    {busy === "accept" ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <>
                        <Check className="mr-1.5 h-4 w-4" aria-hidden />
                        Accept
                      </>
                    )}
                  </Button>
                )}
              </div>
              <p className="mt-2 text-center text-xs text-foreground/40">
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
