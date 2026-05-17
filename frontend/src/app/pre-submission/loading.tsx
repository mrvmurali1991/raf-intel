export default function Loading() {
  return (
    <div role="status" aria-label="Loading pre-submission dashboard" aria-busy="true" aria-live="polite" className="p-6 space-y-6">
      <div className="space-y-2">
        <div className="h-8 w-72 rounded-md bg-muted animate-pulse" />
        <div className="h-4 w-96 rounded-md bg-muted animate-pulse" />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-32 rounded-2xl bg-muted animate-pulse" />
        ))}
      </div>
      <div className="space-y-2 mt-4">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="h-12 w-full rounded-md bg-muted animate-pulse" />
        ))}
      </div>
      <span className="sr-only">Loading pre-submission validation results…</span>
    </div>
  );
}
