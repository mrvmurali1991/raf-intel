/**
 * Route loading boundary for /patients.
 * Rendered by Next.js while the page's React Server Component is streaming.
 * Skeleton structure mirrors the real page (KPI cards row, filter bar,
 * patient table) so the visual hand-off feels seamless.
 */
export default function Loading() {
  return (
    <div
      aria-busy="true"
      aria-live="polite"
      aria-label="Loading patient list"
      className="p-6 space-y-6"
    >
      {/* Page title row */}
      <div className="space-y-2">
        <div className="skeleton h-8 w-64 rounded-md" />
        <div className="skeleton h-4 w-96 rounded-md" />
      </div>

      {/* KPI cards row — 4 cards, ~140px tall */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div
            key={`kpi-${i}`}
            className="skeleton h-[140px] w-full rounded-xl"
          />
        ))}
      </div>

      {/* Filter bar — full width, 48px tall */}
      <div className="skeleton h-12 w-full rounded-lg" />

      {/* Table rows — mirror real column shape: avatar + name + 2 numeric + risk-factors + action */}
      <div className="rounded-xl border border-border overflow-hidden">
        {/* Header row */}
        <div className="hidden md:flex items-center gap-4 px-4 py-3 border-b border-border bg-muted/30">
          <div className="skeleton h-3 w-20 rounded" />
          <div className="skeleton h-3 w-16 rounded ml-auto" />
          <div className="skeleton h-3 w-16 rounded" />
          <div className="skeleton h-3 w-24 rounded" />
          <div className="skeleton h-3 w-20 rounded" />
        </div>
        {Array.from({ length: 8 }).map((_, i) => (
          <div
            key={`row-${i}`}
            className="flex items-center gap-4 px-4 py-3 border-b border-border last:border-b-0"
          >
            {/* Avatar circle */}
            <div className="skeleton h-8 w-8 rounded-full shrink-0" />
            {/* Name column (long) */}
            <div className="flex-1 min-w-0 space-y-1.5">
              <div className="skeleton h-4 w-40 rounded" />
              <div className="skeleton h-3 w-24 rounded" />
            </div>
            {/* Numeric col 1 (short) */}
            <div className="skeleton h-4 w-12 rounded hidden sm:block" />
            {/* Numeric col 2 (short) */}
            <div className="skeleton h-4 w-12 rounded hidden sm:block" />
            {/* Risk factors (medium) */}
            <div className="skeleton h-4 w-28 rounded hidden md:block" />
            {/* Action button (right-aligned) */}
            <div className="skeleton h-8 w-20 rounded-md shrink-0 ml-auto" />
          </div>
        ))}
      </div>

      <span className="sr-only">Loading patients…</span>
    </div>
  );
}
