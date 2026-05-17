"use client";

import React, {
  useState,
  useMemo,
  useCallback,
  useRef,
  useEffect,
} from "react";
import dynamic from "next/dynamic";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";

// Lazy-load heavy modal + detail-panel code — excluded from initial paint.
const ProvidersModals = dynamic(() => import("./ProvidersModals"), {
  ssr: false,
  loading: () => null,
});
const LazyProviderDetailPanel = dynamic(
  () => import("./ProvidersModals").then((m) => ({ default: m.ProviderDetailPanel })),
  {
    ssr: false,
    loading: () => (
      <div style={{ padding: 32, textAlign: "center", fontSize: 13, color: "#64748B" }}>
        <div style={{ width: 28, height: 28, borderRadius: "50%", border: "3px solid #E2E8F0", borderTopColor: "#2563EB", animation: "spin 0.8s linear infinite", margin: "0 auto 10px" }} />
        Loading scorecard...
      </div>
    ),
  }
);
import api from "@/lib/api";
import {
  Stethoscope,
  Users,
  TrendingUp,
  DollarSign,
  Award,
  Plus,
  Search,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  X,
  AlertCircle,
  CheckCircle,
  Bell,
  BellOff,
  Zap,
  Filter,
  ArrowUpDown,
  FileDown,
  Settings,
} from "lucide-react";
import { downloadCSV } from "@/lib/csv-export";
import { initialsColor } from "@/lib/ui-utils";
import { fmtCurrencySmart } from "@/lib/format";
import { tokens } from "@/styles/tokens";
import { StatCard, PageHeader, SectionHeader } from "@/components/healthcare-ui";
import FeatureFlag from "@/components/FeatureFlag";
import { HccChipWithPopover } from "@/components/kg/HccExplainCard";
import ProviderSuspectHotlist from "@/components/ProviderSuspectHotlist";
import ProviderFeaturesSettings from "@/components/ProviderFeaturesSettings";
import TopHccOpportunities from "@/components/TopHccOpportunities";
// Defer Recharts-heavy revenue breakdown — saves ~98 kB gz on first paint.
const ProviderRevenueBreakdown = dynamic(
  () => import("@/components/ProviderRevenueBreakdown"),
  {
    ssr: false,
    loading: () => <div className="h-64 animate-pulse bg-muted rounded-md" />,
  }
);
import ProviderTrendCard from "@/components/ProviderTrendCard";
import PeerPercentileRibbon from "@/components/PeerPercentileRibbon";
import MeatAuditRiskBadge from "@/components/MeatAuditRiskBadge";
import PreVisitBriefingPanel from "@/components/PreVisitBriefingPanel";
import ProviderReportButton from "@/components/ProviderReportButton";

// ── API base ──────────────────────────────────────────────────────────────────

// ── API functions ─────────────────────────────────────────────────────────────
async function getProviderSummary() {
  const { data } = await api.get("/api/providers/summary");
  return data as {
    total_providers: number;
    avg_capture_rate: number;
    average_raf_score: number;
    total_revenue_opportunity: number;
    avg_meat_completeness: number;
  };
}

async function getProviderLeaderboard() {
  const { data } = await api.get("/api/providers/leaderboard");
  return data as ProviderRow[];
}

async function getProviderDetail(providerId: number) {
  const { data } = await api.get(`/api/providers/${providerId}/scorecard`);
  return data as ProviderDetail;
}

async function createProvider(body: ProviderForm) {
  const { data } = await api.post("/api/providers", body);
  return data;
}

async function discoverProviders() {
  const { data } = await api.post("/api/providers/auto-discover");
  return data as { discovered: DiscoveredProvider[] };
}

async function importProviders(ids: number[]) {
  // Import each discovered provider individually via their specific import endpoint
  const results = await Promise.all(
    ids.map((id) => api.post(`/api/providers/${id}/import`).then((r) => r.data))
  );
  return results;
}

async function acknowledgeAlert(payload: { providerId: number; alertId: number }) {
  const { data } = await api.put(
    `/api/providers/${payload.providerId}/alerts/${payload.alertId}/acknowledge`
  );
  return data;
}

// ── Design Tokens (single source of truth: tokens.ts) ─────────────────────────
const C = {
  bg: tokens.slate50,
  card: tokens.white,
  border: tokens.slate200,
  borderLight: tokens.slate100,
  text: tokens.slate900,
  textMuted: tokens.slate500,
  textSub: tokens.slate400,
  primary: tokens.primary,
  primaryLight: "rgba(37,99,235,0.10)",
  primaryDark: tokens.primaryDark,
  emerald: tokens.success,
  emeraldLight: tokens.successSoft,
  emeraldDark: tokens.emerald800,
  amber: tokens.warningStrong,
  amberLight: tokens.warningSoft,
  amberDark: tokens.warningText,
  red: tokens.riskHigh,
  redLight: tokens.riskHighSoft,
  redDark: tokens.danger,
  violet: tokens.accentPurple,
  violetLight: "rgba(139,92,246,0.10)",
  gray50: tokens.slate50,
  gray100: tokens.slate100,
  gray200: tokens.slate200,
  gray300: tokens.slate300,
  gray400: tokens.slate400,
  gray600: tokens.slate600,
  white: tokens.white,
};

// ── Types ─────────────────────────────────────────────────────────────────────
type ProviderRow = {
  provider_id: number;
  first_name: string;
  last_name: string;
  credential: string;
  specialty: string;
  specialty_category: "PCP" | "Specialist" | "Hospitalist";
  practice_name: string | null;
  npi: string | null;
  patient_count: number;
  average_raf_score: number | null;
  hcc_capture_rate: number | null;
  recapture_rate: number | null;
  meat_score: number | null;
  revenue_opportunity: number | null;
};

type HccPerformance = {
  hcc_code: string;
  description: string;
  patients_at_risk: number;
  coded: number;
  uncoded: number;
  capture_pct: number;
  revenue_at_stake: number;
};

type ProviderAlert = {
  alert_id: number;
  type: string;
  message: string;
  severity: "high" | "medium" | "low";
  acknowledged: boolean;
  created_at: string;
};

type ProviderDetail = {
  provider_id: number;
  first_name: string;
  last_name: string;
  credential: string;
  specialty: string;
  specialty_category: string;
  practice_name: string | null;
  npi: string | null;
  email: string | null;
  patient_count: number;
  scorecard: {
    capture_rate: number;
    recapture_rate: number;
    meat_score: number;
    documentation_quality: number;
    revenue_capture: number;
  };
  hcc_performance: HccPerformance[];
  alerts: ProviderAlert[];
};

type ProviderForm = {
  npi: string;
  first_name: string;
  last_name: string;
  credential: string;
  specialty: string;
  specialty_category: string;
  practice_name: string;
  email: string;
};

type DiscoveredProvider = {
  user_id: number;
  first_name: string;
  last_name: string;
  username: string;
  specialty?: string | null;
  npi?: string | null;
  email?: string | null;
  phone?: string | null;
};

type SortField =
  | "name"
  | "patient_count"
  | "average_raf_score"
  | "hcc_capture_rate"
  | "recapture_rate"
  | "meat_score"
  | "revenue_opportunity";
type SortDir = "asc" | "desc";
type SpecialtyFilter = "all" | "PCP" | "Specialist" | "Hospitalist";

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmt$(v: number | null | undefined): string {
  if (v == null) return "$0";
  return fmtCurrencySmart(v);
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "--";
  return `${Math.round(v * 100)}%`;
}

function fmtN(v: number | null | undefined, d = 2): string {
  if (v == null) return "--";
  return Number(v).toFixed(d);
}

function providerName(p: { first_name: string; last_name: string; credential: string }) {
  return `${p.first_name} ${p.last_name}${p.credential ? `, ${p.credential}` : ""}`;
}

function captureColor(rate: number | null): string {
  if (rate == null) return C.gray400;
  if (rate >= 0.85) return C.emerald;
  if (rate >= 0.70) return C.amber;
  return C.red;
}

function captureBg(rate: number | null): string {
  if (rate == null) return C.gray100;
  if (rate >= 0.85) return C.emeraldLight;
  if (rate >= 0.70) return C.amberLight;
  return C.redLight;
}

// ── Capture Rate Badge ────────────────────────────────────────────────────────
function CaptureBadge({ rate }: { rate: number | null }) {
  if (rate == null) return <span className="text-gray-400 text-xs">--</span>;
  return (
    <span
      style={{
        display: "inline-block",
        padding: "3px 10px",
        borderRadius: 9999,
        fontSize: 12,
        fontWeight: 600,
        background: captureBg(rate),
        color: captureColor(rate),
      }}
    >
      {fmtPct(rate)}
    </span>
  );
}

// ── Rank Medal ────────────────────────────────────────────────────────────────
function RankBadge({ rank }: { rank: number }) {
  const colors: Record<number, { bg: string; fg: string }> = {
    1: { bg: tokens.warningSoft, fg: tokens.warningText },
    2: { bg: tokens.slate100, fg: tokens.slate600 },
    3: { bg: tokens.warningSoft, fg: tokens.riskMedium },
  };
  const style = colors[rank] ?? { bg: C.gray100, fg: C.gray600 };
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 26,
        height: 26,
        borderRadius: 6,
        background: style.bg,
        color: style.fg,
        fontSize: 12,
        fontWeight: 700,
      }}
    >
      {rank <= 3 ? ["#1", "#2", "#3"][rank - 1] : rank}
    </span>
  );
}

// ── Specialty Tag ─────────────────────────────────────────────────────────────
function SpecialtyTag({ cat }: { cat: string }) {
  const map: Record<string, { bg: string; fg: string }> = {
    PCP: { bg: C.primaryLight, fg: C.primary },
    Specialist: { bg: C.violetLight, fg: C.violet },
    Hospitalist: { bg: C.amberLight, fg: C.amberDark },
  };
  const s = map[cat] ?? { bg: C.gray100, fg: C.gray600 };
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: 6,
        fontSize: 11,
        fontWeight: 600,
        background: s.bg,
        color: s.fg,
      }}
    >
      {cat}
    </span>
  );
}

// ── Sort Icon (standalone to avoid recreating during render) ──────────────────
function SortIcon({ field, activeField, activeDir }: { field: SortField; activeField: SortField; activeDir: SortDir }) {
  if (activeField !== field) return <ArrowUpDown size={12} style={{ opacity: 0.4 }} />;
  return activeDir === "asc"
    ? <ChevronUp size={13} color={C.primary} />
    : <ChevronDown size={13} color={C.primary} />;
}

// ═════════════════════════════════════════════════════════════════════════════
// Page Component
// ═════════════════════════════════════════════════════════════════════════════
export default function ProvidersPage() {
  const [search, setSearch] = useState("");
  const [specialtyFilter, setSpecialtyFilter] = useState<SpecialtyFilter>("all");
  const [sortField, setSortField] = useState<SortField>("hcc_capture_rate");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [showDiscoverDialog, setShowDiscoverDialog] = useState(false);
  const [hoveredRow, setHoveredRow] = useState<number | null>(null);
  const [showFeatureSettings, setShowFeatureSettings] = useState(false);

  const { data: summary, isLoading: sumLoading } = useQuery({
    queryKey: ["provider-summary"],
    queryFn: getProviderSummary,
    retry: 1,
  });

  const { data: leaderboard = [], isLoading: lbLoading } = useQuery({
    queryKey: ["provider-leaderboard"],
    queryFn: getProviderLeaderboard,
    retry: 1,
  });

  // ── Filtering & sorting ──────────────────────────────────────────────────
  const filtered = useMemo(() => {
    let rows = leaderboard;
    if (search.trim()) {
      const q = search.toLowerCase();
      rows = rows.filter(
        (r) =>
          `${r.first_name} ${r.last_name}`.toLowerCase().includes(q) ||
          r.specialty.toLowerCase().includes(q) ||
          (r.npi ?? "").includes(q)
      );
    }
    if (specialtyFilter !== "all") {
      rows = rows.filter((r) => r.specialty_category === specialtyFilter);
    }
    rows = [...rows].sort((a, b) => {
      let av: number, bv: number;
      switch (sortField) {
        case "name":
          return sortDir === "asc"
            ? `${a.last_name} ${a.first_name}`.localeCompare(`${b.last_name} ${b.first_name}`)
            : `${b.last_name} ${b.first_name}`.localeCompare(`${a.last_name} ${a.first_name}`);
        case "patient_count":
          av = a.patient_count;
          bv = b.patient_count;
          break;
        case "average_raf_score":
          av = a.average_raf_score ?? 0;
          bv = b.average_raf_score ?? 0;
          break;
        case "hcc_capture_rate":
          av = a.hcc_capture_rate ?? 0;
          bv = b.hcc_capture_rate ?? 0;
          break;
        case "recapture_rate":
          av = a.recapture_rate ?? 0;
          bv = b.recapture_rate ?? 0;
          break;
        case "meat_score":
          av = a.meat_score ?? 0;
          bv = b.meat_score ?? 0;
          break;
        case "revenue_opportunity":
          av = a.revenue_opportunity ?? 0;
          bv = b.revenue_opportunity ?? 0;
          break;
        default:
          av = 0;
          bv = 0;
      }
      return sortDir === "asc" ? av - bv : bv - av;
    });
    return rows;
  }, [leaderboard, search, specialtyFilter, sortField, sortDir]);

  const handleSort = useCallback(
    (field: SortField) => {
      if (sortField === field) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
      else { setSortField(field); setSortDir("desc"); }
    },
    [sortField]
  );

  function exportProvidersCSV() {
    if (!filtered.length) return;
    downloadCSV(filtered.map((p) => ({
      "NPI": p.npi ?? "",
      "Name": providerName(p),
      "Specialty": p.specialty,
      "Patient Count": p.patient_count,
      "Avg RAF": p.average_raf_score != null ? Number(p.average_raf_score).toFixed(2) : "",
      "Capture Rate": p.hcc_capture_rate != null ? `${Math.round(p.hcc_capture_rate * 100)}%` : "",
    })), "providers");
  }

  const thStyleStatic: React.CSSProperties = {
    padding: "10px 12px",
    fontWeight: 600,
    color: C.textMuted,
    fontSize: 11,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    whiteSpace: "nowrap",
    textAlign: "left",
  };

  const thStyle = (field: string): React.CSSProperties => ({
    ...thStyleStatic,
    cursor: "pointer",
    userSelect: "none",
    background: sortField === field ? `${C.primary}15` : undefined,
  });

  const isLoading = sumLoading || lbLoading;

  return (
    <div className="providers-page-wrap" style={{ padding: "20px 16px", background: C.bg, minHeight: "100vh" }}>
      <style>{`
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
        @keyframes fadeInUp {
          from { opacity: 0; transform: translateY(12px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .provider-row-animate {
          animation: fadeInUp 0.4s ease-out both;
        }
        .provider-avatar {
          background-size: 200% 200%;
          animation: avatarShimmer 3s ease infinite;
        }
        @keyframes avatarShimmer {
          0%, 100% { background-position: 0% 50%; }
          50% { background-position: 100% 50%; }
        }
        @media (min-width: 640px) {
          .providers-page-wrap { padding: 32px 40px !important; }
        }
        /* Bug 2: drilldown inline row — no phantom height when collapsed */
        .provider-detail-td { height: auto !important; min-height: 0 !important; }
        /* Bug 1 radar: cap height and clip overflow on mobile to kill phantom gap */
        @media (max-width: 768px) {
          .provider-radar-wrap { overflow: hidden; width: 100%; display: flex; justify-content: center; max-height: 280px; }
          .provider-detail-td { padding-bottom: 12px !important; }
        }
      `}</style>

      {/* ── Page Header ───────────────────────────────────────────────────── */}
      <PageHeader
        title="Provider Scorecards"
        subtitle="Provider-level RAF capture rates, HCC coding performance, and revenue metrics"
        icon={<Stethoscope size={22} />}
        actions={
          <>
            <button
              onClick={() => setShowFeatureSettings(true)}
              title="Page features (add/hide sections)"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 7,
                padding: "9px 12px",
                border: `1px solid ${C.border}`,
                borderRadius: 8,
                background: C.white,
                color: C.textMuted,
                fontSize: 13,
                fontWeight: 500,
                cursor: "pointer",
              }}
            >
              <Settings size={15} />
              Page Features
            </button>
            <button
              onClick={() => setShowDiscoverDialog(true)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 7,
                padding: "9px 16px",
                border: `1px solid ${C.border}`,
                borderRadius: 8,
                background: C.white,
                color: C.textMuted,
                fontSize: 13,
                fontWeight: 500,
                cursor: "pointer",
              }}
            >
              <Zap size={15} />
              Auto-Discover from EMR
            </button>
            <button
              onClick={() => setShowAddDialog(true)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 7,
                padding: "9px 18px",
                border: "none",
                borderRadius: 8,
                background: C.primary,
                color: C.white,
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              <Plus size={15} />
              Add Provider
            </button>
          </>
        }
      />

      {/* ── Stats Row ─────────────────────────────────────────────────────── */}
      {isLoading ? (
        <div
          className="providers-stats"
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: 16,
            marginBottom: 28,
          }}
        >
          {[1, 2, 3, 4, 5].map((i) => (
            <div
              key={i}
              className="premium-card shimmer"
              style={{
                borderRadius: 14,
                padding: 20,
                height: 100,
              }}
            />
          ))}
        </div>
      ) : (
        <div
          className="providers-stats"
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: 16,
            marginBottom: 28,
          }}
        >
          <div style={{ animation: "fadeInUp 0.4s ease-out both", animationDelay: "0ms" }}>
          <StatCard
            label="Total Providers"
            value={summary?.total_providers?.toLocaleString() ?? "—"}
            subtitle="In this system"
            icon={<Users size={18} />}
            color={C.primary}
          />
          </div>
          <div style={{ animation: "fadeInUp 0.4s ease-out both", animationDelay: "60ms" }}>
          <StatCard
            label="Avg Capture Rate"
            value={summary ? fmtPct(summary.avg_capture_rate) : "—"}
            subtitle={
              summary?.avg_capture_rate != null
                ? summary.avg_capture_rate >= 0.85
                  ? "Above target"
                  : "Below 85% target"
                : undefined
            }
            icon={<CheckCircle size={18} />}
            color={captureColor(summary?.avg_capture_rate ?? null)}
          />
          </div>
          <div style={{ animation: "fadeInUp 0.4s ease-out both", animationDelay: "120ms" }}>
          <StatCard
            label="Avg RAF Score"
            value={summary ? fmtN(summary.average_raf_score, 3) : "—"}
            subtitle="Population average"
            icon={<TrendingUp size={18} />}
            color={C.amber}
          />
          </div>
          <div style={{ animation: "fadeInUp 0.4s ease-out both", animationDelay: "180ms" }}>
          <StatCard
            label="Revenue Opportunity"
            value={summary ? fmt$(summary.total_revenue_opportunity) : "—"}
            subtitle="Across all providers"
            icon={<DollarSign size={18} />}
            color={C.emerald}
          />
          </div>
          <div style={{ animation: "fadeInUp 0.4s ease-out both", animationDelay: "240ms" }}>
          <StatCard
            label="Avg MEAT Score"
            value={summary ? fmtPct(summary.avg_meat_completeness) : "—"}
            subtitle="Documentation quality"
            icon={<Award size={18} />}
            color={C.violet}
          />
          </div>
        </div>
      )}

      {/* ── Leaderboard Table ──────────────────────────────────────────────── */}
      <div
        className="premium-card premium-shadow gradient-border"
        style={{
          background: C.card,
          borderRadius: 16,
          /* overflow:hidden clips border-radius; use clip so inline scroll still works on mobile */
          overflow: "clip",
          animation: "fadeInUp 0.5s ease-out both",
          animationDelay: "300ms",
        }}
      >
        {/* Table toolbar */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "16px 20px",
            borderBottom: `1px solid ${C.border}`,
            flexWrap: "wrap",
            gap: 12,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <h2
              style={{
                margin: 0,
                fontSize: 16,
                fontWeight: 700,
                color: C.text,
              }}
            >
              Provider Leaderboard
            </h2>
            <span
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: C.primary,
                background: C.primaryLight,
                padding: "2px 8px",
                borderRadius: 999,
              }}
            >
              {filtered.length}
            </span>
          </div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              flexWrap: "wrap",
            }}
          >
            {/* Search */}
            <div
              style={{
                position: "relative",
                display: "flex",
                alignItems: "center",
              }}
            >
              <Search
                size={14}
                style={{
                  position: "absolute",
                  left: 10,
                  color: C.textSub,
                  pointerEvents: "none",
                }}
              />
              <input
                type="text"
                placeholder="Search by name or NPI..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                aria-label="Search providers"
                style={{
                  padding: "8px 14px 8px 32px",
                  border: `1px solid ${C.border}`,
                  borderRadius: 8,
                  fontSize: 13,
                  width: 220,
                  color: C.text,
                  background: C.white,
                }}
              />
            </div>
            {/* Specialty filter */}
            <div
              style={{
                position: "relative",
                display: "flex",
                alignItems: "center",
              }}
            >
              <Filter
                size={13}
                style={{
                  position: "absolute",
                  left: 10,
                  color: C.textSub,
                  pointerEvents: "none",
                }}
              />
              <select
                value={specialtyFilter}
                onChange={(e) => setSpecialtyFilter(e.target.value as SpecialtyFilter)}
                aria-label="Filter by specialty category"
                style={{
                  padding: "8px 14px 8px 30px",
                  border: `1px solid ${C.border}`,
                  borderRadius: 8,
                  fontSize: 13,
                  color: C.text,
                  background: C.white,
                  cursor: "pointer",
                  appearance: "none",
                  paddingRight: 32,
                }}
              >
                <option value="all">All Categories</option>
                <option value="PCP">PCP</option>
                <option value="Specialist">Specialist</option>
                <option value="Hospitalist">Hospitalist</option>
              </select>
              <ChevronDown
                size={13}
                style={{
                  position: "absolute",
                  right: 10,
                  color: C.textSub,
                  pointerEvents: "none",
                }}
              />
            </div>
            <button
              onClick={exportProvidersCSV}
              aria-label="Export providers as CSV"
              style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "8px 14px", borderRadius: 8,
                border: "none", background: C.primary,
                color: C.white, fontSize: 13, fontWeight: 600,
                cursor: "pointer", flexShrink: 0,
              }}
            >
              <FileDown size={14} />
              Export CSV
            </button>
          </div>
        </div>

        {/* Table */}
        <div style={{ overflowX: "auto" }}>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: 13,
            }}
          >
            <thead>
              <tr style={{ borderBottom: `2px solid ${C.border}`, background: C.gray50 }}>
                <th style={thStyleStatic}>Rank</th>
                <th
                  style={thStyle("name")}
                  onClick={() => handleSort("name")}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                    Provider <SortIcon field="name" activeField={sortField} activeDir={sortDir} />
                  </div>
                </th>
                <th style={thStyleStatic}>Specialty</th>
                <th
                  style={thStyle("patient_count")}
                  onClick={() => handleSort("patient_count")}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                    Patients <SortIcon field="patient_count" activeField={sortField} activeDir={sortDir} />
                  </div>
                </th>
                <th
                  style={thStyle("average_raf_score")}
                  onClick={() => handleSort("average_raf_score")}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                    Avg RAF <SortIcon field="average_raf_score" activeField={sortField} activeDir={sortDir} />
                  </div>
                </th>
                <th
                  style={thStyle("hcc_capture_rate")}
                  onClick={() => handleSort("hcc_capture_rate")}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                    HCC Capture <SortIcon field="hcc_capture_rate" activeField={sortField} activeDir={sortDir} />
                  </div>
                </th>
                <th
                  style={thStyle("recapture_rate")}
                  onClick={() => handleSort("recapture_rate")}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                    Recapture <SortIcon field="recapture_rate" activeField={sortField} activeDir={sortDir} />
                  </div>
                </th>
                <th
                  style={thStyle("meat_score")}
                  onClick={() => handleSort("meat_score")}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                    MEAT Score <SortIcon field="meat_score" activeField={sortField} activeDir={sortDir} />
                  </div>
                </th>
                <th
                  style={thStyle("revenue_opportunity")}
                  onClick={() => handleSort("revenue_opportunity")}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                    Revenue Opp. <SortIcon field="revenue_opportunity" activeField={sortField} activeDir={sortDir} />
                  </div>
                </th>
                <th style={thStyleStatic}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {lbLoading ? (
                Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i} style={{ borderBottom: `1px solid ${C.borderLight}` }}>
                    {Array.from({ length: 10 }).map((__, j) => (
                      <td key={j} style={{ padding: "14px 12px" }}>
                        <div
                          style={{
                            height: 14,
                            borderRadius: 4,
                            background: C.gray200,
                            animation: "pulse 1.5s ease-in-out infinite",
                            width: j === 1 ? "80%" : j === 2 ? "60%" : "50%",
                          }}
                        />
                      </td>
                    ))}
                  </tr>
                ))
              ) : filtered.length === 0 ? (
                <tr>
                  <td
                    colSpan={10}
                    style={{ padding: 48, textAlign: "center", color: C.textMuted }}
                  >
                    <Users size={36} color={C.gray300} style={{ display: "block", margin: "0 auto 12px" }} />
                    {leaderboard.length === 0 ? (
                      <>
                        <p style={{ margin: "0 0 4px", fontSize: 15, fontWeight: 700, color: C.text }}>
                          No providers yet
                        </p>
                        <p style={{ margin: "0 0 16px", fontSize: 13, color: C.textMuted }}>
                          Add a provider to start scoring, or use Auto-Discover to import from your EMR.
                        </p>
                        <button
                          onClick={() => setShowAddDialog(true)}
                          style={{
                            display: "inline-flex", alignItems: "center", gap: 7,
                            padding: "9px 18px", borderRadius: 8, border: "none",
                            background: C.primary, color: C.white, fontSize: 13,
                            fontWeight: 600, cursor: "pointer",
                          }}
                        >
                          <Plus size={14} /> Add Your First Provider
                        </button>
                      </>
                    ) : (
                      <>
                        <p style={{ margin: "0 0 4px", fontSize: 15, fontWeight: 700, color: C.text }}>
                          No providers match
                        </p>
                        <p style={{ margin: 0, fontSize: 13, color: C.textMuted }}>
                          Try adjusting the search or specialty filter.
                        </p>
                      </>
                    )}
                  </td>
                </tr>
              ) : (
                filtered.map((row, idx) => {
                  const isExpanded = expandedId === row.provider_id;
                  const isHovered = hoveredRow === row.provider_id;
                  return (
                    <React.Fragment key={row.provider_id}>
                      <tr
                        className="provider-row-animate hover-lift"
                        onClick={() =>
                          setExpandedId(isExpanded ? null : row.provider_id)
                        }
                        onMouseEnter={() => setHoveredRow(row.provider_id)}
                        onMouseLeave={() => setHoveredRow(null)}
                        style={{
                          borderBottom: isExpanded ? "none" : `1px solid ${C.borderLight}`,
                          cursor: "pointer",
                          background: isExpanded
                            ? C.primaryLight
                            : isHovered
                            ? C.gray50
                            : C.white,
                          transition: "background 0.15s, transform 0.25s cubic-bezier(0.4,0,0.2,1), box-shadow 0.25s",
                          animationDelay: `${idx * 50}ms`,
                        }}
                        aria-expanded={isExpanded}
                      >
                        {/* Rank */}
                        <td style={{ padding: "12px 12px" }}>
                          <RankBadge rank={idx + 1} />
                        </td>
                        {/* Provider name */}
                        <td style={{ padding: "12px 12px" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                            <div
                              className="provider-avatar"
                              style={{
                                width: 38,
                                height: 38,
                                borderRadius: 12,
                                background: `linear-gradient(135deg, ${initialsColor(providerName(row))}, ${initialsColor(providerName(row))}cc)`,
                                color: C.white,
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                fontSize: 13,
                                fontWeight: 700,
                                flexShrink: 0,
                                boxShadow: `0 2px 8px ${initialsColor(providerName(row))}40`,
                                letterSpacing: "0.02em",
                              }}
                            >
                              {((row.first_name || "").trim()[0] || (row.last_name || "").trim()[0] || "\u2022").toUpperCase()}{(row.first_name && row.last_name ? (row.last_name || "").trim()[0] : "").toUpperCase()}
                            </div>
                            <div>
                              <div
                                style={{
                                  fontWeight: 600,
                                  color: C.text,
                                  fontSize: 13,
                                }}
                              >
                                {providerName(row)}
                              </div>
                              {row.npi && (
                                <div
                                  style={{
                                    fontSize: 11,
                                    color: C.textSub,
                                    marginTop: 1,
                                  }}
                                >
                                  NPI: {row.npi}
                                </div>
                              )}
                            </div>
                          </div>
                        </td>
                        {/* Specialty */}
                        <td style={{ padding: "12px 12px" }}>
                          <div>
                            <div style={{ fontSize: 12, color: C.text, marginBottom: 3 }}>
                              {row.specialty}
                            </div>
                            <SpecialtyTag cat={row.specialty_category} />
                          </div>
                        </td>
                        {/* Patients */}
                        <td style={{ padding: "12px 12px", color: C.text, fontWeight: 600 }}>
                          {row.patient_count.toLocaleString()}
                        </td>
                        {/* Avg RAF */}
                        <td style={{ padding: "12px 12px", fontWeight: 600, color: C.text }}>
                          {fmtN(row.average_raf_score, 3)}
                        </td>
                        {/* HCC Capture */}
                        <td style={{ padding: "12px 12px" }}>
                          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                            <CaptureBadge rate={row.hcc_capture_rate} />
                            {row.hcc_capture_rate != null && (
                              <div
                                style={{
                                  height: 4,
                                  borderRadius: 2,
                                  background: C.gray200,
                                  overflow: "hidden",
                                  width: 60,
                                }}
                              >
                                <div
                                  style={{
                                    height: "100%",
                                    width: `${Math.round(row.hcc_capture_rate * 100)}%`,
                                    background: captureColor(row.hcc_capture_rate),
                                    borderRadius: 2,
                                    transition: "width 0.3s",
                                  }}
                                />
                              </div>
                            )}
                          </div>
                        </td>
                        {/* Recapture */}
                        <td style={{ padding: "12px 12px" }}>
                          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                            <CaptureBadge rate={row.recapture_rate} />
                            {row.recapture_rate != null && (
                              <div
                                style={{
                                  height: 4,
                                  borderRadius: 2,
                                  background: C.gray200,
                                  overflow: "hidden",
                                  width: 60,
                                }}
                              >
                                <div
                                  style={{
                                    height: "100%",
                                    width: `${Math.round(row.recapture_rate * 100)}%`,
                                    background: captureColor(row.recapture_rate),
                                    borderRadius: 2,
                                    transition: "width 0.3s",
                                  }}
                                />
                              </div>
                            )}
                          </div>
                        </td>
                        {/* MEAT Score */}
                        <td style={{ padding: "12px 12px" }}>
                          {row.meat_score != null ? (
                            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                              <span
                                style={{
                                  fontSize: 13,
                                  fontWeight: 700,
                                  color: C.violet,
                                }}
                              >
                                {fmtPct(row.meat_score)}
                              </span>
                              <div
                                style={{
                                  height: 4,
                                  borderRadius: 2,
                                  background: C.gray200,
                                  overflow: "hidden",
                                  width: 60,
                                }}
                              >
                                <div
                                  style={{
                                    height: "100%",
                                    width: `${Math.round(row.meat_score * 100)}%`,
                                    background: C.violet,
                                    borderRadius: 2,
                                    transition: "width 0.3s",
                                  }}
                                />
                              </div>
                            </div>
                          ) : (
                            <span className="text-gray-400 text-xs">--</span>
                          )}
                        </td>
                        {/* Revenue Opportunity */}
                        <td style={{ padding: "12px 12px" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            <span
                              style={{
                                fontWeight: 700,
                                color: C.emeraldDark,
                                fontSize: 13,
                              }}
                            >
                              {fmt$(row.revenue_opportunity)}
                            </span>
                            {(row.revenue_opportunity ?? 0) > 50000 && (
                              <span
                                aria-label="High revenue opportunity"
                                style={{
                                  display: "inline-flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  width: 18,
                                  height: 18,
                                  borderRadius: 6,
                                  background: C.emeraldLight,
                                  fontSize: 10,
                                }}
                                title="High revenue opportunity"
                              >
                                <TrendingUp size={10} color={C.emerald} />
                              </span>
                            )}
                          </div>
                        </td>
                        {/* Actions */}
                        <td style={{ padding: "12px 12px" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                setExpandedId(isExpanded ? null : row.provider_id);
                              }}
                              title={isExpanded ? "Collapse" : "View scorecard"}
                              aria-label={isExpanded ? "Collapse row" : "Expand scorecard"}
                              className={isExpanded ? "card-glow-blue" : "glow-hover"}
                              style={{
                                padding: "6px 12px",
                                border: `1px solid ${isExpanded ? C.primary : C.border}`,
                                borderRadius: 8,
                                background: isExpanded ? C.primaryLight : C.white,
                                color: isExpanded ? C.primary : C.textMuted,
                                fontSize: 12,
                                fontWeight: 600,
                                cursor: "pointer",
                                display: "flex",
                                alignItems: "center",
                                gap: 4,
                                transition: "all 0.2s ease",
                              }}
                            >
                              {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                              {isExpanded ? "Collapse" : "Scorecard"}
                            </button>
                          </div>
                        </td>
                      </tr>

                      {/* Expanded detail row */}
                      {isExpanded && (
                        <tr>
                          <td
                            colSpan={10}
                            className="provider-detail-td"
                            style={{
                              padding: "0 16px 20px",
                              borderBottom: `1px solid ${C.border}`,
                              background: C.bg,
                              height: "auto",
                            }}
                          >
                            <LazyProviderDetailPanel
                              providerId={row.provider_id}
                              onClose={() => setExpandedId(null)}
                            />
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Table footer */}
        {!lbLoading && filtered.length > 0 && (
          <div
            style={{
              padding: "12px 20px",
              borderTop: `1px solid ${C.border}`,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              fontSize: 12,
              color: C.textMuted,
            }}
          >
            <span>
              Showing {filtered.length} of {leaderboard.length} providers
              {specialtyFilter !== "all" && ` · Filtered: ${specialtyFilter}`}
            </span>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              {[
                { color: C.emerald, bg: C.emeraldLight, label: "Capture \u226585%" },
                { color: C.amber, bg: C.amberLight, label: "70 \u2013 85%" },
                { color: C.red, bg: C.redLight, label: "<70%" },
              ].map((item) => (
                <div
                  key={item.label}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 5,
                    padding: "3px 10px 3px 8px",
                    borderRadius: 999,
                    background: item.bg,
                  }}
                >
                  <div style={{ width: 8, height: 8, borderRadius: 999, background: item.color }} />
                  <span style={{ color: item.color, fontWeight: 600 }}>{item.label}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Dialogs (lazy-loaded) ─────────────────────────────────────────────── */}
      <ProvidersModals
        showAdd={showAddDialog}
        showDiscover={showDiscoverDialog}
        onCloseAdd={() => setShowAddDialog(false)}
        onCloseDiscover={() => setShowDiscoverDialog(false)}
      />
      <ProviderFeaturesSettings
        open={showFeatureSettings}
        onClose={() => setShowFeatureSettings(false)}
      />
    </div>
  );
}
