"use client";

/**
 * FeatureFlag
 * -----------
 * Lightweight client-side feature gate. Lets us roll out new UI surfaces
 * incrementally without forking the codebase.
 *
 * Resolution order (first hit wins):
 *   1. localStorage["ff:<flagKey>"]  — per-user override, useful for QA
 *   2. NEXT_PUBLIC_FF_<FLAGKEY_UPPER_SNAKE>  — env-driven default
 *   3. DEFAULT_FLAGS map (hard-coded in this file)
 *
 * Values "1" / "true" / "on" are truthy; "0" / "false" / "off" disable.
 *
 * Server-rendered first paint always returns `false` — the flag mounts
 * only after hydration so we don't mismatch SSR / CSR markup. This is
 * fine for opt-in surfaces; not suitable for auth gates.
 *
 * Example:
 *   <FeatureFlag flagKey="provider_suspect_hotlist">
 *     <ProviderSuspectHotlist providerId={42} />
 *   </FeatureFlag>
 */
import React from "react";

// ---------------------------------------------------------------------------
// Built-in defaults — keep new surfaces enabled-by-default unless you
// explicitly want a dark-launch.
// ---------------------------------------------------------------------------
const DEFAULT_FLAGS: Record<string, boolean> = {
  provider_suspect_hotlist: true,
};

function envValue(flagKey: string): string | undefined {
  const envName = `NEXT_PUBLIC_FF_${flagKey.toUpperCase()}`;
  // Next.js inlines NEXT_PUBLIC_* at build time, so static access works.
  // We use a dynamic indexer for forward-compat with future flags.
  return (process.env as Record<string, string | undefined>)[envName];
}

function parseBool(v: string | undefined | null): boolean | undefined {
  if (v == null) return undefined;
  const norm = String(v).trim().toLowerCase();
  if (["1", "true", "on", "yes"].includes(norm)) return true;
  if (["0", "false", "off", "no"].includes(norm)) return false;
  return undefined;
}

export function isFeatureEnabled(flagKey: string): boolean {
  // localStorage override (browser only)
  if (typeof window !== "undefined") {
    try {
      const ls = parseBool(window.localStorage.getItem(`ff:${flagKey}`));
      if (ls !== undefined) return ls;
    } catch {
      // localStorage may be unavailable (SSR, sandboxed iframe); ignore.
    }
  }
  const env = parseBool(envValue(flagKey));
  if (env !== undefined) return env;
  return DEFAULT_FLAGS[flagKey] ?? false;
}

export interface FeatureFlagProps {
  flagKey: string;
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

export default function FeatureFlag({ flagKey, children, fallback = null }: FeatureFlagProps) {
  const [hydrated, setHydrated] = React.useState(false);
  React.useEffect(() => setHydrated(true), []);

  if (!hydrated) return <>{fallback}</>;
  return <>{isFeatureEnabled(flagKey) ? children : fallback}</>;
}
