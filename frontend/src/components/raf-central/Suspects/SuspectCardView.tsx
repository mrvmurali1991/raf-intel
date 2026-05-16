"use client";

import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Loader2, Check, XCircle, HelpCircle, ThumbsUp, ThumbsDown } from "lucide-react";
import { useToast } from "@/components/Toast";
import {
  useAcceptSuspectCentral,
  useDismissSuspectCentral,
} from "@/hooks/mutations/useRAFCentralMutations";
import ExplainPanel from "@/components/ExplainPanel";
import { cn } from "@/lib/utils";
import { confidenceTier, needsAcceptGate } from "@/lib/confidence";
import type { SuspectCard, SuspectMeat } from "../_shared";
import {
  AcceptConfirmDialog,
  type AcceptOverridePayload,
} from "@/components/AcceptConfirmDialog";
import { SemiGauge } from "./SemiGauge";
import { DismissReasonDialog } from "./DismissReasonDialog";

// ---------------------------------------------------------------------------
// Compact MEAT chip — 4 coloured squares, no external MEATBadge dependency
// ---------------------------------------------------------------------------
const MEAT_LETTERS: { key: keyof SuspectMeat; label: string; bg: string }[] = [
  { key: "monitor",  label: "M", bg: "bg-teal-500 dark:bg-teal-600"   },
  { key: "evaluate", label: "E", bg: "bg-purple-500 dark:bg-purple-600" },
  { key: "assess",   label: "A", bg: "bg-amber-500 dark:bg-amber-600"  },
  { key: "treat",    label: "T", bg: "bg-green-500 dark:bg-green-600"  },
];

function CompactMeatChip({ meat }: { meat?: SuspectMeat | null }) {
  if (meat === undefined || meat === null) {
    return (
      <span
        title="MEAT evidence not yet generated"
        className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[10px] font-semibold border border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-300 cursor-default select-none"
      >
        MEAT: unknown
      </span>
    );
  }
  return (
    <div className="inline-flex items-center gap-0.5" aria-label="MEAT completeness">
      {MEAT_LETTERS.map(({ key, label, bg }) => (
        <span
          key={key}
          title={`${label} (${key}) ${meat[key] ? "present" : "missing"}`}
          className={cn(
            "inline-flex h-5 w-5 items-center justify-center rounded text-[10px] font-bold text-white",
            meat[key] ? bg : "bg-muted text-muted-foreground"
          )}
        >
          {label}
        </span>
      ))}
    </div>
  );
}

/**
 * SuspectCardView — individual suspect condition card with Accept/Dismiss/Why actions.
 * Uses React Query mutations (useAcceptSuspectCentral / useDismissSuspectCentral).
 * ExplainPanel is mounted inside this component (portal-rendered by ExplainPanel itself).
 */
export function SuspectCardView({
  suspect,
  patientId,
  onChange,
  modelVersion,
  measurementYear,
}: {
  suspect: SuspectCard;
  patientId: number;
  onChange: () => void;
  /** Surfaced to AcceptConfirmDialog so the clinician sees which CMS-HCC
   *  model they are attesting under (V24 vs V28 can yield different RAF). */
  modelVersion?: string | null;
  measurementYear?: number | null;
}) {
  const [showExplain, setShowExplain] = useState(false);
  const [showDismissDialog, setShowDismissDialog] = useState(false);
  const [showAcceptGate, setShowAcceptGate] = useState(false);
  const [feedbackSent, setFeedbackSent] = useState(false);
  const toast = useToast();

  // Mutations — invalidate raf-central query key on success
  const acceptMut = useAcceptSuspectCentral(patientId);
  const dismissMut = useDismissSuspectCentral(patientId);

  // busy mirrors the pending state of whichever mutation is in-flight
  const busy: "accept" | "dismiss" | null = acceptMut.isPending
    ? "accept"
    : dismissMut.isPending
    ? "dismiss"
    : null;

  // Called after gate is passed (or bypassed for safe suspects).
  const acceptSuspect = async (override?: AcceptOverridePayload) => {
    await acceptMut.mutateAsync({
      suspect_id: suspect.id,
      push_to_emr: true,
      ...(override ?? {}),
    } as Parameters<typeof acceptMut.mutateAsync>[0]);
    onChange();
  };

  // Entry-point for the Accept button — gate is ALWAYS shown so every
  // accept gets a model-version disclosure and an explicit "writes to
  // billing record" attestation. Patient-safety review #2 / #A flagged
  // that high-confidence suspects were one-click-to-EMR with no
  // attestation, no model-version surfacing, and no audit prompt — a
  // billing-without-MEAT trail-of-breadcrumbs problem for RADV. The
  // ``needsAcceptGate`` helper is retained for analytics on which risk
  // bucket a suspect falls into, but no longer changes the UX.
  const handleAcceptClick = () => {
    void needsAcceptGate; // intentionally noop — see comment above
    setShowAcceptGate(true);
  };

  const handleAcceptConfirmed = async (payload: AcceptOverridePayload) => {
    setShowAcceptGate(false);
    await acceptSuspect(payload);
  };

  const dismissSuspect = async (reason: string) => {
    setShowDismissDialog(false);
    await dismissMut.mutateAsync({ suspect_id: suspect.id, reason });
    onChange();
    // No action button here. The Restore endpoint has not yet shipped — the
    // previous "Restore (coming soon)" disabled lure advertised an action
    // the system cannot perform (patient-safety review #5 / round-4 carry-
    // over). When `POST /api/raf-central/{pid}/actions/restore-suspect`
    // lands, re-add an `action` to this toast that actually calls it.
    toast.success("Suspect dismissed", suspect.label, { duration: 10_000 });
  };

  // Send clinician sentiment to the backend and disable buttons after one click.
  const sendFeedback = async (sentiment: "helpful" | "incorrect" | "irrelevant") => {
    if (feedbackSent) return;
    const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";
    try {
      const res = await fetch(
        `${API_BASE}/api/suspects/${suspect.id}/feedback`,
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sentiment }),
        }
      );
      if (res.status === 409) {
        toast.error("Feedback already submitted", "You have already rated this suspect today.");
        setFeedbackSent(true);
        return;
      }
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      setFeedbackSent(true);
      const label =
        sentiment === "helpful"
          ? "Marked as helpful"
          : sentiment === "incorrect"
          ? "Marked as incorrect"
          : "Marked as irrelevant";
      toast.success("Feedback noted", label);
    } catch {
      toast.error("Feedback failed", "Could not save your feedback. Please try again.");
    }
  };

  const confPct = Math.round((suspect.confidence ?? 0) * 100);
  const gaugeColor = confidenceTier(confPct).color;
  // V28 hierarchy: when this HCC is trumped by a higher-priority HCC, the
  // RAF scorer will drop it at calculation time. Surface the relationship
  // as a badge AND disable Accept — patient-safety review #7. Without this
  // a clinician can double-document a subordinate condition.
  const trumpedBy = suspect.trumped_by_hcc;
  const isTrumped = trumpedBy != null && trumpedBy > 0;

  return (
    <Card className="p-3 hover:bg-muted/50 transition-colors dark:hover:bg-muted/20">
      <div className="flex items-start gap-3">
        {/* Semicircle confidence gauge */}
        <SemiGauge value={confPct} color={gaugeColor} />

        <div className="flex-1 min-w-0">
          <span className="text-sm font-semibold leading-snug truncate block">{suspect.label}</span>
          <div className="mt-0.5 text-xs text-muted-foreground">
            HCC {suspect.hcc} · {suspect.icd10} · {suspect.trigger}
            {isTrumped && (
              <span
                className="ml-2 inline-flex items-center gap-1 rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-800 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-300"
                title={`CMS-HCC V28 will trump this code at scoring time. Accepting will not change the patient's RAF — HCC ${trumpedBy} already covers this hierarchy.`}
              >
                Trumped by HCC {trumpedBy}
              </span>
            )}
          </div>

          {/* Button hierarchy: Accept primary, Dismiss outline, Why? ghost */}
          <div className="mt-2.5 flex gap-2 items-center flex-wrap">
            <CompactMeatChip meat={suspect.meat} />
            <Button
              size="sm"
              onClick={handleAcceptClick}
              disabled={busy !== null || isTrumped}
              title={
                isTrumped
                  ? `Accept disabled — HCC ${trumpedBy} already covers this hierarchy in V28.`
                  : undefined
              }
            >
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
            {/* Feedback affordance — persisted via POST /api/suspects/{id}/feedback. */}
            <div
              className="ml-auto flex items-center gap-0.5"
              role="group"
              aria-label="Suggestion feedback"
            >
              <Button
                size="sm"
                variant="ghost"
                onClick={() => sendFeedback("helpful")}
                disabled={busy !== null || feedbackSent}
                aria-label="Suggestion was helpful"
                className="h-7 w-7 p-0 text-muted-foreground hover:text-emerald-600 disabled:opacity-40"
              >
                <ThumbsUp className="h-3.5 w-3.5" aria-hidden />
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => sendFeedback("incorrect")}
                disabled={busy !== null || feedbackSent}
                aria-label="Suggestion was incorrect"
                className="h-7 w-7 p-0 text-muted-foreground hover:text-red-600 disabled:opacity-40"
              >
                <ThumbsDown className="h-3.5 w-3.5" aria-hidden />
              </Button>
            </div>
          </div>
        </div>
      </div>
      <ExplainPanel
        patientId={patientId}
        suspectId={suspect.id}
        suspectLabel={suspect.label}
        open={showExplain}
        onClose={() => setShowExplain(false)}
        busy={busy}
        onAccept={async () => {
          setShowExplain(false);
          // Route through the gate — gate will call acceptSuspect on confirm.
          if (needsAcceptGate(suspect.confidence, suspect.meat_status, suspect.clinical_rule_violation)) {
            setShowAcceptGate(true);
          } else {
            await acceptSuspect();
          }
        }}
        onRequestDismiss={() => {
          setShowExplain(false);
          setShowDismissDialog(true);
        }}
      />
      <DismissReasonDialog
        open={showDismissDialog}
        suspectLabel={suspect.label}
        onCancel={() => setShowDismissDialog(false)}
        onSubmit={dismissSuspect}
      />
      <AcceptConfirmDialog
        open={showAcceptGate}
        onClose={() => setShowAcceptGate(false)}
        onConfirm={handleAcceptConfirmed}
        suspect={{
          hcc_code: suspect.hcc,
          icd10_code: suspect.icd10,
          confidence: suspect.confidence,
          meat_status: suspect.meat_status,
          meat_count: suspect.meat_count,
          clinical_rule_violation: suspect.clinical_rule_violation,
          expected_dollar_impact: suspect.expected_dollar_impact,
          model_version: modelVersion ?? null,
          measurement_year: measurementYear ?? null,
        }}
      />
    </Card>
  );
}
