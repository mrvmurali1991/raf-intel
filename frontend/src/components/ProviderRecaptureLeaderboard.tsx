"use client";

/**
 * Provider Peer Benchmarking — Recapture Rate Leaderboard.
 *
 * Sortable table showing each provider's recapture performance with cohort
 * context.  Top-quartile rows are tinted emerald, bottom-quartile amber so
 * peer comparison drives behavioral change.
 *
 * Click a row to open ``ProviderRecaptureCard`` (wired by the parent page).
 */

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpDown, TrendingUp } from "lucide-react";
import {
  getProviderRecaptureLeaderboard,
  type ProviderRecaptureRow,
} from "@/lib/api";

type SortKey =
  | "provider_name"
  | "specialty"
  | "panel_size"
  | "recapture_rate"
  | "$_recaptured"
  | "$_at_risk";

interface Props {
  year: number;
  onSelectProvider?: (provider: ProviderRecaptureRow) => void;
  selectedProviderId?: number | null;
}

const colors = {
  primary: "#2563EB",
  slate900: "#0F172A",
  slate600: "#475569",
  slate400: "#64748B",
  slate200: "#E2E8F0",
  slate100: "#F1F5F9",
  slate50: "#F8FAFC",
  white: "#FFFFFF",
  red600: "#DC2626",
  amber500: "#F59E0B",
  amber50: "#FFFBEB",
  emerald500: "#10B981",
  emerald50: "#ECFDF5",
};

function formatCurrency(n: number): string {
  return "$" + Math.round(n).toLocaleString("en-US");
}

function formatRatePct(rate: number): string {
  return `${(rate * 100).toFixed(1)}%`;
}

function rateChipColor(rate: number, q1: number, q3: number): { bg: string; fg: string } {
  if (rate >= q3) return { bg: "#D1FAE5", fg: "#065F46" };  // emerald
  if (rate <= q1) return { bg: "#FEE2E2", fg: "#991B1B" };  // red
  return { bg: "#FEF3C7", fg: "#92400E" };                   // amber
}

function quartileBand(rate: number, q1: number, q3: number): "top" | "bottom" | "middle" {
  if (rate >= q3 && q3 > 0) return "top";
  if (rate <= q1) return "bottom";
  return "middle";
}

export default function ProviderRecaptureLeaderboard({
  year,
  onSelectProvider,
  selectedProviderId,
}: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("recapture_rate");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["recapture-provider-leaderboard", year],
    queryFn: () => getProviderRecaptureLeaderboard(year),
  });

  const sorted = useMemo(() => {
    if (!data?.providers) return [];
    const rows = [...data.providers];
    rows.sort((a, b) => {
      const av = (a as unknown as Record<string, number | string | null>)[sortKey];
      const bv = (b as unknown as Record<string, number | string | null>)[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "number" && typeof bv === "number") {
        return sortDir === "asc" ? av - bv : bv - av;
      }
      return sortDir === "asc"
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av));
    });
    return rows;
  }, [data, sortKey, sortDir]);

  const network = data?.network;

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "provider_name" || key === "specialty" ? "asc" : "desc");
    }
  }

  const thStyle: React.CSSProperties = {
    padding: "12px 14px",
    fontSize: 11,
    fontWeight: 600,
    textTransform: "uppercase",
    letterSpacing: "0.06em",
    color: colors.slate600,
    textAlign: "left",
    borderBottom: `2px solid ${colors.slate200}`,
    whiteSpace: "nowrap",
    background: colors.slate50,
    cursor: "pointer",
    userSelect: "none",
  };
  const tdStyle: React.CSSProperties = {
    padding: "12px 14px",
    fontSize: 13,
    color: colors.slate900,
    borderBottom: `1px solid ${colors.slate100}`,
  };

  if (isLoading) {
    return (
      <div
        style={{
          padding: 24,
          borderRadius: 10,
          background: colors.white,
          border: `1px solid ${colors.slate200}`,
        }}
      >
        <div
          style={{
            height: 18,
            width: 240,
            borderRadius: 6,
            background: colors.slate100,
            marginBottom: 16,
          }}
        />
        {[1, 2, 3, 4, 5].map((i) => (
          <div
            key={i}
            style={{
              height: 40,
              borderRadius: 6,
              background: colors.slate50,
              marginBottom: 6,
            }}
          />
        ))}
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div
        style={{
          padding: 16,
          borderRadius: 10,
          background: "#FEF2F2",
          border: "1px solid #FECACA",
          color: "#B91C1C",
          fontSize: 13,
        }}
      >
        Failed to load provider recapture leaderboard.
      </div>
    );
  }

  return (
    <div
      data-testid="provider-recapture-leaderboard"
      style={{
        padding: 24,
        borderRadius: 10,
        background: colors.white,
        border: `1px solid ${colors.slate200}`,
        boxShadow: "0 1px 3px rgba(15,23,42,0.04)",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 16,
          flexWrap: "wrap",
          gap: 8,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <TrendingUp size={18} color={colors.primary} />
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: colors.slate900 }}>
            Provider Recapture Leaderboard
          </h3>
          <span
            style={{
              fontSize: 11,
              padding: "2px 8px",
              borderRadius: 999,
              background: colors.slate100,
              color: colors.slate600,
              fontWeight: 600,
            }}
          >
            {year}
          </span>
        </div>
        {network && network.n > 0 ? (
          <span style={{ fontSize: 12, color: colors.slate600 }}>
            Network median{" "}
            <strong style={{ color: colors.slate900 }}>{formatRatePct(network.median_rate)}</strong>{" "}
            · top quartile ≥{" "}
            <strong style={{ color: colors.emerald500 }}>{formatRatePct(network.q3_rate)}</strong>
          </span>
        ) : null}
      </div>

      {sorted.length === 0 ? (
        <div
          style={{
            padding: 24,
            textAlign: "center",
            color: colors.slate600,
            fontSize: 13,
          }}
        >
          No providers found.
        </div>
      ) : (
        <div
          style={{
            overflowX: "auto",
            borderRadius: 10,
            border: `1px solid ${colors.slate200}`,
          }}
        >
          <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 760 }}>
            <thead>
              <tr>
                <Th label="Provider" sortKey="provider_name" current={sortKey} dir={sortDir} onClick={toggleSort} thStyle={thStyle} />
                <Th label="Specialty" sortKey="specialty" current={sortKey} dir={sortDir} onClick={toggleSort} thStyle={thStyle} />
                <Th label="Panel" sortKey="panel_size" current={sortKey} dir={sortDir} onClick={toggleSort} thStyle={thStyle} />
                <Th label="Recapture %" sortKey="recapture_rate" current={sortKey} dir={sortDir} onClick={toggleSort} thStyle={thStyle} />
                <Th label="$ Recaptured" sortKey="$_recaptured" current={sortKey} dir={sortDir} onClick={toggleSort} thStyle={thStyle} />
                <Th label="$ At Risk" sortKey="$_at_risk" current={sortKey} dir={sortDir} onClick={toggleSort} thStyle={thStyle} />
                <th style={thStyle}>Quartile</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => {
                const cohort = r.specialty ? data.specialty_cohorts[r.specialty] : undefined;
                const q1 = cohort?.q1_rate ?? network?.q1_rate ?? 0;
                const q3 = cohort?.q3_rate ?? network?.q3_rate ?? 0;
                const band = quartileBand(r.recapture_rate, q1, q3);
                const chip = rateChipColor(r.recapture_rate, q1, q3);
                const rowBg =
                  band === "top"
                    ? colors.emerald50
                    : band === "bottom"
                      ? colors.amber50
                      : colors.white;
                const isSelected = selectedProviderId === r.provider_id;
                return (
                  <tr
                    key={r.provider_id}
                    onClick={() => onSelectProvider?.(r)}
                    style={{
                      cursor: "pointer",
                      background: isSelected ? "#DBEAFE" : rowBg,
                      borderLeft: `3px solid ${
                        band === "top"
                          ? colors.emerald500
                          : band === "bottom"
                            ? colors.amber500
                            : "transparent"
                      }`,
                      transition: "background 0.15s ease",
                    }}
                    onMouseEnter={(e) => {
                      if (!isSelected) e.currentTarget.style.background = colors.slate50;
                    }}
                    onMouseLeave={(e) => {
                      if (!isSelected) e.currentTarget.style.background = rowBg;
                    }}
                  >
                    <td style={{ ...tdStyle, fontWeight: 600, color: colors.primary }}>
                      {r.provider_name || "—"}
                    </td>
                    <td style={tdStyle}>{r.specialty || "—"}</td>
                    <td className="tabular-nums" style={tdStyle}>{r.panel_size}</td>
                    <td style={tdStyle}>
                      <span
                        style={{
                          display: "inline-block",
                          padding: "3px 10px",
                          borderRadius: 999,
                          fontSize: 12,
                          fontWeight: 700,
                          background: chip.bg,
                          color: chip.fg,
                          fontVariantNumeric: "tabular-nums",
                        }}
                      >
                        {formatRatePct(r.recapture_rate)}
                      </span>
                      <span
                        style={{
                          fontSize: 11,
                          color: colors.slate400,
                          marginLeft: 8,
                        }}
                      >
                        {r.gaps_closed}/{r.gaps_open + r.gaps_closed}
                      </span>
                    </td>
                    <td className="tabular-nums" style={{ ...tdStyle, color: colors.emerald500, fontWeight: 600 }}>
                      {formatCurrency(r["$_recaptured"])}
                    </td>
                    <td className="tabular-nums" style={{ ...tdStyle, color: colors.red600, fontWeight: 600 }}>
                      {formatCurrency(r["$_at_risk"])}
                    </td>
                    <td style={tdStyle}>
                      {band === "top" ? (
                        <span style={{ fontSize: 11, color: colors.emerald500, fontWeight: 700 }}>
                          Top
                        </span>
                      ) : band === "bottom" ? (
                        <span style={{ fontSize: 11, color: colors.amber500, fontWeight: 700 }}>
                          Bottom
                        </span>
                      ) : (
                        <span style={{ fontSize: 11, color: colors.slate400 }}>Mid</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Th({
  label,
  sortKey,
  current,
  dir,
  onClick,
  thStyle,
}: {
  label: string;
  sortKey: SortKey;
  current: SortKey;
  dir: "asc" | "desc";
  onClick: (k: SortKey) => void;
  thStyle: React.CSSProperties;
}) {
  const active = current === sortKey;
  return (
    <th
      style={{
        ...thStyle,
        color: active ? "#0F172A" : thStyle.color,
      }}
      onClick={() => onClick(sortKey)}
    >
      <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
        {label}
        <ArrowUpDown
          size={11}
          style={{
            opacity: active ? 1 : 0.35,
            transform: active && dir === "asc" ? "rotate(180deg)" : "none",
          }}
        />
      </span>
    </th>
  );
}
