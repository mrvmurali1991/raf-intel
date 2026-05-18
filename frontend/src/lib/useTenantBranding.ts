"use client";

/**
 * useTenantBranding — fetch the current tenant's branding row and apply it
 * to ``:root`` as CSS custom properties.
 *
 * Backed by ``GET /api/tenant/branding``.  The response carries the colors
 * and logo text the tenant has configured (or system defaults when the row
 * is missing) so any component that reads ``var(--brand-primary)``,
 * ``var(--brand-secondary)`` or ``var(--logo-text)`` automatically re-skins.
 *
 * Usage::
 *
 *     const { ready, branding } = useTenantBranding();
 *     if (!ready) return null;
 *     return <span>{branding.logo_text}</span>;
 *
 * The hook is gated on authentication — without a session token the
 * endpoint would 401 and we'd just keep the globals.css defaults.
 */

import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { useAuth } from "@/contexts/auth-context";

export interface TenantBranding {
  tenant_id: string;
  display_name: string;
  brand_primary: string;
  brand_secondary: string;
  logo_text: string;
}

/** Defaults must match the ``:root`` block in ``globals.css``.
 *  For the Acme Health demo tenant these are the canonical display values.
 *  Any production tenant will override these via GET /api/tenant/branding. */
const DEFAULT_BRANDING: TenantBranding = {
  tenant_id: "",
  display_name: "Acme Health",
  brand_primary: "#0F766E",
  brand_secondary: "#134E4A",
  logo_text: "Acme Health",
};

function applyBrandingToRoot(b: TenantBranding): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.style.setProperty("--brand-primary", b.brand_primary);
  root.style.setProperty("--brand-secondary", b.brand_secondary);
  // CSS string values must be quoted when used via ``content:`` etc.
  root.style.setProperty("--logo-text", `"${b.logo_text}"`);
}

export function useTenantBranding() {
  const { isAuthenticated } = useAuth();

  const query = useQuery<TenantBranding>({
    queryKey: ["tenant-branding"],
    queryFn: async () => {
      const res = await api.get<TenantBranding>("/api/tenant/branding");
      return res.data;
    },
    enabled: isAuthenticated,
    // Branding rarely changes; cache aggressively to avoid re-fetching on
    // every page nav.
    staleTime: 10 * 60 * 1000,
    retry: 1,
  });

  // Apply CSS variables whenever the branding payload changes.  Falls back
  // to defaults when the query hasn't resolved yet so the very first paint
  // already has values bound (this matches the values in globals.css).
  useEffect(() => {
    const b = query.data ?? DEFAULT_BRANDING;
    applyBrandingToRoot(b);
  }, [query.data]);

  return {
    branding: query.data ?? DEFAULT_BRANDING,
    /** True once the hook has either received a response or skipped (unauthenticated). */
    ready: !isAuthenticated || query.isSuccess || query.isError,
    isLoading: query.isLoading,
    error: query.error,
  };
}

export default useTenantBranding;
