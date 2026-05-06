"use client";

/**
 * /worklist — "Today's priorities" page.
 *
 * The single screen a provider opens on Monday morning.  Lists patients
 * sorted by ``priority_score`` desc with their open recapture gaps,
 * suspect conditions, and estimated revenue at risk.
 *
 * Mobile-first: collapses to a single column on narrow viewports.  Each
 * patient row is a self-contained card so it survives tablet / phone
 * layouts in an exam-room context.
 *
 * Inline fetching against /api/worklist/provider/{id} — no api.ts
 * dependency so this can land alongside other api.ts edits.
 */

import { useMemo } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronRight, FileText, Activity, Stethoscope } from "lucide-react";
import { useAuth } from "@/contexts/auth-context";
import { PageHeader } from "@/components/healthcare-ui";
import { tokens } from "@/styles/tokens";
import api from "@/lib/api";

interface WorklistGap {
  hcc_code: string;
  icd10_codes?: string[];
  prior_year?: number;
  revenue_impact?: number;
}

interface WorklistSuspect {
  hcc_code: string;
  source?: string;
  confidence?: number;
}

interface WorklistItem {
  patient_id: number;
  patient_name: string;
  dob?: string | null;
  last_visit_date?: string | null;
  open_recapture_gaps: WorklistGap[];
  suspect_conditions: WorklistSuspect[];
  estimated_raf_impact: number;
  estimated_revenue_at_risk: number;
  priority_score: number;
}

interface WorklistResponse {
  provider_id: number;
  measurement_year: number;
  total: number;
  items: WorklistItem[];
}

function fmtCurrency(n: number): string {
  if (Math.abs(n) >= 1000) return `$${(n / 1000).toFixed(1)}K`;
  return `$${Math.round(n).toLocaleString()}`;
}

function priorityBand(score: number): { label: string; color: string; bg: string } {
  if (score >= 70) return { label: "High", color: tokens.riskHigh, bg: tokens.riskHighSoft };
  if (score >= 40) return { label: "Medium", color: tokens.warningStrong, bg: tokens.warningSoft };
  return { label: "Low", color: tokens.success, bg: tokens.successSoft };
}

export default function WorklistPage() {
  const { user, isLoading: authLoading } = useAuth();
  const measurementYear = new Date().getFullYear();
  const providerId = user?.id ? Number(user.id) : null;

  const { data, isLoading, isError, error, refetch } = useQuery<WorklistResponse>({
    queryKey: ["provider-worklist", providerId, measurementYear],
    queryFn: async () => {
      const { data } = await api.get<WorklistResponse>(
        `/api/worklist/provider/${providerId}`,
        { params: { measurement_year: measurementYear } },
      );
      return data;
    },
    enabled: providerId != null,
    staleTime: 60_000,
  });

  const summary = useMemo(() => {
    if (!data?.items) return { patients: 0, gaps: 0, revenue: 0 };
    return {
      patients: data.items.length,
      gaps: data.items.reduce((sum, p) => sum + (p.open_recapture_gaps?.length ?? 0), 0),
      revenue: data.items.reduce((sum, p) => sum + (p.estimated_revenue_at_risk ?? 0), 0),
    };
  }, [data]);

  if (authLoading || (providerId != null && isLoading)) {
    return (
      <div style={{ padding: 24 }}>
        <PageHeader title="Today's worklist" subtitle="Loading prioritized patients…" />
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 16, marginTop: 16 }}>
          {[1, 2, 3].map((i) => (
            <div key={i} className="premium-card shimmer" style={{ height: 140, borderRadius: 12 }} />
          ))}
        </div>
      </div>
    );
  }

  if (providerId == null) {
    return (
      <div style={{ padding: 24 }}>
        <PageHeader title="Today's worklist" />
        <div style={{ marginTop: 16, padding: 16, borderRadius: 10, background: tokens.warningSoft, border: `1px solid ${tokens.warningBorder}`, color: tokens.warningText, fontSize: 14 }}>
          Sign in to view your worklist.
        </div>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div style={{ padding: 24 }}>
        <PageHeader title="Today's worklist" />
        <div role="alert" style={{ marginTop: 16, padding: 14, borderRadius: 10, background: tokens.dangerSoft, border: `1px solid ${tokens.dangerBorder}`, color: tokens.danger, display: "flex", alignItems: "center", gap: 10, fontSize: 14 }}>
          <AlertTriangle size={18} />
          <span style={{ flex: 1 }}>
            Couldn't load your worklist{error instanceof Error ? `: ${error.message}` : ""}
          </span>
          <button
            type="button"
            onClick={() => refetch()}
            style={{
              padding: "6px 12px",
              borderRadius: 8,
              border: `1px solid ${tokens.dangerBorder}`,
              background: tokens.white,
              color: tokens.danger,
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (data.items.length === 0) {
    return (
      <div style={{ padding: 24 }}>
        <PageHeader title="Today's worklist" subtitle={`Measurement year ${measurementYear}`} />
        <div
          style={{
            marginTop: 24,
            padding: "32px 20px",
            borderRadius: 12,
            background: tokens.successSoft,
            border: `1px solid ${tokens.success}`,
            color: tokens.successDark,
            textAlign: "center",
          }}
        >
          <Stethoscope size={28} style={{ marginBottom: 8 }} />
          <h2 style={{ margin: "0 0 6px", fontSize: 18, fontWeight: 700 }}>You're caught up</h2>
          <p style={{ margin: 0, fontSize: 14, lineHeight: 1.5 }}>
            No prioritized patients to see this week.  When new gaps or
            suspect conditions surface, they'll appear here.
          </p>
          <div style={{ marginTop: 16, display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
            <Link
              href="/patients"
              style={{
                padding: "8px 16px",
                borderRadius: 8,
                background: tokens.white,
                color: tokens.successDark,
                border: `1px solid ${tokens.success}`,
                fontSize: 13,
                fontWeight: 600,
                textDecoration: "none",
              }}
            >
              View full panel
            </Link>
            <Link
              href="/recapture"
              style={{
                padding: "8px 16px",
                borderRadius: 8,
                background: tokens.successDark,
                color: tokens.white,
                fontSize: 13,
                fontWeight: 600,
                textDecoration: "none",
              }}
            >
              Open recapture report
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{ padding: 24, maxWidth: 1280, margin: "0 auto" }}>
      <PageHeader
        title="Today's worklist"
        subtitle={`${summary.patients} patient${summary.patients === 1 ? "" : "s"} prioritized for ${measurementYear}`}
      />

      {/* Summary strip — collapses to 1 column on phones, 3 on tablets+ */}
      <div
        style={{
          marginTop: 16,
          marginBottom: 24,
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: 12,
        }}
      >
        <SummaryTile label="Patients to see" value={summary.patients} icon={<Stethoscope size={18} />} color={tokens.primary} />
        <SummaryTile label="Open gaps" value={summary.gaps} icon={<FileText size={18} />} color={tokens.riskHigh} />
        <SummaryTile label="Revenue at risk" value={fmtCurrency(summary.revenue)} icon={<Activity size={18} />} color={tokens.warningStrong} />
      </div>

      {/* Patient cards — auto-fit grid; collapses to 1 column on phones */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          gap: 16,
        }}
      >
        {data.items.map((item) => (
          <PatientCard key={item.patient_id} item={item} />
        ))}
      </div>
    </div>
  );
}

function SummaryTile({
  label,
  value,
  icon,
  color,
}: {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  color: string;
}) {
  return (
    <div
      style={{
        padding: "14px 16px",
        borderRadius: 12,
        background: tokens.white,
        border: `1px solid ${tokens.slate200}`,
        display: "flex",
        alignItems: "center",
        gap: 12,
      }}
    >
      <div
        style={{
          width: 36,
          height: 36,
          borderRadius: 10,
          background: `${color}1A`,
          color,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
        }}
      >
        {icon}
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: tokens.slate500, textTransform: "uppercase", letterSpacing: "0.05em" }}>
          {label}
        </div>
        <div className="tabular-nums" style={{ fontSize: 22, fontWeight: 700, color: tokens.slate900, lineHeight: 1.1 }}>
          {value}
        </div>
      </div>
    </div>
  );
}

function PatientCard({ item }: { item: WorklistItem }) {
  const band = priorityBand(item.priority_score);
  return (
    <Link
      href={`/patients/${item.patient_id}`}
      style={{
        display: "block",
        padding: 16,
        borderRadius: 12,
        background: tokens.white,
        border: `1px solid ${tokens.slate200}`,
        textDecoration: "none",
        color: "inherit",
        transition: "box-shadow 120ms ease",
      }}
      className="hover-lift"
    >
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12, marginBottom: 10 }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div
            style={{
              fontSize: 15,
              fontWeight: 700,
              color: tokens.slate900,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {item.patient_name}
          </div>
          <div style={{ fontSize: 12, color: tokens.slate500, marginTop: 2 }}>
            {item.dob ? `DOB ${item.dob}` : "DOB unknown"}
            {item.last_visit_date ? ` · last visit ${item.last_visit_date}` : ""}
          </div>
        </div>
        <span
          style={{
            flexShrink: 0,
            padding: "3px 10px",
            borderRadius: 999,
            background: band.bg,
            color: band.color,
            fontSize: 11,
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.04em",
          }}
        >
          {band.label}
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
        <Stat
          label="Open gaps"
          value={item.open_recapture_gaps?.length ?? 0}
          tone={(item.open_recapture_gaps?.length ?? 0) > 0 ? tokens.riskHigh : tokens.slate500}
        />
        <Stat
          label="Revenue at risk"
          value={fmtCurrency(item.estimated_revenue_at_risk ?? 0)}
          tone={tokens.slate900}
        />
      </div>

      {item.open_recapture_gaps && item.open_recapture_gaps.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
          {item.open_recapture_gaps.slice(0, 4).map((g, i) => (
            <span
              key={`${g.hcc_code}-${i}`}
              style={{
                padding: "2px 8px",
                borderRadius: 999,
                background: tokens.dangerSoft,
                color: tokens.danger,
                fontSize: 11,
                fontWeight: 600,
              }}
            >
              HCC {g.hcc_code}
            </span>
          ))}
          {item.open_recapture_gaps.length > 4 && (
            <span style={{ fontSize: 11, color: tokens.slate500, alignSelf: "center" }}>
              +{item.open_recapture_gaps.length - 4} more
            </span>
          )}
        </div>
      )}

      <div
        style={{
          marginTop: 8,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          fontSize: 12,
          color: tokens.primary,
          fontWeight: 600,
        }}
      >
        <span>Priority score · {item.priority_score}</span>
        <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
          Open chart <ChevronRight size={14} />
        </span>
      </div>
    </Link>
  );
}

function Stat({ label, value, tone }: { label: string; value: string | number; tone: string }) {
  return (
    <div
      style={{
        padding: "8px 10px",
        borderRadius: 8,
        background: tokens.slate50,
        border: `1px solid ${tokens.slate100}`,
      }}
    >
      <div style={{ fontSize: 10, fontWeight: 600, color: tokens.slate500, textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {label}
      </div>
      <div className="tabular-nums" style={{ fontSize: 16, fontWeight: 700, color: tone }}>
        {value}
      </div>
    </div>
  );
}
