"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, useEffect, CSSProperties } from "react";
import {
  LayoutDashboard,
  Users,
  ClipboardCheck,
  Microscope,
  Workflow,
  BarChart3,
  ShieldCheck,
  Moon,
  Sun,
  PanelLeftClose,
  PanelLeft,
  Menu,
  X,
  LogOut,
} from "lucide-react";
import { useTheme } from "@/providers/theme-provider";
import { useAuth } from "@/contexts/auth-context";

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string; style?: CSSProperties }>;
  badge?: string | number;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

const navGroups: NavGroup[] = [
  {
    title: "MAIN",
    items: [
      { href: "/", label: "Dashboard", icon: LayoutDashboard },
      { href: "/patients", label: "Patients", icon: Users },
      { href: "/suspects", label: "Review Queue", icon: ClipboardCheck },
    ],
  },
  {
    title: "ANALYSIS",
    items: [
      { href: "/analysis", label: "Clinical Analysis", icon: Microscope },
      { href: "/demo", label: "Pipeline Demo", icon: Workflow },
    ],
  },
  {
    title: "REPORTS",
    items: [
      { href: "/reports", label: "Analytics", icon: BarChart3 },
      { href: "/audit", label: "Compliance & Audit", icon: ShieldCheck },
    ],
  },
];

function getUserInitials(name?: string): string {
  if (!name) return "?";
  return name
    .split(" ")
    .map((n) => n[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

const EXPANDED_WIDTH = 240;
const COLLAPSED_WIDTH = 64;
const BG = "#0F172A";
const BG_HOVER = "#1E293B";
const BG_ACTIVE = "#1E293B";
const TEXT_DEFAULT = "#94A3B8";
const TEXT_ACTIVE = "#FFFFFF";
const TEXT_SECTION = "#475569";
const TEXT_SUBTLE = "#64748B";
const ACCENT = "#2563EB";
const ACCENT_LIGHT = "#60A5FA";
const BORDER_COLOR = "#1E293B";

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { theme, toggle } = useTheme();
  const { user, logout, isAuthenticated } = useAuth();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [hoveredItem, setHoveredItem] = useState<string | null>(null);

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileOpen(false);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  function isActive(href: string) {
    return href === "/" ? pathname === "/" : pathname.startsWith(href);
  }

  const width = collapsed ? COLLAPSED_WIDTH : EXPANDED_WIDTH;

  function renderNavItem(item: NavItem) {
    const active = isActive(item.href);
    const hovered = hoveredItem === item.href;

    const itemStyle: CSSProperties = {
      display: "flex",
      alignItems: "center",
      gap: collapsed ? 0 : 10,
      justifyContent: collapsed ? "center" : "flex-start",
      height: 42,
      fontSize: 13,
      fontWeight: 500,
      color: active ? TEXT_ACTIVE : TEXT_DEFAULT,
      backgroundColor: active ? BG_ACTIVE : hovered ? BG_HOVER : "transparent",
      borderLeft: active ? `3px solid ${ACCENT}` : "3px solid transparent",
      paddingLeft: collapsed ? 0 : 13,
      paddingRight: collapsed ? 0 : 12,
      textDecoration: "none",
      transition: "background-color 150ms, color 150ms",
      position: "relative",
      cursor: "pointer",
    };

    const iconStyle: CSSProperties = {
      width: 18,
      height: 18,
      flexShrink: 0,
      color: active ? ACCENT_LIGHT : TEXT_DEFAULT,
    };

    return (
      <Link
        key={item.href}
        href={item.href}
        style={itemStyle}
        title={collapsed ? item.label : undefined}
        aria-current={active ? "page" : undefined}
        onMouseEnter={() => setHoveredItem(item.href)}
        onMouseLeave={() => setHoveredItem(null)}
      >
        <item.icon style={iconStyle} />
        {!collapsed && (
          <>
            <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {item.label}
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
          </>
        )}
      </Link>
    );
  }

  function renderNavGroup(group: NavGroup, index: number) {
    const headerStyle: CSSProperties = {
      fontSize: 11,
      fontWeight: 600,
      textTransform: "uppercase",
      letterSpacing: "0.08em",
      color: TEXT_SECTION,
      marginTop: index > 0 ? 20 : 8,
      marginBottom: 4,
      paddingLeft: collapsed ? 0 : 16,
      textAlign: collapsed ? "center" : "left",
    };

    return (
      <div key={group.title}>
        {!collapsed ? (
          <div style={headerStyle}>{group.title}</div>
        ) : (
          index > 0 && (
            <div style={{ display: "flex", justifyContent: "center", margin: "16px 0 8px" }}>
              <div style={{ width: 24, height: 1, backgroundColor: BORDER_COLOR }} />
            </div>
          )
        )}
        {group.items.map(renderNavItem)}
      </div>
    );
  }

  const sidebarContent = (
    <>
      {/* Logo area */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: collapsed ? 0 : 10,
          justifyContent: collapsed ? "center" : "flex-start",
          height: 56,
          flexShrink: 0,
          borderBottom: `1px solid ${BORDER_COLOR}`,
          paddingLeft: collapsed ? 0 : 16,
          paddingRight: collapsed ? 0 : 16,
        }}
      >
        {collapsed ? (
          <span style={{ fontSize: 16, fontWeight: 800, color: TEXT_ACTIVE, letterSpacing: "-0.02em" }}>R</span>
        ) : (
          <div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
              <span style={{ fontSize: 18, fontWeight: 800, color: TEXT_ACTIVE, letterSpacing: "-0.02em" }}>
                TMIAB
              </span>
              <span style={{ fontSize: 18, fontWeight: 800, color: ACCENT_LIGHT, letterSpacing: "-0.02em" }}>
                RAF
              </span>
            </div>
            <div style={{ fontSize: 10, color: TEXT_SUBTLE, fontWeight: 500, marginTop: -2 }}>
              Risk Adjustment
            </div>
          </div>
        )}
      </div>

      {/* Collapse toggle - desktop only */}
      <div
        style={{
          display: "flex",
          justifyContent: collapsed ? "center" : "flex-end",
          alignItems: "center",
          height: 36,
          flexShrink: 0,
          paddingRight: collapsed ? 0 : 8,
        }}
        className="hidden lg:flex"
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
          {collapsed ? <PanelLeft style={{ width: 16, height: 16 }} /> : <PanelLeftClose style={{ width: 16, height: 16 }} />}
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

      {/* Bottom section */}
      <div
        style={{
          flexShrink: 0,
          borderTop: `1px solid ${BORDER_COLOR}`,
          padding: collapsed ? "8px 4px" : "8px 12px",
        }}
      >
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
          aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          title={collapsed ? (theme === "dark" ? "Light mode" : "Dark mode") : undefined}
        >
          {theme === "dark" ? (
            <Sun style={{ width: 16, height: 16 }} />
          ) : (
            <Moon style={{ width: 16, height: 16 }} />
          )}
        </button>

        {/* User profile */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: collapsed ? 0 : 8,
            justifyContent: collapsed ? "center" : "flex-start",
            padding: "6px 4px",
            marginTop: 4,
          }}
        >
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
          >
            {user?.avatar ? (
              <img
                src={user.avatar}
                alt={user.name}
                style={{ width: 32, height: 32, borderRadius: "50%", objectFit: "cover" }}
              />
            ) : (
              getUserInitials(user?.name)
            )}
          </div>
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
                {user?.name || "Guest"}
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
                {user?.role || "User"}
              </div>
            </div>
          )}
          {!collapsed && isAuthenticated && (
            <button
              onClick={() => {
                logout();
                router.push("/login");
              }}
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

        {/* Collapsed logout */}
        {collapsed && isAuthenticated && (
          <button
            onClick={() => {
              logout();
              router.push("/login");
            }}
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
          <span style={{ fontSize: 10, color: TEXT_SECTION }}>v1.0</span>
        </div>
      </div>
    </>
  );

  const sidebarBaseStyle: CSSProperties = {
    backgroundColor: BG,
    display: "flex",
    flexDirection: "column",
    height: "100%",
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  };

  return (
    <>
      {/* Mobile hamburger */}
      <button
        onClick={() => setMobileOpen(true)}
        className="fixed left-4 top-4 z-50 flex h-11 w-11 items-center justify-center rounded-lg shadow-lg lg:hidden"
        style={{ backgroundColor: BG, border: `1px solid ${BORDER_COLOR}` }}
        aria-label="Open navigation menu"
      >
        <Menu className="h-5 w-5 text-white" />
      </button>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm lg:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Mobile sidebar */}
      <aside
        className="fixed left-0 top-0 z-50 lg:hidden transition-transform duration-300 ease-out"
        style={{
          ...sidebarBaseStyle,
          width: EXPANDED_WIDTH,
          transform: mobileOpen ? "translateX(0)" : "translateX(-100%)",
        }}
        role="navigation"
        aria-label="Mobile navigation"
      >
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

      {/* Desktop sidebar */}
      <aside
        className="fixed left-0 top-0 z-30 hidden lg:flex"
        style={{
          ...sidebarBaseStyle,
          width,
          transition: "width 300ms cubic-bezier(0.4, 0, 0.2, 1)",
        }}
        role="navigation"
        aria-label="Main navigation sidebar"
      >
        {sidebarContent}
      </aside>
    </>
  );
}

/** Hook to get the sidebar width for main content offset */
export function useSidebarWidth() {
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
