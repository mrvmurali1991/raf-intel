"use client";

import { ErrorBoundary } from "@/components/error-boundary";
import { DataQualityBanner } from "@/components/DataQualityBanner";
import { QProgressCard } from "@/components/QProgressCard";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "@/components/ui/tooltip";
import { useQuery, useQueries, useQueryClient } from "@tanstack/react-query";
import { usePaymentYear } from "@/contexts/payment-year-context";
import { HistoricalPYBanner } from "@/components/HistoricalPYBanner";
import PageAlerts from "@/components/PageAlerts";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState, useEffect, useCallback, useRef } from "react";
import {
  Users,
  CheckCircle,
  TrendingUp,
  DollarSign,
  AlertCircle,
  RefreshCw,
  Calculator,
  Search,
  FileBarChart,
  ChevronRight,
  Heart,
  FileText,
  Stethoscope,
  Syringe,
  Shield,
  BarChart3,
  Zap,
  Clock,
  Activity,
  ArrowUpRight,
  Eye,
  Send,
  ClipboardList,
  UserCheck,
  Brain,
  Target,
  Info,
  AlertTriangle,
  Upload,
  Play,
  X,
  BookOpen,
  MapPin,
} from "lucide-react";
import api, {
  getDashboardStats,
  getDashboardTrends,
  getKpiTrends,
  getPopulationSummary,
  getRevenueOpportunity,
  getDataCompleteness,
  getPatientScorecard,
  getEmrStatus,
  connectDemoEmr,
  getProviderLeaderboard,
  getSuspectsSummary,
  getWorkflowSummary,
  isEmrDeactivatedError,
  useMetricFormula,
  getTopOpportunities,
  type TopOpportunity,
} from "@/lib/api";
import { MetricTrend } from "@/components/charts/MetricTrend";
import {
  RiskBadge,
  ProgressBar,
  SectionHeader,
  PageHeader,
} from "@/components/healthcare-ui";
import { MetricCard } from "@/components/ui/metric-card";
import {
  AnimatedNumber,
  Sparkline,
  MiniBarChart,
  WaterfallChart,
  CircularGauge,
  DateRangeSelector,
  ExportButton,
} from "@/components/dashboard-charts";
import { tokens } from "@/styles/tokens";
import { TourModal } from "./admin/TourModal";
import { OnboardingCard } from "./admin/OnboardingCard";
import { TopOpportunitiesTile } from "./admin/TopOpportunitiesTile";
import { V28HeroCard } from "./admin/V28HeroCard";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmt$(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `$${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `$${Math.round(abs / 1_000)}K`;
  return `$${Math.round(abs)}`;
}

function fmtN(v: number): string {
  return v.toLocaleString("en-US");
}

function rafColor(s: number): string {
  if (s >= 2.0) return "#EF4444";
  if (s >= 1.0) return "#F59E0B";
  return "#10B981";
}

function completenessColor(pct: number): string {
  if (pct >= 80) return "#10B981";
  if (pct >= 50) return "#F59E0B";
  return "#EF4444";
}

// HCC coefficient estimates (CMS V28 approximate)
const HCC_COEFFICIENTS: Record<string, number> = {
  "18": 0.302, "19": 0.302, "35": 0.423, "36": 0.219, "37": 0.219,
  "38": 0.160, "48": 0.191, "85": 0.323, "86": 0.191, "87": 0.145,
  "88": 0.145, "96": 0.288, "99": 0.288, "100": 0.234, "111": 0.423,
  "112": 0.288, "114": 0.246, "115": 0.246, "134": 0.191, "135": 0.191,
  "136": 0.145, "137": 0.145, "138": 0.145, "157": 0.340, "158": 0.204,
  "159": 0.204, "160": 0.160, "161": 0.160, "162": 0.302, "163": 0.302,
  "189": 0.246, "190": 0.145,
};

function getHccCoefficient(code: string): number {
  const clean = String(code).replace(/[^0-9]/g, "");
  return HCC_COEFFICIENTS[clean] ?? 0.200;
}

function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return "N/A";
  const diff = Date.now() - new Date(dateStr).getTime();
  const hours = Math.floor(diff / 3600000);
  if (hours < 1) return "< 1h ago";
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function generateSparklineData(center: number, count: number): number[] {
  if (!center || isNaN(center)) return Array(count).fill(0);
  const data: number[] = [];
  for (let i = 0; i < count; i++) {
    // Deterministic variation based on index instead of Math.random()
    const offset = Math.sin(i * 1.5) * center * 0.1;
    data.push(center + offset);
  }
  return data;
}

// ---------------------------------------------------------------------------
// Shared Styles
// ---------------------------------------------------------------------------

const card: React.CSSProperties = {
  background: "#FFFFFF",
  border: "1px solid #E5E7EB",
  borderRadius: 14,
  boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
  padding: 24,
};

const hoverCard = (e: React.MouseEvent<HTMLDivElement>, enter: boolean) => {
  if (enter) {
    // Multi-layer soft shadow for 2025-style depth
    e.currentTarget.style.boxShadow = "0 1px 2px rgba(0,0,0,0.04), 0 4px 16px rgba(0,0,0,0.08), 0 16px 40px rgba(0,0,0,0.06)";
    e.currentTarget.style.transform = "translateY(-2px) scale(1.005)";
    e.currentTarget.style.transition = "all 220ms cubic-bezier(0.34, 1.56, 0.64, 1)";
  } else {
    e.currentTarget.style.boxShadow = "0 1px 3px rgba(0,0,0,0.04)";
    e.currentTarget.style.transform = "translateY(0) scale(1)";
    e.currentTarget.style.transition = "all 200ms ease";
  }
};

// ---------------------------------------------------------------------------
// Skeleton Primitives
// ---------------------------------------------------------------------------

function Pulse({ w, h, r = 6 }: { w: string | number; h: number; r?: number }) {
  return (
    <div
      className="shimmer"
      style={{
        width: w,
        height: h,
        borderRadius: r,
      }}
    />
  );
}

function KPISkeleton() {
  // Mirrors the real bento strip: 2fr hero + 3 equal tiles, 160px min-height
  return (
    <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr", gap: 20, marginBottom: 24 }}>
      {[{ flex: true }, {}, {}, {}].map((cfg, i) => (
        <div key={i} style={{ ...card, minHeight: 160, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
          <div>
            <Pulse w={cfg.flex ? 140 : 100} h={14} />
            <div style={{ height: 14 }} />
            <Pulse w={cfg.flex ? 120 : 80} h={cfg.flex ? 40 : 32} />
          </div>
          <Pulse w={cfg.flex ? 180 : 120} h={12} />
        </div>
      ))}
    </div>
  );
}

function CardSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div style={card}>
      <Pulse w={180} h={18} />
      <div style={{ marginTop: 20, display: "flex", flexDirection: "column", gap: 16 }}>
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <Pulse w={60} h={14} />
            <Pulse w="100%" h={18} />
            <Pulse w={40} h={14} />
          </div>
        ))}
      </div>
    </div>
  );
}

/** Full-page skeleton that mirrors AdminDashboard layout to eliminate CLS. */
function DashboardSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading dashboard" role="status">
      {/* Header bar: title block + action buttons */}
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 28, flexWrap: "wrap", gap: 16 }}>
        <div>
          <Pulse w={280} h={26} r={8} />
          <div style={{ height: 10 }} />
          <Pulse w={160} h={14} />
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <Pulse w={120} h={36} r={10} />
          <Pulse w={96} h={36} r={10} />
          <Pulse w={130} h={36} r={10} />
        </div>
      </div>
      {/* 4-up KPI bento strip */}
      <KPISkeleton />
      {/* 2-column section row mirrors row-60-40 (3fr 2fr) */}
      <div style={{ display: "grid", gridTemplateColumns: "3fr 2fr", gap: 20, marginBottom: 24 }}>
        <CardSkeleton rows={4} />
        <CardSkeleton rows={3} />
      </div>
      {/* Second 2-column row mirrors row-55-45 (55% / 45%) */}
      <div style={{ display: "grid", gridTemplateColumns: "55fr 45fr", gap: 20 }}>
        <CardSkeleton rows={5} />
        <CardSkeleton rows={4} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// InfoMetricBox — small metric card with info tooltip
// ---------------------------------------------------------------------------
function InfoMetricBox({ bg, valueColor, labelColor, value, label, tooltip }: {
  bg: string; valueColor: string; labelColor: string;
  value: React.ReactNode; label: string; tooltip: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <div style={{ background: bg, borderRadius: 10, padding: "14px 16px", textAlign: "center", position: "relative" }}>
      <div style={{ fontSize: 24, fontWeight: 800, color: valueColor }}>{value}</div>
      <div style={{ fontSize: 11, color: labelColor, fontWeight: 500, display: "inline-flex", alignItems: "center", gap: 4 }}>
        {label}
        <button
          onClick={(e) => { e.preventDefault(); e.stopPropagation(); setShow(!show); }}
          style={{ border: "none", background: "none", cursor: "pointer", padding: 1, color: labelColor, opacity: 0.6, display: "flex", alignItems: "center" }}
          aria-label={`Info about ${label}`}
        >
          <Info size={12} />
        </button>
      </div>
      {show && (
        <div style={{
          position: "absolute", top: "100%", left: 0, right: 0, zIndex: 20,
          background: "#FFFFFF", border: "1px solid #E2E8F0", borderRadius: 8,
          padding: "10px 12px", fontSize: 11, lineHeight: 1.6, color: "#475569",
          textAlign: "left", boxShadow: "0 4px 12px rgba(0,0,0,0.1)", marginTop: 4,
        }}>
          {tooltip}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// CMS Sweep Deadline Widget — Dark navy 3-column focal card
// ---------------------------------------------------------------------------
function CmsSweepWidget({ revenueOpp }: { revenueOpp: number }) {
  const [daysRemaining, setDaysRemaining] = useState(0);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const now = new Date();
    const sweepDate = new Date(now.getFullYear(), 5, 30);
    if (now > sweepDate) {
      sweepDate.setFullYear(now.getFullYear() + 1);
    }
    const diffTime = Math.abs(sweepDate.getTime() - now.getTime());
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    setDaysRemaining(diffDays);
    const totalDaysInYear = 365;
    const daysPassed = totalDaysInYear - diffDays;
    setProgress(Math.max(0, Math.min(100, (daysPassed / totalDaysInYear) * 100)));
  }, []);

  return (
    <div
      className="animate-fade-in cms-sweep-hero"
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr 1fr",
        alignItems: "center",
        background: "#0F172A",
        borderRadius: 10,
        padding: "20px 28px",
        marginBottom: 24,
        gap: 0,
        boxShadow: "0 4px 24px rgba(0,0,0,0.18), inset 0 1px 0 rgba(255,255,255,0.04)",
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* Subtle teal accent bar at top */}
      <div style={{
        position: "absolute", top: 0, left: 0, right: 0, height: 3,
        background: "linear-gradient(90deg, #0D9488 0%, #14B8A6 60%, transparent 100%)",
      }} />

      {/* Left: Clock icon + title */}
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div style={{
          background: "rgba(13,148,136,0.15)",
          border: "1px solid rgba(13,148,136,0.25)",
          borderRadius: 10,
          padding: 10,
          flexShrink: 0,
        }}>
          <Clock size={20} color="#2DD4BF" />
        </div>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: "#F8FAFC", letterSpacing: "-0.01em", lineHeight: 1.2 }}>
            CMS Data Sweep Deadline
          </div>
          <div style={{ fontSize: 11, color: "rgba(248,250,252,0.55)", marginTop: 3, fontWeight: 500 }}>
            Mid-Year V24/V28 Blended Submission
          </div>
        </div>
      </div>

      {/* Center: days remaining + progress bar */}
      <div style={{ padding: "0 28px", borderLeft: "1px solid rgba(255,255,255,0.08)", borderRight: "1px solid rgba(255,255,255,0.08)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: "#2DD4BF", letterSpacing: "0.03em", textTransform: "uppercase" }}>
            {daysRemaining} Days Remaining
          </span>
          <span style={{ fontSize: 11, color: "rgba(248,250,252,0.5)", fontWeight: 500 }}>June 30th</span>
        </div>
        <div style={{ height: 7, background: "rgba(255,255,255,0.08)", borderRadius: 4, overflow: "hidden" }}>
          <div
            style={{
              height: "100%",
              width: `${progress}%`,
              background: "linear-gradient(90deg, #0D9488 0%, #2DD4BF 100%)",
              borderRadius: 4,
              transition: "width 1.2s cubic-bezier(0.4, 0, 0.2, 1)",
            }}
          />
        </div>
      </div>

      {/* Right: pending opportunity */}
      <div style={{ textAlign: "right", paddingLeft: 28 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: "rgba(248,250,252,0.5)", letterSpacing: "0.04em", textTransform: "uppercase", marginBottom: 4 }}>
          Pending Opportunity
        </div>
        <div style={{ fontSize: 26, fontWeight: 900, color: "#F8FAFC", letterSpacing: "-0.025em", fontVariantNumeric: "tabular-nums", lineHeight: 1 }}>
          {revenueOpp > 0 ? fmt$(revenueOpp) : "$0"}
        </div>
      </div>
    </div>
  );
}

// (TourModal extracted to ./admin/TourModal.tsx)
// (TopOpportunitiesTile extracted to ./admin/TopOpportunitiesTile.tsx)
// (OnboardingCard extracted to ./admin/OnboardingCard.tsx)
// (V28HeroCard extracted to ./admin/V28HeroCard.tsx)

// Main Dashboard
// ---------------------------------------------------------------------------

export function AdminDashboard() {
  const qc = useQueryClient();
  const router = useRouter();
  const { paymentYear } = usePaymentYear();
  const [demoLoading, setDemoLoading] = useState(false);
  const [showDemoConfirm, setShowDemoConfirm] = useState(false);
  const [showTour, setShowTour] = useState(false);
  const [dateRange, setDateRange] = useState("ytd");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  // After 12 s, stop waiting for slow/missing queries and show whatever is available
  const [kpiTimedOut, setKpiTimedOut] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setKpiTimedOut(true), 12_000);
    return () => clearTimeout(t);
  }, []);

  // ---- Batch 1: Core stats (critical, loads first) ----
  const [emrStatusQ, statsQ, popQ] = useQueries({
    queries: [
      { queryKey: ["emr-status"], queryFn: getEmrStatus, retry: 1, staleTime: 60_000 },
      { queryKey: ["dashboard-stats"], queryFn: getDashboardStats, retry: 1, staleTime: 60_000 },
      { queryKey: ["population-summary", paymentYear], queryFn: () => getPopulationSummary(paymentYear), retry: 1, staleTime: 60_000 },
    ],
  });
  const emrStatus = emrStatusQ.data;
  const emrStatusL = emrStatusQ.isLoading;
  const stats = statsQ.data;
  const statsL = statsQ.isLoading;
  const statsErr = statsQ.error;
  const pop = popQ.data;
  const popL = popQ.isLoading;

  const emrConnected = emrStatus?.connected ?? false;

  const handleDemoConnect = async () => {
    setDemoLoading(true);
    setShowDemoConfirm(false);
    try {
      const res = await connectDemoEmr();
      if (res.success) {
        qc.invalidateQueries();
      }
    } finally {
      setDemoLoading(false);
    }
  };

  // Show dashboard content when EMR is connected OR uploaded patient data exists.
  // Anchored to total_patients only — if API returns 0, hasData is false and
  // the OnboardingCard will render regardless of other loading flags.
  const hasData = (stats?.total_patients ?? 0) > 0;

  // Cmd+K / Ctrl+K → open tour
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setShowTour((v) => !v);
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, []);

  // ---- Batch 2: Analytics (secondary) ----
  const [revQ, dcQ, scorecardQ, trendsQ, kpiTrendsQ] = useQueries({
    queries: [
      { queryKey: ["revenue-opportunity", paymentYear], queryFn: () => getRevenueOpportunity(undefined, paymentYear), retry: 1, staleTime: 60_000 },
      { queryKey: ["data-completeness"], queryFn: getDataCompleteness, retry: 1, staleTime: 60_000 },
      { queryKey: ["patient-scorecard"], queryFn: () => getPatientScorecard(), retry: 1, staleTime: 60_000 },
      { queryKey: ["dashboard-trends"], queryFn: getDashboardTrends, retry: 1, staleTime: 60_000 },
      { queryKey: ["kpi-trends-12w"], queryFn: () => getKpiTrends(12), retry: 1, staleTime: 300_000 },
    ],
  });
  const rev = revQ.data;
  const revL = revQ.isLoading;
  const revErr = revQ.error;
  const dc = dcQ.data;
  const dcL = dcQ.isLoading;
  const scorecard = scorecardQ.data;
  const scL = scorecardQ.isLoading;
  const trends = trendsQ.data;
  const kpiTrends = kpiTrendsQ.data;

  // ---- Batch 3: Lists (tertiary) ----
  const [providersQ, suspectsQ, workflowQ] = useQueries({
    queries: [
      { queryKey: ["providers-leaderboard"], queryFn: () => getProviderLeaderboard(), retry: 1, staleTime: 60_000 },
      { queryKey: ["suspects-summary-open"], queryFn: () => getSuspectsSummary("open"), retry: 1, staleTime: 60_000 },
      { queryKey: ["workflow-summary"], queryFn: getWorkflowSummary, retry: 1, staleTime: 60_000 },
    ],
  });
  const providersData = providersQ.data;
  const suspectsData = suspectsQ.data;
  const workflowData = workflowQ.data;

  // ---- V28 portfolio summary (non-blocking, best-effort) ----
  const v28SummaryQ = useQuery<{
    total_revenue_delta: number;
    computed_patient_count: number;
    top_eroded_patients: Array<{ revenue: number }>;
  }>({
    queryKey: ["v28-impact", "portfolio", 2026],
    queryFn: async () => {
      const res = await api.get("/api/v28-impact/portfolio", { params: { year: 2026 } });
      return res.data;
    },
    staleTime: 300_000,
    retry: 1,
  });
  const v28Summary = v28SummaryQ.data;

  // ---- Top RAF Capture Opportunities (non-blocking, best-effort) ----
  const rafCaptureQ = useQuery<TopOpportunity[]>({
    queryKey: ["top-opportunities-14d"],
    queryFn: () => getTopOpportunities(14),
    staleTime: 300_000,
    retry: 1,
    enabled: hasData,
  });
  const rafCaptureOpps = rafCaptureQ.data ?? [];
  const rafCaptureL = rafCaptureQ.isLoading;

  // ---- Onboarding checklist auxiliary counts (best-effort) ----
  const attestationCountQ = useQuery<{ total: number }>({
    queryKey: ["onboarding-attestation-count"],
    queryFn: async () => {
      const res = await api.get<{ gaps?: unknown[]; total?: number }>("/api/recapture/gaps", {
        params: { status: "approved", limit: 1 },
      });
      return { total: res.data.total ?? (res.data.gaps?.length ?? 0) };
    },
    staleTime: 120_000,
    retry: 1,
  });
  const auditRunCountQ = useQuery<{ count: number }>({
    queryKey: ["onboarding-audit-run-count"],
    queryFn: async () => {
      const res = await api.get<{ runs?: unknown[]; total?: number }>("/api/radv/audit-runs");
      return { count: res.data.total ?? (res.data.runs?.length ?? 0) };
    },
    staleTime: 120_000,
    retry: 1,
  });
  const onboardingAttestCount = attestationCountQ.data?.total ?? 0;
  const onboardingAuditCount = auditRunCountQ.data?.count ?? 0;

  // Derived values
  const totalPop = stats?.total_patients ?? pop?.total_patients ?? 0;
  const analyzed = rev?.total_patients_analyzed ?? 0;
  const avgRaf = rev?.average_raf_score ?? stats?.average_raf_score ?? 0;
  const rawRevenueOpp = rev?.estimated_annual_revenue ?? 0;
  const revenueOpp = Math.abs(rawRevenueOpp);
  // Formula provenance for CFO tooltip — _meta direct field or scanned fallback
  const revMeta = useMetricFormula(rev as Record<string, unknown> | null | undefined, "estimated_annual_revenue") ?? rev?._meta ?? null;

  // Suspects count
  const suspectsCount = suspectsData?.length ?? 0;
  const suspectsPatients = useMemo(() => {
    if (!suspectsData?.length) return 0;
    return new Set(suspectsData.map((s: { patient_id: number }) => s.patient_id)).size;
  }, [suspectsData]);

  // Risk tiers from distribution
  const distribution = useMemo(() => {
    if (stats?.raf_distribution?.length) return stats.raf_distribution;
    if (pop?.raf_distribution) return pop.raf_distribution;
    return [];
  }, [stats, pop]);

  const tiers = useMemo(() => {
    let high = 0, med = 0, low = 0;
    for (const b of distribution as Array<{ range?: string; count?: number }>) {
      const r = b.range ?? "";
      const c = b.count ?? 0;
      const numMatch = r.match(/(\d+\.?\d*)/);
      const lowerBound = numMatch ? parseFloat(numMatch[1]) : 0;
      if (lowerBound >= 2.0) {
        high += c;
      } else if (lowerBound >= 1.0) {
        med += c;
      } else {
        low += c;
      }
    }
    const total = high + med + low || 1;
    return { high, med, low, total };
  }, [distribution]);

  // Top opportunities by absolute gap
  const topOpps = useMemo(() => {
    if (!scorecard?.length) return [];
    return [...scorecard]
      .filter((p) => p.gap != null && Math.abs(p.gap ?? 0) > 0)
      .sort((a, b) => Math.abs(b.gap ?? 0) - Math.abs(a.gap ?? 0))
      .slice(0, 8);
  }, [scorecard]);

  // Top HCCs sorted by revenue impact (coefficient * count)
  const topHccs = useMemo(() => {
    if (pop?.top_hccs && Array.isArray(pop.top_hccs)) {
      return ([...pop.top_hccs] as Array<{ patient_count?: number; count?: number; hcc_code?: string; hcc?: string; code?: string; description?: string; label?: string }>)
        .map((h) => ({
          ...h,
          count: (h.patient_count ?? h.count ?? 0) as number,
          code: (h.hcc_code ?? h.hcc ?? h.code ?? "0") as string,
          description: (h.description ?? h.label ?? "") as string,
          revenueImpact: ((h.patient_count ?? h.count ?? 0) as number) * getHccCoefficient((h.hcc_code ?? h.hcc ?? h.code ?? "0") as string) * 12000,
        }))
        .sort((a, b) => b.revenueImpact - a.revenueImpact)
        .slice(0, 8);
    }
    return [];
  }, [pop]);

  const maxHccRevenue = useMemo(() => {
    if (!topHccs.length) return 1;
    return Math.max(...topHccs.map((h) => h.revenueImpact ?? 0), 1);
  }, [topHccs]);

  // Trend helpers
  const analyzedTrend = useMemo(() => {
    if (!trends?.patients_analyzed?.change_pct) return undefined;
    return { value: trends.patients_analyzed.change_pct, label: "vs prior 30d" };
  }, [trends]);

  const rafTrend = useMemo(() => {
    if (!trends?.average_raf_score?.change_pct) return undefined;
    return { value: trends.average_raf_score.change_pct, label: "vs prior 30d" };
  }, [trends]);

  // Provider data — leaderboard returns a plain array with patient_count and average_raf_score
  const providers = useMemo(() => {
    const list = Array.isArray(providersData) ? providersData : (providersData as { providers?: unknown[] } | undefined)?.providers;
    if (list?.length) {
      return (list as Array<{ last_name?: string; provider_name?: string; specialty?: string; patient_count?: number; average_raf_score?: number | null; hcc_capture_rate?: number | null; coding_rate?: number | null }>).slice(0, 4).map((p) => ({
        name: p.provider_name ? `Dr. ${p.last_name || p.provider_name}` : `Dr. ${p.last_name || ""}`,
        specialty: (p.specialty || "Internal Medicine") as string,
        patients: (p.patient_count ?? 0) as number,
        avgRaf: p.average_raf_score != null ? Number(p.average_raf_score).toFixed(2) : "\u2014",
        codingRate: p.coding_rate != null ? Math.round(p.coding_rate) : p.hcc_capture_rate != null ? Math.round(p.hcc_capture_rate) : "\u2014",
      }));
    }
    return [];
  }, [providersData]);

  // Patient priority table (top 10 by revenue opp)
  const priorityPatients = useMemo(() => {
    if (!scorecard?.length) return [];
    return [...scorecard]
      .filter((p) => p.gap != null)
      .sort((a, b) => Math.abs((b.revenue_opportunity ?? b.gap ?? 0)) - Math.abs((a.revenue_opportunity ?? a.gap ?? 0)))
      .slice(0, 10);
  }, [scorecard]);

  // Waterfall chart data from top HCCs
  const waterfallData = useMemo(() => {
    return topHccs.slice(0, 5).map((h) => ({
      label: `HCC ${h.code}`,
      value: h.revenueImpact,
    }));
  }, [topHccs]);

  const handleRefresh = () => qc.invalidateQueries();

  // Error state — but skip the loud red "Unable to Load" panel when the
  // backend is just refusing clinical-data requests because EMR is off.
  // In that case the existing emrConnected branch + global banner already
  // render the right UX.
  if (statsErr && !stats && !pop && !isEmrDeactivatedError(statsErr)) {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          minHeight: "60vh",
          gap: 20,
          textAlign: "center",
          padding: 40,
        }}
      >
        <div style={{ background: "#FEF2F2", borderRadius: 14, padding: 24 }}>
          <AlertCircle size={48} color="#EF4444" />
        </div>
        <h2 className="text-foreground text-xl font-bold">
          Unable to Load Dashboard
        </h2>
        <p className="text-muted-foreground text-sm max-w-[400px]">
          The analytics service is not responding. Please verify the backend is running and try again.
        </p>
        <button
          onClick={handleRefresh}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            padding: "10px 20px",
            border: "1px solid #E5E7EB",
            borderRadius: 8,
            background: "#FFFFFF",
            color: "#1E293B",
            fontSize: 14,
            fontWeight: 500,
            cursor: "pointer",
          }}
        >
          <RefreshCw size={16} />
          Retry
        </button>
      </div>
    );
  }

  const now = new Date();
  const dateStr = now.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" });

  return (
    <ErrorBoundary fallbackTitle="Dashboard failed to load">
    <TooltipProvider delay={200}>
    <>
    {showTour && <TourModal onClose={() => setShowTour(false)} />}
    <div className="admin-dash-outer bg-background" style={{ minHeight: "100vh", padding: "28px 40px 48px", overflowX: "hidden" }}>
      {/* PageAlerts collapsed by default — banners stay accessible but deprioritized */}
      <PageAlerts defaultOpen={false}>
        <DataQualityBanner />
        <HistoricalPYBanner />
      </PageAlerts>
      <style>{`
        @keyframes shimmer {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        @keyframes fadeInUp {
          from { opacity: 0; transform: translateY(20px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes livePulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
        .fade-in-up { animation: fadeInUp 500ms ease-out both; }
        .fade-in-up-1 { animation-delay: 0ms; }
        .fade-in-up-2 { animation-delay: 100ms; }
        .fade-in-up-3 { animation-delay: 200ms; }
        .fade-in-up-4 { animation-delay: 300ms; }
        .fade-in-up-5 { animation-delay: 400ms; }
        .fade-in-up-6 { animation-delay: 500ms; }
        .shimmer {
          background: linear-gradient(90deg, #f1f5f9 25%, #e2e8f0 50%, #f1f5f9 75%);
          background-size: 400% 100%;
          animation: shimmer 1.4s ease-in-out infinite;
        }
        @media (max-width: 1024px) {
          .kpi-strip        { grid-template-columns: repeat(2, 1fr) !important; }
          .row-60-40        { grid-template-columns: 1fr !important; }
          .row-55-45        { grid-template-columns: 1fr !important; }
          .row-50-50        { grid-template-columns: 1fr !important; }
          .cms-sweep-hero   { grid-template-columns: 1fr !important; gap: 16px !important; }
          .admin-dash-outer { padding-left: 12px !important; padding-right: 12px !important; }
          .admin-dash-header { padding-left: 48px !important; }
        }
        @media (max-width: 640px) {
          .kpi-strip { grid-template-columns: 1fr !important; }
        }
      `}</style>

      {/* ── Header ── */}
      <div className="admin-dash-header" style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 16, flexWrap: "wrap", gap: 16 }}>
        <div>
          <h1 className="text-foreground font-extrabold tracking-tight leading-tight m-0" style={{ fontSize: 28 }}>
            Population Health Intelligence
          </h1>
          <span className="text-muted-foreground" style={{ fontSize: 13, marginTop: 6, display: "block" }}>{dateStr}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          {/* Tour link — subtle, top-right */}
          <button
            onClick={() => setShowTour(true)}
            aria-label="Take the product tour"
            className="text-muted-foreground text-xs font-medium hover:text-foreground transition-colors cursor-pointer border-0 bg-transparent"
          >
            <BookOpen size={12} style={{ display: "inline", marginRight: 4, verticalAlign: "middle" }} />
            Tour
          </button>
          <DateRangeSelector
            value={dateRange}
            onChange={setDateRange}
            customStart={customStart}
            customEnd={customEnd}
            onCustomChange={(s, e) => { setCustomStart(s); setCustomEnd(e); }}
          />
          <button
            onClick={handleRefresh}
            aria-label="Refresh dashboard"
            className="text-muted-foreground inline-flex items-center gap-1.5 px-[14px] py-[8px] border border-border bg-background text-[13px] font-semibold cursor-pointer rounded-lg shadow-sm transition-all duration-150 hover:bg-muted hover:border-slate-300"
          >
            <RefreshCw size={14} />
            Refresh
          </button>
          <ExportButton onExport={() => { /* future export */ }} label="Export" />
        </div>
      </div>

      {/* ── EHR Sync Status Banner ── */}
      {emrConnected && (
        <div className="flex items-center gap-3 px-4 py-2.5 rounded-lg mb-5 text-xs font-medium"
          style={{ background: "#F0FDF4", border: "1px solid #BBF7D0", color: "#166534" }}
        >
          <span
            aria-hidden="true"
            style={{
              width: 8, height: 8, borderRadius: "50%", background: "#10B981",
              animation: "livePulse 2s ease-in-out infinite",
              boxShadow: "0 0 6px rgba(16,185,129,0.4)", flexShrink: 0,
            }}
          />
          <span>
            {emrStatus?.display_name || "EHR ServiceDesk (FHIR)"} synced {timeAgo(workflowData?.last_sync_at)}&nbsp;|&nbsp;{fmtN(totalPop)} records&nbsp;|&nbsp;Last analysis: {timeAgo(workflowData?.last_analysis_at)}
          </span>
        </div>
      )}
      {!emrStatusL && !emrConnected && (
        <div style={{ marginBottom: 20 }} />
      )}

      {/* ── EMR Not Connected Banner ── */}
      {!emrStatusL && !emrConnected && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background: "linear-gradient(135deg, #FFF7ED 0%, #FFFBEB 100%)",
            border: "1px solid #FED7AA",
            borderRadius: 10,
            padding: "20px 28px",
            marginBottom: 24,
            gap: 16,
            flexWrap: "wrap",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <div style={{ background: "#FFF", borderRadius: 10, padding: 10, boxShadow: "0 1px 3px rgba(0,0,0,0.08)" }}>
              <AlertCircle size={24} color="#F59E0B" />
            </div>
            <div>
              <h3 className="text-[15px] font-bold text-amber-900 m-0">
                No EMR System Connected
              </h3>
              <p className="text-[13px] text-amber-700 mt-1 mb-0">
                Connect your EMR to see patient data, or try the demo with sample OpenEMR data.
              </p>
            </div>
          </div>
          <div style={{ display: "flex", gap: 10, flexShrink: 0 }}>
            <button
              onClick={() => setShowDemoConfirm(true)}
              disabled={demoLoading}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "9px 18px",
                border: "none",
                borderRadius: 8,
                background: "#F59E0B",
                color: "#FFFFFF",
                fontSize: 13,
                fontWeight: 600,
                cursor: demoLoading ? "wait" : "pointer",
                opacity: demoLoading ? 0.7 : 1,
              }}
            >
              {demoLoading ? <RefreshCw size={14} style={{ animation: "spin 1s linear infinite" }} /> : <Stethoscope size={14} />}
              {demoLoading ? "Connecting..." : "Try with Demo"}
            </button>
            <Link
              href="/emr-config"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "9px 18px",
                border: "1px solid #E5E7EB",
                borderRadius: 8,
                background: "#FFFFFF",
                color: "#1E293B",
                fontSize: 13,
                fontWeight: 600,
                textDecoration: "none",
                cursor: "pointer",
              }}
            >
              <Heart size={14} />
              Connect Your EMR
            </Link>
          </div>
        </div>
      )}

      {/* ── Demo Connect Confirmation Dialog ── */}
      {showDemoConfirm && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.4)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 9999,
          }}
          onClick={() => setShowDemoConfirm(false)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: "#FFFFFF",
              borderRadius: 14,
              padding: "32px",
              maxWidth: 460,
              width: "90%",
              boxShadow: "0 20px 60px rgba(0,0,0,0.15)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 20 }}>
              <div style={{ background: "#FFF7ED", borderRadius: 10, padding: 12 }}>
                <Stethoscope size={28} color="#F59E0B" />
              </div>
              <div>
                <h3 className="text-foreground text-lg font-bold m-0">
                  Connect Demo OpenEMR?
                </h3>
              </div>
            </div>
            <p className="text-muted-foreground text-sm leading-relaxed mb-2 mt-0">
              This will connect to the bundled <strong>OpenEMR</strong> demo instance with sample patient data. You can use this to explore all features of RAF Intelligence.
            </p>
            <div style={{
              background: "#F0FDF4",
              border: "1px solid #BBF7D0",
              borderRadius: 8,
              padding: "12px 14px",
              marginBottom: 24,
              fontSize: 13,
              color: "#166534",
              lineHeight: 1.5,
            }}>
              <strong>What you will get:</strong>
              <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                <li>Sample patient records from OpenEMR</li>
                <li>Clinical data, diagnoses, and encounters</li>
                <li>Full RAF scoring and AI analysis ready</li>
              </ul>
            </div>
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button
                onClick={() => setShowDemoConfirm(false)}
                style={{
                  padding: "10px 20px",
                  border: "1px solid #E5E7EB",
                  borderRadius: 8,
                  background: "#FFFFFF",
                  color: "#64748B",
                  fontSize: 14,
                  fontWeight: 500,
                  cursor: "pointer",
                }}
              >
                Cancel
              </button>
              <button
                onClick={handleDemoConnect}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "10px 24px",
                  border: "none",
                  borderRadius: 8,
                  background: "#F59E0B",
                  color: "#FFFFFF",
                  fontSize: 14,
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                <Stethoscope size={16} />
                Yes, Connect Demo
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Welcome State when not connected and no uploaded data ── */}
      {!emrStatusL && !emrConnected && !hasData && (
        <div
          style={{
            ...card,
            textAlign: "center",
            padding: "60px 40px",
            marginBottom: 24,
          }}
        >
          <div style={{ background: "#F0FDFA", borderRadius: 14, padding: 24, display: "inline-block", marginBottom: 20 }}>
            <Stethoscope size={48} color="#0D9488" />
          </div>
          <h2 className="text-foreground text-[22px] font-bold mb-2 mt-0">
            Welcome to RAF Intelligence
          </h2>
          <p className="text-muted-foreground text-[15px] leading-relaxed max-w-[480px] mx-auto mb-6 mt-0">
            Connect your EMR system to start analyzing patient data, identifying HCC coding gaps, and uncovering revenue opportunities.
          </p>
          <div style={{ display: "flex", gap: 12, justifyContent: "center" }}>
            <button
              onClick={() => setShowDemoConfirm(true)}
              disabled={demoLoading}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "12px 24px",
                border: "none",
                borderRadius: 8,
                background: "#F59E0B",
                color: "#FFFFFF",
                fontSize: 14,
                fontWeight: 600,
                cursor: demoLoading ? "wait" : "pointer",
                opacity: demoLoading ? 0.7 : 1,
              }}
            >
              {demoLoading ? <RefreshCw size={16} style={{ animation: "spin 1s linear infinite" }} /> : <Stethoscope size={16} />}
              {demoLoading ? "Connecting..." : "Try with Demo Data"}
            </button>
            <Link
              href="/emr-config"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "12px 24px",
                border: "1px solid #E5E7EB",
                borderRadius: 8,
                background: "#FFFFFF",
                color: "#1E293B",
                fontSize: 14,
                fontWeight: 600,
                textDecoration: "none",
              }}
            >
              <Heart size={16} />
              Connect Your EMR
            </Link>
          </div>
        </div>
      )}

      {(emrConnected || emrStatusL || hasData) && <>

      {/* Partial data warning */}
      {(statsErr || revErr) && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 16px", borderRadius: 10, background: "#FFFBEB", border: "1px solid #FDE68A", color: "#92400E", fontSize: 13, marginBottom: 16 }}>
          <AlertTriangle size={16} />
          <span>Some dashboard data couldn&apos;t be loaded. Displayed values may be incomplete.</span>
        </div>
      )}

      {/* ══════════════════════════════════════════════════════════════════════
          ROW 1: 5-step onboarding checklist (always shown until hidden) + KPI Strip
          ══════════════════════════════════════════════════════════════════════ */}
      {/* ── CMS Sweep Deadline Hero ── */}
      <CmsSweepWidget revenueOpp={revenueOpp} />

      {/* ── 4-KPI Strip ── */}
      <div className="fade-in-up fade-in-up-1">
      {(statsL && !kpiTimedOut) ? (
        <DashboardSkeleton />
      ) : (
        <div
          className="kpi-strip"
          role="status"
          aria-live="polite"
          style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 24 }}
        >
          {/* TOTAL MEMBERS */}
          <div style={{ ...card, minHeight: 160, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: "#64748B", textTransform: "uppercase", letterSpacing: "0.06em" }}>Total Members</span>
              <div style={{ background: "#F1F5F9", borderRadius: 8, padding: 6 }}>
                <Users size={16} color="#64748B" />
              </div>
            </div>
            <div style={{ fontSize: 36, fontWeight: 800, color: "#0F172A", fontVariantNumeric: "tabular-nums", letterSpacing: "-0.025em", lineHeight: 1 }}>
              {fmtN(totalPop)}
            </div>
            <div style={{ fontSize: 12, color: "#64748B" }}>Patients in system</div>
          </div>

          {/* PATIENTS ANALYZED */}
          <div style={{ ...card, minHeight: 160, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: "#64748B", textTransform: "uppercase", letterSpacing: "0.06em" }}>Patients Analyzed</span>
              <div style={{ background: "#F0FDF4", borderRadius: 8, padding: 6 }}>
                <CheckCircle size={16} color="#10B981" />
              </div>
            </div>
            <div style={{ fontSize: 36, fontWeight: 800, color: "#0F172A", fontVariantNumeric: "tabular-nums", letterSpacing: "-0.025em", lineHeight: 1 }}>
              {analyzed > 0 ? fmtN(analyzed) : fmtN(totalPop)}
            </div>
            <div style={{ fontSize: 12, color: "#64748B" }}>
              {totalPop > 0 ? `${Math.round(((analyzed > 0 ? analyzed : totalPop) / totalPop) * 100)}% coverage` : "No patients yet"}
            </div>
          </div>

          {/* AVERAGE RAF SCORE */}
          <div style={{ ...card, minHeight: 160, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: "#64748B", textTransform: "uppercase", letterSpacing: "0.06em" }}>Average RAF Score</span>
              <div style={{ background: "#F0FDF4", borderRadius: 8, padding: 6 }}>
                <TrendingUp size={16} color="#10B981" />
              </div>
            </div>
            <div style={{ fontSize: 36, fontWeight: 800, color: "#0F172A", fontVariantNumeric: "tabular-nums", letterSpacing: "-0.025em", lineHeight: 1 }}>
              {avgRaf > 0 ? avgRaf.toFixed(3) : "--"}
            </div>
            <div style={{ fontSize: 12, color: "#64748B" }}>
              {avgRaf === 0 ? "Pending analysis" : avgRaf < 1.0 ? "Below average acuity" : avgRaf < 1.5 ? "Moderate acuity" : "High acuity population"}
            </div>
          </div>

          {/* REVENUE OPPORTUNITY */}
          <div style={{ ...card, minHeight: 160, display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: "#64748B", textTransform: "uppercase", letterSpacing: "0.06em" }}>Revenue Opportunity</span>
              <div style={{ background: "#F0FDF4", borderRadius: 8, padding: 6 }}>
                <DollarSign size={16} color="#10B981" />
              </div>
            </div>
            <div style={{ fontSize: 36, fontWeight: 800, color: "#0F172A", fontVariantNumeric: "tabular-nums", letterSpacing: "-0.025em", lineHeight: 1 }}
              data-testid="revenue-at-risk-value"
            >
              {revenueOpp > 0 ? fmt$(revenueOpp) : "--"}
            </div>
            <div style={{ fontSize: 12, color: "#64748B" }}>
              {revenueOpp > 0 ? "Estimated annual capture" : "Run analysis to calculate"}
            </div>
          </div>
        </div>
      )}
      </div>

      {/* Chart Requests KPI Banner — RADV CMS compliance */}
      <ChartRequestsKpiBanner />

      {/* ══════════════════════════════════════════════════════════════════════
          ROW 2: Risk Stratification (50%) + Suspect Conditions (50%)
          ══════════════════════════════════════════════════════════════════════ */}
      <div
        className="row-50-50 fade-in-up fade-in-up-2"
        style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 24 }}
      >
        {/* Left: Risk Stratification */}
        {(statsL && popL) ? (
          <CardSkeleton rows={4} />
        ) : (
          <div style={{ ...card, transition: "box-shadow 0.2s, transform 0.2s" }}
            onMouseEnter={(e) => hoverCard(e, true)}
            onMouseLeave={(e) => hoverCard(e, false)}
          >
            <SectionHeader
              title="Population Risk Stratification"
              icon={<BarChart3 size={18} />}
              count={tiers.total > 1 ? tiers.total : undefined}
            />

            {/* Stacked horizontal bar */}
            {tiers.total > 1 && (
              <div style={{ marginBottom: 24 }}>
                <div
                  style={{
                    display: "flex",
                    height: 36,
                    borderRadius: 10,
                    overflow: "hidden",
                    background: "#F1F5F9",
                  }}
                >
                  {tiers.high > 0 && (
                    <Tooltip>
                      <TooltipTrigger style={{ width: `${(tiers.high / tiers.total) * 100}%`, border: "none", padding: 0, background: "none" }}>
                        <div
                          style={{
                            width: "100%",
                            height: 36,
                            background: "#DC2626",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            color: "#FFF",
                            fontSize: 12,
                            fontWeight: 700,
                            minWidth: 28,
                          }}
                        >
                          {Math.round((tiers.high / tiers.total) * 100)}%
                        </div>
                      </TooltipTrigger>
                      <TooltipContent>{tiers.high} High Risk Patients (RAF &gt;= 2.0)</TooltipContent>
                    </Tooltip>
                  )}
                  {tiers.med > 0 && (
                    <Tooltip>
                      <TooltipTrigger style={{ width: `${(tiers.med / tiers.total) * 100}%`, border: "none", padding: 0, background: "none" }}>
                        <div
                          style={{
                            width: "100%",
                            height: 36,
                            background: "#D97706",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            color: "#FFF",
                            fontSize: 12,
                            fontWeight: 700,
                            minWidth: 28,
                          }}
                        >
                          {Math.round((tiers.med / tiers.total) * 100)}%
                        </div>
                      </TooltipTrigger>
                      <TooltipContent>{tiers.med} Medium Risk Patients (RAF 1.0 - 2.0)</TooltipContent>
                    </Tooltip>
                  )}
                  {tiers.low > 0 && (
                    <Tooltip>
                      <TooltipTrigger style={{ width: `${(tiers.low / tiers.total) * 100}%`, border: "none", padding: 0, background: "none" }}>
                        <div
                          style={{
                            width: "100%",
                            height: 36,
                            background: "#059669",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            color: "#FFF",
                            fontSize: 12,
                            fontWeight: 700,
                            minWidth: 28,
                          }}
                        >
                          {Math.round((tiers.low / tiers.total) * 100)}%
                        </div>
                      </TooltipTrigger>
                      <TooltipContent>{tiers.low} Low Risk Patients (RAF &lt; 1.0)</TooltipContent>
                    </Tooltip>
                  )}
                </div>
              </div>
            )}

            {/* Tier cards */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
              {[
                { label: "High Risk", desc: "RAF >= 2.0", count: tiers.high, color: "#E11D48", bg: "#FFF1F2", border: "#FECDD3", filter: "high" },
                { label: "Medium Risk", desc: "RAF 1.0 - 2.0", count: tiers.med, color: "#D97706", bg: "#FFFBEB", border: "#FDE68A", filter: "medium" },
                { label: "Low Risk", desc: "RAF < 1.0", count: tiers.low, color: "#059669", bg: "#ECFDF5", border: "#A7F3D0", filter: "low" },
              ].map((t) => (
                <Link
                  key={t.label}
                  href={`/patients?risk=${t.filter}`}
                  style={{ textDecoration: "none", color: "inherit" }}
                >
                <div
                  style={{
                    background: t.bg,
                    border: `1px solid ${t.border}`,
                    borderRadius: 10,
                    padding: 18,
                    textAlign: "center",
                    cursor: "pointer",
                    transition: "box-shadow 0.2s, transform 0.2s",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.boxShadow = `0 4px 16px ${t.color}20`;
                    e.currentTarget.style.transform = "translateY(-2px)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.boxShadow = "none";
                    e.currentTarget.style.transform = "translateY(0)";
                  }}
                >
                  <div
                    style={{
                      width: 10,
                      height: 10,
                      borderRadius: 5,
                      background: t.color,
                      margin: "0 auto 8px",
                      boxShadow: `0 0 8px ${t.color}40`,
                    }}
                  />
                  <div className="text-[13px] font-semibold" style={{ color: t.color }}>{t.label}</div>
                  <div className="text-foreground text-[28px] font-extrabold tracking-tight my-1">
                    {fmtN(t.count)}
                  </div>
                  <div className="text-muted-foreground text-xs font-medium">
                    {tiers.total > 0 ? `${Math.round((t.count / tiers.total) * 100)}%` : "0%"} of population
                  </div>
                  <div className="text-muted-foreground text-[10px] mt-0.5">{t.desc}</div>
                </div>
                </Link>
              ))}
            </div>
          </div>
        )}

        {/* Right: Suspect Conditions Summary */}
        {scL ? (
          <CardSkeleton rows={6} />
        ) : (
          <div style={{ ...card, transition: "box-shadow 0.2s, transform 0.2s" }}
            onMouseEnter={(e) => hoverCard(e, true)}
            onMouseLeave={(e) => hoverCard(e, false)}
          >
            <SectionHeader
              title="Suspect Conditions"
              icon={<AlertCircle size={18} />}
              count={suspectsCount > 0 ? suspectsCount : undefined}
              action={
                suspectsCount > 0 ? (
                  <Link href="/suspects" style={{ fontSize: 12, fontWeight: 600, color: "#F59E0B", textDecoration: "none", display: "flex", alignItems: "center", gap: 4 }}>
                    Review All <ChevronRight size={14} />
                  </Link>
                ) : undefined
              }
            />
            {suspectsCount === 0 ? (
              <div className="text-muted-foreground text-sm py-6 text-center">
                No suspect conditions found. Run clinical analysis to identify gaps.
              </div>
            ) : (
              <div>
                {/* Summary stats */}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
                  <InfoMetricBox
                    bg="#FFFBEB"
                    valueColor="#D97706"
                    labelColor="#92400E"
                    value={suspectsCount}
                    label="Open Suspects"
                    tooltip="Conditions identified by AI analysis from clinical notes, vitals, and labs that are not yet coded in billing. Each suspect has a confidence score based on clinical evidence strength."
                  />
                  <InfoMetricBox
                    bg="#F0FDF4"
                    valueColor="#059669"
                    labelColor="#065F46"
                    value={fmt$(suspectsCount * 2800)}
                    label="Est. Revenue"
                    tooltip={`Estimated revenue if all ${suspectsCount} open suspects are confirmed and coded. Calculated as ${suspectsCount} suspects × $2,800 average per HCC. This differs from the Revenue Opportunity card which shows the total population-wide RAF gap including recapture gaps, over-coding, and all coding discrepancies.`}
                  />
                </div>
                {/* Top suspects list */}
                <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
                  {(suspectsData ?? []).slice(0, 5).map((s, i: number) => (
                    <Link key={`${s.patient_id}-${i}`} href={`/patients/${s.patient_id}`} style={{ textDecoration: "none", color: "inherit" }}>
                      <div
                        style={{
                          display: "flex", alignItems: "center", justifyContent: "space-between",
                          padding: "10px 8px", borderRadius: 6, cursor: "pointer",
                          borderBottom: i < 4 ? "1px solid #F1F5F9" : "none",
                          transition: "background 0.15s",
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.background = "#F8FAFC")}
                        onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: 8, flex: 1, minWidth: 0 }}>
                          <span style={{ fontSize: 11, fontWeight: 700, color: "#F59E0B", background: "#FFFBEB", padding: "2px 6px", borderRadius: 4, flexShrink: 0 }}>
                            HCC {(s.hcc_code as string) ?? "--"}
                          </span>
                          <span style={{ fontSize: 12, color: "#475569", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {s.icd10_code as string}
                          </span>
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
                          <span style={{
                            fontSize: 10, fontWeight: 600, padding: "2px 6px", borderRadius: 4,
                            color: ((s.confidence_score as number) ?? 0) >= 0.9 ? "#DC2626" : ((s.confidence_score as number) ?? 0) >= 0.8 ? "#D97706" : "#0F766E",
                            background: ((s.confidence_score as number) ?? 0) >= 0.9 ? "#FEF2F2" : ((s.confidence_score as number) ?? 0) >= 0.8 ? "#FFFBEB" : "#F0FDFA",
                          }}>
                            {Math.round(((s.confidence_score as number) ?? 0) * 100)}%
                          </span>
                          <ChevronRight size={14} color="#CBD5E1" />
                        </div>
                      </div>
                    </Link>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ══════════════════════════════════════════════════════════════════════
          ROW 3: Top Revenue Opportunities (50%) + Revenue Waterfall (50%)
          ══════════════════════════════════════════════════════════════════════ */}
      <div
        className="row-50-50 fade-in-up fade-in-up-3"
        style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 24 }}
      >
        {/* Left: Top Revenue Opportunities */}
        {scL ? (
          <CardSkeleton rows={8} />
        ) : (
          <div style={{ ...card, transition: "box-shadow 0.2s, transform 0.2s" }}
            onMouseEnter={(e) => hoverCard(e, true)}
            onMouseLeave={(e) => hoverCard(e, false)}
          >
            <SectionHeader
              title="Top Revenue Opportunities"
              icon={<DollarSign size={18} />}
              count={topOpps.length > 0 ? topOpps.length : undefined}
              action={
                topOpps.length > 0 ? (
                  <Link href="/reports" style={{ fontSize: 12, fontWeight: 600, color: "#2563EB", textDecoration: "none", display: "flex", alignItems: "center", gap: 4 }}>
                    View All <ChevronRight size={14} />
                  </Link>
                ) : undefined
              }
            />
            {topOpps.length === 0 ? (
              <div className="text-muted-foreground text-sm py-8 text-center">
                <Calculator size={32} color="#CBD5E1" style={{ marginBottom: 8 }} />
                <div>Run clinical analysis to identify revenue gaps.</div>
              </div>
            ) : (
              /* overflow-x: auto so fixed-width columns scroll on mobile rather than overflow the page */
              <div style={{ overflowX: "auto", WebkitOverflowScrolling: "touch" } as React.CSSProperties}>
              <div style={{ display: "flex", flexDirection: "column", gap: 0, minWidth: 360 }}>
                {/* Table header */}
                <div style={{ display: "flex", alignItems: "center", padding: "0 8px 10px", borderBottom: "1px solid #E5E7EB" }}>
                  <span className="text-muted-foreground flex-1 text-[11px] font-semibold uppercase tracking-[0.05em]">Patient</span>
                  <span className="text-muted-foreground text-[11px] font-semibold uppercase tracking-[0.05em] text-center" style={{ width: 70 }}>Billing RAF</span>
                  <span className="text-muted-foreground text-[11px] font-semibold uppercase tracking-[0.05em] text-center" style={{ width: 70 }}>TMIAB RAF</span>
                  <span className="text-muted-foreground text-[11px] font-semibold uppercase tracking-[0.05em] text-center" style={{ width: 60 }}>Gap</span>
                  <span className="text-muted-foreground text-[11px] font-semibold uppercase tracking-[0.05em] text-right" style={{ width: 80 }}>Revenue</span>
                  <span style={{ width: 20 }} />
                </div>
                {topOpps.map((p, i: number) => {
                  const absGap = Math.abs((p.gap as number) ?? 0);
                  const revOpp = Math.abs((p.revenue_opportunity as number) ?? absGap * 12000);
                  return (
                    <Link
                      key={p.pid}
                      href={`/patients/${p.pid}`}
                      style={{ textDecoration: "none", color: "inherit" }}
                    >
                      <div
                        style={{
                          display: "flex",
                          alignItems: "center",
                          padding: "11px 8px",
                          borderRadius: 8,
                          cursor: "pointer",
                          borderBottom: i < topOpps.length - 1 ? "1px solid #F8FAFC" : "none",
                          transition: "background 0.15s",
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.background = "#F8FAFC")}
                        onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                      >
                        <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
                          <span
                            style={{
                              width: 24,
                              height: 24,
                              borderRadius: 8,
                              background: i < 3 ? "#F0FDFA" : "#F8FAFC",
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                              fontSize: 11,
                              fontWeight: 700,
                              color: i < 3 ? "#0F766E" : "#64748B",
                              flexShrink: 0,
                            }}
                          >
                            {i + 1}
                          </span>
                          <span
                            style={{
                              fontSize: 13,
                              fontWeight: 600,
                              color: "#1E293B",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                            }}
                          >
                            {p.name as string}
                          </span>
                        </div>
                        <span className="text-muted-foreground" style={{ width: 70, fontSize: 12, fontWeight: 500, textAlign: "center" }}>
                          {(p.billing_raf as number) != null ? (p.billing_raf as number).toFixed(2) : "--"}
                        </span>
                        <span style={{ width: 70, fontSize: 12, fontWeight: 600, color: "#1E293B", textAlign: "center" }}>
                          {(p.ai_raf as number) != null ? (p.ai_raf as number).toFixed(2) : "--"}
                        </span>
                        <span
                          style={{
                            width: 60,
                            fontSize: 12,
                            fontWeight: 700,
                            color: "#EF4444",
                            textAlign: "center",
                          }}
                        >
                          +{(absGap ?? 0).toFixed(2)}
                        </span>
                        <span
                          style={{
                            width: 80,
                            fontSize: 13,
                            fontWeight: 700,
                            color: "#10B981",
                            textAlign: "right",
                          }}
                        >
                          {fmt$(revOpp)}
                        </span>
                        <ChevronRight size={14} color="#CBD5E1" style={{ marginLeft: 4 }} />
                      </div>
                    </Link>
                  );
                })}
              </div>
              </div>
            )}
          </div>
        )}

        {/* Right: Revenue Waterfall Chart */}
        {popL ? (
          <CardSkeleton rows={6} />
        ) : (
          <div style={{ ...card, transition: "box-shadow 0.2s, transform 0.2s" }}
            onMouseEnter={(e) => hoverCard(e, true)}
            onMouseLeave={(e) => hoverCard(e, false)}
          >
            <SectionHeader
              title="Revenue Waterfall"
              icon={<BarChart3 size={18} />}
            />
            {waterfallData.length === 0 ? (
              <div className="flex flex-col items-center gap-2 py-6 text-center">
                <p className="text-[13px] font-semibold text-foreground">
                  {totalPop === 0
                    ? "Connect EMR or upload a CSV to begin"
                    : `${analyzed > 0 ? analyzed : totalPop} patient${(analyzed > 0 ? analyzed : totalPop) !== 1 ? "s" : ""} ready — run analysis to see the revenue waterfall`}
                </p>
                {totalPop === 0 && (
                  <a
                    href="/emr-config"
                    className="inline-flex items-center justify-center rounded-lg bg-primary px-4 py-1.5 text-[13px] font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
                  >
                    Connect EMR
                  </a>
                )}
              </div>
            ) : (
              <div>
                <WaterfallChart
                  data={waterfallData}
                  totalLabel="Total Opportunity"
                  height={36}
                />
                <div className="text-muted-foreground mt-4 text-[11px] leading-snug">
                  Revenue estimated as patient count x coefficient x $12,000 base rate per condition category.
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ══════════════════════════════════════════════════════════════════════
          ROW 4: Provider Performance (50%) + Workflow Queue (50%)
          ══════════════════════════════════════════════════════════════════════ */}
      <div
        className="row-50-50 fade-in-up fade-in-up-4"
        style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 24 }}
      >
        {/* Left: Provider Performance */}
        <div style={{ ...card, transition: "box-shadow 0.2s, transform 0.2s" }}
          onMouseEnter={(e) => hoverCard(e, true)}
          onMouseLeave={(e) => hoverCard(e, false)}
        >
          <SectionHeader
            title="Provider Performance"
            icon={<UserCheck size={18} />}
            count={providers.length}
          />
          <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
            {providers.map((prov: { name: string; specialty: string; patients: number; avgRaf: string; codingRate: string | number }, idx: number) => (
              <div
                key={idx}
                style={{
                  display: "flex",
                  alignItems: "center",
                  padding: "12px 0",
                  borderBottom: idx < providers.length - 1 ? "1px solid #F8FAFC" : "none",
                }}
              >
                <div style={{ flex: 1, display: "flex", alignItems: "center", gap: 10 }}>
                  <div
                    style={{
                      width: 34,
                      height: 34,
                      borderRadius: 10,
                      background: ["#F0FDFA", "#F1F5F9", "#FFF7ED", "#F0FDF4"][idx % 4],
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 13,
                      fontWeight: 700,
                      color: ["#0F766E", "#475569", "#D97706", "#059669"][idx % 4],
                    }}
                  >
                    {prov.name.replace("Dr. ", "").charAt(0)}
                  </div>
                  <div style={{ minWidth: 0 }}>
                    <div className="text-foreground text-[13px] font-semibold">{prov.name}</div>
                    <div className="text-muted-foreground text-[11px]">{prov.specialty}</div>
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span className="text-muted-foreground" style={{ fontSize: 12, width: 32, textAlign: "center" }}>{prov.patients}</span>
                  <span
                    style={{
                      fontSize: 11,
                      fontWeight: 700,
                      color: rafColor(parseFloat(prov.avgRaf)),
                      background: `${rafColor(parseFloat(prov.avgRaf))}1A`,
                      padding: "3px 8px",
                      borderRadius: 6,
                    }}
                  >
                    {prov.avgRaf}
                  </span>
                  <Sparkline
                    data={generateSparklineData(parseFloat(prov.avgRaf), 7)}
                    width={60}
                    height={24}
                    color={rafColor(parseFloat(prov.avgRaf))}
                  />
                </div>
              </div>
            ))}
          </div>
          {/* Provider comparison bar chart */}
          <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid #F1F5F9" }}>
            <div className="text-muted-foreground text-xs font-semibold mb-2.5">Patient Distribution</div>
            <MiniBarChart
              data={providers.map((p: { name: string; patients: number }, idx: number) => ({
                label: p.name,
                value: p.patients,
                color: ["#3B82F6", "#8B5CF6", "#F59E0B", "#10B981"][idx % 4],
              }))}
              height={20}
              showValues
              animate
            />
          </div>
        </div>

        {/* Right: Workflow Queue */}
        <div style={{ ...card, transition: "box-shadow 0.2s, transform 0.2s" }}
          onMouseEnter={(e) => hoverCard(e, true)}
          onMouseLeave={(e) => hoverCard(e, false)}
        >
          <SectionHeader
            title="Workflow Queue"
            icon={<ClipboardList size={18} />}
          />
          <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
            {[
              {
                icon: Search,
                color: "#F59E0B",
                bg: "#FFFBEB",
                title: "Suspects Pending Review",
                count: workflowData?.open_suspects ?? suspectsCount,
                href: "/suspects",
              },
              {
                icon: Zap,
                color: "#EF4444",
                bg: "#FEF2F2",
                title: "High-Confidence Alerts",
                count: workflowData?.high_confidence_suspects ?? 0,
                href: "/suspects",
              },
              {
                icon: Calculator,
                color: "#8B5CF6",
                bg: "#F5F3FF",
                title: "Patients Not Analyzed",
                count: workflowData?.patients_unanalyzed ?? (totalPop - analyzed),
                href: "/analysis",
              },
              {
                icon: Activity,
                color: "#3B82F6",
                bg: "#EFF6FF",
                title: "Recent Analyses (7d)",
                count: workflowData?.recent_analyses_7d ?? 0,
                href: "/analysis",
              },
              {
                icon: UserCheck,
                color: "#10B981",
                bg: "#F0FDF4",
                title: "Active Providers",
                count: workflowData?.providers_active ?? providers.length,
                href: "/providers",
              },
            ].map((item, idx) => {
              const Icon = item.icon;
              return (
                <Link key={idx} href={item.href} style={{ textDecoration: "none", color: "inherit" }}>
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 12,
                      padding: "12px 8px",
                      borderRadius: 10,
                      borderBottom: idx < 4 ? "1px solid #F8FAFC" : "none",
                      cursor: "pointer",
                      transition: "background 0.15s",
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = "#F8FAFC")}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                  >
                    <div
                      style={{
                        width: 36,
                        height: 36,
                        borderRadius: 10,
                        background: item.bg,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        flexShrink: 0,
                      }}
                    >
                      <Icon size={16} color={item.color} />
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div className="text-foreground text-[13px] font-semibold">{item.title}</div>
                    </div>
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
                      <span style={{
                        fontSize: 13,
                        fontWeight: 700,
                        color: item.color,
                        background: item.bg,
                        padding: "4px 10px",
                        borderRadius: 8,
                        fontVariantNumeric: "tabular-nums",
                      }}>
                        {fmtN(item.count)}
                      </span>
                      <ChevronRight size={14} color="#CBD5E1" />
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>
          {/* Avg Confidence Gauge */}
          {(workflowData?.avg_confidence != null && workflowData.avg_confidence > 0) && (
            <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid #F1F5F9", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <CircularGauge
                value={Math.round((workflowData.avg_confidence as number) * 100)}
                size={100}
                strokeWidth={8}
                color="#0f766e"
                label="Avg Confidence"
              />
            </div>
          )}
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════════════════
          ROW 5: EMR Data Coverage (full width)
          ══════════════════════════════════════════════════════════════════════ */}
      {dcL ? (
        <div className="fade-in-up fade-in-up-5" style={{ marginBottom: 24 }}><CardSkeleton rows={3} /></div>
      ) : dc ? (
        <div className="fade-in-up fade-in-up-5" style={{ marginBottom: 24 }}>
          <div style={{ ...card, transition: "box-shadow 0.2s, transform 0.2s" }}
            onMouseEnter={(e) => hoverCard(e, true)}
            onMouseLeave={(e) => hoverCard(e, false)}
          >
            <SectionHeader title="EMR Data Coverage" icon={<Shield size={18} />} />
            {(() => {
              const total = dc.total_patients || 1;
              const overall = dc.completeness_score ?? 0;
              const items = [
                { label: "Billing", value: dc.patients_with_billing ?? 0, color: "#3B82F6" },
                { label: "Problems", value: dc.patients_with_problems ?? 0, color: "#EF4444" },
                { label: "Notes", value: dc.patients_with_clinical_notes ?? 0, color: "#8B5CF6" },
                { label: "Vitals", value: dc.patients_with_vitals ?? 0, color: "#10B981" },
                { label: "Immunizations", value: dc.patients_with_immunizations ?? 0, color: "#F59E0B" },
                { label: "Insurance", value: dc.patients_with_insurance ?? 0, color: "#06B6D4" },
              ];
              const barData = items.map((item) => ({
                label: item.label,
                value: Math.round((item.value / total) * 100),
                color: item.color,
              }));
              return (
                <div style={{ display: "flex", gap: 32, alignItems: "center" }}>
                  <div style={{ flexShrink: 0 }}>
                    <CircularGauge
                      value={overall}
                      size={100}
                      strokeWidth={8}
                      color={completenessColor(overall)}
                      label="Overall"
                    />
                  </div>
                  <div style={{ flex: 1 }}>
                    <MiniBarChart
                      data={barData}
                      height={22}
                      showValues
                      animate
                    />
                  </div>
                </div>
              );
            })()}
          </div>
        </div>
      ) : null}

      {/* ══════════════════════════════════════════════════════════════════════
          BELOW-FOLD: V28 Hero + Top Opportunities + Onboarding (deprioritized)
          ══════════════════════════════════════════════════════════════════════ */}
      <V28HeroCard
        v28Summary={v28Summary}
        isLoading={v28SummaryQ.isLoading}
      />

      {hasData && (
        <div className="fade-in-up fade-in-up-5">
          <TopOpportunitiesTile opportunities={rafCaptureOpps} isLoading={rafCaptureL} />
        </div>
      )}

      {!statsL && (
        <OnboardingCard
          data-testid="onboarding-card"
          emrConnected={emrConnected}
          patientCount={totalPop}
          analysisRunCount={workflowData?.recent_analyses_7d ?? 0}
          attestationCount={onboardingAttestCount}
          auditPackageCount={onboardingAuditCount}
          demoLoading={demoLoading}
          onTryDemo={() => setShowDemoConfirm(true)}
        />
      )}

      {/* ══════════════════════════════════════════════════════════════════════
          Patient Priority Table (full width)
          ══════════════════════════════════════════════════════════════════════ */}
      <div className="fade-in-up fade-in-up-6">
      {scL ? (
        <CardSkeleton rows={10} />
      ) : priorityPatients.length > 0 ? (
        <div style={{ ...card, transition: "box-shadow 0.2s, transform 0.2s" }}
          onMouseEnter={(e) => hoverCard(e, true)}
          onMouseLeave={(e) => hoverCard(e, false)}
        >
          <SectionHeader
            title="Patient Priority List"
            icon={<Target size={18} />}
            count={priorityPatients.length}
            action={
              <Link href="/patients" style={{ fontSize: 12, fontWeight: 600, color: "#2563EB", textDecoration: "none", display: "flex", alignItems: "center", gap: 4 }}>
                View All Patients <ChevronRight size={14} />
              </Link>
            }
          />
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 900 }}>
              <thead>
                <tr>
                  {["#", "Patient Name", "Age", "Sex", "Risk Level", "Billing RAF", "TMIAB RAF", "Gap", "Revenue", "HCCs", "Status"].map((h) => (
                    <th
                      key={h}
                      className="text-muted-foreground text-[11px] font-bold uppercase tracking-[0.05em] whitespace-nowrap px-3 py-2.5 border-b-2 border-border"
                      style={{ textAlign: h === "#" || h === "Patient Name" ? "left" : "center" }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {priorityPatients.map((p, idx: number) => {
                  const absGap = Math.abs((p.gap as number) ?? 0);
                  const revOpp = Math.abs((p.revenue_opportunity as number) ?? absGap * 12000);
                  const aiRaf = (p.ai_raf as number) ?? ((p.billing_raf as number) ?? 0) + absGap;
                  const riskLevel = aiRaf >= 2.0 ? "High" : aiRaf >= 1.0 ? "Medium" : "Low";
                  const rColor = aiRaf >= 2.0 ? "#EF4444" : aiRaf >= 1.0 ? "#F59E0B" : "#10B981";
                  const riskBg = aiRaf >= 2.0 ? "#FEF2F2" : aiRaf >= 1.0 ? "#FFFBEB" : "#F0FDF4";
                  return (
                    <tr
                      key={p.pid}
                      role="button"
                      tabIndex={0}
                      style={{ cursor: "pointer", transition: "background 0.15s" }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = "#F8FAFC")}
                      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
                      onClick={() => router.push(`/patients/${p.pid}`)}
                      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); router.push(`/patients/${p.pid}`); } }}
                    >
                      <td className="text-muted-foreground p-3 text-xs font-semibold border-b border-slate-100">{idx + 1}</td>
                      <td style={{ padding: "12px", borderBottom: "1px solid #F1F5F9" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span className="text-foreground text-[13px] font-semibold">{p.name as string}</span>
                          <Sparkline
                            data={generateSparklineData(aiRaf, 6)}
                            width={48}
                            height={18}
                            color={rColor}
                          />
                        </div>
                      </td>
                      <td style={{ padding: "12px", fontSize: 13, color: "#475569", textAlign: "center", borderBottom: "1px solid #F1F5F9" }}>{(p.age as number) ?? "--"}</td>
                      <td style={{ padding: "12px", fontSize: 13, color: "#475569", textAlign: "center", borderBottom: "1px solid #F1F5F9" }}>{(p.sex as string) ?? "--"}</td>
                      <td style={{ padding: "12px", textAlign: "center", borderBottom: "1px solid #F1F5F9" }}>
                        <RiskBadge score={aiRaf} size="sm" />
                      </td>
                      <td style={{ padding: "12px", fontSize: 13, fontWeight: 500, color: "#475569", textAlign: "center", borderBottom: "1px solid #F1F5F9", fontVariantNumeric: "tabular-nums" }}>
                        {(p.billing_raf as number) != null ? (p.billing_raf as number).toFixed(3) : "--"}
                      </td>
                      <td style={{ padding: "12px", fontSize: 13, fontWeight: 600, color: "#1E293B", textAlign: "center", borderBottom: "1px solid #F1F5F9", fontVariantNumeric: "tabular-nums" }}>
                        {(p.ai_raf as number) != null ? (p.ai_raf as number).toFixed(3) : "--"}
                      </td>
                      <td style={{ padding: "12px", fontSize: 13, fontWeight: 700, color: "#EF4444", textAlign: "center", borderBottom: "1px solid #F1F5F9", fontVariantNumeric: "tabular-nums" }}>
                        +{(absGap ?? 0).toFixed(3)}
                      </td>
                      <td style={{ padding: "12px", fontSize: 13, fontWeight: 700, color: "#10B981", textAlign: "center", borderBottom: "1px solid #F1F5F9" }}>
                        {fmt$(revOpp)}
                      </td>
                      <td style={{ padding: "12px", fontSize: 12, color: "#475569", textAlign: "center", borderBottom: "1px solid #F1F5F9" }}>
                        <span style={{ fontSize: 11, fontWeight: 600, color: "#0F766E", background: "#F0FDFA", padding: "2px 8px", borderRadius: 4 }}>
                          {((p.hcc_count_ai ?? p.hcc_count_billing ?? 0) as number)}
                        </span>
                      </td>
                      <td style={{ padding: "12px", textAlign: "center", borderBottom: "1px solid #F1F5F9" }}>
                        <span style={{
                          fontSize: 11,
                          fontWeight: 600,
                          color: (p.analyzed as boolean) ? "#10B981" : "#F59E0B",
                          background: (p.analyzed as boolean) ? "#F0FDF4" : "#FFFBEB",
                          padding: "3px 10px",
                          borderRadius: 6,
                        }}>
                          {(p.analyzed as boolean) ? "Analyzed" : "Pending"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
      </div>

      </>}
    </div>
    </>
    </TooltipProvider>
    </ErrorBoundary>
  );
}

// ---------------------------------------------------------------------------
// Chart Requests KPI Banner — surfaces open / overdue RADV chart pull counts
// ---------------------------------------------------------------------------

function ChartRequestsKpiBanner() {
  const [open, setOpen] = useState<number | null>(null);
  const [overdue, setOverdue] = useState<number | null>(null);

  useEffect(() => {
    // Pull summary across all audit runs for this tenant by fetching the run list
    // and aggregating chart-request summaries lazily (best-effort, never blocks render).
    let cancelled = false;
    void (async () => {
      try {
        const runsRes = await fetch("/api/radv/audit-runs", { credentials: "include" });
        if (!runsRes.ok || cancelled) return;
        const { runs } = (await runsRes.json()) as { runs: { id: number }[] };
        if (!runs?.length || cancelled) return;
        // Only look at the 3 most-recent runs to avoid N+1 on large tenants
        const slice = runs.slice(0, 3);
        const results = await Promise.allSettled(
          slice.map((r) =>
            fetch(`/api/radv/${r.id}/chart-requests`, { credentials: "include" })
              .then((res) => res.json() as Promise<{ summary: { open: number; overdue: number } }>)
          )
        );
        if (cancelled) return;
        let totalOpen = 0, totalOverdue = 0;
        for (const r of results) {
          if (r.status === "fulfilled") {
            totalOpen += r.value?.summary?.open ?? 0;
            totalOverdue += r.value?.summary?.overdue ?? 0;
          }
        }
        setOpen(totalOpen);
        setOverdue(totalOverdue);
      } catch {
        // non-blocking — banner simply stays hidden
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (open === null || open === 0) return null;

  return (
    <Link
      href="/radv?tab=chart-requests"
      style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: "10px 16px", borderRadius: 10, marginBottom: 16,
        backgroundColor: overdue && overdue > 0 ? "#FEF2F2" : "#F0FDFA",
        border: `1px solid ${overdue && overdue > 0 ? "#FECACA" : "#99F6E4"}`,
        textDecoration: "none", color: "inherit", fontSize: 13,
      }}
      aria-label="View RADV chart requests"
    >
      <ClipboardList size={16} color={overdue && overdue > 0 ? "#DC2626" : "#0D9488"} />
      <span>
        <strong style={{ color: overdue && overdue > 0 ? "#DC2626" : "#0F766E" }}>{open} chart request{open !== 1 ? "s" : ""} open</strong>
        {overdue && overdue > 0
          ? <span style={{ color: "#DC2626" }}> · {overdue} overdue</span>
          : null}
        <span style={{ color: "#64748B" }}> — RADV CMS compliance</span>
      </span>
    </Link>
  );
}
