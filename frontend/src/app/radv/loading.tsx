/**
 * Next.js route-level loading UI for /radv (RADV Audit Defense).
 * Layout: page header → 5-up stat tiles → tab bar → audit-runs table (list view).
 */
export default function Loading() {
  return (
    <div
      role="status"
      aria-busy="true"
      aria-live="polite"
      className="p-6 space-y-5 bg-background min-h-screen animate-pulse"
    >
      <span className="sr-only">Loading RADV audit defense…</span>

      {/* Page header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-7 w-7 rounded-lg bg-muted" />
          <div className="space-y-1.5">
            <div className="h-6 w-48 rounded-lg bg-muted" />
            <div className="h-3.5 w-72 rounded bg-muted/70" />
          </div>
        </div>
        <div className="flex items-center gap-3">
          {/* Extrapolation toggle */}
          <div className="h-8 w-48 rounded-lg bg-muted/60" />
          {/* New run button */}
          <div className="h-9 w-32 rounded-lg bg-muted" />
        </div>
      </div>

      {/* 5-up stat tiles — shown in detail view */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {[
          { label: "Records", w: "w-14" },
          { label: "Defensible", w: "w-10" },
          { label: "Undefensible", w: "w-10" },
          { label: "Pending", w: "w-10" },
          { label: "Exposure", w: "w-20" },
        ].map((c, i) => (
          <div
            key={i}
            className="rounded-xl border border-border bg-card p-3 space-y-1.5"
          >
            <div className="h-3 w-20 rounded bg-muted/70" />
            <div className={`h-6 ${c.w} rounded bg-muted`} />
          </div>
        ))}
      </div>

      {/* Tab bar */}
      <div className="flex gap-2">
        <div className="h-9 w-32 rounded-lg bg-muted" />
        <div className="h-9 w-36 rounded-lg bg-muted/50" />
        <div className="ml-auto h-9 w-40 rounded-lg bg-muted/60" />
        <div className="h-9 w-32 rounded-lg bg-muted/60" />
      </div>

      {/* Audit runs table */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        {/* Header */}
        <div className="flex gap-3 px-5 py-3 border-b border-border bg-muted/30">
          {[1.4, 0.6, 0.7, 1, 0.8, 0.8, 1, 0.5].map((fr, i) => (
            <div key={i} className="h-4 rounded bg-muted/70" style={{ flex: fr }} />
          ))}
        </div>
        {/* Rows — Name | Year | Sample | Method | Status | Decided | Exposure | Action */}
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className="flex gap-3 items-center px-5 py-4 border-b border-border last:border-0"
          >
            {/* Name */}
            <div className="h-4 w-36 rounded bg-muted font-semibold" style={{ flex: 1.4 }} />
            {/* Year */}
            <div className="h-4 w-10 rounded bg-muted/70" style={{ flex: 0.6 }} />
            {/* Sample */}
            <div className="h-4 w-12 rounded bg-muted/70" style={{ flex: 0.7 }} />
            {/* Method */}
            <div className="h-4 w-24 rounded bg-muted/60" style={{ flex: 1 }} />
            {/* Status badge */}
            <div className="h-5 w-18 rounded-full bg-muted/60" style={{ flex: 0.8 }} />
            {/* Decided */}
            <div className="h-4 w-10 rounded bg-muted/70" style={{ flex: 0.8 }} />
            {/* Exposure */}
            <div className="h-4 w-20 rounded bg-muted" style={{ flex: 1 }} />
            {/* Open button */}
            <div className="h-8 w-16 rounded-lg bg-muted/50" style={{ flex: 0.5 }} />
          </div>
        ))}
      </div>
    </div>
  );
}
