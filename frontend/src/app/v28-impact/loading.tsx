/**
 * Next.js route-level loading UI for /v28-impact.
 * Layout: page header → 4-up KPI strip → histogram panel → top-eroded table.
 */
export default function Loading() {
  return (
    <div
      role="status"
      aria-busy="true"
      aria-live="polite"
      className="p-6 space-y-6 bg-background min-h-screen animate-pulse"
    >
      <span className="sr-only">Loading V28 transition impact…</span>

      {/* Page header */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div className="space-y-2">
          <div className="h-7 w-64 rounded-lg bg-muted" />
          <div className="h-4 w-96 rounded bg-muted/70" />
        </div>
        <div className="flex gap-2">
          <div className="h-9 w-28 rounded-lg bg-muted/60" />
          <div className="h-9 w-24 rounded-lg bg-muted/50" />
        </div>
      </div>

      {/* 4-up KPI strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { w: "w-20" },
          { w: "w-24" },
          { w: "w-16" },
          { w: "w-28" },
        ].map((c, i) => (
          <div
            key={i}
            className="rounded-xl border border-border bg-card p-4 space-y-2"
          >
            <div className="flex items-center justify-between">
              <div className="h-3.5 w-24 rounded bg-muted/70" />
              <div className="h-5 w-5 rounded bg-muted/50" />
            </div>
            <div className={`h-8 ${c.w} rounded bg-muted`} />
            <div className="h-3 w-20 rounded bg-muted/50" />
          </div>
        ))}
      </div>

      {/* 2-col body: histogram + HCC breakdown */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6">
        {/* Histogram panel */}
        <div className="rounded-xl border border-border bg-card p-5 space-y-4">
          <div className="flex items-center justify-between">
            <div className="h-5 w-48 rounded bg-muted" />
            <div className="h-4 w-24 rounded bg-muted/60" />
          </div>
          {/* Bars */}
          {[55, 80, 100, 90, 70, 50, 35, 25, 18, 12].map((pct, i) => (
            <div key={i} className="flex items-center gap-3">
              <div className="w-20 h-4 rounded bg-muted/70 shrink-0" />
              <div className="flex-1 h-7 rounded bg-muted/40 overflow-hidden">
                <div
                  className="h-full rounded bg-muted/70"
                  style={{ width: `${pct}%` }}
                />
              </div>
              <div className="w-8 h-4 rounded bg-muted/70 shrink-0" />
            </div>
          ))}
        </div>

        {/* HCC erosion breakdown sidebar */}
        <div className="rounded-xl border border-border bg-card p-4 space-y-3">
          <div className="h-5 w-36 rounded bg-muted mb-2" />
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3">
              <div className="h-4 w-10 rounded bg-muted/70 shrink-0" />
              <div className="flex-1 h-5 rounded bg-muted/40 overflow-hidden">
                <div
                  className="h-full rounded bg-muted/60"
                  style={{ width: `${100 - i * 10}%` }}
                />
              </div>
              <div className="h-4 w-12 rounded bg-muted/70 shrink-0" />
            </div>
          ))}
        </div>
      </div>

      {/* Top-eroded patients table */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        <div className="px-5 py-3 border-b border-border bg-muted/30">
          <div className="h-5 w-48 rounded bg-muted" />
        </div>
        {/* Header */}
        <div className="flex gap-3 px-5 py-3 border-b border-border bg-muted/20">
          {[1.4, 0.8, 0.8, 0.9, 0.8, 1.2].map((fr, i) => (
            <div key={i} className="h-4 rounded bg-muted/70" style={{ flex: fr }} />
          ))}
        </div>
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className="flex gap-3 items-center px-5 py-3.5 border-b border-border last:border-0"
          >
            <div className="space-y-1" style={{ flex: 1.4 }}>
              <div className="h-3.5 w-28 rounded bg-muted" />
              <div className="h-3 w-16 rounded bg-muted/60" />
            </div>
            <div className="h-4 w-14 rounded bg-muted/70" style={{ flex: 0.8 }} />
            <div className="h-4 w-14 rounded bg-muted/70" style={{ flex: 0.8 }} />
            <div className="h-5 w-16 rounded-full bg-muted/60" style={{ flex: 0.9 }} />
            <div className="h-5 w-20 rounded-full bg-muted/60" style={{ flex: 0.8 }} />
            <div className="flex gap-1" style={{ flex: 1.2 }}>
              <div className="h-5 w-10 rounded-full bg-muted/50" />
              <div className="h-5 w-10 rounded-full bg-muted/50" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
