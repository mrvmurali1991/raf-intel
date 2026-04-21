"use client";

import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Loader2, Check, XCircle, HelpCircle } from "lucide-react";
import { useToast } from "@/components/Toast";
import {
  useAcceptSuspectCentral,
  useDismissSuspectCentral,
} from "@/hooks/mutations/useRAFCentralMutations";
import ExplainPanel from "@/components/ExplainPanel";
import type { SuspectCard } from "../_shared";
import { SemiGauge } from "./SemiGauge";
import { DismissReasonDialog } from "./DismissReasonDialog";

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

  const acceptSuspect = async () => {
    await acceptMut.mutateAsync({ suspect_id: suspect.id, push_to_emr: true });
    onChange();
  };

  const dismissSuspect = async (reason: string) => {
    setShowDismissDialog(false);
    await dismissMut.mutateAsync({ suspect_id: suspect.id, reason });
    onChange();
    // TODO: No restore endpoint exists yet — Undo button closes the toast without action.
    // When a restore endpoint is added, call it here instead of just closing.
    toast.success(
      "Suspect dismissed",
      suspect.label,
      {
        duration: 10_000,
        action: {
          label: "Undo",
          onClick: () => {
            // No restore endpoint available yet — dismiss the toast only.
            // TODO: POST /api/raf-central/{pid}/actions/restore-suspect when endpoint exists.
          },
        },
      }
    );
  };

  const confPct = Math.round(suspect.confidence * 100);
  const gaugeColor: "emerald" | "amber" | "red" =
    confPct >= 85 ? "emerald" : confPct >= 70 ? "amber" : "red";

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
            <Button size="sm" onClick={acceptSuspect} disabled={busy !== null}>
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
          </div>
        </div>
      </div>
      <ExplainPanel
        patientId={patientId}
        suspectId={suspect.id}
        suspectLabel={suspect.label}
        open={showExplain}
        onClose={() => setShowExplain(false)}
      />
      <DismissReasonDialog
        open={showDismissDialog}
        suspectLabel={suspect.label}
        onCancel={() => setShowDismissDialog(false)}
        onSubmit={dismissSuspect}
      />
    </Card>
  );
}
