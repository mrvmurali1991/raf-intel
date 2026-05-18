/**
 * Next.js route-level loading UI for /population (redirects to /population/heatmap).
 * Shown during the redirect + child-page load cycle.
 * Mirrors the heatmap shell so there's no layout flash.
 */
export default function Loading() {
  return (
    <div
      role="status"
      aria-label="Loading population"
      aria-busy="true"
      aria-live="polite"
      className="rci-page-pad-desktop bg-background text-foreground min-h-screen animate-pulse"
    >
      <div className="mb-6">
        <div className="h-8 w-64 rounded-lg bg-muted mb-2" />
        <div className="h-4 w-80 rounded bg-muted/70" />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-24 rounded-xl border border-border bg-card p-4 flex flex-col justify-between"
          >
            <div className="h-3 w-24 rounded bg-muted/70" />
            <div className="h-7 w-16 rounded bg-muted" />
            <div className="h-3 w-20 rounded bg-muted/60" />
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-border bg-card p-6">
        {Array.from({ length: 10 }).map((_, i) => (
          <div key={i} className="flex items-center gap-3 mb-3">
            <div className="w-16 h-4 rounded bg-muted/70" />
            <div className="flex-1 h-7 rounded bg-muted/50" />
            <div className="w-14 h-4 rounded bg-muted/70" />
          </div>
        ))}
      </div>

      <span className="sr-only">Loading population data, please wait…</span>
    </div>
  );
}
