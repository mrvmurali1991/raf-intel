/**
 * useRAFCentralPanel
 * ------------------
 * Fetches the unified RAF intelligence panel payload for a patient.
 *
 *   GET /api/raf-central/{pid}?year={year}
 *
 * Usage:
 *   const { data, isLoading, isError, error, refetch } = useRAFCentralPanel(patientId, year);
 */

import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import type { RAFCentralPayload } from "@/components/RAFCentralPanel";

export const RAF_CENTRAL_QUERY_KEY = (pid: number, year?: number) =>
  ["raf-central", pid, year ?? null] as const;

export function useRAFCentralPanel(pid: number, year?: number) {
  return useQuery<RAFCentralPayload>({
    queryKey: RAF_CENTRAL_QUERY_KEY(pid, year),
    queryFn: async () => {
      const url = `/api/raf-central/${pid}${year ? `?year=${year}` : ""}`;
      const { data } = await api.get<RAFCentralPayload>(url);
      return data;
    },
    enabled: pid > 0,
  });
}
