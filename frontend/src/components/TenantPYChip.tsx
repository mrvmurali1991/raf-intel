"use client";

/**
 * TenantPYChip
 *
 * Top-bar pill showing:
 *   Line 1: current tenant display name
 *   Line 2: payment year (PY YYYY)
 *
 * - Single-tenant users see a static chip (no dropdown).
 * - Multi-tenant admins can click to open a popover with a tenant list and
 *   a payment-year radio selector.
 * - Shows a subtle env badge when NEXT_PUBLIC_APP_ENV is "staging" or "dev".
 */

import { useState, useRef, useEffect } from "react";
import { Building2, ChevronDown, Check } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/contexts/auth-context";
import { usePaymentYear, PAYMENT_YEARS } from "@/contexts/payment-year-context";
import api from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TenantInfo {
  tenant_id: string;
  name: string;
  patient_count?: number;
}

// ---------------------------------------------------------------------------
// Env badge helpers
// ---------------------------------------------------------------------------

const APP_ENV =
  (process.env.NEXT_PUBLIC_APP_ENV ?? "production").toLowerCase();
const SHOW_ENV_BADGE = APP_ENV === "staging" || APP_ENV === "dev" || APP_ENV === "development";
const ENV_LABEL = APP_ENV === "staging" ? "STAGING" : "DEV";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TenantPYChip() {
  const { user, switchTenant } = useAuth();
  const { paymentYear, setPaymentYear } = usePaymentYear();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const chipRef = useRef<HTMLDivElement>(null);

  // Fetch tenant list (admin-only; 404 degrades gracefully)
  const { data } = useQuery({
    queryKey: ["tenants"],
    queryFn: async () => {
      try {
        const res = await api.get<{ tenants: TenantInfo[]; current_tenant_id: string }>(
          "/api/auth/tenants"
        );
        return res.data;
      } catch (err: unknown) {
        const status = (err as { response?: { status?: number } })?.response?.status;
        if (status === 404) return { tenants: [] as TenantInfo[], current_tenant_id: "" };
        throw err;
      }
    },
    enabled: !!user,
    staleTime: 30_000,
    retry: false,
  });

  const tenants = data?.tenants ?? [];
  const currentTid = user?.tenant_id ?? "";
  const currentTenant = tenants.find((t) => t.tenant_id === currentTid);
  // Fall back to tenant_id if name is not available in the list yet.
  const tenantDisplayName = currentTenant?.name ?? (currentTid ? `Org ${currentTid}` : "My Organization");
  const isMultiTenant = tenants.length >= 2;
  const isInteractive = isMultiTenant;

  // Close popover on outside click
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (chipRef.current && !chipRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open]);

  async function handleSwitchTenant(tid: string) {
    if (tid === currentTid || switching) return;
    setSwitching(true);
    try {
      await switchTenant(tid);
      queryClient.clear();
      window.location.reload();
    } catch {
      setSwitching(false);
    }
  }

  return (
    <div ref={chipRef} style={{ position: "relative", display: "inline-flex" }}>
      {/* ------------------------------------------------------------------ */}
      {/* Chip button                                                          */}
      {/* ------------------------------------------------------------------ */}
      <button
        onClick={() => isInteractive && setOpen((v) => !v)}
        aria-label={`Tenant and payment year selector. Current tenant: ${tenantDisplayName}, Payment year: PY ${paymentYear}${isInteractive ? ". Click to switch." : ""}`}
        aria-haspopup={isInteractive ? "dialog" : undefined}
        aria-expanded={isInteractive ? open : undefined}
        disabled={!isInteractive}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          padding: "5px 10px 5px 8px",
          borderRadius: 999,
          border: "1px solid var(--border, rgba(148,163,184,0.35))",
          background: "var(--card, rgba(255,255,255,0.07))",
          cursor: isInteractive ? "pointer" : "default",
          // Use CSS custom properties so dark mode (applied on <html>) is respected.
          color: "var(--foreground)",
          lineHeight: 1,
          transition: "background 150ms, border-color 150ms",
        }}
        onMouseEnter={(e) => {
          if (isInteractive)
            (e.currentTarget as HTMLButtonElement).style.borderColor =
              "var(--ring, rgba(148,163,184,0.6))";
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLButtonElement).style.borderColor =
            "var(--border, rgba(148,163,184,0.35))";
        }}
      >
        <Building2
          aria-hidden="true"
          style={{ width: 13, height: 13, opacity: 0.6, flexShrink: 0 }}
        />

        {/* Two-line content */}
        <span
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "flex-start",
            minWidth: 0,
            maxWidth: 160,
          }}
        >
          <span
            style={{
              fontSize: 12,
              fontWeight: 600,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              maxWidth: "100%",
              lineHeight: 1.3,
            }}
          >
            {tenantDisplayName}
          </span>
          <span
            style={{
              fontSize: 10,
              fontWeight: 500,
              opacity: 0.6,
              letterSpacing: "0.04em",
              lineHeight: 1.3,
            }}
          >
            PY {paymentYear}
          </span>
        </span>

        {/* Env badge */}
        {SHOW_ENV_BADGE && (
          <span
            aria-label={`Environment: ${ENV_LABEL}`}
            style={{
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: "0.06em",
              padding: "1px 5px",
              borderRadius: 4,
              background: APP_ENV === "staging" ? "rgba(245,158,11,0.15)" : "rgba(59,130,246,0.15)",
              color: APP_ENV === "staging" ? "#d97706" : "#2563eb",
              border: `1px solid ${APP_ENV === "staging" ? "rgba(245,158,11,0.3)" : "rgba(59,130,246,0.3)"}`,
              flexShrink: 0,
            }}
          >
            {ENV_LABEL}
          </span>
        )}

        {isInteractive && (
          <ChevronDown
            aria-hidden="true"
            style={{
              width: 12,
              height: 12,
              opacity: 0.5,
              flexShrink: 0,
              transform: open ? "rotate(180deg)" : "rotate(0deg)",
              transition: "transform 150ms",
            }}
          />
        )}
      </button>

      {/* ------------------------------------------------------------------ */}
      {/* Popover                                                              */}
      {/* ------------------------------------------------------------------ */}
      {open && (
        <div
          role="dialog"
          aria-label="Tenant and payment year selector"
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            right: 0,
            zIndex: 100,
            minWidth: 220,
            borderRadius: 10,
            border: "1px solid var(--border, rgba(148,163,184,0.25))",
            background: "var(--card, #ffffff)",
            boxShadow: "0 8px 24px rgba(0,0,0,0.12)",
            overflow: "hidden",
          }}
        >
          {/* Tenant section */}
          {isMultiTenant && (
            <section aria-label="Switch tenant">
              <div
                style={{
                  padding: "8px 12px 4px",
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  color: "var(--muted-foreground, #64748b)",
                }}
              >
                Tenant
              </div>
              {tenants.map((t) => {
                const active = t.tenant_id === currentTid;
                return (
                  <button
                    key={t.tenant_id}
                    onClick={() => handleSwitchTenant(t.tenant_id)}
                    disabled={active || switching}
                    aria-pressed={active}
                    style={{
                      width: "100%",
                      display: "flex",
                      alignItems: "center",
                      gap: 8,
                      padding: "8px 12px",
                      border: "none",
                      background: active
                        ? "rgba(15,118,110,0.08)"
                        : "transparent",
                      cursor: active ? "default" : "pointer",
                      color: "var(--foreground)",
                      fontSize: 13,
                      fontWeight: active ? 600 : 400,
                      textAlign: "left",
                      transition: "background 120ms",
                    }}
                    onMouseEnter={(e) => {
                      if (!active)
                        (e.currentTarget as HTMLButtonElement).style.background =
                          "var(--accent, rgba(148,163,184,0.1))";
                    }}
                    onMouseLeave={(e) => {
                      if (!active)
                        (e.currentTarget as HTMLButtonElement).style.background =
                          "transparent";
                    }}
                  >
                    <Building2
                      aria-hidden="true"
                      style={{ width: 13, height: 13, opacity: 0.5, flexShrink: 0 }}
                    />
                    <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {t.name}
                    </span>
                    {active && (
                      <Check
                        aria-hidden="true"
                        style={{ width: 13, height: 13, color: "#10b981", flexShrink: 0 }}
                      />
                    )}
                  </button>
                );
              })}
            </section>
          )}

          {/* Divider between sections */}
          {isMultiTenant && (
            <div
              style={{
                height: 1,
                margin: "4px 0",
                background: "var(--border, rgba(148,163,184,0.2))",
              }}
            />
          )}

          {/* Payment Year section */}
          <section aria-label="Select payment year">
            <div
              style={{
                padding: "8px 12px 4px",
                fontSize: 10,
                fontWeight: 700,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: "var(--muted-foreground, #64748b)",
              }}
            >
              Payment Year
            </div>
            <div
              role="radiogroup"
              aria-label="Payment year"
              style={{ padding: "4px 12px 10px", display: "flex", gap: 6 }}
            >
              {PAYMENT_YEARS.map((yr) => {
                const selected = yr === paymentYear;
                return (
                  <button
                    key={yr}
                    role="radio"
                    aria-checked={selected}
                    onClick={() => {
                      setPaymentYear(yr);
                      setOpen(false);
                    }}
                    style={{
                      flex: 1,
                      padding: "6px 0",
                      borderRadius: 6,
                      border: selected
                        ? "1px solid #0f766e"
                        : "1px solid var(--border, rgba(148,163,184,0.3))",
                      background: selected ? "rgba(15,118,110,0.1)" : "transparent",
                      color: selected ? "#0f766e" : "var(--foreground)",
                      fontSize: 12,
                      fontWeight: selected ? 700 : 500,
                      cursor: "pointer",
                      transition: "all 120ms",
                    }}
                    onMouseEnter={(e) => {
                      if (!selected)
                        (e.currentTarget as HTMLButtonElement).style.background =
                          "var(--accent, rgba(148,163,184,0.08))";
                    }}
                    onMouseLeave={(e) => {
                      if (!selected)
                        (e.currentTarget as HTMLButtonElement).style.background =
                          "transparent";
                    }}
                  >
                    PY {yr}
                  </button>
                );
              })}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
