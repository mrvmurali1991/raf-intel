/**
 * Route loading boundary for /analysis.
 * Mirrors the real form + results split layout.
 */
export default function Loading() {
  return (
    <div
      aria-busy="true"
      aria-live="polite"
      aria-label="Loading analysis"
      className="p-6 space-y-4"
    >
      <div className="space-y-2">
        <div className="skeleton h-8 w-56 rounded-md" />
        <div className="skeleton h-4 w-80 rounded-md" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mt-6">
        {/* Form column (left, takes 1/3) */}
        <div className="space-y-3 lg:col-span-1">
          <div className="skeleton h-10 w-full rounded-lg" />
          <div className="skeleton h-10 w-full rounded-lg" />
          <div className="skeleton h-32 w-full rounded-lg" />
          <div className="skeleton h-10 w-32 rounded-lg" />
        </div>
        {/* Results column (right, takes 2/3) */}
        <div className="space-y-3 lg:col-span-2">
          <div className="skeleton h-64 w-full rounded-xl" />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="skeleton h-32 w-full rounded-xl" />
            ))}
          </div>
        </div>
      </div>

      <span className="sr-only">Loading analysis…</span>
    </div>
  );
}
