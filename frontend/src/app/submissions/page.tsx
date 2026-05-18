"use client";

import React, { useState, useCallback, useRef, useMemo } from "react";
import dynamic from "next/dynamic";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { tokens } from "@/styles/tokens";
import { DataQualityBanner } from "@/components/DataQualityBanner";
import {
  Send,
  RefreshCw,
  AlertTriangle,
  X,
  ChevronDown,
  ChevronUp,
  CheckCircle,
  XCircle,
  Clock,
  Loader2,
  Download,
  Upload,
  FileText,
  AlertCircle,
  DollarSign,
  BarChart2,
  Calendar,
  Play,
  Eye,
  List,
  ShieldCheck,
  FileCheck,
  Inbox,
} from "lucide-react";
import { PageHeader, EmptyState } from "@/components/healthcare-ui";
import { MetricCard } from "@/components/ui/metric-card";

// ─────────────────────────────────────────────
// Lazy-loaded heavy panels (deferred from initial paint)
// ─────────────────────────────────────────────

const LazyGenerateDialog = dynamic(
  () => import("./SubmissionsDialogsPanels").then((m) => ({ default: m.GenerateDialog })),
  { ssr: false, loading: () => null }
);

const LazyUploadResponseDialog = dynamic(
  () => import("./SubmissionsDialogsPanels").then((m) => ({ default: m.UploadResponseDialog })),
  { ssr: false, loading: () => null }
);

const LazyBatchDetailPanel = dynamic(
  () => import("./SubmissionsDialogsPanels").then((m) => ({ default: m.BatchDetailPanel })),
  {
    ssr: false,
    loading: () => (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: 48, gap: 10, color: "#64748B" }}>
        <div style={{ width: 20, height: 20, border: "3px solid #E2E8F0", borderTopColor: "#2563EB", borderRadius: "50%", animation: "spin 0.8s linear infinite" }} />
        <span style={{ fontSize: 14 }}>Loading detail…</span>
      </div>
    ),
  }
);

// ─────────────────────────────────────────────
// Design Tokens (sourced from tokens.ts — no hardcoded hex)
// ─────────────────────────────────────────────

const T = {
  white:      tokens.white,
  slate50:    tokens.slate50,
  slate100:   tokens.slate100,
  slate200:   tokens.slate200,
  slate300:   tokens.slate300,
  slate400:   tokens.slate400,
  slate500:   tokens.slate500,
  slate600:   tokens.slate600,
  slate700:   tokens.slate700,
  slate800:   tokens.slate800,
  slate900:   tokens.slate900,
  blue50:     tokens.primarySoft,
  blue100:    "rgba(37,99,235,0.12)",
  blue500:    tokens.infoBlue,
  blue600:    tokens.primary,
  blue700:    tokens.primaryDark,
  emerald50:  tokens.successSoft,
  emerald100: tokens.emerald100,
  emerald500: tokens.success,
  emerald600: tokens.riskLow,
  amber50:    tokens.warningSoft,
  amber100:   tokens.warningSoft,
  amber500:   tokens.warningStrong,
  amber600:   tokens.riskMedium,
  red50:      tokens.riskHighSoft,
  red100:     tokens.dangerSoft,
  red500:     tokens.riskHigh,
  red600:     tokens.danger,
  violet50:   "rgba(139,92,246,0.08)",
  violet500:  tokens.accentPurple,
  violet600:  "rgba(124,58,237,1)",
  gray100:    tokens.slate100,
  gray200:    tokens.slate200,
  gray400:    tokens.slate400,
  gray500:    tokens.slate500,
};


// ─────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────

type SubmissionType = "RAPS" | "EDPS";
type SweepType = "Initial" | "Mid-Year" | "Final" | "Supplemental";
type BatchStatus =
  | "draft"
  | "validating"
  | "validated"
  | "submitted"
  | "accepted"
  | "rejected"
  | "partial"
  | "error";

type DetailTab = "records" | "validation" | "responses" | "reconciliation";

interface SubmissionBatch {
  id: string;
  batch_id: string;
  submission_type: SubmissionType;
  payment_year: number;
  sweep_type: SweepType;
  total_records: number;
  accepted_records: number;
  rejected_records: number;
  status: BatchStatus;
  submitted_at: string | null;
  created_at: string;
  validation_errors: number;
  validation_warnings: number;
}

interface SubmissionRecord {
  id: string;
  patient_name: string;
  patient_id: string;
  icd10_code: string;
  hcc_code: number | null;
  hcc_description: string | null;
  date_of_service: string;
  through_date: string;
  provider_id: string;
  validation_status: "pass" | "warning" | "error";
  cms_status: "accepted" | "rejected" | "pending" | null;
  rejection_reason: string | null;
}

interface ValidationIssue {
  rule_id: string;
  rule_name: string;
  severity: "error" | "warning";
  count: number;
  affected_records: string[];
  description: string;
  recommendation: string;
}

interface ResponseFile {
  id: string;
  file_name: string;
  file_type: "MAO-002" | "MAO-004";
  uploaded_at: string;
  records_parsed: number;
  accepted: number;
  rejected: number;
  status: "parsed" | "processing" | "error";
}

interface ReconciliationEntry {
  hcc_code: number;
  hcc_description: string;
  patient_count: number;
  risk_score_delta: number;
  payment_delta: number;
  cms_status: "accepted" | "rejected" | "pending";
}

interface BatchDetail {
  batch: SubmissionBatch;
  records: SubmissionRecord[];
  validation_issues: ValidationIssue[];
  response_files: ResponseFile[];
  reconciliation: ReconciliationEntry[];
  total_payment_impact: number;
  risk_score_adjustment: number;
}

interface SubmissionsStats {
  total_batches: number;
  records_submitted: number;
  acceptance_rate: number;
  pending_validation: number;
  upcoming_deadlines: number;
}

interface Deadline {
  name: string;
  type: SubmissionType;
  payment_year: number;
  sweep_type: SweepType;
  due_date: string;
  days_remaining: number;
}

// ─────────────────────────────────────────────
// API Helpers
// ─────────────────────────────────────────────

async function fetchStats(): Promise<SubmissionsStats> {
  const { data } = await api.get(`/api/submissions/stats`);
  return data;
}

async function fetchBatches(): Promise<SubmissionBatch[]> {
  const { data } = await api.get(`/api/submissions/batches`);
  return Array.isArray(data) ? data : (data?.items ?? data?.batches ?? []);
}

async function fetchDeadlines(): Promise<Deadline[]> {
  const { data } = await api.get(`/api/submissions/schedule`);
  const raw = Array.isArray(data) ? data : (data?.schedule ?? []);
  // Map API field names to frontend interface
  return raw.map((d: any) => ({
    name: d.description ?? d.name ?? '',
    type: d.submission_type ?? d.type ?? 'RAPS',
    payment_year: d.payment_year ?? new Date().getFullYear(),
    sweep_type: d.sweep_type ?? 'Initial',
    due_date: d.deadline_date ?? d.due_date ?? '',
    days_remaining: d.days_until ?? d.days_remaining ?? 0,
  }));
}

async function fetchBatchDetail(batchId: string): Promise<BatchDetail> {
  const { data } = await api.get(`/api/submissions/batches/${batchId}`);
  return data;
}

// ─────────────────────────────────────────────
// Status Badge
// ─────────────────────────────────────────────

function StatusBadge({ status }: { status: BatchStatus }) {
  const map: Record<BatchStatus, { label: string; bg: string; color: string; dot: string; icon: React.ReactNode }> = {
    draft: { label: "Draft", bg: T.slate100, color: T.slate600, dot: T.slate400, icon: <Clock size={11} /> },
    validating: { label: "Validating", bg: T.blue100, color: T.blue700, dot: T.blue500, icon: <Loader2 size={11} style={{ animation: "spin 1s linear infinite" }} /> },
    validated: { label: "Validated", bg: T.emerald50, color: T.emerald600, dot: T.emerald500, icon: <CheckCircle size={11} /> },
    submitted: { label: "Submitted", bg: `${T.emerald500}18`, color: T.emerald600, dot: T.emerald500, icon: <Send size={11} /> },
    accepted: { label: "Accepted", bg: T.emerald100, color: T.emerald600, dot: T.emerald500, icon: <CheckCircle size={11} /> },
    rejected: { label: "Rejected", bg: T.red100, color: T.red600, dot: T.red500, icon: <XCircle size={11} /> },
    partial: { label: "Partial Accept", bg: T.amber100, color: T.amber600, dot: T.amber500, icon: <AlertCircle size={11} /> },
    error: { label: "Error", bg: T.red50, color: T.red500, dot: T.red500, icon: <XCircle size={11} /> },
  };
  const cfg = map[status] ?? { label: status, bg: T.gray100, color: T.gray500, dot: T.gray400, icon: null };
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "4px 10px",
        borderRadius: 999,
        fontSize: 11,
        fontWeight: 600,
        backgroundColor: cfg.bg,
        color: cfg.color,
        whiteSpace: "nowrap",
        border: `1px solid ${cfg.color}20`,
      }}
    >
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: "50%",
          backgroundColor: cfg.dot,
          boxShadow: `0 0 6px ${cfg.dot}60`,
          flexShrink: 0,
        }}
      />
      {cfg.icon}
      {cfg.label}
    </span>
  );
}

function TypeBadge({ type }: { type: SubmissionType }) {
  const isRAPS = type === "RAPS";
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "3px 9px",
        borderRadius: 6,
        fontSize: 11,
        fontWeight: 700,
        backgroundColor: isRAPS ? T.violet50 : T.blue50,
        color: isRAPS ? T.violet600 : T.blue700,
        border: `1px solid ${isRAPS ? T.violet500 + "33" : T.blue500 + "33"}`,
        letterSpacing: "0.04em",
      }}
    >
      {type}
    </span>
  );
}

function ValidationBadge({ status }: { status: "pass" | "warning" | "error" }) {
  const map = {
    pass: { label: "Pass", bg: T.emerald50, color: T.emerald600 },
    warning: { label: "Warning", bg: T.amber50, color: T.amber600 },
    error: { label: "Error", bg: T.red50, color: T.red500 },
  };
  const cfg = map[status];
  return (
    <span
      style={{
        padding: "2px 7px",
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 600,
        backgroundColor: cfg.bg,
        color: cfg.color,
      }}
    >
      {cfg.label}
    </span>
  );
}

function CmsStatusBadge({ status }: { status: "accepted" | "rejected" | "pending" | null }) {
  if (!status) return <span style={{ color: T.slate400, fontSize: 12 }}>—</span>;
  const map = {
    accepted: { label: "Accepted", color: T.emerald600, bg: T.emerald50 },
    rejected: { label: "Rejected", color: T.red600, bg: T.red50 },
    pending: { label: "Pending", color: T.amber600, bg: T.amber50 },
  };
  const cfg = map[status];
  return (
    <span
      style={{
        padding: "2px 7px",
        borderRadius: 4,
        fontSize: 11,
        fontWeight: 600,
        backgroundColor: cfg.bg,
        color: cfg.color,
      }}
    >
      {cfg.label}
    </span>
  );
}

// ─────────────────────────────────────────────
// Deadline Banner
// ─────────────────────────────────────────────

function DeadlinesBanner({ deadlines }: { deadlines: Deadline[] }) {
  const sorted = [...deadlines].sort((a, b) => a.days_remaining - b.days_remaining);

  type DeadlineTheme = {
    bg: string;
    border: string;
    text: string;
    badge: string;
    badgeText: string;
    rowOpacity: number;
    pillLabel: string;
    pillBg: string;
    pillColor: string;
  };

  function deadlineTheme(days: number): DeadlineTheme {
    if (days < 0) {
      return {
        bg: T.red50,
        border: T.red500 + "40",
        text: T.red600,
        badge: T.red100,
        badgeText: T.red600,
        rowOpacity: 0.72,
        pillLabel: "Overdue",
        pillBg: T.red100,
        pillColor: T.red600,
      };
    }
    if (days <= 7) {
      return {
        bg: T.amber50,
        border: T.amber500 + "40",
        text: T.amber600,
        badge: T.amber100,
        badgeText: T.amber600,
        rowOpacity: 1,
        pillLabel: "Closing soon",
        pillBg: T.amber100,
        pillColor: T.amber600,
      };
    }
    if (days <= 30) {
      return {
        bg: T.amber50,
        border: T.amber500 + "30",
        text: T.amber600,
        badge: T.amber100,
        badgeText: T.amber600,
        rowOpacity: 1,
        pillLabel: "",
        pillBg: "",
        pillColor: "",
      };
    }
    return {
      bg: T.emerald50,
      border: T.emerald500 + "40",
      text: T.emerald600,
      badge: T.emerald100,
      badgeText: T.emerald600,
      rowOpacity: 1,
      pillLabel: "",
      pillBg: "",
      pillColor: "",
    };
  }

  function deadlineCountLabel(days: number): string {
    if (days < 0) return `Closed ${Math.abs(days)} day${Math.abs(days) === 1 ? "" : "s"} ago`;
    if (days === 0) return "Due today";
    return `${days} day${days === 1 ? "" : "s"} left`;
  }

  return (
    <div
      className="sub-fade-up-2"
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        marginBottom: 24,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
        <Calendar size={14} className="text-muted-foreground" />
        <span style={{ fontSize: 12, fontWeight: 600, color: T.slate500, textTransform: "uppercase", letterSpacing: "0.06em" }}>
          Submission Deadlines
        </span>
      </div>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {sorted.map((d, i) => {
          const c = deadlineTheme(d.days_remaining);
          const isOverdue = d.days_remaining < 0;
          return (
            <div
              key={`${d.name}-${i}`}
              className="hover-lift"
              style={{
                flex: "1 1 260px",
                backgroundColor: c.bg,
                border: `1px solid ${c.border}`,
                borderRadius: 10,
                padding: "14px 18px",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
                animation: `fadeInUp 0.4s ease-out ${0.08 * i}s both`,
                opacity: c.rowOpacity,
              }}
              aria-label={`${d.name}: ${deadlineCountLabel(d.days_remaining)}`}
            >
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span
                    style={{
                      fontSize: 13,
                      fontWeight: 600,
                      color: T.slate800,
                      textDecoration: isOverdue ? "line-through" : "none",
                      textDecorationColor: T.slate400,
                    }}
                  >
                    {d.name}
                  </span>
                  {c.pillLabel && (
                    <span
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        padding: "2px 8px",
                        borderRadius: 999,
                        fontSize: 10,
                        fontWeight: 700,
                        backgroundColor: c.pillBg,
                        color: c.pillColor,
                        border: `1px solid ${c.pillColor}33`,
                        textTransform: "uppercase",
                        letterSpacing: "0.04em",
                        whiteSpace: "nowrap",
                      }}
                      role="status"
                    >
                      {c.pillLabel}
                    </span>
                  )}
                </div>
                <span style={{ fontSize: 11, color: T.slate500 }}>
                  PY{d.payment_year} · {d.sweep_type} · Due {new Date(d.due_date).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
                </span>
              </div>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 2, flexShrink: 0 }}>
                <span
                  style={{
                    fontSize: 13,
                    fontWeight: 700,
                    color: c.text,
                    lineHeight: 1.3,
                    textAlign: "right",
                    whiteSpace: "nowrap",
                  }}
                >
                  {deadlineCountLabel(d.days_remaining)}
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────
// Batches Table
// ─────────────────────────────────────────────

interface BatchesTableProps {
  batches: SubmissionBatch[];
  expandedId: string | null;
  onExpand: (id: string | null) => void;
  onValidate: (id: string) => void;
  onDownload: (id: string) => void;
  onUploadResponse: (id: string, name: string) => void;
  onViewErrors: (id: string) => void;
}

function BatchesTable({
  batches,
  expandedId,
  onExpand,
  onValidate,
  onDownload,
  onUploadResponse,
  onViewErrors,
}: BatchesTableProps) {
  const colHeader: React.CSSProperties = {
    padding: "10px 14px",
    fontSize: 11,
    fontWeight: 700,
    color: T.slate500,
    textTransform: "uppercase",
    letterSpacing: "0.06em",
    textAlign: "left",
    borderBottom: `2px solid ${T.slate200}`,
    background: `linear-gradient(180deg, ${T.slate50} 0%, ${T.white} 100%)`,
    whiteSpace: "nowrap",
  };

  const cell: React.CSSProperties = {
    padding: "14px 14px",
    fontSize: 13,
    color: T.slate700,
    borderBottom: `1px solid ${T.slate100}`,
    verticalAlign: "middle",
    transition: "background-color 0.15s ease",
  };

  if (batches.length === 0) {
    return (
      <div
        className="premium-card"
        style={{
          padding: 48,
          textAlign: "center",
        }}
      >
        <div>
          <EmptyState
            icon={<Send size={28} />}
            title="No CMS submission batches yet — this is unusual"
            description="CMS submissions are required for MA plan payment. Verify the submission pipeline is running and generate your first batch above."
          />
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        overflow: "hidden",
      }}
    >
      <div style={{ overflowX: "auto" }}>
        <table aria-label="CMS submission batches" style={{ width: "100%", borderCollapse: "collapse", minWidth: 900 }}>
          <thead>
            <tr>
              <th scope="col" style={{ ...colHeader, width: 40 }}><span className="sr-only">Expand</span></th>
              <th scope="col" style={colHeader}>Batch ID</th>
              <th scope="col" style={colHeader}>Type</th>
              <th scope="col" style={colHeader}>PY</th>
              <th scope="col" style={colHeader}>Sweep</th>
              <th scope="col" style={{ ...colHeader, textAlign: "right" }}>Records</th>
              <th scope="col" style={colHeader}>Status</th>
              <th scope="col" style={colHeader}>Submitted</th>
              <th scope="col" style={colHeader}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {batches.map((b) => {
              const isExpanded = expandedId === b.id;
              const acceptPct = b.total_records > 0 ? Math.round((b.accepted_records / b.total_records) * 100) : 0;

              return (
                <React.Fragment key={b.id}>
                  <tr className="sub-table-row" style={{ backgroundColor: isExpanded ? T.blue50 : "transparent", animationDelay: `${0.03 * batches.indexOf(b)}s` }}>
                    {/* Expand toggle */}
                    <td style={{ ...cell, padding: "12px 8px 12px 14px" }}>
                      <button
                        onClick={() => onExpand(isExpanded ? null : b.id)}
                        style={{
                          width: 24,
                          height: 24,
                          borderRadius: 6,
                          border: `1px solid ${T.slate200}`,
                          background: T.white,
                          cursor: "pointer",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          color: T.slate500,
                          flexShrink: 0,
                        }}
                        aria-label={isExpanded ? "Collapse row" : "Expand row"}
                        aria-expanded={isExpanded}
                      >
                        {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                      </button>
                    </td>

                    {/* Batch ID */}
                    <td style={cell}>
                      <span style={{ fontFamily: "monospace", fontWeight: 700, color: T.slate800, fontSize: 13 }}>
                        {b.batch_id}
                      </span>
                    </td>

                    {/* Type */}
                    <td style={cell}><TypeBadge type={b.submission_type} /></td>

                    {/* PY */}
                    <td style={{ ...cell, fontWeight: 600 }}>PY{b.payment_year}</td>

                    {/* Sweep */}
                    <td style={{ ...cell, fontSize: 12, color: T.slate600 }}>{b.sweep_type}</td>

                    {/* Records */}
                    <td style={{ ...cell, textAlign: "right" }}>
                      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 3 }}>
                        <span style={{ fontWeight: 700, color: T.slate800 }}>
                          {b.total_records?.toLocaleString() ?? "0"}
                        </span>
                        <div style={{ display: "flex", gap: 8, fontSize: 11 }}>
                          <span style={{ color: T.emerald600 }}>
                            {b.accepted_records?.toLocaleString() ?? "0"} acc
                          </span>
                          {b.rejected_records > 0 && (
                            <span style={{ color: T.red500 }}>
                              {b.rejected_records?.toLocaleString() ?? "0"} rej
                            </span>
                          )}
                        </div>
                        {b.total_records > 0 && (
                          <div
                            style={{
                              height: 3,
                              width: 72,
                              borderRadius: 2,
                              backgroundColor: T.slate200,
                              overflow: "hidden",
                            }}
                          >
                            <div
                              style={{
                                height: "100%",
                                width: `${acceptPct}%`,
                                borderRadius: 2,
                                backgroundColor: acceptPct >= 90 ? T.emerald500 : acceptPct >= 70 ? T.amber500 : T.red500,
                                transition: "width 0.4s ease",
                              }}
                            />
                          </div>
                        )}
                      </div>
                    </td>

                    {/* Status */}
                    <td style={cell}><StatusBadge status={b.status} /></td>

                    {/* Submitted Date */}
                    <td style={{ ...cell, fontSize: 12, color: T.slate500 }}>
                      {b.submitted_at
                        ? new Date(b.submitted_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
                        : <span className="text-muted-foreground">—</span>}
                    </td>

                    {/* Actions */}
                    <td style={cell}>
                      <div style={{ display: "flex", gap: 4 }}>
                        <ActionButton
                          icon={<ShieldCheck size={13} />}
                          label="Validate"
                          onClick={() => onValidate(b.id)}
                        />
                        <ActionButton
                          icon={<Download size={13} />}
                          label="Download"
                          onClick={() => onDownload(b.id)}
                        />
                        <ActionButton
                          icon={<Upload size={13} />}
                          label="Upload Response"
                          onClick={() => onUploadResponse(b.id, b.batch_id)}
                        />
                        {(b.validation_errors > 0 || b.rejected_records > 0) && (
                          <ActionButton
                            icon={<AlertCircle size={13} />}
                            label="View Errors"
                            onClick={() => onViewErrors(b.id)}
                            color={T.red600}
                          />
                        )}
                      </div>
                    </td>
                  </tr>

                  {/* Expanded detail */}
                  {isExpanded && (
                    <tr>
                      <td colSpan={9} style={{ padding: "0 16px 16px", backgroundColor: T.slate50 }}>
                        <LazyBatchDetailPanel
                          batchId={b.id}
                          onClose={() => onExpand(null)}
                          onUploadResponse={onUploadResponse}
                        />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ActionButton({
  icon,
  label,
  onClick,
  color = T.slate600,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  color?: string;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <button
      onClick={onClick}
      title={label}
      aria-label={label}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 4,
        padding: "5px 10px",
        borderRadius: 6,
        border: `1px solid ${hovered ? color + "66" : T.slate200}`,
        backgroundColor: hovered ? color + "0F" : T.white,
        color: hovered ? color : T.slate500,
        cursor: "pointer",
        fontSize: 11,
        fontWeight: 600,
        transition: "all 0.18s ease",
        whiteSpace: "nowrap",
        transform: hovered ? "translateY(-1px)" : "none",
        boxShadow: hovered ? `0 2px 8px ${color}20` : "none",
      }}
    >
      {icon}
      <span className="hidden xl:inline">{label}</span>
    </button>
  );
}

// ─────────────────────────────────────────────
// Main Page
// ─────────────────────────────────────────────

export default function SubmissionsPage() {
  const queryClient = useQueryClient();
  const [showGenerate, setShowGenerate] = useState(false);
  const [expandedBatch, setExpandedBatch] = useState<string | null>(null);
  const [uploadTarget, setUploadTarget] = useState<{ id: string; name: string } | null>(null);
  const [filterType, setFilterType] = useState<SubmissionType | "ALL">("ALL");
  const [filterStatus, setFilterStatus] = useState<BatchStatus | "ALL">("ALL");

  const statsQuery = useQuery({ queryKey: ["submissions-stats"], queryFn: fetchStats });
  const batchesQuery = useQuery({ queryKey: ["submissions-batches"], queryFn: fetchBatches });
  const deadlinesQuery = useQuery({ queryKey: ["submissions-deadlines"], queryFn: fetchDeadlines });

  // batchesQuery error is surfaced at the top level since it's the primary data.
  // Stats and deadlines have their own inline error states.
  const queryError = batchesQuery.isError;

  // Normalize API response — upcoming_deadlines arrives as an array of objects,
  // records_submitted is total_records, pending_validation is total_invalid.
  const rawStats = statsQuery.data as Record<string, unknown> | undefined;
  const stats = {
    total_batches: (rawStats?.total_batches as number) ?? 0,
    records_submitted: (rawStats?.records_submitted as number) ?? (rawStats?.total_records as number) ?? 0,
    acceptance_rate: (rawStats?.acceptance_rate as number) ?? 0,
    pending_validation: (rawStats?.pending_validation as number) ?? (rawStats?.total_invalid as number) ?? 0,
    upcoming_deadlines: Array.isArray(rawStats?.upcoming_deadlines)
      ? (rawStats!.upcoming_deadlines as unknown[]).length
      : (rawStats?.upcoming_deadlines as number) ?? 0,
  };
  const deadlines = deadlinesQuery.data ?? [];

  const batches = useMemo(() => {
    const all = batchesQuery.data ?? [];
    return all.filter((b) => {
      if (filterType !== "ALL" && b.submission_type !== filterType) return false;
      if (filterStatus !== "ALL" && b.status !== filterStatus) return false;
      return true;
    });
  }, [batchesQuery.data, filterType, filterStatus]);

  function handleRefresh() {
    queryClient.invalidateQueries({ queryKey: ["submissions-stats"] });
    queryClient.invalidateQueries({ queryKey: ["submissions-batches"] });
  }

  function handleValidate(id: string) {
    queryClient.invalidateQueries({ queryKey: ["submission-batch-detail", id] });
  }

  function handleDownload(id: string) {
    window.open(`/api/submissions/batches/${id}/download`, "_blank");
  }

  function handleViewErrors(id: string) {
    setExpandedBatch(id);
    // Switch to validation tab is handled inside the panel
  }

  const pageStyle: React.CSSProperties = {
    minHeight: "100vh",
    backgroundColor: T.slate50,
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  };

  const contentStyle: React.CSSProperties = {
    padding: "28px 28px 48px",
    maxWidth: 1440,
    margin: "0 auto",
  };

  const filterBtnStyle = (active: boolean): React.CSSProperties => ({
    padding: "5px 12px",
    borderRadius: 6,
    border: `1px solid ${active ? T.blue600 : T.slate200}`,
    backgroundColor: active ? T.blue50 : T.white,
    color: active ? T.blue700 : T.slate500,
    fontWeight: 600,
    fontSize: 12,
    cursor: "pointer",
    transition: "all 0.1s",
  });

  return (
    <div style={pageStyle}>
      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes fadeInUp { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        .sub-fade-in { animation: fadeIn 0.4s ease-out both; }
        .sub-fade-up-1 { animation: fadeInUp 0.45s ease-out 0.05s both; }
        .sub-fade-up-2 { animation: fadeInUp 0.45s ease-out 0.12s both; }
        .sub-fade-up-3 { animation: fadeInUp 0.45s ease-out 0.2s both; }
        .sub-table-row { animation: fadeInUp 0.35s ease-out both; }
        .sub-table-row:hover { background-color: ${T.slate50} !important; }
        .sub-gradient-btn { background: linear-gradient(135deg, ${T.blue600} 0%, ${T.blue700} 100%); box-shadow: 0 2px 8px rgba(37,99,235,0.35); transition: all 0.2s ease; }
        .sub-gradient-btn:hover { box-shadow: 0 4px 16px rgba(37,99,235,0.45); transform: translateY(-1px); }
        .sub-outline-btn { transition: all 0.18s ease; }
        .sub-outline-btn:hover { border-color: ${T.blue500}; color: ${T.blue600}; background-color: ${T.blue50}; }
        @media (max-width: 640px) { .rci-page-pad-desktop { padding: 20px 16px !important; } }
        button:focus-visible { outline: 2px solid ${T.blue600}; outline-offset: 2px; border-radius: 4px; }
      `}</style>

      {queryError && (
        <div
          style={{
            margin: "16px 28px 0",
            padding: "12px 16px",
            borderRadius: 10,
            border: `1px solid ${T.red500}40`,
            backgroundColor: T.red50,
            color: T.red600,
            fontSize: 13,
            fontWeight: 600,
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 8,
          }}
          role="alert"
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <AlertCircle size={15} style={{ flexShrink: 0 }} />
            <span>
              {(batchesQuery.error as any)?.response?.data?.detail ??
                (batchesQuery.error as any)?.message ??
                "Failed to load submission batches."}
            </span>
          </div>
          <button
            onClick={() => batchesQuery.refetch()}
            style={{
              padding: "4px 12px",
              borderRadius: 6,
              border: `1px solid ${T.red500}40`,
              backgroundColor: T.white,
              color: T.red600,
              fontWeight: 600,
              fontSize: 12,
              cursor: "pointer",
              flexShrink: 0,
            }}
          >
            Retry
          </button>
        </div>
      )}

      <div style={contentStyle} className="rci-page-pad-desktop">
        {/* Data quality banner — degraded data on a compliance page is a critical signal */}
        <DataQualityBanner />

        {/* Page Header */}
        <PageHeader
          title="CMS Submissions"
          subtitle="Manage RAPS and EDPS submissions to the Centers for Medicare & Medicaid Services"
          icon={<Send size={22} />}
          actions={
            <div style={{ display: "flex", gap: 8 }}>
              <button
                onClick={handleRefresh}
                className="sub-outline-btn"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "8px 14px",
                  borderRadius: 8,
                  border: `1px solid ${T.slate200}`,
                  backgroundColor: T.white,
                  color: T.slate600,
                  fontWeight: 600,
                  fontSize: 13,
                  cursor: "pointer",
                }}
                aria-label="Refresh data"
              >
                <RefreshCw size={14} />
                Refresh
              </button>
              <button
                onClick={() => setShowGenerate(true)}
                className="sub-gradient-btn"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  padding: "8px 16px",
                  borderRadius: 8,
                  border: "none",
                  color: T.white,
                  fontWeight: 700,
                  fontSize: 13,
                  cursor: "pointer",
                }}
              >
                <Send size={14} />
                Generate Submission
              </button>
            </div>
          }
        />

        {/* Stats Row */}
        <div
          className="sub-fade-up-1"
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: 16,
            marginBottom: 24,
          }}
        >
          {statsQuery.isLoading ? (
            Array.from({ length: 5 }).map((_, i) => (
              <div
                key={i}
                style={{
                  backgroundColor: T.white,
                  border: `1px solid ${T.slate200}`,
                  borderRadius: 10,
                  padding: "20px 20px",
                  display: "flex",
                  flexDirection: "column",
                  gap: 10,
                }}
                aria-hidden="true"
              >
                <div style={{ height: 12, width: "60%", borderRadius: 6, backgroundColor: T.slate100 }} />
                <div style={{ height: 28, width: "40%", borderRadius: 6, backgroundColor: T.slate100 }} />
                <div style={{ height: 10, width: "80%", borderRadius: 6, backgroundColor: T.slate100 }} />
              </div>
            ))
          ) : statsQuery.isError ? (
            <div
              style={{
                gridColumn: "1 / -1",
                backgroundColor: T.red50,
                border: `1px solid ${T.red500}40`,
                borderRadius: 10,
                padding: "12px 16px",
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
              role="alert"
            >
              <AlertCircle size={15} style={{ color: T.red600 }} />
              <span style={{ fontSize: 13, color: T.red600, fontWeight: 600 }}>
                Failed to load submission statistics.
              </span>
            </div>
          ) : (
            <>
              <MetricCard
                label="Total Batches"
                value={stats.total_batches}
                icon={<FileText size={18} />}
                subtitle="All submission batches"
              />
              <MetricCard
                label="Records Submitted"
                value={stats.records_submitted?.toLocaleString() ?? "0"}
                icon={<Send size={18} />}
                intent="success"
                subtitle="Across all batches"
              />
              <MetricCard
                label="Acceptance Rate"
                value={`${(stats.acceptance_rate ?? 0).toFixed(1)}%`}
                icon={<CheckCircle size={18} />}
                intent="success"
                subtitle="CMS accepted records"
                delta={1.2}
              />
              <MetricCard
                label="Pending Validation"
                value={stats.pending_validation}
                icon={<Clock size={18} />}
                intent="warning"
                subtitle="Awaiting validation run"
              />
              <MetricCard
                label="Upcoming Deadlines"
                value={stats.upcoming_deadlines}
                icon={<Calendar size={18} />}
                intent={deadlines.some((d) => d.days_remaining < 7) ? "danger" : "warning"}
                subtitle="Within 30 days"
              />
            </>
          )}
        </div>

        {/* Deadlines Banner */}
        {deadlinesQuery.isLoading ? (
          <div style={{ display: "flex", gap: 10, marginBottom: 24, flexWrap: "wrap" }}>
            {Array.from({ length: 3 }).map((_, i) => (
              <div
                key={i}
                style={{
                  flex: "1 1 260px",
                  height: 70,
                  borderRadius: 10,
                  backgroundColor: T.slate100,
                }}
                aria-hidden="true"
              />
            ))}
          </div>
        ) : deadlinesQuery.isError ? (
          <div
            style={{
              marginBottom: 24,
              padding: "12px 16px",
              borderRadius: 10,
              border: `1px solid ${T.amber500}40`,
              backgroundColor: T.amber50,
              display: "flex",
              alignItems: "center",
              gap: 8,
            }}
            role="alert"
          >
            <AlertTriangle size={15} style={{ color: T.amber600 }} />
            <span style={{ fontSize: 13, color: T.amber600, fontWeight: 600 }}>
              Could not load submission deadlines.
            </span>
          </div>
        ) : deadlines.length > 0 ? (
          <DeadlinesBanner deadlines={deadlines} />
        ) : null}

        {/* Batches section */}
        <div
          className="premium-card sub-fade-up-3"
          style={{
            overflow: "hidden",
          }}
        >
          {/* Table header & filters */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              padding: "16px 20px",
              borderBottom: `1px solid ${T.slate200}`,
              gap: 12,
              flexWrap: "wrap",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <BarChart2 size={16} style={{ color: T.blue600 }} />
              <span style={{ fontSize: 15, fontWeight: 700, color: T.slate900 }}>
                Submission Batches
              </span>
              <span
                style={{
                  padding: "2px 8px",
                  borderRadius: 999,
                  fontSize: 11,
                  fontWeight: 600,
                  backgroundColor: `${T.blue600}1A`,
                  color: T.blue600,
                }}
              >
                {batches.length}
              </span>
            </div>

            {/* Filters */}
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {/* Type filter */}
              <div style={{ display: "flex", gap: 4 }}>
                {(["ALL", "RAPS", "EDPS"] as const).map((t) => (
                  <button key={t} style={filterBtnStyle(filterType === t)} onClick={() => setFilterType(t)}>
                    {t}
                  </button>
                ))}
              </div>

              <div style={{ width: 1, backgroundColor: T.slate200 }} />

              {/* Status filter */}
              <select
                value={filterStatus}
                onChange={(e) => setFilterStatus(e.target.value as BatchStatus | "ALL")}
                style={{
                  padding: "5px 10px",
                  borderRadius: 6,
                  border: `1px solid ${T.slate200}`,
                  fontSize: 12,
                  color: T.slate600,
                  backgroundColor: T.white,
                  cursor: "pointer",
                }}
              >
                <option value="ALL">All Statuses</option>
                <option value="draft">Draft</option>
                <option value="validating">Validating</option>
                <option value="validated">Validated</option>
                <option value="submitted">Submitted</option>
                <option value="accepted">Accepted</option>
                <option value="rejected">Rejected</option>
                <option value="partial">Partial Accept</option>
                <option value="error">Error</option>
              </select>
            </div>
          </div>

          {/* Loading / error / data state */}
          {batchesQuery.isLoading ? (
            <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 8 }}>
              {Array.from({ length: 4 }).map((_, i) => (
                <div
                  key={i}
                  style={{
                    height: 52,
                    borderRadius: 8,
                    backgroundColor: T.slate100,
                  }}
                  aria-hidden="true"
                />
              ))}
            </div>
          ) : batchesQuery.isError ? (
            <div
              style={{
                padding: 48,
                textAlign: "center",
                color: T.slate400,
              }}
            >
              <AlertCircle size={32} style={{ color: T.red500, marginBottom: 12, opacity: 0.6 }} />
              <p style={{ margin: "0 0 4px", fontSize: 14, fontWeight: 600, color: T.slate600 }}>
                Could not load submission batches
              </p>
              <p style={{ margin: "0 0 16px", fontSize: 13, color: T.slate400 }}>
                Check your connection and try again.
              </p>
              <button
                onClick={() => batchesQuery.refetch()}
                style={{
                  padding: "8px 20px",
                  borderRadius: 8,
                  border: `1px solid ${T.slate200}`,
                  backgroundColor: T.white,
                  color: T.slate600,
                  fontWeight: 600,
                  fontSize: 13,
                  cursor: "pointer",
                }}
              >
                Retry
              </button>
            </div>
          ) : (
            <BatchesTable
              batches={batches}
              expandedId={expandedBatch}
              onExpand={setExpandedBatch}
              onValidate={handleValidate}
              onDownload={handleDownload}
              onUploadResponse={(id, name) => setUploadTarget({ id, name })}
              onViewErrors={handleViewErrors}
            />
          )}
        </div>
      </div>

      {/* Generate Submission Dialog */}
      {showGenerate && (
        <LazyGenerateDialog
          onClose={() => setShowGenerate(false)}
          onSuccess={() => {
            queryClient.invalidateQueries({ queryKey: ["submissions-batches"] });
            queryClient.invalidateQueries({ queryKey: ["submissions-stats"] });
          }}
        />
      )}

      {/* Upload Response Dialog */}
      {uploadTarget && (
        <LazyUploadResponseDialog
          batchId={uploadTarget.id}
          batchName={uploadTarget.name}
          onClose={() => setUploadTarget(null)}
          onSuccess={() => {
            queryClient.invalidateQueries({ queryKey: ["submission-batch-detail", uploadTarget.id] });
          }}
        />
      )}
    </div>
  );
}
