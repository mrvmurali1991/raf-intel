"use client";

/**
 * PatientV28ImpactPanel
 * ---------------------
 * Per-patient V24 → V28 transition delta panel.  Backed by
 * GET /api/v28-impact/patient/{pid}?year=YYYY.
 *
 * Surfaces the patient's V24 vs V28 payment RAF, the resulting $ delta,
 * the HCCs that were dropped from V28 (the erosion driver), and the HCCs
 * newly recognized in V28 (rarely positive — typically only the kidney
 * disease split and a handful of others).
 */

import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { Loader2, AlertTriangle, TrendingDown, TrendingUp } from "lucide-react";
import { formatCurrency } from "@/lib/format";

type V28PatientImpact = {
  patient_id: number;
  measurement_year: number;
  v24_raf: number;
  v28_raf: number;
  raf_delta: number;
  raf_delta_pct: number;
  revenue_delta_annual: number;
  dropped_hccs: string[];
  gained_hccs: string[];
  common_hccs: string[];
  icd_count: number;
  model_segment: string | null;
};

function fmtMoney(n: number): string {
  return formatCurrency(Math.round(n), { showSign: n > 0 });
}

function fmtRAF(n: number): string {
  return n.toFixed(3);
}

export function PatientV28ImpactPanel({
  pid,
  year,
}: {
  pid: string;
  year: number;
}) {
  const { data, isLoading, error } = useQuery<V28PatientImpact>({
    queryKey: ["v28-impact", "patient", pid, year],
    queryFn: async () => {
      const res = await api.get<V28PatientImpact>(
        `/api/v28-impact/patient/${pid}`,
        { params: { year } },
      );
      return res.data;
    },
    staleTime: 60_000,
    retry: 1,
  });

  if (isLoading) {
    return (
      <div className="text-muted-foreground" style={{ display: "flex", alignItems: "center", gap: 8, padding: 24 }}>
        <Loader2 size={16} className="animate-spin" />
        Computing V24 vs V28 delta…
      </div>
    );
  }
  if (error || !data) {
    return (
      <div
        className="bg-red-50 border border-red-300 text-red-800 dark:bg-red-950 dark:border-red-700 dark:text-red-300"
      style={{
          padding: 16,
          borderRadius: 8,
          display: "flex",
          gap: 8,
          alignItems: "center",
        }}
      >
        <AlertTriangle size={16} />
        Could not load V28 impact for this patient.
      </div>
    );
  }

  const negative = data.raf_delta < 0;
  const accent = negative ? "#dc2626" : data.raf_delta > 0 ? "#059669" : "#475569";
  const TrendIcon = negative ? TrendingDown : TrendingUp;

  return (
    <div style={{ display: "grid", gap: 16 }}>
      {/* Header summary */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, minmax(140px, 1fr))",
          gap: 12,
        }}
      >
        <Stat label="V24 RAF" value={fmtRAF(data.v24_raf)} />
        <Stat label="V28 RAF" value={fmtRAF(data.v28_raf)} />
        <Stat
          label="Δ RAF (V28 − V24)"
          value={`${data.raf_delta > 0 ? "+" : ""}${fmtRAF(data.raf_delta)}`}
          accent={accent}
          icon={<TrendIcon size={14} />}
        />
        <Stat
          label="Annual Δ Revenue"
          value={fmtMoney(data.revenue_delta_annual)}
          subtitle={`${data.raf_delta_pct > 0 ? "+" : ""}${data.raf_delta_pct.toFixed(1)}% RAF`}
          accent={accent}
        />
      </div>

      {/* Dropped HCCs */}
      <Section title={`HCCs dropped in V28 (${data.dropped_hccs.length})`} subtitle="These HCC categories existed in V24 but have been removed or restructured in V28.">
        {data.dropped_hccs.length === 0 ? (
          <Empty>No HCCs dropped — this patient's coded conditions all carry over to V28.</Empty>
        ) : (
          <ChipRow chips={data.dropped_hccs} color="#dc2626" bg="#fef2f2" />
        )}
      </Section>

      {/* Gained HCCs */}
      <Section title={`HCCs gained in V28 (${data.gained_hccs.length})`} subtitle="These HCC categories are newly recognized in V28 (e.g. CKD splits, restructured categories).">
        {data.gained_hccs.length === 0 ? (
          <Empty>No HCCs gained from V28 restructuring.</Empty>
        ) : (
          <ChipRow chips={data.gained_hccs} color="#059669" bg="#ecfdf5" />
        )}
      </Section>

      {/* Common */}
      <Section title={`HCCs present in both models (${data.common_hccs.length})`} subtitle="Stable across the transition.">
        {data.common_hccs.length === 0 ? (
          <Empty>No HCCs in common.</Empty>
        ) : (
          <ChipRow chips={data.common_hccs} color="#1e40af" bg="#eff6ff" />
        )}
      </Section>

      <div className="text-xs text-muted-foreground" style={{ lineHeight: 1.4 }}>
        Disclaimer: estimates produced by hccinfhir (third-party CMS-HCC
        implementation). Not validated by CMS — cross-check against the
        official CMS HCC Software before contract / payment use.
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  subtitle,
  accent,
  icon,
}: {
  label: string;
  value: string;
  subtitle?: string;
  accent?: string;
  icon?: React.ReactNode;
}) {
  return (
    <div
      className="bg-card border border-border"
      style={{
        padding: 12,
        borderRadius: 8,
        display: "flex",
        flexDirection: "column",
        gap: 4,
      }}
    >
      <div className="text-muted-foreground" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: 0.4, display: "flex", alignItems: "center", gap: 4 }}>
        {icon}
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: accent ?? "var(--foreground)" }}>{value}</div>
      {subtitle && (
        <div className="text-muted-foreground" style={{ fontSize: 11 }}>{subtitle}</div>
      )}
    </div>
  );
}

function Section({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="bg-card border border-border"
      style={{
        padding: 14,
        borderRadius: 8,
      }}
    >
      <div className="text-sm font-bold text-foreground">{title}</div>
      {subtitle && (
        <div className="text-xs text-muted-foreground" style={{ marginTop: 2, marginBottom: 8 }}>
          {subtitle}
        </div>
      )}
      <div>{children}</div>
    </div>
  );
}

function ChipRow({ chips, color, bg }: { chips: string[]; color: string; bg: string }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
      {chips.map((c) => (
        <span
          key={c}
          style={{
            padding: "3px 8px",
            borderRadius: 999,
            fontSize: 11,
            fontWeight: 600,
            color,
            background: bg,
            border: `1px solid ${color}33`,
          }}
        >
          HCC {c}
        </span>
      ))}
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="text-xs text-muted-foreground italic">{children}</div>;
}

export default PatientV28ImpactPanel;
