/**
 * Sentry edge (middleware / edge route handlers) init.
 *
 * Minimal init; runs in the edge runtime so the SDK surface is smaller.
 * No-ops cleanly when SENTRY_DSN is not set.
 */
import * as Sentry from "@sentry/nextjs";

const dsn = process.env.SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    environment: process.env.NODE_ENV,
    tracesSampleRate: 0.1,
  });
}
