/**
 * Next.js route-level loading UI for /attestations.
 * Layout: page header → 6-up KPI strip → status tabs + search bar → attestation table.
 */
export default function Loading() {
  return (
    <div
      role="status"
      aria-busy="true"
      aria-live="polite"
      className="p-6 space-y-6 bg-background min-h-screen animate-pulse"
    >
      <span className="sr-only">Loading attestations…</span>

      {/* Page header */}
      <div className="flex items-center justify-between">
        <div className="space-y-2">
          <div className="h-7 w-52 rounded-lg bg-muted" />
          <div className="h-4 w-80 rounded bg-muted/70" />
        </div>
        <div className="h-9 w-24 rounded-lg bg-muted/60" />
      </div>

      {/* 6-up KPI strip */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-4">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <div
            key={i}
            className="rounded-xl border border-border bg-card p-4 flex flex-col gap-2"
          >
            <div className="flex items-center justify-between">
              <div className="h-3.5 w-16 rounded bg-muted/70" />
              <div className="h-4 w-4 rounded bg-muted/50" />
            </div>
            <div className="h-7 w-12 rounded bg-muted" />
          </div>
        ))}
      </div>

      {/* Filters row: status tabs + search */}
      <div className="flex gap-3 items-center flex-wrap">
        {/* Status tab group */}
        <div className="flex gap-1 p-1 rounded-lg bg-muted/40">
          {[56, 64, 72, 68, 68].map((w, i) => (
            <div key={i} className="h-8 rounded-md bg-muted/60" style={{ width: w }} />
          ))}
        </div>
        {/* Search */}
        <div className="h-9 flex-1 max-w-xs rounded-lg bg-muted/60" />
      </div>

      {/* Attestation table */}
      <div className="rounded-xl border border-border bg-card overflow-hidden">
        {/* Header */}
        <div className="flex gap-3 px-5 py-3 border-b border-border bg-muted/30">
          {[0.6, 1.2, 1.2, 1, 0.8, 0.8, 0.7].map((fr, i) => (
            <div key={i} className="h-4 rounded bg-muted/70" style={{ flex: fr }} />
          ))}
        </div>
        {/* Rows — columns: Patient ID | HCC | ICD-10 | Provider NPI | Source | Status | Created */}
        {Array.from({ length: 8 }).map((_, i) => (
          <div
            key={i}
            className="flex gap-3 items-start px-5 py-3.5 border-b border-border last:border-0"
          >
            {/* Patient ID */}
            <div className="h-4 w-12 rounded bg-muted/70 shrink-0" style={{ flex: 0.6, alignSelf: "center" }} />
            {/* HCC */}
            <div className="space-y-1" style={{ flex: 1.2 }}>
              <div className="h-3.5 w-16 rounded bg-muted font-semibold" />
              <div className="h-3 w-36 rounded bg-muted/60" />
            </div>
            {/* ICD-10 */}
            <div className="space-y-1" style={{ flex: 1.2 }}>
              <div className="h-3.5 w-14 rounded bg-muted" />
              <div className="h-3 w-40 rounded bg-muted/60" />
            </div>
            {/* Provider NPI */}
            <div className="h-4 w-24 rounded bg-muted/70" style={{ flex: 1, alignSelf: "center" }} />
            {/* Source badge */}
            <div className="h-5 w-16 rounded bg-muted/50" style={{ flex: 0.8, alignSelf: "center" }} />
            {/* Status badge */}
            <div className="h-5 w-16 rounded-full bg-muted/60" style={{ flex: 0.8, alignSelf: "center" }} />
            {/* Created date */}
            <div className="h-4 w-20 rounded bg-muted/60" style={{ flex: 0.7, alignSelf: "center" }} />
          </div>
        ))}
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between">
        <div className="h-4 w-40 rounded bg-muted/60" />
        <div className="flex gap-2">
          <div className="h-8 w-16 rounded-lg bg-muted/60" />
          <div className="h-8 w-16 rounded-lg bg-muted/60" />
        </div>
      </div>
    </div>
  );
}
