"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/contexts/auth-context";
import { Sidebar } from "@/components/Sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ToastProvider } from "@/components/Toast";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { CommandPalette } from "@/components/CommandPalette";
import { KeyboardShortcuts } from "@/components/KeyboardShortcuts";
import { WelcomeWizard } from "@/components/WelcomeWizard";
import { DemoBanner } from "@/components/DemoBanner";
import { EmrDeactivatedBanner } from "@/components/EmrDeactivatedBanner";
import { SessionTimeoutWarning } from "@/components/SessionTimeoutWarning";
import { PageLoader } from "@/components/ui/loading";
import { initErrorTracking } from "@/lib/error-tracking";

// NOTE: ThemeProvider and QueryProvider are intentionally NOT imported here.
// They are mounted once in layout.tsx (root) so they remain stable across
// all route changes. Mounting them here would cause them to remount on every
// auth-state transition (login → dashboard), resetting query cache and theme.

export function AuthLayout({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading, mustChangePassword, user } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [commandOpen, setCommandOpen] = useState(false);

  const isLoginPage = pathname === "/login";
  // Cover /settings and any nested path (e.g. /settings/security)
  const isSettingsPage = pathname === "/settings" || pathname.startsWith("/settings/");

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
  }, [isLoading, isAuthenticated, isLoginPage, isSettingsPage, mustChangePassword, router]);

  // While the auth context is bootstrapping (checking stored refresh token),
  // show a full-page spinner. ThemeProvider wraps this so dark mode applies.
  if (isLoading) {
    return <PageLoader />;
  }

  // Login page — no sidebar, no shell, no redirect loop risk.
  // ThemeProvider and QueryProvider are still active (mounted in layout.tsx).
  if (isLoginPage) {
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
    return <PageLoader />;
  }

  // Authenticated — full app shell with Sidebar.
  return (
    <TooltipProvider>
      <ToastProvider>
        <Sidebar />
        <main
          id="main-content"
          className="min-h-screen transition-all duration-300 ease-out lg:ml-64 p-5 pt-16 lg:p-10 lg:pt-8"
          tabIndex={-1}
        >
          <EmrDeactivatedBanner />
          <DemoBanner />
          <ErrorBoundary isAdmin={user?.role === "admin"}>
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
