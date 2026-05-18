"use client";

/**
 * /ehr-writeback — Admin view of the EHR Problem List write-back queue.
 *
 * Shows all entries from ehr_writeback_queue with status chip,
 * patient ID, ICD-10, attested-by, and timestamps.
 */

import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, RefreshCw, AlertCircle, CheckCircle2, Clock } from "lucide-react";
import { getEhrWriteBackQueue } from "@/lib/api";
import type { EhrWriteBackQueueItem } from "@/lib/api";
import { FONT_SYS, FONT_MONO } from "@/lib/ui-utils";
import { FieldTooltip } from "@/components/ui/field-tooltip";

const STATUS_CONFIG: Record<
  EhrWriteBackQueueItem["status"],
  { label: string; bg: string; color: string; icon: React.ReactNode }
> = {
  queued: {
    label: "Queued",
    bg: "#eff6ff",
    color: "#2563eb",
    icon: <Clock size={12} />,
  },
  sent: {
    label: "Sent",
    bg: "#f0fdf4",
    color: "#16a34a",
    icon: <CheckCircle2 size={12} />,
  },
  failed: {
    label: "Failed",
    bg: "#fef2f2",
    color: "#dc2626",
    icon: <AlertCircle size={12} />,
  },
};

const STATUS_FILTERS = ["all", "queued", "sent", "failed"] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];

function StatusChip({ status }: { status: EhrWriteBackQueueItem["status"] }) {
  const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG.queued;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "3px 9px",
        borderRadius: 14,
        fontSize: 11.5,
        fontWeight: 600,
        background: cfg.bg,
        color: cfg.color,
      }}
    >
      {cfg.icon}
      {cfg.label}
    </span>
  );
}

function fmt(dt: string | null) {
  if (!dt) return "—";
  try {
    return new Date(dt).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return dt;
  }
}

export default function EhrWriteBackPage() {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ["ehr-writeback-queue", statusFilter],
    queryFn: () =>
      getEhrWriteBackQueue(statusFilter === "all" ? undefined : statusFilter),
    refetchInterval: 30_000,
  });

  const rows = data ?? [];

  return (
    <div
      style={{
        fontFamily: FONT_SYS,
        color: "#0f172a",
        minHeight: "100vh",
        background: "#f8fafc",
        padding: "28px 24px 48px",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 24,
          flexWrap: "wrap",
          gap: 12,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span
            style={{
              background: "#eff6ff",
              borderRadius: 10,
              padding: 10,
              lineHeight: 0,
              color: "#2563eb",
            }}
          >
            <Activity size={22} />
          </span>
          <div>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>
              EHR Write-Back Queue
            </h1>
            <p style={{ margin: 0, fontSize: 13, color: "#64748b" }}>
              Problem List entries awaiting SMART-on-FHIR delivery
            </p>
          </div>
        </div>

        <button
          onClick={() => refetch()}
          disabled={isFetching}
          aria-label="Refresh queue"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            padding: "8px 14px",
            borderRadius: 8,
            border: "1.5px solid #e2e8f0",
            background: "#fff",
            color: "#475569",
            fontSize: 13,
            fontWeight: 500,
            cursor: isFetching ? "not-allowed" : "pointer",
          }}
        >
          <RefreshCw size={14} style={{ animation: isFetching ? "spin 1s linear infinite" : "none" }} />
          Refresh
        </button>
      </div>

      {/* Filter tabs */}
      <div style={{ display: "flex", gap: 6, marginBottom: 18, alignItems: "center" }}>
        {STATUS_FILTERS.map((s) => {
          const tabTooltip =
            s === "all"    ? "Show all write-back entries regardless of status." :
            s === "queued" ? "Queued — entry is waiting to be delivered to the EHR via SMART-on-FHIR. Delivery is attempted on the next scheduler run." :
            s === "sent"   ? "Sent — the Problem List entry was successfully written to the EHR. No further action needed." :
                             "Failed — delivery to the EHR failed after the maximum number of retries. Click a row to retry manually.";
          return (
            <FieldTooltip key={s} content={tabTooltip} side="bottom">
              <button
                onClick={() => setStatusFilter(s)}
                style={{
                  padding: "6px 14px",
                  borderRadius: 14,
                  border: "1.5px solid",
                  borderColor: statusFilter === s ? "#2563eb" : "#e2e8f0",
                  background: statusFilter === s ? "#eff6ff" : "#fff",
                  color: statusFilter === s ? "#2563eb" : "#64748b",
                  fontSize: 12.5,
                  fontWeight: 600,
                  cursor: "pointer",
                  textTransform: "capitalize",
                }}
              >
                {s}
              </button>
            </FieldTooltip>
          );
        })}
        <FieldTooltip content="This queue refreshes automatically every 30 seconds. Click any failed row to trigger an immediate retry." side="right">
          <span style={{ fontSize: 11.5, color: "#94a3b8", marginLeft: 8, cursor: "default" }}>
            Auto-refreshes every 30s
          </span>
        </FieldTooltip>
      </div>

      {/* Table */}
      <div
        style={{
          background: "#fff",
          borderRadius: 10,
          border: "1px solid #e2e8f0",
          overflow: "hidden",
        }}
      >
        {/* Table header */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "60px 110px 120px 110px 1fr 130px 130px",
            padding: "10px 20px",
            background: "#f8fafc",
            borderBottom: "1px solid #e2e8f0",
            fontSize: 11.5,
            fontWeight: 700,
            color: "#94a3b8",
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            gap: 8,
          }}
        >
          <span>ID</span>
          <span>Status</span>
          <span>Patient</span>
          <span>ICD-10</span>
          <span>Attested By</span>
          <span>Last Attempt</span>
          <span>Queued At</span>
        </div>

        {/* Rows */}
        {isLoading && (
          <div style={{ padding: "32px 20px", color: "#94a3b8", textAlign: "center", fontSize: 14 }}>
            Loading queue...
          </div>
        )}
        {isError && (
          <div style={{ padding: "32px 20px", color: "#dc2626", textAlign: "center", fontSize: 14 }}>
            Failed to load queue. Check permissions.
          </div>
        )}
        {!isLoading && !isError && rows.length === 0 && (
          <div style={{ padding: "32px 20px", color: "#94a3b8", textAlign: "center", fontSize: 14 }}>
            No entries found.
          </div>
        )}
        {rows.map((row, i) => (
          <div
            key={row.id}
            style={{
              display: "grid",
              gridTemplateColumns: "60px 110px 120px 110px 1fr 130px 130px",
              padding: "12px 20px",
              borderBottom: i < rows.length - 1 ? "1px solid #f1f5f9" : "none",
              alignItems: "center",
              gap: 8,
              fontSize: 13,
            }}
          >
            <span style={{ color: "#94a3b8", fontFamily: FONT_MONO, fontSize: 12 }}>
              #{row.id}
            </span>
            <span>
              <StatusChip status={row.status} />
            </span>
            <span style={{ color: "#334155" }}>#{row.patient_id}</span>
            <span
              style={{
                fontFamily: FONT_MONO,
                fontSize: 12.5,
                fontWeight: 600,
                color: "#1e293b",
              }}
            >
              {row.icd10}
              {row.hcc_code && (
                <span style={{ color: "#94a3b8", fontWeight: 400, marginLeft: 4 }}>
                  HCC {row.hcc_code}
                </span>
              )}
            </span>
            <span style={{ color: "#475569", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {row.attested_by ?? "—"}
            </span>
            <span style={{ color: "#64748b", fontSize: 12 }}>{fmt(row.last_attempt_at)}</span>
            <span style={{ color: "#64748b", fontSize: 12 }}>{fmt(row.created_at)}</span>
          </div>
        ))}
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
