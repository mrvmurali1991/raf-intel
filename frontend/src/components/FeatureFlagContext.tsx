"use client";

/**
 * FeatureFlagContext — provider + hooks for the per-user UI feature toggles.
 *
 * Lifecycle
 * ---------
 *   - Fetches `/api/feature-flags` once the user is authenticated.
 *   - The `isAuthenticated` prop gates the fetch so it never fires on cold-load
 *     before the auth context has exchanged the refresh token for an access token.
 *     Without this guard every cold page-load produces a 401, because the
 *     FeatureFlagProvider mounts (and immediately calls `refetch`) before
 *     AuthProvider.init() has set the Bearer token on the axios instance.
 *   - When `isAuthenticated` transitions false → true the fetch fires automatically
 *     (handles login) and when it transitions true → false the flag cache is wiped
 *     (handles logout / session expiry).
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
import { useAuth } from "@/contexts/auth-context";

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

interface FeatureFlagProviderProps {
  children: ReactNode;
  /**
   * Pass the resolved authentication state from AuthContext.
   * The flags fetch is held until this becomes `true`, preventing the
   * cold-load 401 that occurs when the provider mounts before AuthProvider
   * has restored the session token.
   * When this transitions back to `false` (logout / session expiry) the
   * local flag cache is wiped so stale per-user flags don't leak across
   * accounts.
   */
  isAuthenticated: boolean;
}

export function FeatureFlagProvider({ children, isAuthenticated }: FeatureFlagProviderProps) {
  const [state, setState] = useState<FeatureFlagState>({
    flags: {},
    orderedKeys: [],
    // Start as NOT loading when unauthenticated — we know we can't fetch.
    // Flip to `true` only once we actually kick off the authenticated fetch.
    loading: false,
    error: null,
  });

  const refetch = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
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
      // 401/403 just mean "user not signed in yet" — fall back silently to
      // registry defaults rather than surfacing a scary error in the UI.
      const status = (err as { response?: { status?: number } } | undefined)?.response?.status;
      if (status === 401 || status === 403) {
        setState((s) => ({ ...s, loading: false, error: null }));
        return;
      }
      const message = err instanceof Error ? err.message : "Failed to load feature flags";
      setState((s) => ({ ...s, loading: false, error: message }));
    }
  }, []);

  // Fetch flags whenever the user authenticates (false → true transition).
  // Wipe the cache when the user logs out (true → false transition) so stale
  // per-user overrides don't bleed across accounts on the same browser tab.
  useEffect(() => {
    if (isAuthenticated) {
      void refetch();
    } else {
      // User logged out or session expired — clear cached flags.
      setState({ flags: {}, orderedKeys: [], loading: false, error: null });
    }
  }, [isAuthenticated, refetch]);

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

// ---------------------------------------------------------------------------
// AuthedFeatureFlagProvider — convenience wrapper for use inside AuthProvider.
//
// Reads `isAuthenticated` from the nearest AuthContext so the parent (layout.tsx)
// does not need to wire it through manually.  This must be rendered as a
// descendant of <AuthProvider>.
// ---------------------------------------------------------------------------

/**
 * Drop-in replacement for `<FeatureFlagProvider isAuthenticated={...}>` that
 * reads auth state from AuthContext automatically.
 *
 * Usage (layout.tsx):
 *   <AuthProvider>
 *     <AuthedFeatureFlagProvider>
 *       ...
 *     </AuthedFeatureFlagProvider>
 *   </AuthProvider>
 */
export function AuthedFeatureFlagProvider({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  return (
    <FeatureFlagProvider isAuthenticated={isAuthenticated}>
      {children}
    </FeatureFlagProvider>
  );
}
