"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, useEffect } from "react";
import {
  LayoutDashboard,
  Users,
  SearchCheck,
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
  FileSignature,
  ClipboardList,
  CheckCircle2,
  ChevronDown,
  Building2,
} from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTheme } from "@/providers/theme-provider";
import { useAuth } from "@/contexts/auth-context";
import api, { getEmrStatus } from "@/lib/api";
import { useTenantBranding } from "@/lib/useTenantBranding";
import { NotificationCenter } from "@/components/NotificationCenter";
import { hasUsedKeyboardShortcuts } from "@/components/KeyboardShortcuts";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface NavItem {
  href: string;
  label: string;
  nonAdminLabel?: string;
  icon: React.ComponentType<{ className?: string; size?: number }>;
  badge?: string | number;
  shortcut?: string;
  visibleToRoles?: string[];
  tooltip?: string;
}

interface NavCluster {
  label: string;
  items: NavItem[];
  defaultCollapsed?: boolean;
  visibleToRoles?: string[];
}

interface NavGroup {
  title: string;
  items?: NavItem[];
  clusters?: NavCluster[];
  defaultCollapsed?: boolean;
}

interface TenantInfo {
  tenant_id: string;
  name: string;
  patient_count: number;
}

// Feature flag — set NEXT_PUBLIC_DEMO_MODE=true to reveal demo-only nav items
const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

// ---------------------------------------------------------------------------
// Design constants
// ---------------------------------------------------------------------------

const EXPANDED_WIDTH = 240;
const COLLAPSED_WIDTH = 64;

// ---------------------------------------------------------------------------
// Navigation structure — 4 task-based sections
// ---------------------------------------------------------------------------

const navGroups: NavGroup[] = [
  {
    title: "DAILY WORK",
    items: [
      { href: "/", label: "Dashboard", icon: LayoutDashboard, shortcut: "g h", tooltip: "Population Health Intelligence — CMS Sweep deadline, KPIs, provider workload, EMR coverage" },
      { href: "/worklist", label: "Today's Worklist", nonAdminLabel: "My Worklist", icon: Stethoscope, shortcut: "g w", tooltip: "Daily prioritized patient queue — bulk-attest, AWV scheduling, evidence preview" },
      { href: "/md/today", label: "Provider Prep (MD)", icon: HeartPulse, shortcut: "g m", visibleToRoles: ["provider", "md"] },
      { href: "/patients", label: "Patients", icon: Users, shortcut: "g p", tooltip: "Full patient roster — risk filters, RAF column, bulk actions" },
    ],
  },
  {
    title: "HCC WORKFLOW",
    items: [
      { href: "/suspects", label: "Suspects", icon: SearchCheck, tooltip: "AI-flagged HCC diagnoses awaiting coder review — Accept/Reject with reason codes" },
      { href: "/recapture", label: "Recapture Gaps", icon: CalendarClock, tooltip: "Prior-year HCCs not yet documented this payment year" },
      { href: "/attestations", label: "Attestations", icon: FileSignature, tooltip: "Provider sign-off workflow for accepted suspects" },
      { href: "/review-queue", label: "Coder Review", icon: ClipboardList, shortcut: "g s", tooltip: "Queue assigned to coding team" },
      { href: "/qa", label: "QA Audit", icon: ShieldCheck, tooltip: "QA team's review queue for completed attestations" },
      { href: "/pre-submission", label: "Pre-submission", icon: CheckCircle2, tooltip: "5-tier validation gate before CMS EDI submission" },
      { href: "/goals", label: "Quarterly Goals", icon: Target, tooltip: "Goal-vs-actual RAF capture tracking" },
    ],
  },
  {
    title: "ANALYSIS",
    defaultCollapsed: true,
    clusters: [
      {
        label: "Analytics & Insights",
        items: [
          { href: "/reports", label: "Reports", icon: BarChart3, shortcut: "g r", tooltip: "Revenue, scorecards, HCC distribution, CMS benchmarks" },
          { href: "/population/heatmap", label: "Population", icon: MapPin, tooltip: "ZIP-level risk heat map and bar chart" },
          { href: "/coder-analytics", label: "Coder Analytics", icon: BarChart3, tooltip: "Throughput, accuracy, productivity per coder" },
          { href: "/providers/scorecard", label: "Provider Scorecards", icon: UserCheck, tooltip: "Per-provider capture rate, MEAT score, revenue contribution" },
          { href: "/v28-impact", label: "V28 Impact", icon: TrendingDown, tooltip: "CMS-HCC V28 model portfolio impact analysis" },
          { href: "/analysis", label: "Clinical Analysis", icon: Microscope, shortcut: "g a", tooltip: "Free-form clinical note → AI-extracted HCC suspects" },
          ...(DEMO_MODE ? [{ href: "/demo", label: "Pipeline Demo", icon: Workflow }] : []),
        ],
      },
      {
        label: "Reference Tools",
        items: [
          { href: "/raf-calculate", label: "RAF Calculator", icon: Calculator, shortcut: "g c", tooltip: "Per-patient RAF scoring with V24/V28 toggle" },
          { href: "/crosswalk", label: "HCC Crosswalk", icon: ArrowLeftRight, tooltip: "ICD-10 → HCC mapping reference tool" },
          { href: "/roi", label: "ROI Calculator", icon: Calculator, tooltip: "Customer ROI projection with NPV and payback period" },
        ],
      },
    ],
  },
  {
    title: "ADMIN",
    defaultCollapsed: true,
    clusters: [
      {
        label: "Setup",
        items: [
          { href: "/settings", label: "Settings", icon: Settings, tooltip: "Profile, security, EMR connections, team, API keys" },
          { href: "/users", label: "Users", icon: UsersRound, tooltip: "Team member management with role-based permissions" },
          { href: "/emr-config", label: "EMR Config", icon: Database, shortcut: "g e", tooltip: "Connect Epic, Cerner, Athena, or OpenEMR via FHIR" },
          { href: "/uploads", label: "Data Uploads", icon: Upload, tooltip: "Bulk patient/claims/encounter ingest from CSV" },
        ],
      },
      {
        label: "Compliance",
        items: [
          { href: "/audit", label: "Audit", icon: ShieldCheck, tooltip: "Immutable SHA-256 audit chain with integrity verify" },
          { href: "/radv", label: "RADV Audit Defense", icon: ShieldCheck, tooltip: "CMS RADV audit run management, chart requests, exposure modeling" },
          { href: "/admin/document-ingestion", label: "Doc Ingestion", icon: FileStack, visibleToRoles: ["admin"] },
        ],
      },
      {
        label: "Power user",
        defaultCollapsed: true,
        visibleToRoles: ["admin"],
        items: [
          { href: "/ehr-writeback", label: "EHR Write-Back Queue", icon: Activity, visibleToRoles: ["admin"] },
          { href: "/system", label: "System Health", icon: Activity, visibleToRoles: ["admin"] },
          { href: "/developer", label: "Developer", icon: Code, visibleToRoles: ["admin"] },
        ],
      },
    ],
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getUserInitials(firstName?: string, lastName?: string): string {
  const first = firstName?.[0] ?? "";
  const last = lastName?.[0] ?? "";
  return (first + last).toUpperCase() || "•";
}

function getUserDisplayName(
  user: { first_name?: string; last_name?: string; email?: string } | null
): string {
  if (!user) return "Guest";
  const full = [user.first_name, user.last_name].filter(Boolean).join(" ");
  return full || user.email || "User";
}

// ---------------------------------------------------------------------------
// TenantSwitcher sub-component
// ---------------------------------------------------------------------------

function TenantSwitcher({ collapsed }: { collapsed: boolean }) {
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

  if (tenants.length < 2 || collapsed) return null;

  return (
    <div className="relative mt-1.5 mb-0.5">
      <button
        onClick={() => setOpen(!open)}
        aria-label={`Switch tenant. Current: ${displayName}`}
        aria-expanded={open}
        aria-haspopup="listbox"
        className="w-full flex items-center gap-2 px-2.5 py-2 rounded-[10px] border border-sidebar-border bg-sidebar-accent/50 cursor-pointer text-sidebar-foreground text-[12px] font-medium transition-colors duration-200 hover:bg-sidebar-accent"
      >
        <Building2 size={14} className="shrink-0 opacity-70" />
        <span className="flex-1 text-left overflow-hidden text-ellipsis whitespace-nowrap">
          {displayName}
        </span>
        <ChevronDown
          size={12}
          className={`opacity-50 transition-transform duration-200 ${open ? "rotate-180" : "rotate-0"}`}
        />
      </button>

      {open && (
        <div className="absolute bottom-[calc(100%+4px)] left-0 right-0 bg-popover border border-border rounded-[10px] shadow-lg z-50 overflow-hidden">
          <div className="px-2.5 pt-2 pb-1 text-[10px] font-semibold text-muted-foreground uppercase tracking-[0.5px]">
            Switch Tenant
          </div>
          {tenants.map((t) => (
            <button
              key={t.tenant_id}
              onClick={() => handleSwitch(t.tenant_id)}
              disabled={switching}
              className={`w-full flex items-center gap-2 px-2.5 py-2 border-none text-[12px] text-left transition-colors duration-150 ${
                t.tenant_id === currentTid
                  ? "bg-primary/10 cursor-default"
                  : "bg-transparent cursor-pointer hover:bg-muted"
              } text-foreground`}
            >
              <Building2 size={13} className="opacity-60" />
              <div className="flex-1 min-w-0">
                <div className="font-medium overflow-hidden text-ellipsis whitespace-nowrap">
                  {t.name}
                </div>
                <div className="text-[10px] opacity-60">{t.patient_count} patients</div>
              </div>
              {t.tenant_id === currentTid && (
                <div className="w-1.5 h-1.5 rounded-full bg-green-500 shrink-0" />
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SidebarItem sub-component
// ---------------------------------------------------------------------------

interface SidebarItemProps {
  item: NavItem;
  collapsed: boolean;
  isActive: boolean;
  showShortcutHints: boolean;
  userRole: string;
}

function SidebarItem({ item, collapsed, isActive, showShortcutHints, userRole }: SidebarItemProps) {
  const isAdmin = userRole === "admin";
  const resolvedLabel = (!isAdmin && item.nonAdminLabel) ? item.nonAdminLabel : item.label;

  const linkEl = (
    <Link
      href={item.href}
      title={item.tooltip ?? resolvedLabel}
      aria-current={isActive ? "page" : undefined}
      className={[
        "group flex items-center h-9 text-sm no-underline",
        "transition-all duration-150 ease-out relative",
        // Collapsed: centered icon pill
        collapsed
          ? "justify-center mx-2 rounded-lg"
          : "justify-start rounded-r-lg mr-2 ml-0 py-2 px-4",
        // Active state — 3 px left accent + teal tint
        isActive
          ? [
              collapsed
                ? "shadow-[inset_0_0_0_1px_hsl(var(--sidebar-primary)/0.2)] bg-sidebar-primary/10 text-sidebar-primary"
                : "border-l-[3px] border-[var(--primary)] bg-primary/10 text-foreground font-medium pl-[13px]",
            ].join(" ")
          : [
              collapsed ? "" : "border-l-[3px] border-transparent pl-[13px]",
              "text-sidebar-foreground hover:bg-muted/50 hover:text-sidebar-accent-foreground",
            ].join(" "),
        // Collapsed needs its own border reset
        collapsed ? "border-l-0 border border-transparent" : "",
      ].join(" ")}
    >
      <item.icon
        size={16}
        className={[
          "shrink-0 transition-[color,transform] duration-150",
          isActive
            ? "text-sidebar-primary"
            : "text-sidebar-foreground group-hover:text-sidebar-primary",
        ].join(" ")}
      />
      {!collapsed && (
        <>
          <span className="flex-1 overflow-hidden text-ellipsis whitespace-nowrap ml-3">
            {resolvedLabel}
          </span>
          {item.badge !== undefined && (
            <span className="ml-auto text-[11px] font-semibold bg-primary/15 text-sidebar-primary px-[7px] py-0.5 rounded">
              {item.badge}
            </span>
          )}
          {showShortcutHints && item.shortcut && item.badge === undefined && (
            <span
              aria-label={`Shortcut: ${item.shortcut}`}
              className={`ml-auto flex gap-[3px] shrink-0 transition-opacity duration-150 ${isActive ? "opacity-100" : "opacity-45 group-hover:opacity-100"}`}
            >
              {item.shortcut.split(" ").map((k, i) => (
                <kbd
                  key={i}
                  className="text-[10px] font-semibold font-[inherit] text-muted-foreground bg-muted border border-border rounded-[3px] px-1 py-0 leading-[1.5]"
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

  if (item.tooltip) {
    return (
      <Tooltip key={item.href}>
        <TooltipTrigger asChild>{linkEl}</TooltipTrigger>
        <TooltipContent side="right" sideOffset={8}>
          {item.tooltip}
        </TooltipContent>
      </Tooltip>
    );
  }

  return linkEl;
}

// ---------------------------------------------------------------------------
// SidebarCluster sub-component
// ---------------------------------------------------------------------------

interface SidebarClusterProps {
  cluster: NavCluster;
  clusterIndex: number;
  collapsed: boolean;
  clusterCollapsed: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}

function SidebarCluster({
  cluster,
  clusterIndex,
  collapsed,
  clusterCollapsed,
  onToggle,
  children,
}: SidebarClusterProps) {
  if (collapsed) {
    return <div>{children}</div>;
  }

  const hasToggle = cluster.defaultCollapsed !== undefined;

  return (
    <div>
      <div
        className={[
          "mx-4 mb-0.5",
          clusterIndex === 0 ? "mt-0.5" : "mt-2.5 pt-[7px] border-t border-border/50",
        ].join(" ")}
      >
        {hasToggle ? (
          <button
            onClick={onToggle}
            aria-expanded={!clusterCollapsed}
            aria-controls={`nav-cluster-${cluster.label}`}
            className="flex items-center justify-between w-full bg-transparent border-none cursor-pointer p-0"
          >
            <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              {cluster.label}
            </span>
            <ChevronDown
              size={11}
              className={`text-muted-foreground shrink-0 transition-transform duration-200 ${clusterCollapsed ? "-rotate-90" : "rotate-0"}`}
            />
          </button>
        ) : (
          <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            {cluster.label}
          </span>
        )}
      </div>
      {!clusterCollapsed && (
        <div id={`nav-cluster-${cluster.label}`}>{children}</div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SidebarSection sub-component
// ---------------------------------------------------------------------------

interface SidebarSectionProps {
  group: NavGroup;
  groupIndex: number;
  collapsed: boolean;
  sectionCollapsed: boolean;
  onToggleSection: () => void;
  children: React.ReactNode;
}

function SidebarSection({
  group,
  groupIndex,
  collapsed,
  sectionCollapsed,
  onToggleSection,
  children,
}: SidebarSectionProps) {
  return (
    <div>
      {/* Section divider — collapsed: short centered rule; expanded: full-width gradient rule */}
      {groupIndex > 0 && (
        collapsed ? (
          <div className="flex justify-center my-3">
            <div className="w-7 h-px bg-border/60 rounded" />
          </div>
        ) : (
          <div className="h-px mx-0 mt-4 bg-gradient-to-r from-transparent via-border/70 to-transparent" />
        )
      )}

      {/* Section header */}
      {!collapsed ? (
        <button
          onClick={onToggleSection}
          aria-expanded={!sectionCollapsed}
          aria-controls={`nav-section-${group.title}`}
          className={[
            "flex items-center justify-between w-full bg-transparent border-none cursor-pointer",
            "px-4 pt-5 pb-1",
            groupIndex === 0 ? "pt-2" : "",
          ].join(" ")}
        >
          <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-muted-foreground/60">
            {group.title}
          </span>
          <ChevronDown
            size={11}
            className={`text-muted-foreground/50 shrink-0 transition-transform duration-200 ${sectionCollapsed ? "-rotate-90" : "rotate-0"}`}
          />
        </button>
      ) : null}

      {/* Section content */}
      {!sectionCollapsed && (
        <div id={`nav-section-${group.title}`}>{children}</div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Sidebar component
// ---------------------------------------------------------------------------

export function Sidebar() {
  const pathname = usePathname();
  const { theme, toggle } = useTheme();
  const { user, logout, isAuthenticated } = useAuth();
  const { branding } = useTenantBranding();

  const { data: emrStatus, isLoading: emrLoading } = useQuery({
    queryKey: ["emr-status"],
    queryFn: () => getEmrStatus(),
    refetchInterval: 60_000,
    retry: 1,
  });

  const isDark = theme === "dark";

  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [showShortcutHints, setShowShortcutHints] = useState(false);

  // Per-section collapse state — keyed by title, persisted in localStorage
  const [sectionCollapsed, setSectionCollapsed] = useState<Record<string, boolean>>(() => {
    try {
      const saved = typeof window !== "undefined" ? localStorage.getItem("raf-nav-sections") : null;
      if (saved) return JSON.parse(saved);
    } catch { /* noop */ }
    return Object.fromEntries(
      navGroups.filter((g) => g.defaultCollapsed).map((g) => [g.title, true])
    );
  });

  // Per-cluster collapse state — keyed by cluster label
  const [clusterCollapsed, setClusterCollapsed] = useState<Record<string, boolean>>(() => {
    const defaults: Record<string, boolean> = {};
    for (const group of navGroups) {
      for (const cluster of group.clusters ?? []) {
        if (cluster.defaultCollapsed) defaults[cluster.label] = true;
      }
    }
    return defaults;
  });

  function toggleSection(title: string) {
    setSectionCollapsed((prev) => {
      const next = { ...prev, [title]: !prev[title] };
      try { localStorage.setItem("raf-nav-sections", JSON.stringify(next)); } catch { /* noop */ }
      return next;
    });
  }

  function toggleCluster(label: string) {
    setClusterCollapsed((prev) => ({ ...prev, [label]: !prev[label] }));
  }

  // Keyboard shortcut hint detection
  useEffect(() => {
    const refresh = () => setShowShortcutHints(hasUsedKeyboardShortcuts());
    refresh();
    window.addEventListener("raf-kb-used", refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener("raf-kb-used", refresh);
      window.removeEventListener("storage", refresh);
    };
  }, []);

  // Close mobile drawer on route change
  const [prevPathname, setPrevPathname] = useState(pathname);
  if (prevPathname !== pathname) {
    setPrevPathname(pathname);
    if (mobileOpen) setMobileOpen(false);
  }

  // Close mobile drawer on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileOpen(false);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  function isActive(href: string): boolean {
    if (href === "/") return pathname === "/";
    return pathname === href || pathname.startsWith(href + "/");
  }

  function handleLogout() {
    logout();
  }

  const role = (user as { role?: string } | null)?.role ?? "";

  function filterItems(items: NavItem[]): NavItem[] {
    return items.filter((it) => {
      if (!it.visibleToRoles || it.visibleToRoles.length === 0) return true;
      return it.visibleToRoles.includes(role);
    });
  }

  // ---------------------------------------------------------------------------
  // Render helpers
  // ---------------------------------------------------------------------------

  function renderItem(item: NavItem) {
    return (
      <SidebarItem
        key={item.href}
        item={item}
        collapsed={collapsed}
        isActive={isActive(item.href)}
        showShortcutHints={showShortcutHints}
        userRole={role}
      />
    );
  }

  function renderGroup(group: NavGroup, groupIndex: number) {
    // In collapsed mode, sections are always shown (no room for toggle controls)
    const isSectionCollapsed = !collapsed && !!sectionCollapsed[group.title];

    const sectionContent = group.clusters
      ? group.clusters.map((cluster, ci) => {
          // Cluster-level role gate
          if (cluster.visibleToRoles && !cluster.visibleToRoles.includes(role)) return null;
          const filteredItems = filterItems(cluster.items);
          if (filteredItems.length === 0) return null;

          const isClusterCollapsed = !collapsed && !!clusterCollapsed[cluster.label];

          return (
            <SidebarCluster
              key={cluster.label}
              cluster={cluster}
              clusterIndex={ci}
              collapsed={collapsed}
              clusterCollapsed={isClusterCollapsed}
              onToggle={() => toggleCluster(cluster.label)}
            >
              {filteredItems.map(renderItem)}
            </SidebarCluster>
          );
        })
      : filterItems(group.items ?? []).map(renderItem);

    return (
      <SidebarSection
        key={group.title}
        group={group}
        groupIndex={groupIndex}
        collapsed={collapsed}
        sectionCollapsed={isSectionCollapsed}
        onToggleSection={() => toggleSection(group.title)}
      >
        {sectionContent}
      </SidebarSection>
    );
  }

  // ---------------------------------------------------------------------------
  // Shared sidebar content
  // ---------------------------------------------------------------------------

  const sidebarContent = (
    <>
      {/* Logo header */}
      <div
        className={[
          "flex items-center h-16 shrink-0 border-b border-sidebar-border",
          collapsed ? "justify-center px-0" : "justify-start px-4 gap-2",
        ].join(" ")}
      >
        {collapsed ? (
          <div className="relative flex items-center justify-center">
            <div className="sidebar-logo-glow absolute inset-[-4px] rounded-[10px] bg-[radial-gradient(circle,hsl(var(--sidebar-primary)/0.25),transparent_70%)] blur-[6px]" />
            <div className="relative flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-sidebar-primary to-primary text-primary-foreground">
              <HeartPulse size={18} />
            </div>
          </div>
        ) : (
          <>
            <div className="relative flex items-center justify-center shrink-0">
              <div className="sidebar-logo-glow absolute inset-[-6px] rounded-[14px] bg-[radial-gradient(circle,hsl(var(--sidebar-primary)/0.3),transparent_70%)] blur-[8px]" />
              <div className="relative flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-br from-sidebar-primary to-primary text-primary-foreground shadow-[0_2px_12px_hsl(var(--sidebar-primary)/0.25)]">
                <HeartPulse size={18} />
              </div>
            </div>
            <div>
              <div className="flex items-baseline gap-1">
                <span
                  data-testid="sidebar-logo-text"
                  className="text-[17px] font-extrabold text-sidebar-accent-foreground tracking-tight"
                >
                  {branding.logo_text || "Acme Health"}
                </span>
              </div>
              <div className="text-[10px] text-muted-foreground font-semibold -mt-0.5 uppercase tracking-[0.05em]">
                {branding.display_name || "Clinical Intelligence"}
              </div>
            </div>
          </>
        )}
      </div>

      {/* Search + Notifications row */}
      <div
        className={[
          "flex items-center shrink-0",
          collapsed ? "gap-0 m-2 mt-2" : "gap-1.5 mx-2.5 mt-2",
        ].join(" ")}
      >
        <button
          onClick={() => window.dispatchEvent(new CustomEvent("open-command-palette"))}
          title="Search (⌘K)"
          aria-label="Open command palette (Cmd+K)"
          className={[
            "group flex items-center h-[38px] rounded-[7px] cursor-pointer",
            "bg-sidebar-accent/60 border border-sidebar-border text-sidebar-foreground text-[13px]",
            "transition-all duration-200 hover:bg-sidebar-accent hover:border-border",
            collapsed
              ? "justify-center w-8 p-0 flex-none"
              : "justify-start flex-1 gap-2 px-2.5",
          ].join(" ")}
        >
          <Search size={15} className="shrink-0 text-sidebar-foreground" aria-hidden />
          {!collapsed && (
            <>
              <span className="flex-1 text-left text-sidebar-foreground">Search…</span>
              <kbd className="text-[10px] text-muted-foreground bg-muted/50 border border-border rounded-[3px] px-[5px] py-0 font-[inherit] shrink-0 leading-[1.8]">
                ⌘K
              </kbd>
            </>
          )}
        </button>
        <NotificationCenter collapsed={collapsed} />
      </div>

      {/* Collapse toggle — desktop only */}
      <div
        className={[
          "hidden lg:flex items-center h-9 shrink-0",
          collapsed ? "justify-center" : "justify-end pr-2",
        ].join(" ")}
      >
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="p-1.5 rounded bg-transparent border-none cursor-pointer text-muted-foreground hover:text-foreground hover:bg-muted transition-colors duration-150"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? <PanelLeft size={16} /> : <PanelLeftClose size={16} />}
        </button>
      </div>

      {/* Navigation */}
      <TooltipProvider delayDuration={300}>
        <nav
          className="flex-1 overflow-y-auto pt-1 pb-2"
          role="navigation"
          aria-label="Main navigation"
        >
          {navGroups.map((group, i) => renderGroup(group, i))}
        </nav>
      </TooltipProvider>

      {/* Keyboard shortcut hint */}
      {!collapsed && (
        <div
          className="mt-auto px-3.5 pt-1.5 pb-1 text-[11px] text-muted-foreground flex items-center gap-1"
          aria-label="Press ? to open keyboard shortcuts"
        >
          Press{" "}
          <kbd className="inline-block px-[5px] py-0 border border-border rounded bg-muted/40 text-[11px] font-mono text-muted-foreground leading-[1.7]">
            ?
          </kbd>{" "}
          for shortcuts
        </div>
      )}

      {/* Footer: EMR status, theme toggle, tenant switcher, user profile, version */}
      <div
        className={[
          "shrink-0 border-t border-sidebar-border",
          collapsed ? "px-1 py-2" : "px-3 py-2",
        ].join(" ")}
      >
        {/* EMR Connection Status — pill badge */}
        <div className={["flex mb-2", collapsed ? "justify-center" : "justify-start pl-0.5"].join(" ")}>
          <Link
            href="/emr-config"
            title={emrLoading ? "EMR: Checking…" : emrStatus?.connected ? "EMR Connected" : "EMR Disconnected"}
            aria-label={emrLoading ? "EMR checking" : emrStatus?.connected ? "EMR Connected — click to configure" : "EMR Disconnected — click to configure"}
            className={[
              "inline-flex items-center gap-1.5 no-underline cursor-pointer",
              "rounded-full border transition-colors duration-150",
              collapsed ? "w-6 h-6 justify-center px-0" : "px-2.5 py-[3px]",
              emrLoading
                ? "border-border/50 bg-muted/40 text-muted-foreground hover:bg-muted"
                : emrStatus?.connected
                  ? "border-green-500/30 bg-green-500/10 text-green-600 dark:text-green-400 hover:bg-green-500/20"
                  : "border-red-500/30 bg-red-500/10 text-red-600 dark:text-red-400 hover:bg-red-500/20",
            ].join(" ")}
          >
            <span
              className={[
                "rounded-full shrink-0 transition-colors duration-300",
                collapsed ? "w-2 h-2" : "w-1.5 h-1.5",
                emrLoading
                  ? "bg-muted-foreground"
                  : emrStatus?.connected
                    ? "bg-green-500 emr-pulse"
                    : "bg-red-500",
              ].join(" ")}
            />
            {!collapsed && (
              <span className="text-[11px] font-medium leading-none">
                {emrLoading ? "Checking…" : emrStatus?.connected ? "Connected" : "Disconnected"}
              </span>
            )}
          </Link>
        </div>

        {/* Theme toggle */}
        <button
          onClick={toggle}
          className={[
            "flex items-center gap-2 w-full h-8 bg-transparent border-none cursor-pointer",
            "text-sidebar-foreground text-[12px] rounded mb-1 transition-colors duration-150 hover:bg-sidebar-accent",
            collapsed ? "justify-center px-0" : "justify-start pl-1",
          ].join(" ")}
          aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
          aria-pressed={isDark}
          title={collapsed ? (isDark ? "Light mode" : "Dark mode") : undefined}
        >
          {isDark ? <Sun size={16} /> : <Moon size={16} />}
          {!collapsed && (
            <>
              <span className="flex-1">{isDark ? "Light mode" : "Dark mode"}</span>
              {/* Toggle switch indicator */}
              <span
                role="presentation"
                data-state={isDark ? "on" : "off"}
                className={[
                  "inline-flex items-center w-8 h-[18px] rounded-full px-0.5 shrink-0 transition-colors duration-200",
                  isDark ? "bg-sidebar-primary" : "bg-muted-foreground/30",
                ].join(" ")}
              >
                <span
                  className={[
                    "w-3.5 h-3.5 rounded-full bg-white shrink-0 transition-transform duration-200",
                    isDark ? "translate-x-3.5" : "translate-x-0",
                  ].join(" ")}
                />
              </span>
            </>
          )}
        </button>

        {/* Tenant switcher (admin only, expanded only) */}
        {user?.role === "admin" && (
          <TenantSwitcher collapsed={collapsed} />
        )}

        {/* User profile row */}
        <div
          className={[
            "flex items-center gap-2 mt-1.5 rounded-[10px]",
            "bg-sidebar-accent/50 border border-sidebar-border/60 transition-colors duration-200",
            collapsed ? "justify-center px-1 py-1.5" : "justify-start px-2 py-2",
          ].join(" ")}
        >
          {/* Avatar */}
          <div
            className="w-8 h-8 rounded-full bg-sidebar-primary text-sidebar-primary-foreground text-[12px] font-semibold flex items-center justify-center shrink-0 overflow-hidden"
            title={collapsed ? getUserDisplayName(user) : undefined}
          >
            {user?.avatar_url && user.avatar_url.startsWith("https://") ? (
              <img
                src={user.avatar_url}
                alt={getUserDisplayName(user)}
                className="w-8 h-8 rounded-full object-cover"
              />
            ) : (
              getUserInitials(user?.first_name, user?.last_name)
            )}
          </div>

          {/* Name + role */}
          {!collapsed && (
            <div className="flex-1 min-w-0">
              <div className="text-[13px] font-medium text-sidebar-accent-foreground overflow-hidden text-ellipsis whitespace-nowrap">
                {getUserDisplayName(user)}
              </div>
              <div className="text-[11px] text-muted-foreground overflow-hidden text-ellipsis whitespace-nowrap">
                {role || "User"}
              </div>
            </div>
          )}

          {/* Logout — inline when expanded */}
          {!collapsed && isAuthenticated && (
            <button
              onClick={handleLogout}
              className="p-1 bg-transparent border-none cursor-pointer text-muted-foreground hover:text-foreground rounded flex items-center transition-colors duration-150"
              aria-label="Sign out"
              title="Sign out"
            >
              <LogOut size={15} />
            </button>
          )}
        </div>

        {/* Logout — standalone when collapsed */}
        {collapsed && isAuthenticated && (
          <button
            onClick={handleLogout}
            className="flex items-center justify-center w-full h-8 bg-transparent border-none cursor-pointer text-muted-foreground hover:text-foreground rounded transition-colors duration-150"
            aria-label="Sign out"
            title="Sign out"
          >
            <LogOut size={15} />
          </button>
        )}

        {/* Version */}
        <div className={`pt-1.5 ${collapsed ? "text-center" : "pl-1"}`}>
          <span
            className="text-[10px] text-muted-foreground/60 font-mono"
            title={`Build ${process.env.NEXT_PUBLIC_BUILD_ID || "dev"} — ${process.env.NEXT_PUBLIC_BUILD_TIME || "unknown"}`}
          >
            v2.0 · {(process.env.NEXT_PUBLIC_BUILD_ID || "dev").slice(0, 7)}
          </span>
        </div>
      </div>
    </>
  );

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <>
      {/* Keyframe animations */}
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
        className="fixed left-4 top-4 z-50 flex h-11 w-11 items-center justify-center rounded-lg shadow-lg lg:hidden bg-sidebar border border-sidebar-border"
        aria-label="Open navigation menu"
        aria-expanded={mobileOpen}
        aria-controls="mobile-sidebar"
      >
        <Menu size={20} className="text-sidebar-accent-foreground" />
      </button>

      {/* Mobile backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm lg:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Mobile sidebar */}
      <aside
        id="mobile-sidebar"
        className={`fixed left-0 top-0 z-50 lg:hidden flex flex-col h-full bg-sidebar transition-transform duration-300 ease-out ${mobileOpen ? "translate-x-0" : "-translate-x-full"}`}
        style={{ width: EXPANDED_WIDTH }}
        aria-label="Mobile navigation"
        inert={!mobileOpen}
      >
        {/* Close button */}
        <div className="absolute right-2.5 top-2.5 z-10">
          <button
            onClick={() => setMobileOpen(false)}
            className="p-1 bg-transparent border-none cursor-pointer text-muted-foreground flex items-center rounded hover:text-foreground transition-colors duration-150"
            aria-label="Close navigation menu"
          >
            <X size={20} />
          </button>
        </div>
        {sidebarContent}
      </aside>

      {/* Desktop sidebar */}
      <aside
        className="fixed left-0 top-0 z-30 hidden lg:flex flex-col h-full overflow-hidden bg-sidebar transition-[width] duration-300 ease-[cubic-bezier(0.4,0,0.2,1)]"
        style={{ width: collapsed ? COLLAPSED_WIDTH : EXPANDED_WIDTH }}
        aria-label="Main navigation sidebar"
      >
        {sidebarContent}
      </aside>
    </>
  );
}

// ---------------------------------------------------------------------------
// Hook — returns current desktop sidebar width for main-content offsetting
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
