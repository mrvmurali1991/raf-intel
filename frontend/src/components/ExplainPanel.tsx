"use client";

/**
 * ExplainPanel
 * ------------
 * "Why was this flagged?" drill-down for a single suspect condition.
 *
 *   GET /api/raf-central/{patientId}/suspect/{suspectId}/explain
 *
 * Renders as a right-anchored Sheet (shadcn) so it never clips inside the
 * panel, and fills remaining space with a confidence bar + signal list.
 */

import { useEffect, useState } from "react";
import {
  FileText,
  FlaskConical,
  History,
  Loader2,
  Pill,
  X,
  AlertCircle,
} from "lucide-react";

import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface ExplainPanelProps {
  patientId: number;
  suspectId: number;
  suspectLabel: string;
  open: boolean;
  onClose: () => void;
}

interface ContributingSignal {
  source: "medication" | "lab" | "history" | "nlp" | "note" | "other";
  label: string;
  value?: string | null;
  timestamp?: string | null;
}

interface ExplainResponse {
  suspect_id: number;
  patient_id: number;
  suspect_icd10: string;
  suspect_hcc: string;
  confidence: number;
  evidence_type: string;
  contributing_signals: ContributingSignal[];
  summary: string;
}

function iconFor(source: ContributingSignal["source"]) {
  switch (source) {
    case "medication":
      return <Pill className="h-4 w-4 text-indigo-500" />;
    case "lab":
      return <FlaskConical className="h-4 w-4 text-emerald-500" />;
    case "history":
      return <History className="h-4 w-4 text-amber-500" />;
    case "nlp":
    case "note":
      return <FileText className="h-4 w-4 text-sky-500" />;
    default:
      return <FileText className="h-4 w-4 text-muted-foreground" />;
  }
}

function ConfidenceBar({ pct }: { pct: number }) {
  const color =
    pct >= 85
      ? "bg-emerald-500"
      : pct >= 70
      ? "bg-amber-500"
      : "bg-red-400";
  const label =
    pct >= 85 ? "High confidence" : pct >= 70 ? "Moderate confidence" : "Low confidence";
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground font-medium">{label}</span>
        <span className="font-bold tabular-nums">{pct}%</span>
      </div>
      <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={cn("h-full rounded-full transition-all duration-500", color)}
          style={{ width: `${pct}%` }}
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`Confidence ${pct}%`}
        />
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
}: ExplainPanelProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<ExplainResponse | null>(null);

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

  if (!open) return null;

  const confPct = data ? Math.round(data.confidence * 100) : null;

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 bg-black/40 backdrop-blur-[1px]"
      onClick={onClose}
      aria-hidden="true"
    >
      {/* Drawer */}
      <div
        className="absolute right-0 top-0 h-full w-full max-w-[440px] flex flex-col bg-background shadow-2xl border-l animate-in slide-in-from-right duration-200"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`Evidence for ${suspectLabel}`}
      >
        {/* Header — no overlap, fixed height */}
        <header className="flex-shrink-0 flex items-start justify-between gap-3 border-b bg-background px-5 py-4">
          <div className="min-w-0 flex-1">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-0.5">
              Why was this flagged?
            </p>
            <h2 className="text-sm font-bold leading-snug line-clamp-2">
              {suspectLabel}
            </h2>
          </div>
          <Button
            size="icon"
            variant="ghost"
            className="flex-shrink-0 mt-0.5 h-8 w-8"
            aria-label="Close evidence panel"
            onClick={onClose}
          >
            <X className="h-4 w-4" />
          </Button>
        </header>

        {/* Body — scrollable */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {loading && (
            <div className="flex items-center gap-2 py-12 justify-center text-sm text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" />
              <span>Loading evidence…</span>
            </div>
          )}

          {error && (
            <div className="flex items-start gap-2 rounded-md bg-red-50 border border-red-200 p-3 text-sm text-red-700 dark:bg-red-950 dark:border-red-800 dark:text-red-300" role="alert">
              <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          {!loading && !error && data && (
            <>
              {/* Metadata chip row */}
              <div className="flex flex-wrap gap-2 text-xs">
                <span className="rounded-full bg-muted px-2.5 py-1 font-medium text-foreground">
                  HCC {data.suspect_hcc}
                </span>
                <span className="rounded-full bg-muted px-2.5 py-1 font-medium text-foreground">
                  {data.suspect_icd10}
                </span>
                <span className="rounded-full bg-muted px-2.5 py-1 font-medium text-muted-foreground capitalize">
                  {data.evidence_type.replace(/_/g, " ")}
                </span>
              </div>

              {/* Confidence bar */}
              {confPct !== null && <ConfidenceBar pct={confPct} />}

              {/* Summary */}
              {data.summary && (
                <p className="text-xs text-muted-foreground leading-relaxed border-l-2 border-muted pl-3">
                  {data.summary}
                </p>
              )}

              {/* Contributing signals */}
              {data.contributing_signals.length === 0 ? (
                <div className="flex flex-col items-center gap-2 py-8 text-center">
                  <div className="h-10 w-10 rounded-full bg-muted flex items-center justify-center">
                    <FileText className="h-5 w-5 text-muted-foreground" />
                  </div>
                  <p className="text-sm text-muted-foreground">No additional evidence recorded.</p>
                </div>
              ) : (
                <div>
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">
                    Contributing signals ({data.contributing_signals.length})
                  </p>
                  <ul className="space-y-2">
                    {data.contributing_signals.map((sig, i) => (
                      <li
                        key={i}
                        className="flex items-start gap-3 rounded-lg border bg-muted/20 p-3 hover:bg-muted/40 transition-colors"
                      >
                        <span className="mt-0.5 flex-shrink-0">{iconFor(sig.source)}</span>
                        <div className="min-w-0 flex-1">
                          <div className="text-sm font-medium leading-snug">
                            {sig.label}
                          </div>
                          {sig.value && (
                            <div className="mt-0.5 text-xs text-muted-foreground break-words">
                              {sig.value}
                            </div>
                          )}
                          {sig.timestamp && (
                            <div className="mt-0.5 text-[10px] text-muted-foreground/70">
                              {sig.timestamp}
                            </div>
                          )}
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default ExplainPanel;
