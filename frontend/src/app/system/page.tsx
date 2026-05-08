"use client";

import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { authApi } from "@/contexts/auth-context";
import { tokens } from "@/styles/tokens";
import {
  Activity,
  Database,
  Cpu,
  RefreshCw,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Users,
  Clock,
  Shield,
  Server,
  Wifi,
  Brain,
  CalendarClock,
  Trash2,
  KeyRound,
} from "lucide-react";
import {
  StatCard,
  PageHeader,
  SectionHeader,
} from "@/components/healthcare-ui";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface HealthResponse {
  status: "healthy" | "degraded";
  request_id: string | null;
  databases: Record<string, boolean>;
  gemini_model: string;
  sync_scheduler: {
    running: boolean;
    check_interval_seconds: number;
    retention_check_interval_hours: number;
    last_retention_sweep: string | null;
  };
  monitoring: Record<string, unknown>;
}

interface AuditEntry {
  id: number;
  user_id: number | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  patient_id: number | null;
  ip_address: string | null;
  request_method: string | null;
  request_path: string | null;
  response_status: number | null;
  details: string | null;
  created_at: string;
}

interface RetentionPolicy {
  table_name: string;
  retention_days: number;
  total_rows: number;
  oldest_record: string | null;
  eligible_for_purge: number;
}

interface JwtKeyStatus {
  algorithm: string;
  last_rotated: string | null;
  rotation_due: string | null;
  status: "ok" | "due" | "overdue";
}

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function fetchHealth(): Promise<HealthResponse> {
  const { data } = await api.get("/health");
  return data;
}

async function fetchUsers(): Promise<{ total: number; active: number }> {
  try {
    const { data } = await authApi.get("/api/auth/users");
    const users = Array.isArray(data) ? data : (data?.users ?? []);
    return {
      total: users.length,
      active: users.filter((u: { is_active?: boolean }) => u.is_active).length,
    };
  } catch {
    return { total: 0, active: 0 };
  }
}

async function fetchAuditLog(): Promise<AuditEntry[]> {
  const { data } = await authApi.get("/api/auth/audit-log", {
    params: { limit: 20 },
  });
  return Array.isArray(data) ? data : (data?.rows ?? data?.entries ?? []);
}

async function fetchRetention(): Promise<RetentionPolicy[]> {
  try {
    const { data } = await authApi.get("/api/admin/retention");
    return Array.isArray(data) ? data : (data?.policies ?? data?.tables ?? []);
  } catch {
    return [];
  }
}

async function fetchJwtKeyStatus(): Promise<JwtKeyStatus | null> {
  try {
    const { data } = await authApi.get("/api/admin/jwt-key-status");
    return data;
  } catch (err: unknown) {
    // Silently ignore 404 — endpoint may not be provisioned yet
    const status = (err as { response?: { status?: number } })?.response?.status;
    if (status !== 404) {
      console.warn("jwt-key-status fetch failed:", status);
    }
    return null;
  }
}

// ---------------------------------------------------------------------------
// Skeleton row helper
// ---------------------------------------------------------------------------

function SkeletonRow({ cols }: { cols: number }) {
  return (
    <tr>
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} style={{ padding: "10px 14px" }}>
          <div
            className="skeleton"
            style={{ height: 12, borderRadius: 4, width: i === 0 ? 140 : 80 }}
          />
        </td>
      ))}
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Status indicator
// ---------------------------------------------------------------------------

function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 0" }}>
      <span
        style={{
          width: 10,
          height: 10,
          borderRadius: "50%",
          backgroundColor: ok ? tokens.riskLow : tokens.riskHigh,
          flexShrink: 0,
          boxShadow: ok
            ? `0 0 8px ${tokens.riskLow}80`
            : `0 0 8px ${tokens.riskHigh}80`,
        }}
      />
      <span style={{ fontSize: 14, fontWeight: 500 }}>{label}</span>
      <span
        style={{
          marginLeft: "auto",
          fontSize: 12,
          fontWeight: 600,
          color: ok ? tokens.riskLow : tokens.riskHigh,
        }}
      >
        {ok ? "Connected" : "Down"}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Card wrapper
// ---------------------------------------------------------------------------

function ServiceCard({ children, title, icon }: { children: React.ReactNode; title: string; icon?: React.ReactNode }) {
  return (
    <div
      style={{
        padding: 20,
        borderRadius: 12,
        border: `1px solid ${tokens.slate200}`,
        background: tokens.white,
      }}
    >
      {(title || icon) && (
        <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
          {icon}
          {title}
        </div>
      )}
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function SystemHealthPage() {
  const [refetchKey, setRefetchKey] = useState(0);

  const { data: health, isLoading: healthLoading, isError: healthError, error: healthRawError, refetch: refetchHealth } = useQuery({
    queryKey: ["system-health", refetchKey],
    queryFn: fetchHealth,
    refetchInterval: 30_000,
    retry: 1,
  });

  const { data: userStats } = useQuery({
    queryKey: ["system-users"],
    queryFn: fetchUsers,
    refetchInterval: 60_000,
    retry: 1,
  });

  const { data: auditLog, isLoading: auditLoading } = useQuery({
    queryKey: ["system-audit"],
    queryFn: fetchAuditLog,
    refetchInterval: 30_000,
    retry: 1,
  });

  const { data: retention, isLoading: retentionLoading } = useQuery({
    queryKey: ["system-retention"],
    queryFn: fetchRetention,
    refetchInterval: 120_000,
    retry: 1,
  });

  const { data: jwtStatus } = useQuery({
    queryKey: ["system-jwt-status"],
    queryFn: fetchJwtKeyStatus,
    refetchInterval: 300_000,
    retry: 1,
  });

  const handleRefresh = () => {
    setRefetchKey((k) => k + 1);
    refetchHealth();
  };

  const overallStatus = healthError ? "error" : health?.status === "healthy" ? "healthy" : "degraded";

  // Distinguish 403 vs 5xx error
  const healthHttpStatus = (healthRawError as { response?: { status?: number } } | null | undefined)?.response?.status;
  const isPermDenied = healthHttpStatus === 403;

  // Count total errors from monitoring stats — only scalar numeric values
  const totalErrors = health?.monitoring
    ? Object.entries(health.monitoring).reduce((sum, [, v]) => sum + (typeof v === "number" ? v : 0), 0)
    : 0;

  // Database degraded?
  const hasDbFailure = health?.databases
    ? Object.values(health.databases).some((ok) => !ok)
    : false;

  const showDegradedBanner = !healthLoading && (overallStatus === "degraded" || overallStatus === "error" || hasDbFailure);

  return (
    <div style={{ padding: "20px 16px", maxWidth: 1400 }} className="rci-page-pad-desktop">
      <PageHeader
        title="System Health"
        subtitle="Monitor services, databases, and system activity"
        icon={<Activity style={{ width: 24, height: 24 }} />}
        actions={
          <button
            onClick={handleRefresh}
            aria-label="Refresh system health"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "8px 16px",
              fontSize: 13,
              fontWeight: 500,
              borderRadius: 8,
              border: `1px solid ${tokens.slate200}`,
              background: tokens.white,
              color: tokens.slate900,
              cursor: "pointer",
            }}
          >
            <RefreshCw style={{ width: 14, height: 14 }} />
            Refresh
          </button>
        }
      />

      {/* ── Degraded / offline red banner ── */}
      {showDegradedBanner && (
        <div
          role="alert"
          style={{
            marginTop: 16,
            padding: "14px 20px",
            borderRadius: 10,
            display: "flex",
            alignItems: "flex-start",
            gap: 12,
            fontSize: 14,
            fontWeight: 600,
            backgroundColor: tokens.dangerSoft,
            border: `1px solid ${tokens.dangerBorder}`,
            color: tokens.danger,
          }}
        >
          <AlertTriangle style={{ width: 18, height: 18, flexShrink: 0, marginTop: 1 }} />
          <div>
            {isPermDenied
              ? "Permission denied (403) — you need admin access to view system health details."
              : overallStatus === "error"
              ? "Unable to reach backend API (server error). Check that the backend service is running."
              : hasDbFailure
              ? "One or more database connections are down. Data ingestion and RAF analysis may be impaired."
              : "System is degraded — some services are unavailable. Review the service health panel below."}
          </div>
        </div>
      )}

      {/* ── Overall status banner ── */}
      <div
        style={{
          marginTop: showDegradedBanner ? 12 : 20,
          padding: "14px 20px",
          borderRadius: 12,
          display: "flex",
          alignItems: "center",
          gap: 12,
          fontSize: 15,
          fontWeight: 600,
          background: overallStatus === "healthy"
            ? `linear-gradient(135deg, ${tokens.successSoft}, rgba(16,185,129,0.04))`
            : overallStatus === "degraded"
              ? `linear-gradient(135deg, ${tokens.warningSoft}, rgba(217,119,6,0.04))`
              : `linear-gradient(135deg, ${tokens.dangerSoft}, rgba(220,38,38,0.04))`,
          border: `1px solid ${overallStatus === "healthy" ? `${tokens.riskLow}33` : overallStatus === "degraded" ? `${tokens.warningStrong}33` : `${tokens.riskHigh}33`}`,
        }}
      >
        {healthLoading ? (
          <RefreshCw style={{ width: 18, height: 18, animation: "spin 1s linear infinite" }} />
        ) : overallStatus === "healthy" ? (
          <CheckCircle style={{ width: 18, height: 18, color: tokens.riskLow }} />
        ) : overallStatus === "degraded" ? (
          <AlertTriangle style={{ width: 18, height: 18, color: tokens.warningStrong }} />
        ) : (
          <XCircle style={{ width: 18, height: 18, color: tokens.riskHigh }} />
        )}
        <span>
          {healthLoading
            ? "Checking system health..."
            : overallStatus === "healthy"
              ? "All systems operational"
              : overallStatus === "degraded"
                ? "System degraded — some services unavailable"
                : isPermDenied
                  ? "Permission denied (403) — insufficient privileges"
                  : "Unable to reach backend API (server error 5xx)"}
        </span>
      </div>

      {/* ── KPI cards ── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: 16,
          marginTop: 24,
        }}
      >
        <StatCard
          label="System Status"
          value={healthLoading ? "..." : overallStatus === "healthy" ? "Healthy" : overallStatus === "degraded" ? "Degraded" : "Offline"}
          icon={<Server style={{ width: 20, height: 20 }} />}
          color={overallStatus === "healthy" ? tokens.riskLow : overallStatus === "degraded" ? tokens.warningStrong : tokens.riskHigh}
          loading={healthLoading}
        />
        <StatCard
          label="Total Users"
          value={userStats?.total ?? "..."}
          subtitle={`${userStats?.active ?? 0} active`}
          icon={<Users style={{ width: 20, height: 20 }} />}
          color={tokens.riskLow}
        />
        <StatCard
          label="Error Count"
          value={totalErrors}
          subtitle="from monitoring"
          icon={<AlertTriangle style={{ width: 20, height: 20 }} />}
          color={totalErrors > 0 ? tokens.riskHigh : tokens.riskLow}
          loading={healthLoading}
        />
        <StatCard
          label="Last Retention Sweep"
          value={
            health?.sync_scheduler?.last_retention_sweep
              ? new Date(health.sync_scheduler.last_retention_sweep).toLocaleDateString()
              : "Never"
          }
          icon={<Clock style={{ width: 20, height: 20 }} />}
          color={tokens.accentPurple}
          loading={healthLoading}
        />
      </div>

      {/* ── Service Health ── */}
      <div style={{ marginTop: 32 }}>
        <SectionHeader title="Service Health" icon={<Wifi style={{ width: 18, height: 18 }} />} />
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))",
            gap: 16,
            marginTop: 12,
          }}
        >
          {/* Backend API */}
          <ServiceCard title="Backend API" icon={<Server style={{ width: 16, height: 16 }} />}>
            {healthLoading ? (
              <div className="skeleton" style={{ height: 32, borderRadius: 6 }} />
            ) : (
              <StatusDot ok={!healthError && health?.status === "healthy"} label="API Server" />
            )}
          </ServiceCard>

          {/* Database Connections */}
          <ServiceCard title="Database Connections" icon={<Database style={{ width: 16, height: 16 }} />}>
            {healthLoading ? (
              <>
                <div className="skeleton" style={{ height: 28, borderRadius: 6, marginBottom: 8 }} />
                <div className="skeleton" style={{ height: 28, borderRadius: 6 }} />
              </>
            ) : health?.databases ? (
              Object.entries(health.databases).map(([name, ok]) => (
                <StatusDot
                  key={name}
                  ok={ok}
                  label={name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                />
              ))
            ) : (
              <div style={{ fontSize: 13, color: tokens.slate400, padding: "8px 0" }}>
                {healthError ? "Could not retrieve database status." : "No data available"}
              </div>
            )}
          </ServiceCard>

          {/* AI Engine */}
          <ServiceCard title="AI Engine" icon={<Brain style={{ width: 16, height: 16 }} />}>
            {healthLoading ? (
              <div className="skeleton" style={{ height: 28, borderRadius: 6 }} />
            ) : (
              <>
                <StatusDot ok={!!health?.gemini_model} label="AI Engine Active" />
                {health?.gemini_model && (
                  <div style={{ fontSize: 12, color: tokens.slate500, paddingLeft: 20, marginTop: 4 }}>
                    Model: <span style={{ fontWeight: 600 }}>{health.gemini_model}</span>
                  </div>
                )}
              </>
            )}
          </ServiceCard>

          {/* Sync Scheduler */}
          <ServiceCard title="EMR Sync Scheduler" icon={<CalendarClock style={{ width: 16, height: 16 }} />}>
            {healthLoading ? (
              <div className="skeleton" style={{ height: 72, borderRadius: 6 }} />
            ) : (
              <>
                <StatusDot ok={!!health?.sync_scheduler?.running} label="Scheduler Thread" />
                {health?.sync_scheduler && (
                  <div style={{ fontSize: 12, color: tokens.slate500, paddingLeft: 20, marginTop: 4, lineHeight: 1.8 }}>
                    Check interval: <strong>{health.sync_scheduler.check_interval_seconds}s</strong>
                    <br />
                    Retention check: <strong>every {health.sync_scheduler.retention_check_interval_hours}h</strong>
                    <br />
                    Last sweep:{" "}
                    <strong>
                      {health.sync_scheduler.last_retention_sweep
                        ? new Date(health.sync_scheduler.last_retention_sweep).toLocaleString()
                        : "Never"}
                    </strong>
                  </div>
                )}
              </>
            )}
          </ServiceCard>
        </div>
      </div>

      {/* ── JWT Key Rotation Status ── */}
      {(jwtStatus || healthLoading) && (
        <div style={{ marginTop: 32 }}>
          <SectionHeader title="JWT Signing Key" icon={<KeyRound style={{ width: 18, height: 18 }} />} />
          <div
            style={{
              marginTop: 12,
              padding: 20,
              borderRadius: 12,
              border: `1px solid ${jwtStatus?.status === "overdue" ? tokens.dangerBorder : jwtStatus?.status === "due" ? tokens.warningBorder : tokens.slate200}`,
              background: jwtStatus?.status === "overdue" ? tokens.dangerSoft : jwtStatus?.status === "due" ? tokens.warningSoft : tokens.white,
            }}
          >
            {healthLoading ? (
              <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
                {[120, 100, 100].map((w, i) => (
                  <div key={i} className="skeleton" style={{ height: 14, width: w, borderRadius: 4 }} />
                ))}
              </div>
            ) : jwtStatus ? (
              <div style={{ display: "flex", gap: 32, flexWrap: "wrap", fontSize: 13 }}>
                <div>
                  <div style={{ color: tokens.slate400, fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>Algorithm</div>
                  <div style={{ fontWeight: 700, color: tokens.slate900 }}>{jwtStatus.algorithm}</div>
                </div>
                <div>
                  <div style={{ color: tokens.slate400, fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>Last Rotated</div>
                  <div style={{ fontWeight: 600, color: tokens.slate700 }}>
                    {jwtStatus.last_rotated ? new Date(jwtStatus.last_rotated).toLocaleDateString() : "Never"}
                  </div>
                </div>
                <div>
                  <div style={{ color: tokens.slate400, fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>Rotation Due</div>
                  <div style={{ fontWeight: 600, color: jwtStatus.status === "overdue" ? tokens.danger : jwtStatus.status === "due" ? tokens.warningStrong : tokens.riskLow }}>
                    {jwtStatus.rotation_due ? new Date(jwtStatus.rotation_due).toLocaleDateString() : "Not scheduled"}
                  </div>
                </div>
                <div>
                  <div style={{ color: tokens.slate400, fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>Status</div>
                  <div style={{ fontWeight: 700, color: jwtStatus.status === "overdue" ? tokens.danger : jwtStatus.status === "due" ? tokens.warningStrong : tokens.riskLow }}>
                    {jwtStatus.status === "overdue" ? "Rotation Overdue" : jwtStatus.status === "due" ? "Rotation Due Soon" : "Up to Date"}
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        </div>
      )}

      {/* ── Monitoring / Error Stats ── */}
      {health?.monitoring && Object.keys(health.monitoring).length > 0 && (
        <div style={{ marginTop: 32 }}>
          <SectionHeader title="Error Statistics" icon={<AlertTriangle style={{ width: 18, height: 18 }} />} />
          <div
            style={{
              marginTop: 12,
              padding: 20,
              borderRadius: 12,
              border: `1px solid ${tokens.slate200}`,
              background: tokens.white,
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
              gap: 16,
            }}
          >
            {Object.entries(health.monitoring)
              // Only render scalar (number | string | boolean) values — skip nested objects/arrays
              .filter(([, value]) => typeof value !== "object" || value === null)
              .map(([key, value]) => (
                <div key={key} style={{ textAlign: "center" }}>
                  <div style={{ fontSize: 24, fontWeight: 700, color: typeof value === "number" && value > 0 ? tokens.riskHigh : tokens.riskLow }}>
                    {typeof value === "number" ? value : String(value ?? "—")}
                  </div>
                  <div style={{ fontSize: 12, color: tokens.slate500, marginTop: 4 }}>
                    {key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                  </div>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* ── Recent Audit Log — latest 5 events ── */}
      <div style={{ marginTop: 32 }}>
        <SectionHeader
          title="Recent Audit Events"
          icon={<Shield style={{ width: 18, height: 18 }} />}
          count={auditLog ? Math.min(auditLog.length, 5) : undefined}
        />
        <div
          style={{
            marginTop: 12,
            borderRadius: 12,
            border: `1px solid ${tokens.slate200}`,
            background: tokens.white,
            overflow: "auto",
          }}
        >
          {auditLoading ? (
            <table aria-label="Audit log" style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${tokens.slate200}`, textAlign: "left" }}>
                  {["Timestamp", "User", "Action", "Resource", "Path", "Status", "IP"].map((h) => (
                    <th key={h} style={{ padding: "10px 14px", fontWeight: 600, fontSize: 12, textTransform: "uppercase", letterSpacing: "0.04em", color: tokens.slate500, whiteSpace: "nowrap" }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: 5 }).map((_, i) => <SkeletonRow key={i} cols={7} />)}
              </tbody>
            </table>
          ) : !auditLog || auditLog.length === 0 ? (
            <div style={{ padding: 32, textAlign: "center", color: tokens.slate400, fontSize: 14 }}>
              No audit entries found
            </div>
          ) : (
            <table aria-label="Audit log" style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${tokens.slate200}`, textAlign: "left" }}>
                  {["Timestamp", "User", "Action", "Resource", "Path", "Status", "IP"].map((h) => (
                    <th key={h} style={{ padding: "10px 14px", fontWeight: 600, fontSize: 12, textTransform: "uppercase", letterSpacing: "0.04em", color: tokens.slate500, whiteSpace: "nowrap" }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {auditLog.slice(0, 5).map((entry) => (
                  <tr
                    key={entry.id}
                    style={{ borderBottom: `1px solid ${tokens.slate100}` }}
                  >
                    <td style={{ padding: "8px 14px", whiteSpace: "nowrap", color: tokens.slate500, fontSize: 12 }}>
                      {new Date(entry.created_at).toLocaleString()}
                    </td>
                    <td style={{ padding: "8px 14px" }}>
                      {entry.user_id ?? "-"}
                    </td>
                    <td style={{ padding: "8px 14px" }}>
                      <span
                        style={{
                          display: "inline-block",
                          padding: "2px 8px",
                          borderRadius: 4,
                          fontSize: 11,
                          fontWeight: 600,
                          backgroundColor: entry.action?.includes("login")
                            ? `${tokens.riskLow}1A`
                            : entry.action?.includes("error") || entry.action?.includes("fail")
                              ? `${tokens.riskHigh}1A`
                              : `${tokens.accentPurple}1A`,
                          color: entry.action?.includes("login")
                            ? tokens.riskLow
                            : entry.action?.includes("error") || entry.action?.includes("fail")
                              ? tokens.riskHigh
                              : tokens.accentPurple,
                        }}
                      >
                        {entry.action}
                      </span>
                    </td>
                    <td style={{ padding: "8px 14px", fontSize: 12 }}>
                      {entry.resource_type}
                      {entry.resource_id ? ` #${entry.resource_id}` : ""}
                    </td>
                    <td style={{ padding: "8px 14px", fontSize: 12, color: tokens.slate500, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {entry.request_method && entry.request_path
                        ? `${entry.request_method} ${entry.request_path}`
                        : "-"}
                    </td>
                    <td style={{ padding: "8px 14px" }}>
                      {entry.response_status ? (
                        <span
                          style={{
                            fontSize: 12,
                            fontWeight: 600,
                            color: entry.response_status < 400 ? tokens.riskLow : entry.response_status < 500 ? tokens.warningStrong : tokens.riskHigh,
                          }}
                        >
                          {entry.response_status}
                        </span>
                      ) : (
                        "-"
                      )}
                    </td>
                    <td style={{ padding: "8px 14px", fontSize: 12, color: tokens.slate400 }}>
                      {entry.ip_address ?? "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* ── Data Retention Status ── */}
      <div style={{ marginTop: 32, marginBottom: 48 }}>
        <SectionHeader
          title="Data Retention Policies"
          icon={<Trash2 style={{ width: 18, height: 18 }} />}
          count={retention?.length}
        />
        <div
          style={{
            marginTop: 12,
            borderRadius: 12,
            border: `1px solid ${tokens.slate200}`,
            background: tokens.white,
            overflow: "auto",
          }}
        >
          {retentionLoading ? (
            <table aria-label="Data retention policies" style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${tokens.slate200}`, textAlign: "left" }}>
                  {["Table", "Retention Period", "Total Rows", "Oldest Record", "Eligible for Purge"].map((h) => (
                    <th key={h} style={{ padding: "10px 14px", fontWeight: 600, fontSize: 12, textTransform: "uppercase", letterSpacing: "0.04em", color: tokens.slate500, whiteSpace: "nowrap" }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Array.from({ length: 4 }).map((_, i) => <SkeletonRow key={i} cols={5} />)}
              </tbody>
            </table>
          ) : !retention || retention.length === 0 ? (
            <div style={{ padding: 32, textAlign: "center", color: tokens.slate400, fontSize: 14 }}>
              No retention policies configured
            </div>
          ) : (
            <table aria-label="Data retention policies" style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${tokens.slate200}`, textAlign: "left" }}>
                  {["Table", "Retention Period", "Total Rows", "Oldest Record", "Eligible for Purge"].map((h) => (
                    <th key={h} style={{ padding: "10px 14px", fontWeight: 600, fontSize: 12, textTransform: "uppercase", letterSpacing: "0.04em", color: tokens.slate500, whiteSpace: "nowrap" }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {retention.map((policy, i) => (
                  <tr key={policy.table_name ?? i} style={{ borderBottom: `1px solid ${tokens.slate100}` }}>
                    <td style={{ padding: "8px 14px", fontWeight: 500 }}>
                      {policy.table_name}
                    </td>
                    <td style={{ padding: "8px 14px" }}>
                      {policy.retention_days} days
                    </td>
                    <td style={{ padding: "8px 14px" }}>
                      {policy.total_rows?.toLocaleString() ?? "-"}
                    </td>
                    <td style={{ padding: "8px 14px", fontSize: 12, color: tokens.slate500 }}>
                      {policy.oldest_record ? new Date(policy.oldest_record).toLocaleDateString() : "-"}
                    </td>
                    <td style={{ padding: "8px 14px" }}>
                      <span
                        style={{
                          fontWeight: 600,
                          color: policy.eligible_for_purge > 0 ? tokens.warningStrong : tokens.riskLow,
                        }}
                      >
                        {policy.eligible_for_purge?.toLocaleString() ?? 0}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Spin animation for refresh icon */}
      <style>{`
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
