"use client";

import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Loader2, Check, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import { OrderLabButton } from "@/components/OrderLabButton";
import StartTreatmentButton from "@/components/StartTreatmentButton";
import { useMEATAttest } from "@/hooks/mutations/useRAFCentralMutations";
import type { MEATGap } from "../_shared";
import { Tooltip } from "../common/Tooltip";
import { LetterDots } from "./LetterDots";
import { MEATProgressBar } from "./MEATProgressBar";
import { MEATAttestationDialog } from "./MEATAttestationDialog";

/**
 * MEATCard — full card view used in the panel (accordion) layout.
 * Uses useMEATAttest React Query mutation for attestation.
 */
export function MEATCard({
  gap,
  patientId,
  year,
  onChange,
}: {
  gap: MEATGap;
  patientId: number;
  year?: number;
  onChange: () => void;
}) {
  const [dialogOpen, setDialogOpen] = useState(false);

  // Mutation — invalidates raf-central query on success
  const meatMut = useMEATAttest(patientId, year);
  const busy = meatMut.isPending;

  const missing = (Object.entries(gap.gaps) as [keyof MEATGap["gaps"], boolean][])
    .filter(([, on]) => !on)
    .map(([k]) => k);
  const missingLabel = missing.map((k) => k[0].toUpperCase() + k.slice(1)).join(", ");

  const submitMeat = async (note: string) => {
    if (!gap.patient_hcc_id) return;
    setDialogOpen(false);
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
    setDialogOpen(true);
  };

  const isComplete = gap.status === "COMPLETE";

  return (
    <Card className="p-3 hover:bg-muted/50 transition-colors dark:hover:bg-muted/20">
      {/* Row 1: HCC code + ICD + label + status pill */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <Tooltip text={`HCC ${gap.hcc} — ${gap.label}`}>
              <span className="text-sm font-bold cursor-default">HCC {gap.hcc}</span>
            </Tooltip>
            <span className="text-muted-foreground select-none">·</span>
            <span className="text-xs text-muted-foreground font-normal">
              {gap.icd10_codes.slice(0, 3).join(", ")}
            </span>
          </div>
          <div className="mt-0.5 text-xs font-medium leading-relaxed text-foreground/80 truncate">
            {gap.label}
          </div>
        </div>

        {/* Status pill */}
        {isComplete ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300 flex-shrink-0">
            <Check className="h-3 w-3" aria-hidden /> Complete
          </span>
        ) : (
          <Badge
            className={cn(
              "text-[10px] font-semibold border-0 flex-shrink-0",
              gap.status === "PARTIAL"
                ? "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300"
                : "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300"
            )}
          >
            {gap.status}
          </Badge>
        )}
      </div>

      {/* Row 2: MEAT dots + coef */}
      <div className="mt-2 flex items-center gap-3">
        <LetterDots gaps={gap.gaps} />
        <Tooltip text="Model coefficient contribution to RAF score">
          <span className="inline-flex items-center gap-0.5 text-xs text-muted-foreground tabular-nums cursor-default">
            <Info className="h-3 w-3 text-muted-foreground/60" aria-hidden />
            coef {gap.coefficient.toFixed(3)}
          </span>
        </Tooltip>
      </div>

      {/* MEAT completion progress bar */}
      <MEATProgressBar gaps={gap.gaps} />

      {/* Actions */}
      {!isComplete && gap.patient_hcc_id ? (
        <div className="mt-2.5 flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={markReviewed} disabled={busy}>
            {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : "Mark reviewed"}
          </Button>
          {!gap.gaps.monitor ? (
            <OrderLabButton
              patientId={patientId}
              hccCode={gap.hcc}
              icd10={gap.icd10_codes[0] || ""}
              onOrdered={onChange}
            />
          ) : null}
          {!gap.gaps.treat ? (
            <StartTreatmentButton
              patientId={patientId}
              hccCode={gap.hcc}
              icd10={gap.icd10_codes[0] ?? ""}
              onStarted={onChange}
            />
          ) : null}
        </div>
      ) : null}

      {/* MEAT attestation dialog */}
      <MEATAttestationDialog
        open={dialogOpen}
        hcc={gap.hcc}
        label={gap.label}
        missingLabel={missingLabel}
        onCancel={() => setDialogOpen(false)}
        onSubmit={submitMeat}
      />
    </Card>
  );
}
