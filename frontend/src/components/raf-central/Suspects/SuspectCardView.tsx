"use client";

import React, { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Loader2 } from "lucide-react";
import { useToast } from "@/components/Toast";
import {
  useAcceptSuspectCentral,
  useDismissSuspectCentral,
  useRestoreSuspectCentral,
  useForceAcceptSuspect,
} from "@/hooks/mutations/useRAFCentralMutations";
import ExplainPanel from "@/components/ExplainPanel";
import { needsAcceptGate } from "@/lib/confidence";
import api from "@/lib/api";
import type { SuspectCard } from "../_shared";
import {
  AcceptConfirmDialog,
  type AcceptOverridePayload,
} from "@/components/AcceptConfirmDialog";
import { DismissReasonDialog } from "./DismissReasonDialog";
import { registerContextShortcut } from "@/lib/keyboard-shortcuts";
import { SuspectRow } from "@/components/ui/suspect-row";

/**
 * SuspectCardView — individual suspect condition with Accept/Dismiss/Why actions.
 *
 * Layout: delegates to SuspectRow (horizontal, information-dense) for all visual
 * structure. This component owns all mutations, dialogs, keyboard shortcuts, and
 * feedback logic — SuspectRow is a pure display primitive.
 *
 * Uses React Query mutations (useAcceptSuspectCentral / useDismissSuspectCentral).
 * ExplainPanel is portal-rendered by ExplainPanel itself.
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
  const queryTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const queryCloseBtnRef = useRef<HTMLButtonElement | null>(null);
  const queryDialogRef = useRef<HTMLDivElement | null>(null);
  const toast = useToast();

  // Focus management for the Request-docs dialog:
  //   - Esc closes the dialog
  //   - Tab is trapped between the textarea, Cancel, and Send buttons
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
        // dialog) can't bleed into our focus trap. UX review N+2 blocker.
        const sendBtn =
          queryDialogRef.current?.querySelector<HTMLButtonElement>(
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
      toast.success(
        "Force-accepted",
        `${suspect.label} accepted with RADV-risk audit logged.`,
      );
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
                  err instanceof Error
                    ? err.message
                    : "Could not restore suspect.";
                toast.error("Restore failed", msg);
              },
            },
          );
        },
      },
    });
  };

  // Send clinician sentiment to the backend and disable buttons after one click.
  // Use the shared `api` client so the Bearer token and X-Active-Tenant header
  // are injected by the interceptor (raw fetch skipped both — broke for any
  // tenant other than the default).
  const sendFeedback = async (
    sentiment: "helpful" | "incorrect" | "irrelevant",
  ) => {
    if (feedbackSent) return;
    try {
      await api.post(`/api/suspects/${suspect.id}/feedback`, { sentiment });
      setFeedbackSent(true);
      const label =
        sentiment === "helpful"
          ? "Marked as helpful"
          : sentiment === "incorrect"
          ? "Marked as incorrect"
          : "Marked as irrelevant";
      toast.success("Feedback noted", label);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response
        ?.status;
      if (status === 409) {
        toast.error(
          "Feedback already submitted",
          "You have already rated this suspect today.",
        );
        setFeedbackSent(true);
        return;
      }
      toast.error(
        "Feedback failed",
        "Could not save your feedback. Please try again.",
      );
    }
  };

  // Net-new / Audit / Confirmed taxonomy — Apixio's HCC-Complete pattern.
  // Drives the badge color and clarifies the coder's action path.
  //
  // Safety guard: "confirmed" requires claim_history evidence OR a signed
  // attestation so MEAT-guessed completeness alone cannot promote a suspect.
  // Safety review round-N+1 #2.
  const taxonomy = (() => {
    if (suspect.taxonomy) return suspect.taxonomy;
    const meat = suspect.meat_completeness ?? 0;
    const conf = suspect.confidence ?? 0;
    const ev = (suspect.evidence_type || "").toLowerCase();
    if (ev.startsWith("hist") || ev.startsWith("recap"))
      return "audit" as const;
    const ruleOk = !suspect.clinical_rule_violation;
    const evidenceConfirmed =
      ev === "claim_history" || suspect.attestation_signed_at != null;
    if (meat >= 0.75 && conf >= 0.8 && ruleOk && evidenceConfirmed)
      return "confirmed" as const;
    return "new" as const;
  })();

  const taxonomyMeta = {
    new: {
      label: "Net-new",
      className:
        "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300",
      title:
        "Net-new suspect — evidence supports a diagnosis that has not been coded before. Accept to add it to the patient's problem list.",
    },
    audit: {
      label: "Audit",
      className:
        "border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-300",
      title:
        "Audit candidate — diagnosis was coded in a prior year but current MEAT documentation is thin. Review the chart before re-billing.",
    },
    confirmed: {
      label: "Confirmed",
      className:
        "border-sky-300 bg-sky-50 text-sky-800 dark:border-sky-700 dark:bg-sky-950/40 dark:text-sky-300",
      title:
        "Already-validated suspect — MEAT documentation is sufficient. Informational; safe to accept.",
    },
  }[taxonomy];

  // V28 hierarchy: when this HCC is trumped by a higher-priority HCC, the
  // RAF scorer will drop it at calculation time. Surface the relationship
  // as a badge AND disable Accept — patient-safety review #7.
  const trumpedBy = suspect.trumped_by_hcc;
  const isTrumped = trumpedBy != null && trumpedBy > 0;

  // ----- Keyboard shortcuts: A / D / R fire on the focused card -----------
  // Register handlers only while a child of this card has focus; the global
  // shortcut layer keeps a LIFO stack so the most-recently-focused card
  // wins. Without this, Tab-navigating through a list of suspects would
  // ambiguously dispatch shortcuts.
  const cardRef = useRef<HTMLDivElement | null>(null);
  const [isFocused, setIsFocused] = useState(false);
  useEffect(() => {
    if (!isFocused) return;
    const offAccept = registerContextShortcut("accept-focused-suspect", () => {
      if (busy || isTrumped) return;
      handleAcceptClick();
    });
    const offDismiss = registerContextShortcut(
      "dismiss-focused-suspect",
      () => {
        if (busy) return;
        setShowDismissDialog(true);
      },
    );
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
    <div
      ref={cardRef}
      tabIndex={0}
      data-suspect-card={suspect.id}
      onFocus={() => setIsFocused(true)}
      onBlur={(e: React.FocusEvent<HTMLDivElement>) => {
        // Only mark "blurred" once focus truly leaves the card subtree
        if (!cardRef.current?.contains(e.relatedTarget as Node | null)) {
          setIsFocused(false);
        }
      }}
      className="rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400 focus-visible:ring-offset-1"
    >
      {/* ── Main horizontal row — SuspectRow owns all layout/visual structure ── */}
      <SuspectRow
        hcc={suspect.hcc}
        icd10={suspect.icd10}
        label={suspect.label}
        confidence={suspect.confidence ?? 0}
        meat={suspect.meat}
        meatStatus={suspect.meat_status}
        revenueDollars={suspect.expected_dollar_impact}
        evidenceSource={suspect.evidence_type}
        taxonomyBadge={taxonomyMeta}
        isTrumped={isTrumped}
        trumpedByHcc={trumpedBy ?? null}
        isMeatMissing={isMeatMissing}
        busy={busy}
        onAccept={handleAcceptClick}
        onDismiss={() => setShowDismissDialog(true)}
        onWhy={() => setShowExplain(true)}
        onRequestDocs={() => setQueryDialogOpen(true)}
        onForceAccept={() => setShowForceAcceptDialog(true)}
        onFeedbackHelpful={() => sendFeedback("helpful")}
        onFeedbackIncorrect={() => sendFeedback("incorrect")}
        feedbackSent={feedbackSent}
      />

      {/* ── Dialogs and panels (portal-rendered, always present in DOM) ── */}
      <ExplainPanel
        patientId={patientId}
        suspectId={suspect.id}
        suspectLabel={suspect.label}
        open={showExplain}
        onClose={() => setShowExplain(false)}
        busy={busy}
        suspectMeat={suspect.meat ?? null}
        suspectDollarImpact={suspect.expected_dollar_impact ?? null}
        onAccept={async () => {
          setShowExplain(false);
          // Route through the gate — gate will call acceptSuspect on confirm.
          if (
            needsAcceptGate(
              suspect.confidence,
              suspect.meat_status,
              suspect.clinical_rule_violation,
            )
          ) {
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

      {/* Request-docs dialog */}
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
                    await api.post("/api/clinical-queries", {
                      patient_id: patientId,
                      suspect_id: suspect.id,
                      hcc_code: String(suspect.hcc),
                      icd10_code: suspect.icd10,
                      query_text: queryText.trim(),
                    });
                    toast.success("Query sent", "PCP will be notified to respond.");
                    setQueryText("");
                    setQueryDialogOpen(false);
                  } catch (err: unknown) {
                    const detail = (
                      err as { response?: { data?: { detail?: string } } }
                    )?.response?.data?.detail;
                    const status = (err as { response?: { status?: number } })
                      ?.response?.status;
                    toast.error(
                      "Could not send",
                      detail || `HTTP ${status ?? "?"}`,
                    );
                  } finally {
                    setQuerySubmitting(false);
                  }
                }}
                disabled={queryText.trim().length < 10 || querySubmitting}
              >
                {querySubmitting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  "Send query"
                )}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Force-accept dialog — shown only when MEAT is missing.
          Requires MRN confirmation + a minimum-20-char reason.
          Writes audit event SUSPECT_FORCE_ACCEPTED_NO_MEAT. */}
      {showForceAcceptDialog && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="force-accept-title"
          className="fixed inset-0 z-50 bg-black/75 flex items-center justify-center p-4"
          onClick={() =>
            !forceAcceptSubmitting && setShowForceAcceptDialog(false)
          }
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
              <h3
                id="force-accept-title"
                className="text-base font-bold text-red-700 dark:text-red-400"
              >
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
                  <span className="text-destructive ml-1" aria-hidden="true">
                    *
                  </span>
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
                  <span className="text-destructive ml-1" aria-hidden="true">
                    *
                  </span>
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
                    : `${20 - forceAcceptReason.trim().length} more character${
                        20 - forceAcceptReason.trim().length === 1 ? "" : "s"
                      } required`}
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
    </div>
  );
}
