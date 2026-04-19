"use client";

/**
 * StartTreatmentButton
 * --------------------
 * Inline "Start Treatment" action used inside the MEAT Gaps section of
 * RAFCentralPanel. Satisfies a missing MEAT-T (treatment) letter by
 * writing a new prescription into OpenEMR.
 *
 * Clinical-safety note: prescribing is higher-stakes than an order-lab
 * action, so the button REQUIRES a two-step confirmation via a dialog
 * before firing the POST. The confirm gate lives entirely client-side;
 * the backend audits every call via the ordered-by tag on the
 * prescription note field.
 *
 * Backend: POST /api/raf-central/{pid}/actions/start-treatment
 *   body: { hcc_code, icd10, suggested_drug?, suggested_rxnorm?, dosage? }
 *   resp: { status: "ok", prescription_id: number, drug: string }
 */

import { useState } from "react";
import { Loader2, Pill } from "lucide-react";
import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogClose,
} from "@/components/ui/dialog";
import { useToast } from "@/components/Toast";

export interface StartTreatmentButtonProps {
  patientId: number;
  hccCode: string;
  icd10: string;
  /** Optional suggested drug name. When absent, backend falls back to a
   *  small HCC → default-drug map (diabetes/CHF/CKD). */
  suggestedDrug?: string;
  suggestedRxnorm?: string;
  dosage?: string;
  /** Called after a successful prescription write so the parent panel
   *  can re-fetch the MEAT-gap state. */
  onStarted?: () => void;
}

/** Defaults mirrored from backend `_DEFAULT_TREATMENT_BY_HCC` so the
 *  confirm dialog can show the drug name without a pre-flight request. */
const FALLBACK_DRUG_BY_HCC: Record<string, string> = {
  "37": "Metformin 500mg",
  "38": "Metformin 500mg",
  "85": "Lisinopril 10mg",
  "136": "Losartan 50mg",
  "137": "Losartan 50mg",
};

function resolveDisplayDrug(
  hccCode: string,
  suggested?: string,
): string {
  if (suggested) return suggested;
  const key = hccCode.replace(/^HCC/, "").trim();
  return FALLBACK_DRUG_BY_HCC[key] ?? "the recommended treatment";
}

export default function StartTreatmentButton({
  patientId,
  hccCode,
  icd10,
  suggestedDrug,
  suggestedRxnorm,
  dosage,
  onStarted,
}: StartTreatmentButtonProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  const displayDrug = resolveDisplayDrug(hccCode, suggestedDrug);

  const fireStartTreatment = async () => {
    setBusy(true);
    try {
      const resp = await api.post(
        `/api/raf-central/${patientId}/actions/start-treatment`,
        {
          hcc_code: hccCode,
          icd10,
          suggested_drug: suggestedDrug ?? null,
          suggested_rxnorm: suggestedRxnorm ?? null,
          dosage: dosage ?? null,
        },
      );
      const drug = resp.data?.drug ?? displayDrug;
      toast.success(
        "Treatment started",
        `${drug} prescribed and written to OpenEMR.`,
      );
      setOpen(false);
      onStarted?.();
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data
          ?.detail ?? "Failed to write prescription.";
      toast.error("Prescription failed", msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button size="sm" variant="default" className="gap-1">
            <Pill className="h-3 w-3" />
            Start treatment
          </Button>
        }
      />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Start treatment?</DialogTitle>
          <DialogDescription>
            Prescribe <span className="font-medium">{displayDrug}</span> to this
            patient? This will write a new active prescription into OpenEMR for
            HCC {hccCode.replace(/^HCC/, "")} / ICD-10 {icd10}.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <DialogClose
            render={
              <Button variant="outline" disabled={busy}>
                Cancel
              </Button>
            }
          />
          <Button onClick={fireStartTreatment} disabled={busy}>
            {busy ? (
              <>
                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                Prescribing…
              </>
            ) : (
              "Confirm & prescribe"
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
