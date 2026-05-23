"use client";

import { useEffect } from "react";

/**
 * Shared route-level error fallback used by every `error.tsx` under
 * `frontend/src/app/`. Centralised here so wording/styling tweaks ship in
 * one place instead of touching dozens of duplicate files.
 *
 * Next.js App Router contract: each route's `error.tsx` must default-export
 * a Client Component that accepts `{ error, reset }`. Re-export this from
 * each route to satisfy the contract without copy-paste.
 */
export default function PageError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error("Page error:", error);
  }, [error]);

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] px-6 text-center">
      <h1 className="text-2xl font-bold text-slate-900 mb-3">
        Something went wrong
      </h1>
      <p className="text-sm text-slate-600 mb-6 max-w-md">
        We hit an unexpected error rendering this page. Try again, or contact
        support if it keeps happening.
      </p>
      <button
        onClick={() => reset()}
        className="inline-flex items-center justify-center rounded-lg bg-teal-600 hover:bg-teal-700 text-white text-sm font-semibold px-6 py-2.5"
      >
        Try again
      </button>
    </div>
  );
}
