"use client";

/**
 * TenantAccessBanner
 *
 * A small read-only pill shown in the top bar that surfaces the logged-in
 * user's data scope at a glance:
 *
 *   [Building] Tenant <name>  ·  <N> patients
 *
 * On narrow viewports (mobile) the tenant name is hidden and only the
 * patient count + icon are shown.
 *
 * When the `degraded` flag is true (backend health check returns a warning)
 * an amber alert dot is rendered next to the pill.
 *
 * The component is wrapped in an internal error boundary so a failed fetch
 * never crashes the layout.
 */

import { Component, type ReactNode } from "react";
import { Building2, Users, AlertTriangle } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/contexts/auth-context";
import { getDashboardStats } from "@/lib/api";
import api from "@/lib/api";

// ─── Design tokens (inline — mirrors colors in healthcare-ui.tsx) ─────────────
// Intentionally NOT importing from healthcare-ui to keep this component
// self-contained and free of SSR side-effects from the "use client" chain.

const tok = {
  slate200: "#f1f5f9",
  slate600: "#475569",
  slate400: "#94A3B8",
  amber500: "#d97706",
  amber100: "#fef3c7",
  amber300: "#fcd34d",
  white: "#FFFFFF",
} as const;

// ─── API shape ────────────────────────────────────────────────────────────────

interface TenantMeResponse {
  tenant_id?: string;
  tenant_name?: string;
  role?: string;
  permissions?: string[];
  degraded?: boolean;
}

// ─── Internal error boundary ─────────────────────────────────────────────────

interface EBState { hasError: boolean }

class BannerErrorBoundary extends Component<{ children: ReactNode }, EBState> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): EBState {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) return null;
    return this.props.children;
  }
}

// ─── Inner pill (rendered inside the error boundary) ─────────────────────────

function TenantAccessPill() {
  const { user } = useAuth();

  // Fetch /api/auth/me for tenant_name and degraded flag.
  // We use a short staleTime so the pill reflects tenant switches promptly.
  const { data: meData } = useQuery<TenantMeResponse>({
    queryKey: ["auth-me-tenant"],
    queryFn: async () => {
      const { data } = await api.get<TenantMeResponse>("/api/auth/me");
      return data;
    },
    enabled: !!user,
    staleTime: 30_000,
    retry: false,
    // Don't throw — silently degrade to user object fallback
    throwOnError: false,
  });

  // Fetch patient count from dashboard stats (already cached by other queries)
  const { data: stats } = useQuery({
    queryKey: ["dashboard-stats"],
    queryFn: getDashboardStats,
    enabled: !!user,
    staleTime: 60_000,
    retry: false,
    throwOnError: false,
  });

  // Derive display values with graceful fallbacks
  const tenantName =
    meData?.tenant_name ??
    (user?.tenant_id ? `Org ${user.tenant_id}` : null);

  const patientCount = stats?.total_patients;
  const degraded = meData?.degraded === true;

  // Don't render until we have at least the user object
  if (!user) return null;
  // Hide entirely if we have nothing meaningful to show
  if (!tenantName && patientCount === undefined) return null;

  const countLabel =
    patientCount === undefined
      ? null
      : patientCount.toLocaleString("en-US");

  return (
    <div
      role="status"
      aria-label={[
        tenantName ? `Tenant: ${tenantName}` : null,
        countLabel ? `${countLabel} patients` : null,
        degraded ? "Warning: system degraded" : null,
      ]
        .filter(Boolean)
        .join(", ")}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "5px 10px",
        borderRadius: 999,
        border: `1px solid ${degraded ? tok.amber300 : tok.slate200}`,
        background: degraded ? tok.amber100 : tok.white,
        fontSize: 12,
        fontWeight: 500,
        color: tok.slate600,
        whiteSpace: "nowrap",
        userSelect: "none",
        lineHeight: 1,
      }}
    >
      {/* Warning indicator */}
      {degraded && (
        <AlertTriangle
          aria-hidden="true"
          size={13}
          style={{ color: tok.amber500, flexShrink: 0 }}
        />
      )}

      {/* Building icon */}
      {!degraded && (
        <Building2
          aria-hidden="true"
          size={13}
          style={{ color: tok.slate400, flexShrink: 0 }}
        />
      )}

      {/* Tenant name — hidden on mobile via CSS (handled by parent) */}
      {tenantName && (
        <span
          className="tenant-access-banner__name"
          style={{
            maxWidth: 140,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {tenantName}
        </span>
      )}

      {/* Divider + patient count */}
      {tenantName && countLabel && (
        <span aria-hidden="true" style={{ opacity: 0.35, fontSize: 11 }}>·</span>
      )}

      {countLabel !== null && (
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 3,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          <Users aria-hidden="true" size={11} style={{ color: tok.slate400, flexShrink: 0 }} />
          {countLabel}
        </span>
      )}
    </div>
  );
}

// ─── Public export (wrapped in error boundary) ────────────────────────────────

/**
 * Usage in auth-layout.tsx top bar:
 *
 *   <TenantAccessBanner />
 *
 * Renders nothing when:
 *   - User is not authenticated
 *   - Both tenant name and patient count are unavailable
 *   - An unexpected render error occurs (boundary catches it silently)
 */
export function TenantAccessBanner() {
  return (
    <BannerErrorBoundary>
      <TenantAccessPill />
    </BannerErrorBoundary>
  );
}

export default TenantAccessBanner;
