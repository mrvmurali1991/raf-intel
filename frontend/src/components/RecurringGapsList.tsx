"use client";

/**
 * RecurringGapsList
 *
 * Dedicated section that lists ONLY recurring recapture gaps for a given
 * year, decorated with a years_recurring chip + escalation CTA + a
 * "Suggest AWV" button per row.
 *
 * Wraps:
 *   POST /api/recapture/recurring/detect      (button: "Detect Recurring")
 *   GET  /api/recapture/recurring?year=YYYY
 *   POST /api/recapture/gaps/{id}/suggest-awv  (opened in <AWVSuggestionDialog>)
 */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, RefreshCw, CalendarPlus, Flame } from "lucide-react";

import {
  detectRecurringGaps,
  listRecurringGaps,
  type RecurringGap,
} from "@/lib/api";
import { RecurringGapAlert } from "@/components/RecurringGapAlert";
import { AWVSuggestionDialog } from "@/components/AWVSuggestionDialog";

interface RecurringGapsListProps {
  year: number;
  /** Optional: callback invoked after a successful detect run. */
  onDetected?: (matches: number) => void;
}

const colors = {
  primary: "#2563EB",
  red600: "#DC2626",
  amber500: "#F59E0B",
  slate900: "#0F172A",
  slate600: "#475569",
  slate400: "#64748B",
  slate200: "#E2E8F0",
  slate100: "#F1F5F9",
  slate50: "#F8FAFC",
  white: "#FFFFFF",
};

export function RecurringGapsList({ year, onDetected }: RecurringGapsListProps) {
  const queryClient = useQueryClient();
  const [selectedGapId, setSelectedGapId] = useState<number | null>(null);

  const { data, isLoading, isError, refetch } = useQuery<{ year: number; total: number; items: RecurringGap[] }>({
    queryKey: ["recurring-gaps", year],
    queryFn: () => listRecurringGaps(year),
  });

  const detectMutation = useMutation({
    mutationFn: () => detectRecurringGaps(year, 3),
    onSuccess: (resp) => {
      onDetected?.(resp.matches);
      queryClient.invalidateQueries({ queryKey: ["recurring-gaps", year] });
    },
  });

  const items = data?.items ?? [];

  return (
    <div
      className="premium-card animate-slide-up"
      style={{
        padding: 24,
        marginBottom: 24,
        border: `1px solid ${colors.slate200}`,
        borderRadius: 12,
        background: colors.white,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16, flexWrap: "wrap", gap: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Flame size={20} color={colors.red600} />
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: colors.slate900 }}>
            Recurring Recapture Gaps ({year})
          </h3>
          {data && (
            <span
              style={{
                padding: "2px 10px",
                borderRadius: 999,
                fontSize: 11,
                fontWeight: 700,
                background: `${colors.red600}1A`,
                color: colors.red600,
              }}
            >
              {data.total}
            </span>
          )}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            onClick={() => detectMutation.mutate()}
            disabled={detectMutation.isPending}
            className="btn-press"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "8px 14px",
              borderRadius: 8,
              border: `1px solid ${colors.slate200}`,
              background: colors.white,
              color: colors.slate900,
              fontSize: 13,
              fontWeight: 600,
              cursor: detectMutation.isPending ? "not-allowed" : "pointer",
              opacity: detectMutation.isPending ? 0.6 : 1,
            }}
          >
            <RefreshCw size={14} className={detectMutation.isPending ? "spin" : ""} />
            {detectMutation.isPending ? "Detecting…" : "Detect Recurring"}
          </button>
        </div>
      </div>

      <p style={{ margin: "0 0 16px", fontSize: 13, color: colors.slate600, lineHeight: 1.5 }}>
        These gaps have been open for 2+ consecutive years — provider isn't capturing them
        and the patient isn't visiting. Each one is a candidate for an Annual Wellness Visit.
      </p>

      {detectMutation.isSuccess && detectMutation.data && (
        <div
          style={{
            padding: "10px 14px",
            borderRadius: 8,
            background: "#ECFDF5",
            border: "1px solid #A7F3D0",
            color: "#065F46",
            fontSize: 13,
            marginBottom: 12,
          }}
        >
          Detection complete — {detectMutation.data.matches} recurring gap(s) identified.
        </div>
      )}

      {isLoading && (
        <div style={{ padding: 32, textAlign: "center", color: colors.slate400, fontSize: 13 }}>
          Loading recurring gaps…
        </div>
      )}

      {isError && (
        <div
          role="alert"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "10px 14px",
            borderRadius: 8,
            background: "#FEF2F2",
            border: "1px solid #FECACA",
            color: "#B91C1C",
            fontSize: 13,
          }}
        >
          <AlertTriangle size={16} />
          <span>Failed to load recurring gaps.</span>
          <button
            type="button"
            onClick={() => refetch()}
            style={{
              marginLeft: "auto",
              padding: "4px 10px",
              borderRadius: 6,
              border: "1px solid #FECACA",
              background: colors.white,
              color: "#B91C1C",
              fontSize: 12,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Retry
          </button>
        </div>
      )}

      {!isLoading && !isError && items.length === 0 && (
        <div
          style={{
            padding: 24,
            textAlign: "center",
            color: colors.slate400,
            fontSize: 13,
            border: `1px dashed ${colors.slate200}`,
            borderRadius: 10,
          }}
        >
          No recurring gaps for {year}. Click <strong>Detect Recurring</strong> after detection runs to refresh.
        </div>
      )}

      {!isLoading && !isError && items.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {items.map((g) => (
            <div
              key={g.id}
              style={{
                border: `1px solid ${colors.slate200}`,
                borderLeft: `4px solid ${colors.red600}`,
                borderRadius: 10,
                padding: 14,
                background: colors.slate50,
              }}
            >
              <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", justifyContent: "space-between", gap: 12, marginBottom: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 14, fontWeight: 700, color: colors.slate900 }}>
                    {g.patient_name || `Patient #${g.patient_id}`}
                  </span>
                  <span
                    style={{
                      padding: "2px 8px",
                      borderRadius: 999,
                      fontSize: 11,
                      fontWeight: 700,
                      background: `${colors.red600}1A`,
                      color: colors.red600,
                      letterSpacing: "0.04em",
                    }}
                  >
                    {g.years_recurring ?? "?"}-yr recurring
                  </span>
                  <span
                    style={{
                      fontFamily: "monospace",
                      fontSize: 12,
                      color: colors.slate600,
                    }}
                  >
                    HCC {g.hcc_code} · {g.icd10_code}
                  </span>
                  {g.awv_suggested && (
                    <span
                      style={{
                        padding: "2px 8px",
                        borderRadius: 999,
                        fontSize: 11,
                        fontWeight: 700,
                        background: "#ECFDF5",
                        color: "#065F46",
                      }}
                    >
                      AWV scheduled{g.awv_visit_date ? ` · ${g.awv_visit_date}` : ""}
                    </span>
                  )}
                </div>
                <div style={{ display: "flex", gap: 6 }}>
                  <button
                    type="button"
                    onClick={() => setSelectedGapId(g.id)}
                    className="btn-press"
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      padding: "6px 12px",
                      borderRadius: 8,
                      border: "none",
                      background: "linear-gradient(135deg,#2563EB,#1D4ED8)",
                      color: colors.white,
                      fontSize: 12,
                      fontWeight: 600,
                      cursor: "pointer",
                      boxShadow: "0 1px 3px rgba(37,99,235,0.3)",
                    }}
                  >
                    <CalendarPlus size={13} /> Suggest AWV
                  </button>
                </div>
              </div>

              <RecurringGapAlert yearsRecurring={g.years_recurring ?? 2} compact />

              <div style={{ display: "flex", flexWrap: "wrap", gap: 16, marginTop: 8, fontSize: 12, color: colors.slate600 }}>
                <span>
                  <strong>Revenue at risk:</strong> ${(g.revenue_impact || 0).toLocaleString()}
                </span>
                <span>
                  <strong>Status:</strong> {g.status}
                </span>
                {g.dob && (
                  <span>
                    <strong>DOB:</strong> {g.dob}
                  </span>
                )}
                {g.provider_npi && (
                  <span>
                    <strong>Provider NPI:</strong> {g.provider_npi}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      <AWVSuggestionDialog
        gapId={selectedGapId}
        open={selectedGapId != null}
        onClose={() => setSelectedGapId(null)}
        onScheduled={() => {
          queryClient.invalidateQueries({ queryKey: ["recurring-gaps", year] });
        }}
      />
    </div>
  );
}

export default RecurringGapsList;
