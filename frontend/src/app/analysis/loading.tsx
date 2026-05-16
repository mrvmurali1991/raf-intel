/**
 * Route loading boundary for /analysis.
 */
export default function Loading() {
  return (
    <div
      aria-busy="true"
      aria-live="polite"
      className="p-6 space-y-4"
    >
      <div className="h-8 w-56 rounded-md bg-muted animate-pulse" />
      <div className="h-64 w-full rounded-md bg-muted animate-pulse mt-6" />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            className="h-32 w-full rounded-md bg-muted animate-pulse"
          />
        ))}
      </div>
      <span className="sr-only">Loading analysis…</span>
    </div>
  );
}
