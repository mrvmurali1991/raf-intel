/**
 * Route loading boundary for /review-queue.
 */
export default function Loading() {
  return (
    <div
      aria-busy="true"
      aria-live="polite"
      className="p-6 space-y-4"
    >
      <div className="h-8 w-72 rounded-md bg-muted animate-pulse" />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-6">
        {Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            className="h-24 w-full rounded-md bg-muted animate-pulse"
          />
        ))}
      </div>
      <span className="sr-only">Loading review queue…</span>
    </div>
  );
}
