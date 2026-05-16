/**
 * Route loading boundary for /patients.
 * Rendered by Next.js while the page's React Server Component is streaming.
 * Keep this trivial — no client-side state, no data fetch.
 */
export default function Loading() {
  return (
    <div
      aria-busy="true"
      aria-live="polite"
      className="p-6 space-y-4"
    >
      <div className="h-8 w-64 rounded-md bg-muted animate-pulse" />
      <div className="h-4 w-96 rounded-md bg-muted animate-pulse" />
      <div className="space-y-2 mt-6">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="h-12 w-full rounded-md bg-muted animate-pulse"
          />
        ))}
      </div>
      <span className="sr-only">Loading patients…</span>
    </div>
  );
}
