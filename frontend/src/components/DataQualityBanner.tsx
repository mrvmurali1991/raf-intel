"use client";

/**
 * <DataQualityBanner /> — surfaces backend-reported data degradation.
 *
 * The dashboard-stats endpoint includes ``degraded: bool`` and
 * ``degraded_fields: string[]`` (set when one of the secondary aggregate
 * queries failed silently — e.g. raf_scores join, suspect count, etc.).
 *
 * When degraded, render a soft amber banner explaining which fields are
 * unreliable so the user does not interpret zeros as real clinical data.
 * Renders nothing when data is healthy.
 */

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { tokens } from "@/styles/tokens";
import { getDashboardStats } from "@/lib/api";

interface MaybeDegradedStats {
  degraded?: boolean;
  degraded_fields?: string[];
}

const FIELD_LABELS: Record<string, string> = {
  emr_connections: "EMR connection check",
  raf_scores: "RAF score aggregation",
  suspects_count: "Suspect-condition count",
  raf_distribution: "RAF distribution histogram",
  top_undercoded: "Top under-coded patients list",
  meat_compliance: "MEAT compliance percentage",
  open_recapture_gaps: "Open recapture-gap count",
  pending_attestations: "Pending-attestation count",
};

export function DataQualityBanner() {
  const { data } = useQuery<MaybeDegradedStats>({
    queryKey: ["dashboard-stats"],
    queryFn: async () => {
      const result = await getDashboardStats();
      return result as unknown as MaybeDegradedStats;
    },
    staleTime: 60_000,
    retry: 0,
  });

  if (!data?.degraded) return null;

  const fields = data.degraded_fields ?? [];
  const friendly = fields.length > 0
    ? fields.map((f) => FIELD_LABELS[f] ?? f).join(" · ")
    : "Some metrics could not be loaded";

  return (
    <div
      role="status"
      style={{
        margin: "0 0 16px",
        padding: "12px 16px",
        borderRadius: 10,
        background: tokens.warningSoft,
        border: `1px solid ${tokens.warningBorder}`,
        color: tokens.warningText,
        display: "flex",
        alignItems: "flex-start",
        gap: 12,
        fontSize: 13,
        lineHeight: 1.5,
      }}
    >
      <AlertTriangle size={18} style={{ flexShrink: 0, marginTop: 1 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, marginBottom: 2 }}>
          Some dashboard data may be incomplete
        </div>
        <div style={{ fontSize: 12 }}>
          Affected: {friendly}.  Zero values for these fields may not reflect
          real clinical state — try refreshing, or check the system-health
          page if the warning persists.
        </div>
      </div>
    </div>
  );
}

export default DataQualityBanner;
