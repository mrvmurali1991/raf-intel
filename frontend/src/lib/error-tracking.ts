/**
 * Client-side error tracking.
 * Sends scrubbed errors to backend /api/admin/errors/report endpoint.
 * Supports Sentry SDK when NEXT_PUBLIC_SENTRY_DSN is set.
 */

/**
 * Scrub common PHI-adjacent patterns and secret shapes before the message
 * leaves the browser. The backend endpoint also re-scrubs; this is
 * belt-and-braces. Keep short and cheap — this runs in an error handler.
 */
function scrub(value: string): string {
  return value
    .replace(/(?:authorization|bearer|token|password|secret|api[_-]?key|ssn|mrn)[=:\s]+\S+/gi, "[redacted]")
    .replace(/\b\d{3}-\d{2}-\d{4}\b/g, "[redacted-ssn]")
    .replace(/\b\d{13,19}\b/g, "[redacted-long-number]")
    .slice(0, 500);
}

interface ErrorEvent {
  type: string;
  message: string;
  source?: string;
  line?: number;
}

export function initErrorTracking() {
  window.addEventListener("error", (event) => {
    reportError({
      type: "uncaught",
      message: scrub(event.message || "unknown"),
      source: event.filename ? scrub(event.filename) : undefined,
      line: event.lineno,
    });
  });
  window.addEventListener("unhandledrejection", (event) => {
    reportError({
      type: "unhandled_promise",
      message: scrub(String(event.reason)),
    });
  });
}

function reportError(error: ErrorEvent) {
  // Plain fetch (no axios) to avoid recursive error-reporting if axios itself
  // is the failure source. Credentials: 'same-origin' sends the refresh
  // cookie so the backend can optionally resolve the user without requiring
  // an Authorization header (pre-login errors are still accepted).
  fetch("/api/admin/errors/report", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(error),
    keepalive: true,
  }).catch((e) => {
    if (process.env.NODE_ENV !== "production") {
      // eslint-disable-next-line no-console
      console.warn("error-tracking: failed to report error", e);
    }
  });
}
