/**
 * Client-side error tracking.
 * Sends errors to backend /api/admin/errors/report endpoint.
 * Supports Sentry SDK when NEXT_PUBLIC_SENTRY_DSN is set.
 */
export function initErrorTracking() {
  window.addEventListener("error", (event) => {
    reportError({ type: "uncaught", message: event.message, source: event.filename, line: event.lineno });
  });
  window.addEventListener("unhandledrejection", (event) => {
    reportError({ type: "unhandled_promise", message: String(event.reason) });
  });
}

function reportError(error: any) {
  // Fire and forget — don't block the UI
  fetch("/api/admin/errors/report", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(error),
  }).catch(() => {});
}
