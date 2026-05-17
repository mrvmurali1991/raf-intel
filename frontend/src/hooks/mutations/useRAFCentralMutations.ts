/**
 * useRAFCentralMutations
 * ----------------------
 * React Query mutation wrappers for all RAF Central Panel actions.
 *
 * Mutations:
 *   - useRecalculateRAF    → POST /api/raf-central/{pid}/actions/recalculate
 *   - useAcceptSuspectCentral → POST /api/raf-central/{pid}/actions/accept-suspect
 *   - useDismissSuspectCentral → POST /api/raf-central/{pid}/actions/dismiss-suspect
 *   - useRestoreSuspectCentral → POST /api/raf-central/{pid}/actions/restore-suspect
 *   - useMEATAttest        → POST /api/raf-central/{pid}/actions/mark-meat-reviewed
 *
 * Each mutation invalidates RAF_CENTRAL_QUERY_KEY on success.
 *
 * Usage:
 *   const recalcMut = useRecalculateRAF(patientId, year);
 *   recalcMut.mutate();
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { RAF_CENTRAL_QUERY_KEY } from "@/hooks/queries/useRAFCentralPanel";

// ---------------------------------------------------------------------------
// Recalculate RAF
// ---------------------------------------------------------------------------

export function useRecalculateRAF(pid: number, year?: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api
        .post(
          `/api/raf-central/${pid}/actions/recalculate${year ? `?year=${year}` : ""}`
        )
        .then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: RAF_CENTRAL_QUERY_KEY(pid, year),
      });
    },
  });
}

// ---------------------------------------------------------------------------
// Accept suspect (RAF Central path)
// ---------------------------------------------------------------------------

interface AcceptSuspectArgs {
  suspect_id: number;
  push_to_emr?: boolean;
}

export function useAcceptSuspectCentral(pid: number, year?: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (args: AcceptSuspectArgs) =>
      api
        .post(`/api/raf-central/${pid}/actions/accept-suspect`, {
          suspect_id: args.suspect_id,
          push_to_emr: args.push_to_emr ?? true,
        })
        .then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: RAF_CENTRAL_QUERY_KEY(pid, year),
      });
    },
  });
}

// ---------------------------------------------------------------------------
// Dismiss suspect (RAF Central path)
// ---------------------------------------------------------------------------

interface DismissSuspectArgs {
  suspect_id: number;
  reason: string;
}

export function useDismissSuspectCentral(pid: number, year?: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (args: DismissSuspectArgs) =>
      api
        .post(`/api/raf-central/${pid}/actions/dismiss-suspect`, {
          suspect_id: args.suspect_id,
          reason: args.reason,
        })
        .then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: RAF_CENTRAL_QUERY_KEY(pid, year),
      });
    },
  });
}

// ---------------------------------------------------------------------------
// Restore suspect (RAF Central path) — undo a dismiss
// ---------------------------------------------------------------------------

interface RestoreSuspectArgs {
  suspect_id: number;
  reason?: string | null;
}

export function useRestoreSuspectCentral(pid: number, year?: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (args: RestoreSuspectArgs) =>
      api
        .post(`/api/raf-central/${pid}/actions/restore-suspect`, {
          suspect_id: args.suspect_id,
          reason: args.reason ?? null,
        })
        .then((r) => r.data),
    onSuccess: () => {
      // Same invalidation set as accept / dismiss — the suspects panel,
      // RAF gauge, and HCC count can all shift when a row flips back to open.
      queryClient.invalidateQueries({
        queryKey: RAF_CENTRAL_QUERY_KEY(pid, year),
      });
    },
  });
}

// ---------------------------------------------------------------------------
// MEAT attestation
// ---------------------------------------------------------------------------

interface MEATAttestArgs {
  patient_hcc_id: number;
  monitor_note: string | null;
  evaluate_note: string | null;
  assess_note: string | null;
  treat_note: string | null;
}

export function useMEATAttest(pid: number, year?: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (args: MEATAttestArgs) =>
      api
        .post(
          `/api/raf-central/${pid}/actions/mark-meat-reviewed`,
          args
        )
        .then((r) => r.data),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: RAF_CENTRAL_QUERY_KEY(pid, year),
      });
    },
  });
}
