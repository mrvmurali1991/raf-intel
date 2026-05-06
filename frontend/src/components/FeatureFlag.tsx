"use client";

/**
 * <FeatureFlag flagKey="..."> — declarative gate for UI subtrees.
 *
 *   <FeatureFlag flagKey="provider_yoy_trend">
 *     <YoyTrendChart />
 *   </FeatureFlag>
 *
 * Behaviour
 * ---------
 *   - While the flags context is loading: renders ``fallback`` (default null).
 *     This avoids a "flash of disabled feature" on first paint.
 *   - Enabled: renders ``children``.
 *   - Disabled: renders ``fallback``.
 *   - Unknown flag key: renders ``children`` (graceful fallback so other agents
 *     can wrap UI before this PR is merged into their branch).
 */

import type { ReactNode } from "react";

import { useFeatureFlag } from "@/components/FeatureFlagContext";

interface FeatureFlagProps {
  flagKey: string;
  children: ReactNode;
  /** What to render while loading or when the flag is disabled. */
  fallback?: ReactNode;
  /**
   * If true, render ``children`` only when the flag is explicitly DISABLED.
   * Useful for "show legacy UI when new feature is off" cases.
   */
  invert?: boolean;
}

export function FeatureFlag({
  flagKey,
  children,
  fallback = null,
  invert = false,
}: FeatureFlagProps) {
  const { enabled, loading } = useFeatureFlag(flagKey);

  // Render nothing on the very first paint to avoid a flicker.
  if (loading) {
    return <>{fallback}</>;
  }

  const shouldRender = invert ? !enabled : enabled;
  return <>{shouldRender ? children : fallback}</>;
}

export default FeatureFlag;
