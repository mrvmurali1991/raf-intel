"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { CheckCircle, Users, Activity, FileText, Stethoscope } from "lucide-react";
import { PageHeader, SectionHeader, StatCard } from "@/components/healthcare-ui";
import { getDashboardStats } from "@/lib/api";
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
        <div key={i} className="bg-card border border-border/40 rounded-2xl p-6 shadow-sm">
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
    queryFn: async () => {
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
  });

  return (
    <div className="fade-in-up">
      <DataQualityBanner />
      <PageHeader
        title="Today's priorities"
        subtitle="Patients you should see this week, gaps to close, and your RAF performance at a glance."
      />

      <div style={{ paddingBottom: 24 }} />

      {isLoading ? (
        <KPISkeleton />
      ) : (
        <div
          style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 20, marginBottom: 32 }}
          role="status"
          aria-live="polite"
        >
          <StatCard
            label="Open recapture gaps"
            value={stats?.open_recapture_gaps ?? "—"}
            subtitle="HCCs from prior year not yet documented"
            icon={<FileText size={20} />}
            color="#EF4444"
            href="/recapture"
            sparklinePlaceholder
            actionLink={{ label: "View worklist", href: "/worklist" }}
            emptyState={{
              message: "No open gaps — nice work! All HCCs are documented.",
              ctaLabel: "View recapture history",
              ctaHref: "/recapture",
            }}
          />
          <StatCard
            label="Suspect conditions"
            value={stats?.total_suspects_open ?? "—"}
            subtitle="AI-flagged suggestions awaiting your review"
            icon={<Activity size={20} />}
            color="#F59E0B"
            href="/suspects"
            sparklinePlaceholder
            emptyState={{
              message: "No suspects to review right now.",
              ctaLabel: "Run AI scan",
              ctaHref: "/suspects",
            }}
          />
          <StatCard
            label="Panel patients"
            value={stats?.total_patients ?? "—"}
            subtitle="Under your care"
            icon={<Users size={20} />}
            color="#3B82F6"
            href="/patients"
            sparklinePlaceholder
            emptyState={{
              message: "Connect your EHR to see your patient panel.",
              ctaLabel: "Set up integration",
              ctaHref: "/settings/integrations",
            }}
          />
          <StatCard
            label="Average RAF"
            value={stats?.average_raf_score ? stats.average_raf_score.toFixed(3) : "—"}
            subtitle="Across your panel"
            icon={<CheckCircle size={20} />}
            color="#10B981"
            href="/providers"
            sparklinePlaceholder
          />
        </div>
      )}

      <SectionHeader title="Where to start" />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 20, marginTop: 16 }}>
        {/* primary action — teal */}
        <Link href="/worklist" className="block p-6 bg-card border border-border/40 rounded-2xl shadow-sm hover:shadow-md transition">
          <div className="flex items-center gap-3 text-teal-700 dark:text-teal-400 mb-2">
            <Stethoscope size={24} />
            <span className="font-semibold text-lg text-foreground">Today's worklist</span>
          </div>
          <p className="text-muted-foreground text-sm">
            Patients prioritized for you this week — open gaps, suspect
            conditions, and revenue at risk on a single screen.
          </p>
        </Link>
        {/* urgency / warning — amber */}
        <Link href="/recapture" className="block p-6 bg-card border border-border/40 rounded-2xl shadow-sm hover:shadow-md transition">
          <div className="flex items-center gap-3 text-amber-600 dark:text-amber-400 mb-2">
            <FileText size={24} />
            <span className="font-semibold text-lg text-foreground">Close recapture gaps</span>
          </div>
          <p className="text-muted-foreground text-sm">
            Patients with HCCs documented last year that haven't been re-coded
            this year — the highest-revenue lever in your worklist.
          </p>
        </Link>
        {/* info — slate */}
        <Link href="/suspects" className="block p-6 bg-card border border-border/40 rounded-2xl shadow-sm hover:shadow-md transition">
          <div className="flex items-center gap-3 text-slate-600 dark:text-slate-400 mb-2">
            <Activity size={24} />
            <span className="font-semibold text-lg text-foreground">Review suspect conditions</span>
          </div>
          <p className="text-muted-foreground text-sm">
            AI-suggested HCCs with KG-traced evidence chains.  Approve, reject,
            or request more documentation in one click.
          </p>
        </Link>
      </div>
    </div>
  );
}
