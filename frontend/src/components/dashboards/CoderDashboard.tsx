"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { CheckCircle, AlertTriangle, FileText, Activity } from "lucide-react";
import { PageHeader, SectionHeader } from "@/components/healthcare-ui";
import { MetricCard } from "@/components/ui/metric-card";
import { DataQualityBanner } from "@/components/DataQualityBanner";
import { getDashboardStats } from "@/lib/api";

interface CoderDashboardStats {
  total_suspects_open?: number | string;
  patients_analyzed?: number | string;
  [key: string]: unknown;
}

function Pulse({ w, h, r = 6 }: { w: string | number; h: number; r?: number }) {
  return (
    <div
      className="shimmer"
      style={{ width: w, height: h, borderRadius: r }}
    />
  );
}

function KPISkeleton() {
  return (
    <div
      className="grid grid-cols-3 gap-5"
      aria-busy="true"
      aria-label="Loading dashboard"
      role="status"
    >
      {[1, 2, 3].map((i) => (
        <div key={i} className="rounded-lg border bg-card p-6 shadow-sm">
          <Pulse w={100} h={14} />
          <div className="h-3" />
          <Pulse w={80} h={32} />
        </div>
      ))}
    </div>
  );
}

export function CoderDashboard() {
  const { data: stats, isLoading } = useQuery<CoderDashboardStats>({
    queryKey: ["dashboard-stats"],
    queryFn: () => getDashboardStats() as unknown as CoderDashboardStats,
  });

  return (
    <div className="fade-in-up">
      <DataQualityBanner />
      <PageHeader
        title="Coder Worklist Dashboard"
        subtitle="Review suspected conditions, missing documentation, and active queue."
      />

      <div className="mt-6">
        {isLoading ? (
          <KPISkeleton />
        ) : (
          <div className="grid grid-cols-3 gap-5 mb-8">
            <MetricCard
              label="Pending Suspects"
              value={stats?.total_suspects_open ?? "0"}
              subtitle="Requires Validation"
              icon={<AlertTriangle size={18} />}
              intent="warning"
              href="/suspects"
            />
            <MetricCard
              label="Missing Documents"
              value="0"
              subtitle="Follow-up needed"
              icon={<FileText size={18} />}
              intent="default"
            />
            <MetricCard
              label="Analyzed Patients"
              value={stats?.patients_analyzed ?? "0"}
              subtitle="Total NLP Scanned"
              icon={<Activity size={18} />}
              intent="success"
              href="/patients"
            />
          </div>
        )}
      </div>

      <SectionHeader title="Active Quick Links" />
      <div className="grid grid-cols-2 gap-5 mt-4">
        <Link href="/suspects" className="block p-6 rounded-lg border bg-card shadow-sm hover:shadow-md transition-shadow">
          <div className="flex items-center gap-3 text-amber-600 mb-2">
            <AlertTriangle size={22} />
            <span className="font-semibold text-base text-foreground">Suspects Queue</span>
          </div>
          <p className="text-muted-foreground text-sm">Validations are waiting. Accept suspects to push them directly to OpenEMR.</p>
        </Link>
        <Link href="/documents" className="block p-6 rounded-lg border bg-card shadow-sm hover:shadow-md transition-shadow">
          <div className="flex items-center gap-3 text-blue-600 mb-2">
            <FileText size={22} />
            <span className="font-semibold text-base text-foreground">Document Analysis</span>
          </div>
          <p className="text-muted-foreground text-sm">Upload C-CDA or PDF files for NLP extraction and validation.</p>
        </Link>
      </div>
    </div>
  );
}
