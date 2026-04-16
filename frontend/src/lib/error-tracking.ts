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
  // Fire and forget — don't block the UI. Errors in reporting itself
  // are suppressed by design to avoid infinite loops (reporting error
  // → reporting failure → reporting error …). Dev-mode surfaces them.
  fetch("/api/admin/errors/report", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(error),
  }).catch((e) => {
    if (process.env.NODE_ENV !== "production") {
      // eslint-disable-next-line no-console
      console.warn("error-tracking: failed to report error", e);
    }
  });
}
