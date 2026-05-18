/**
 * Next.js route-level loading UI for /suspects.
 * Rendered instantly during navigation — gives perceived <100 ms transition.
 * Layout: page header → 4-up KPI strip → toolbar → table (header + 8 rows) → pagination.
 */
export default function Loading() {
  return (
    <div
      role="status"
      aria-label="Loading suspects"
      aria-busy="true"
      aria-live="polite"
      className="rci-page-pad-desktop bg-background text-foreground min-h-screen animate-pulse"
    >
      {/* Page header */}
      <div className="mb-6">
        <div className="h-8 w-56 rounded-lg bg-muted mb-2" />
        <div className="h-4 w-80 rounded bg-muted/70" />
      </div>

      {/* 4-up KPI strip */}
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

      {/* Toolbar */}
      <div className="flex gap-3 mb-4">
        <div className="h-9 flex-1 max-w-xs rounded-lg bg-muted/70" />
        <div className="h-9 w-28 rounded-lg bg-muted/60" />
        <div className="h-9 w-28 rounded-lg bg-muted/60" />
        <div className="ml-auto h-9 w-24 rounded-lg bg-muted/50" />
      </div>

      {/* Table */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="flex gap-3 px-5 py-3 border-b border-border bg-muted/30">
          {[1.6, 2.4, 1, 1, 0.8, 0.8, 0.9, 0.8].map((fr, i) => (
            <div key={i} className="h-4 rounded bg-muted/70" style={{ flex: fr }} />
          ))}
        </div>
        {Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            className="flex gap-3 px-5 py-4 border-b border-border last:border-0"
          >
            <div className="flex gap-2 items-center" style={{ flex: 1.6 }}>
              <div className="h-9 w-9 rounded-full bg-muted/70 shrink-0" />
              <div className="space-y-1.5 flex-1">
                <div className="h-3.5 w-32 rounded bg-muted" />
                <div className="h-3 w-20 rounded bg-muted/60" />
              </div>
            </div>
            <div className="space-y-1.5" style={{ flex: 2.4 }}>
              <div className="h-3.5 w-40 rounded bg-muted" />
              <div className="h-3 w-56 rounded bg-muted/60" />
            </div>
            <div className="h-6 w-20 rounded-full bg-muted/60" style={{ flex: 1, alignSelf: "center" }} />
            <div className="h-6 w-16 rounded-full bg-muted/60" style={{ flex: 1, alignSelf: "center" }} />
            <div className="h-4 w-10 rounded bg-muted/70" style={{ flex: 0.8, alignSelf: "center" }} />
            <div className="h-4 w-14 rounded bg-muted/70" style={{ flex: 0.8, alignSelf: "center" }} />
            <div className="h-6 w-16 rounded-full bg-muted/50" style={{ flex: 0.9, alignSelf: "center" }} />
            <div className="flex gap-1" style={{ flex: 0.8, alignSelf: "center" }}>
              <div className="h-7 w-7 rounded bg-muted/60" />
              <div className="h-7 w-7 rounded bg-muted/60" />
            </div>
          </div>
        ))}
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between mt-4">
        <div className="h-4 w-40 rounded bg-muted/60" />
        <div className="flex gap-2">
          <div className="h-8 w-8 rounded bg-muted/60" />
          <div className="h-8 w-8 rounded bg-muted/60" />
        </div>
      </div>

      <span className="sr-only">Loading suspects, please wait...</span>
    </div>
  );
}
