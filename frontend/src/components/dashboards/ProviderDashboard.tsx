"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { CheckCircle, Users, Activity, FileText, Inbox } from "lucide-react";
import { PageHeader, SectionHeader, StatCard } from "@/components/healthcare-ui";
import { getDashboardStats } from "@/lib/api";
import { SkeletonCard } from "@/components/ui/loading";

interface ProviderDashboardStats {
  total_patients?: number;
  average_raf_score?: number;
  [key: string]: unknown;
}

function ShimmerBar({ w, h }: { w: string | number; h: number }) {
  return (
    <div
      style={{
        width: w,
        height: h,
        borderRadius: 6,
        background: "linear-gradient(90deg, #E2E8F0 25%, #EDF2F7 50%, #E2E8F0 75%)",
        backgroundSize: "200% 100%",
        animation: "shimmer 1.5s ease-in-out infinite",
      }}
    />
  );
}

function WorkflowSkeleton() {
  return (
    <div className="provider-dash-workflows">
      {[1, 2].map((i) => (
        <div key={i} className="bg-white border border-border/40 rounded-2xl p-6 shadow-sm">
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
            <ShimmerBar w={24} h={24} />
            <ShimmerBar w={120} h={18} />
          </div>
          <ShimmerBar w="90%" h={14} />
          <div style={{ height: 6 }} />
          <ShimmerBar w="70%" h={14} />
        </div>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <div
      style={{
        textAlign: "center",
        padding: "48px 24px",
        background: "#F9FAFB",
        borderRadius: 16,
        border: "1px dashed #E2E8F0",
      }}
    >
      <Inbox size={40} color="#94A3B8" style={{ margin: "0 auto 12px", display: "block" }} />
      <h3 style={{ margin: "0 0 6px", fontSize: 16, fontWeight: 700, color: "#0F172A" }}>
        No provider data yet
      </h3>
      <p style={{ margin: 0, fontSize: 14, color: "#64748B", lineHeight: 1.6, maxWidth: 380, marginInline: "auto" }}>
        Patient and RAF data will appear here once records have been imported. Visit the{" "}
        <Link href="/patients" style={{ color: "#2563EB", fontWeight: 600, textDecoration: "none" }}>
          Patients
        </Link>{" "}
        page to get started.
      </p>
    </div>
  );
}

export function ProviderDashboard() {
  const { data: stats, isLoading } = useQuery<ProviderDashboardStats>({
    queryKey: ["dashboard", "stats"],
    queryFn: () => getDashboardStats() as unknown as ProviderDashboardStats,
  });

  const hasData = stats && (stats.total_patients != null && stats.total_patients > 0);

  return (
    <div className="fade-in-up">
      <style>{`
        .provider-dash-stats {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 20px;
          margin-bottom: 32px;
        }
        .provider-dash-workflows {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 20px;
          margin-top: 16px;
        }
        @media (max-width: 1024px) {
          .provider-dash-stats {
            grid-template-columns: repeat(2, 1fr);
          }
        }
        @media (max-width: 640px) {
          .provider-dash-stats {
            grid-template-columns: 1fr;
          }
          .provider-dash-workflows {
            grid-template-columns: 1fr;
          }
        }
      `}</style>

      <PageHeader
        title="Provider Dashboard"
        subtitle="Review your patient panel, RAF compliance scorecard, and missing care gaps."
      />

      <div style={{ paddingBottom: 24 }} />

      {isLoading ? (
        <>
          <SkeletonCard columns={3} />
          <SectionHeader title="Your Workflows" />
          <WorkflowSkeleton />
        </>
      ) : !hasData ? (
        <EmptyState />
      ) : (
        <>
          <div className="provider-dash-stats">
            <StatCard
              label="Total Panel Patients"
              value={stats?.total_patients ?? "0"}
              subtitle="Under your care"
              icon={<Users size={20} />}
              color="#3B82F6"
              href="/patients"
              aria-label={`Total panel patients: ${stats?.total_patients ?? 0}`}
            />
            <StatCard
              label="Average Patient RAF"
              value={stats?.average_raf_score ? stats.average_raf_score.toFixed(3) : "1.000"}
              subtitle="Target: 1.200"
              icon={<Activity size={20} />}
              color="#10B981"
              aria-label={`Average patient RAF score: ${stats?.average_raf_score ? stats.average_raf_score.toFixed(3) : "1.000"}`}
            />
            <StatCard
              label="Pending Attestations"
              value={"0"}
              subtitle="Awaiting your signature"
              icon={<FileText size={20} />}
              color="#F59E0B"
              href="/attestations"
              aria-label="Pending attestations: 0"
            />
          </div>

          <SectionHeader title="Your Workflows" />
          <div className="provider-dash-workflows">
            <Link
              href="/patients"
              className="block p-6 bg-white border border-border/40 rounded-2xl shadow-sm hover:shadow-md transition"
              aria-label="View your patient panel"
            >
              <div className="flex items-center gap-3 text-sky-600 mb-2">
                <Users size={24} />
                <span className="font-semibold text-lg text-foreground">View Panel</span>
              </div>
              <p className="text-muted-foreground text-sm">
                Access clinical records, demographics, and active RAF suspects for your assigned patients.
              </p>
            </Link>
            <Link
              href="/providers"
              className="block p-6 bg-white border border-border/40 rounded-2xl shadow-sm hover:shadow-md transition"
              aria-label="View provider scorecard"
            >
              <div className="flex items-center gap-3 text-emerald-600 mb-2">
                <CheckCircle size={24} />
                <span className="font-semibold text-lg text-foreground">Provider Scorecard</span>
              </div>
              <p className="text-muted-foreground text-sm">
                Review your coding accuracy metrics, condition recapture rates, and peer benchmarks.
              </p>
            </Link>
          </div>
        </>
      )}
    </div>
  );
}
