"use client";

/**
 * Slide-out settings panel for the /providers page feature toggles.
 *
 * Renders a backdrop + right-edge drawer.  Inside the drawer:
 *   - one section per category (Benchmarks, Revenue, Trends, etc.)
 *   - one row per flag with name, description, and toggle switch
 *   - "Reset to defaults" button at the bottom
 *
 * No third-party deps — pure Tailwind + a couple of lucide icons that the
 * codebase already pulls in via Sidebar/Toast.
 */

import { useEffect, useMemo, useState } from "react";
import { Loader2, RotateCcw, X } from "lucide-react";

import {
  useFeatureFlagsAll,
} from "@/components/FeatureFlagContext";
import type { FeatureFlagItem } from "@/lib/api";

interface ProviderFeaturesSettingsProps {
  open: boolean;
  onClose: () => void;
}

export function ProviderFeaturesSettings({
  open,
  onClose,
}: ProviderFeaturesSettingsProps) {
  const { flags, orderedKeys, loading, error, setFlag, resetAll } = useFeatureFlagsAll();

  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  // Lock body scroll while open.
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  // Close on Escape key.
  useEffect(() => {
    if (!open) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [open, onClose]);

  // Group flags by category in stable backend order.
  const grouped = useMemo(() => {
    const out: Record<string, FeatureFlagItem[]> = {};
    for (const key of orderedKeys) {
      const flag = flags[key];
      if (!flag) continue;
      const cat = flag.category || "Other";
      if (!out[cat]) out[cat] = [];
      out[cat].push(flag);
    }
    return out;
  }, [flags, orderedKeys]);

  async function handleToggle(key: string, next: boolean) {
    setSavingKey(key);
    setLocalError(null);
    try {
      await setFlag(key, next);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "Failed to update flag");
    } finally {
      setSavingKey(null);
    }
  }

  async function handleReset() {
    setResetting(true);
    setLocalError(null);
    try {
      await resetAll();
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "Failed to reset flags");
    } finally {
      setResetting(false);
    }
  }

  return (
    <>
      {/* Backdrop */}
      <div
        aria-hidden={!open}
        onClick={onClose}
        className={`fixed inset-0 z-40 bg-black/40 transition-opacity duration-200 ${
          open ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
      />

      {/* Drawer */}
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Provider page feature settings"
        className={`fixed right-0 top-0 z-50 flex h-full w-full max-w-md flex-col bg-white shadow-xl transition-transform duration-300 dark:bg-slate-900 ${
          open ? "translate-x-0" : "translate-x-full"
        }`}
      >
        {/* Header */}
        <header className="flex items-center justify-between border-b border-slate-200 px-5 py-4 dark:border-slate-800">
          <div>
            <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">
              Page features
            </h2>
            <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
              Toggle which sections appear on the provider page.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close settings panel"
            className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-700 dark:text-slate-400 dark:hover:bg-slate-800"
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {loading ? (
            <div className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400">
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading flags…
            </div>
          ) : error ? (
            <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200">
              Could not load flags: {error}.  Showing defaults.
            </div>
          ) : (
            <div className="flex flex-col gap-6">
              {Object.entries(grouped).map(([category, items]) => (
                <section key={category}>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
                    {category}
                  </h3>
                  <ul className="flex flex-col gap-2">
                    {items.map((flag) => (
                      <li
                        key={flag.key}
                        className="flex items-start justify-between gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-800/50"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <p className="truncate text-sm font-medium text-slate-900 dark:text-slate-100">
                              {flag.name}
                            </p>
                            {flag.default_enabled === false && (
                              <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-600 dark:bg-slate-700 dark:text-slate-300">
                                Off by default
                              </span>
                            )}
                          </div>
                          <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
                            {flag.description}
                          </p>
                          <p className="mt-1 font-mono text-[10px] text-slate-400 dark:text-slate-500">
                            {flag.key}
                          </p>
                        </div>
                        <ToggleSwitch
                          enabled={!!flag.enabled}
                          disabled={savingKey === flag.key}
                          onChange={(next) => handleToggle(flag.key, next)}
                          ariaLabel={`Toggle ${flag.name}`}
                        />
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>
          )}

          {localError && (
            <div className="mt-4 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800 dark:border-red-800 dark:bg-red-950/40 dark:text-red-200">
              {localError}
            </div>
          )}
        </div>

        {/* Footer */}
        <footer className="border-t border-slate-200 px-5 py-3 dark:border-slate-800">
          <button
            type="button"
            onClick={handleReset}
            disabled={resetting || loading}
            className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
          >
            {resetting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RotateCcw className="h-3.5 w-3.5" />
            )}
            Reset to defaults
          </button>
        </footer>
      </aside>
    </>
  );
}

// ---------------------------------------------------------------------------
// Toggle switch — pure Tailwind, no extra deps
// ---------------------------------------------------------------------------

interface ToggleSwitchProps {
  enabled: boolean;
  disabled?: boolean;
  onChange: (next: boolean) => void;
  ariaLabel: string;
}

function ToggleSwitch({ enabled, disabled, onChange, ariaLabel }: ToggleSwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={() => onChange(!enabled)}
      className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-teal-600 focus-visible:ring-offset-2 ${
        enabled
          ? "bg-teal-700"
          : "bg-slate-300 dark:bg-slate-600"
      }`}
    >
      <span
        aria-hidden="true"
        className={`inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition-transform ${
          enabled ? "translate-x-5" : "translate-x-0.5"
        }`}
      />
    </button>
  );
}

export default ProviderFeaturesSettings;
