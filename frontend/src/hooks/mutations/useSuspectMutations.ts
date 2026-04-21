/**
 * useSuspectMutations
 * -------------------
 * React Query mutation wrappers for the global /api/suspects endpoints.
 * These are distinct from RAF Central panel actions (which use /api/raf-central/…/actions/…).
 *
 * Mutations:
 *   - useAcceptSuspect  → PUT /api/suspects/{id}/accept
 *   - useDismissSuspect → PUT /api/suspects/{id}/dismiss
 *   - useBulkSuspects   → POST /api/suspects/bulk-update
 *
 * Invalidates ["suspects-list"] on success. Callers can pass additional
 * queryKeys to invalidate (e.g. per-patient suspect queries).
 *
 * Usage:
 *   const acceptMut = useAcceptSuspect(["patient-suspects", pid, "open", year]);
 *   acceptMut.mutate(suspectId);
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { acceptSuspect, dismissSuspect, bulkUpdateSuspects } from "@/lib/api";
import { SUSPECTS_LIST_QUERY_KEY } from "@/hooks/queries/useSuspectsList";

type QueryKey = readonly unknown[];

export function useAcceptSuspect(extraInvalidate?: QueryKey[]) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (suspectId: number) => acceptSuspect(suspectId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: SUSPECTS_LIST_QUERY_KEY({}),
      });
      extraInvalidate?.forEach((key) =>
        queryClient.invalidateQueries({ queryKey: key })
      );
    },
  });
}

export function useDismissSuspect(extraInvalidate?: QueryKey[]) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      suspectId,
      reason,
    }: {
      suspectId: number;
      reason?: string;
    }) => dismissSuspect(suspectId, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: SUSPECTS_LIST_QUERY_KEY({}),
      });
      extraInvalidate?.forEach((key) =>
        queryClient.invalidateQueries({ queryKey: key })
      );
    },
  });
}

export function useBulkSuspects(extraInvalidate?: QueryKey[]) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      ids,
      action,
      reason,
    }: {
      ids: number[];
      action: "accept" | "dismiss";
      reason?: string;
    }) => bulkUpdateSuspects(ids, action, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: SUSPECTS_LIST_QUERY_KEY({}),
      });
      extraInvalidate?.forEach((key) =>
        queryClient.invalidateQueries({ queryKey: key })
      );
    },
  });
}
