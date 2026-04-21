/**
 * useExplainSuspect
 * -----------------
 * Fetches the "Why was this flagged?" drill-down for a single suspect condition.
 *
 *   GET /api/raf-central/{pid}/suspect/{suspectId}/explain
 *
 * The query is disabled by default and only fires when `enabled` is true
 * (i.e. when the ExplainPanel drawer is opened).
 *
 * Usage:
 *   const { data, isLoading, isError, error } = useExplainSuspect(pid, suspectId, open);
 */

import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";

export interface ContributingSignal {
  source: "medication" | "lab" | "history" | "nlp" | "note" | "other";
  label: string;
  value?: string | null;
  timestamp?: string | null;
}

export interface ExplainResponse {
  suspect_id: number;
  patient_id: number;
  suspect_icd10: string;
  suspect_hcc: string;
  confidence: number;
  evidence_type: string;
  contributing_signals: ContributingSignal[];
  summary: string;
}

export const EXPLAIN_SUSPECT_QUERY_KEY = (pid: number, suspectId: number) =>
  ["raf-central-explain", pid, suspectId] as const;

export function useExplainSuspect(
  pid: number,
  suspectId: number,
  enabled: boolean
) {
  return useQuery<ExplainResponse>({
    queryKey: EXPLAIN_SUSPECT_QUERY_KEY(pid, suspectId),
    queryFn: async () => {
      const { data } = await api.get<ExplainResponse>(
        `/api/raf-central/${pid}/suspect/${suspectId}/explain`
      );
      return data;
    },
    enabled: enabled && pid > 0 && suspectId > 0,
    // Evidence data is stable for the session; extend stale time to avoid
    // redundant re-fetches every time the drawer is reopened.
    staleTime: 5 * 60_000,
  });
}
