"use client";

/**
 * useAIHealth — poll the backend Gemini AI health probe.
 *
 * Backed by `GET /api/health/ai` which performs a tiny live call against
 * Gemini (cached server-side for 60s).  We refetch every 5 minutes so the
 * banner surfaces outages without hammering the API.
 *
 * Response shape:
 *   { ok: true,  model: string }
 *   { ok: false, reason: string, model?: string }
 */

import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";

export interface AIHealth {
  ok: boolean;
  reason?: string;
  model?: string;
}

export function useAIHealth() {
  return useQuery<AIHealth>({
    queryKey: ["ai-health"],
    queryFn: async () => {
      const res = await api.get<AIHealth>("/api/health/ai");
      return res.data;
    },
    // Poll every 5 minutes; cache server-side still caps actual Gemini calls.
    refetchInterval: 5 * 60 * 1000,
    staleTime: 60 * 1000,
    retry: 1,
  });
}

export default useAIHealth;
