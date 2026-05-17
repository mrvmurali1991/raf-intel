"use client";

/**
 * TenantBrandingProvider — runs the ``useTenantBranding`` hook once on
 * app mount so the CSS custom properties (``--brand-primary``,
 * ``--brand-secondary``, ``--logo-text``) are set on ``:root`` before any
 * children render.
 *
 * For unauthenticated visitors the hook resolves immediately to defaults
 * (the values already declared in globals.css) so login / marketing pages
 * are never blocked behind a network round-trip.
 *
 * For authenticated users we wait for the first fetch to land before
 * rendering ``children`` — that way no widget ever paints with the
 * default colors and then flashes to the tenant colors a tick later.
 */

import type { ReactNode } from "react";
import { useTenantBranding } from "@/lib/useTenantBranding";

interface Props {
  children: ReactNode;
}

export function TenantBrandingProvider({ children }: Props) {
  const { ready } = useTenantBranding();
  if (!ready) return null;
  return <>{children}</>;
}

export default TenantBrandingProvider;
