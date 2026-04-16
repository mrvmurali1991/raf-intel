"use client";

/**
 * AIHealthBanner
 * --------------
 * Amber warning banner shown when Gemini AI analysis is unavailable
 * (invalid API key, rate-limited, network error, etc.).
 *
 * The banner polls `GET /api/health/ai` every 5 minutes via `useAIHealth()`
 * and renders only when `ok === false`. Dismissal is persisted per browser
 * session (sessionStorage) so it does not re-appear on every navigation,
 * but does re-surface after a fresh login / tab restart.
 *
 * Styling intentionally mirrors `EmrDeactivatedBanner` for visual parity.
 */

import { useEffect, useState } from "react";
import { AlertTriangle, X } from "lucide-react";
import { useAIHealth } from "@/lib/useAIHealth";

const DISMISS_KEY = "ai-health-banner-dismissed";

export function AIHealthBanner() {
  const { data } = useAIHealth();
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    setDismissed(sessionStorage.getItem(DISMISS_KEY) === "1");
  }, []);

  if (!data || data.ok || dismissed) return null;

  const handleDismiss = () => {
    try {
      sessionStorage.setItem(DISMISS_KEY, "1");
    } catch {
      /* sessionStorage may be unavailable in private mode — ignore */
    }
    setDismissed(true);
  };

  return (
    <div
      role="alert"
      className="mb-4 w-full rounded-md border border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/60 dark:text-amber-200"
    >
      <div className="flex items-start justify-between gap-3 px-4 py-2.5 text-sm">
        <div className="flex items-start gap-2 min-w-0">
          <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0" aria-hidden="true" />
          <span className="min-w-0">
            <strong>AI Analysis unavailable</strong> — MEAT evidence and NLP
            suspects will not populate. Contact admin.
            {data.reason && (
              <span
                className="ml-1 text-xs opacity-80"
                title={data.reason}
              >
                ({data.reason.length > 80 ? `${data.reason.slice(0, 80)}…` : data.reason})
              </span>
            )}
          </span>
        </div>
        <button
          type="button"
          onClick={handleDismiss}
          aria-label="Dismiss AI health warning"
          className="flex-shrink-0 rounded p-1 text-amber-900/70 transition hover:bg-amber-100 hover:text-amber-900 dark:text-amber-200/70 dark:hover:bg-amber-900/40 dark:hover:text-amber-100"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}

export default AIHealthBanner;
