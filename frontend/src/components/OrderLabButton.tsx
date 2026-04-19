"use client";

/**
 * OrderLabButton
 * --------------
 * Inline action button rendered inside a MEAT-gap card when the patient's
 * "Monitoring" letter is missing for an HCC.  Clicking it places a lab
 * order in OpenEMR via:
 *
 *   POST /api/raf-central/{patientId}/actions/order-lab
 *
 * The backend resolves the actual lab code from either the suggestion we
 * pass through or a small HCC→lab default map (e.g. diabetes → A1C).
 *
 * Success / error feedback is surfaced through the shared Toast provider
 * (components/Toast.tsx) so this component drops in anywhere inside the
 * authenticated shell without needing its own notification UI.
 */

import { useState } from "react";
import { FlaskConical, Loader2 } from "lucide-react";

import api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";

export interface OrderLabButtonProps {
  patientId: number;
  hccCode: string;
  icd10: string;
  /** Optional explicit lab code override (overrides backend HCC default map). */
  suggestedLabCode?: string | null;
  suggestedLabName?: string | null;
  /** Called after a successful order so parents can re-fetch the panel. */
  onOrdered?: () => void;
  /** Pass-through to the underlying Button so callers can downsize it in tight cards. */
  size?: "default" | "sm" | "lg" | "icon";
}

interface OrderLabResponse {
  status: "ok" | "skipped";
  reason?: string;
  procedure_order_id?: number;
  suggested_lab_code?: string;
}

export function OrderLabButton({
  patientId,
  hccCode,
  icd10,
  suggestedLabCode,
  suggestedLabName,
  onOrdered,
  size = "sm",
}: OrderLabButtonProps) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  const handleClick = async () => {
    setBusy(true);
    try {
      const res = await api.post<OrderLabResponse>(
        `/api/raf-central/${patientId}/actions/order-lab`,
        {
          hcc_code: hccCode,
          icd10,
          suggested_lab_code: suggestedLabCode ?? null,
          suggested_lab_name: suggestedLabName ?? null,
        }
      );

      const body = res.data;
      if (body.status === "skipped") {
        toast.warning(
          "Lab order skipped",
          body.reason || "No EMR connection is configured."
        );
      } else {
        toast.success(
          "Lab ordered",
          `Order #${body.procedure_order_id} (${body.suggested_lab_code}) sent to OpenEMR.`
        );
        onOrdered?.();
      }
    } catch (err) {
      const message =
        err instanceof Error
          ? err.message
          : "Unable to place lab order — check server logs.";
      toast.error("Lab order failed", message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Button
      size={size}
      variant="outline"
      onClick={handleClick}
      disabled={busy}
      title="Place lab order in OpenEMR to close the Monitoring gap"
    >
      {busy ? (
        <Loader2 className="h-3 w-3 animate-spin" />
      ) : (
        <>
          <FlaskConical className="h-3 w-3 mr-1" />
          Order lab
        </>
      )}
    </Button>
  );
}

export default OrderLabButton;
