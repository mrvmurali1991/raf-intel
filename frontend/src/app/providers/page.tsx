"use client";

import React, {
  useState,
  useMemo,
  useCallback,
} from "react";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";

// Lazy-load heavy modal + detail-panel code — excluded from initial paint.
const ProvidersModals = dynamic(() => import("./ProvidersModals"), {
  ssr: false,
  loading: () => null,
});
const LazyProviderDetailPanel = dynamic(
  () =>
    import("./ProvidersModals").then((m) => ({
      default: m.ProviderDetailPanel,
    })),
  {
    ssr: false,
    loading: () => (
      <div className="p-8 text-center text-[13px] text-muted-foreground">
        <div className="w-7 h-7 rounded-full border-2 border-border border-t-primary animate-spin mx-auto mb-2.5" />
        Loading scorecard...
      </div>
    ),
  },
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
  CheckCircle,
  Zap,
  Filter,
  ArrowUpDown,
  FileDown,
  Settings,
} from "lucide-react";
import { downloadCSV } from "@/lib/csv-export";
import { initialsColor } from "@/lib/ui-utils";
import { fmtCurrencySmart } from "@/lib/format";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { MetricCard } from "@/components/ui/metric-card";
import ProviderFeaturesSettings from "@/components/ProviderFeaturesSettings";

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

async function createProvider(body: ProviderForm) {
  const { data } = await api.post("/api/providers", body);
  return data;
}

async function discoverProviders() {
  const { data } = await api.post("/api/providers/auto-discover");
  return data as { discovered: DiscoveredProvider[] };
}

async function importProviders(ids: number[]) {
  const results = await Promise.all(
    ids.map((id) =>
      api.post(`/api/providers/${id}/import`).then((r) => r.data),
    ),
  );
  return results;
}

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

function providerName(p: {
  first_name: string;
  last_name: string;
  credential: string;
}) {
  return `${p.first_name} ${p.last_name}${p.credential ? `, ${p.credential}` : ""}`;
}

// ── Capture Rate colour helpers (Tailwind class-based) ────────────────────────
function captureTextClass(rate: number | null): string {
  if (rate == null) return "text-muted-foreground";
  if (rate >= 0.85) return "text-emerald-600 dark:text-emerald-400";
  if (rate >= 0.7) return "text-amber-600 dark:text-amber-400";
  return "text-red-600 dark:text-red-400";
}

function captureBgClass(rate: number | null): string {
  if (rate == null) return "bg-muted text-muted-foreground";
  if (rate >= 0.85)
    return "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300";
  if (rate >= 0.7)
    return "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300";
  return "bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300";
}

function captureBarClass(rate: number | null): string {
  if (rate == null) return "bg-muted-foreground/30";
  if (rate >= 0.85) return "bg-emerald-500";
  if (rate >= 0.7) return "bg-amber-500";
  return "bg-red-500";
}

// ── Capture Rate Badge ────────────────────────────────────────────────────────
function CaptureBadge({ rate }: { rate: number | null }) {
  if (rate == null)
    return <span className="text-muted-foreground text-xs">--</span>;
  return (
    <span
      className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-semibold ${captureBgClass(rate)}`}
    >
      {fmtPct(rate)}
    </span>
  );
}

// ── Mini progress bar ─────────────────────────────────────────────────────────
function MiniBar({ rate }: { rate: number | null }) {
  if (rate == null) return null;
  return (
    <div className="h-1 rounded-full bg-muted overflow-hidden w-[60px]">
      <div
        className={`h-full rounded-full transition-[width] duration-300 ${captureBarClass(rate)}`}
        style={{ width: `${Math.round(rate * 100)}%` }}
      />
    </div>
  );
}

// ── Rank Medal ────────────────────────────────────────────────────────────────
function RankBadge({ rank }: { rank: number }) {
  const medalClass: Record<number, string> = {
    1: "bg-amber-50 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
    2: "bg-muted text-muted-foreground",
    3: "bg-orange-50 text-orange-600 dark:bg-orange-900/30 dark:text-orange-300",
  };
  const cls =
    medalClass[rank] ?? "bg-muted/50 text-muted-foreground";
  return (
    <span
      className={`inline-flex items-center justify-center w-[26px] h-[26px] rounded-md text-xs font-bold ${cls}`}
    >
      {rank <= 3 ? `#${rank}` : rank}
    </span>
  );
}

// ── Specialty Tag ─────────────────────────────────────────────────────────────
function SpecialtyTag({ cat }: { cat: string }) {
  const cls: Record<string, string> = {
    PCP: "bg-primary/10 text-primary",
    Specialist:
      "bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300",
    Hospitalist:
      "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300",
  };
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded-md text-[11px] font-semibold ${cls[cat] ?? "bg-muted text-muted-foreground"}`}
    >
      {cat}
    </span>
  );
}

// ── Sort icon ─────────────────────────────────────────────────────────────────
function SortIcon({
  field,
  activeField,
  activeDir,
}: {
  field: SortField;
  activeField: SortField;
  activeDir: SortDir;
}) {
  if (activeField !== field)
    return <ArrowUpDown size={12} className="opacity-40" />;
  return activeDir === "asc" ? (
    <ChevronUp size={13} className="text-primary" />
  ) : (
    <ChevronDown size={13} className="text-primary" />
  );
}

// ── Sortable TH ───────────────────────────────────────────────────────────────
function SortTh({
  field,
  label,
  sortField,
  sortDir,
  onSort,
}: {
  field: SortField;
  label: string;
  sortField: SortField;
  sortDir: SortDir;
  onSort: (f: SortField) => void;
}) {
  const active = sortField === field;
  return (
    <th
      onClick={() => onSort(field)}
      className={`px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground whitespace-nowrap cursor-pointer select-none transition-colors hover:text-foreground ${active ? "bg-primary/8 text-primary" : ""}`}
    >
      <div className="flex items-center gap-1.5">
        {label}
        <SortIcon field={field} activeField={sortField} activeDir={sortDir} />
      </div>
    </th>
  );
}

// ── Static TH ─────────────────────────────────────────────────────────────────
function StaticTh({ label }: { label: string }) {
  return (
    <th className="px-3 py-2.5 text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground whitespace-nowrap">
      {label}
    </th>
  );
}

// ══════════════════════════════════════════════════════════════════════════════
// Page Component
// ══════════════════════════════════════════════════════════════════════════════
export default function ProvidersPage() {
  const [search, setSearch] = useState("");
  const [specialtyFilter, setSpecialtyFilter] =
    useState<SpecialtyFilter>("all");
  const [sortField, setSortField] = useState<SortField>("hcc_capture_rate");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [showDiscoverDialog, setShowDiscoverDialog] = useState(false);
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
          (r.npi ?? "").includes(q),
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
            ? `${a.last_name} ${a.first_name}`.localeCompare(
                `${b.last_name} ${b.first_name}`,
              )
            : `${b.last_name} ${b.first_name}`.localeCompare(
                `${a.last_name} ${a.first_name}`,
              );
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
      else {
        setSortField(field);
        setSortDir("desc");
      }
    },
    [sortField],
  );

  function exportProvidersCSV() {
    if (!filtered.length) return;
    downloadCSV(
      filtered.map((p) => ({
        NPI: p.npi ?? "",
        Name: providerName(p),
        Specialty: p.specialty,
        "Patient Count": p.patient_count,
        "Avg RAF":
          p.average_raf_score != null
            ? Number(p.average_raf_score).toFixed(2)
            : "",
        "Capture Rate":
          p.hcc_capture_rate != null
            ? `${Math.round(p.hcc_capture_rate * 100)}%`
            : "",
      })),
      "providers",
    );
  }

  const isLoading = sumLoading || lbLoading;

  return (
    <div className="p-6 min-h-screen bg-background">
      {/* ── Page Header ──────────────────────────────────────────────────── */}
      <PageHeader
        title="Provider Scorecards"
        subtitle="Provider-level RAF capture rates, HCC coding performance, and revenue metrics"
        icon={<Stethoscope size={22} />}
        actions={
          <>
            <button
              onClick={() => setShowFeatureSettings(true)}
              title="Page features (add/hide sections)"
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-border bg-card text-muted-foreground text-[13px] font-medium hover:bg-muted/60 transition-colors"
            >
              <Settings size={15} aria-hidden />
              Page Features
            </button>
            <button
              onClick={() => setShowDiscoverDialog(true)}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg border border-border bg-card text-muted-foreground text-[13px] font-medium hover:bg-muted/60 transition-colors"
            >
              <Zap size={15} aria-hidden />
              Auto-Discover from EMR
            </button>
            <button
              onClick={() => setShowAddDialog(true)}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg border-0 bg-primary text-primary-foreground text-[13px] font-semibold hover:bg-primary/90 transition-colors"
            >
              <Plus size={15} aria-hidden />
              Add Provider
            </button>
          </>
        }
      />

      {/* ── KPI Strip ────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4 mb-7">
        {isLoading ? (
          Array.from({ length: 5 }).map((_, i) => (
            <MetricCard key={i} label="" value="" loading />
          ))
        ) : (
          <>
            <MetricCard
              label="Total Providers"
              value={summary?.total_providers?.toLocaleString() ?? "—"}
              subtitle="In this system"
              icon={<Users size={18} />}
            />
            <MetricCard
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
              intent={
                summary?.avg_capture_rate != null &&
                summary.avg_capture_rate >= 0.85
                  ? "success"
                  : "warning"
              }
            />
            <MetricCard
              label="Avg RAF Score"
              value={summary ? fmtN(summary.average_raf_score, 3) : "—"}
              subtitle="Population average"
              icon={<TrendingUp size={18} />}
              intent="warning"
            />
            <MetricCard
              label="Revenue Opportunity"
              value={summary ? fmt$(summary.total_revenue_opportunity) : "—"}
              subtitle="Across all providers"
              icon={<DollarSign size={18} />}
              intent="success"
            />
            <MetricCard
              label="Avg MEAT Score"
              value={summary ? fmtPct(summary.avg_meat_completeness) : "—"}
              subtitle="Documentation quality"
              icon={<Award size={18} />}
            />
          </>
        )}
      </div>

      {/* ── Leaderboard Table ────────────────────────────────────────────── */}
      <div className="bg-card border border-border rounded-[14px] overflow-clip">
        {/* Toolbar */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border flex-wrap gap-3">
          <div className="flex items-center gap-2.5">
            <h2 className="m-0 text-base font-bold text-foreground">
              Provider Leaderboard
            </h2>
            <span className="text-xs font-semibold text-primary bg-primary/10 px-2 py-0.5 rounded-full">
              {filtered.length}
            </span>
          </div>

          <div className="flex items-center gap-2.5 flex-wrap">
            {/* Search */}
            <div className="relative flex items-center">
              <Search
                size={14}
                className="absolute left-2.5 text-muted-foreground/60 pointer-events-none"
                aria-hidden
              />
              <input
                type="text"
                placeholder="Search by name or NPI..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                aria-label="Search providers"
                className="pl-8 pr-3.5 py-2 border border-border rounded-lg text-[13px] w-[220px] bg-card text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>

            {/* Specialty filter */}
            <div className="relative flex items-center">
              <Filter
                size={13}
                className="absolute left-2.5 text-muted-foreground/60 pointer-events-none"
                aria-hidden
              />
              <select
                value={specialtyFilter}
                onChange={(e) =>
                  setSpecialtyFilter(e.target.value as SpecialtyFilter)
                }
                aria-label="Filter by specialty category"
                className="pl-7 pr-8 py-2 border border-border rounded-lg text-[13px] bg-card text-foreground cursor-pointer appearance-none focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="all">All Categories</option>
                <option value="PCP">PCP</option>
                <option value="Specialist">Specialist</option>
                <option value="Hospitalist">Hospitalist</option>
              </select>
              <ChevronDown
                size={13}
                className="absolute right-2.5 text-muted-foreground/60 pointer-events-none"
                aria-hidden
              />
            </div>

            <button
              onClick={exportProvidersCSV}
              aria-label="Export providers as CSV"
              className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-primary text-primary-foreground text-[13px] font-semibold hover:bg-primary/90 transition-colors flex-shrink-0"
            >
              <FileDown size={14} aria-hidden />
              Export CSV
            </button>
          </div>
        </div>

        {/* Table */}
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-[13px]">
            <thead>
              <tr className="border-b-2 border-border bg-muted/30">
                <StaticTh label="Rank" />
                <SortTh
                  field="name"
                  label="Provider"
                  sortField={sortField}
                  sortDir={sortDir}
                  onSort={handleSort}
                />
                <StaticTh label="Specialty" />
                <SortTh
                  field="patient_count"
                  label="Patients"
                  sortField={sortField}
                  sortDir={sortDir}
                  onSort={handleSort}
                />
                <SortTh
                  field="average_raf_score"
                  label="Avg RAF"
                  sortField={sortField}
                  sortDir={sortDir}
                  onSort={handleSort}
                />
                <SortTh
                  field="hcc_capture_rate"
                  label="HCC Capture"
                  sortField={sortField}
                  sortDir={sortDir}
                  onSort={handleSort}
                />
                <SortTh
                  field="recapture_rate"
                  label="Recapture"
                  sortField={sortField}
                  sortDir={sortDir}
                  onSort={handleSort}
                />
                <SortTh
                  field="meat_score"
                  label="MEAT Score"
                  sortField={sortField}
                  sortDir={sortDir}
                  onSort={handleSort}
                />
                <SortTh
                  field="revenue_opportunity"
                  label="Revenue Opp."
                  sortField={sortField}
                  sortDir={sortDir}
                  onSort={handleSort}
                />
                <StaticTh label="Actions" />
              </tr>
            </thead>

            <tbody>
              {/* ── Loading skeleton ── */}
              {lbLoading &&
                Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i} className="border-b border-border/50">
                    {Array.from({ length: 10 }).map((__, j) => (
                      <td key={j} className="px-3 py-3.5">
                        <div
                          className={`h-3.5 rounded animate-pulse bg-muted ${j === 1 ? "w-4/5" : j === 2 ? "w-3/5" : "w-1/2"}`}
                        />
                      </td>
                    ))}
                  </tr>
                ))}

              {/* ── Empty state ── */}
              {!lbLoading && filtered.length === 0 && (
                <tr>
                  <td colSpan={10} className="px-6 py-12 text-center">
                    {leaderboard.length === 0 ? (
                      <EmptyState
                        state="no-data"
                        icon={<Users size={28} />}
                        title="No providers yet"
                        description="Add a provider to start scoring, or use Auto-Discover to import from your EMR."
                        cta={{
                          label: "Add Your First Provider",
                          onClick: () => setShowAddDialog(true),
                        }}
                      />
                    ) : (
                      <EmptyState
                        state="filtered-out"
                        icon={<Users size={28} />}
                        description="Try adjusting the search or specialty filter."
                        cta={{
                          label: "Clear filters",
                          onClick: () => {
                            setSearch("");
                            setSpecialtyFilter("all");
                          },
                        }}
                      />
                    )}
                  </td>
                </tr>
              )}

              {/* ── Data rows ── */}
              {!lbLoading &&
                filtered.map((row, idx) => {
                  const isExpanded = expandedId === row.provider_id;
                  const initials = (
                    ((row.first_name || "").trim()[0] || "").toUpperCase() +
                    (row.first_name && row.last_name
                      ? ((row.last_name || "").trim()[0] || "").toUpperCase()
                      : "")
                  ) || "•";
                  const avatarColor = initialsColor(providerName(row));

                  return (
                    <React.Fragment key={row.provider_id}>
                      <tr
                        onClick={() =>
                          setExpandedId(isExpanded ? null : row.provider_id)
                        }
                        aria-expanded={isExpanded}
                        className={`border-b border-border/50 cursor-pointer transition-colors ${isExpanded ? "bg-primary/5" : "hover:bg-muted/30"}`}
                        style={{ animationDelay: `${idx * 40}ms` }}
                      >
                        {/* Rank */}
                        <td className="px-3 py-3">
                          <RankBadge rank={idx + 1} />
                        </td>

                        {/* Provider name */}
                        <td className="px-3 py-3">
                          <div className="flex items-center gap-2.5">
                            <div
                              className="w-9 h-9 rounded-[10px] flex items-center justify-center text-white text-[13px] font-bold flex-shrink-0"
                              style={{
                                background: `linear-gradient(135deg, ${avatarColor}, ${avatarColor}cc)`,
                                boxShadow: `0 2px 8px ${avatarColor}40`,
                              }}
                              aria-hidden
                            >
                              {initials}
                            </div>
                            <div>
                              <div className="font-semibold text-foreground">
                                {providerName(row)}
                              </div>
                              {row.npi && (
                                <div className="text-[11px] text-muted-foreground mt-0.5">
                                  NPI: {row.npi}
                                </div>
                              )}
                            </div>
                          </div>
                        </td>

                        {/* Specialty */}
                        <td className="px-3 py-3">
                          <div className="text-xs text-foreground mb-1">
                            {row.specialty}
                          </div>
                          <SpecialtyTag cat={row.specialty_category} />
                        </td>

                        {/* Patients */}
                        <td className="px-3 py-3 font-semibold text-foreground">
                          {row.patient_count.toLocaleString()}
                        </td>

                        {/* Avg RAF */}
                        <td className="px-3 py-3 font-semibold text-foreground">
                          {fmtN(row.average_raf_score, 3)}
                        </td>

                        {/* HCC Capture */}
                        <td className="px-3 py-3">
                          <div className="flex flex-col gap-1">
                            <CaptureBadge rate={row.hcc_capture_rate} />
                            <MiniBar rate={row.hcc_capture_rate} />
                          </div>
                        </td>

                        {/* Recapture */}
                        <td className="px-3 py-3">
                          <div className="flex flex-col gap-1">
                            <CaptureBadge rate={row.recapture_rate} />
                            <MiniBar rate={row.recapture_rate} />
                          </div>
                        </td>

                        {/* MEAT Score */}
                        <td className="px-3 py-3">
                          {row.meat_score != null ? (
                            <div className="flex flex-col gap-1">
                              <span className="text-[13px] font-bold text-violet-600 dark:text-violet-400">
                                {fmtPct(row.meat_score)}
                              </span>
                              <div className="h-1 rounded-full bg-muted overflow-hidden w-[60px]">
                                <div
                                  className="h-full rounded-full bg-violet-500 transition-[width] duration-300"
                                  style={{
                                    width: `${Math.round(row.meat_score * 100)}%`,
                                  }}
                                />
                              </div>
                            </div>
                          ) : (
                            <span className="text-muted-foreground text-xs">
                              --
                            </span>
                          )}
                        </td>

                        {/* Revenue Opportunity */}
                        <td className="px-3 py-3">
                          <div className="flex items-center gap-1.5">
                            <span className="font-bold text-emerald-700 dark:text-emerald-400">
                              {fmt$(row.revenue_opportunity)}
                            </span>
                            {(row.revenue_opportunity ?? 0) > 50_000 && (
                              <span
                                aria-label="High revenue opportunity"
                                className="inline-flex items-center justify-center w-5 h-5 rounded-md bg-emerald-50 dark:bg-emerald-900/30"
                                title="High revenue opportunity"
                              >
                                <TrendingUp
                                  size={10}
                                  className="text-emerald-600 dark:text-emerald-400"
                                  aria-hidden
                                />
                              </span>
                            )}
                          </div>
                        </td>

                        {/* Actions */}
                        <td className="px-3 py-3">
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setExpandedId(
                                isExpanded ? null : row.provider_id,
                              );
                            }}
                            title={isExpanded ? "Collapse" : "View scorecard"}
                            aria-label={
                              isExpanded ? "Collapse row" : "Expand scorecard"
                            }
                            className={`inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border text-xs font-semibold transition-all ${isExpanded ? "border-primary bg-primary/10 text-primary" : "border-border bg-card text-muted-foreground hover:border-primary/50 hover:text-foreground"}`}
                          >
                            {isExpanded ? (
                              <ChevronUp size={13} aria-hidden />
                            ) : (
                              <ChevronDown size={13} aria-hidden />
                            )}
                            {isExpanded ? "Collapse" : "Scorecard"}
                          </button>
                        </td>
                      </tr>

                      {/* Inline detail panel */}
                      {isExpanded && (
                        <tr>
                          <td
                            colSpan={10}
                            className="px-4 pb-5 border-b border-border bg-muted/20"
                            style={{ height: "auto", minHeight: 0 }}
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
                })}
            </tbody>
          </table>
        </div>

        {/* Table footer — count + legend */}
        {!lbLoading && filtered.length > 0 && (
          <div className="px-5 py-3 border-t border-border flex items-center justify-between flex-wrap gap-3 text-xs text-muted-foreground">
            <span>
              Showing {filtered.length} of {leaderboard.length} providers
              {specialtyFilter !== "all" && ` · Filtered: ${specialtyFilter}`}
            </span>
            <div className="flex items-center gap-3">
              {[
                {
                  bar: "bg-emerald-500",
                  badge: "bg-emerald-50 text-emerald-700",
                  label: "Capture ≥85%",
                },
                {
                  bar: "bg-amber-500",
                  badge: "bg-amber-50 text-amber-700",
                  label: "70–85%",
                },
                {
                  bar: "bg-red-500",
                  badge: "bg-red-50 text-red-700",
                  label: "<70%",
                },
              ].map((item) => (
                <div
                  key={item.label}
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold ${item.badge}`}
                >
                  <div className={`w-2 h-2 rounded-full ${item.bar}`} />
                  {item.label}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Lazy-loaded dialogs ──────────────────────────────────────────── */}
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
