"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Loader2, Check, MoreHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";
import { OrderLabButton } from "@/components/OrderLabButton";
import StartTreatmentButton from "@/components/StartTreatmentButton";
import { useMEATAttest } from "@/hooks/mutations/useRAFCentralMutations";
import type { MEATGap } from "../_shared";
import { Tooltip } from "../common/Tooltip";
import { LetterDots } from "./LetterDots";
import { MEATAttestationDialog } from "./MEATAttestationDialog";

/**
 * MEATRow — compact row used in the dashboard layout priority buckets.
 * Uses useMEATAttest React Query mutation for attestation.
 */
export function MEATRow({
  gap,
  patientId,
  year,
  onChange,
  isOdd,
}: {
  gap: MEATGap;
  patientId: number;
  year?: number;
  onChange: () => void;
  isOdd: boolean;
}) {
  const [overflowOpen, setOverflowOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<"review" | "notes" | null>(null);

  // Mutation — invalidates raf-central query on success
  const meatMut = useMEATAttest(patientId, year);
  const busy = meatMut.isPending;

  const railColor =
    gap.coefficient >= 0.4
      ? "bg-red-500"
      : gap.coefficient >= 0.15
      ? "bg-amber-500"
      : "bg-slate-400";

  const doneCount = [gap.gaps.monitor, gap.gaps.evaluate, gap.gaps.assess, gap.gaps.treat].filter(
    Boolean
  ).length;
  const isComplete = gap.status === "COMPLETE";

  const statusLabel = isComplete
    ? "Complete"
    : gap.status === "PARTIAL"
    ? `Partial (${doneCount}/4)`
    : "Missing";
  const statusClass = isComplete
    ? "text-emerald-700 dark:text-emerald-400"
    : gap.status === "PARTIAL"
    ? "text-amber-700 dark:text-amber-400"
    : "text-red-700 dark:text-red-400";

  const missing = (Object.entries(gap.gaps) as [keyof MEATGap["gaps"], boolean][])
    .filter(([, on]) => !on)
    .map(([k]) => k);
  const missingLabel = missing.map((k) => k[0].toUpperCase() + k.slice(1)).join(", ");

  const submitMeat = async (note: string) => {
    if (!gap.patient_hcc_id) return;
    setDialogMode(null);
    await meatMut.mutateAsync({
      patient_hcc_id: gap.patient_hcc_id,
      monitor_note: gap.gaps.monitor ? null : note,
      evaluate_note: gap.gaps.evaluate ? null : note,
      assess_note: gap.gaps.assess ? null : note,
      treat_note: gap.gaps.treat ? null : note,
    });
    onChange();
  };

  const markReviewed = () => {
    if (!gap.patient_hcc_id || missing.length === 0) return;
    setDialogMode("review");
  };

  const addNotes = () => {
    if (!gap.patient_hcc_id) return;
    setDialogMode("notes");
  };

  return (
    <div
      className={cn(
        "relative flex items-center gap-3 py-3 pr-3 pl-0 transition-colors",
        isOdd ? "bg-muted/20 dark:bg-muted/10" : "bg-card"
      )}
    >
      {/* 4px severity rail */}
      <div className={cn("absolute left-0 top-0 bottom-0 w-1 rounded-sm flex-shrink-0", railColor)} aria-hidden />

      {/* MEAT dots — smaller */}
      <div className="ml-3 flex-shrink-0">
        <LetterDots gaps={gap.gaps} size="sm" />
      </div>

      {/* Identity + status */}
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline gap-1.5 flex-wrap">
          <Tooltip text={`HCC ${gap.hcc} — ${gap.label}`}>
            <span className="text-xs font-bold cursor-default">HCC {gap.hcc}</span>
          </Tooltip>
          <span className="text-[11px] text-muted-foreground truncate max-w-[20ch]">{gap.label}</span>
        </div>
        <div className="flex items-center gap-2 mt-0.5">
          <span className={cn("text-[11px] font-semibold", statusClass)}>{statusLabel}</span>
          <Tooltip text="Model coefficient contribution to RAF score">
            <span className="text-[10px] text-muted-foreground/70 tabular-nums cursor-default">
              coef {gap.coefficient.toFixed(3)}
            </span>
          </Tooltip>
        </div>
      </div>

      {/* Right-aligned actions */}
      <div className="flex items-center gap-1.5 flex-shrink-0">
        {!isComplete && gap.patient_hcc_id && (
          <>
            <Button
              size="sm"
              variant="default"
              onClick={markReviewed}
              disabled={busy}
              className="h-7 px-2.5 text-xs"
              aria-label={`Review HCC ${gap.hcc}`}
            >
              {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : "Review"}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={addNotes}
              disabled={busy}
              className="h-7 px-2.5 text-xs"
              aria-label={`Add notes for HCC ${gap.hcc}`}
            >
              Add Notes
            </Button>
            {/* Overflow: Order Lab + Start Treatment */}
            <div className="relative">
              <Button
                size="sm"
                variant="ghost"
                className="h-7 w-7 p-0"
                onClick={() => setOverflowOpen((o) => !o)}
                aria-label="More actions"
                aria-expanded={overflowOpen}
                aria-haspopup="menu"
              >
                <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
              </Button>
              {overflowOpen && (
                <div
                  className="absolute right-0 top-full mt-1 z-20 rounded-md border border-border bg-popover shadow-md py-1 min-w-[140px]"
                  role="menu"
                >
                  {!gap.gaps.monitor && (
                    <div role="menuitem" className="px-1 py-0.5">
                      <OrderLabButton
                        patientId={patientId}
                        hccCode={gap.hcc}
                        icd10={gap.icd10_codes[0] || ""}
                        onOrdered={() => { setOverflowOpen(false); onChange(); }}
                      />
                    </div>
                  )}
                  {!gap.gaps.treat && (
                    <div role="menuitem" className="px-1 py-0.5">
                      <StartTreatmentButton
                        patientId={patientId}
                        hccCode={gap.hcc}
                        icd10={gap.icd10_codes[0] ?? ""}
                        onStarted={() => { setOverflowOpen(false); onChange(); }}
                      />
                    </div>
                  )}
                  {gap.gaps.monitor && gap.gaps.treat && (
                    <div className="px-3 py-2 text-xs text-muted-foreground">No additional actions</div>
                  )}
                </div>
              )}
            </div>
          </>
        )}
        {isComplete && (
          <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-700 dark:text-emerald-400">
            <Check className="h-3 w-3" aria-hidden />
          </span>
        )}
      </div>

      {/* MEAT attestation dialog — replaces window.prompt */}
      <MEATAttestationDialog
        open={dialogMode !== null}
        hcc={gap.hcc}
        label={gap.label}
        missingLabel={dialogMode === "review" ? missingLabel : ""}
        onCancel={() => setDialogMode(null)}
        onSubmit={submitMeat}
      />
    </div>
  );
}
