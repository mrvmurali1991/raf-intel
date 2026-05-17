"use client";

import React, { useEffect, useRef, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Loader2, Check, XCircle, HelpCircle, ThumbsUp, ThumbsDown, MessageSquareWarning } from "lucide-react";
import { useToast } from "@/components/Toast";
import {
  useAcceptSuspectCentral,
  useDismissSuspectCentral,
  useRestoreSuspectCentral,
  useForceAcceptSuspect,
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
import { registerContextShortcut } from "@/lib/keyboard-shortcuts";
import { KeyHint } from "@/components/ui/key-hint";

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
  const [showForceAcceptDialog, setShowForceAcceptDialog] = useState(false);
  const [forceAcceptMrn, setForceAcceptMrn] = useState("");
  const [forceAcceptReason, setForceAcceptReason] = useState("");
  const [forceAcceptSubmitting, setForceAcceptSubmitting] = useState(false);
  const [queryDialogOpen, setQueryDialogOpen] = useState(false);
  const [queryText, setQueryText] = useState("");
  const [querySubmitting, setQuerySubmitting] = useState(false);
  const [feedbackSent, setFeedbackSent] = useState(false);
  const queryTriggerRef = useRef<HTMLButtonElement | null>(null);
  const queryTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const queryCloseBtnRef = useRef<HTMLButtonElement | null>(null);
  const queryDialogRef = useRef<HTMLDivElement | null>(null);
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
        // Scope the Send-button lookup to THIS dialog so a second
        // SuspectCardView mounted on the same page (or a parallel
        // dialog) can't bleed into our focus trap. UX review N+2
        // blocker.
        const sendBtn = queryDialogRef.current?.querySelector<HTMLButtonElement>(
          "[data-cq-send='1']",
        ) ?? null;
        const focusable: HTMLElement[] = [
          queryTextareaRef.current,
          queryCloseBtnRef.current,
          sendBtn,
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
  const restoreMut = useRestoreSuspectCentral(patientId);
  const forceAcceptMut = useForceAcceptSuspect(patientId);

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

  // Whether MEAT is fully absent — Accept must be blocked in this case.
  // "missing" status OR null/undefined meat_completeness (engine never ran)
  // both count. A signed attestation lifts the block regardless.
  const isMeatMissing =
    suspect.attestation_signed_at == null &&
    (suspect.meat_status === "missing" || suspect.meat_completeness == null);

  // Entry-point for the Accept button — blocked entirely when MEAT is missing
  // so the clinician must either add MEAT evidence or use Force Accept with an
  // explicit audit trail. Otherwise the gate is always shown for model-version
  // disclosure + RADV attestation. Patient-safety review #2/#A.
  const handleAcceptClick = () => {
    if (isMeatMissing) return; // button is disabled; guard for safety
    setShowAcceptGate(true);
  };

  // Force-accept handler — writes SUSPECT_FORCE_ACCEPTED_NO_MEAT audit event.
  const handleForceAccept = async () => {
    if (forceAcceptReason.trim().length < 20) return;
    setForceAcceptSubmitting(true);
    try {
      await forceAcceptMut.mutateAsync({
        suspect_id: suspect.id,
        mrn_confirmation: forceAcceptMrn.trim(),
        force_reason: forceAcceptReason.trim(),
      });
      setShowForceAcceptDialog(false);
      setForceAcceptMrn("");
      setForceAcceptReason("");
      onChange();
      toast.success("Force-accepted", `${suspect.label} accepted with RADV-risk audit logged.`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Force accept failed.";
      toast.error("Force accept failed", msg);
    } finally {
      setForceAcceptSubmitting(false);
    }
  };

  const handleAcceptConfirmed = async (payload: AcceptOverridePayload) => {
    setShowAcceptGate(false);
    await acceptSuspect(payload);
  };

  const dismissSuspect = async (reason: string) => {
    setShowDismissDialog(false);
    await dismissMut.mutateAsync({ suspect_id: suspect.id, reason });
    onChange();
    // Restore endpoint (POST /api/raf-central/{pid}/actions/restore-suspect)
    // is now live — the toast action calls it, the panel cache is
    // invalidated by the mutation's onSuccess, and onChange() re-syncs the
    // list view so the resurfaced suspect reappears in 'open'. Patient-
    // safety review #5 closes: no more disabled "coming soon" lure.
    toast.success("Suspect dismissed", suspect.label, {
      duration: 10_000,
      action: {
        label: "Restore",
        onClick: () => {
          restoreMut.mutate(
            { suspect_id: suspect.id },
            {
              onSuccess: () => {
                onChange();
                toast.success("Suspect restored", suspect.label);
              },
              onError: (err: unknown) => {
                const msg =
                  err instanceof Error ? err.message : "Could not restore suspect.";
                toast.error("Restore failed", msg);
              },
            },
          );
        },
      },
    });
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
    // "confirmed" requires claim_history evidence OR a signed attestation so
    // that MEAT-guessed completeness alone cannot promote a suspect to
    // "Confirmed". Safety review round-N+1 #2 + Fix 1 taxonomy requirement.
    const evidenceConfirmed =
      ev === "claim_history" || suspect.attestation_signed_at != null;
    if (meat >= 0.75 && conf >= 0.80 && ruleOk && evidenceConfirmed) return "confirmed" as const;
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

  // ----- Keyboard shortcuts: A / D / R fire on the focused card -----------
  // Register handlers only while a child of this card has focus; the global
  // shortcut layer keeps a LIFO stack so the most-recently-focused card
  // wins.  Without this, Tab-navigating through a list of suspects would
  // ambiguously dispatch shortcuts.
  const cardRef = useRef<HTMLDivElement | null>(null);
  const [isFocused, setIsFocused] = useState(false);
  useEffect(() => {
    if (!isFocused) return;
    const offAccept = registerContextShortcut("accept-focused-suspect", () => {
      if (busy || isTrumped) return;
      handleAcceptClick();
    });
    const offDismiss = registerContextShortcut("dismiss-focused-suspect", () => {
      if (busy) return;
      setShowDismissDialog(true);
    });
    // "R = mark MEAT reviewed" — sends a positive feedback signal (the
    // closest existing API affordance) until a dedicated meat-reviewed
    // endpoint ships.
    const offMeat = registerContextShortcut("mark-meat-reviewed", () => {
      if (feedbackSent) return;
      void sendFeedback("helpful");
    });
    return () => {
      offAccept();
      offDismiss();
      offMeat();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isFocused, busy, isTrumped, feedbackSent]);

  return (
    <Card
      ref={cardRef as unknown as React.Ref<HTMLDivElement>}
      tabIndex={0}
      data-suspect-card={suspect.id}
      onFocus={() => setIsFocused(true)}
      onBlur={(e: React.FocusEvent<HTMLDivElement>) => {
        // Only mark "blurred" once focus truly leaves the card subtree
        if (!cardRef.current?.contains(e.relatedTarget as Node | null)) {
          setIsFocused(false);
        }
      }}
      className="p-3 hover:bg-muted/50 transition-colors dark:hover:bg-muted/20 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:ring-offset-1"
    >
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
              disabled={busy !== null || isTrumped || isMeatMissing}
              title={
                isTrumped
                  ? `Accept disabled — HCC ${trumpedBy} already covers this hierarchy in V28.`
                  : isMeatMissing
                  ? "Add MEAT evidence before accepting."
                  : undefined
              }
              aria-disabled={isMeatMissing || isTrumped || busy !== null}
            >
              {busy === "accept" ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <><Check className="h-3 w-3 mr-1" aria-hidden /> Accept<KeyHint>A</KeyHint></>
              )}
            </Button>
            {isMeatMissing && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setShowForceAcceptDialog(true)}
                disabled={busy !== null}
                title="Force-accept despite missing MEAT — logs a RADV-risk audit event"
                className="text-xs text-amber-700 dark:text-amber-400 hover:text-amber-900 dark:hover:text-amber-200 px-2"
              >
                Force accept (RADV risk)
              </Button>
            )}
            <Button
              size="sm"
              variant="outline"
              onClick={() => setShowDismissDialog(true)}
              disabled={busy !== null}
            >
              {busy === "dismiss" ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <><XCircle className="h-3 w-3 mr-1" aria-hidden /> Dismiss<KeyHint>D</KeyHint></>
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
              <HelpCircle className="h-3 w-3 mr-1" aria-hidden /> Why?<KeyHint>R</KeyHint>
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
          ref={queryDialogRef}
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
      {/* Force-accept dialog — shown only when MEAT is missing and the user
          clicks "Force accept (RADV risk)". Requires MRN confirmation + a
          minimum-20-char reason before submitting. Writes audit event
          SUSPECT_FORCE_ACCEPTED_NO_MEAT via the forceAcceptMut mutation. */}
      {showForceAcceptDialog && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="force-accept-title"
          className="fixed inset-0 z-50 bg-black/75 flex items-center justify-center p-4"
          onClick={() => !forceAcceptSubmitting && setShowForceAcceptDialog(false)}
        >
          <div
            className="bg-white dark:bg-zinc-900 rounded-lg shadow-2xl w-full max-w-md p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center gap-2 mb-1">
              <span
                className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-red-100 dark:bg-red-900/40 text-red-600 dark:text-red-400 text-xs font-bold shrink-0"
                aria-hidden="true"
              >
                !
              </span>
              <h3 id="force-accept-title" className="text-base font-bold text-red-700 dark:text-red-400">
                Force accept — RADV risk
              </h3>
            </div>
            <p className="text-xs text-muted-foreground mb-3">
              {suspect.label} · HCC {suspect.hcc} · {suspect.icd10}
            </p>
            <div
              className="rounded-md border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/30 px-3 py-2 text-xs text-red-900 dark:text-red-200 mb-4"
              role="alert"
            >
              Accepting without MEAT documentation creates a RADV audit
              exposure. This action will be logged as{" "}
              <strong>SUSPECT_FORCE_ACCEPTED_NO_MEAT</strong> and may be
              reviewed during a CMS audit.
            </div>
            <div className="space-y-3">
              <div>
                <label
                  htmlFor="force-accept-mrn"
                  className="block text-sm font-medium mb-1"
                >
                  Confirm patient MRN (or last 4 digits)
                  <span className="text-destructive ml-1" aria-hidden="true">*</span>
                </label>
                <input
                  id="force-accept-mrn"
                  type="text"
                  value={forceAcceptMrn}
                  onChange={(e) => setForceAcceptMrn(e.target.value)}
                  placeholder="e.g. 1234"
                  autoFocus
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  aria-label="Patient MRN confirmation"
                  disabled={forceAcceptSubmitting}
                />
              </div>
              <div>
                <label
                  htmlFor="force-accept-reason"
                  className="block text-sm font-medium mb-1"
                >
                  Clinical reason for override
                  <span className="text-destructive ml-1" aria-hidden="true">*</span>
                </label>
                <textarea
                  id="force-accept-reason"
                  value={forceAcceptReason}
                  onChange={(e) => setForceAcceptReason(e.target.value)}
                  placeholder="Explain why this suspect should be accepted despite missing MEAT documentation…"
                  rows={3}
                  className="w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  aria-label="Force accept reason"
                  aria-describedby="force-reason-hint"
                  disabled={forceAcceptSubmitting}
                />
                <p
                  id="force-reason-hint"
                  className={`mt-0.5 text-xs ${
                    forceAcceptReason.trim().length >= 20
                      ? "text-emerald-600 dark:text-emerald-400"
                      : "text-muted-foreground"
                  }`}
                >
                  {forceAcceptReason.trim().length >= 20
                    ? "Minimum length met."
                    : `${20 - forceAcceptReason.trim().length} more character${20 - forceAcceptReason.trim().length === 1 ? "" : "s"} required`}
                </p>
              </div>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <Button
                variant="outline"
                onClick={() => {
                  setShowForceAcceptDialog(false);
                  setForceAcceptMrn("");
                  setForceAcceptReason("");
                }}
                disabled={forceAcceptSubmitting}
              >
                Cancel
              </Button>
              <Button
                variant="destructive"
                onClick={handleForceAccept}
                disabled={
                  forceAcceptSubmitting ||
                  forceAcceptMrn.trim().length === 0 ||
                  forceAcceptReason.trim().length < 20
                }
                aria-label="Confirm force accept with RADV risk acknowledged"
              >
                {forceAcceptSubmitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  "Accept anyway — log audit"
                )}
              </Button>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
