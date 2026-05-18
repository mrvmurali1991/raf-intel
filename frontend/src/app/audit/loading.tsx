/**
 * Next.js route-level loading UI for /audit.
 * Layout: page header → readiness card → filter bar → package table (header + 6 rows).
 */
export default function Loading() {
  return (
    <div
      role="status"
      aria-busy="true"
      aria-live="polite"
      className="p-6 space-y-6 bg-background min-h-screen animate-pulse"
    >
      <span className="sr-only">Loading audit packages…</span>

      {/* Page header */}
      <div className="flex items-start justify-between">
        <div className="space-y-2">
          <div className="h-7 w-48 rounded-lg bg-muted" />
          <div className="h-4 w-80 rounded bg-muted/70" />
        </div>
        {/* Action buttons */}
        <div className="flex gap-2">
          <div className="h-9 w-32 rounded-lg bg-muted/60" />
          <div className="h-9 w-28 rounded-lg bg-muted/60" />
        </div>
      </div>

      {/* Audit readiness card (AuditReadinessCard shape) */}
      <div className="rounded-xl border border-border bg-card p-5 space-y-4">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-lg bg-muted/70" />
          <div className="h-5 w-44 rounded bg-muted" />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="space-y-1.5">
              <div className="h-3 w-20 rounded bg-muted/70" />
              <div className="h-6 w-14 rounded bg-muted" />
            </div>
          ))}
        </div>
        {/* RADV scenarios block */}
        <div className="space-y-2 pt-2 border-t border-border">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-12 rounded-lg bg-muted/40" />
          ))}
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex gap-3 items-center">
        <div className="h-9 w-44 rounded-lg bg-muted/70" />
        <div className="h-9 flex-1 max-w-xs rounded-lg bg-muted/60" />
        <div className="ml-auto h-9 w-32 rounded-lg bg-muted/50" />
      </div>

      {/* Package table */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        {/* Header */}
        <div className="flex gap-3 px-5 py-3 border-b border-border bg-muted/30">
          {[0.4, 1.6, 1, 1, 0.8, 0.8, 0.7].map((fr, i) => (
            <div key={i} className="h-4 rounded bg-muted/70" style={{ flex: fr }} />
          ))}
        </div>
        {/* Rows */}
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="flex gap-3 items-center px-5 py-4 border-b border-border last:border-0"
          >
            {/* Checkbox */}
            <div className="h-4 w-4 rounded bg-muted/60 shrink-0" style={{ flex: 0.4 }} />
            {/* Patient name + ID */}
            <div className="space-y-1.5" style={{ flex: 1.6 }}>
              <div className="h-3.5 w-32 rounded bg-muted" />
              <div className="h-3 w-20 rounded bg-muted/60" />
            </div>
            {/* HCC codes */}
            <div className="flex gap-1" style={{ flex: 1 }}>
              <div className="h-5 w-12 rounded-full bg-muted/60" />
              <div className="h-5 w-12 rounded-full bg-muted/50" />
            </div>
            {/* RAF score */}
            <div className="h-5 w-14 rounded-full bg-muted/60" style={{ flex: 1 }} />
            {/* Status badge */}
            <div className="h-5 w-20 rounded-full bg-muted/60" style={{ flex: 0.8 }} />
            {/* Date */}
            <div className="h-4 w-24 rounded bg-muted/60" style={{ flex: 0.8 }} />
            {/* Action */}
            <div className="h-8 w-24 rounded-lg bg-muted/50" style={{ flex: 0.7 }} />
          </div>
        ))}
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between">
        <div className="h-4 w-40 rounded bg-muted/60" />
        <div className="flex gap-2">
          <div className="h-8 w-8 rounded bg-muted/60" />
          <div className="h-8 w-8 rounded bg-muted/60" />
        </div>
      </div>
    </div>
  );
}
