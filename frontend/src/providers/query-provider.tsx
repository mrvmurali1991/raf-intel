"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { FeatureFlagProvider } from "@/components/FeatureFlagContext";

/**
 * Do not retry requests blocked by the EMR gate (HTTP 423) — the state only
 * changes when the user activates an EMR connection, so retrying just spams
 * the backend and the console.
 */
function shouldRetry(failureCount: number, error: unknown): boolean {
  const status = (error as { response?: { status?: number } } | undefined)
    ?.response?.status;
  if (status === 423 || status === 401 || status === 403) return false;
  return failureCount < 1;
}

export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: shouldRetry,
            refetchOnWindowFocus: false,
          },
          mutations: {
            retry: shouldRetry,
          },
        },
      })
  );
  return (
    <QueryClientProvider client={client}>
      <FeatureFlagProvider>{children}</FeatureFlagProvider>
    </QueryClientProvider>
  );
}
