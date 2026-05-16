/**
 * Client-side error tracking.
 *
 * Two destinations:
 *   1. Always: POST to backend /api/admin/errors/report (PHI-scrubbed).
 *   2. Optional: @sentry/nextjs when NEXT_PUBLIC_SENTRY_DSN is set.
 *
 * Sentry init is dynamic so that builds without the DSN — or builds
 * where @sentry/nextjs has not been installed yet — still succeed.
 * Run `npm install` after pulling so the optional dep is available.
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
 * Run npm install after pulling so @sentry/nextjs is available.
 */
async function initSentry(): Promise<void> {
  if (sentryInitialized) return;
  const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
  if (!dsn) return;

  try {
    // Dynamic import so the bundle does not break when the package is
    // not yet installed in dev environments. The package is declared
    // in package.json — run npm install after pulling.
    // We cast to a minimal local shape because the module may be absent
    // at typecheck time on fresh checkouts.
    type MinimalSentryEvent = {
      message?: string;
      exception?: { values?: Array<{ value?: string }> };
    };
    interface MinimalSentry {
      init(opts: {
        dsn: string;
        environment?: string;
        tracesSampleRate?: number;
        beforeSend?: (event: MinimalSentryEvent) => MinimalSentryEvent | null;
      }): void;
    }
    const mod = (await import(
      /* webpackChunkName: "sentry" */ "@sentry/nextjs" as string
    ).catch(() => null)) as MinimalSentry | null;
    if (!mod) return;

    mod.init({
      dsn,
      environment: process.env.NEXT_PUBLIC_ENV ?? process.env.NODE_ENV,
      tracesSampleRate: 0.1,
      beforeSend(event: MinimalSentryEvent) {
        // Defence-in-depth scrub on the way out.
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
