/**
 * Sentry server-side (Node.js runtime) init.
 *
 * Uses SENTRY_DSN (server-only secret), not the NEXT_PUBLIC_ variant.
 * No-ops cleanly when DSN is not set.
 */
import * as Sentry from "@sentry/nextjs";

const dsn = process.env.SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.NODE_ENV,
    tracesSampleRate: 0.1,
    beforeSend(event) {
      const scrub = (v: string) =>
        v
          .replace(
            /(?:authorization|bearer|token|password|secret|api[_-]?key|ssn|mrn)[=:\s]+\S+/gi,
            "[redacted]",
          )
          .replace(/\b\d{3}-\d{2}-\d{4}\b/g, "[redacted-ssn]")
          .replace(/\b\d{13,19}\b/g, "[redacted-long-number]");
      if (event.message) event.message = scrub(event.message);
      if (event.exception?.values) {
        for (const v of event.exception.values) {
          if (v.value) v.value = scrub(v.value);
        }
      }
      return event;
    },
  });
}
