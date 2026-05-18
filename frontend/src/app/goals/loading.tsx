/**
 * Next.js route-level loading UI for /goals.
 * Layout: page header + Set Goal button → section label → 3-column goal-card grid
 *   (each card: metric icon + label, progress bar, actual/target values, meta row).
 */
export default function Loading() {
  return (
    <div
      role="status"
      aria-busy="true"
      aria-live="polite"
      className="container mx-auto p-6 space-y-8 max-w-5xl animate-pulse"
    >
      <span className="sr-only">Loading quarterly goals…</span>

      {/* Page header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="space-y-2">
          <div className="h-7 w-44 rounded-lg bg-muted" />
          <div className="h-4 w-72 rounded bg-muted/70" />
        </div>
        <div className="h-9 w-24 rounded-lg bg-muted self-start sm:self-auto" />
      </div>

      {/* Active quarter section */}
      <div className="space-y-3">
        {/* Section label */}
        <div className="h-3.5 w-36 rounded bg-muted/70" />

        {/* 3-column goal card grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="rounded-xl border border-slate-200 bg-white p-5 space-y-4 shadow-sm"
            >
              {/* Card header: metric icon + label + period badge */}
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  <div className="h-7 w-7 rounded-lg bg-muted/60" />
                  <div className="h-4 w-28 rounded bg-muted" />
                </div>
                <div className="h-5 w-16 rounded-full bg-muted/50" />
              </div>

              {/* Progress section */}
              <div className="space-y-1.5">
                <div className="flex justify-between">
                  <div className="h-3.5 w-16 rounded bg-muted/70" />
                  <div className="h-3.5 w-10 rounded bg-muted/70" />
                </div>
                {/* Progress bar */}
                <div className="w-full h-2.5 rounded-full bg-muted/40 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-muted/70"
                    style={{ width: `${40 + i * 20}%` }}
                  />
                </div>
                {/* Actual / target labels */}
                <div className="flex justify-between">
                  <div className="h-3 w-20 rounded bg-muted/60" />
                  <div className="h-3 w-20 rounded bg-muted/60" />
                </div>
              </div>

              {/* Meta row: days remaining + on-track indicator */}
              <div className="flex items-center justify-between pt-1 border-t border-slate-100">
                <div className="h-3.5 w-28 rounded bg-muted/60" />
                <div className="h-3.5 w-20 rounded bg-muted/50" />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Previous quarters section */}
      <div className="space-y-3">
        <div className="h-3.5 w-32 rounded bg-muted/70" />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[0, 1].map((i) => (
            <div
              key={i}
              className="rounded-xl border border-slate-200 bg-white p-5 space-y-4 shadow-sm"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  <div className="h-7 w-7 rounded-lg bg-muted/50" />
                  <div className="h-4 w-24 rounded bg-muted/70" />
                </div>
                <div className="h-5 w-16 rounded-full bg-muted/40" />
              </div>
              <div className="space-y-1.5">
                <div className="flex justify-between">
                  <div className="h-3.5 w-16 rounded bg-muted/60" />
                  <div className="h-3.5 w-10 rounded bg-muted/60" />
                </div>
                <div className="w-full h-2.5 rounded-full bg-muted/30 overflow-hidden">
                  <div className="h-full rounded-full bg-muted/60" style={{ width: "100%" }} />
                </div>
                <div className="flex justify-between">
                  <div className="h-3 w-20 rounded bg-muted/50" />
                  <div className="h-3 w-20 rounded bg-muted/50" />
                </div>
              </div>
              <div className="flex items-center justify-between pt-1 border-t border-slate-100">
                <div className="h-3.5 w-24 rounded bg-muted/50" />
                <div className="h-3.5 w-16 rounded bg-muted/40" />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
