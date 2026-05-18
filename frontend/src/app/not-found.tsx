import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Page not found",
};

/**
 * Next.js app-router 404 page.
 *
 * Uses semantic Tailwind tokens (bg-background / text-foreground) so the
 * dark-mode surface is applied correctly — the `.dark` class on <html> is
 * set by ThemeProvider in the root layout, which does propagate here even
 * though this route is rendered outside the main layout shell.
 */
export default function NotFound() {
  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col items-center justify-center px-6 py-24 text-center">
      {/* Error code */}
      <p className="text-sm font-semibold uppercase tracking-widest text-teal-600 dark:text-teal-400 mb-3">
        404
      </p>

      {/* Heading */}
      <h1 className="text-3xl font-bold tracking-tight text-foreground sm:text-4xl mb-4">
        Page not found
      </h1>

      {/* Sub-copy */}
      <p className="max-w-sm text-base text-muted-foreground mb-8">
        The page you&apos;re looking for doesn&apos;t exist or has been moved.
      </p>

      {/* Primary CTA */}
      <Link
        href="/"
        className="inline-flex items-center justify-center rounded-lg bg-teal-600 hover:bg-teal-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-teal-500 focus-visible:ring-offset-2 text-white text-sm font-semibold px-6 py-2.5 transition-colors"
      >
        Back to Dashboard
      </Link>

      {/* Support link */}
      <p className="mt-6 text-sm text-muted-foreground">
        Need help?{" "}
        <a
          href="mailto:support@raf.health"
          className="underline underline-offset-4 hover:text-foreground transition-colors"
        >
          Contact support
        </a>
      </p>
    </div>
  );
}
