/**
 * Sentry client-side init.
 *
 * This file is auto-loaded by @sentry/nextjs in the browser bundle.
 * No-ops cleanly when NEXT_PUBLIC_SENTRY_DSN is not set so local/dev
 * builds never emit network requests or console errors.
 */
import * as Sentry from "@sentry/nextjs";

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.NEXT_PUBLIC_ENV ?? process.env.NODE_ENV,
    tracesSampleRate: 0.1,
    integrations: [Sentry.browserTracingIntegration()],
    beforeSend(event) {
      // PHI / secret defence-in-depth scrub before leaving the browser.
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
