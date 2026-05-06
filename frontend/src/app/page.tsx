"use client";

import type React from "react";
import { useAuth } from "@/contexts/auth-context";
import { AdminDashboard } from "@/components/dashboards/AdminDashboard";
import { CoderDashboard } from "@/components/dashboards/CoderDashboard";
import { ProviderDashboard } from "@/components/dashboards/ProviderDashboard";
import { AIHealthBanner } from "@/components/AIHealthBanner";

export default function DashboardOrchestrator() {
  const { user, isLoading } = useAuth();

  if (isLoading || !user) {
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground" role="status" aria-label="Loading dashboard">
        <div className="animate-pulse flex items-center gap-2" aria-hidden="true">
          <div className="w-4 h-4 rounded-full bg-slate-300" />
          <div className="w-4 h-4 rounded-full bg-slate-300" />
          <div className="w-4 h-4 rounded-full bg-slate-300" />
        </div>
      </div>
    );
  }

  // Pick the dashboard segment by role (enforces Minimum Necessary Information).
  let Dashboard: React.ComponentType;
  if (user.role === "admin" || user.role === "manager" || user.role === "auditor") {
    Dashboard = AdminDashboard;
  } else if (user.role === "coder") {
    Dashboard = CoderDashboard;
  } else if (user.role === "provider" || user.role === "clinician") {
    Dashboard = ProviderDashboard;
  } else {
    Dashboard = ProviderDashboard; // fallback
  }

  return (
    <>
      <AIHealthBanner />
      <Dashboard />
    </>
  );
}
