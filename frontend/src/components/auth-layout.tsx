"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/contexts/auth-context";
import { Sidebar } from "@/components/Sidebar";
import { QueryProvider } from "@/providers/query-provider";
import { ThemeProvider } from "@/providers/theme-provider";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ToastProvider } from "@/components/Toast";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Loader2 } from "lucide-react";

export function AuthLayout({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  const isLoginPage = pathname === "/login";

  useEffect(() => {
    if (!isLoading) {
      if (!isAuthenticated && !isLoginPage) {
        router.push("/login");
      } else if (isAuthenticated && isLoginPage) {
        router.push("/");
      }
    }
  }, [isLoading, isAuthenticated, isLoginPage, router]);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 via-blue-50 to-cyan-50 dark:from-slate-950 dark:via-slate-900 dark:to-slate-800">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (isLoginPage) {
    return (
      <ThemeProvider>
        {children}
      </ThemeProvider>
    );
  }

  if (!isAuthenticated) {
    return null;
  }

  return (
    <ThemeProvider>
      <QueryProvider>
        <TooltipProvider>
          <ToastProvider>
            <Sidebar />
            <main
              id="main-content"
              className="min-h-screen transition-all duration-300 ease-out lg:ml-64 p-5 pt-16 lg:p-10 lg:pt-8"
              tabIndex={-1}
            >
              <ErrorBoundary>
                {children}
              </ErrorBoundary>
            </main>
          </ToastProvider>
        </TooltipProvider>
      </QueryProvider>
    </ThemeProvider>
  );
}
