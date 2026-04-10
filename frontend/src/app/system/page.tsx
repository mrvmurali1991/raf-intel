"use client";

import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { authApi } from "@/contexts/auth-context";
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
  Eye,
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
  monitoring: Record<string, number>;
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
      active: users.filter((u: any) => u.is_active).length,
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
          backgroundColor: ok ? "#22c55e" : "#ef4444",
          flexShrink: 0,
          boxShadow: ok ? "0 0 8px rgba(34,197,94,0.5)" : "0 0 8px rgba(239,68,68,0.5)",
        }}
      />
      <span style={{ fontSize: 14, fontWeight: 500 }}>{label}</span>
      <span
        style={{
          marginLeft: "auto",
          fontSize: 12,
          fontWeight: 600,
          color: ok ? "#22c55e" : "#ef4444",
        }}
      >
        {ok ? "Connected" : "Down"}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function SystemHealthPage() {
  const [refetchKey, setRefetchKey] = useState(0);

  const { data: health, isLoading: healthLoading, isError: healthError, refetch: refetchHealth } = useQuery({
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

  const handleRefresh = () => {
    setRefetchKey((k) => k + 1);
    refetchHealth();
  };

  const overallStatus = healthError ? "error" : health?.status === "healthy" ? "healthy" : "degraded";

  // Count total errors from monitoring stats
  const totalErrors = health?.monitoring
    ? Object.values(health.monitoring).reduce((sum, v) => sum + (typeof v === "number" ? v : 0), 0)
    : 0;

  return (
    <div style={{ padding: "24px 32px", maxWidth: 1400 }}>
      <PageHeader
        title="System Health"
        subtitle="Monitor services, databases, and system activity"
        icon={<Activity style={{ width: 24, height: 24 }} />}
        actions={
          <button
            onClick={handleRefresh}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "8px 16px",
              fontSize: 13,
              fontWeight: 500,
              borderRadius: 8,
              border: "1px solid var(--border, #e2e8f0)",
              background: "var(--card, #fff)",
              color: "var(--foreground, #0f172a)",
              cursor: "pointer",
            }}
          >
            <RefreshCw style={{ width: 14, height: 14 }} />
            Refresh
          </button>
        }
      />

      {/* ── Overall status banner ── */}
      <div
        style={{
          marginTop: 20,
          padding: "14px 20px",
          borderRadius: 12,
          display: "flex",
          alignItems: "center",
          gap: 12,
          fontSize: 15,
          fontWeight: 600,
          background: overallStatus === "healthy"
            ? "linear-gradient(135deg, rgba(34,197,94,0.08), rgba(16,185,129,0.04))"
            : overallStatus === "degraded"
              ? "linear-gradient(135deg, rgba(245,158,11,0.08), rgba(217,119,6,0.04))"
              : "linear-gradient(135deg, rgba(239,68,68,0.08), rgba(220,38,38,0.04))",
          border: `1px solid ${overallStatus === "healthy" ? "rgba(34,197,94,0.2)" : overallStatus === "degraded" ? "rgba(245,158,11,0.2)" : "rgba(239,68,68,0.2)"}`,
        }}
      >
        {healthLoading ? (
          <RefreshCw style={{ width: 18, height: 18, animation: "spin 1s linear infinite" }} />
        ) : overallStatus === "healthy" ? (
          <CheckCircle style={{ width: 18, height: 18, color: "#22c55e" }} />
        ) : overallStatus === "degraded" ? (
          <AlertTriangle style={{ width: 18, height: 18, color: "#f59e0b" }} />
        ) : (
          <XCircle style={{ width: 18, height: 18, color: "#ef4444" }} />
        )}
        <span>
          {healthLoading
            ? "Checking system health..."
            : overallStatus === "healthy"
              ? "All systems operational"
              : overallStatus === "degraded"
                ? "System degraded - some services unavailable"
                : "Unable to reach backend API"}
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
          color={overallStatus === "healthy" ? "#22c55e" : overallStatus === "degraded" ? "#f59e0b" : "#ef4444"}
        />
        <StatCard
          label="Total Users"
          value={userStats?.total ?? "..."}
          subtitle={`${userStats?.active ?? 0} active`}
          icon={<Users style={{ width: 20, height: 20 }} />}
          color="#0f766e"
        />
        <StatCard
          label="Error Count"
          value={totalErrors}
          subtitle="from monitoring"
          icon={<AlertTriangle style={{ width: 20, height: 20 }} />}
          color={totalErrors > 0 ? "#ef4444" : "#22c55e"}
        />
        <StatCard
          label="Last Retention Sweep"
          value={
            health?.sync_scheduler?.last_retention_sweep
              ? new Date(health.sync_scheduler.last_retention_sweep).toLocaleDateString()
              : "Never"
          }
          icon={<Clock style={{ width: 20, height: 20 }} />}
          color="#6366f1"
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
          <div
            style={{
              padding: 20,
              borderRadius: 12,
              border: "1px solid var(--border, #e2e8f0)",
              background: "var(--card, #fff)",
            }}
          >
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 12 }}>Backend API</div>
            <StatusDot ok={!healthError && health?.status === "healthy"} label="API Server" />
          </div>

          {/* Database Connections */}
          <div
            style={{
              padding: 20,
              borderRadius: 12,
              border: "1px solid var(--border, #e2e8f0)",
              background: "var(--card, #fff)",
            }}
          >
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
              <Database style={{ width: 16, height: 16 }} />
              Database Connections
            </div>
            {health?.databases ? (
              Object.entries(health.databases).map(([name, ok]) => (
                <StatusDot key={name} ok={ok} label={name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())} />
              ))
            ) : (
              <div style={{ fontSize: 13, color: "#94a3b8", padding: "8px 0" }}>
                {healthLoading ? "Checking database status…" : "No data available"}
              </div>
            )}
          </div>

          {/* AI Engine */}
          <div
            style={{
              padding: 20,
              borderRadius: 12,
              border: "1px solid var(--border, #e2e8f0)",
              background: "var(--card, #fff)",
            }}
          >
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
              <Brain style={{ width: 16, height: 16 }} />
              AI Engine
            </div>
            <StatusDot ok={!!health?.gemini_model} label="AI Engine Active" />
            {health?.gemini_model && (
              <div style={{ fontSize: 12, color: "#64748b", paddingLeft: 20, marginTop: 4 }}>
                Status: <span style={{ fontWeight: 600 }}>Active</span>
              </div>
            )}
          </div>

          {/* Sync Scheduler */}
          <div
            style={{
              padding: 20,
              borderRadius: 12,
              border: "1px solid var(--border, #e2e8f0)",
              background: "var(--card, #fff)",
            }}
          >
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
              <CalendarClock style={{ width: 16, height: 16 }} />
              EMR Sync Scheduler
            </div>
            <StatusDot ok={!!health?.sync_scheduler?.running} label="Scheduler Thread" />
            {health?.sync_scheduler && (
              <div style={{ fontSize: 12, color: "#64748b", paddingLeft: 20, marginTop: 4, lineHeight: 1.8 }}>
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
          </div>
        </div>
      </div>

      {/* ── Monitoring / Error Stats ── */}
      {health?.monitoring && Object.keys(health.monitoring).length > 0 && (
        <div style={{ marginTop: 32 }}>
          <SectionHeader title="Error Statistics" icon={<AlertTriangle style={{ width: 18, height: 18 }} />} />
          <div
            style={{
              marginTop: 12,
              padding: 20,
              borderRadius: 12,
              border: "1px solid var(--border, #e2e8f0)",
              background: "var(--card, #fff)",
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
              gap: 16,
            }}
          >
            {Object.entries(health.monitoring).map(([key, value]) => (
              <div key={key} style={{ textAlign: "center" }}>
                <div style={{ fontSize: 24, fontWeight: 700, color: typeof value === "number" && value > 0 ? "#ef4444" : "#22c55e" }}>
                  {typeof value === "number" ? value : String(value)}
                </div>
                <div style={{ fontSize: 12, color: "#64748b", marginTop: 4 }}>
                  {key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Recent Audit Log ── */}
      <div style={{ marginTop: 32 }}>
        <SectionHeader
          title="Recent Audit Log"
          icon={<Shield style={{ width: 18, height: 18 }} />}
          count={auditLog?.length}
        />
        <div
          style={{
            marginTop: 12,
            borderRadius: 12,
            border: "1px solid var(--border, #e2e8f0)",
            background: "var(--card, #fff)",
            overflow: "auto",
          }}
        >
          {auditLoading ? (
            <div style={{ padding: 32, textAlign: "center", color: "#94a3b8", fontSize: 14 }}>
              Loading audit entries...
            </div>
          ) : !auditLog || auditLog.length === 0 ? (
            <div style={{ padding: 32, textAlign: "center", color: "#94a3b8", fontSize: 14 }}>
              No audit entries found
            </div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr
                  style={{
                    borderBottom: "1px solid var(--border, #e2e8f0)",
                    textAlign: "left",
                  }}
                >
                  {["Timestamp", "User", "Action", "Resource", "Path", "Status", "IP"].map((h) => (
                    <th
                      key={h}
                      style={{
                        padding: "10px 14px",
                        fontWeight: 600,
                        fontSize: 12,
                        textTransform: "uppercase",
                        letterSpacing: "0.04em",
                        color: "#64748b",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {auditLog.map((entry) => (
                  <tr
                    key={entry.id}
                    style={{
                      borderBottom: "1px solid var(--border, #f1f5f9)",
                    }}
                  >
                    <td style={{ padding: "8px 14px", whiteSpace: "nowrap", color: "#64748b", fontSize: 12 }}>
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
                            ? "rgba(34,197,94,0.1)"
                            : entry.action?.includes("error") || entry.action?.includes("fail")
                              ? "rgba(239,68,68,0.1)"
                              : "rgba(99,102,241,0.1)",
                          color: entry.action?.includes("login")
                            ? "#16a34a"
                            : entry.action?.includes("error") || entry.action?.includes("fail")
                              ? "#dc2626"
                              : "#6366f1",
                        }}
                      >
                        {entry.action}
                      </span>
                    </td>
                    <td style={{ padding: "8px 14px", fontSize: 12 }}>
                      {entry.resource_type}
                      {entry.resource_id ? ` #${entry.resource_id}` : ""}
                    </td>
                    <td style={{ padding: "8px 14px", fontSize: 12, color: "#64748b", maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
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
                            color: entry.response_status < 400 ? "#16a34a" : entry.response_status < 500 ? "#f59e0b" : "#ef4444",
                          }}
                        >
                          {entry.response_status}
                        </span>
                      ) : (
                        "-"
                      )}
                    </td>
                    <td style={{ padding: "8px 14px", fontSize: 12, color: "#94a3b8" }}>
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
            border: "1px solid var(--border, #e2e8f0)",
            background: "var(--card, #fff)",
            overflow: "auto",
          }}
        >
          {retentionLoading ? (
            <div style={{ padding: 32, textAlign: "center", color: "#94a3b8", fontSize: 14 }}>
              Loading retention policies...
            </div>
          ) : !retention || retention.length === 0 ? (
            <div style={{ padding: 32, textAlign: "center", color: "#94a3b8", fontSize: 14 }}>
              No retention policies configured
            </div>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border, #e2e8f0)", textAlign: "left" }}>
                  {["Table", "Retention Period", "Total Rows", "Oldest Record", "Eligible for Purge"].map((h) => (
                    <th
                      key={h}
                      style={{
                        padding: "10px 14px",
                        fontWeight: 600,
                        fontSize: 12,
                        textTransform: "uppercase",
                        letterSpacing: "0.04em",
                        color: "#64748b",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {retention.map((policy, i) => (
                  <tr key={policy.table_name ?? i} style={{ borderBottom: "1px solid var(--border, #f1f5f9)" }}>
                    <td style={{ padding: "8px 14px", fontWeight: 500 }}>
                      {policy.table_name}
                    </td>
                    <td style={{ padding: "8px 14px" }}>
                      {policy.retention_days} days
                    </td>
                    <td style={{ padding: "8px 14px" }}>
                      {policy.total_rows?.toLocaleString() ?? "-"}
                    </td>
                    <td style={{ padding: "8px 14px", fontSize: 12, color: "#64748b" }}>
                      {policy.oldest_record ? new Date(policy.oldest_record).toLocaleDateString() : "-"}
                    </td>
                    <td style={{ padding: "8px 14px" }}>
                      <span
                        style={{
                          fontWeight: 600,
                          color: policy.eligible_for_purge > 0 ? "#f59e0b" : "#22c55e",
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
