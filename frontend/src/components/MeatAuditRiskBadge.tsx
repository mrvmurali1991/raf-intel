"use client";

/**
 * MeatAuditRiskBadge — pill badge that surfaces a provider's RADV audit-risk
 * tier.  Tooltip shows the underlying MEAT % + HCC count.  Click opens the
 * MEAT Evidence Modal so coders can drill into the weakest HCCs.
 *
 * The badge is intentionally compact (size="sm") for use inside leaderboard
 * rows, and has a "lg" variant for the provider detail drawer header.
 */
import React, { useState } from "react";
import { ShieldCheck, ShieldAlert, ShieldX, ShieldQuestion } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import {
  getProviderMeatAuditRisk,
  type MeatAuditRisk,
  type MeatAuditRiskTier,
} from "@/lib/api";
import { MeatEvidenceModal } from "./MeatEvidenceModal";

const TIER_COLORS: Record<
  MeatAuditRiskTier,
  { fg: string; bg: string; border: string; Icon: React.ComponentType<{ size: number }> }
> = {
  ready: {
    fg: "#065F46",
    bg: "#D1FAE5",
    border: "#10B981",
    Icon: ShieldCheck,
  },
  at_risk: {
    fg: "#92400E",
    bg: "#FEF3C7",
    border: "#F59E0B",
    Icon: ShieldAlert,
  },
  audit_risk: {
    fg: "#991B1B",
    bg: "#FEE2E2",
    border: "#EF4444",
    Icon: ShieldX,
  },
  insufficient: {
    fg: "#475569",
    bg: "#F1F5F9",
    border: "#94A3B8",
    Icon: ShieldQuestion,
  },
};

export interface MeatAuditRiskBadgeProps {
  providerId: number;
  providerName?: string;
  year?: number;
  size?: "sm" | "lg";
  /**
   * If true, clicking does nothing (caller handles drilldown).  Default false:
   * the badge owns the modal lifecycle.
   */
  noModal?: boolean;
}

export function MeatAuditRiskBadge({
  providerId,
  providerName,
  year,
  size = "sm",
  noModal = false,
}: MeatAuditRiskBadgeProps) {
  const [modalOpen, setModalOpen] = useState(false);

  const { data, isLoading, isError } = useQuery<MeatAuditRisk>({
    queryKey: ["meat-audit-risk", providerId, year ?? 2026],
    queryFn: () => getProviderMeatAuditRisk(providerId, year),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  if (isLoading) {
    return (
      <span
        aria-label="Loading audit-risk"
        style={{
          display: "inline-block",
          width: size === "lg" ? 130 : 96,
          height: size === "lg" ? 28 : 22,
          borderRadius: 9999,
          background: "#F1F5F9",
          opacity: 0.6,
        }}
      />
    );
  }

  if (isError || !data) {
    return null;
  }

  const colors = TIER_COLORS[data.risk_tier];
  const Icon = colors.Icon;

  const pct = Math.round(data.meat_completeness * 100);
  const tooltip = `${pct}% MEAT compliance across ${data.hcc_count} coded HCC${data.hcc_count === 1 ? "" : "s"}${data.risk_tier === "insufficient" ? " (need at least 3)" : ""}`;

  const padX = size === "lg" ? 12 : 8;
  const padY = size === "lg" ? 6 : 3;
  const fontSize = size === "lg" ? 13 : 11;
  const iconSize = size === "lg" ? 14 : 12;

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (noModal) return;
    setModalOpen(true);
  };

  return (
    <>
      <button
        type="button"
        title={tooltip}
        aria-label={`${data.risk_label}: ${tooltip}`}
        onClick={handleClick}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: size === "lg" ? 6 : 4,
          padding: `${padY}px ${padX}px`,
          borderRadius: 9999,
          fontSize,
          fontWeight: 700,
          background: colors.bg,
          color: colors.fg,
          border: `1px solid ${colors.border}`,
          cursor: noModal ? "default" : "pointer",
          letterSpacing: "0.02em",
          whiteSpace: "nowrap",
          transition: "transform 0.15s ease, box-shadow 0.15s ease",
        }}
        onMouseEnter={(e) => {
          if (noModal) return;
          (e.currentTarget as HTMLButtonElement).style.boxShadow = `0 0 0 3px ${colors.border}33`;
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLButtonElement).style.boxShadow = "none";
        }}
      >
        <Icon size={iconSize} />
        <span>{data.risk_label}</span>
      </button>

      {!noModal && modalOpen && (
        <MeatEvidenceModal
          providerId={providerId}
          providerName={providerName}
          year={year}
          assessment={data}
          onClose={() => setModalOpen(false)}
        />
      )}
    </>
  );
}

export default MeatAuditRiskBadge;
