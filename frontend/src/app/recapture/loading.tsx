/**
 * Next.js route-level loading UI for /recapture.
 * Rendered instantly during navigation — gives perceived <100 ms transition.
 * Layout: page header → 4-up KPI strip → toolbar → 2-col (conditions sidebar + gaps table).
 */
export default function Loading() {
  return (
    <div
      role="status"
      aria-label="Loading recapture"
      aria-busy="true"
      aria-live="polite"
      className="rci-page-pad-desktop bg-background text-foreground min-h-screen animate-pulse"
    >
      {/* Page header */}
      <div className="mb-6">
        <div className="h-8 w-64 rounded-lg bg-muted mb-2" />
        <div className="h-4 w-96 rounded bg-muted/70" />
      </div>

      {/* 4-up KPI strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-24 rounded-xl border border-border bg-card p-4 flex flex-col justify-between"
          >
            <div className="h-3 w-28 rounded bg-muted/70" />
            <div className="h-7 w-16 rounded bg-muted" />
            <div className="h-3 w-20 rounded bg-muted/60" />
          </div>
        ))}
      </div>

      {/* Toolbar */}
      <div className="flex gap-3 mb-4">
        <div className="h-9 flex-1 max-w-xs rounded-lg bg-muted/70" />
        <div className="h-9 w-32 rounded-lg bg-muted/60" />
        <div className="ml-auto h-9 w-24 rounded-lg bg-muted/50" />
      </div>

      {/* 2-col body */}
      <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-6">
        {/* Left: top-conditions sidebar */}
        <div className="rounded-xl border border-border bg-card p-4 space-y-3 h-fit">
          <div className="h-5 w-36 rounded bg-muted mb-2" />
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3">
              <div className="h-4 w-12 rounded bg-muted/70" />
              <div className="flex-1 h-5 rounded bg-muted/50" />
              <div className="h-4 w-8 rounded bg-muted/70" />
            </div>
          ))}
        </div>

        {/* Right: gaps table */}
        <div className="rounded-xl border border-border bg-card overflow-hidden">
          <div className="flex gap-3 px-5 py-3 border-b border-border bg-muted/30">
            {[2, 2, 1, 1, 1].map((fr, i) => (
              <div key={i} className="h-4 rounded bg-muted/70" style={{ flex: fr }} />
            ))}
          </div>
          {Array.from({ length: 10 }).map((_, i) => (
            <div
              key={i}
              className="flex gap-3 px-5 py-4 border-b border-border last:border-0"
            >
              <div className="flex gap-2 items-center" style={{ flex: 2 }}>
                <div className="h-8 w-8 rounded-full bg-muted/70 shrink-0" />
                <div className="space-y-1.5 flex-1">
                  <div className="h-3.5 w-28 rounded bg-muted" />
                  <div className="h-3 w-16 rounded bg-muted/60" />
                </div>
              </div>
              <div className="space-y-1.5" style={{ flex: 2 }}>
                <div className="h-3.5 w-36 rounded bg-muted" />
                <div className="h-3 w-20 rounded bg-muted/60" />
              </div>
              <div className="h-6 w-16 rounded-full bg-muted/60" style={{ flex: 1, alignSelf: "center" }} />
              <div className="h-4 w-20 rounded bg-muted/70" style={{ flex: 1, alignSelf: "center" }} />
              <div className="h-6 w-14 rounded-full bg-muted/50" style={{ flex: 1, alignSelf: "center" }} />
            </div>
          ))}
        </div>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between mt-4">
        <div className="h-4 w-40 rounded bg-muted/60" />
        <div className="flex gap-2">
          <div className="h-8 w-8 rounded bg-muted/60" />
          <div className="h-8 w-8 rounded bg-muted/60" />
        </div>
      </div>

      <span className="sr-only">Loading recapture gaps, please wait...</span>
    </div>
  );
}
