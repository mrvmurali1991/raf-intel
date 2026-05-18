"use client";

/**
 * /admin/hcc-rejections — Read-only audit log of all HCC gap rejections.
 *
 * Paginated table showing every rejection recorded in raf_hcc_rejections,
 * linked to the SHA-256 audit chain.  Compliance officers use this during
 * RADV reviews and DOJ inquiries to demonstrate two-way coding practice.
 *
 * Accessibility: table headers have scope="col", status chips have aria-label.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ShieldAlert, AlertTriangle, ChevronLeft, ChevronRight as ChevronRightIcon } from "lucide-react";
import { PageHeader } from "@/components/healthcare-ui";
import { tokens } from "@/styles/tokens";
import api from "@/lib/api";
import { FieldTooltip } from "@/components/ui/field-tooltip";

interface RejectionRow {
  id: number;
  patient_id: number;
  hcc_code: string;
  payment_year: number;
  rejected_by: number;
  rejected_at: string;
  reason_code: string;
  reason_label: string;
  reason_text: string | null;
  prior_year_documented: number;
  sha256_hash: string;
}

interface RejectionListResponse {
  total: number;
  page: number;
  page_size: number;
  items: RejectionRow[];
}

const REASON_COLORS: Record<string, { bg: string; color: string }> = {
  not_supported_in_chart:      { bg: "#fef2f2", color: "#dc2626" },
  incorrect_specificity:       { bg: "#fff7ed", color: "#c2410c" },
  resolved_condition:          { bg: "#f0fdf4", color: "#166534" },
  documentation_insufficient:  { bg: "#eff6ff", color: "#1d4ed8" },
  coder_error:                 { bg: "#fdf4ff", color: "#7e22ce" },
  provider_dispute:            { bg: "#fefce8", color: "#854d0e" },
};

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString("en-US", {
      month: "short", day: "numeric", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function truncateHash(hash: string): string {
  return `${hash.slice(0, 8)}…${hash.slice(-6)}`;
}

const PAGE_SIZE = 50;

export default function HccRejectionsAdminPage() {
  const [page, setPage] = useState(1);

  const { data, isLoading, isError, error } = useQuery<RejectionListResponse>({
    queryKey: ["hcc-rejections-admin", page],
    queryFn: async () => {
      const { data } = await api.get<RejectionListResponse>("/api/v1/hcc-rejections", {
        params: { page, page_size: PAGE_SIZE },
      });
      return data;
    },
    staleTime: 30_000,
  });

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 1;

  return (
    <div style={{ padding: "20px 16px", maxWidth: 1400, margin: "0 auto" }} className="rci-page-pad-desktop">
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
        <ShieldAlert size={22} color={tokens.danger} aria-hidden />
        <PageHeader
          title="HCC Rejection Audit Log"
          subtitle="Immutable, append-only record of all coder-rejected HCC gaps (DOJ-compliant)"
        />
      </div>

      {/* Compliance callout */}
      <div
        style={{
          marginBottom: 20,
          padding: "10px 14px",
          borderRadius: 8,
          background: "#FFFBEB",
          border: "1px solid #FDE68A",
          fontSize: 12,
          color: "#92400E",
          lineHeight: 1.6,
        }}
      >
        <strong>Read-only.</strong> Each row is SHA-256 chained to the previous entry.
        Rejected gaps are excluded from the recapture queue for the recorded payment year.
        Re-acceptance requires a subsequent rejection-of-rejection entry — the original record is never deleted.
      </div>

      {isLoading && (
        <div style={{ display: "grid", gap: 8 }}>
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="shimmer" style={{ height: 44, borderRadius: 8 }} />
          ))}
        </div>
      )}

      {isError && (
        <div
          role="alert"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: 14,
            borderRadius: 10,
            background: tokens.dangerSoft,
            border: `1px solid ${tokens.dangerBorder}`,
            color: tokens.danger,
            fontSize: 14,
          }}
        >
          <AlertTriangle size={18} />
          {error instanceof Error ? error.message : "Failed to load rejection log."}
        </div>
      )}

      {data && (
        <>
          <div style={{ overflowX: "auto", borderRadius: 10, border: `1px solid ${tokens.slate200}` }}>
            <table
              style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}
              aria-label="HCC Rejection audit log"
            >
              <thead>
                <tr style={{ background: tokens.slate50, borderBottom: `1px solid ${tokens.slate200}` }}>
                  {["ID", "Patient", "HCC", "Year", "Reason", "Notes", "Prior yr doc'd", "Rejected by", "Rejected at", "SHA-256"].map((h) => (
                    <th
                      key={h}
                      scope="col"
                      style={{
                        padding: "10px 12px",
                        textAlign: "left",
                        fontSize: 11,
                        fontWeight: 700,
                        color: tokens.slate600,
                        textTransform: "uppercase",
                        letterSpacing: "0.04em",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.items.length === 0 && (
                  <tr>
                    <td
                      colSpan={10}
                      style={{ padding: "32px 16px", textAlign: "center", color: tokens.slate400, fontSize: 13 }}
                    >
                      No rejections recorded yet.
                    </td>
                  </tr>
                )}
                {data.items.map((row, idx) => {
                  const rc = REASON_COLORS[row.reason_code] ?? { bg: tokens.slate50, color: tokens.slate600 };
                  return (
                    <tr
                      key={row.id}
                      style={{
                        borderBottom: `1px solid ${tokens.slate100}`,
                        background: idx % 2 === 0 ? tokens.white : tokens.slate50,
                      }}
                    >
                      <td style={{ padding: "9px 12px", color: tokens.slate500, fontVariantNumeric: "tabular-nums" }}>
                        {row.id}
                      </td>
                      <td style={{ padding: "9px 12px", color: tokens.slate700, fontWeight: 600 }}>
                        {row.patient_id}
                      </td>
                      <td style={{ padding: "9px 12px" }}>
                        <span
                          style={{
                            padding: "2px 8px",
                            borderRadius: 999,
                            background: tokens.dangerSoft,
                            color: tokens.danger,
                            fontSize: 11,
                            fontWeight: 700,
                          }}
                        >
                          HCC {row.hcc_code}
                        </span>
                      </td>
                      <td style={{ padding: "9px 12px", color: tokens.slate700, fontVariantNumeric: "tabular-nums" }}>
                        {row.payment_year}
                      </td>
                      <td style={{ padding: "9px 12px" }}>
                        <FieldTooltip
                          content={
                            row.reason_code === "not_supported_in_chart"     ? "Not Supported in Chart — no clinical documentation found in the medical record to support this HCC." :
                            row.reason_code === "incorrect_specificity"      ? "Incorrect Specificity — the diagnosis code lacks the required specificity for RAF risk-adjustment credit." :
                            row.reason_code === "resolved_condition"         ? "Resolved Condition — the condition was treated and resolved; no active status found in the encounter." :
                            row.reason_code === "documentation_insufficient" ? "Documentation Insufficient — clinical notes exist but do not meet CMS RADV evidence standards." :
                            row.reason_code === "coder_error"                ? "Coder Error — the HCC was mapped incorrectly; the underlying ICD-10 does not map to this HCC." :
                            row.reason_code === "provider_dispute"           ? "Provider Dispute — the treating provider contests the coding and has submitted a corrected claim." :
                            `Reason code: ${row.reason_code}`
                          }
                          side="right"
                        >
                          <span
                            aria-label={`Reason: ${row.reason_label}`}
                            style={{
                              display: "inline-block",
                              padding: "2px 8px",
                              borderRadius: 6,
                              background: rc.bg,
                              color: rc.color,
                              fontSize: 11,
                              fontWeight: 600,
                              whiteSpace: "nowrap",
                              cursor: "help",
                            }}
                          >
                            {row.reason_label}
                          </span>
                        </FieldTooltip>
                      </td>
                      <td
                        style={{
                          padding: "9px 12px",
                          color: tokens.slate600,
                          maxWidth: 200,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                        title={row.reason_text ?? ""}
                      >
                        {row.reason_text ?? <span style={{ color: tokens.slate300 }}>—</span>}
                      </td>
                      <td style={{ padding: "9px 12px", textAlign: "center" }}>
                        <FieldTooltip
                          content="Prior-year documented: True if this HCC was billed and accepted in the previous payment year. Used by RADV auditors to assess recapture patterns."
                          side="top"
                        >
                          <span
                            aria-label={row.prior_year_documented ? "Yes" : "No"}
                            style={{
                              padding: "2px 8px",
                              borderRadius: 6,
                              fontSize: 11,
                              fontWeight: 700,
                              background: row.prior_year_documented ? "#f0fdf4" : tokens.slate100,
                              color: row.prior_year_documented ? "#166534" : tokens.slate500,
                              cursor: "help",
                            }}
                          >
                            {row.prior_year_documented ? "Yes" : "No"}
                          </span>
                        </FieldTooltip>
                      </td>
                      <td style={{ padding: "9px 12px", color: tokens.slate600, fontVariantNumeric: "tabular-nums" }}>
                        {row.rejected_by}
                      </td>
                      <td style={{ padding: "9px 12px", color: tokens.slate600, whiteSpace: "nowrap" }}>
                        {fmtDate(row.rejected_at)}
                      </td>
                      <td style={{ padding: "9px 12px" }}>
                        <FieldTooltip
                          content={`Truncated SHA-256 hash of this rejection event. Full hash: ${row.sha256_hash}. Each row is chained to the previous entry to form an immutable audit ledger.`}
                          side="left"
                        >
                          <code
                            style={{
                              fontSize: 10,
                              fontFamily: "monospace",
                              color: tokens.slate500,
                              background: tokens.slate100,
                              padding: "2px 6px",
                              borderRadius: 4,
                              cursor: "help",
                            }}
                          >
                            {truncateHash(row.sha256_hash)}
                          </code>
                        </FieldTooltip>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div
              style={{
                marginTop: 16,
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                fontSize: 13,
                color: tokens.slate600,
              }}
            >
              <span>
                Showing {((page - 1) * PAGE_SIZE) + 1}–{Math.min(page * PAGE_SIZE, data.total)} of {data.total} rejections
              </span>
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  aria-label="Previous page"
                  style={{
                    display: "flex", alignItems: "center", gap: 4,
                    padding: "6px 12px", borderRadius: 8,
                    border: `1px solid ${tokens.slate200}`,
                    background: tokens.white,
                    color: page === 1 ? tokens.slate300 : tokens.slate700,
                    cursor: page === 1 ? "not-allowed" : "pointer",
                    fontSize: 13, fontWeight: 600,
                  }}
                >
                  <ChevronLeft size={14} /> Prev
                </button>
                <span style={{ padding: "6px 12px", fontSize: 13, color: tokens.slate500 }}>
                  {page} / {totalPages}
                </span>
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  aria-label="Next page"
                  style={{
                    display: "flex", alignItems: "center", gap: 4,
                    padding: "6px 12px", borderRadius: 8,
                    border: `1px solid ${tokens.slate200}`,
                    background: tokens.white,
                    color: page === totalPages ? tokens.slate300 : tokens.slate700,
                    cursor: page === totalPages ? "not-allowed" : "pointer",
                    fontSize: 13, fontWeight: 600,
                  }}
                >
                  Next <ChevronRightIcon size={14} />
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
