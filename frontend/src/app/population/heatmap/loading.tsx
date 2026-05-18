/**
 * Next.js route-level loading UI for /population/heatmap.
 * Rendered INSTANTLY during navigation (parallel route slot) giving perceived
 * <100 ms transition while the heatmap API call resolves (~5-7 s cold).
 *
 * Layout mirrors the real page exactly:
 *   page header → year picker → 4-up KPI cards → bar-chart panel → ZIP table
 */
export default function Loading() {
  return (
    <div
      role="status"
      aria-label="Loading population heatmap"
      aria-busy="true"
      aria-live="polite"
      className="rci-page-pad-desktop bg-background text-foreground min-h-screen animate-pulse"
    >
      {/* ── Page header ─────────────────────────────────────────── */}
      <div className="flex items-start justify-between mb-6 flex-wrap gap-3">
        <div>
          <div className="h-8 w-72 rounded-lg bg-muted mb-2" />
          <div className="h-4 w-96 rounded bg-muted/70" />
        </div>
        {/* Year picker placeholder */}
        <div className="h-9 w-28 rounded-lg bg-muted/60" />
      </div>

      {/* ── 4-up KPI cards ──────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        {[
          { label: "ZIP Codes", icon: "w-5 h-5" },
          { label: "Patients", icon: "w-5 h-5" },
          { label: "Open Gaps", icon: "w-5 h-5" },
          { label: "High Risk", icon: "w-5 h-5" },
        ].map((_, i) => (
          <div
            key={i}
            className="rounded-xl border border-border bg-card p-4 flex flex-col gap-2"
          >
            <div className="flex items-center justify-between">
              <div className="h-3.5 w-24 rounded bg-muted/70" />
              <div className="h-5 w-5 rounded bg-muted/60" />
            </div>
            <div className="h-8 w-20 rounded bg-muted" />
            <div className="h-3 w-28 rounded bg-muted/50" />
          </div>
        ))}
      </div>

      {/* ── Bar-chart panel ─────────────────────────────────────── */}
      <div className="rounded-xl border border-border bg-card p-6 mb-6">
        {/* Chart title + legend */}
        <div className="flex items-center justify-between mb-5">
          <div className="h-5 w-52 rounded bg-muted" />
          <div className="flex gap-3">
            <div className="h-4 w-20 rounded bg-muted/60" />
            <div className="h-4 w-20 rounded bg-muted/60" />
            <div className="h-4 w-20 rounded bg-muted/60" />
          </div>
        </div>

        {/* Horizontal bars — vary widths to feel organic */}
        {[90, 78, 71, 63, 58, 52, 47, 43, 38, 34, 30, 26].map((pct, i) => (
          <div key={i} className="flex items-center gap-3 mb-3">
            {/* ZIP label */}
            <div className="w-14 h-4 rounded bg-muted/70 shrink-0" />
            {/* Bar */}
            <div className="flex-1 h-7 rounded bg-muted/40 overflow-hidden">
              <div
                className="h-full rounded bg-muted/70"
                style={{ width: `${pct}%` }}
              />
            </div>
            {/* Count */}
            <div className="w-10 h-4 rounded bg-muted/70 shrink-0 text-right" />
            {/* RAF badge */}
            <div className="w-16 h-6 rounded-full bg-muted/60 shrink-0" />
          </div>
        ))}
      </div>

      {/* ── ZIP table skeleton ──────────────────────────────────── */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        {/* Table header */}
        <div className="flex gap-4 px-5 py-3 border-b border-border bg-muted/30">
          {[0.8, 1, 1, 1, 1, 1].map((fr, i) => (
            <div key={i} className="h-4 rounded bg-muted/70" style={{ flex: fr }} />
          ))}
        </div>

        {/* Table rows */}
        {Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            className="flex gap-4 px-5 py-3.5 border-b border-border last:border-0"
          >
            {/* ZIP */}
            <div className="h-4 w-14 rounded bg-muted/70" style={{ flex: 0.8 }} />
            {/* Patients */}
            <div className="h-4 rounded bg-muted/60" style={{ flex: 1 }} />
            {/* Avg RAF */}
            <div className="h-6 w-20 rounded-full bg-muted/60" style={{ flex: 1, alignSelf: "center" }} />
            {/* Open Gaps */}
            <div className="h-4 rounded bg-muted/60" style={{ flex: 1 }} />
            {/* High Risk */}
            <div className="h-4 rounded bg-muted/60" style={{ flex: 1 }} />
            {/* Risk bar */}
            <div className="h-2 rounded-full bg-muted/50 self-center" style={{ flex: 1 }} />
          </div>
        ))}
      </div>

      <span className="sr-only">Loading population heatmap, please wait…</span>
    </div>
  );
}
