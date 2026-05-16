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
}: {
  suspect: SuspectCard;
  patientId: number;
  onChange: () => void;
}) {
  const [showExplain, setShowExplain] = useState(false);
  const [showDismissDialog, setShowDismissDialog] = useState(false);
  const [showAcceptGate, setShowAcceptGate] = useState(false);
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

  // Entry-point for the Accept button — gate is shown only when risks are present.
  const handleAcceptClick = () => {
    if (needsAcceptGate(suspect.confidence, suspect.meat_status, suspect.clinical_rule_violation)) {
      setShowAcceptGate(true);
    } else {
      acceptSuspect();
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
    // The restore endpoint has not shipped yet, so the action button is
    // disabled and labelled "Restore (coming soon)". Once the backend
    // route POST /api/raf-central/{pid}/actions/restore-suspect ships,
    // remove `disabled` and call it from onClick below.
    toast.success(
      "Suspect dismissed",
      suspect.label,
      {
        duration: 10_000,
        action: {
          label: "Restore (coming soon)",
          disabled: true,
          onClick: () => {
            // No-op until the restore endpoint exists.
          },
        },
      }
    );
  };

  // Lightweight feedback affordance — closes the model-trust loop. Real
  // backend wiring is a follow-up ticket; for now we log + toast so usage
  // signals show up in browser logs and the user gets immediate ack.
  const sendFeedback = (helpful: boolean) => {
    const event = {
      suspect_id: suspect.id,
      hcc: suspect.hcc,
      icd10: suspect.icd10,
      helpful,
      ts: new Date().toISOString(),
    };
    // eslint-disable-next-line no-console
    console.info("[suspect-feedback]", event);
    // TODO: POST /api/suspects/${suspect.id}/feedback once endpoint exists.
    toast.success("Feedback noted", helpful ? "Marked as helpful" : "Marked as incorrect");
  };

  const confPct = Math.round(suspect.confidence * 100);
  const gaugeColor = confidenceTier(confPct).color;

  return (
    <Card className="p-3 hover:bg-muted/50 transition-colors dark:hover:bg-muted/20">
      <div className="flex items-start gap-3">
        {/* Semicircle confidence gauge */}
        <SemiGauge value={confPct} color={gaugeColor} />

        <div className="flex-1 min-w-0">
          <span className="text-sm font-semibold leading-snug truncate block">{suspect.label}</span>
          <div className="mt-0.5 text-xs text-muted-foreground">
            HCC {suspect.hcc} · {suspect.icd10} · {suspect.trigger}
          </div>

          {/* Button hierarchy: Accept primary, Dismiss outline, Why? ghost */}
          <div className="mt-2.5 flex gap-2 items-center flex-wrap">
            <CompactMeatChip meat={suspect.meat} />
            <Button size="sm" onClick={handleAcceptClick} disabled={busy !== null}>
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
            {/* Feedback affordance — thin scaffold; backend wiring is a follow-up ticket. */}
            <div
              className="ml-auto flex items-center gap-0.5"
              role="group"
              aria-label="Suggestion feedback"
            >
              <Button
                size="sm"
                variant="ghost"
                onClick={() => sendFeedback(true)}
                disabled={busy !== null}
                aria-label="Suggestion was helpful"
                className="h-7 w-7 p-0 text-muted-foreground hover:text-emerald-600"
              >
                <ThumbsUp className="h-3.5 w-3.5" aria-hidden />
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => sendFeedback(false)}
                disabled={busy !== null}
                aria-label="Suggestion was incorrect"
                className="h-7 w-7 p-0 text-muted-foreground hover:text-red-600"
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
        }}
      />
    </Card>
  );
}
