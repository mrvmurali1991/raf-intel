"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, useEffect, CSSProperties } from "react";
import {
  LayoutDashboard,
  Users,
  ClipboardCheck,
  CalendarClock,
  Target,
  Microscope,
  Workflow,
  BarChart3,
  UserCheck,
  Calculator,
  ShieldCheck,
  UsersRound,
  Code,
  Settings,
  Database,
  Moon,
  Sun,
  PanelLeftClose,
  PanelLeft,
  Menu,
  X,
  LogOut,
  HeartPulse,
  Search,
  ArrowLeftRight,
  Activity,
  Upload,
  Stethoscope,
  MapPin,
  TrendingDown,
  FileStack,
} from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTheme } from "@/providers/theme-provider";
import { useAuth } from "@/contexts/auth-context";
import api, { getEmrStatus } from "@/lib/api";
import { useTenantBranding } from "@/lib/useTenantBranding";
import { NotificationCenter } from "@/components/NotificationCenter";
import { hasUsedKeyboardShortcuts } from "@/components/KeyboardShortcuts";
import { Building2, ChevronDown } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface NavItem {
  href: string;
  label: string;
  /** Alternative label shown to non-admin users. Admin always sees `label`. */
  nonAdminLabel?: string;
  icon: React.ComponentType<{ className?: string; style?: CSSProperties }>;
  badge?: string | number;
  /** Keyboard shortcut hint, e.g. "g h". Shown when sidebar is expanded and user has used shortcuts before. */
  shortcut?: string;
  /** When set, the item is only shown to users whose `role` matches one of these values. */
  visibleToRoles?: string[];
}

interface NavCluster {
  label: string;
  items: NavItem[];
}

interface NavGroup {
  title: string;
  /** Flat item list — used when there are no sub-clusters */
  items?: NavItem[];
  /** Sub-clusters with divider labels — used instead of `items` */
  clusters?: NavCluster[];
  /** When true, section starts collapsed by default */
  defaultCollapsed?: boolean;
}

// Feature flag — set NEXT_PUBLIC_DEMO_MODE=true to reveal demo-only nav items
const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

// ---------------------------------------------------------------------------
// Navigation structure — 4 task-based sections
// ---------------------------------------------------------------------------

const navGroups: NavGroup[] = [
  {
    title: "DAILY WORK",
    items: [
      { href: "/", label: "Dashboard", icon: LayoutDashboard, shortcut: "g h" },
      { href: "/worklist", label: "Today's Worklist", nonAdminLabel: "My Worklist", icon: Stethoscope, shortcut: "g w" },
      { href: "/md/today", label: "Provider Prep (MD)", icon: HeartPulse, shortcut: "g m", visibleToRoles: ["provider", "md", "admin"] },
      { href: "/patients", label: "Patients", icon: Users, shortcut: "g p" },
    ],
  },
  {
    title: "HCC WORKFLOW",
    items: [
      { href: "/suspects", label: "Suspects", icon: ClipboardCheck },
      { href: "/recapture", label: "Recapture Gaps", icon: CalendarClock },
      { href: "/attestations", label: "Attestations", icon: ClipboardCheck },
      { href: "/review-queue", label: "Coder Review", icon: ClipboardCheck, shortcut: "g s" },
      { href: "/qa", label: "QA Audit", icon: ShieldCheck },
      { href: "/pre-submission", label: "Pre-submission", icon: ShieldCheck },
      { href: "/goals", label: "Quarterly Goals", icon: Target },
    ],
  },
  {
    title: "ANALYSIS",
    clusters: [
      {
        label: "Analytics & Insights",
        items: [
          { href: "/reports", label: "Reports", icon: BarChart3, shortcut: "g r" },
          { href: "/population/heatmap", label: "Population", icon: MapPin },
          { href: "/coder-analytics", label: "Coder Analytics", icon: BarChart3 },
          { href: "/providers/scorecard", label: "Provider Scorecards", icon: UserCheck },
          { href: "/v28-impact", label: "V28 Impact", icon: TrendingDown },
          { href: "/analysis", label: "Clinical Analysis", icon: Microscope, shortcut: "g a" },
          ...(DEMO_MODE ? [{ href: "/demo", label: "Pipeline Demo", icon: Workflow }] : []),
        ],
      },
      {
        label: "Reference Tools",
        items: [
          { href: "/raf-calculate", label: "RAF Calculator", icon: Calculator, shortcut: "g c" },
          { href: "/crosswalk", label: "HCC Crosswalk", icon: ArrowLeftRight },
          { href: "/roi", label: "ROI Calculator", icon: Calculator },
        ],
      },
    ],
  },
  {
    title: "ADMIN",
    clusters: [
      {
        label: "Setup",
        items: [
          { href: "/settings", label: "Settings", icon: Settings },
          { href: "/users", label: "Users", icon: UsersRound },
          { href: "/emr-config", label: "EMR Config", icon: Database, shortcut: "g e" },
          { href: "/uploads", label: "Data Uploads", icon: Upload },
        ],
      },
      {
        label: "Compliance",
        items: [
          { href: "/audit", label: "Audit", icon: ShieldCheck },
          { href: "/radv", label: "RADV Audit Defense", icon: ShieldCheck },
          { href: "/admin/document-ingestion", label: "Doc Ingestion", icon: FileStack, visibleToRoles: ["admin"] },
          { href: "/system", label: "System Health", icon: Activity, visibleToRoles: ["admin"] },
          { href: "/developer", label: "Developer", icon: Code, visibleToRoles: ["admin"] },
        ],
      },
    ],
  },
];

// ---------------------------------------------------------------------------
// Design tokens
// ---------------------------------------------------------------------------

const EXPANDED_WIDTH = 240;
const COLLAPSED_WIDTH = 64;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getUserInitials(firstName?: string, lastName?: string): string {
  const first = firstName?.[0] ?? "";
  const last = lastName?.[0] ?? "";
  return (first + last).toUpperCase() || "\u2022";
}

function getUserDisplayName(
  user: { first_name?: string; last_name?: string; email?: string } | null
): string {
  if (!user) return "Guest";
  const full = [user.first_name, user.last_name].filter(Boolean).join(" ");
  return full || user.email || "User";
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface TenantInfo {
  tenant_id: string;
  name: string;
  patient_count: number;
}

function TenantSwitcher({ isDark }: { isDark: boolean }) {
  const { user, switchTenant } = useAuth();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [switching, setSwitching] = useState(false);

  const { data } = useQuery({
    queryKey: ["tenants"],
    queryFn: async () => {
      try {
        const res = await api.get<{ tenants: TenantInfo[]; current_tenant_id: string }>(
          "/api/auth/tenants"
        );
        return res.data;
      } catch (err: unknown) {
        // 404 means the backend version doesn't expose this endpoint yet.
        // Return an empty result so the UI degrades gracefully (switcher stays hidden).
        const status = (err as { response?: { status?: number } })?.response?.status;
        if (status === 404) return { tenants: [], current_tenant_id: "1" };
        throw err;
      }
    },
    enabled: user?.role === "admin",
    staleTime: 30_000,
    retry: false,
  });

  const tenants = data?.tenants || [];
  const currentTid = user?.tenant_id || "1";
  const currentTenant = tenants.find((t) => t.tenant_id === currentTid);
  const displayName = currentTenant?.name || `Tenant ${currentTid}`;

  async function handleSwitch(tid: string) {
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

  if (tenants.length < 2) return null;

  return (
    <div style={{ position: "relative", marginTop: 6, marginBottom: 2 }}>
      <button
        onClick={() => setOpen(!open)}
        aria-label={`Switch tenant. Current: ${displayName}`}
        aria-expanded={open}
        aria-haspopup="listbox"
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "8px 10px",
          borderRadius: 10,
          border: `1px solid ${isDark ? "rgba(51,65,85,0.5)" : "rgba(226,232,240,0.8)"}`,
          backgroundColor: isDark ? "rgba(30,41,59,0.5)" : "rgba(241,245,249,0.7)",
          cursor: "pointer",
          color: isDark ? "#e2e8f0" : "#334155",
          fontSize: 12,
          fontWeight: 500,
          transition: "all 200ms",
        }}
      >
        <Building2 style={{ width: 14, height: 14, flexShrink: 0, opacity: 0.7 }} />
        <span style={{ flex: 1, textAlign: "left", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {displayName}
        </span>
        <ChevronDown
          style={{
            width: 12,
            height: 12,
            opacity: 0.5,
            transform: open ? "rotate(180deg)" : "rotate(0deg)",
            transition: "transform 200ms",
          }}
        />
      </button>

      {open && (
        <div
          style={{
            position: "absolute",
            bottom: "calc(100% + 4px)",
            left: 0,
            right: 0,
            backgroundColor: isDark ? "#1e293b" : "#ffffff",
            border: `1px solid ${isDark ? "#334155" : "#e2e8f0"}`,
            borderRadius: 10,
            boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
            zIndex: 50,
            overflow: "hidden",
          }}
        >
          <div style={{ padding: "8px 10px 4px", fontSize: 10, fontWeight: 600, color: isDark ? "#64748b" : "#64748b", textTransform: "uppercase", letterSpacing: 0.5 }}>
            Switch Tenant
          </div>
          {tenants.map((t) => (
            <button
              key={t.tenant_id}
              onClick={() => handleSwitch(t.tenant_id)}
              disabled={switching}
              style={{
                width: "100%",
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "8px 10px",
                border: "none",
                backgroundColor: t.tenant_id === currentTid
                  ? (isDark ? "rgba(15,118,110,0.2)" : "rgba(240,253,250,1)")
                  : "transparent",
                cursor: t.tenant_id === currentTid ? "default" : "pointer",
                color: isDark ? "#e2e8f0" : "#334155",
                fontSize: 12,
                textAlign: "left",
                transition: "background-color 150ms",
              }}
              onMouseEnter={(e) => {
                if (t.tenant_id !== currentTid)
                  e.currentTarget.style.backgroundColor = isDark ? "rgba(51,65,85,0.5)" : "#f8fafc";
              }}
              onMouseLeave={(e) => {
                if (t.tenant_id !== currentTid)
                  e.currentTarget.style.backgroundColor = "transparent";
              }}
            >
              <Building2 style={{ width: 13, height: 13, opacity: 0.6 }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {t.name}
                </div>
                <div style={{ fontSize: 10, opacity: 0.6 }}>
                  {t.patient_count} patients
                </div>
              </div>
              {t.tenant_id === currentTid && (
                <div style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: "#10b981" }} />
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { theme, toggle } = useTheme();
  const { user, logout, isAuthenticated } = useAuth();
  // Tenant co-branding — falls back to "RAF Intelligence" defaults when the
  // tenant has not customized anything (or when the user is unauthenticated).
  const { branding } = useTenantBranding();

  const { data: emrStatus, isLoading: emrLoading } = useQuery({
    queryKey: ["emr-status"],
    queryFn: () => getEmrStatus(),
    refetchInterval: 60_000,
    retry: 1,
  });

  const isDark = theme === "dark";
  const BG = isDark ? "#0f172a" : "#ffffff";
  const BG_GRADIENT = isDark
    ? "linear-gradient(180deg, #0f172a 0%, #0c1222 50%, #0f172a 100%)"
    : "linear-gradient(180deg, #ffffff 0%, #f8fafc 50%, #ffffff 100%)";
  const BG_HOVER = isDark ? "#1e293b" : "#f8fafc";
  const BG_ACTIVE = isDark ? "#0f766e20" : "#f0fdfa";
  const TEXT_DEFAULT = isDark ? "#94a3b8" : "#64748b";
  const TEXT_ACTIVE = isDark ? "#ffffff" : "#0f766e";
  const TEXT_SECTION = isDark ? "#64748b" : "#cbd5e1";
  const TEXT_SUBTLE = isDark ? "#64748b" : "#64748b";
  const ACCENT = isDark ? "#0f766e" : "#0d9488";
  const ACCENT_LIGHT = isDark ? "#2dd4bf" : "#0f766e";
  const BORDER_COLOR = isDark ? "#1e293b" : "#f1f5f9";
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [hoveredItem, setHoveredItem] = useState<string | null>(null);
  // Per-section collapse state — keyed by section title, persisted in localStorage
  const [sectionCollapsed, setSectionCollapsed] = useState<Record<string, boolean>>(() => {
    try {
      const saved = typeof window !== "undefined" ? localStorage.getItem("raf-nav-sections") : null;
      return saved ? JSON.parse(saved) : {};
    } catch {
      return {};
    }
  });

  function toggleSection(title: string) {
    setSectionCollapsed((prev) => {
      const next = { ...prev, [title]: !prev[title] };
      try { localStorage.setItem("raf-nav-sections", JSON.stringify(next)); } catch { /* noop */ }
      return next;
    });
  }
  // Only show shortcut hint badges after the user has triggered at least one shortcut
  const [showShortcutHints, setShowShortcutHints] = useState(false);

  useEffect(() => {
    // Check on mount, then re-check whenever a shortcut fires (storage event
    // covers cross-tab; custom event covers same-tab from KeyboardShortcuts).
    const refresh = () => setShowShortcutHints(hasUsedKeyboardShortcuts());
    refresh();
    window.addEventListener("raf-kb-used", refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener("raf-kb-used", refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);

  // Close mobile menu on route change
  const [prevPathname, setPrevPathname] = useState(pathname);
  if (prevPathname !== pathname) {
    setPrevPathname(pathname);
    if (mobileOpen) setMobileOpen(false);
  }

  // Close mobile menu on Escape key
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileOpen(false);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  function isActive(href: string): boolean {
    if (href === "/") return pathname === "/";
    // Match /patients as active for /patients/[pid] sub-pages
    return pathname === href || pathname.startsWith(href + "/");
  }

  function handleLogout() {
    // logout() handles navigation to /login internally — no need to push here.
    logout();
  }

  const width = collapsed ? COLLAPSED_WIDTH : EXPANDED_WIDTH;

  // ----- Nav item renderer -----
  function renderNavItem(item: NavItem) {
    const role = (user as { role?: string } | null)?.role ?? "";
    const isAdmin = role === "admin";
    // Non-admin users see the personalized label when one is provided
    const resolvedLabel = (!isAdmin && item.nonAdminLabel) ? item.nonAdminLabel : item.label;

    const active = isActive(item.href);
    const hovered = hoveredItem === item.href;

    const itemStyle: CSSProperties = {
      display: "flex",
      alignItems: "center",
      gap: collapsed ? 0 : 10,
      justifyContent: collapsed ? "center" : "flex-start",
      height: 36,
      fontSize: 13,
      fontWeight: active ? 600 : 500,
      letterSpacing: active ? "-0.01em" : "normal",
      color: active ? TEXT_ACTIVE : TEXT_DEFAULT,
      // Linear-style: tinted bg when active, subtle hover bg
      backgroundColor: active
        ? isDark ? "rgba(15,118,110,0.18)" : "rgba(13,148,136,0.10)"
        : hovered ? BG_HOVER : "transparent",
      // Linear-style colored left bar accent
      borderLeft: active ? `3px solid ${ACCENT}` : "3px solid transparent",
      borderRadius: collapsed ? 8 : "0 8px 8px 0",
      marginRight: collapsed ? 8 : 8,
      marginLeft: collapsed ? 8 : 0,
      paddingLeft: collapsed ? 0 : 13,
      paddingRight: collapsed ? 0 : 12,
      textDecoration: "none",
      transition: "all 180ms cubic-bezier(0.4, 0, 0.2, 1)",
      position: "relative",
      cursor: "pointer",
      boxShadow: active
        ? isDark
          ? `inset 0 0 0 1px rgba(15,118,110,0.2), 0 1px 4px rgba(15,118,110,0.12)`
          : `inset 0 0 0 1px rgba(13,148,136,0.18), 0 1px 3px rgba(13,148,136,0.10)`
        : "none",
    };

    const iconStyle: CSSProperties = {
      width: 17,
      height: 17,
      flexShrink: 0,
      color: active ? ACCENT_LIGHT : hovered ? ACCENT : TEXT_DEFAULT,
      transition: "transform 180ms cubic-bezier(0.34, 1.56, 0.64, 1), color 180ms",
      transform: hovered && !active ? "scale(1.12)" : active ? "scale(1.05)" : "scale(1)",
    };

    return (
      <Link
        key={item.href}
        href={item.href}
        style={itemStyle}
        // Tooltip shown in collapsed mode instead of label text
        title={collapsed ? resolvedLabel : undefined}
        aria-current={active ? "page" : undefined}
        onMouseEnter={() => setHoveredItem(item.href)}
        onMouseLeave={() => setHoveredItem(null)}
      >
        <item.icon style={iconStyle} />
        {!collapsed && (
          <>
            <span
              style={{
                flex: 1,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {resolvedLabel}
            </span>
            {item.badge !== undefined && (
              <span
                style={{
                  marginLeft: "auto",
                  fontSize: 11,
                  fontWeight: 600,
                  backgroundColor: "rgba(37,99,235,0.15)",
                  color: ACCENT_LIGHT,
                  padding: "2px 7px",
                  borderRadius: 4,
                }}
              >
                {item.badge}
              </span>
            )}
            {showShortcutHints && item.shortcut && item.badge === undefined && (
              <span
                aria-label={`Shortcut: ${item.shortcut}`}
                title={`Shortcut: ${item.shortcut}`}
                style={{
                  marginLeft: "auto",
                  display: "flex",
                  gap: 3,
                  flexShrink: 0,
                  opacity: hovered || active ? 1 : 0.45,
                  transition: "opacity 150ms",
                }}
              >
                {item.shortcut.split(" ").map((k, i) => (
                  <kbd
                    key={i}
                    style={{
                      fontSize: 10,
                      fontWeight: 600,
                      fontFamily: "inherit",
                      color: isDark ? "#64748b" : "#64748b",
                      backgroundColor: isDark ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.05)",
                      border: `1px solid ${BORDER_COLOR}`,
                      borderRadius: 3,
                      padding: "1px 4px",
                      lineHeight: 1.5,
                    }}
                  >
                    {k}
                  </kbd>
                ))}
              </span>
            )}
          </>
        )}
      </Link>
    );
  }

  // ----- Sub-cluster label (not collapsible; appears inside an expanded section) -----
  function renderClusterLabel(label: string, isFirst: boolean) {
    if (collapsed) return null;
    return (
      <div
        key={label}
        style={{
          marginTop: isFirst ? 2 : 10,
          marginBottom: 2,
          marginLeft: 16,
          marginRight: 16,
          borderTop: isFirst
            ? "none"
            : `1px solid ${isDark ? "rgba(51,65,85,0.45)" : "rgba(226,232,240,0.9)"}`,
          paddingTop: isFirst ? 0 : 7,
        }}
      >
        <span
          style={{
            fontSize: 10,
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.08em",
            color: isDark ? "#475569" : "#94a3b8",
          }}
        >
          {label}
        </span>
      </div>
    );
  }

  // ----- Nav group renderer -----
  function renderNavGroup(group: NavGroup, index: number) {
    // In collapsed (icon-only) sidebar mode, never hide items — no room for toggles
    const isSectionCollapsed = !collapsed && !!sectionCollapsed[group.title];

    function filterItems(items: NavItem[]): NavItem[] {
      return items.filter((it) => {
        if (!it.visibleToRoles || it.visibleToRoles.length === 0) return true;
        const role = (user as { role?: string } | null)?.role ?? "";
        return it.visibleToRoles.includes(role);
      });
    }

    return (
      <div key={group.title}>
        {!collapsed ? (
          <>
            {index > 0 && (
              <div
                style={{
                  height: 1,
                  margin: "12px 16px 0",
                  background: isDark
                    ? "linear-gradient(90deg, transparent, #1e293b 30%, #334155 50%, #1e293b 70%, transparent)"
                    : "linear-gradient(90deg, transparent, #e2e8f0 30%, #cbd5e1 50%, #e2e8f0 70%, transparent)",
                }}
              />
            )}
            {/* Clickable section header — clicking collapses/expands the group */}
            <button
              onClick={() => toggleSection(group.title)}
              aria-expanded={!isSectionCollapsed}
              aria-controls={`nav-section-${group.title}`}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                width: "100%",
                background: "none",
                border: "none",
                cursor: "pointer",
                padding: "0 16px 0 16px",
                marginTop: index > 0 ? 10 : 8,
                marginBottom: 4,
              }}
            >
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 600,
                  textTransform: "uppercase",
                  letterSpacing: "0.1em",
                  color: TEXT_SECTION,
                }}
              >
                {group.title}
              </span>
              <ChevronDown
                style={{
                  width: 12,
                  height: 12,
                  color: TEXT_SECTION,
                  flexShrink: 0,
                  transform: isSectionCollapsed ? "rotate(-90deg)" : "rotate(0deg)",
                  transition: "transform 200ms cubic-bezier(0.4, 0, 0.2, 1)",
                }}
              />
            </button>
          </>
        ) : (
          index > 0 && (
            <div
              style={{
                display: "flex",
                justifyContent: "center",
                margin: "12px 0 8px",
              }}
            >
              <div
                style={{
                  width: 28,
                  height: 1,
                  background: isDark
                    ? "linear-gradient(90deg, transparent, #334155, transparent)"
                    : "linear-gradient(90deg, transparent, #cbd5e1, transparent)",
                  borderRadius: 1,
                }}
              />
            </div>
          )
        )}
        {!isSectionCollapsed && (
          <div id={`nav-section-${group.title}`}>
            {group.clusters
              ? group.clusters.map((cluster, ci) => (
                  <div key={cluster.label}>
                    {renderClusterLabel(cluster.label, ci === 0)}
                    {filterItems(cluster.items).map(renderNavItem)}
                  </div>
                ))
              : filterItems(group.items ?? []).map(renderNavItem)}
          </div>
        )}
      </div>
    );
  }

  // ----- Shared sidebar content (used by both desktop and mobile) -----
  const sidebarContent = (
    <>
      {/* Logo */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: collapsed ? 0 : 8,
          justifyContent: collapsed ? "center" : "flex-start",
          height: 64,
          flexShrink: 0,
          borderBottom: `1px solid ${BORDER_COLOR}`,
          paddingLeft: collapsed ? 0 : 16,
          paddingRight: collapsed ? 0 : 16,
        }}
      >
        {collapsed ? (
          <div style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <div className="sidebar-logo-glow" style={{ position: "absolute", inset: -4, borderRadius: 12, background: `radial-gradient(circle, ${ACCENT}40, transparent 70%)`, filter: "blur(6px)" }} />
            <div style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center", width: 32, height: 32, borderRadius: 8, background: `linear-gradient(135deg, ${ACCENT}, ${ACCENT_LIGHT})`, color: "#fff" }}>
              <HeartPulse size={18} />
            </div>
          </div>
        ) : (
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <div className="sidebar-logo-glow" style={{ position: "absolute", inset: -6, borderRadius: 14, background: `radial-gradient(circle, ${ACCENT}50, transparent 70%)`, filter: "blur(8px)" }} />
              <div style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center", width: 32, height: 32, borderRadius: 8, background: `linear-gradient(135deg, ${ACCENT}, ${ACCENT_LIGHT})`, color: "#fff", boxShadow: `0 2px 12px ${ACCENT}40` }}>
                <HeartPulse size={18} />
              </div>
            </div>
            <div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
                {/* Tenant logo text — driven by useTenantBranding().
                    Defaults to "RAF Intel" when no row exists for the tenant. */}
                <span
                  data-testid="sidebar-logo-text"
                  style={{
                    fontSize: 17,
                    fontWeight: 800,
                    color: TEXT_ACTIVE,
                    letterSpacing: "-0.02em",
                  }}
                >
                  {branding.logo_text || "RAF Intelligence"}
                </span>
              </div>
              <div style={{ fontSize: 10, color: TEXT_SUBTLE, fontWeight: 600, marginTop: -2, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                {branding.display_name || "Clinical Intelligence"}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Search + Notifications row */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: collapsed ? 0 : 6,
          margin: collapsed ? "8px 8px 0" : "8px 10px 0",
          flexShrink: 0,
        }}
      >
        {/* Search button */}
        <button
          onClick={() => window.dispatchEvent(new CustomEvent("open-command-palette"))}
          title="Search (⌘K)"
          aria-label="Open command palette (Cmd+K)"
          style={{
            display: "flex",
            alignItems: "center",
            gap: collapsed ? 0 : 8,
            justifyContent: collapsed ? "center" : "flex-start",
            height: 38,
            flex: collapsed ? "0 0 auto" : 1,
            width: collapsed ? 32 : undefined,
            padding: collapsed ? "0" : "0 10px",
            borderRadius: 7,
            background: isDark
              ? "rgba(15,23,42,0.6)"
              : "rgba(248,250,252,0.8)",
            border: `1px solid ${BORDER_COLOR}`,
            boxShadow: isDark
              ? "inset 0 1px 3px rgba(0,0,0,0.3), 0 0 0 0 transparent"
              : "inset 0 1px 3px rgba(0,0,0,0.06), 0 0 0 0 transparent",
            cursor: "pointer",
            color: TEXT_DEFAULT,
            fontSize: 13,
            transition: "all 200ms cubic-bezier(0.4, 0, 0.2, 1)",
          }}
          onMouseEnter={(e) => {
            const btn = e.currentTarget as HTMLButtonElement;
            btn.style.borderColor = isDark ? "#334155" : "#cbd5e1";
            btn.style.background = isDark ? "rgba(30,41,59,0.8)" : "rgba(241,245,249,0.9)";
            btn.style.boxShadow = isDark
              ? `inset 0 1px 3px rgba(0,0,0,0.3), 0 0 8px ${ACCENT}20`
              : `inset 0 1px 3px rgba(0,0,0,0.06), 0 0 8px ${ACCENT}15`;
          }}
          onMouseLeave={(e) => {
            const btn = e.currentTarget as HTMLButtonElement;
            btn.style.borderColor = BORDER_COLOR;
            btn.style.background = isDark ? "rgba(15,23,42,0.6)" : "rgba(248,250,252,0.8)";
            btn.style.boxShadow = isDark
              ? "inset 0 1px 3px rgba(0,0,0,0.3), 0 0 0 0 transparent"
              : "inset 0 1px 3px rgba(0,0,0,0.06), 0 0 0 0 transparent";
          }}
        >
          <Search style={{ width: 15, height: 15, flexShrink: 0, color: TEXT_DEFAULT }} aria-hidden />
          {!collapsed && (
            <>
              <span style={{ flex: 1, textAlign: "left", color: TEXT_DEFAULT }}>Search…</span>
              <kbd
                style={{
                  fontSize: 10,
                  color: TEXT_SUBTLE,
                  backgroundColor: "rgba(255,255,255,0.06)",
                  border: `1px solid ${BORDER_COLOR}`,
                  borderRadius: 3,
                  padding: "1px 5px",
                  fontFamily: "inherit",
                  flexShrink: 0,
                }}
              >
                ⌘K
              </kbd>
            </>
          )}
        </button>

        {/* Notification bell */}
        <NotificationCenter collapsed={collapsed} />
      </div>

      {/* Collapse toggle — desktop only (hidden on mobile via className) */}
      <div
        className="hidden lg:flex"
        style={{
          justifyContent: collapsed ? "center" : "flex-end",
          alignItems: "center",
          height: 36,
          flexShrink: 0,
          paddingRight: collapsed ? 0 : 8,
        }}
      >
        <button
          onClick={() => setCollapsed(!collapsed)}
          style={{
            background: "none",
            border: "none",
            padding: 6,
            cursor: "pointer",
            color: TEXT_SUBTLE,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            borderRadius: 4,
          }}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <PanelLeft style={{ width: 16, height: 16 }} />
          ) : (
            <PanelLeftClose style={{ width: 16, height: 16 }} />
          )}
        </button>
      </div>

      {/* Navigation */}
      <nav
        style={{ flex: 1, overflowY: "auto", paddingTop: 4, paddingBottom: 8 }}
        role="navigation"
        aria-label="Main navigation"
      >
        {navGroups.map((group, i) => renderNavGroup(group, i))}
      </nav>

      {/* Keyboard shortcut affordance hint — shown only when sidebar is expanded */}
      {!collapsed && (
        <div
          style={{
            marginTop: "auto",
            padding: "6px 14px 4px",
            fontSize: 11,
            color: isDark ? "#475569" : "#64748b",
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}
          aria-label="Press ? to open keyboard shortcuts"
        >
          Press{" "}
          <kbd
            style={{
              display: "inline-block",
              padding: "1px 5px",
              border: `1px solid ${isDark ? "#334155" : "#cbd5e1"}`,
              borderRadius: 4,
              fontSize: 11,
              fontFamily: "monospace",
              background: isDark ? "rgba(255,255,255,0.05)" : "rgba(0,0,0,0.04)",
              color: isDark ? "#64748b" : "#64748b",
            }}
          >
            ?
          </kbd>{" "}
          for shortcuts
        </div>
      )}

      {/* Bottom section: theme toggle + user profile + version */}
      <div
        style={{
          flexShrink: 0,
          borderTop: `1px solid ${BORDER_COLOR}`,
          padding: collapsed ? "8px 4px" : "8px 12px",
        }}
      >
        {/* EMR Connection Status */}
        <Link
          href="/emr-config"
          title={collapsed ? (emrLoading ? "EMR: Checking..." : emrStatus?.connected ? "EMR Connected" : "EMR Disconnected") : undefined}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: collapsed ? "center" : "flex-start",
            gap: 8,
            width: "100%",
            height: 32,
            background: "none",
            textDecoration: "none",
            cursor: "pointer",
            color: TEXT_DEFAULT,
            fontSize: 12,
            borderRadius: 4,
            paddingLeft: collapsed ? 0 : 4,
            marginBottom: 4,
          }}
        >
          <span
            className={emrStatus?.connected ? "emr-pulse" : undefined}
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              flexShrink: 0,
              backgroundColor: emrLoading
                ? (isDark ? "#64748b" : "#94a3b8")
                : emrStatus?.connected
                  ? "#22c55e"
                  : "#ef4444",
              transition: "background-color 300ms",
            }}
          />
          {!collapsed && (
            <span style={{ fontSize: 12, color: TEXT_DEFAULT }}>
              {emrLoading ? "EMR Checking..." : emrStatus?.connected ? "EMR Connected" : "EMR Disconnected"}
            </span>
          )}
        </Link>

        {/* Theme toggle */}
        <button
          onClick={toggle}
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: collapsed ? "center" : "flex-start",
            gap: 8,
            width: "100%",
            height: 32,
            background: "none",
            border: "none",
            cursor: "pointer",
            color: TEXT_DEFAULT,
            fontSize: 12,
            borderRadius: 4,
            paddingLeft: collapsed ? 0 : 4,
          }}
          aria-label={
            theme === "dark" ? "Switch to light mode" : "Switch to dark mode"
          }
          aria-pressed={theme === "dark"}
          title={
            collapsed
              ? theme === "dark"
                ? "Light mode"
                : "Dark mode"
              : undefined
          }
        >
          {theme === "dark" ? (
            <Sun style={{ width: 16, height: 16 }} />
          ) : (
            <Moon style={{ width: 16, height: 16 }} />
          )}
          {!collapsed && (
            <>
              <span style={{ flex: 1 }}>Dark mode</span>
              {/* Visual switch indicator — shows ON/OFF state at a glance */}
              <span
                role="presentation"
                data-state={theme === "dark" ? "on" : "off"}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  width: 32,
                  height: 18,
                  borderRadius: 9,
                  backgroundColor: theme === "dark" ? "#0f766e" : (isDark ? "#334155" : "#cbd5e1"),
                  padding: "0 2px",
                  transition: "background-color 200ms",
                  flexShrink: 0,
                }}
              >
                <span
                  style={{
                    width: 14,
                    height: 14,
                    borderRadius: "50%",
                    backgroundColor: "#ffffff",
                    transform: theme === "dark" ? "translateX(14px)" : "translateX(0)",
                    transition: "transform 200ms cubic-bezier(0.4,0,0.2,1)",
                    flexShrink: 0,
                  }}
                />
              </span>
            </>
          )}
        </button>

        {/* Tenant switcher (admin only) */}
        {user?.role === "admin" && !collapsed && <TenantSwitcher isDark={isDark} />}

        {/* User profile row */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: collapsed ? 0 : 8,
            justifyContent: collapsed ? "center" : "flex-start",
            padding: collapsed ? "6px 4px" : "8px 8px",
            marginTop: 6,
            borderRadius: 10,
            backgroundColor: isDark ? "rgba(30,41,59,0.5)" : "rgba(241,245,249,0.7)",
            border: `1px solid ${isDark ? "rgba(51,65,85,0.3)" : "rgba(226,232,240,0.6)"}`,
            transition: "background-color 200ms",
          }}
        >
          {/* Avatar */}
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: "50%",
              backgroundColor: ACCENT,
              color: TEXT_ACTIVE,
              fontSize: 12,
              fontWeight: 600,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
              overflow: "hidden",
            }}
            title={collapsed ? getUserDisplayName(user) : undefined}
          >
            {user?.avatar_url && user.avatar_url.startsWith("https://") ? (
              <img
                src={user.avatar_url}
                alt={getUserDisplayName(user)}
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: "50%",
                  objectFit: "cover",
                }}
              />
            ) : (
              getUserInitials(user?.first_name, user?.last_name)
            )}
          </div>

          {/* Name + role (expanded only) */}
          {!collapsed && (
            <div style={{ flex: 1, minWidth: 0 }}>
              <div
                style={{
                  fontSize: 13,
                  fontWeight: 500,
                  color: TEXT_ACTIVE,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {getUserDisplayName(user)}
              </div>
              <div
                style={{
                  fontSize: 11,
                  color: TEXT_SUBTLE,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {(user as { role?: string } | null)?.role ?? "User"}
              </div>
            </div>
          )}

          {/* Logout button — inline when expanded */}
          {!collapsed && isAuthenticated && (
            <button
              onClick={handleLogout}
              style={{
                background: "none",
                border: "none",
                padding: 4,
                cursor: "pointer",
                color: TEXT_SUBTLE,
                display: "flex",
                alignItems: "center",
                borderRadius: 4,
              }}
              aria-label="Sign out"
              title="Sign out"
            >
              <LogOut style={{ width: 15, height: 15 }} />
            </button>
          )}
        </div>

        {/* Logout button — standalone row when collapsed */}
        {collapsed && isAuthenticated && (
          <button
            onClick={handleLogout}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              width: "100%",
              height: 32,
              background: "none",
              border: "none",
              cursor: "pointer",
              color: TEXT_SUBTLE,
              borderRadius: 4,
            }}
            aria-label="Sign out"
            title="Sign out"
          >
            <LogOut style={{ width: 15, height: 15 }} />
          </button>
        )}

        {/* Version */}
        <div
          style={{
            textAlign: collapsed ? "center" : "left",
            paddingLeft: collapsed ? 0 : 4,
            paddingTop: 6,
          }}
        >
          <span style={{ fontSize: 10, color: TEXT_SECTION }}>v2.0</span>
        </div>
      </div>
    </>
  );

  const sidebarBaseStyle: CSSProperties = {
    background: BG_GRADIENT,
    display: "flex",
    flexDirection: "column",
    height: "100%",
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  };

  return (
    <>
      {/* Keyframe animations for sidebar */}
      <style>{`
        @keyframes sidebarLogoGlow {
          0%, 100% { opacity: 0.5; transform: scale(1); }
          50% { opacity: 1; transform: scale(1.15); }
        }
        .sidebar-logo-glow {
          animation: sidebarLogoGlow 3s ease-in-out infinite;
        }
        @keyframes emrPulse {
          0%, 100% { box-shadow: 0 0 0 0 rgba(34,197,94,0.5); }
          50% { box-shadow: 0 0 0 4px rgba(34,197,94,0); }
        }
        .emr-pulse {
          animation: emrPulse 2s ease-in-out infinite;
        }
      `}</style>

      {/* Mobile hamburger button */}
      <button
        onClick={() => setMobileOpen(true)}
        className="fixed left-4 top-4 z-50 flex h-11 w-11 items-center justify-center rounded-lg shadow-lg lg:hidden"
        style={{ backgroundColor: BG, border: `1px solid ${BORDER_COLOR}` }}
        aria-label="Open navigation menu"
        aria-expanded={mobileOpen}
        aria-controls="mobile-sidebar"
      >
        <Menu className="h-5 w-5" style={{ color: TEXT_ACTIVE }} />
      </button>

      {/* Mobile backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm lg:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Mobile sidebar.
       * Use the `inert` attribute when closed so focusable descendants
       * (close button, nav links, sign-out) are removed from the tab
       * order AND hidden from assistive tech. `aria-hidden` alone left
       * those descendants focusable, which axe rightly flagged. */}
      <aside
        id="mobile-sidebar"
        className="fixed left-0 top-0 z-50 lg:hidden transition-transform duration-300 ease-out"
        style={{
          ...sidebarBaseStyle,
          width: EXPANDED_WIDTH,
          transform: mobileOpen ? "translateX(0)" : "translateX(-100%)",
        }}
        aria-label="Mobile navigation"
        inert={!mobileOpen}
      >
        {/* Close button */}
        <div style={{ position: "absolute", right: 10, top: 10, zIndex: 10 }}>
          <button
            onClick={() => setMobileOpen(false)}
            style={{
              background: "none",
              border: "none",
              padding: 4,
              cursor: "pointer",
              color: TEXT_SUBTLE,
              display: "flex",
            }}
            aria-label="Close navigation menu"
          >
            <X style={{ width: 20, height: 20 }} />
          </button>
        </div>
        {sidebarContent}
      </aside>

      {/* Desktop sidebar.
          NOTE: do NOT add `display` to the inline style — the Tailwind
          `hidden lg:flex` classes must control visibility. An inline
          `display:flex` would override `hidden` (higher specificity than
          classes) and leak the desktop sidebar into mobile viewports. */}
      <aside
        className="fixed left-0 top-0 z-30 hidden lg:flex"
        style={{
          background: sidebarBaseStyle.background,
          flexDirection: "column",
          height: "100%",
          fontFamily: sidebarBaseStyle.fontFamily,
          width,
          transition: "width 300ms cubic-bezier(0.4, 0, 0.2, 1)",
        }}
        aria-label="Main navigation sidebar"
      >
        {sidebarContent}
      </aside>
    </>
  );
}

// ---------------------------------------------------------------------------
// Hook — returns the current desktop sidebar width for main-content offsetting
// ---------------------------------------------------------------------------

export function useSidebarWidth(): number {
  const [width, setWidth] = useState(EXPANDED_WIDTH);

  useEffect(() => {
    const sidebar = document.querySelector(
      "aside.lg\\:flex"
    ) as HTMLElement | null;
    if (!sidebar) return;

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setWidth(entry.contentRect.width);
      }
    });
    observer.observe(sidebar);
    return () => observer.disconnect();
  }, []);

  return width;
}
