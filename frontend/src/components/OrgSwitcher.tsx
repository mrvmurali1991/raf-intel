"use client";

/**
 * OrgSwitcher
 *
 * Multi-payer / multi-LoB organisation switcher — the Edifecs pattern.
 *
 * A user with access to multiple tenants picks the active one here. The
 * selection is persisted to ``localStorage.active_tenant_id`` and forwarded
 * on every API call as ``X-Active-Tenant`` (see the interceptor in
 * ``lib/api.ts``). After picking, the page reloads so React Query caches
 * scoped to the previous tenant are dropped cleanly.
 *
 * Visibility:
 *   - 0 or 1 accessible tenants → component renders nothing.
 *   - 2+ accessible tenants     → renders a button + dropdown.
 *
 * Data source: the existing auth context's user object exposes
 * ``user.accessible_tenants`` (populated by /api/auth/me).
 */

import { useState, useRef, useEffect, useMemo } from "react";
import { Building2, ChevronDown, Check } from "lucide-react";
import { useAuth, type AccessibleTenant } from "@/contexts/auth-context";
import { ACTIVE_TENANT_STORAGE_KEY } from "@/lib/api";

function readPersistedActiveTenant(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(ACTIVE_TENANT_STORAGE_KEY);
  } catch {
    return null;
  }
}

function persistActiveTenant(id: string) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(ACTIVE_TENANT_STORAGE_KEY, id);
  } catch {
    /* localStorage unavailable — switching is best-effort */
  }
}

export function OrgSwitcher() {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  // The list of tenants we render. Falls back to an empty array so the
  // hook ordering stays stable while the user is loading.
  const tenants: AccessibleTenant[] = useMemo(
    () => user?.accessible_tenants ?? [],
    [user?.accessible_tenants]
  );

  // Pick the active tenant: prefer the persisted localStorage choice, fall
  // back to the user record's tenant_id (canonical assignment), then the
  // first entry in the list. Compute on every render so the chip stays in
  // sync with localStorage updates from other tabs.
  const activeId = useMemo(() => {
    const persisted = readPersistedActiveTenant();
    if (persisted && tenants.some((t) => t.id === persisted)) return persisted;
    if (user?.tenant_id && tenants.some((t) => t.id === user.tenant_id)) {
      return user.tenant_id;
    }
    return tenants[0]?.id ?? null;
  }, [tenants, user?.tenant_id]);

  const activeTenant = tenants.find((t) => t.id === activeId) ?? null;

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
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

  // Single-tenant (or no-tenant) users get no chrome — the dropdown only
  // makes sense when there's something to switch to.
  if (tenants.length < 2 || !activeTenant) return null;

  function handlePick(id: string) {
    if (id === activeId) {
      setOpen(false);
      return;
    }
    persistActiveTenant(id);
    // Hard reload so every React Query cache + in-memory tenant-scoped
    // state is rebuilt cleanly against the new tenant context.
    if (typeof window !== "undefined") {
      window.location.reload();
    }
  }

  return (
    <div
      ref={wrapperRef}
      style={{ position: "relative", display: "inline-flex" }}
      data-testid="org-switcher"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Active organization: ${activeTenant.display_name}. Click to switch organization.`}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          padding: "5px 10px 5px 8px",
          borderRadius: 999,
          border: "1px solid var(--border, rgba(148,163,184,0.35))",
          background: "var(--card, rgba(255,255,255,0.07))",
          cursor: "pointer",
          color: "var(--foreground)",
          lineHeight: 1,
          transition: "background 150ms, border-color 150ms",
        }}
        onMouseEnter={(e) => {
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
        <span
          style={{
            fontSize: 12,
            fontWeight: 600,
            maxWidth: 160,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {activeTenant.display_name}
        </span>
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
      </button>

      {open && (
        <ul
          role="listbox"
          aria-label="Available organizations"
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            right: 0,
            zIndex: 100,
            minWidth: 220,
            margin: 0,
            padding: "4px 0",
            listStyle: "none",
            borderRadius: 10,
            border: "1px solid var(--border, rgba(148,163,184,0.25))",
            background: "var(--card, #ffffff)",
            boxShadow: "0 8px 24px rgba(0,0,0,0.12)",
            overflow: "hidden",
          }}
        >
          <li
            aria-hidden="true"
            style={{
              padding: "8px 12px 4px",
              fontSize: 10,
              fontWeight: 700,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              color: "var(--muted-foreground, #94a3b8)",
            }}
          >
            Switch Organization
          </li>
          {tenants.map((t) => {
            const active = t.id === activeId;
            return (
              <li key={t.id} role="presentation">
                <button
                  type="button"
                  role="option"
                  aria-selected={active}
                  onClick={() => handlePick(t.id)}
                  data-testid={`org-switcher-option-${t.id}`}
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
                    style={{
                      width: 13,
                      height: 13,
                      opacity: 0.5,
                      flexShrink: 0,
                    }}
                  />
                  <span
                    style={{
                      flex: 1,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {t.display_name}
                  </span>
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 600,
                      letterSpacing: "0.04em",
                      textTransform: "uppercase",
                      padding: "2px 6px",
                      borderRadius: 4,
                      background: "rgba(148,163,184,0.15)",
                      color: "var(--muted-foreground, #64748b)",
                      flexShrink: 0,
                    }}
                  >
                    {t.role}
                  </span>
                  {active && (
                    <Check
                      aria-hidden="true"
                      style={{
                        width: 13,
                        height: 13,
                        color: "#10b981",
                        flexShrink: 0,
                      }}
                    />
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
