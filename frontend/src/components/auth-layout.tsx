"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/contexts/auth-context";
import { Sidebar } from "@/components/Sidebar";
import { TenantPYChip } from "@/components/TenantPYChip";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ToastProvider } from "@/components/Toast";
import { ErrorBoundary } from "@/components/error-boundary";
import { CommandPalette } from "@/components/CommandPalette";
import { KeyboardShortcuts } from "@/components/KeyboardShortcuts";
import { WelcomeWizard } from "@/components/WelcomeWizard";
import { DemoBanner } from "@/components/DemoBanner";
import { EmrDeactivatedBanner } from "@/components/EmrDeactivatedBanner";
import { SessionTimeoutWarning } from "@/components/SessionTimeoutWarning";
import { Loader2 } from "lucide-react";
import { initErrorTracking } from "@/lib/error-tracking";

// NOTE: ThemeProvider and QueryProvider are intentionally NOT imported here.
// They are mounted once in layout.tsx (root) so they remain stable across
// all route changes. Mounting them here would cause them to remount on every
// auth-state transition (login → dashboard), resetting query cache and theme.

export function AuthLayout({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading, mustChangePassword } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [commandOpen, setCommandOpen] = useState(false);

  const isLoginPage = pathname === "/login";
  // Cover /settings and any nested path (e.g. /settings/security)
  const isSettingsPage = pathname === "/settings" || pathname.startsWith("/settings/");
  // /embed/* routes render the authenticated panel inside a third-party iframe
  // (OpenEMR chart). They must NOT redirect to /login, must NOT show the sidebar
  // or header chrome, and handle their own short-lived-JWT handshake.
  const isEmbedPage = pathname.startsWith("/embed/");

  // Initialize client-side error tracking once on mount
  useEffect(() => {
    initErrorTracking();
  }, []);

  // Global Cmd+K / Ctrl+K shortcut for command palette
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setCommandOpen((prev) => !prev);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  // Listen for event-based open (from Sidebar search icon)
  useEffect(() => {
    const handler = () => setCommandOpen(true);
    window.addEventListener("open-command-palette", handler);
    return () => window.removeEventListener("open-command-palette", handler);
  }, []);

  useEffect(() => {
    if (!isLoading) {
      // Embed pages manage their own token flow — never redirect them.
      if (isEmbedPage) return;
      // NOTE: The cookie check below is purely for flash-prevention (avoiding a
      // brief redirect to /login when auth state hasn't hydrated yet). It is NOT
      // a security gate — the real auth gate is `isAuthenticated` from the auth
      // context, which validates the token server-side on each API request.
      const hasAuthCookie = typeof document !== "undefined" && document.cookie.includes("raf_authenticated=true");
      if (!isAuthenticated && !isLoginPage && !hasAuthCookie) {
        // Not authenticated, no auth cookie, and not on login — redirect to login
        router.push("/login");
      } else if (isAuthenticated && isLoginPage) {
        // Already authenticated and on login — redirect to dashboard
        router.push("/");
      } else if (isAuthenticated && mustChangePassword && !isSettingsPage) {
        // Force the user to change their password before accessing any other page
        router.push("/settings?force_password_change=true");
      }
    }
  }, [isLoading, isAuthenticated, isLoginPage, isEmbedPage, isSettingsPage, mustChangePassword, router]);

  // While the auth context is bootstrapping (checking stored refresh token),
  // show a full-page spinner. ThemeProvider wraps this so dark mode applies.
  if (isLoading) {
    return (
      <div
        className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 via-blue-50 to-cyan-50 dark:from-slate-950 dark:via-slate-900 dark:to-slate-800"
        role="status"
        aria-label="Loading application"
        aria-busy="true"
      >
        <Loader2 className="h-8 w-8 animate-spin text-primary" aria-hidden="true" />
        <span className="sr-only">Loading…</span>
      </div>
    );
  }

  // Login page — no sidebar, no shell, no redirect loop risk.
  // ThemeProvider and QueryProvider are still active (mounted in layout.tsx).
  if (isLoginPage) {
    return <>{children}</>;
  }

  // Embed page — rendered inside OpenEMR iframe. No sidebar, no chrome,
  // no auth redirect. The page itself completes the token handshake and
  // renders RAFCentralPanel directly.
  if (isEmbedPage) {
    return <>{children}</>;
  }

  // Not authenticated and not on login — check if we have a valid auth cookie
  // (set during login) before redirecting. This prevents a race condition where
  // router.push("/") fires before the auth state has propagated.
  if (!isAuthenticated) {
    const hasAuthCookie = typeof document !== "undefined" && document.cookie.includes("raf_authenticated=true");
    if (!hasAuthCookie) {
      return null;
    }
    // Auth cookie exists but state hasn't caught up — show loading instead of redirecting
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 via-blue-50 to-cyan-50 dark:from-slate-950 dark:via-slate-900 dark:to-slate-800">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  // Authenticated — full app shell with Sidebar.
  return (
    <TooltipProvider>
      <ToastProvider>
        <Sidebar />

        {/* ---------------------------------------------------------------- */}
        {/* Top bar — tenant + PY chip lives here, right-aligned             */}
        {/* Fixed at top-0, offset by sidebar width on lg screens.           */}
        {/* Height matches the pt-16 / pt-8 top-padding of <main>.           */}
        {/* ---------------------------------------------------------------- */}
        <div
          className="fixed top-0 right-0 z-20 flex items-center justify-end px-4 lg:left-64"
          style={{ height: "3.5rem" /* 56 px = pt-14 — sits under mobile hamburger row */ }}
          aria-label="App top bar"
        >
          <TenantPYChip />
        </div>

        <main
          id="main-content"
          className="min-h-screen transition-all duration-300 ease-out lg:ml-64 p-5 pt-16 lg:p-10 lg:pt-8"
          tabIndex={-1}
        >
          <EmrDeactivatedBanner />
          <DemoBanner />
          <ErrorBoundary>
            {children}
          </ErrorBoundary>
        </main>
        <CommandPalette open={commandOpen} onClose={() => setCommandOpen(false)} />
        <KeyboardShortcuts />
        <WelcomeWizard />
        <SessionTimeoutWarning />
      </ToastProvider>
    </TooltipProvider>
  );
}
