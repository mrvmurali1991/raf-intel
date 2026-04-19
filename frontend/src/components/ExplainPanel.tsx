"use client";

/**
 * ExplainPanel
 * ------------
 * "Why was this flagged?" drill-down for a single suspect condition.
 *
 *   GET /api/raf-central/{patientId}/suspect/{suspectId}/explain
 *
 * Decomposes raf_suspect_conditions.evidence_detail into a typed list of
 * contributing signals (medications, labs, prior HCCs, note excerpts) so
 * the clinician can verify why the suspect engine triggered.
 */

import { useEffect, useState } from "react";
import {
  FileText,
  FlaskConical,
  History,
  Loader2,
  Pill,
  X,
} from "lucide-react";

import api from "@/lib/api";
import { Button } from "@/components/ui/button";

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

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-end bg-black/30"
      onClick={onClose}
    >
      <div
        className="h-full w-full max-w-md overflow-y-auto bg-background shadow-xl animate-in slide-in-from-right"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={`Evidence for ${suspectLabel}`}
      >
        <header className="sticky top-0 flex items-center justify-between border-b bg-background px-4 py-3">
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold">
              Why was this flagged?
            </h2>
            <p className="truncate text-xs text-muted-foreground">
              {suspectLabel}
            </p>
          </div>
          <Button
            size="icon"
            variant="ghost"
            aria-label="Close evidence panel"
            onClick={onClose}
          >
            <X className="h-4 w-4" />
          </Button>
        </header>

        <div className="p-4">
          {loading && (
            <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading evidence…
            </div>
          )}
          {error && (
            <p className="py-4 text-sm text-red-600" role="alert">
              {error}
            </p>
          )}
          {!loading && !error && data && (
            <>
              <div className="mb-4 rounded-md border bg-muted/40 p-3 text-xs">
                <div>
                  <span className="text-muted-foreground">HCC:</span>{" "}
                  <span className="font-medium">{data.suspect_hcc}</span>
                  <span className="text-muted-foreground"> · ICD-10:</span>{" "}
                  <span className="font-medium">{data.suspect_icd10}</span>
                </div>
                <div className="mt-1 text-muted-foreground">{data.summary}</div>
              </div>

              {data.contributing_signals.length === 0 ? (
                <p className="py-4 text-center text-xs text-muted-foreground">
                  No additional evidence recorded.
                </p>
              ) : (
                <ul className="space-y-2">
                  {data.contributing_signals.map((sig, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-3 rounded-md border p-2"
                    >
                      <span className="mt-0.5">{iconFor(sig.source)}</span>
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-medium">
                          {sig.label}
                        </div>
                        {sig.value && (
                          <div className="truncate text-xs text-muted-foreground">
                            {sig.value}
                          </div>
                        )}
                        {sig.timestamp && (
                          <div className="text-[10px] text-muted-foreground">
                            {sig.timestamp}
                          </div>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default ExplainPanel;
