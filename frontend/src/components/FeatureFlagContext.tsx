"use client";

/**
 * FeatureFlagContext — provider + hooks for the per-user UI feature toggles.
 *
 * Lifecycle
 * ---------
 *   - On mount, fetches `/api/feature-flags` ONCE.
 *   - Exposes:
 *       useFeatureFlag(key)        -> { enabled, loading, exists, flag }
 *       useSetFeatureFlag()        -> (key, enabled) => Promise<void>
 *       useResetFeatureFlags()     -> () => Promise<void>
 *       useFeatureFlagsAll()       -> the full state, used by the settings panel.
 *
 * Graceful degradation
 * --------------------
 *   - While loading: ``useFeatureFlag`` returns ``loading=true``.
 *   - Unknown flag key: defaults to enabled=true (so other agents can wrap
 *     UI with a flag before this PR is merged without breaking the page).
 *   - Network failure: defaults to enabled=true for every key, with an
 *     internal ``error`` field consumers can choose to surface.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  getFeatureFlags,
  setFeatureFlag as apiSetFeatureFlag,
  resetFeatureFlags as apiResetFeatureFlags,
  type FeatureFlagItem,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Context shape
// ---------------------------------------------------------------------------

interface FeatureFlagState {
  /** flagKey -> resolved metadata (incl. enabled). */
  flags: Record<string, FeatureFlagItem>;
  /** Insertion order from the backend — preserved for stable rendering. */
  orderedKeys: string[];
  /** True until the first /api/feature-flags response (success or fail). */
  loading: boolean;
  /** Set when the initial fetch failed; consumers fall back to enabled=true. */
  error: string | null;
}

interface FeatureFlagContextValue extends FeatureFlagState {
  refetch: () => Promise<void>;
  setFlag: (key: string, enabled: boolean) => Promise<void>;
  resetAll: () => Promise<void>;
}

const FeatureFlagContext = createContext<FeatureFlagContextValue | null>(null);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

export function FeatureFlagProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<FeatureFlagState>({
    flags: {},
    orderedKeys: [],
    loading: true,
    error: null,
  });

  const refetch = useCallback(async () => {
    try {
      const resp = await getFeatureFlags();
      const items: FeatureFlagItem[] = resp.flags ?? [];
      const flags: Record<string, FeatureFlagItem> = {};
      const orderedKeys: string[] = [];
      for (const item of items) {
        flags[item.key] = item;
        orderedKeys.push(item.key);
      }
      setState({ flags, orderedKeys, loading: false, error: null });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load feature flags";
      setState((s) => ({ ...s, loading: false, error: message }));
    }
  }, []);

  // Fetch once on mount.
  useEffect(() => {
    void refetch();
  }, [refetch]);

  const setFlag = useCallback(
    async (key: string, enabled: boolean) => {
      // Optimistic update first; revert on failure.
      const previous = state.flags[key];
      setState((s) => ({
        ...s,
        flags: {
          ...s.flags,
          [key]: previous
            ? { ...previous, enabled }
            : {
                key,
                name: key,
                description: "",
                category: "Misc",
                default_enabled: true,
                scope: "user",
                enabled,
              },
        },
      }));

      try {
        const resp = await apiSetFeatureFlag(key, enabled) as { flag?: FeatureFlagItem };
        const updated: FeatureFlagItem | undefined = resp?.flag;
        if (updated) {
          setState((s) => ({
            ...s,
            flags: { ...s.flags, [updated.key]: updated },
          }));
        }
      } catch (err) {
        // Roll back on failure.
        if (previous) {
          setState((s) => ({
            ...s,
            flags: { ...s.flags, [key]: previous },
          }));
        }
        throw err;
      }
    },
    [state.flags],
  );

  const resetAll = useCallback(async () => {
    await apiResetFeatureFlags();
    await refetch();
  }, [refetch]);

  const value = useMemo<FeatureFlagContextValue>(
    () => ({ ...state, refetch, setFlag, resetAll }),
    [state, refetch, setFlag, resetAll],
  );

  return (
    <FeatureFlagContext.Provider value={value}>
      {children}
    </FeatureFlagContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

function useFeatureFlagContext(): FeatureFlagContextValue {
  const ctx = useContext(FeatureFlagContext);
  if (!ctx) {
    // Provider not mounted (e.g. in a test or a page rendered outside the
    // app shell).  Return a permissive stub so calls never throw.
    return {
      flags: {},
      orderedKeys: [],
      loading: false,
      error: null,
      refetch: async () => {},
      setFlag: async () => {},
      resetAll: async () => {},
    };
  }
  return ctx;
}

interface UseFeatureFlagResult {
  /** Resolved enabled state. Defaults to true when unknown / loading-error. */
  enabled: boolean;
  /** True only on the very first paint, before the flags fetch resolves. */
  loading: boolean;
  /** True iff the backend registry knows about this key. */
  exists: boolean;
  /** Full metadata when the flag is known; ``undefined`` otherwise. */
  flag: FeatureFlagItem | undefined;
}

/**
 * Read a single feature flag by key.
 *
 * Defaults to ``enabled=true`` whenever the flag is unknown or the initial
 * fetch errored — this keeps the UI usable when other agents reference flags
 * before this PR has been merged into their branch.
 */
export function useFeatureFlag(key: string): UseFeatureFlagResult {
  const ctx = useFeatureFlagContext();
  const flag = ctx.flags[key];

  if (ctx.loading) {
    return { enabled: true, loading: true, exists: false, flag: undefined };
  }
  if (flag) {
    return { enabled: !!flag.enabled, loading: false, exists: true, flag };
  }
  // Unknown flag — graceful fallback.
  return { enabled: true, loading: false, exists: false, flag: undefined };
}

/** Convenience: only the resolved boolean, no metadata. */
export function useIsFeatureEnabled(key: string): boolean {
  return useFeatureFlag(key).enabled;
}

/** Imperatively flip a flag.  Throws on network failure (after rollback). */
export function useSetFeatureFlag() {
  const ctx = useFeatureFlagContext();
  return ctx.setFlag;
}

/** Wipe every override for the current user. */
export function useResetFeatureFlags() {
  const ctx = useFeatureFlagContext();
  return ctx.resetAll;
}

/**
 * The full state — used by the settings panel that lists every flag.
 * Most consumers should prefer ``useFeatureFlag`` instead.
 */
export function useFeatureFlagsAll() {
  const ctx = useFeatureFlagContext();
  return {
    flags: ctx.flags,
    orderedKeys: ctx.orderedKeys,
    loading: ctx.loading,
    error: ctx.error,
    refetch: ctx.refetch,
    setFlag: ctx.setFlag,
    resetAll: ctx.resetAll,
  };
}
