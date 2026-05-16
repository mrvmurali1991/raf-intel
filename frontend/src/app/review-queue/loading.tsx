/**
 * Route loading boundary for /review-queue.
 * Mirrors the real card-list layout (~80px tall cards).
 */
export default function Loading() {
  return (
    <div
      aria-busy="true"
      aria-live="polite"
      aria-label="Loading review queue"
      className="p-6 space-y-4"
    >
      <div className="space-y-2">
        <div className="skeleton h-8 w-72 rounded-md" />
        <div className="skeleton h-4 w-80 rounded-md" />
      </div>

      {/* Filter bar */}
      <div className="skeleton h-12 w-full rounded-lg mt-2" />

      {/* Card list — review-queue is a list of ~80px tall cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-4">
        {Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            className="skeleton h-20 w-full rounded-xl"
          />
        ))}
      </div>
      <span className="sr-only">Loading review queue…</span>
    </div>
  );
}
