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
 * All single-item mutations apply an optimistic update that removes the
 * suspect from the cached list immediately, then rolls back on error and
 * refetches on settle. Callers can pass additional queryKeys to invalidate
 * (e.g. per-patient suspect queries).
 *
 * Usage:
 *   const acceptMut = useAcceptSuspect(["patient-suspects", pid, "open", year]);
 *   acceptMut.mutate(suspectId);
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { acceptSuspect, dismissSuspect, bulkUpdateSuspects } from "@/lib/api";
import { SUSPECTS_LIST_QUERY_KEY } from "@/hooks/queries/useSuspectsList";
import type { SuspectsResponse } from "@/lib/api";

type QueryKey = readonly unknown[];

/** Remove a suspect by id from any cached SuspectsResponse shape. */
function removeSuspectFromCache(
  queryClient: ReturnType<typeof useQueryClient>,
  suspectId: number
) {
  // Target the generic suspects-list key prefix so all status variants are covered.
  const previousEntries: Array<{ key: QueryKey; data: unknown }> = [];

  queryClient.getQueryCache().findAll({ queryKey: ["suspects-list"] }).forEach((query) => {
    previousEntries.push({ key: query.queryKey, data: query.state.data });
    queryClient.setQueryData<SuspectsResponse>(query.queryKey, (old) => {
      if (!old) return old;
      return {
        ...old,
        suspects: old.suspects.filter((s) => s.id !== suspectId),
        count: Math.max(0, old.count - 1),
      };
    });
  });

  return previousEntries;
}

export function useAcceptSuspect(extraInvalidate?: QueryKey[]) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (suspectId: number) => acceptSuspect(suspectId),
    onMutate: async (suspectId) => {
      await queryClient.cancelQueries({ queryKey: ["suspects-list"] });
      const previousEntries = removeSuspectFromCache(queryClient, suspectId);
      return { previousEntries };
    },
    onError: (_err, _id, context) => {
      context?.previousEntries.forEach(({ key, data }) => {
        queryClient.setQueryData(key, data);
      });
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: SUSPECTS_LIST_QUERY_KEY({}) });
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
    onMutate: async ({ suspectId }) => {
      await queryClient.cancelQueries({ queryKey: ["suspects-list"] });
      const previousEntries = removeSuspectFromCache(queryClient, suspectId);
      return { previousEntries };
    },
    onError: (_err, _vars, context) => {
      context?.previousEntries.forEach(({ key, data }) => {
        queryClient.setQueryData(key, data);
      });
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: SUSPECTS_LIST_QUERY_KEY({}) });
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
    onError: () => {
      // Bulk: full refetch is simpler than rolling back N items
      queryClient.invalidateQueries({ queryKey: SUSPECTS_LIST_QUERY_KEY({}) });
    },
  });
}
