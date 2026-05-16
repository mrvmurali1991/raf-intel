"use client";

/**
 * Route error boundary for /analysis.
 * SECURITY: do NOT render error.message — it may include PHI.
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
    if (typeof window !== "undefined") {
      // eslint-disable-next-line no-console
      console.error("[analysis route]", error.digest ?? "boundary hit");
    }
  }, [error]);

  return (
    <div
      role="alert"
      className="p-6 max-w-md mx-auto mt-12 rounded-lg border border-border bg-card text-card-foreground"
    >
      <h2 className="text-lg font-semibold">Something went wrong</h2>
      <p className="mt-2 text-sm text-muted-foreground">
        We couldn&apos;t load the analysis. Try again in a moment.
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
