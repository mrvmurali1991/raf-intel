/**
 * usePatientEncounters
 * --------------------
 * Fetches encounter list for a patient, optionally filtered by year.
 *
 *   GET /api/patients/{pid}/encounters?year={year}
 *
 * Usage:
 *   const { data, isLoading, isError } = usePatientEncounters(pid, year);
 */

import { useQuery } from "@tanstack/react-query";
import { getPatientEncounters } from "@/lib/api";
import type { PatientEncountersResponse } from "@/lib/api";

export const PATIENT_ENCOUNTERS_QUERY_KEY = (
  pid: string | number,
  year?: number
) => ["patient-encounters", String(pid), year ?? null] as const;

export function usePatientEncounters(pid: string | number, year?: number) {
  return useQuery<PatientEncountersResponse>({
    queryKey: PATIENT_ENCOUNTERS_QUERY_KEY(pid, year),
    queryFn: () => getPatientEncounters(pid, year),
    enabled: Boolean(pid),
  });
}
