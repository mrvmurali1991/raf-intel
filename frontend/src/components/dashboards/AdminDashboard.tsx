"use client";

import { ErrorBoundary } from "@/components/error-boundary";
import { DataQualityBanner } from "@/components/DataQualityBanner";
import { QProgressCard } from "@/components/QProgressCard";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "@/components/ui/tooltip";
import { useQuery, useQueries, useQueryClient } from "@tanstack/react-query";
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
import {
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
} from "@/lib/api";
import { MetricTrend } from "@/components/charts/MetricTrend";
import {
  StatCard,
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
  borderRadius: 16,
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
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 20 }}>
      {[1, 2, 3, 4].map((i) => (
        <div key={i} style={card}>
          <Pulse w={100} h={14} />
          <div style={{ height: 12 }} />
          <Pulse w={80} h={32} />
          <div style={{ height: 8 }} />
          <Pulse w={120} h={12} />
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
// CMS Sweep Deadline Widget
// ---------------------------------------------------------------------------
function CmsSweepWidget({ revenueOpp }: { revenueOpp: number }) {
  const [daysRemaining, setDaysRemaining] = useState(0);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const now = new Date();
    // Default to end of June (Mid-Year Sweep) of current year
    const sweepDate = new Date(now.getFullYear(), 5, 30);
    if (now > sweepDate) {
      sweepDate.setFullYear(now.getFullYear() + 1);
    }
    const diffTime = Math.abs(sweepDate.getTime() - now.getTime());
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
    setDaysRemaining(diffDays);

    const totalDaysInYear = 365;
    const daysPassed = totalDaysInYear - diffDays;
    setProgress((daysPassed / totalDaysInYear) * 100);
  }, []);

  return (
    <div
      className="animate-fade-in"
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        background: tokens.warningSoft,
        border: `1px solid ${tokens.warningBorder ?? "#FDE68A"}`,
        borderRadius: 12,
        padding: "12px 20px",
        marginTop: 16,
        marginBottom: 24,
        gap: 16,
        flexWrap: "wrap",
        color: tokens.warningText ?? "#92400E",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <div style={{ background: "rgba(217, 119, 6, 0.10)", borderRadius: 8, padding: 8, border: "1px solid rgba(217, 119, 6, 0.18)" }}>
          <Clock size={18} color={tokens.riskMedium} />
        </div>
        <div>
          <h3 style={{ fontSize: 14, fontWeight: 700, margin: 0, color: tokens.warningText ?? "#92400E" }}>
            CMS Data Sweep Deadline
          </h3>
          <p style={{ fontSize: 12, color: tokens.warningText ?? "#92400E", opacity: 0.8, margin: "2px 0 0" }}>
            Mid-Year V24/V28 Blended Submission
          </p>
        </div>
      </div>

      <div style={{ flex: 1, minWidth: 200, margin: "0 12px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, marginBottom: 6, fontWeight: 500 }}>
          <span style={{ color: tokens.riskMedium, fontWeight: 600 }}>{daysRemaining} Days Remaining</span>
          <span style={{ color: tokens.warningText ?? "#92400E", opacity: 0.75 }}>June 30th</span>
        </div>
        <div style={{ height: 6, background: "rgba(217, 119, 6, 0.18)", borderRadius: 4, overflow: "hidden" }}>
          <div
            style={{
              height: "100%",
              width: `${progress}%`,
              background: tokens.riskMedium,
              borderRadius: 4,
              transition: "width 1s ease-in-out",
            }}
          />
        </div>
      </div>

      <div style={{ textAlign: "right", borderLeft: "1px solid rgba(217, 119, 6, 0.25)", paddingLeft: 20 }}>
        <div style={{ fontSize: 11, color: tokens.warningText ?? "#92400E", opacity: 0.8, fontWeight: 500, marginBottom: 2 }}>
          Pending Opportunity
        </div>
        <div style={{ fontSize: 18, fontWeight: 800, color: tokens.warningText ?? "#92400E", letterSpacing: "-0.3px" }}>
          {fmt$(revenueOpp)}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tour Modal — step-by-step guided walkthrough (Cmd+K invokable)
// ---------------------------------------------------------------------------

const TOUR_STEPS = [
  {
    title: "Population Health Intelligence",
    body: "The dashboard shows your full patient population. KPI tiles at the top surface revenue opportunity, member count, analyzed patients, and average RAF score at a glance.",
    icon: <BarChart3 size={28} color="#3B82F6" />,
    cta: null as string | null,
    ctaHref: null as string | null,
  },
  {
    title: "Connect your EMR",
    body: "Go to EMR Config to connect OpenEMR, Epic, or any FHIR-compatible source. Once connected, patients sync automatically and analysis runs on the next scheduled cycle.",
    icon: <Heart size={28} color="#EF4444" />,
    cta: "Go to EMR Config",
    ctaHref: "/emr-config",
  },
  {
    title: "Upload a Patient CSV",
    body: "No EMR? Upload a CSV of patient records directly from the Uploads page. The system maps columns automatically and ingests data within minutes.",
    icon: <Upload size={28} color="#8B5CF6" />,
    cta: "Go to Uploads",
    ctaHref: "/uploads",
  },
  {
    title: "Run RAF Analysis",
    body: "After patients are loaded, trigger an analysis run from the Analysis page. The AI engine scores each patient, surfaces HCC coding gaps, and calculates revenue opportunity.",
    icon: <Brain size={28} color="#10B981" />,
    cta: "Go to Analysis",
    ctaHref: "/analysis",
  },
  {
    title: "Review Reports",
    body: "Explore the Reports section for per-patient scorecards, HCC gap lists, provider leaderboards, and CMS sweep deadline tracking.",
    icon: <FileBarChart size={28} color="#F59E0B" />,
    cta: "Go to Reports",
    ctaHref: "/reports",
  },
];

function TourModal({ onClose }: { onClose: () => void }) {
  const [step, setStep] = useState(0);
  const router = useRouter();
  const overlayRef = useRef<HTMLDivElement>(null);
  const total = TOUR_STEPS.length;
  const current = TOUR_STEPS[step];

  const handleKey = useCallback((e: KeyboardEvent) => {
    if (e.key === "Escape") onClose();
    if (e.key === "ArrowRight" && step < total - 1) setStep((s) => s + 1);
    if (e.key === "ArrowLeft" && step > 0) setStep((s) => s - 1);
  }, [step, total, onClose]);

  useEffect(() => {
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [handleKey]);

  return (
    <div
      ref={overlayRef}
      role="dialog"
      aria-modal="true"
      aria-label="Product tour"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15,23,42,0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 9998,
        backdropFilter: "blur(2px)",
      }}
      onClick={(e) => { if (e.target === overlayRef.current) onClose(); }}
    >
      <div
        style={{
          background: "#FFFFFF",
          borderRadius: 20,
          padding: "36px 36px 28px",
          maxWidth: 480,
          width: "90%",
          boxShadow: "0 24px 64px rgba(0,0,0,0.18)",
          position: "relative",
        }}
      >
        {/* Close */}
        <button
          onClick={onClose}
          aria-label="Close tour"
          style={{
            position: "absolute",
            top: 16,
            right: 16,
            border: "none",
            background: "#F1F5F9",
            borderRadius: 8,
            padding: 6,
            cursor: "pointer",
            color: "#64748B",
            display: "flex",
            alignItems: "center",
          }}
        >
          <X size={16} />
        </button>

        {/* Step indicator */}
        <div style={{ display: "flex", gap: 6, marginBottom: 24 }}>
          {TOUR_STEPS.map((_, i) => (
            <button
              key={i}
              onClick={() => setStep(i)}
              aria-label={`Go to step ${i + 1}`}
              style={{
                flex: 1,
                height: 4,
                borderRadius: 2,
                border: "none",
                cursor: "pointer",
                background: i <= step ? "#3B82F6" : "#E2E8F0",
                transition: "background 0.2s",
                padding: 0,
              }}
            />
          ))}
        </div>

        {/* Icon */}
        <div style={{
          background: "#F8FAFC",
          borderRadius: 14,
          padding: 16,
          display: "inline-flex",
          marginBottom: 18,
          border: "1px solid #E2E8F0",
        }}>
          {current.icon}
        </div>

        {/* Content */}
        <div style={{ fontSize: 11, fontWeight: 600, color: "#94A3B8", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 6 }}>
          Step {step + 1} of {total}
        </div>
        <h3 style={{ fontSize: 19, fontWeight: 700, color: "#0F172A", margin: "0 0 10px", letterSpacing: "-0.02em" }}>
          {current.title}
        </h3>
        <p style={{ fontSize: 14, color: "#475569", lineHeight: 1.65, margin: "0 0 24px" }}>
          {current.body}
        </p>

        {/* Nav */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
          <button
            onClick={() => setStep((s) => s - 1)}
            disabled={step === 0}
            style={{
              padding: "9px 18px",
              border: "1px solid #E2E8F0",
              borderRadius: 8,
              background: "#FFFFFF",
              color: "#64748B",
              fontSize: 13,
              fontWeight: 500,
              cursor: step === 0 ? "default" : "pointer",
              opacity: step === 0 ? 0.35 : 1,
            }}
          >
            Back
          </button>

          <div style={{ display: "flex", gap: 8 }}>
            {current.cta && current.ctaHref && (
              <button
                onClick={() => { onClose(); router.push(current.ctaHref!); }}
                style={{
                  padding: "9px 18px",
                  border: "none",
                  borderRadius: 8,
                  background: "#F1F5F9",
                  color: "#1E293B",
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                {current.cta}
              </button>
            )}
            {step < total - 1 ? (
              <button
                onClick={() => setStep((s) => s + 1)}
                style={{
                  padding: "9px 20px",
                  border: "none",
                  borderRadius: 8,
                  background: "#3B82F6",
                  color: "#FFFFFF",
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Next
              </button>
            ) : (
              <button
                onClick={onClose}
                style={{
                  padding: "9px 20px",
                  border: "none",
                  borderRadius: 8,
                  background: "#10B981",
                  color: "#FFFFFF",
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: "pointer",
                }}
              >
                Finish
              </button>
            )}
          </div>
        </div>

        <p style={{ textAlign: "center", fontSize: 11, color: "#CBD5E1", marginTop: 16, marginBottom: 0 }}>
          Use arrow keys to navigate &middot; Esc to close
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// OnboardingCard — replaces KPI strip when patientCount === 0
// ---------------------------------------------------------------------------

function OnboardingCard({
  emrConnected,
  demoLoading,
  onTryDemo,
}: {
  emrConnected: boolean;
  demoLoading: boolean;
  onTryDemo: () => void;
}) {
  const steps = [
    {
      number: 1,
      title: "Connect your EMR",
      description: "Link OpenEMR, Epic, or any FHIR source to import patient records automatically.",
      icon: <Heart size={20} color={emrConnected ? "#10B981" : "#3B82F6"} />,
      ctaLabel: "Go to EMR Config",
      ctaHref: "/emr-config" as string | undefined,
      ctaAction: undefined as (() => void) | undefined,
      complete: emrConnected,
    },
    {
      number: 2,
      title: "Or upload a patient CSV",
      description: "No EMR? Upload a CSV directly. The system maps columns and ingests data in minutes.",
      icon: <Upload size={20} color="#8B5CF6" />,
      ctaLabel: "Go to Uploads",
      ctaHref: "/uploads" as string | undefined,
      ctaAction: undefined as (() => void) | undefined,
      complete: false,
    },
    {
      number: 3,
      title: "Or try with sample data",
      description: "Explore all features instantly using the bundled OpenEMR demo with 9 real-looking patients.",
      icon: <Play size={20} color="#F59E0B" />,
      ctaLabel: demoLoading ? "Connecting..." : "Try Demo",
      ctaHref: undefined as string | undefined,
      ctaAction: onTryDemo,
      complete: false,
    },
  ];

  return (
    <div
      style={{
        ...card,
        padding: "32px 36px",
        marginBottom: 24,
        background: "linear-gradient(135deg, #FAFBFF 0%, #F0F4FF 100%)",
        border: "1px solid #DBEAFE",
      }}
      role="region"
      aria-label="Getting started"
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 28 }}>
        <div style={{
          background: "#EFF6FF",
          borderRadius: 12,
          padding: 12,
          border: "1px solid #BFDBFE",
        }}>
          <BookOpen size={24} color="#3B82F6" />
        </div>
        <div>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "#0F172A", letterSpacing: "-0.02em" }}>
            Get started in 3 steps
          </h2>
          <p style={{ margin: "4px 0 0", fontSize: 13, color: "#64748B" }}>
            Complete any one step to populate your dashboard
          </p>
        </div>
      </div>

      {/* Steps */}
      <div
        className="onboarding-steps"
        style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}
      >
        <style>{`
          @media (max-width: 768px) {
            .onboarding-steps { grid-template-columns: 1fr !important; }
          }
        `}</style>
        {steps.map((s) => (
          <div
            key={s.number}
            style={{
              background: s.complete ? "#F0FDF4" : "#FFFFFF",
              border: s.complete ? "1px solid #BBF7D0" : "1px solid #E2E8F0",
              borderRadius: 14,
              padding: "20px 20px 16px",
              display: "flex",
              flexDirection: "column",
              gap: 10,
            }}
          >
            {/* Step number + icon */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{
                width: 28,
                height: 28,
                borderRadius: "50%",
                background: s.complete ? "#10B981" : "#EFF6FF",
                border: s.complete ? "none" : "1px solid #BFDBFE",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 13,
                fontWeight: 700,
                color: s.complete ? "#FFFFFF" : "#3B82F6",
                flexShrink: 0,
              }}>
                {s.complete ? <CheckCircle size={16} color="#FFFFFF" strokeWidth={2.5} /> : s.number}
              </div>
              <div style={{ opacity: 0.75 }}>{s.icon}</div>
            </div>

            {/* Text */}
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: "#1E293B", marginBottom: 4 }}>
                {s.title}
              </div>
              <div style={{ fontSize: 12, color: "#64748B", lineHeight: 1.55 }}>
                {s.description}
              </div>
            </div>

            {/* CTA */}
            {!s.complete ? (
              s.ctaHref ? (
                <Link
                  href={s.ctaHref}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    marginTop: "auto",
                    padding: "8px 14px",
                    border: "1px solid #BFDBFE",
                    borderRadius: 8,
                    background: "#EFF6FF",
                    color: "#1D4ED8",
                    fontSize: 12,
                    fontWeight: 600,
                    textDecoration: "none",
                    width: "fit-content",
                  }}
                >
                  {s.ctaLabel}
                  <ChevronRight size={12} />
                </Link>
              ) : (
                <button
                  onClick={s.ctaAction}
                  disabled={demoLoading}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 6,
                    marginTop: "auto",
                    padding: "8px 14px",
                    border: "none",
                    borderRadius: 8,
                    background: "#FEF3C7",
                    color: "#92400E",
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: demoLoading ? "wait" : "pointer",
                    width: "fit-content",
                    opacity: demoLoading ? 0.7 : 1,
                  }}
                >
                  {demoLoading
                    ? <RefreshCw size={12} style={{ animation: "spin 1s linear infinite" }} />
                    : <Play size={12} />}
                  {s.ctaLabel}
                </button>
              )
            ) : (
              <div style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                padding: "6px 12px",
                borderRadius: 8,
                background: "#D1FAE5",
                color: "#065F46",
                fontSize: 12,
                fontWeight: 600,
                width: "fit-content",
                marginTop: "auto",
              }}>
                <CheckCircle size={12} strokeWidth={2.5} />
                Done
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Dashboard
// ---------------------------------------------------------------------------

export function AdminDashboard() {
  const qc = useQueryClient();
  const router = useRouter();
  const [demoLoading, setDemoLoading] = useState(false);
  const [showDemoConfirm, setShowDemoConfirm] = useState(false);
  const [showTour, setShowTour] = useState(false);
  const [dateRange, setDateRange] = useState("ytd");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");

  // ---- Batch 1: Core stats (critical, loads first) ----
  const [emrStatusQ, statsQ, popQ] = useQueries({
    queries: [
      { queryKey: ["emr-status"], queryFn: getEmrStatus, retry: 1, staleTime: 60_000 },
      { queryKey: ["dashboard-stats"], queryFn: getDashboardStats, retry: 1, staleTime: 60_000 },
      { queryKey: ["population-summary", new Date().getFullYear()], queryFn: () => getPopulationSummary(new Date().getFullYear()), retry: 1, staleTime: 60_000 },
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

  // Show dashboard content when EMR is connected OR uploaded patient data exists
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
      { queryKey: ["revenue-opportunity", new Date().getFullYear()], queryFn: () => getRevenueOpportunity(new Date().getFullYear()), retry: 1, staleTime: 60_000 },
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

  // Derived values
  const totalPop = stats?.total_patients ?? pop?.total_patients ?? 0;
  const analyzed = rev?.total_patients_analyzed ?? 0;
  const avgRaf = rev?.average_raf_score ?? stats?.average_raf_score ?? 0;
  const rawRevenueOpp = rev?.estimated_annual_revenue ?? 0;
  const revenueOpp = Math.abs(rawRevenueOpp);

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
        <div style={{ background: "#FEF2F2", borderRadius: 16, padding: 24 }}>
          <AlertCircle size={48} color="#EF4444" />
        </div>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: "#1E293B" }}>
          Unable to Load Dashboard
        </h2>
        <p style={{ fontSize: 14, color: "#64748B", maxWidth: 400 }}>
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
    <div className="admin-dash-outer" style={{ background: "#F8FAFC", minHeight: "100vh", padding: "28px 40px 48px", overflowX: "hidden" }}>
      <DataQualityBanner />
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
        .fade-in-up {
          animation: fadeInUp 500ms ease-out both;
        }
        .fade-in-up-1 { animation-delay: 0ms; }
        .fade-in-up-2 { animation-delay: 100ms; }
        .fade-in-up-3 { animation-delay: 200ms; }
        .fade-in-up-4 { animation-delay: 300ms; }
        .fade-in-up-5 { animation-delay: 400ms; }
        .fade-in-up-6 { animation-delay: 500ms; }
        @media (max-width: 1024px) {
          .kpi-strip { grid-template-columns: repeat(2, 1fr) !important; }
          .row-60-40 { grid-template-columns: 1fr !important; }
          .row-55-45 { grid-template-columns: 1fr !important; }
          .row-50-50 { grid-template-columns: 1fr !important; }
          /* Fix 2: Reduce outer div padding on mobile to prevent horizontal overflow.
             On mobile main has ~12px padding; 40px L/R here = 92px total → overflows 414px.
             Use 12px to match main padding, keeping total ≤ viewport width. */
          .admin-dash-outer { padding-left: 12px !important; padding-right: 12px !important; }
          /* Fix 1: H1 must clear the fixed hamburger button.
             Hamburger: fixed left-4(16px) + w-11(44px) = 60px right edge.
             main padding (12px) + outer padding (12px) = 24px → H1 at x=24.
             Add 48px left padding to header to push H1 to x ≥ 72px. */
          .admin-dash-header { padding-left: 48px !important; }
        }
        @media (max-width: 640px) {
          .kpi-strip { grid-template-columns: 1fr !important; }
        }
      `}</style>

      {/* ── Header ── */}
      <div className="admin-dash-header" style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 12, flexWrap: "wrap", gap: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800, color: "#0F172A", letterSpacing: "-0.02em", lineHeight: 1.2 }}>
            Population Health Intelligence
          </h1>
          <div style={{ display: "flex", alignItems: "center", gap: 16, marginTop: 8 }}>
            <span style={{ fontSize: 13, color: "#64748B" }}>{dateStr}</span>
            <button
              onClick={() => setShowTour(true)}
              aria-label="Take the product tour"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                padding: "4px 12px",
                border: "1px solid #BFDBFE",
                borderRadius: 20,
                background: "#EFF6FF",
                color: "#1D4ED8",
                fontSize: 12,
                fontWeight: 600,
                cursor: "pointer",
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = "#DBEAFE"; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = "#EFF6FF"; }}
            >
              <BookOpen size={12} />
              Take the tour
            </button>
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <DateRangeSelector
            value={dateRange}
            onChange={setDateRange}
            customStart={customStart}
            customEnd={customEnd}
            onCustomChange={(s, e) => { setCustomStart(s); setCustomEnd(e); }}
          />
          <button
            onClick={handleRefresh}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "9px 18px",
              border: "1px solid #E5E7EB",
              borderRadius: 10,
              background: "#FFFFFF",
              color: "#475569",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
              transition: "all 0.15s ease",
              boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = "#F8FAFC"; e.currentTarget.style.borderColor = "#CBD5E1"; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = "#FFFFFF"; e.currentTarget.style.borderColor = "#E5E7EB"; }}
          >
            <RefreshCw size={14} />
            Refresh
          </button>
          <ExportButton onExport={() => { /* future export */ }} label="Export Dashboard" />
        </div>
      </div>

      {/* ── Data Freshness Bar ── */}
      {emrConnected && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 16,
            padding: "10px 20px",
            background: "#F0FDF4",
            border: "1px solid #BBF7D0",
            borderRadius: 10,
            marginBottom: 24,
            fontSize: 12,
            color: "#166534",
            fontWeight: 500,
          }}
        >
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: "#10B981",
              animation: "livePulse 2s ease-in-out infinite",
              boxShadow: "0 0 6px rgba(16,185,129,0.4)",
              flexShrink: 0,
            }}
          />
          <span>
            {emrStatus?.display_name || "OpenEMR"} synced {timeAgo(workflowData?.last_sync_at)} | {fmtN(totalPop)} records | Last analysis: {timeAgo(workflowData?.last_analysis_at)}
          </span>
        </div>
      )}
      {!emrStatusL && !emrConnected && (
        <div style={{ marginBottom: 24 }} />
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
            borderRadius: 12,
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
              <h3 style={{ fontSize: 15, fontWeight: 700, color: "#92400E", margin: 0 }}>
                No EMR System Connected
              </h3>
              <p style={{ fontSize: 13, color: "#A16207", margin: "4px 0 0" }}>
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
              borderRadius: 16,
              padding: "32px",
              maxWidth: 460,
              width: "90%",
              boxShadow: "0 20px 60px rgba(0,0,0,0.15)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 20 }}>
              <div style={{ background: "#FFF7ED", borderRadius: 12, padding: 12 }}>
                <Stethoscope size={28} color="#F59E0B" />
              </div>
              <div>
                <h3 style={{ fontSize: 18, fontWeight: 700, color: "#1E293B", margin: 0 }}>
                  Connect Demo OpenEMR?
                </h3>
              </div>
            </div>
            <p style={{ fontSize: 14, color: "#64748B", lineHeight: 1.6, margin: "0 0 8px" }}>
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
          <div style={{ background: "#F0F9FF", borderRadius: 16, padding: 24, display: "inline-block", marginBottom: 20 }}>
            <Stethoscope size={48} color="#3B82F6" />
          </div>
          <h2 style={{ fontSize: 22, fontWeight: 700, color: "#1E293B", margin: "0 0 8px" }}>
            Welcome to RAF Intelligence
          </h2>
          <p style={{ fontSize: 15, color: "#64748B", maxWidth: 480, margin: "0 auto 24px", lineHeight: 1.6 }}>
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
          ROW 1: KPI Strip — replaced by OnboardingCard when no data yet
          ══════════════════════════════════════════════════════════════════════ */}
      <div className="fade-in-up fade-in-up-1">
      {!statsL && !revL && !hasData ? (
        <OnboardingCard
          emrConnected={emrConnected}
          demoLoading={demoLoading}
          onTryDemo={() => setShowDemoConfirm(true)}
        />
      ) : (statsL && revL) ? (
        <KPISkeleton />
      ) : (
        <div
          className="kpi-strip kpi-strip-bento"
          role="status"
          aria-live="polite"
          style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr", gap: 20, marginBottom: 24 }}
        >
          {/* Bento sizing: hero (Revenue Opportunity) gets 2x width and a larger
              primary number; all tiles share a minimum height so the row reads
              as a unified bento strip even when individual cards render the
              short empty-state layout. */}
          <style>{`
            .kpi-strip-bento > a,
            .kpi-strip-bento > div { min-height: 132px; display: grid; }
            .kpi-strip-bento > a > div,
            .kpi-strip-bento > div > div { height: 100%; }
            .kpi-strip-hero .tabular-nums { font-size: 36px !important; }
          `}</style>
          {/* Hero tile — Revenue Opportunity dominates the row. */}
          <MetricCard
            label="Revenue Opportunity"
            value={revenueOpp > 0 ? `$${(revenueOpp / 1_000_000).toFixed(1)}M` : "--"}
            subtitle={revenueOpp > 0 ? (rawRevenueOpp < 0 ? "Over-coded gap identified" : "Estimated annual capture") : "Run analysis to calculate"}
            icon={<DollarSign size={20} />}
            intent={revenueOpp > 0 ? "success" : "default"}
            href="/reports"
          />
          <MetricCard
            label="Panel Patients"
            value={totalPop.toLocaleString()}
            subtitle="Active members"
            icon={<Users size={20} />}
            intent="default"
            href="/patients"
            trend={kpiTrends?.panel_patients?.length ? kpiTrends.panel_patients : undefined}
            delta={kpiTrends?.deltas?.panel_patients ?? undefined}
          />
          <MetricCard
            label="Open Gaps"
            value={(workflowData?.open_recapture_gaps ?? 0).toLocaleString()}
            subtitle="Recapture gaps open"
            icon={<AlertCircle size={20} />}
            intent="warning"
            href="/recapture"
            trend={kpiTrends?.open_gaps?.length ? kpiTrends.open_gaps : undefined}
            delta={kpiTrends?.deltas?.open_gaps != null ? -(kpiTrends.deltas.open_gaps) : undefined}
          />
          <MetricCard
            label="Average RAF Score"
            value={avgRaf > 0 ? avgRaf.toFixed(3) : "--"}
            subtitle={avgRaf === 0 ? "Pending analysis" : avgRaf < 1.0 ? "Below average acuity" : avgRaf < 1.5 ? "Moderate acuity" : "High acuity population"}
            icon={<TrendingUp size={20} />}
            intent={avgRaf === 0 ? "default" : avgRaf >= 2.0 ? "danger" : avgRaf >= 1.0 ? "warning" : "success"}
            delta={kpiTrends?.deltas?.avg_raf ?? rafTrend?.value}
            trend={kpiTrends?.avg_raf?.length ? kpiTrends.avg_raf : undefined}
            href="/reports?tab=raf-distribution"
          />
        </div>
      )}
      </div>

      {/* Q-Progress: most-tracked active quarterly goal */}
      <div className="mb-6 max-w-sm">
        <QProgressCard />
      </div>

      <CmsSweepWidget revenueOpp={revenueOpp} />

      {/* ══════════════════════════════════════════════════════════════════════
          ROW 2: Risk Stratification (60%) + Suspect Conditions (40%)
          ══════════════════════════════════════════════════════════════════════ */}
      <div
        className="row-60-40 fade-in-up fade-in-up-2"
        style={{ display: "grid", gridTemplateColumns: "3fr 2fr", gap: 20, marginBottom: 24 }}
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
                            background: "linear-gradient(135deg, #EF4444, #DC2626)",
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
                            background: "linear-gradient(135deg, #F59E0B, #D97706)",
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
                            background: "linear-gradient(135deg, #10B981, #059669)",
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
                { label: "High Risk", desc: "RAF >= 2.0", count: tiers.high, color: "#EF4444", bg: "#FEF2F2", border: "#FECACA", filter: "high" },
                { label: "Medium Risk", desc: "RAF 1.0 - 2.0", count: tiers.med, color: "#F59E0B", bg: "#FFFBEB", border: "#FDE68A", filter: "medium" },
                { label: "Low Risk", desc: "RAF < 1.0", count: tiers.low, color: "#10B981", bg: "#F0FDF4", border: "#A7F3D0", filter: "low" },
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
                    borderRadius: 12,
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
                  <div style={{ fontSize: 13, fontWeight: 600, color: t.color }}>{t.label}</div>
                  <div style={{ fontSize: 28, fontWeight: 800, color: "#0F172A", margin: "4px 0", letterSpacing: "-0.02em" }}>
                    {fmtN(t.count)}
                  </div>
                  <div style={{ fontSize: 12, color: "#64748B", fontWeight: 500 }}>
                    {tiers.total > 0 ? `${Math.round((t.count / tiers.total) * 100)}%` : "0%"} of population
                  </div>
                  <div style={{ fontSize: 10, color: "#64748B", marginTop: 2 }}>{t.desc}</div>
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
              <div style={{ color: "#64748B", fontSize: 14, padding: "24px 0", textAlign: "center" }}>
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
                            color: ((s.confidence_score as number) ?? 0) >= 0.9 ? "#DC2626" : ((s.confidence_score as number) ?? 0) >= 0.8 ? "#D97706" : "#2563EB",
                            background: ((s.confidence_score as number) ?? 0) >= 0.9 ? "#FEF2F2" : ((s.confidence_score as number) ?? 0) >= 0.8 ? "#FFFBEB" : "#EFF6FF",
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
          ROW 3: Top Revenue Opportunities (55%) + Revenue Waterfall (45%)
          ══════════════════════════════════════════════════════════════════════ */}
      <div
        className="row-55-45 fade-in-up fade-in-up-3"
        style={{ display: "grid", gridTemplateColumns: "11fr 9fr", gap: 20, marginBottom: 24 }}
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
              <div style={{ color: "#64748B", fontSize: 14, padding: "32px 0", textAlign: "center" }}>
                <Calculator size={32} color="#CBD5E1" style={{ marginBottom: 8 }} />
                <div>Run clinical analysis to identify revenue gaps.</div>
              </div>
            ) : (
              /* overflow-x: auto so fixed-width columns scroll on mobile rather than overflow the page */
              <div style={{ overflowX: "auto", WebkitOverflowScrolling: "touch" } as React.CSSProperties}>
              <div style={{ display: "flex", flexDirection: "column", gap: 0, minWidth: 360 }}>
                {/* Table header */}
                <div style={{ display: "flex", alignItems: "center", padding: "0 8px 10px", borderBottom: "1px solid #E5E7EB" }}>
                  <span style={{ flex: 1, fontSize: 11, fontWeight: 600, color: "#64748B", textTransform: "uppercase", letterSpacing: "0.05em" }}>Patient</span>
                  <span style={{ width: 70, fontSize: 11, fontWeight: 600, color: "#64748B", textTransform: "uppercase", letterSpacing: "0.05em", textAlign: "center" }}>Billing RAF</span>
                  <span style={{ width: 70, fontSize: 11, fontWeight: 600, color: "#64748B", textTransform: "uppercase", letterSpacing: "0.05em", textAlign: "center" }}>TMIAB RAF</span>
                  <span style={{ width: 60, fontSize: 11, fontWeight: 600, color: "#64748B", textTransform: "uppercase", letterSpacing: "0.05em", textAlign: "center" }}>Gap</span>
                  <span style={{ width: 80, fontSize: 11, fontWeight: 600, color: "#64748B", textTransform: "uppercase", letterSpacing: "0.05em", textAlign: "right" }}>Revenue</span>
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
                              background: i < 3 ? "#EFF6FF" : "#F8FAFC",
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                              fontSize: 11,
                              fontWeight: 700,
                              color: i < 3 ? "#2563EB" : "#64748B",
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
                        <span style={{ width: 70, fontSize: 12, fontWeight: 500, color: "#64748B", textAlign: "center" }}>
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
              <div style={{ color: "#64748B", fontSize: 14, padding: "32px 0", textAlign: "center" }}>
                No HCC data available. Run analysis first.
              </div>
            ) : (
              <div>
                <WaterfallChart
                  data={waterfallData}
                  totalLabel="Total Opportunity"
                  height={36}
                />
                <div style={{ marginTop: 16, fontSize: 11, color: "#64748B", lineHeight: 1.5 }}>
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
        style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, marginBottom: 24 }}
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
                      background: ["#EFF6FF", "#F5F3FF", "#FFF7ED", "#F0FDF4"][idx % 4],
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 13,
                      fontWeight: 700,
                      color: ["#2563EB", "#7C3AED", "#D97706", "#059669"][idx % 4],
                    }}
                  >
                    {prov.name.replace("Dr. ", "").charAt(0)}
                  </div>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "#1E293B" }}>{prov.name}</div>
                    <div style={{ fontSize: 11, color: "#64748B" }}>{prov.specialty}</div>
                  </div>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 12, color: "#64748B", width: 32, textAlign: "center" }}>{prov.patients}</span>
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
            <div style={{ fontSize: 12, fontWeight: 600, color: "#64748B", marginBottom: 10 }}>Patient Distribution</div>
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
                      <div style={{ fontSize: 13, fontWeight: 600, color: "#1E293B" }}>{item.title}</div>
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
          ROW 6: Patient Priority Table (full width)
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
                      style={{
                        padding: "10px 12px",
                        fontSize: 11,
                        fontWeight: 700,
                        color: "#64748B",
                        textTransform: "uppercase",
                        letterSpacing: "0.05em",
                        borderBottom: "2px solid #E5E7EB",
                        textAlign: h === "#" || h === "Patient Name" ? "left" : "center",
                        whiteSpace: "nowrap",
                      }}
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
                      <td style={{ padding: "12px", fontSize: 12, fontWeight: 600, color: "#64748B", borderBottom: "1px solid #F1F5F9" }}>{idx + 1}</td>
                      <td style={{ padding: "12px", borderBottom: "1px solid #F1F5F9" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span style={{ fontSize: 13, fontWeight: 600, color: "#1E293B" }}>{p.name as string}</span>
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
                        <span style={{ fontSize: 11, fontWeight: 600, color: "#2563EB", background: "#EFF6FF", padding: "2px 8px", borderRadius: 4 }}>
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
