"use client";

/**
 * Route error boundary for /patients.
 *
 * SECURITY: We deliberately do NOT render `error.message` — backend
 * exceptions can contain patient identifiers or other PHI. Keep the
 * message generic; full details go to the server logs / Sentry.
 */
import { useEffect } from "react";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Forward to the global error tracker — that path scrubs before sending.
    if (typeof window !== "undefined") {
      // eslint-disable-next-line no-console
      console.error("[patients route]", error.digest ?? "boundary hit");
    }
  }, [error]);

  return (
    <div
      role="alert"
      className="p-6 max-w-md mx-auto mt-12 rounded-lg border border-border bg-card text-card-foreground"
    >
      <h2 className="text-lg font-semibold">Something went wrong</h2>
      <p className="mt-2 text-sm text-muted-foreground">
        We couldn&apos;t load the patient list. Try again in a moment.
      </p>
      <button
        type="button"
        onClick={() => reset()}
        className="mt-4 inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90"
      >
        Retry
      </button>
    </div>
  );
}
