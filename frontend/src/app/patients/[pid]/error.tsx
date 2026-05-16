"use client";

/**
 * Route error boundary for /patients/[pid].
 *
 * Without this, any thrown exception inside the patient detail tree
 * (e.g. a null-field crash in RAFCentralPanel, MEATRow, FinancialCard)
 * bubbles to the parent /patients boundary and shows the worklist's
 * "Couldn't load the patient list" message — confusing for clinicians
 * who are already deep in a chart. A local boundary contains the blast
 * radius to this patient's view.
 *
 * SECURITY: we never render error.message — backend exceptions can leak
 * patient identifiers or other PHI. Full details go to the server logs
 * via the global error tracker.
 */
import { useEffect } from "react";

export default function PatientDetailError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    if (typeof window !== "undefined") {
      // eslint-disable-next-line no-console
      console.error("[patients/[pid] route]", error.digest ?? "boundary hit");
    }
  }, [error]);

  return (
    <div
      role="alert"
      className="p-6 max-w-md mx-auto mt-12 rounded-lg border border-border bg-card text-card-foreground"
    >
      <h2 className="text-lg font-semibold">Couldn&apos;t render this patient</h2>
      <p className="mt-2 text-sm text-muted-foreground">
        One of the panels on this chart hit an error. The rest of the app
        is still working — go back to the worklist or retry below.
      </p>
      <div className="mt-4 flex gap-2">
        <button
          type="button"
          onClick={() => reset()}
          className="inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          Retry
        </button>
        <a
          href="/patients"
          className="inline-flex items-center rounded-md border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:bg-muted"
        >
          Back to worklist
        </a>
      </div>
    </div>
  );
}
