"use client";

import React, { useState, useMemo, useCallback } from "react";
import dynamic from "next/dynamic";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { downloadCSV } from "@/lib/csv-export";
import {
  Target,
  RefreshCw,
  Download,
  FileDown,
  Calendar,
  Search,
  ChevronLeft,
  ChevronRight,
  Users,
  AlertTriangle,
  TrendingUp,
  ClipboardList,
  X,
  Phone,
  Printer,
  Eye,
  CalendarPlus,
  FileText,
  CheckCircle,
  Clock,
  Star,
} from "lucide-react";
import {
  searchPatients,
  getPopulationSummary,
  getSuspects,
  getRecaptureGapsReport,
  getRevenueOpportunity,
  useMetricFormula,
} from "@/lib/api";
import { StatCard, PageHeader, EmptyState } from "@/components/healthcare-ui";
import { fmtCurrencyFull, fmtCurrencyCompact } from "@/lib/format";
import { tokens } from "@/styles/tokens";
// ── Dynamic import: defer Pre-Visit Summary modal (~35 kB) ──
// Modal only opens on user click — zero cost on initial page paint.
const PreVisitSummaryModal = dynamic(
  () => import("./PreVisitSummaryModal"),
  { ssr: false, loading: () => null }
);

// ─── Design Tokens (single source of truth: tokens.ts) ───────────────────────

const C = {
  primary: tokens.primary,
  slate900: tokens.slate900,
  slate700: tokens.slate700,
  slate600: tokens.slate600,
  slate400: tokens.slate400,
  slate300: tokens.slate300,
  slate200: tokens.slate200,
  slate100: tokens.slate100,
  slate50: tokens.slate50,
  white: tokens.white,
  red600: tokens.riskHigh,
  red50: tokens.riskHighSoft,
  amber500: tokens.warningStrong,
  amber50: tokens.warningSoft,
  emerald500: tokens.success,
  emerald50: tokens.successSoft,
  purple600: tokens.accentPurple,
  purple50: "rgba(139,92,246,0.08)",
  gold: tokens.riskMedium,
  silver: tokens.slate500,
  bronze: tokens.warningText,
  subtleText: tokens.slate500,
};

// ─── Types ────────────────────────────────────────────────────────────────────

interface EnrichedPatient {
  pid: number;
  fname: string;
  lname: string;
  DOB?: string;
  sex?: string;
  phone?: string;
  city?: string;
  state?: string;
  provider?: string;
  raf_score: number;
  hcc_count: number;
  last_visit_date: string | null;
  days_since_visit: number;
  open_suspects_count: number;
  recapture_gaps_count: number;
  potential_raf: number;
  raf_gap: number;
  estimated_revenue_opportunity: number;
  priority_score: number;
  priority_level: "High" | "Medium" | "Low";
  awv_eligible: boolean;
  awv_had_this_year: boolean;
}

interface PreVisitSummaryPatient {
  pid: number;
  fname: string;
  lname: string;
  DOB?: string;
  sex?: string;
  raf_score: number;
  potential_raf: number;
  raf_gap: number;
  open_suspects_count: number;
  recapture_gaps_count: number;
  estimated_revenue_opportunity: number;
  provider?: string;
}

type DaysSinceFilter = "all" | "30" | "90" | "180" | "365";
type PriorityFilter = "all" | "High" | "Medium" | "Low";

const PAGE_SIZE = 20;
const REVENUE_PER_RAF_POINT = 12000;
const AVG_SUSPECT_HCC_COEFFICIENT = 0.35;
const AWV_REVENUE_INITIAL = 250;
const AWV_REVENUE_SUBSEQUENT = 175;

// ─── Helpers ──────────────────────────────────────────────────────────────────

function daysSince(dateStr: string | null): number {
  if (!dateStr) return 9999;
  const diff = Date.now() - new Date(dateStr).getTime();
  return Math.floor(diff / (1000 * 60 * 60 * 24));
}

function fmtDate(dateStr: string | null): string {
  if (!dateStr) return "Never";
  return new Date(dateStr).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function fmtCurrency(n: number): string {
  return fmtCurrencyFull(n);
}

function calcAge(dob?: string): number | null {
  if (!dob) return null;
  const diff = Date.now() - new Date(dob).getTime();
  return Math.floor(diff / (365.25 * 24 * 60 * 60 * 1000));
}

function priorityLevel(score: number): "High" | "Medium" | "Low" {
  if (score >= 70) return "High";
  if (score >= 35) return "Medium";
  return "Low";
}

function priorityColor(level: "High" | "Medium" | "Low"): string {
  if (level === "High") return C.red600;
  if (level === "Medium") return C.amber500;
  return C.emerald500;
}

function rankMedal(rank: number): { bg: string; color: string; label: string } | null {
  if (rank === 1) return { bg: tokens.warningSoft, color: C.gold, label: "1" };
  if (rank === 2) return { bg: tokens.slate100, color: C.silver, label: "2" };
  if (rank === 3) return { bg: tokens.warningSoft, color: C.bronze, label: "3" };
  return null;
}

// ─── AWV Tracker Row ──────────────────────────────────────────────────────────

function AwvRow({
  patient,
  index,
  scheduledAwv,
  onMarkScheduled,
}: {
  patient: EnrichedPatient;
  index: number;
  scheduledAwv: Set<number>;
  onMarkScheduled: (pid: number) => void;
}) {
  const age = calcAge(patient.DOB);
  const isInitial = !patient.awv_had_this_year && (age ?? 0) >= 65;
  const awvRevenue = isInitial ? AWV_REVENUE_INITIAL : AWV_REVENUE_SUBSEQUENT;

  const scheduled = scheduledAwv.has(patient.pid);

  return (
    <tr
      style={{ backgroundColor: index % 2 === 0 ? C.white : C.slate50, transition: "background 0.15s" }}
      onMouseEnter={(e) => { e.currentTarget.style.background = `${C.primary}08`; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = index % 2 === 0 ? C.white : C.slate50; }}
    >
      <td style={{ padding: "12px 16px", fontSize: 13, fontWeight: 600, color: C.primary }}>
        {patient.lname}, {patient.fname}
        <div style={{ fontSize: 11, color: C.subtleText, fontWeight: 400 }}>PID #{patient.pid}</div>
      </td>
      <td style={{ padding: "12px 16px", fontSize: 13, color: C.subtleText }}>
        {age !== null ? `${age} ${patient.sex === "Female" ? "F" : patient.sex === "Male" ? "M" : ""}` : "—"}
      </td>
      <td style={{ padding: "12px 16px", fontSize: 13, color: C.slate900 }}>
        {patient.provider || "—"}
      </td>
      <td style={{ padding: "12px 16px", fontSize: 13, color: C.subtleText }}>
        {fmtDate(patient.last_visit_date)}
      </td>
      <td style={{ padding: "12px 16px", fontSize: 13 }}>
        <span
          style={{
            display: "inline-block",
            padding: "3px 10px",
            borderRadius: 999,
            fontSize: 11,
            fontWeight: 600,
            color: isInitial ? C.purple600 : C.primary,
            backgroundColor: isInitial ? `${C.purple600}1A` : `${C.primary}1A`,
          }}
        >
          {isInitial ? "Initial AWV" : "Subsequent AWV"}
        </span>
      </td>
      <td className="tabular-nums" style={{ padding: "12px 16px", fontSize: 13, fontWeight: 700, color: C.emerald500 }}>
        {fmtCurrency(awvRevenue)}
      </td>
      <td style={{ padding: "12px 16px" }}>
        {scheduled ? (
          <span style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 12, color: C.emerald500, fontWeight: 600 }}>
            <CheckCircle size={13} /> Scheduled
          </span>
        ) : (
          <button
            onClick={() => { onMarkScheduled(patient.pid); }}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 5,
              padding: "6px 12px",
              borderRadius: 7,
              border: `1px solid ${C.primary}`,
              background: `${C.primary}0D`,
              fontSize: 12,
              fontWeight: 600,
              color: C.primary,
              cursor: "pointer",
            }}
          >
            <CalendarPlus size={12} /> Schedule
          </button>
        )}
      </td>
    </tr>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function ProspectivePage() {
  const router = useRouter();
  const [search, setSearch] = useState("");
  const [providerFilter, setProviderFilter] = useState("all");
  const [priorityFilter, setPriorityFilter] = useState<PriorityFilter>("all");
  const [daysSinceFilter, setDaysSinceFilter] = useState<DaysSinceFilter>("all");
  const [page, setPage] = useState(0);
  const [preVisitPatient, setPreVisitPatient] = useState<PreVisitSummaryPatient | null>(null);
  const [scheduledAwv, setScheduledAwv] = useState<Set<number>>(new Set());

  // ── Data Fetching ──────────────────────────────────────────────────────────

  const { data: patientsData, isLoading: loadingPatients, isError: patientsError, refetch: refetchPatients } = useQuery({
    queryKey: ["prospective-patients"],
    queryFn: () => searchPatients({ limit: 500, offset: 0 }),
    staleTime: 5 * 60 * 1000,
  });

  useQuery({
    queryKey: ["population-summary"],
    queryFn: () => getPopulationSummary(),
    staleTime: 5 * 60 * 1000,
  });

  const { data: suspectsData } = useQuery({
    queryKey: ["suspects-open"],
    queryFn: () => getSuspects("open", 1000),
    staleTime: 5 * 60 * 1000,
  });

  const { data: recaptureReport } = useQuery<{ gaps?: { pid?: number | string }[] }>({
    queryKey: ["recapture-gaps-current"],
    queryFn: () => getRecaptureGapsReport(new Date().getFullYear()),
    staleTime: 5 * 60 * 1000,
  });

  const { data: revenueData } = useQuery({
    queryKey: ["revenue-opportunity"],
    queryFn: () => getRevenueOpportunity(new Date().getFullYear()),
    staleTime: 5 * 60 * 1000,
  });
  const revenueAtRiskMeta = useMetricFormula(revenueData as Record<string, unknown> | null | undefined, "estimated_annual_revenue") ?? revenueData?._meta ?? null;

  // ── Data Enrichment ────────────────────────────────────────────────────────

  const enrichedPatients = useMemo<EnrichedPatient[]>(() => {
    const rawPatients = patientsData?.patients ?? [];
    if (!rawPatients.length) return [];

    // Build suspect counts per patient
    const suspectsByPid = new Map<number, number>();
    const suspects = suspectsData?.suspects ?? [];
    for (const s of suspects) {
      const pid = Number(s.patient_id);
      suspectsByPid.set(pid, (suspectsByPid.get(pid) ?? 0) + 1);
    }

    // Build recapture gap counts per patient
    const recaptureByPid = new Map<number, number>();
    const gaps = recaptureReport?.gaps ?? [];
    for (const g of gaps) {
      const pid = Number(g.pid);
      recaptureByPid.set(pid, (recaptureByPid.get(pid) ?? 0) + 1);
    }

    type RawPatient = { pid?: number | string; raf_score?: number; hcc_count?: number; encounters?: { date?: string; encounter_date?: string; cpt_code?: string; codes?: string }[]; last_visit_date?: string; DOB?: string; sex?: string; phone_cell?: string; phone_home?: string; phone?: string; city?: string; state?: string; provider?: string; provider_name?: string; fname?: string; lname?: string; insurance_type?: string };
    return (rawPatients as RawPatient[]).map((p): EnrichedPatient => {
      const pid = Number(p.pid);
      const raf = Number(p.raf_score ?? 0);
      const hccCount = Number(p.hcc_count ?? 0);

      // Derive last visit from encounters if available
      const encounters = p.encounters ?? [];
      let lastVisitDate: string | null = null;
      if (encounters.length > 0) {
        const sorted = [...encounters].sort(
          (a, b) => new Date(b.date ?? b.encounter_date ?? 0).getTime() - new Date(a.date ?? a.encounter_date ?? 0).getTime()
        );
        lastVisitDate = sorted[0]?.date ?? sorted[0]?.encounter_date ?? null;
      } else if (p.last_visit_date) {
        lastVisitDate = p.last_visit_date;
      }

      const days = daysSince(lastVisitDate);
      const openSuspects = suspectsByPid.get(pid) ?? 0;
      const recaptureGaps = recaptureByPid.get(pid) ?? 0;

      // Potential RAF: current + suspects * avg HCC coefficient
      const potentialRaf = raf + openSuspects * AVG_SUSPECT_HCC_COEFFICIENT;
      const rafGap = potentialRaf - raf;
      const revenueOpportunity = rafGap * REVENUE_PER_RAF_POINT + recaptureGaps * 3000;

      // Priority score: weighted composite
      // Days since visit: 0-40 pts; suspects: 0-30 pts; RAF gap: 0-20 pts; HCC count: 0-10 pts
      const daysScore = Math.min((days / 365) * 40, 40);
      const suspectScore = Math.min(openSuspects * 6, 30);
      const rafGapScore = Math.min(rafGap * 20, 20);
      const hccScore = Math.min(hccCount * 2, 10);
      const priorityScore = daysScore + suspectScore + rafGapScore + hccScore;

      // AWV eligibility: Medicare patients (age >= 65 or enrolled) who haven't had AWV this year
      const age = calcAge(p.DOB) ?? 0;
      const awvEligible = age >= 65 || Boolean(p.insurance_type?.toLowerCase().includes("medicare"));
      const currentYear = new Date().getFullYear();
      const awvHadThisYear = encounters.some((enc) => {
        const encYear = new Date(enc.date ?? enc.encounter_date ?? 0).getFullYear();
        const cpt = enc.cpt_code ?? enc.codes ?? "";
        return encYear === currentYear && (cpt.includes("G0439") || cpt.includes("G0438") || cpt.includes("99387") || cpt.includes("99397"));
      });

      return {
        pid,
        fname: p.fname ?? "",
        lname: p.lname ?? "",
        DOB: p.DOB,
        sex: p.sex,
        phone: p.phone_cell ?? p.phone_home ?? p.phone ?? "",
        city: p.city,
        state: p.state,
        provider: p.provider ?? p.provider_name ?? "",
        raf_score: raf,
        hcc_count: hccCount,
        last_visit_date: lastVisitDate,
        days_since_visit: days,
        open_suspects_count: openSuspects,
        recapture_gaps_count: recaptureGaps,
        potential_raf: potentialRaf,
        raf_gap: rafGap,
        estimated_revenue_opportunity: revenueOpportunity,
        priority_score: priorityScore,
        priority_level: priorityLevel(priorityScore),
        awv_eligible: awvEligible,
        awv_had_this_year: awvHadThisYear,
      };
    });
  }, [patientsData, suspectsData, recaptureReport]);

  // ── Derived stats ──────────────────────────────────────────────────────────

  const stats = useMemo(() => {
    const currentYear = new Date().getFullYear();
    const notSeenThisYear = enrichedPatients.filter((p) => {
      if (!p.last_visit_date) return true;
      return new Date(p.last_visit_date).getFullYear() < currentYear;
    }).length;

    const totalSuspects = enrichedPatients.reduce((sum, p) => sum + p.open_suspects_count, 0);
    const totalRevenue = enrichedPatients.reduce((sum, p) => sum + p.estimated_revenue_opportunity, 0);
    const awvOpportunities = enrichedPatients.filter((p) => p.awv_eligible && !p.awv_had_this_year).length;
    const highPriority = enrichedPatients.filter((p) => p.priority_level === "High").length;

    return { notSeenThisYear, totalSuspects, totalRevenue, awvOpportunities, highPriority };
  }, [enrichedPatients]);

  // ── Providers list ─────────────────────────────────────────────────────────

  const providers = useMemo(() => {
    const set = new Set<string>();
    for (const p of enrichedPatients) {
      if (p.provider) set.add(p.provider);
    }
    return Array.from(set).sort();
  }, [enrichedPatients]);

  // ── Filtered + sorted worklist ─────────────────────────────────────────────

  const filtered = useMemo(() => {
    let list = [...enrichedPatients].sort((a, b) => b.priority_score - a.priority_score);

    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        (p) =>
          p.fname.toLowerCase().includes(q) ||
          p.lname.toLowerCase().includes(q) ||
          String(p.pid).includes(q)
      );
    }
    if (providerFilter !== "all") {
      list = list.filter((p) => p.provider === providerFilter);
    }
    if (priorityFilter !== "all") {
      list = list.filter((p) => p.priority_level === priorityFilter);
    }
    if (daysSinceFilter !== "all") {
      const threshold = parseInt(daysSinceFilter, 10);
      list = list.filter((p) => p.days_since_visit >= threshold);
    }

    return list;
  }, [enrichedPatients, search, providerFilter, priorityFilter, daysSinceFilter]);

  // Reset page on filter change
  React.useEffect(() => { setPage(0); }, [search, providerFilter, priorityFilter, daysSinceFilter]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paged = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  // ── AWV eligible list ──────────────────────────────────────────────────────

  const awvList = useMemo(
    () => enrichedPatients.filter((p) => p.awv_eligible && !p.awv_had_this_year && !scheduledAwv.has(p.pid)).slice(0, 10),
    [enrichedPatients, scheduledAwv]
  );

  // ── Chase List Export ──────────────────────────────────────────────────────

  const exportChaseList = useCallback(() => {
    if (!filtered.length) return;
    const outreachScript =
      "Hi, this is [Practice Name] calling for [Patient Name]. " +
      "We noticed it has been a while since your last visit with Dr. [Provider]. " +
      "We wanted to reach out to schedule your Annual Wellness Visit and make sure all your health conditions are properly managed. " +
      "Please call us back at [Phone Number] or visit [Portal URL] to schedule.";

    const header = "Patient Name,PID,Phone,Address,Last Visit,Days Since Visit,Priority,Open Suspects,Recapture Gaps,Provider,Revenue Opportunity,Outreach Script\n";
    const rows = filtered
      .map(
        (p) =>
          `"${p.lname}, ${p.fname}",${p.pid},"${p.phone || ""}","${[p.city, p.state].filter(Boolean).join(", ")}","${fmtDate(p.last_visit_date)}",${p.days_since_visit === 9999 ? "Never seen" : p.days_since_visit},${p.priority_level},${p.open_suspects_count},${p.recapture_gaps_count},"${p.provider || ""}","${fmtCurrency(p.estimated_revenue_opportunity)}","${outreachScript}"`
      )
      .join("\n");
    const blob = new Blob([header + rows], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `chase-list-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [filtered]);

  function exportWorklistCSV() {
    if (!filtered.length) return;
    downloadCSV(filtered.map((p) => ({
      "Name": `${p.lname}, ${p.fname}`,
      "DOB": p.DOB ?? "",
      "RAF Score": Number(p.raf_score).toFixed(2),
      "Open Gaps": p.open_suspects_count + p.recapture_gaps_count,
      "Priority": p.priority_level,
      "Last Visit": p.last_visit_date ? fmtDate(p.last_visit_date) : "Never",
      "AWV Eligible": p.awv_eligible ? "Yes" : "No",
    })), "prospective-worklist");
  }

  // ── Shared styles ──────────────────────────────────────────────────────────

  const cardStyle: React.CSSProperties = {
    background: C.white,
    border: `1px solid ${C.slate200}`,
    borderRadius: 12,
  };

  const thStyle: React.CSSProperties = {
    padding: "10px 12px",
    fontSize: 11,
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "0.05em",
    color: C.slate400,
    textAlign: "left",
    borderBottom: `1px solid ${C.slate200}`,
    whiteSpace: "nowrap",
    background: C.slate50,
  };

  const tdStyle: React.CSSProperties = {
    padding: "11px 12px",
    fontSize: 13,
    color: C.slate900,
    borderBottom: `1px solid ${C.slate100}`,
    verticalAlign: "middle",
  };

  const selectStyle: React.CSSProperties = {
    padding: "7px 10px",
    borderRadius: 8,
    border: `1px solid ${C.slate200}`,
    fontSize: 13,
    color: C.slate900,
    background: C.white,
    cursor: "pointer",
  };

  const actionBtnStyle: React.CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: 4,
    padding: "5px 9px",
    borderRadius: 6,
    border: `1px solid ${C.slate200}`,
    background: C.white,
    fontSize: 11,
    fontWeight: 600,
    color: C.slate600,
    cursor: "pointer",
    whiteSpace: "nowrap",
  };

  if (patientsError) {
    return (
      <div style={{ padding: 32, maxWidth: 1400, margin: "0 auto" }}>
        <PageHeader title="Prospective RAF Management" icon={<Target size={22} />} />
        <div
          role="alert"
          style={{
            display: "flex", alignItems: "center", gap: 12,
            padding: "14px 18px", borderRadius: 10,
            background: tokens.riskHighSoft,
            border: `1px solid ${tokens.dangerBorder}`,
            color: tokens.riskHigh, fontSize: 14, marginBottom: 24,
          }}
        >
          <AlertTriangle size={18} aria-hidden="true" />
          <span style={{ flex: 1 }}>Failed to load patient data. Please check your connection and try again.</span>
          <button
            type="button"
            onClick={() => refetchPatients()}
            aria-label="Retry loading patient data"
            style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              padding: "6px 12px", borderRadius: 8,
              border: `1px solid ${tokens.dangerBorder}`,
              background: tokens.white, color: tokens.riskHigh,
              fontSize: 13, fontWeight: 600, cursor: "pointer",
            }}
          >
            <RefreshCw size={14} /> Retry
          </button>
        </div>
      </div>
    );
  }

  if (loadingPatients) {
    return (
      <div style={{ padding: 32, maxWidth: 1400, margin: "0 auto" }}>
        <PageHeader title="Prospective RAF Management" icon={<Target size={22} />} />
        {/* Stats skeleton */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 16, marginBottom: 24 }}>
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className={`premium-card shimmer animate-slide-up stagger-${i + 1}`} style={{ background: C.white, border: `1px solid ${C.slate200}`, borderRadius: 12, padding: 20 }}>
              <div className="skeleton" style={{ width: 90, height: 12, borderRadius: 4, marginBottom: 10 }} />
              <div className="skeleton" style={{ width: 60, height: 28, borderRadius: 4, marginBottom: 8 }} />
              <div className="skeleton" style={{ width: 110, height: 10, borderRadius: 4 }} />
            </div>
          ))}
        </div>
        {/* Table skeleton */}
        <div className="premium-card premium-shadow animate-fade-in" style={{ background: C.white, border: `1px solid ${C.slate200}`, borderRadius: 12, overflow: "hidden" }}>
          <div style={{ height: 44, background: C.slate50, borderBottom: `1px solid ${C.slate200}` }} />
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="shimmer" style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr 1fr 1fr 80px", alignItems: "center", padding: "0 16px", height: 60, borderBottom: `1px solid ${C.slate100}`, gap: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <div style={{ width: 32, height: 32, borderRadius: 16, background: C.slate100, flexShrink: 0 }} />
                <div style={{ width: 130, height: 12, borderRadius: 4, background: C.slate100 }} />
              </div>
              {[70, 80, 80, 70, 60].map((w, j) => (
                <div key={j} style={{ width: w, height: 12, borderRadius: 4, background: C.slate100 }} />
              ))}
              <div style={{ width: 50, height: 22, borderRadius: 6, background: C.slate100 }} />
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div style={{ padding: 32, maxWidth: 1400, margin: "0 auto" }}>
      {/* Header */}
      <PageHeader
        title="Prospective RAF Management"
        subtitle="Forward-looking patient engagement — identify, prioritize, and act on revenue opportunities before they close"
        icon={<Target size={22} />}
        actions={
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <button
              onClick={exportWorklistCSV}
              aria-label="Export worklist as CSV"
              className="btn-press"
              style={{
                display: "flex", alignItems: "center", gap: 7,
                padding: "9px 18px", borderRadius: 9,
                border: `1px solid ${C.slate200}`, background: C.white,
                color: C.slate600, fontSize: 13, fontWeight: 600,
                cursor: "pointer",
              }}
            >
              <FileDown size={14} /> Export CSV
            </button>
            <button
              onClick={exportChaseList}
              className="btn-press"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 7,
                padding: "9px 18px",
                borderRadius: 9,
                border: "none",
                background: C.primary,
                color: C.white,
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              <Download size={14} /> Export Chase List
            </button>
            <button
              onClick={() => window.print()}
              className="no-print"
              aria-label="Print worklist"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 7,
                padding: "9px 18px",
                borderRadius: 9,
                border: `1px solid ${C.slate200}`,
                background: C.white,
                color: C.slate600,
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              <Printer size={14} /> Print Worklist
            </button>
          </div>
        }
      />

      {/* Stats Row */}
      <div className="animate-fade-in" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 16, marginBottom: 28 }}>
        <div className="animate-slide-up stagger-1 card-glow-rose">
          <StatCard
            label="Not Seen This Year"
            value={stats.notSeenThisYear.toLocaleString()}
            subtitle="patients requiring outreach"
            color={C.red600}
            icon={<Users size={18} />}
          />
        </div>
        <div className="animate-slide-up stagger-2 card-glow-amber">
          <StatCard
            label="Open Suspect Conditions"
            value={stats.totalSuspects.toLocaleString()}
            subtitle="across all patients"
            color={C.amber500}
            icon={<AlertTriangle size={18} />}
          />
        </div>
        <div className="animate-slide-up stagger-3 card-glow-emerald">
          <StatCard
            label="Revenue at Risk"
            value={fmtCurrencyCompact(stats.totalRevenue)}
            subtitle="estimated opportunity"
            color={C.emerald500}
            icon={<TrendingUp size={18} />}
            meta={revenueAtRiskMeta ?? undefined}
            labelTestId="revenue-at-risk-label"
            valueTestId="revenue-at-risk-value"
          />
        </div>
        <div className="animate-slide-up stagger-4 card-glow-blue">
          <StatCard
            label="AWV Opportunities"
            value={stats.awvOpportunities.toLocaleString()}
            subtitle="eligible patients"
            color={C.purple600}
            icon={<Calendar size={18} />}
          />
        </div>
        <div className="animate-slide-up stagger-5 card-glow-blue">
          <StatCard
            label="High Priority Patients"
            value={stats.highPriority.toLocaleString()}
            subtitle="requiring immediate action"
            color={C.primary}
            icon={<Star size={18} />}
          />
        </div>
      </div>

      {/* Priority Worklist */}
      <div className="premium-card premium-shadow animate-fade-in stagger-2" style={{ ...cardStyle, marginBottom: 28 }}>
        {/* Worklist Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexWrap: "wrap",
            gap: 12,
            padding: "16px 20px",
            borderBottom: `1px solid ${C.slate200}`,
            background: C.slate50,
            borderTop: `3px solid ${C.primary}`,
            borderRadius: "12px 12px 0 0",
          }}
        >
          <div>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: C.slate900 }}>
              Priority Worklist
            </h3>
            <p style={{ margin: "3px 0 0", fontSize: 12, color: C.subtleText }}>
              {filtered.length.toLocaleString()} patients ranked by RAF revenue opportunity
            </p>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            {/* Search */}
            <div style={{ position: "relative" }}>
              <Search
                size={14}
                style={{ position: "absolute", left: 9, top: "50%", transform: "translateY(-50%)", color: C.slate400 }}
              />
              <input
                type="text"
                placeholder="Search patient..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                aria-label="Search patients"
                style={{
                  ...selectStyle,
                  paddingLeft: 28,
                  width: 190,
                }}
              />
            </div>

            {/* Provider filter */}
            <select
              value={providerFilter}
              onChange={(e) => setProviderFilter(e.target.value)}
              style={selectStyle}
              aria-label="Filter by provider"
            >
              <option value="all">All Providers</option>
              {providers.map((pv) => (
                <option key={pv} value={pv}>{pv}</option>
              ))}
            </select>

            {/* Priority filter */}
            <select
              value={priorityFilter}
              onChange={(e) => setPriorityFilter(e.target.value as PriorityFilter)}
              style={selectStyle}
              aria-label="Filter by priority"
            >
              <option value="all">All Priorities</option>
              <option value="High">High Priority</option>
              <option value="Medium">Medium Priority</option>
              <option value="Low">Low Priority</option>
            </select>

            {/* Days since filter */}
            <select
              value={daysSinceFilter}
              onChange={(e) => setDaysSinceFilter(e.target.value as DaysSinceFilter)}
              style={selectStyle}
              aria-label="Filter by days since last visit"
            >
              <option value="all">Any Last Visit</option>
              <option value="30">Not seen 30+ days</option>
              <option value="90">Not seen 90+ days</option>
              <option value="180">Not seen 180+ days</option>
              <option value="365">Not seen 1+ year</option>
            </select>
          </div>
        </div>

        {/* Table */}
        {filtered.length === 0 ? (
          enrichedPatients.length === 0 ? (
            <EmptyState
              icon={<Users size={24} />}
              title="No upcoming visits this week"
              description="Check back tomorrow as new visits are scheduled, or add patients to your panel."
            />
          ) : (
            <EmptyState
              icon={<Search size={24} />}
              title="No patients match your filters"
              description="Try adjusting the search or filter criteria."
            />
          )
        ) : (
          <>
            <div style={{ overflowX: "auto", WebkitOverflowScrolling: "touch", maxWidth: "100%" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 900 }}>
                <thead>
                  <tr>
                    <th style={{ ...thStyle, width: 56 }}>Rank</th>
                    <th style={thStyle}>Patient</th>
                    <th style={thStyle}>Last Visit</th>
                    <th style={thStyle}>Current RAF</th>
                    <th style={thStyle}>Potential RAF</th>
                    <th style={thStyle}>RAF Gap</th>
                    <th style={thStyle}>Revenue Opp.</th>
                    <th style={thStyle}>Suspects</th>
                    <th style={thStyle}>Recapture</th>
                    <th style={thStyle}>Priority</th>
                    <th style={{ ...thStyle, textAlign: "right" as const }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {paged.map((patient, rowIdx) => {
                    const globalRank = page * PAGE_SIZE + rowIdx + 1;
                    const medal = rankMedal(globalRank);
                    const pLevel = patient.priority_level;
                    const pColor = priorityColor(pLevel);
                    const daysLabel =
                      patient.days_since_visit === 9999
                        ? "Never"
                        : patient.days_since_visit === 1
                        ? "1 day ago"
                        : `${patient.days_since_visit}d ago`;

                    return (
                      <tr
                        key={patient.pid}
                        style={{
                          transition: "background 0.15s, transform 0.15s",
                          backgroundColor: rowIdx % 2 === 0 ? C.white : C.slate50,
                        }}
                        onMouseEnter={(e) => { e.currentTarget.style.background = `${C.primary}08`; }}
                        onMouseLeave={(e) => { e.currentTarget.style.background = rowIdx % 2 === 0 ? C.white : C.slate50; }}
                      >
                        {/* Rank */}
                        <td style={{ ...tdStyle, textAlign: "center" as const }}>
                          {medal ? (
                            <span
                              style={{
                                display: "inline-flex",
                                alignItems: "center",
                                justifyContent: "center",
                                width: 26,
                                height: 26,
                                borderRadius: 8,
                                fontSize: 12,
                                fontWeight: 800,
                                background: medal.bg,
                                color: medal.color,
                              }}
                            >
                              {medal.label}
                            </span>
                          ) : (
                            <span style={{ fontSize: 12, color: C.slate400, fontWeight: 600 }}>{globalRank}</span>
                          )}
                        </td>

                        {/* Patient */}
                        <td style={tdStyle}>
                          <div
                            style={{ fontWeight: 600, color: C.primary, cursor: "pointer" }}
                            onClick={() => router.push(`/patients/${patient.pid}`)}
                          >
                            {patient.lname}, {patient.fname}
                          </div>
                          <div style={{ fontSize: 11, color: C.subtleText }}>PID #{patient.pid}</div>
                        </td>

                        {/* Last Visit */}
                        <td style={tdStyle}>
                          <div style={{ fontSize: 12, color: C.slate900 }}>
                            {patient.last_visit_date === null ? "Never seen" : fmtDate(patient.last_visit_date)}
                          </div>
                          <div
                            style={{
                              fontSize: 11,
                              fontWeight: 600,
                              color:
                                patient.days_since_visit > 365
                                  ? C.red600
                                  : patient.days_since_visit > 180
                                  ? C.amber500
                                  : C.emerald500,
                            }}
                          >
                            {daysLabel}
                          </div>
                        </td>

                        {/* Current RAF */}
                        <td style={tdStyle}>
                          <span
                            className="tabular-nums"
                            style={{
                              fontSize: 14,
                              fontWeight: 700,
                              color:
                                patient.raf_score >= 2
                                  ? C.red600
                                  : patient.raf_score >= 1
                                  ? C.amber500
                                  : patient.raf_score > 0
                                  ? C.emerald500
                                  : C.slate400,
                            }}
                          >
                            {patient.raf_score > 0 ? (patient.raf_score ?? 0).toFixed(3) : "\u2014"}
                          </span>
                        </td>

                        {/* Potential RAF */}
                        <td style={tdStyle}>
                          <span className="tabular-nums" style={{ fontSize: 14, fontWeight: 700, color: C.primary }}>
                            {patient.potential_raf > 0 ? (patient.potential_raf ?? 0).toFixed(3) : "\u2014"}
                          </span>
                        </td>

                        {/* RAF Gap */}
                        <td style={tdStyle}>
                          {patient.raf_gap > 0 ? (
                            <span
                              className="tabular-nums gradient-text"
                              style={{
                                fontSize: 13,
                                fontWeight: 700,
                              }}
                            >
                              +{(patient.raf_gap ?? 0).toFixed(3)}
                            </span>
                          ) : (
                            <span style={{ fontSize: 12, color: C.slate400 }}>{"\u2014"}</span>
                          )}
                        </td>

                        {/* Revenue Opportunity */}
                        <td style={tdStyle}>
                          <span className="tabular-nums" style={{ fontWeight: 700, color: patient.estimated_revenue_opportunity > 0 ? C.emerald500 : C.slate400 }}>
                            {patient.estimated_revenue_opportunity > 0
                              ? fmtCurrency(patient.estimated_revenue_opportunity)
                              : "\u2014"}
                          </span>
                        </td>

                        {/* Open Suspects */}
                        <td style={tdStyle}>
                          {patient.open_suspects_count > 0 ? (
                            <span
                              style={{
                                display: "inline-flex",
                                alignItems: "center",
                                padding: "3px 9px",
                                borderRadius: 999,
                                fontSize: 12,
                                fontWeight: 700,
                                color: C.amber500,
                                background: `${C.amber500}1A`,
                              }}
                            >
                              {patient.open_suspects_count}
                            </span>
                          ) : (
                            <span style={{ fontSize: 12, color: C.slate300 }}>0</span>
                          )}
                        </td>

                        {/* Recapture Gaps */}
                        <td style={tdStyle}>
                          {patient.recapture_gaps_count > 0 ? (
                            <span
                              style={{
                                display: "inline-flex",
                                alignItems: "center",
                                padding: "3px 9px",
                                borderRadius: 999,
                                fontSize: 12,
                                fontWeight: 700,
                                color: C.red600,
                                background: `${C.red600}0F`,
                              }}
                            >
                              {patient.recapture_gaps_count}
                            </span>
                          ) : (
                            <span style={{ fontSize: 12, color: C.slate300 }}>0</span>
                          )}
                        </td>

                        {/* Priority */}
                        <td style={tdStyle}>
                          <span
                            style={{
                              display: "inline-block",
                              padding: "3px 10px",
                              borderRadius: 999,
                              fontSize: 11,
                              fontWeight: 700,
                              color: pColor,
                              background: `${pColor}1A`,
                            }}
                          >
                            {pLevel}
                          </span>
                        </td>

                        {/* Actions */}
                        <td style={{ ...tdStyle, textAlign: "right" as const }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 5, justifyContent: "flex-end" }}>
                            <button
                              style={actionBtnStyle}
                              onClick={() => router.push(`/patients/${patient.pid}`)}
                              title="View patient profile"
                            >
                              <Eye size={11} /> Profile
                            </button>
                            <button
                              style={{ ...actionBtnStyle, color: C.primary, borderColor: `${C.primary}44` }}
                              onClick={() =>
                                setPreVisitPatient({
                                  pid: patient.pid,
                                  fname: patient.fname,
                                  lname: patient.lname,
                                  DOB: patient.DOB,
                                  sex: patient.sex,
                                  raf_score: patient.raf_score,
                                  potential_raf: patient.potential_raf,
                                  raf_gap: patient.raf_gap,
                                  open_suspects_count: patient.open_suspects_count,
                                  recapture_gaps_count: patient.recapture_gaps_count,
                                  estimated_revenue_opportunity: patient.estimated_revenue_opportunity,
                                  provider: patient.provider,
                                })
                              }
                              title="Generate pre-visit summary"
                            >
                              <FileText size={11} /> Pre-Visit
                            </button>
                            <button
                              style={{ ...actionBtnStyle, color: C.emerald500, borderColor: `${C.emerald500}44` }}
                              title="Schedule visit"
                            >
                              <CalendarPlus size={11} /> Schedule
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "12px 20px",
                borderTop: `1px solid ${C.slate200}`,
                background: C.slate50,
                fontSize: 13,
                color: C.subtleText,
              }}
            >
              <span>
                Showing{" "}
                <strong style={{ color: C.slate900 }}>{page * PAGE_SIZE + 1}</strong>–
                <strong style={{ color: C.slate900 }}>{Math.min((page + 1) * PAGE_SIZE, filtered.length)}</strong> of{" "}
                <strong style={{ color: C.slate900 }}>{filtered.length}</strong>
              </span>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <button
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    padding: "6px 10px",
                    borderRadius: 7,
                    border: `1px solid ${C.slate200}`,
                    background: C.white,
                    cursor: page === 0 ? "not-allowed" : "pointer",
                    opacity: page === 0 ? 0.4 : 1,
                  }}
                >
                  <ChevronLeft size={14} />
                </button>
                <span style={{ padding: "0 8px", fontWeight: 600, color: C.slate900 }}>
                  {page + 1} / {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                  disabled={page >= totalPages - 1}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    padding: "6px 10px",
                    borderRadius: 7,
                    border: `1px solid ${C.slate200}`,
                    background: C.white,
                    cursor: page >= totalPages - 1 ? "not-allowed" : "pointer",
                    opacity: page >= totalPages - 1 ? 0.4 : 1,
                  }}
                >
                  <ChevronRight size={14} />
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* AWV Tracker */}
      {awvList.length > 0 && (
        <div className="premium-card premium-shadow animate-fade-in stagger-3 hover-lift" style={{ ...cardStyle, marginBottom: 28 }}>
          <div
            style={{
              padding: "16px 20px",
              borderBottom: `1px solid ${C.slate200}`,
              borderTop: `3px solid ${C.purple600}`,
              borderRadius: "12px 12px 0 0",
              background: C.slate50,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <div>
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: C.slate900 }}>
                Annual Wellness Visit Tracker
              </h3>
              <p style={{ margin: "3px 0 0", fontSize: 12, color: C.subtleText }}>
                Medicare-eligible patients who have not had an AWV this year
              </p>
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "8px 14px",
                borderRadius: 8,
                background: `${C.purple600}0D`,
                border: `1px solid ${C.purple600}33`,
              }}
            >
              <Calendar size={14} style={{ color: C.purple600 }} />
              <span style={{ fontSize: 13, fontWeight: 700, color: C.purple600 }}>
                {stats.awvOpportunities} eligible
              </span>
              <span style={{ fontSize: 12, color: C.subtleText }}>
                &middot; est. {fmtCurrency(stats.awvOpportunities * AWV_REVENUE_SUBSEQUENT)}
              </span>
            </div>
          </div>
          <div style={{ overflowX: "auto", WebkitOverflowScrolling: "touch", maxWidth: "100%" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 600 }}>
              <thead>
                <tr>
                  <th style={thStyle}>Patient</th>
                  <th style={thStyle}>Age / Sex</th>
                  <th style={thStyle}>Provider</th>
                  <th style={thStyle}>Last Visit</th>
                  <th style={thStyle}>AWV Type</th>
                  <th style={thStyle}>Revenue</th>
                  <th style={thStyle}>Action</th>
                </tr>
              </thead>
              <tbody>
                {awvList.map((p, i) => (
                  <AwvRow
                    key={p.pid}
                    patient={p}
                    index={i}
                    scheduledAwv={scheduledAwv}
                    onMarkScheduled={(pid) => setScheduledAwv((s) => new Set([...s, pid]))}
                  />
                ))}
              </tbody>
            </table>
          </div>
          {stats.awvOpportunities > 10 && (
            <div
              style={{
                padding: "10px 20px",
                borderTop: `1px solid ${C.slate200}`,
                background: C.slate50,
                fontSize: 12,
                color: C.subtleText,
                textAlign: "center" as const,
              }}
            >
              Showing top 10 of {stats.awvOpportunities} eligible patients &mdash; export Chase List for full list
            </div>
          )}
        </div>
      )}

      {/* Chase List Export Banner */}
      <div
        className="premium-card hover-lift animate-fade-in stagger-4 gradient-border"
        style={{
          ...cardStyle,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 24,
          padding: "20px 24px",
          background: `linear-gradient(135deg, ${C.primary}08, ${C.primary}14)`,
          border: `1px solid ${C.primary}22`,
        }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", gap: 14 }}>
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: 12,
              background: `${C.primary}1A`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: C.primary,
              flexShrink: 0,
            }}
          >
            <Phone size={20} />
          </div>
          <div>
            <p style={{ margin: 0, fontSize: 14, fontWeight: 700, color: C.slate900 }}>
              Export Chase List for Outreach
            </p>
            <p style={{ margin: "5px 0 0", fontSize: 13, color: C.subtleText, maxWidth: 580, lineHeight: 1.5 }}>
              Download a prioritized CSV with patient contact info, last visit, suspect count, and a templated outreach call script. Ideal for care coordinators to run systematic patient recall campaigns.
            </p>
          </div>
        </div>
        <button
          onClick={exportChaseList}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "11px 22px",
            borderRadius: 9,
            border: "none",
            background: C.primary,
            color: C.white,
            fontSize: 14,
            fontWeight: 600,
            cursor: "pointer",
            flexShrink: 0,
          }}
        >
          <Download size={15} /> Export Chase List
        </button>
      </div>

      {/* Pre-Visit Summary Modal */}
      {preVisitPatient && (
        <PreVisitSummaryModal
          patient={preVisitPatient}
          onClose={() => setPreVisitPatient(null)}
        />
      )}

      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
        @media print {
          aside, nav, button { display: none !important; }
        }
      `}</style>
    </div>
  );
}
