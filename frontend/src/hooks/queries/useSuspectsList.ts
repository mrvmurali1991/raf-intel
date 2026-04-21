/**
 * useSuspectsList
 * ---------------
 * Fetches the global suspect conditions list with status/limit filters.
 *
 *   GET /api/suspects?status={status}&limit={limit}
 *
 * Also exports a per-patient variant:
 *   GET /api/suspects/{pid}?status={status}&year={year}
 *
 * Usage:
 *   const { data, isLoading, isError } = useSuspectsList({ status: "open", limit: 200 });
 *   const { data, isLoading } = usePatientSuspectsList(pid, "open", year);
 */

import { useQuery } from "@tanstack/react-query";
import { getSuspects, getPatientSuspects } from "@/lib/api";
import type { SuspectsResponse, PatientSuspectsResponse } from "@/lib/api";

export interface SuspectsFilters {
  status?: string;
  limit?: number;
}

export const SUSPECTS_LIST_QUERY_KEY = (filters: SuspectsFilters) =>
  ["suspects-list", filters.status ?? "open", filters.limit ?? 200] as const;

export function useSuspectsList(filters: SuspectsFilters = {}) {
  const { status = "open", limit = 200 } = filters;
  return useQuery<SuspectsResponse>({
    queryKey: SUSPECTS_LIST_QUERY_KEY(filters),
    queryFn: () => getSuspects(status, limit),
  });
}

export const PATIENT_SUSPECTS_QUERY_KEY = (
  pid: string | number,
  status: string,
  year?: number
) => ["patient-suspects", String(pid), status, year ?? null] as const;

export function usePatientSuspectsList(
  pid: string | number,
  status: string = "open",
  year?: number
) {
  return useQuery<PatientSuspectsResponse>({
    queryKey: PATIENT_SUSPECTS_QUERY_KEY(pid, status, year),
    queryFn: () => getPatientSuspects(pid, status, year),
    enabled: Boolean(pid),
  });
}
