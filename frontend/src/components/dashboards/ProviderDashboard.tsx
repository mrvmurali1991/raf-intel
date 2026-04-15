"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { CheckCircle, Users, Activity, FileText } from "lucide-react";
import { PageHeader, SectionHeader, StatCard } from "@/components/healthcare-ui";
import { getDashboardStats } from "@/lib/api";

interface ProviderDashboardStats {
  total_patients?: number;
  average_raf_score?: number;
  [key: string]: unknown;
}

function Pulse({ w, h, r = 6 }: { w: string | number; h: number; r?: number }) {
  return (
    <div
      style={{
        width: w,
        height: h,
        borderRadius: r,
        background: "linear-gradient(90deg, #E2E8F0 25%, #EDF2F7 50%, #E2E8F0 75%)",
        backgroundSize: "200% 100%",
        animation: "shimmer 1.5s ease-in-out infinite",
      }}
    />
  );
}

function KPISkeleton() {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 20 }}>
      {[1, 2, 3].map((i) => (
        <div key={i} className="bg-white border border-border/40 rounded-2xl p-6 shadow-sm">
          <Pulse w={100} h={14} />
          <div style={{ height: 12 }} />
          <Pulse w={80} h={32} />
        </div>
      ))}
    </div>
  );
}

export function ProviderDashboard() {
  const { data: stats, isLoading } = useQuery<ProviderDashboardStats>({
    queryKey: ["dashboard-stats"],
    queryFn: () => getDashboardStats() as unknown as ProviderDashboardStats,
  });

  return (
    <div className="fade-in-up">
      <PageHeader 
        title="Provider Dashboard" 
        subtitle="Review your patient panel, RAF compliance scorecard, and missing care gaps."
      />

      <div style={{ paddingBottom: 24 }} />

      {isLoading ? (
        <KPISkeleton />
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 20, marginBottom: 32 }}>
          <StatCard
            label="Total Panel Patients"
            value={stats?.total_patients ?? "0"}
            subtitle="Under your care"
            icon={<Users size={20} />}
            color="#3B82F6"
            href="/patients"
          />
          <StatCard
            label="Average Patient RAF"
            value={stats?.average_raf_score ? stats.average_raf_score.toFixed(3) : "1.000"}
            subtitle="Target: 1.200"
            icon={<Activity size={20} />}
            color="#10B981"
          />
          <StatCard
            label="Pending Attestations"
            value={"0"}
            subtitle="Awaiting your signature"
            icon={<FileText size={20} />}
            color="#F59E0B"
            href="/attestations"
          />
        </div>
      )}

      <SectionHeader title="Your Workflows" />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginTop: 16 }}>
        <Link href="/patients" className="block p-6 bg-white border border-border/40 rounded-2xl shadow-sm hover:shadow-md transition">
          <div className="flex items-center gap-3 text-sky-600 mb-2">
            <Users size={24} />
            <span className="font-semibold text-lg text-foreground">View Panel</span>
          </div>
          <p className="text-muted-foreground text-sm">Access clinical records, demographics, and active RAF suspects for your assigned patients.</p>
        </Link>
        <Link href="/providers" className="block p-6 bg-white border border-border/40 rounded-2xl shadow-sm hover:shadow-md transition">
          <div className="flex items-center gap-3 text-emerald-600 mb-2">
            <CheckCircle size={24} />
            <span className="font-semibold text-lg text-foreground">Provider Scorecard</span>
          </div>
          <p className="text-muted-foreground text-sm">Review your coding accuracy metrics, condition recapture rates, and peer benchmarks.</p>
        </Link>
      </div>
    </div>
  );
}
