"use client";

import { useAuth } from "@/contexts/auth-context";
import { AdminDashboard } from "@/components/dashboards/AdminDashboard";
import { CoderDashboard } from "@/components/dashboards/CoderDashboard";
import { ProviderDashboard } from "@/components/dashboards/ProviderDashboard";

export default function DashboardOrchestrator() {
  const { user, isLoading } = useAuth();
  
  if (isLoading || !user) {
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground">
        <div className="animate-pulse flex items-center gap-2">
          <div className="w-4 h-4 rounded-full bg-slate-300" />
          <div className="w-4 h-4 rounded-full bg-slate-300" />
          <div className="w-4 h-4 rounded-full bg-slate-300" />
        </div>
      </div>
    );
  }

  // Segment by Role to enforce Minimum Necessary Information (MNI)
  if (user.role === "admin" || user.role === "manager" || user.role === "auditor") {
    return <AdminDashboard />;
  }
  
  if (user.role === "coder") {
    return <CoderDashboard />;
  }
  
  if (user.role === "provider" || user.role === "clinician") {
    return <ProviderDashboard />;
  }

  // Fallback map
  return <ProviderDashboard />;
}
