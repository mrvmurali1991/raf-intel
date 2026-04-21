/**
 * usePatientProfile
 * -----------------
 * Fetches the comprehensive patient profile (billing, vitals, enrollment, etc.)
 *
 *   GET /api/patients/{pid}/comprehensive-profile
 *
 * Usage:
 *   const { data, isLoading, isError } = usePatientProfile(pid);
 */

import { useQuery } from "@tanstack/react-query";
import { getPatientProfile } from "@/lib/api";
import type { PatientProfile } from "@/lib/api";

export const PATIENT_PROFILE_QUERY_KEY = (pid: string | number) =>
  ["patient-profile", String(pid)] as const;

export function usePatientProfile(pid: string | number) {
  return useQuery<PatientProfile>({
    queryKey: PATIENT_PROFILE_QUERY_KEY(pid),
    queryFn: () => getPatientProfile(pid),
    enabled: Boolean(pid),
  });
}
