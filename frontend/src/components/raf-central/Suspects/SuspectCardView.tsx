"use client";

import { useEffect, useRef, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Loader2, Check, XCircle, HelpCircle, ThumbsUp, ThumbsDown, MessageSquareWarning } from "lucide-react";
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
  const [queryDialogOpen, setQueryDialogOpen] = useState(false);
  const [queryText, setQueryText] = useState("");
  const [querySubmitting, setQuerySubmitting] = useState(false);
  const [feedbackSent, setFeedbackSent] = useState(false);
  const queryTriggerRef = useRef<HTMLButtonElement | null>(null);
  const queryTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const queryCloseBtnRef = useRef<HTMLButtonElement | null>(null);
  const toast = useToast();

  // Focus management for the Request-docs dialog (UX review blocker #2):
  //   - Esc closes the dialog
  //   - Tab is trapped between the textarea, Cancel, and Send buttons
  //   - Focus returns to the originating "Request docs" button on close
  useEffect(() => {
    if (!queryDialogOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        if (!querySubmitting) setQueryDialogOpen(false);
      }
      if (e.key === "Tab") {
        const focusable: HTMLElement[] = [
          queryTextareaRef.current,
          queryCloseBtnRef.current,
          // Send button is found dynamically since it carries varying disabled state
          document.querySelector<HTMLButtonElement>("[data-cq-send='1']"),
        ].filter(Boolean) as HTMLElement[];
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        const active = document.activeElement as HTMLElement | null;
        if (e.shiftKey && active === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && active === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [queryDialogOpen, querySubmitting]);

  useEffect(() => {
    if (queryDialogOpen) return;
    // Restore focus to the trigger after close so keyboard users don't
    // dump back to <body>.
    queryTriggerRef.current?.focus();
  }, [queryDialogOpen]);

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

  // Net-new / Audit / Confirmed taxonomy — Apixio's HCC-Complete pattern.
  // Drives the badge color and clarifies the coder's action path: a
  // net-new suspect needs evidence to submit; an audit row needs
  // documentation review BEFORE submission; a confirmed row is
  // informational. Backend may eventually ship suspect.taxonomy; until
  // then we derive it from evidence_type + meat_completeness.
  //
  // Safety guard: "confirmed" implies "safe to accept" in the badge
  // tooltip. The derivation MUST require BOTH high MEAT completeness
  // AND high confidence AND no clinical-rule violation — otherwise a
  // 35%-confidence suspect with thin evidence can be mislabeled
  // "Confirmed" purely on a MEAT score the engine guessed at. Safety
  // review round-N+1 #2.
  const taxonomy = (() => {
    if (suspect.taxonomy) return suspect.taxonomy;
    const meat = suspect.meat_completeness ?? 0;
    const conf = suspect.confidence ?? 0;
    const ev = (suspect.evidence_type || "").toLowerCase();
    if (ev.startsWith("hist") || ev.startsWith("recap")) return "audit" as const;
    const ruleOk = !suspect.clinical_rule_violation;
    if (meat >= 0.75 && conf >= 0.80 && ruleOk) return "confirmed" as const;
    return "new" as const;
  })();
  const taxonomyMeta = {
    new:       { label: "Net-new",   className: "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300", title: "Net-new suspect — evidence supports a diagnosis that has not been coded before. Accept to add it to the patient's problem list." },
    audit:     { label: "Audit",     className: "border-amber-300   bg-amber-50   text-amber-800   dark:border-amber-700   dark:bg-amber-950/40   dark:text-amber-300",   title: "Audit candidate — diagnosis was coded in a prior year but current MEAT documentation is thin. Review the chart before re-billing." },
    confirmed: { label: "Confirmed", className: "border-sky-300     bg-sky-50     text-sky-800     dark:border-sky-700     dark:bg-sky-950/40     dark:text-sky-300",     title: "Already-validated suspect — MEAT documentation is sufficient. Informational; safe to accept." },
  }[taxonomy];
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
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold leading-snug truncate flex-1">{suspect.label}</span>
            <span
              className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${taxonomyMeta.className}`}
              title={taxonomyMeta.title}
            >
              {taxonomyMeta.label}
            </span>
          </div>
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
            <Button
              size="sm"
              variant="ghost"
              ref={queryTriggerRef}
              onClick={() => setQueryDialogOpen(true)}
              disabled={busy !== null}
              aria-label="Request documentation from the provider"
              title="Open a structured query to the PCP asking for documentation that supports this suspect. Status tracked Pending → Replied → Closed."
              className="text-muted-foreground hover:text-foreground px-2"
            >
              <MessageSquareWarning className="h-3 w-3 mr-1" aria-hidden /> Request docs
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
      {queryDialogOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Request documentation"
          className="fixed inset-0 z-50 bg-black/75 flex items-center justify-center p-4"
          onClick={() => !querySubmitting && setQueryDialogOpen(false)}
        >
          <div
            className="bg-white dark:bg-zinc-900 rounded-lg shadow-2xl w-full max-w-md p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-base font-bold mb-1">Request documentation</h3>
            <p className="text-xs text-muted-foreground mb-3">
              {suspect.label} · HCC {suspect.hcc} · {suspect.icd10}
            </p>
            <p className="text-xs text-muted-foreground mb-3">
              Routes a structured query to the PCP for the documentation that
              would support this suspect. Status tracked Pending → Replied →
              Closed in the patient&apos;s query log.
            </p>
            <textarea
              ref={queryTextareaRef}
              value={queryText}
              onChange={(e) => setQueryText(e.target.value)}
              placeholder="Describe the documentation needed — e.g., 'Please confirm current eGFR trend and CKD stage for PY 2026'"
              rows={4}
              className="w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              aria-label="Documentation request"
              autoFocus
            />
            <div className="mt-2 text-[11px] text-muted-foreground">
              {queryText.trim().length < 10
                ? `${10 - queryText.trim().length} more character${10 - queryText.trim().length === 1 ? "" : "s"} required`
                : "Ready to send."}
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <Button
                variant="outline"
                ref={queryCloseBtnRef}
                onClick={() => setQueryDialogOpen(false)}
                disabled={querySubmitting}
              >
                Cancel
              </Button>
              <Button
                data-cq-send="1"
                onClick={async () => {
                  if (queryText.trim().length < 10) return;
                  setQuerySubmitting(true);
                  try {
                    const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";
                    const res = await fetch(`${API_BASE}/api/clinical-queries`, {
                      method: "POST",
                      credentials: "include",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({
                        patient_id: patientId,
                        suspect_id: suspect.id,
                        hcc_code: String(suspect.hcc),
                        icd10_code: suspect.icd10,
                        query_text: queryText.trim(),
                      }),
                    });
                    if (res.ok) {
                      toast.success("Query sent", "PCP will be notified to respond.");
                      setQueryText("");
                      setQueryDialogOpen(false);
                    } else {
                      const body = await res.json().catch(() => ({}));
                      toast.error("Could not send", body.detail || `HTTP ${res.status}`);
                    }
                  } catch (e) {
                    toast.error("Network error", String(e));
                  } finally {
                    setQuerySubmitting(false);
                  }
                }}
                disabled={queryText.trim().length < 10 || querySubmitting}
              >
                {querySubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : "Send query"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
