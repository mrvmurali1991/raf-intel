"use client";

/**
 * Side card surfaced when a row in ``ProviderRecaptureLeaderboard`` is clicked.
 *
 *   - Provider's recapture rate vs specialty median (delta arrow)
 *   - Provider's rate vs network median
 *   - 3-year trend mini-sparkline
 *   - Top 3 unrecaptured HCC conditions
 */

import React, { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowDownRight, ArrowUpRight, Minus, X } from "lucide-react";
import {
  getProviderRecapturePercentile,
  getProviderRecaptureTrend,
} from "@/lib/api";

interface Props {
  providerId: number;
  providerName?: string;
  year: number;
  onClose?: () => void;
}

const colors = {
  primary: "#2563EB",
  slate900: "#0F172A",
  slate700: "#334155",
  slate600: "#475569",
  slate400: "#94A3B8",
  slate200: "#E2E8F0",
  slate100: "#F1F5F9",
  slate50: "#F8FAFC",
  white: "#FFFFFF",
  red600: "#DC2626",
  amber500: "#F59E0B",
  emerald500: "#10B981",
};

function pct(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

function deltaArrow(delta: number | null | undefined) {
  if (delta == null || Math.abs(delta) < 0.0005) {
    return { icon: <Minus size={14} />, color: colors.slate400, label: "0.0%" };
  }
  if (delta > 0) {
    return {
      icon: <ArrowUpRight size={14} />,
      color: colors.emerald500,
      label: `+${(delta * 100).toFixed(1)} pp`,
    };
  }
  return {
    icon: <ArrowDownRight size={14} />,
    color: colors.red600,
    label: `${(delta * 100).toFixed(1)} pp`,
  };
}

function Sparkline({ values, width = 160, height = 36 }: { values: number[]; width?: number; height?: number }) {
  if (values.length === 0) return null;
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const range = max - min || 1;
  const stepX = values.length > 1 ? width / (values.length - 1) : 0;
  const points = values
    .map((v, i) => `${i * stepX},${height - ((v - min) / range) * height}`)
    .join(" ");
  const last = values[values.length - 1];
  const lastY = height - ((last - min) / range) * height;
  const lastX = (values.length - 1) * stepX;
  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      <polyline
        fill="none"
        stroke={colors.primary}
        strokeWidth={2}
        points={points}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={lastX} cy={lastY} r={3} fill={colors.primary} />
    </svg>
  );
}

export default function ProviderRecaptureCard({
  providerId,
  providerName,
  year,
  onClose,
}: Props) {
  const percentileQ = useQuery({
    queryKey: ["recapture-provider-percentile", providerId, year],
    queryFn: () => getProviderRecapturePercentile(providerId, year),
  });
  const trendQ = useQuery({
    queryKey: ["recapture-provider-trend", providerId],
    queryFn: () => getProviderRecaptureTrend(providerId, 3),
  });

  const p = percentileQ.data;
  const t = trendQ.data;

  const specialtyDelta = useMemo(() => {
    if (!p || p.specialty_median == null) return null;
    return p.recapture_rate - p.specialty_median;
  }, [p]);

  const networkDelta = useMemo(() => {
    if (!p) return null;
    return p.recapture_rate - p.network_median;
  }, [p]);

  return (
    <div
      data-testid="provider-recapture-card"
      style={{
        position: "relative",
        padding: 20,
        borderRadius: 12,
        background: colors.white,
        border: `1px solid ${colors.slate200}`,
        boxShadow: "0 4px 14px rgba(15,23,42,0.08)",
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 600, color: colors.slate400, textTransform: "uppercase", letterSpacing: "0.06em" }}>
            Recapture detail
          </div>
          <div style={{ fontSize: 16, fontWeight: 700, color: colors.slate900, marginTop: 2 }}>
            {p?.provider_name || providerName || `Provider #${providerId}`}
          </div>
          <div style={{ fontSize: 12, color: colors.slate600 }}>
            {p?.specialty ?? "—"} · {year}
          </div>
        </div>
        {onClose ? (
          <button
            onClick={onClose}
            aria-label="Close"
            style={{
              padding: 6,
              borderRadius: 8,
              border: `1px solid ${colors.slate200}`,
              background: colors.white,
              cursor: "pointer",
              color: colors.slate600,
            }}
          >
            <X size={14} />
          </button>
        ) : null}
      </div>

      {/* Headline rate */}
      <div
        style={{
          marginTop: 16,
          padding: 14,
          borderRadius: 10,
          background: colors.slate50,
          border: `1px solid ${colors.slate100}`,
        }}
      >
        <div style={{ fontSize: 11, color: colors.slate600, fontWeight: 600 }}>RECAPTURE RATE</div>
        <div
          style={{
            fontSize: 28,
            fontWeight: 800,
            color: colors.slate900,
            fontVariantNumeric: "tabular-nums",
            marginTop: 2,
          }}
        >
          {pct(p?.recapture_rate)}
        </div>
        {p?.percentile_in_specialty != null ? (
          <div style={{ fontSize: 12, color: colors.slate600, marginTop: 2 }}>
            <strong style={{ color: colors.slate900 }}>{p.percentile_in_specialty}%</strong>{" "}
            percentile in specialty (n={p.ranks_among_n})
          </div>
        ) : (
          <div style={{ fontSize: 12, color: colors.amber500, marginTop: 2 }}>
            Insufficient peers in specialty (n={p?.ranks_among_n ?? 0})
          </div>
        )}
      </div>

      {/* vs specialty / network */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 12 }}>
        <CompareTile
          label="vs Specialty median"
          peerRate={p?.specialty_median ?? null}
          delta={specialtyDelta}
        />
        <CompareTile
          label="vs Network median"
          peerRate={p?.network_median ?? null}
          delta={networkDelta}
        />
      </div>

      {/* Sparkline */}
      <div style={{ marginTop: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: colors.slate600, textTransform: "uppercase", letterSpacing: "0.06em" }}>
            3-year trend
          </span>
          {t?.years.length ? (
            <span style={{ fontSize: 11, color: colors.slate400 }}>
              {t.years[0]} → {t.years[t.years.length - 1]}
            </span>
          ) : null}
        </div>
        {t?.rates.length ? (
          <Sparkline values={t.rates} />
        ) : (
          <div style={{ fontSize: 12, color: colors.slate400 }}>No trend data.</div>
        )}
        {t?.rates.length ? (
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4, fontSize: 11, color: colors.slate600 }}>
            {t.years.map((y, i) => (
              <span key={y} className="tabular-nums">
                {y} <strong style={{ color: colors.slate900 }}>{(t.rates[i] * 100).toFixed(0)}%</strong>
              </span>
            ))}
          </div>
        ) : null}
      </div>

      {/* Top unrecaptured HCCs */}
      <div style={{ marginTop: 16 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: colors.slate600, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 6 }}>
          Top unrecaptured HCCs
        </div>
        {p?.top_unrecaptured_hccs?.length ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {p.top_unrecaptured_hccs.map((h) => (
              <div
                key={h.hcc_code}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "6px 10px",
                  borderRadius: 8,
                  background: colors.slate50,
                  border: `1px solid ${colors.slate100}`,
                  fontSize: 12,
                }}
              >
                <span style={{ fontWeight: 700, color: colors.slate900 }}>HCC {h.hcc_code}</span>
                <span style={{ color: colors.slate600 }}>
                  {h.count} pt{h.count === 1 ? "" : "s"} ·{" "}
                  <span style={{ color: colors.red600, fontWeight: 600 }}>
                    ${Math.round(h["$_at_risk"]).toLocaleString("en-US")}
                  </span>
                </span>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ fontSize: 12, color: colors.slate400 }}>No open HCCs to recapture.</div>
        )}
      </div>
    </div>
  );
}

function CompareTile({
  label,
  peerRate,
  delta,
}: {
  label: string;
  peerRate: number | null;
  delta: number | null;
}) {
  const arrow = deltaArrow(delta);
  return (
    <div
      style={{
        padding: 12,
        borderRadius: 10,
        background: colors.white,
        border: `1px solid ${colors.slate200}`,
      }}
    >
      <div style={{ fontSize: 11, color: colors.slate600, fontWeight: 600 }}>{label}</div>
      <div
        style={{
          fontSize: 16,
          fontWeight: 700,
          color: colors.slate900,
          marginTop: 2,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {pct(peerRate)}
      </div>
      <div
        style={{
          marginTop: 4,
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          padding: "2px 8px",
          borderRadius: 999,
          background: `${arrow.color}1A`,
          color: arrow.color,
          fontSize: 11,
          fontWeight: 700,
        }}
      >
        {arrow.icon} {arrow.label}
      </div>
    </div>
  );
}
