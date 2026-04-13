"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { CheckCircle, AlertTriangle, FileText, Activity } from "lucide-react";
import { PageHeader, SectionHeader, StatCard } from "@/components/healthcare-ui";
import { getDashboardStats } from "@/lib/api";

interface CoderDashboardStats {
  total_suspects_open?: number | string;
  patients_analyzed?: number | string;
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
    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 20 }}>
      {[1, 2, 3, 4].map((i) => (
        <div key={i} className="bg-white border border-border/40 rounded-2xl p-6 shadow-sm">
          <Pulse w={100} h={14} />
          <div style={{ height: 12 }} />
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
      <PageHeader 
        title="Coder Worklist Dashboard" 
        subtitle="Review suspected conditions, missing documentation, and active queue."
      />

      <div style={{ paddingBottom: 24 }} />

      {isLoading ? (
        <KPISkeleton />
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 20, marginBottom: 32 }}>
          <StatCard
            label="Pending Suspects"
            value={stats?.total_suspects_open ?? "0"}
            subtitle="Requires Validation"
            icon={<AlertTriangle size={20} />}
            color="#F59E0B"
            href="/suspects"
          />
          <StatCard
            label="Missing Documents"
            value={"0"}
            subtitle="Follow-up needed"
            icon={<FileText size={20} />}
            color="#3B82F6"
          />
          <StatCard
            label="Analyzed Patients"
            value={stats?.patients_analyzed ?? "0"}
            subtitle="Total NLP Scanned"
            icon={<Activity size={20} />}
            color="#10B981"
            href="/patients"
          />
        </div>
      )}

      <SectionHeader title="Active Quick Links" />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginTop: 16 }}>
        <Link href="/suspects" className="block p-6 bg-white border border-border/40 rounded-2xl shadow-sm hover:shadow-md transition">
          <div className="flex items-center gap-3 text-amber-600 mb-2">
            <AlertTriangle size={24} />
            <span className="font-semibold text-lg text-foreground">Suspects Queue</span>
          </div>
          <p className="text-muted-foreground text-sm">Validations are waiting. Accept suspects to push them directly to OpenEMR.</p>
        </Link>
        <Link href="/documents" className="block p-6 bg-white border border-border/40 rounded-2xl shadow-sm hover:shadow-md transition">
          <div className="flex items-center gap-3 text-blue-600 mb-2">
            <FileText size={24} />
            <span className="font-semibold text-lg text-foreground">Document Analysis</span>
          </div>
          <p className="text-muted-foreground text-sm">Upload C-CDA or PDF files for NLP extraction and validation.</p>
        </Link>
      </div>
    </div>
  );
}
