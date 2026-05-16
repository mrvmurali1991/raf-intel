export default function Loading() {
  return (
    <div role="status" aria-label="Loading" aria-busy="true" aria-live="polite" className="p-6 space-y-4">
      <div className="h-8 w-64 rounded-md bg-muted animate-pulse" />
      <div className="h-4 w-96 rounded-md bg-muted animate-pulse" />
      <div className="space-y-2 mt-6">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-12 w-full rounded-md bg-muted animate-pulse" />
        ))}
      </div>
      <span className="sr-only">Loading worklist…</span>
    </div>
  );
}
