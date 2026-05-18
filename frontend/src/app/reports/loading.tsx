/**
 * Next.js route-level loading UI for /reports.
 * Layout: page header → report-group tabs → tab content area with
 *   KPI summary row → chart panel → data table rows.
 */
export default function Loading() {
  return (
    <div
      role="status"
      aria-busy="true"
      aria-live="polite"
      className="p-6 space-y-5 bg-background min-h-screen animate-pulse"
    >
      <span className="sr-only">Loading reports…</span>

      {/* Page header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div className="space-y-2">
          <div className="h-7 w-40 rounded-lg bg-muted" />
          <div className="h-4 w-72 rounded bg-muted/70" />
        </div>
        <div className="flex gap-2">
          <div className="h-9 w-32 rounded-lg bg-muted/60" />
          <div className="h-9 w-28 rounded-lg bg-muted/50" />
        </div>
      </div>

      {/* Report-group pill tabs (Clinical / Analytics) */}
      <div className="flex gap-2">
        <div className="h-9 w-24 rounded-lg bg-muted" />
        <div className="h-9 w-24 rounded-lg bg-muted/50" />
      </div>

      {/* Sub-tab strip (Revenue, Patient Scorecard, HCC Distribution…) */}
      <div className="flex gap-2 overflow-hidden">
        {[80, 120, 116, 140, 64].map((w, i) => (
          <div key={i} className="h-8 rounded-md bg-muted/60 shrink-0" style={{ width: w }} />
        ))}
      </div>

      {/* Filter bar */}
      <div className="flex gap-3 items-center flex-wrap">
        <div className="h-9 w-32 rounded-lg bg-muted/70" />
        <div className="h-9 w-36 rounded-lg bg-muted/60" />
        <div className="h-9 w-40 rounded-lg bg-muted/60" />
        <div className="ml-auto h-9 w-24 rounded-lg bg-muted/50" />
      </div>

      {/* KPI summary row (3-up) */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="rounded-xl border border-border bg-card p-4 space-y-2"
          >
            <div className="h-3.5 w-24 rounded bg-muted/70" />
            <div className="h-8 w-20 rounded bg-muted" />
            <div className="h-3 w-28 rounded bg-muted/50" />
          </div>
        ))}
      </div>

      {/* Chart panel */}
      <div className="rounded-xl border border-border bg-card p-5 space-y-3">
        <div className="flex items-center justify-between">
          <div className="h-5 w-44 rounded bg-muted" />
          <div className="h-8 w-28 rounded-lg bg-muted/60" />
        </div>
        {/* Chart placeholder area */}
        <div className="h-52 rounded-lg bg-muted/30 flex items-end gap-1 px-4 pb-4 overflow-hidden">
          {[40, 55, 70, 60, 80, 65, 90, 75, 85, 95, 70, 60].map((h, i) => (
            <div
              key={i}
              className="flex-1 rounded-t bg-muted/60"
              style={{ height: `${h}%` }}
            />
          ))}
        </div>
      </div>

      {/* Data table */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        {/* Header */}
        <div className="flex gap-3 px-5 py-3 border-b border-border bg-muted/30">
          {[1.5, 1, 1, 1, 0.8].map((fr, i) => (
            <div key={i} className="h-4 rounded bg-muted/70" style={{ flex: fr }} />
          ))}
        </div>
        {Array.from({ length: 7 }).map((_, i) => (
          <div
            key={i}
            className="flex gap-3 items-center px-5 py-3.5 border-b border-border last:border-0"
          >
            <div className="space-y-1.5" style={{ flex: 1.5 }}>
              <div className="h-3.5 w-32 rounded bg-muted" />
              <div className="h-3 w-20 rounded bg-muted/60" />
            </div>
            <div className="h-4 rounded bg-muted/60" style={{ flex: 1 }} />
            <div className="h-5 w-16 rounded-full bg-muted/60" style={{ flex: 1 }} />
            <div className="h-4 rounded bg-muted/60" style={{ flex: 1 }} />
            <div className="h-8 w-20 rounded-lg bg-muted/50" style={{ flex: 0.8 }} />
          </div>
        ))}
      </div>
    </div>
  );
}
