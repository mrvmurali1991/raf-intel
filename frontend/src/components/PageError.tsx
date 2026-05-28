"use client";

import { useEffect } from "react";
import { AlertTriangle } from "lucide-react";

/**
 * Shared route-level error fallback used by every `error.tsx` under
 * `frontend/src/app/`. Centralised here so wording/styling tweaks ship in
 * one place instead of touching dozens of duplicate files.
 *
 * Next.js App Router contract: each route's `error.tsx` must default-export
 * a Client Component that accepts `{ error, reset }`. Re-export this from
 * each route to satisfy the contract without copy-paste.
 *
 * Can also be rendered inline (outside of error.tsx) using the named props:
 *
 *   <PageError
 *     title="Something went wrong"
 *     message="We hit an unexpected error."
 *     contextual="Failed to load suspects"
 *     retry={reset}
 *   />
 *
 * Or the App Router way (error.tsx default export):
 *
 *   export { default } from "@/components/PageError";
 */

// ---------------------------------------------------------------------------
// Prop interfaces
// ---------------------------------------------------------------------------

/** Extended props for inline / programmatic usage */
export interface PageErrorProps {
  /** Optional heading — defaults to "Something went wrong" */
  title?: string;
  /**
   * Body copy. Defaults to the standard fallback sentence.
   * Ignored when the component is mounted by Next.js via error.tsx
   * (use `contextual` for the machine-generated detail line in that mode).
   */
  message?: string;
  /**
   * Short, page-specific detail line rendered beneath the main message.
   * e.g. "Failed to load suspects" — good for contextual error.tsx files.
   */
  contextual?: string;
  /** Callback wired to the retry/try-again button */
  retry?: () => void;
}

/** Shape Next.js App Router passes to error.tsx components */
interface NextErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

type Props = PageErrorProps | NextErrorProps;

function isNextErrorProps(p: Props): p is NextErrorProps {
  return "error" in p && "reset" in p;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function PageError(props: Props) {
  const isNext = isNextErrorProps(props);

  const error  = isNext ? props.error       : undefined;
  const reset  = isNext ? props.reset       : (props as PageErrorProps).retry;
  const title  = isNext ? undefined         : (props as PageErrorProps).title;
  const msg    = isNext ? undefined         : (props as PageErrorProps).message;
  const ctx    = isNext ? undefined         : (props as PageErrorProps).contextual;

  useEffect(() => {
    if (error) {
      // eslint-disable-next-line no-console
      console.error("Page error:", error);
    }
  }, [error]);

  const headline    = title ?? "Something went wrong";
  const bodyMessage = msg ?? "We hit an unexpected error rendering this page. Try again, or contact support if it keeps happening.";
  const contextLine = ctx ?? (error?.digest ? `Error ID: ${error.digest}` : undefined);

  return (
    <div
      className="flex flex-col items-center justify-center min-h-[60vh] px-6 text-center"
      role="alert"
      aria-live="assertive"
    >
      {/* Icon */}
      <div
        className="mb-4 flex items-center justify-center w-14 h-14 rounded-full bg-destructive/10"
        aria-hidden="true"
      >
        <AlertTriangle className="text-destructive" size={28} strokeWidth={1.75} />
      </div>

      {/* Headline */}
      <h1 className="text-2xl font-bold text-foreground mb-3">{headline}</h1>

      {/* Body */}
      <p className="text-sm text-muted-foreground mb-1 max-w-md leading-relaxed">
        {bodyMessage}
      </p>

      {/* Contextual detail line */}
      {contextLine && (
        <p className="text-xs text-muted-foreground/70 mb-6 max-w-md">
          {contextLine}
        </p>
      )}

      {/* Spacer when no contextual line */}
      {!contextLine && <div className="mb-5" />}

      {/* Retry button */}
      {reset && (
        <button
          type="button"
          onClick={reset}
          className="inline-flex items-center justify-center rounded-lg bg-primary px-6 py-2.5 text-sm font-semibold text-primary-foreground transition-all duration-150 hover:brightness-105 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50"
        >
          Try again
        </button>
      )}
    </div>
  );
}
