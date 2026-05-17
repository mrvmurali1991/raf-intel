"use client";

/**
 * TenantBrandingProvider — runs the ``useTenantBranding`` hook once on
 * app mount so the CSS custom properties (``--brand-primary``,
 * ``--brand-secondary``, ``--logo-text``) are set on ``:root`` before any
 * children render.
 *
 * Children render immediately with the defaults from globals.css.
 * ``useTenantBranding`` swaps the CSS custom properties in place once the
 * fetch resolves, so the eventual repaint is a single colour shift rather
 * than a blank screen. Previously this gated the entire app subtree on
 * the branding fetch — a 200–400 ms full-screen white flash on every page
 * load, longer on degraded networks.
 */

import type { ReactNode } from "react";
import { useTenantBranding } from "@/lib/useTenantBranding";

interface Props {
  children: ReactNode;
}

export function TenantBrandingProvider({ children }: Props) {
  // Call the hook for its side-effect (applies CSS vars to :root). We
  // intentionally do NOT block on `ready` — defaults paint instantly,
  // tenant colours apply transparently once the fetch lands.
  useTenantBranding();
  return <>{children}</>;
}

export default TenantBrandingProvider;
