"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { getEmrStatus } from "@/lib/api";

/**
 * EmrDeactivatedBanner
 * --------------------
 * A sticky banner surfaced at the top of the app shell whenever the tenant's
 * EMR connection is deactivated. The backend's `emr_gate` middleware returns
 * HTTP 423 (code=EMR_DEACTIVATED) for every clinical-data endpoint when there
 * are zero active EMR connections; the axios response interceptor in
 * `lib/api.ts` translates that into a global `emr-deactivated` DOM event,
 * which we listen for here to immediately invalidate the cached EMR status.
 *
 * We reuse the same React Query key (`["emr-status"]`) that the Sidebar uses
 * so the two stay in sync and we never hit the backend twice.
 */
export function EmrDeactivatedBanner() {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();

  const { data: emrStatus } = useQuery({
    queryKey: ["emr-status"],
    queryFn: () => getEmrStatus(),
    refetchInterval: 60_000,
    retry: 1,
  });

  // Track the most recent gate code so we can differentiate
  // EMR_DEACTIVATED (user has uploaded data or just toggled off EMR)
  // from NO_DATA_SOURCE (nothing at all).
  const [gateCode, setGateCode] = useState<string | null>(null);

  // When any API call is blocked by the EMR gate, force-refresh the status
  // query so the banner reflects reality immediately instead of waiting for
  // the next 60s poll tick.
  useEffect(() => {
    const handler = (e: Event) => {
      const code = (e as CustomEvent).detail?.code as string | undefined;
      if (code) setGateCode(code);
      queryClient.invalidateQueries({ queryKey: ["emr-status"] });
    };
    window.addEventListener("emr-deactivated", handler as EventListener);
    return () => window.removeEventListener("emr-deactivated", handler as EventListener);
  }, [queryClient]);

  // Hide on routes where the banner would be noise or create a redirect loop.
  const hiddenRoutes =
    pathname === "/emr-config" ||
    pathname === "/login" ||
    pathname.startsWith("/admin");
  if (hiddenRoutes) return null;

  // `connected` is the canonical field from /api/emr/status. Only render once
  // the query has resolved AND the tenant is disconnected.
  if (!emrStatus || emrStatus.connected) return null;

  const noDataAtAll = gateCode === "NO_DATA_SOURCE";

  return (
    <div
      role="alert"
      className="sticky top-0 z-40 w-full border-b border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/60 dark:text-amber-200"
    >
      <div className="flex items-center justify-between gap-4 px-4 py-2.5 text-sm">
        <div className="flex items-center gap-2 min-w-0">
          <AlertTriangle
            className="h-4 w-4 flex-shrink-0"
            aria-hidden="true"
          />
          <span className="truncate">
            {noDataAtAll ? (
              <>
                <strong>No data source connected</strong> — Activate an EMR or
                upload a patient file to get started.
              </>
            ) : (
              <>
                <strong>EMR Disconnected</strong> — Activate a connection to
                view patient data.
              </>
            )}
          </span>
        </div>
        <div className="flex-shrink-0 flex items-center gap-2">
          {noDataAtAll && (
            <button
              type="button"
              onClick={() => router.push("/uploads")}
              className="rounded-md border border-amber-400 bg-white px-3 py-1 text-xs font-medium text-amber-900 shadow-sm transition hover:bg-amber-100 dark:border-amber-700 dark:bg-amber-900/40 dark:text-amber-100 dark:hover:bg-amber-900/70"
            >
              Upload a patient file
            </button>
          )}
          <button
            type="button"
            onClick={() => router.push("/emr-config")}
            className="rounded-md border border-amber-400 bg-white px-3 py-1 text-xs font-medium text-amber-900 shadow-sm transition hover:bg-amber-100 dark:border-amber-700 dark:bg-amber-900/40 dark:text-amber-100 dark:hover:bg-amber-900/70"
          >
            Go to EMR Configuration
          </button>
        </div>
      </div>
    </div>
  );
}

export default EmrDeactivatedBanner;
