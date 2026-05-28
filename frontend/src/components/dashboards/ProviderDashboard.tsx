"use client";

import { useQuery, useQueries } from "@tanstack/react-query";
import Link from "next/link";
import { CheckCircle, Users, Activity, FileText, Stethoscope } from "lucide-react";
import { PageHeader, SectionHeader } from "@/components/healthcare-ui";
import { MetricCard } from "@/components/ui/metric-card";
import { getDashboardStats, getKpiTrends } from "@/lib/api";
import { DataQualityBanner } from "@/components/DataQualityBanner";

interface ProviderDashboardStats {
  total_patients?: number;
  average_raf_score?: number;
  pending_attestations?: number;
  open_recapture_gaps?: number;
  total_suspects_open?: number;
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
  // Mirrors real 4-col MetricCard grid, 160px min-height to prevent CLS
  return (
    <div
      aria-busy="true"
      aria-label="Loading dashboard"
      role="status"
    >
      {/* Header bar skeleton */}
      <div className="mb-6">
        <Pulse w={220} h={26} r={8} />
        <div className="h-2" />
        <Pulse w={340} h={14} />
      </div>
      {/* 4-up KPI cards */}
      <div className="grid grid-cols-4 gap-5 mb-8">
        {[1, 2, 3, 4].map((i) => (
          <div
            key={i}
            className="rounded-lg border bg-card p-6 shadow-sm flex flex-col justify-between"
            style={{ minHeight: 160 }}
          >
            <div>
              <Pulse w={100} h={14} />
              <div className="h-3" />
              <Pulse w={80} h={32} />
            </div>
            <Pulse w={120} h={12} />
          </div>
        ))}
      </div>
      {/* "Where to start" action cards skeleton */}
      <div className="mb-2">
        <Pulse w={140} h={18} r={6} />
      </div>
      <div className="grid grid-cols-3 gap-5 mt-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="rounded-lg border bg-card p-6 shadow-sm" style={{ minHeight: 110 }}>
            <div className="flex items-center gap-2.5 mb-3">
              <Pulse w={24} h={24} r={6} />
              <Pulse w={140} h={18} />
            </div>
            <Pulse w="100%" h={14} />
            <div className="h-1.5" />
            <Pulse w="80%" h={14} />
          </div>
        ))}
      </div>
    </div>
  );
}

export function ProviderDashboard() {
  const [statsQ, kpiTrendsQ] = useQueries({
    queries: [
      {
        queryKey: ["dashboard-stats"],
        queryFn: async (): Promise<ProviderDashboardStats> => {
          const result = await getDashboardStats();
          // getDashboardStats returns DashboardStats; cast through unknown so we
          // can pluck the optional fields this dashboard renders without
          // depending on the full shape.
          const r = result as unknown as Record<string, unknown>;
          return {
            total_patients: typeof r.total_patients === "number" ? r.total_patients : undefined,
            average_raf_score: typeof r.average_raf_score === "number" ? r.average_raf_score : undefined,
            pending_attestations: typeof r.pending_attestations === "number" ? r.pending_attestations : undefined,
            open_recapture_gaps: typeof r.open_recapture_gaps === "number" ? r.open_recapture_gaps : undefined,
            total_suspects_open: typeof r.total_suspects_open === "number" ? r.total_suspects_open : undefined,
          };
        },
      },
      {
        queryKey: ["kpi-trends-12w"],
        queryFn: () => getKpiTrends(12),
        retry: 1,
        staleTime: 300_000,
      },
    ],
  });
  const stats = statsQ.data;
  const isLoading = statsQ.isLoading;
  const kpiTrends = kpiTrendsQ.data;

  return (
    <div className="fade-in-up">
      <DataQualityBanner />

      {isLoading ? (
        <KPISkeleton />
      ) : (
        <>
        <PageHeader
          title="Today's priorities"
          subtitle="Patients you should see this week, gaps to close, and your RAF performance at a glance."
        />

        <div className="mt-6">
          <div
            className="grid grid-cols-4 gap-5 mb-8"
            role="status"
            aria-live="polite"
          >
            <MetricCard
              label="Open Recapture Gaps"
              value={stats?.open_recapture_gaps ?? "—"}
              subtitle="HCCs from prior year not yet documented"
              icon={<FileText size={18} />}
              intent="danger"
              href="/recapture"
              trend={kpiTrends?.open_gaps?.length ? kpiTrends.open_gaps : undefined}
              delta={kpiTrends?.deltas?.open_gaps != null ? -(kpiTrends.deltas.open_gaps) : undefined}
              actionLink={{ label: "View worklist", href: "/worklist" }}
            />
            <MetricCard
              label="Suspect Conditions"
              value={stats?.total_suspects_open ?? "—"}
              subtitle="AI-flagged suggestions awaiting your review"
              icon={<Activity size={18} />}
              intent="warning"
              href="/suspects"
              trend={kpiTrends?.suspects?.length ? kpiTrends.suspects : undefined}
              delta={kpiTrends?.deltas?.suspects ?? undefined}
            />
            <MetricCard
              label="Panel Patients"
              value={stats?.total_patients ?? "—"}
              subtitle="Under your care"
              icon={<Users size={18} />}
              intent="default"
              href="/patients"
              trend={kpiTrends?.panel_patients?.length ? kpiTrends.panel_patients : undefined}
              delta={kpiTrends?.deltas?.panel_patients ?? undefined}
            />
            <MetricCard
              label="Average RAF"
              value={stats?.average_raf_score ? stats.average_raf_score.toFixed(3) : "—"}
              subtitle="Across your panel"
              icon={<CheckCircle size={18} />}
              intent="success"
              href="/providers"
              trend={kpiTrends?.avg_raf?.length ? kpiTrends.avg_raf : undefined}
              delta={kpiTrends?.deltas?.avg_raf ?? undefined}
            />
          </div>
        </div>

        <SectionHeader title="Where to start" />
        <div className="grid grid-cols-3 gap-5 mt-4">
          {/* primary action — teal */}
          <Link href="/worklist" className="block p-6 rounded-lg border bg-card shadow-sm hover:shadow-md transition-shadow">
            <div className="flex items-center gap-3 text-teal-700 dark:text-teal-400 mb-2">
              <Stethoscope size={22} />
              <span className="font-semibold text-base text-foreground">Today's worklist</span>
            </div>
            <p className="text-muted-foreground text-sm">
              Patients prioritized for you this week — open gaps, suspect
              conditions, and revenue at risk on a single screen.
            </p>
          </Link>
          {/* urgency / warning — amber */}
          <Link href="/recapture" className="block p-6 rounded-lg border bg-card shadow-sm hover:shadow-md transition-shadow">
            <div className="flex items-center gap-3 text-amber-600 dark:text-amber-400 mb-2">
              <FileText size={22} />
              <span className="font-semibold text-base text-foreground">Close recapture gaps</span>
            </div>
            <p className="text-muted-foreground text-sm">
              Patients with HCCs documented last year that haven't been re-coded
              this year — the highest-revenue lever in your worklist.
            </p>
          </Link>
          {/* info — slate */}
          <Link href="/suspects" className="block p-6 rounded-lg border bg-card shadow-sm hover:shadow-md transition-shadow">
            <div className="flex items-center gap-3 text-slate-600 dark:text-slate-400 mb-2">
              <Activity size={22} />
              <span className="font-semibold text-base text-foreground">Review suspect conditions</span>
            </div>
            <p className="text-muted-foreground text-sm">
              AI-suggested HCCs with KG-traced evidence chains. Approve, reject,
              or request more documentation in one click.
            </p>
          </Link>
        </div>
        </>
      )}
    </div>
  );
}
