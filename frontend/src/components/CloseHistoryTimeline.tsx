"use client";

/**
 * CloseHistoryTimeline
 * --------------------
 * Vertical timeline of recent recapture-gap closures, sourced from
 * ``GET /api/recapture/close-history``. Shows who closed what, when, and
 * the evidence they entered.
 */

import { useQuery } from "@tanstack/react-query";
import { History, User, Quote, FileText, RefreshCw } from "lucide-react";
import { getRecaptureCloseHistory, type RecaptureGapRow } from "@/lib/api";

interface Props {
  year?: number;
  limit?: number;
}

function formatRelative(iso: string): string {
  try {
    const ts = new Date(iso).getTime();
    if (Number.isNaN(ts)) return iso;
    const diff = Date.now() - ts;
    const m = Math.round(diff / 60_000);
    if (m < 1) return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.round(m / 60);
    if (h < 24) return `${h}h ago`;
    const d = Math.round(h / 24);
    if (d < 30) return `${d}d ago`;
    return new Date(iso).toLocaleDateString();
  } catch {
    return iso;
  }
}

export default function CloseHistoryTimeline({ year, limit = 25 }: Props) {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["recapture-close-history", year, limit],
    queryFn: () => getRecaptureCloseHistory(year, limit),
  });

  return (
    <div className="premium-card" style={{ padding: 24, marginBottom: 24 }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
        <h3 className="gradient-text" style={{ margin: 0, fontSize: 16, fontWeight: 700, display: "flex", alignItems: "center", gap: 8 }}>
          <History size={16} />
          Recent Close Activity
        </h3>
        <button
          type="button"
          onClick={() => refetch()}
          disabled={isLoading}
          style={{
            display: "inline-flex", alignItems: "center", gap: 6,
            padding: "6px 10px", borderRadius: 8,
            border: "1px solid #E2E8F0", background: "#fff",
            fontSize: 12, fontWeight: 600, color: "#475569",
            cursor: isLoading ? "not-allowed" : "pointer",
          }}
        >
          <RefreshCw size={12} /> Refresh
        </button>
      </div>

      {isLoading && (
        <p style={{ fontSize: 13, color: "#64748B", margin: 0 }}>Loading close history…</p>
      )}
      {isError && (
        <p style={{ fontSize: 13, color: "#B91C1C", margin: 0 }}>
          Failed to load close history.
        </p>
      )}

      {!isLoading && !isError && (data?.items?.length ?? 0) === 0 && (
        <p style={{ fontSize: 13, color: "#64748B", margin: 0 }}>
          No gaps closed yet for this period.
        </p>
      )}

      {!isLoading && !isError && (data?.items?.length ?? 0) > 0 && (
        <ol
          style={{
            listStyle: "none", margin: 0, padding: 0,
            position: "relative",
            borderLeft: "2px solid #E2E8F0",
            paddingLeft: 18,
          }}
        >
          {data!.items.map((item: RecaptureGapRow) => (
            <li
              key={item.id}
              style={{
                position: "relative", marginBottom: 16,
                paddingBottom: 14, borderBottom: "1px solid #F1F5F9",
              }}
            >
              {/* dot */}
              <span style={{
                position: "absolute", left: -25, top: 4,
                width: 12, height: 12, borderRadius: 6,
                background: "#2563EB", border: "2px solid #fff",
                boxShadow: "0 0 0 2px #BFDBFE",
              }} />

              <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: "#0F172A" }}>
                  {item.patient_name || `Patient ${item.patient_id}`}
                </span>
                <span style={{
                  fontSize: 11, padding: "2px 8px", borderRadius: 999,
                  background: "#EFF6FF", color: "#1E40AF", fontWeight: 600,
                }}>
                  HCC {item.hcc_code}
                </span>
                {item.meat_element && (
                  <span style={{
                    fontSize: 11, padding: "2px 8px", borderRadius: 999,
                    background: "#ECFDF5", color: "#047857", fontWeight: 600,
                  }}>
                    MEAT · {item.meat_element}
                  </span>
                )}
                <span style={{ fontSize: 11, color: "#64748B", marginLeft: "auto" }}>
                  {item.resolved_at ? formatRelative(item.resolved_at) : ""}
                </span>
              </div>

              <div style={{ marginTop: 6, fontSize: 12, color: "#64748B", display: "flex", alignItems: "center", gap: 6 }}>
                <User size={12} />
                <span>Closed by <strong style={{ color: "#0F172A" }}>{item.resolved_by || "system"}</strong></span>
              </div>

              {item.evidence_phrase && (
                <blockquote style={{
                  margin: "8px 0 0", padding: "8px 12px",
                  borderLeft: "3px solid #BFDBFE",
                  background: "#F8FAFC", borderRadius: 4,
                  fontSize: 12, color: "#334155", fontStyle: "italic",
                  display: "flex", alignItems: "flex-start", gap: 8,
                }}>
                  <Quote size={12} style={{ flexShrink: 0, color: "#2563EB", marginTop: 2 }} />
                  <span style={{ flex: 1 }}>{item.evidence_phrase}</span>
                </blockquote>
              )}

              {item.icd10_code && (
                <div style={{ marginTop: 6, fontSize: 11, color: "#64748B", display: "flex", alignItems: "center", gap: 6 }}>
                  <FileText size={11} /> ICD-10 {item.icd10_code}
                </div>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
