/**
 * Client-side error tracking.
 *
 * Two destinations:
 *   1. Always: POST to backend /api/admin/errors/report (PHI-scrubbed).
 *   2. Optional: @sentry/nextjs when NEXT_PUBLIC_SENTRY_DSN is set.
 *
 * Sentry is loaded via dynamic import() so that the SDK is code-split out
 * of the main bundle and only fetched when a DSN is configured. When no
 * DSN is set, initSentry() is a no-op.
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

let sentryInitialized = false;

/**
 * Initialise Sentry if a DSN is configured. No-op otherwise.
 *
 * NOTE: sentry.client.config.ts already calls Sentry.init() at bundle load
 * time when the DSN is present. This function is kept as an idempotent
 * safety net that scrubs PHI from any events that bypass that config
 * (e.g. very early errors before the Sentry config module evaluates).
 */
async function initSentry(): Promise<void> {
  if (sentryInitialized) return;
  const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
  if (!dsn) return;

  try {
    const Sentry = await import("@sentry/nextjs");
    // If the auto-loaded sentry.client.config.ts has already initialised
    // the SDK, getClient() returns a truthy hub and we just mark done.
    if (Sentry.getClient()) {
      sentryInitialized = true;
      return;
    }
    Sentry.init({
      dsn,
      environment: process.env.NEXT_PUBLIC_ENV ?? process.env.NODE_ENV,
      tracesSampleRate: 0.1,
      beforeSend(event) {
        if (event.message) event.message = scrub(event.message);
        if (event.exception?.values) {
          for (const v of event.exception.values) {
            if (v.value) v.value = scrub(v.value);
          }
        }
        return event;
      },
    });
    sentryInitialized = true;
  } catch {
    // Swallow — if Sentry can't init, the in-app POST below still works.
  }
}

export function initErrorTracking() {
  // Fire-and-forget Sentry init; in-app reporting works regardless.
  void initSentry();

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
