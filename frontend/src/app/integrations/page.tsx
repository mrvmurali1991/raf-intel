"use client";

import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { FocusTrap } from "@/components/ui/focus-trap";
import {
  Plug,
  Plus,
  RefreshCw,
  TestTube2,
  ChevronDown,
  ChevronUp,
  X,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Activity,
  Database,
  Users,
  Hash,
  Loader2,
  Wifi,
  WifiOff,
  Minus,
} from "lucide-react";
import { PageHeader, StatCard, SectionHeader, EmptyState } from "@/components/healthcare-ui";

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------


async function fetchConnections(): Promise<FhirConnection[]> {
  const { data } = await api.get("/api/fhir/connections");
  return Array.isArray(data) ? data : (data?.connections ?? []);
}


async function fetchSyncHistory(connectionId: string): Promise<SyncRecord[]> {
  const { data } = await api.get(`/api/fhir/sync/${connectionId}/status`);
  return data.history ?? data;
}

async function createConnection(payload: ConnectionFormData): Promise<FhirConnection> {
  const { data } = await api.post("/api/fhir/connections", payload);
  return data;
}

async function testConnection(connectionId: string): Promise<{ success: boolean; message: string; latency_ms?: number }> {
  const { data } = await api.post(`/api/fhir/connections/${connectionId}/test`);
  return data;
}

async function triggerSync(connectionId: string): Promise<{ job_id: string; status: string }> {
  const { data } = await api.post(`/api/fhir/sync/${connectionId}`);
  return data;
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ConnectionStatus = "active" | "inactive" | "error" | "syncing";
type AuthType = "client_credentials" | "authorization_code" | "basic" | "none";
type EhrType = "Epic" | "Cerner" | "Athenahealth" | "OpenEMR" | "Generic FHIR";

interface FhirConnection {
  id: string;
  name: string;
  ehr_type: EhrType;
  fhir_base_url: string;
  client_id?: string;
  auth_type: AuthType;
  token_url?: string;
  scope?: string;
  status: ConnectionStatus;
  last_sync_at?: string;
  created_at: string;
  total_resources_synced?: number;
  patients_synced?: number;
}

interface SyncRecord {
  id: string;
  connection_id: string;
  started_at: string;
  completed_at?: string;
  status: "success" | "failed" | "running" | "partial";
  records_fetched: number;
  records_processed: number;
  records_failed: number;
  duration_seconds?: number;
  error_message?: string;
}

interface IntegrationStats {
  total_conditions_synced: number;
  patients_mapped: number;
  unmapped_patients: number;
  hcc_codes_found: number;
}

interface ConnectionFormData {
  name: string;
  ehr_type: EhrType;
  fhir_base_url: string;
  client_id: string;
  client_secret: string;
  auth_type: AuthType;
  token_url: string;
  scope: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const EHR_TYPES: EhrType[] = ["Epic", "Cerner", "Athenahealth", "OpenEMR", "Generic FHIR"];
const AUTH_TYPES: { value: AuthType; label: string }[] = [
  { value: "client_credentials", label: "Client Credentials (OAuth2)" },
  { value: "authorization_code", label: "Authorization Code (OAuth2)" },
  { value: "basic", label: "Basic Auth" },
  { value: "none", label: "No Authentication" },
];

const DEFAULT_FORM: ConnectionFormData = {
  name: "",
  ehr_type: "Generic FHIR",
  fhir_base_url: "",
  client_id: "",
  client_secret: "",
  auth_type: "client_credentials",
  token_url: "",
  scope: "system/*.read",
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: ConnectionStatus }) {
  const map: Record<ConnectionStatus, { color: string; bg: string; dot: string; label: string; shadow: string }> = {
    active:   { color: "#059669", bg: "#D1FAE5", dot: "#10B981", label: "Active", shadow: "0 2px 6px rgba(16,185,129,0.2)" },
    inactive: { color: "#6B7280", bg: "#F3F4F6", dot: "#9CA3AF", label: "Inactive", shadow: "none" },
    error:    { color: "#DC2626", bg: "#FEE2E2", dot: "#EF4444", label: "Error", shadow: "0 2px 6px rgba(239,68,68,0.2)" },
    syncing:  { color: "#2563EB", bg: "#DBEAFE", dot: "#3B82F6", label: "Syncing", shadow: "0 2px 6px rgba(59,130,246,0.2)" },
  };
  const s = map[status] ?? map.inactive;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: "4px 12px", borderRadius: 999,
      backgroundColor: s.bg, color: s.color,
      fontSize: 12, fontWeight: 600,
      boxShadow: s.shadow,
      transition: "all 0.2s ease",
    }}>
      <span style={{ width: 7, height: 7, borderRadius: "50%", backgroundColor: s.dot, flexShrink: 0, boxShadow: `0 0 6px ${s.dot}` }} />
      {s.label}
    </span>
  );
}

function SyncStatusBadge({ status }: { status: SyncRecord["status"] }) {
  const map = {
    success: { color: "#059669", bg: "#D1FAE5", label: "Success" },
    failed:  { color: "#DC2626", bg: "#FEE2E2", label: "Failed" },
    running: { color: "#2563EB", bg: "#DBEAFE", label: "Running" },
    partial: { color: "#D97706", bg: "#FEF3C7", label: "Partial" },
  };
  const s = map[status] ?? map.failed;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center",
      padding: "3px 10px", borderRadius: 999,
      backgroundColor: s.bg, color: s.color,
      fontSize: 11, fontWeight: 600,
      boxShadow: `0 1px 4px ${s.bg}`,
      transition: "all 0.2s ease",
    }}>
      {s.label}
    </span>
  );
}

function EhrTypePill({ type }: { type: EhrType }) {
  const map: Record<EhrType, string> = {
    "Epic":         "#4F46E5",
    "Cerner":       "#0891B2",
    "Athenahealth": "#7C3AED",
    "OpenEMR":      "#059669",
    "Generic FHIR": "#64748B",
  };
  const color = map[type] ?? "#64748B";
  return (
    <span style={{
      display: "inline-flex", alignItems: "center",
      padding: "2px 8px", borderRadius: 4,
      backgroundColor: `${color}1A`, color,
      fontSize: 11, fontWeight: 600,
    }}>
      {type}
    </span>
  );
}

function formatDateTime(iso?: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric", year: "numeric",
    hour: "numeric", minute: "2-digit",
  });
}

function formatDuration(seconds?: number): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s}s`;
}

// ---------------------------------------------------------------------------
// Add Connection Modal
// ---------------------------------------------------------------------------

interface AddConnectionModalProps {
  onClose: () => void;
  onSuccess: () => void;
}

function AddConnectionModal({ onClose, onSuccess }: AddConnectionModalProps) {
  const [form, setForm] = useState<ConnectionFormData>(DEFAULT_FORM);
  const [errors, setErrors] = useState<Partial<Record<keyof ConnectionFormData, string>>>({});

  const mutation = useMutation({
    mutationFn: createConnection,
    onSuccess: () => {
      onSuccess();
      onClose();
    },
  });

  function set<K extends keyof ConnectionFormData>(key: K, value: ConnectionFormData[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
    setErrors((prev) => ({ ...prev, [key]: undefined }));
  }

  function validate(): boolean {
    const e: Partial<Record<keyof ConnectionFormData, string>> = {};
    if (!form.name.trim()) e.name = "Connection name is required";
    if (!form.fhir_base_url.trim()) e.fhir_base_url = "FHIR Base URL is required";
    else if (!/^https?:\/\/.+/.test(form.fhir_base_url)) e.fhir_base_url = "Must be a valid URL starting with http(s)://";
    if (form.auth_type !== "none") {
      if (!form.client_id.trim()) e.client_id = "Client ID is required";
      if (!form.token_url.trim()) e.token_url = "Token URL is required";
    }
    setErrors(e);
    return Object.keys(e).length === 0;
  }

  function handleSubmit(ev: React.FormEvent) {
    ev.preventDefault();
    if (!validate()) return;
    mutation.mutate(form);
  }

  const inputStyle = (hasError?: string): React.CSSProperties => ({
    width: "100%", height: 38, borderRadius: 8,
    border: `1px solid ${hasError ? "#FCA5A5" : "#E2E8F0"}`,
    padding: "0 12px", fontSize: 13, color: "#0F172A",
    outline: "none", backgroundColor: "#FFFFFF",
    boxSizing: "border-box",
  });

  const selectStyle = (hasError?: string): React.CSSProperties => ({
    ...inputStyle(hasError),
    cursor: "pointer", appearance: "none" as const,
  });

  const labelStyle: React.CSSProperties = {
    display: "block", fontSize: 12, fontWeight: 600,
    color: "#475569", marginBottom: 4,
  };

  const fieldStyle: React.CSSProperties = { marginBottom: 16 };

  return (
    <div
      className="animate-fade-in"
      style={{
        position: "fixed", inset: 0, zIndex: 1000,
        display: "flex", alignItems: "center", justifyContent: "center",
        backgroundColor: "rgba(0,0,0,0.5)", backdropFilter: "blur(4px)",
        padding: 16,
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <FocusTrap>
        <div className="animate-scale-in" style={{
          backgroundColor: "#FFFFFF", borderRadius: 20,
          width: "100%", maxWidth: 560,
          maxHeight: "90vh", overflowY: "auto",
          boxShadow: "0 24px 80px rgba(0,0,0,0.3)",
        }} role="dialog" aria-modal="true" aria-label="Add connection">
        {/* Modal header */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "20px 24px 0",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{
              width: 36, height: 36, borderRadius: 10,
              backgroundColor: "#2563EB1A", display: "flex",
              alignItems: "center", justifyContent: "center",
            }}>
              <Plug size={18} color="#2563EB" />
            </div>
            <div>
              <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "#0F172A" }}>
                Add FHIR Connection
              </h2>
              <p style={{ margin: 0, fontSize: 12, color: "#64748B" }}>
                Connect to your EHR system via FHIR R4
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", cursor: "pointer", padding: 6, borderRadius: 8, color: "#94A3B8" }}
            aria-label="Close dialog"
          >
            <X size={20} />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} style={{ padding: 24 }}>
          {mutation.isError && (
            <div style={{
              display: "flex", alignItems: "center", gap: 10,
              padding: 12, borderRadius: 8, backgroundColor: "#FEF2F2",
              border: "1px solid #FECACA", marginBottom: 20,
            }}>
              <AlertTriangle size={16} color="#EF4444" style={{ flexShrink: 0 }} />
              <span style={{ fontSize: 13, color: "#DC2626" }}>
                {(mutation.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Failed to create connection. Please try again."}
              </span>
            </div>
          )}

          <div style={fieldStyle}>
            <label style={labelStyle} htmlFor="conn-name">Connection Name</label>
            <input
              id="conn-name"
              type="text"
              placeholder="e.g. Main Hospital Epic"
              value={form.name}
              onChange={(e) => set("name", e.target.value)}
              style={inputStyle(errors.name)}
              aria-invalid={!!errors.name}
              aria-describedby={errors.name ? "conn-name-err" : undefined}
            />
            {errors.name && <p id="conn-name-err" style={{ margin: "4px 0 0", fontSize: 11, color: "#DC2626" }}>{errors.name}</p>}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
            <div>
              <label style={labelStyle} htmlFor="conn-ehr-type">EHR Type</label>
              <select
                id="conn-ehr-type"
                value={form.ehr_type}
                onChange={(e) => set("ehr_type", e.target.value as EhrType)}
                style={selectStyle()}
              >
                {EHR_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label style={labelStyle} htmlFor="conn-auth-type">Auth Type</label>
              <select
                id="conn-auth-type"
                value={form.auth_type}
                onChange={(e) => set("auth_type", e.target.value as AuthType)}
                style={selectStyle()}
              >
                {AUTH_TYPES.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
              </select>
            </div>
          </div>

          <div style={fieldStyle}>
            <label style={labelStyle} htmlFor="conn-fhir-url">FHIR Base URL</label>
            <input
              id="conn-fhir-url"
              type="url"
              placeholder="https://fhir.hospital.org/api/FHIR/R4"
              value={form.fhir_base_url}
              onChange={(e) => set("fhir_base_url", e.target.value)}
              style={inputStyle(errors.fhir_base_url)}
              aria-invalid={!!errors.fhir_base_url}
            />
            {errors.fhir_base_url && <p style={{ margin: "4px 0 0", fontSize: 11, color: "#DC2626" }}>{errors.fhir_base_url}</p>}
          </div>

          {form.auth_type !== "none" && (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 16 }}>
                <div>
                  <label style={labelStyle} htmlFor="conn-client-id">Client ID</label>
                  <input
                    id="conn-client-id"
                    type="text"
                    placeholder="client_id"
                    value={form.client_id}
                    onChange={(e) => set("client_id", e.target.value)}
                    style={inputStyle(errors.client_id)}
                  />
                  {errors.client_id && <p style={{ margin: "4px 0 0", fontSize: 11, color: "#DC2626" }}>{errors.client_id}</p>}
                </div>
                <div>
                  <label style={labelStyle} htmlFor="conn-client-secret">Client Secret</label>
                  <input
                    id="conn-client-secret"
                    type="password"
                    placeholder="client_secret"
                    value={form.client_secret}
                    onChange={(e) => set("client_secret", e.target.value)}
                    style={inputStyle()}
                    autoComplete="new-password"
                  />
                </div>
              </div>

              <div style={fieldStyle}>
                <label style={labelStyle} htmlFor="conn-token-url">Token URL</label>
                <input
                  id="conn-token-url"
                  type="url"
                  placeholder="https://fhir.hospital.org/oauth2/token"
                  value={form.token_url}
                  onChange={(e) => set("token_url", e.target.value)}
                  style={inputStyle(errors.token_url)}
                />
                {errors.token_url && <p style={{ margin: "4px 0 0", fontSize: 11, color: "#DC2626" }}>{errors.token_url}</p>}
              </div>

              <div style={fieldStyle}>
                <label style={labelStyle} htmlFor="conn-scope">Scope</label>
                <input
                  id="conn-scope"
                  type="text"
                  placeholder="system/*.read"
                  value={form.scope}
                  onChange={(e) => set("scope", e.target.value)}
                  style={inputStyle()}
                />
                <p style={{ margin: "4px 0 0", fontSize: 11, color: "#94A3B8" }}>
                  Space-separated SMART on FHIR scopes
                </p>
              </div>
            </>
          )}

          <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, paddingTop: 8, borderTop: "1px solid #F1F5F9" }}>
            <button
              type="button"
              onClick={onClose}
              className="btn-press"
              style={{
                padding: "8px 18px", borderRadius: 10,
                border: "2px solid #E2E8F0", backgroundColor: "#FFFFFF",
                fontSize: 13, fontWeight: 500, color: "#475569", cursor: "pointer",
                transition: "all 0.2s ease",
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={mutation.isPending}
              className="btn-press"
              style={{
                padding: "8px 18px", borderRadius: 10,
                border: "none",
                background: mutation.isPending ? "#93C5FD" : "linear-gradient(135deg, #2563EB, #0EA5E9)",
                fontSize: 13, fontWeight: 600, color: "#FFFFFF", cursor: mutation.isPending ? "not-allowed" : "pointer",
                display: "inline-flex", alignItems: "center", gap: 6,
                boxShadow: mutation.isPending ? "none" : "0 2px 8px rgba(37,99,235,0.25)",
                transition: "all 0.2s ease",
              }}
            >
              {mutation.isPending && <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} />}
              {mutation.isPending ? "Saving..." : "Add Connection"}
            </button>
          </div>
        </form>
      </div>
      </FocusTrap>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sync History Table
// ---------------------------------------------------------------------------

function SyncHistoryTable({ connectionId }: { connectionId: string }) {
  const { data: history, isLoading } = useQuery({
    queryKey: ["sync-history", connectionId],
    queryFn: () => fetchSyncHistory(connectionId),
    staleTime: 30_000,
  });

  if (isLoading) {
    return (
      <div style={{ padding: "16px 0" }}>
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="shimmer" style={{
            height: 36, borderRadius: 8, backgroundColor: "#F1F5F9",
            marginBottom: 6,
          }} />
        ))}
      </div>
    );
  }

  if (!history || history.length === 0) {
    return (
      <div style={{ padding: "20px 0", textAlign: "center" }}>
        <p style={{ fontSize: 13, color: "#94A3B8", margin: 0 }}>No sync history yet</p>
      </div>
    );
  }

  const colStyle: React.CSSProperties = {
    fontSize: 11, fontWeight: 600, textTransform: "uppercase",
    letterSpacing: "0.05em", color: "#94A3B8", padding: "8px 10px",
  };

  const cellStyle: React.CSSProperties = {
    fontSize: 12, color: "#475569", padding: "10px 10px",
    borderBottom: "1px solid #F1F5F9",
  };

  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }} role="table" aria-label="Sync history">
        <thead>
          <tr style={{ backgroundColor: "#F8FAFC" }}>
            <th style={{ ...colStyle, textAlign: "left" }}>Started</th>
            <th style={{ ...colStyle, textAlign: "left" }}>Status</th>
            <th style={{ ...colStyle, textAlign: "right" }}>Fetched</th>
            <th style={{ ...colStyle, textAlign: "right" }}>Processed</th>
            <th style={{ ...colStyle, textAlign: "right" }}>Failed</th>
            <th style={{ ...colStyle, textAlign: "right" }}>Duration</th>
          </tr>
        </thead>
        <tbody>
          {history.slice(0, 10).map((rec, idx) => (
            <tr key={rec.id} style={{ backgroundColor: idx % 2 === 0 ? "#FFFFFF" : "#F8FAFC", transition: "background-color 0.15s ease" }} onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = "#EFF6FF"; }} onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.backgroundColor = idx % 2 === 0 ? "#FFFFFF" : "#F8FAFC"; }}>
              <td style={{ ...cellStyle, whiteSpace: "nowrap" }}>{formatDateTime(rec.started_at)}</td>
              <td style={cellStyle}><SyncStatusBadge status={rec.status} /></td>
              <td style={{ ...cellStyle, textAlign: "right", fontWeight: 600, color: "#0F172A" }}>
                {rec.records_fetched.toLocaleString()}
              </td>
              <td style={{ ...cellStyle, textAlign: "right", color: "#059669", fontWeight: 600 }}>
                {rec.records_processed.toLocaleString()}
              </td>
              <td style={{ ...cellStyle, textAlign: "right", color: rec.records_failed > 0 ? "#DC2626" : "#94A3B8", fontWeight: 600 }}>
                {rec.records_failed.toLocaleString()}
              </td>
              <td style={{ ...cellStyle, textAlign: "right", fontFamily: "monospace" }}>
                {formatDuration(rec.duration_seconds)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Connection Card
// ---------------------------------------------------------------------------

interface TestResult {
  success: boolean;
  message: string;
  latency_ms?: number;
}

function ConnectionCard({ conn }: { conn: FhirConnection }) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [syncingId, setSyncingId] = useState(false);
  const [currentStatus, setCurrentStatus] = useState<ConnectionStatus>(conn.status);
  const prevStatusRef = useRef<ConnectionStatus>(conn.status);

  // Poll for status updates when syncing
  useEffect(() => {
    if (currentStatus !== "syncing") return;
    const interval = setInterval(async () => {
      try {
        const { data } = await api.get(`/api/fhir/connections/${conn.id}`);
        if (data?.status && data.status !== currentStatus) {
          setCurrentStatus(data.status);
          queryClient.setQueryData(["fhir-connections"], (old: FhirConnection[] | undefined) =>
            old?.map((c) => (c.id === conn.id ? { ...c, status: data.status } : c))
          );
        }
      } catch {
        // Silently ignore polling errors
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [currentStatus, conn.id, queryClient]);

  // Sync local status when conn prop changes
  useEffect(() => {
    if (conn.status !== prevStatusRef.current) {
      setCurrentStatus(conn.status);
      prevStatusRef.current = conn.status;
    }
  }, [conn.status]);

  const testMutation = useMutation({
    mutationFn: () => testConnection(conn.id),
    onSuccess: (result) => setTestResult(result),
    onError: () => setTestResult({ success: false, message: "Connection test failed. Check credentials and URL." }),
  });

  const syncMutation = useMutation({
    mutationFn: () => triggerSync(conn.id),
    onMutate: () => setSyncingId(true),
    onSettled: () => {
      setSyncingId(false);
      queryClient.invalidateQueries({ queryKey: ["sync-history", conn.id] });
      queryClient.invalidateQueries({ queryKey: ["fhir-connections"] });

    },
  });

  const borderColorMap: Record<ConnectionStatus, string> = {
    active: "#10B981",
    inactive: "#D1D5DB",
    error: "#EF4444",
    syncing: "#3B82F6",
  };

  return (
    <div className="premium-card hover-lift" style={{
      backgroundColor: "#FFFFFF",
      borderRadius: 16,
      border: "1px solid #E2E8F0",
      borderLeft: `4px solid ${borderColorMap[conn.status]}`,
      overflow: "hidden",
      transition: "all 0.3s ease",
    }}>
      {/* Card header row */}
      <div style={{ padding: "16px 20px" }}>
        <div style={{
          display: "flex", alignItems: "flex-start",
          justifyContent: "space-between", gap: 12, flexWrap: "wrap",
        }}>
          {/* Left: name + details */}
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 6 }}>
              <div style={{
                width: 34, height: 34, borderRadius: 9,
                backgroundColor: "#2563EB1A", display: "flex",
                alignItems: "center", justifyContent: "center", flexShrink: 0,
              }}>
                <Plug size={16} color="#2563EB" />
              </div>
              <div>
                <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: "#0F172A" }}>
                  {conn.name}
                </h3>
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 2, flexWrap: "wrap" }}>
                  <EhrTypePill type={conn.ehr_type} />
                  <span style={{ fontSize: 12, color: "#94A3B8", fontFamily: "monospace", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 300 }}>
                    {conn.fhir_base_url}
                  </span>
                </div>
              </div>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap", marginTop: 8 }}>
              <StatusBadge status={conn.status} />
              <div style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12, color: "#64748B" }}>
                <Clock size={12} />
                <span>Last sync: {formatDateTime(conn.last_sync_at)}</span>
              </div>
              {conn.auth_type && (
                <span style={{ fontSize: 11, color: "#94A3B8", backgroundColor: "#F8FAFC", padding: "2px 8px", borderRadius: 4, border: "1px solid #E2E8F0" }}>
                  {AUTH_TYPES.find((a) => a.value === conn.auth_type)?.label ?? conn.auth_type}
                </span>
              )}
            </div>
          </div>

          {/* Right: action buttons */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0, flexWrap: "wrap" }}>
            <button
              onClick={() => { testMutation.mutate(); setTestResult(null); }}
              disabled={testMutation.isPending}
              className="btn-press"
              style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "7px 14px", borderRadius: 10,
                border: "2px solid #E2E8F0", backgroundColor: "#FFFFFF",
                fontSize: 12, fontWeight: 500, color: "#475569",
                cursor: testMutation.isPending ? "not-allowed" : "pointer",
                opacity: testMutation.isPending ? 0.7 : 1,
                transition: "all 0.2s ease",
              }}
              aria-label={`Test connection for ${conn.name}`}
            >
              {testMutation.isPending
                ? <Loader2 size={13} style={{ animation: "spin 1s linear infinite" }} />
                : <TestTube2 size={13} />
              }
              {testMutation.isPending ? "Testing..." : "Test"}
            </button>

            <button
              onClick={() => syncMutation.mutate()}
              disabled={syncingId || conn.status === "syncing"}
              className="btn-press"
              style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "7px 14px", borderRadius: 10,
                border: "none",
                background: syncingId ? "#93C5FD" : "linear-gradient(135deg, #2563EB, #0EA5E9)",
                fontSize: 12, fontWeight: 600, color: "#FFFFFF",
                cursor: (syncingId || conn.status === "syncing") ? "not-allowed" : "pointer",
                boxShadow: syncingId ? "none" : "0 2px 8px rgba(37,99,235,0.25)",
                transition: "all 0.2s ease",
              }}
              aria-label={`Sync now for ${conn.name}`}
            >
              <RefreshCw size={13} style={{ animation: syncingId ? "spin 1s linear infinite" : "none" }} />
              {syncingId ? "Syncing..." : "Sync Now"}
            </button>

            <button
              onClick={() => setExpanded((p) => !p)}
              style={{
                display: "inline-flex", alignItems: "center", gap: 4,
                padding: "7px 10px", borderRadius: 8,
                border: "1px solid #E2E8F0", backgroundColor: "#F8FAFC",
                fontSize: 12, fontWeight: 500, color: "#64748B", cursor: "pointer",
              }}
              aria-expanded={expanded}
              aria-label={expanded ? "Hide sync history" : "Show sync history"}
            >
              History
              {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            </button>
          </div>
        </div>

        {/* Test result inline feedback */}
        {testResult && (
          <div style={{
            display: "flex", alignItems: "center", gap: 8, marginTop: 12,
            padding: "8px 12px", borderRadius: 8,
            backgroundColor: testResult.success ? "#D1FAE5" : "#FEE2E2",
            border: `1px solid ${testResult.success ? "#6EE7B7" : "#FECACA"}`,
          }}>
            {testResult.success
              ? <CheckCircle2 size={15} color="#059669" />
              : <AlertTriangle size={15} color="#DC2626" />
            }
            <span style={{ fontSize: 12, color: testResult.success ? "#065F46" : "#991B1B", fontWeight: 500 }}>
              {testResult.message}
              {testResult.success && testResult.latency_ms != null && (
                <span style={{ color: "#047857", marginLeft: 8, fontFamily: "monospace" }}>
                  {testResult.latency_ms}ms
                </span>
              )}
            </span>
            <button
              onClick={() => setTestResult(null)}
              style={{ marginLeft: "auto", background: "none", border: "none", cursor: "pointer", color: "#94A3B8", padding: 2 }}
              aria-label="Dismiss test result"
            >
              <X size={12} />
            </button>
          </div>
        )}

        {/* Sync mutation error */}
        {syncMutation.isError && (
          <div style={{
            display: "flex", alignItems: "center", gap: 8, marginTop: 12,
            padding: "8px 12px", borderRadius: 8,
            backgroundColor: "#FEF2F2", border: "1px solid #FECACA",
          }}>
            <AlertTriangle size={15} color="#DC2626" />
            <span style={{ fontSize: 12, color: "#991B1B" }}>
              {(syncMutation.error as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Sync failed to start. Please try again."}
            </span>
          </div>
        )}

        {syncMutation.isSuccess && (
          <div style={{
            display: "flex", alignItems: "center", gap: 8, marginTop: 12,
            padding: "8px 12px", borderRadius: 8,
            backgroundColor: "#DBEAFE", border: "1px solid #BFDBFE",
          }}>
            <Activity size={15} color="#2563EB" />
            <span style={{ fontSize: 12, color: "#1D4ED8", fontWeight: 500 }}>
              Sync job started — Job ID: <code style={{ fontFamily: "monospace" }}>{syncMutation.data?.job_id}</code>
            </span>
          </div>
        )}
      </div>

      {/* Expandable sync history */}
      {expanded && (
        <div style={{ borderTop: "1px solid #F1F5F9", padding: "0 20px 16px" }}>
          <div style={{ paddingTop: 16 }}>
            <SectionHeader
              title="Sync History"
              icon={<Clock size={14} />}
              count={10}
            />
            <SyncHistoryTable connectionId={conn.id} />
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function IntegrationsPage() {
  const [showAddModal, setShowAddModal] = useState(false);
  const queryClient = useQueryClient();

  const {
    data: connections,
    isLoading: connectionsLoading,
    isError: connectionsError,
    refetch: refetchConnections,
  } = useQuery({
    queryKey: ["fhir-connections"],
    queryFn: fetchConnections,
    staleTime: 30_000,
  });

  const stats = useMemo<IntegrationStats | undefined>(() => {
    if (!connections) return undefined;
    const active = connections.filter((c) => c.status === "active").length;
    return {
      total_connections: connections.length,
      active_connections: active,
      total_conditions_synced: connections.reduce((s, c) => s + (c.total_resources_synced ?? 0), 0),
      patients_mapped: connections.reduce((s, c) => s + (c.patients_synced ?? 0), 0),
      unmapped_patients: 0,
      hcc_codes_found: 0,
    } as IntegrationStats;
  }, [connections]);
  const statsLoading = connectionsLoading;

  const handleAddSuccess = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["fhir-connections"] });
  }, [queryClient]);

  // Active connections count for subtitle
  const activeCount = connections?.filter((c) => c.status === "active").length ?? 0;
  const totalCount = connections?.length ?? 0;

  // ---- Error state ----
  if (connectionsError) {
    return (
      <div className="animate-fade-in" style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "60vh", gap: 16 }}>
        <div style={{ borderRadius: 20, backgroundColor: "#FEF2F2", padding: 24 }}>
          <AlertTriangle size={40} color="#EF4444" />
        </div>
        <h2 style={{ fontSize: 18, fontWeight: 700, color: "#0F172A", margin: 0 }}>Failed to load integrations</h2>
        <p style={{ fontSize: 14, color: "#64748B", margin: 0 }}>Check that the server is running and try again.</p>
        <button
          onClick={() => refetchConnections()}
          style={{
            display: "inline-flex", alignItems: "center", gap: 8,
            borderRadius: 8, border: "1px solid #E2E8F0", backgroundColor: "#FFFFFF",
            padding: "8px 16px", fontSize: 14, fontWeight: 500, color: "#475569", cursor: "pointer",
          }}
        >
          <RefreshCw size={16} /> Retry
        </button>
      </div>
    );
  }

  return (
    <div className="animate-fade-in" style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      {/* Page Header */}
      <PageHeader
        title="EHR Integrations"
        icon={<Plug size={22} />}
        subtitle={
          !connectionsLoading
            ? `${totalCount} connection${totalCount !== 1 ? "s" : ""} · ${activeCount} active`
            : undefined
        }
        actions={
          <button
            onClick={() => setShowAddModal(true)}
            className="btn-press"
            style={{
              display: "inline-flex", alignItems: "center", gap: 8,
              padding: "9px 18px", borderRadius: 10,
              border: "none",
              background: "linear-gradient(135deg, #2563EB, #0EA5E9)",
              fontSize: 13, fontWeight: 600, color: "#FFFFFF", cursor: "pointer",
              boxShadow: "0 4px 14px rgba(37,99,235,0.3)",
              transition: "all 0.2s ease",
            }}
            aria-label="Add FHIR connection"
          >
            <Plus size={15} />
            Add Connection
          </button>
        }
      />

      {/* Stats row */}
      <div className="animate-slide-up stagger-1" style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
        gap: 14, marginBottom: 24,
      }}>
        <StatCard
          label="Conditions Synced"
          value={statsLoading ? "—" : (stats?.total_conditions_synced ?? 0).toLocaleString()}
          icon={<Database size={18} />}
          color="#2563EB"
          subtitle="Across all connections"
        />
        <StatCard
          label="Patients Mapped"
          value={statsLoading ? "—" : (stats?.patients_mapped ?? 0).toLocaleString()}
          icon={<Users size={18} />}
          color="#059669"
          subtitle="Successfully linked"
        />
        <StatCard
          label="Unmapped Patients"
          value={statsLoading ? "—" : (stats?.unmapped_patients ?? 0).toLocaleString()}
          icon={<Minus size={18} />}
          color="#D97706"
          subtitle="Require manual review"
        />
        <StatCard
          label="HCC Codes Found"
          value={statsLoading ? "—" : (stats?.hcc_codes_found ?? 0).toLocaleString()}
          icon={<Hash size={18} />}
          color="#7C3AED"
          subtitle="Via FHIR conditions"
        />
      </div>

      {/* Connections list */}
      <div className="animate-slide-up stagger-2" style={{ marginBottom: 8 }}>
        <SectionHeader
          title="FHIR Connections"
          icon={<Wifi size={16} />}
          count={totalCount}
          action={
            <button
              onClick={() => refetchConnections()}
              className="btn-press"
              style={{
                display: "inline-flex", alignItems: "center", gap: 6,
                padding: "5px 12px", borderRadius: 8,
                border: "1px solid #E2E8F0", backgroundColor: "#FFFFFF",
                fontSize: 12, fontWeight: 500, color: "#64748B", cursor: "pointer",
                transition: "all 0.2s ease",
              }}
              aria-label="Refresh connections"
            >
              <RefreshCw size={12} />
              Refresh
            </button>
          }
        />
      </div>

      {/* Loading skeleton */}
      {connectionsLoading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {Array.from({ length: 2 }).map((_, i) => (
            <div
              key={i}
              className="shimmer"
              style={{
                height: 120, borderRadius: 12,
                backgroundColor: "#F8FAFC", border: "1px solid #E2E8F0",
              }}
            />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!connectionsLoading && (!connections || connections.length === 0) && (
        <div className="animate-fade-in" style={{
          backgroundColor: "#FFFFFF", borderRadius: 16,
          border: "2px dashed #E2E8F0",
        }}>
          <EmptyState
            icon={<WifiOff size={24} />}
            title="No FHIR connections configured"
            description="Connect your EHR system to automatically sync patient conditions, diagnoses, and HCC codes for RAF scoring."
          />
          <div style={{ display: "flex", justifyContent: "center", paddingBottom: 32 }}>
            <button
              onClick={() => setShowAddModal(true)}
              className="btn-press"
              style={{
                display: "inline-flex", alignItems: "center", gap: 8,
                padding: "10px 20px", borderRadius: 10,
                border: "none",
                background: "linear-gradient(135deg, #2563EB, #0EA5E9)",
                fontSize: 13, fontWeight: 600, color: "#FFFFFF", cursor: "pointer",
                boxShadow: "0 4px 14px rgba(37,99,235,0.3)",
                transition: "all 0.2s ease",
              }}
            >
              <Plus size={15} />
              Add Your First Connection
            </button>
          </div>
        </div>
      )}

      {/* Connection cards */}
      {!connectionsLoading && connections && connections.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {connections.map((conn, idx) => (
            <div key={conn.id} className={`animate-slide-up stagger-${Math.min(idx + 3, 6)}`}>
              <ConnectionCard conn={conn} />
            </div>
          ))}
        </div>
      )}

      {/* FHIR R4 info footer */}
      {!connectionsLoading && connections && connections.length > 0 && (
        <div className="animate-slide-up stagger-5" style={{
          marginTop: 24, padding: "14px 18px", borderRadius: 12,
          backgroundColor: "#EFF6FF", border: "1px solid #BFDBFE",
          display: "flex", alignItems: "center", gap: 10,
        }}>
          <Activity size={16} color="#2563EB" style={{ flexShrink: 0 }} />
          <p style={{ margin: 0, fontSize: 12, color: "#1D4ED8", lineHeight: 1.5 }}>
            <strong>FHIR R4</strong> — Connections use the HL7 FHIR R4 standard.
            Conditions are mapped to ICD-10 codes and enriched with HCC classification during each sync.
            Sync jobs run in the background and update patient RAF scores automatically.
          </p>
        </div>
      )}

      {/* Add connection modal */}
      {showAddModal && (
        <AddConnectionModal
          onClose={() => setShowAddModal(false)}
          onSuccess={handleAddSuccess}
        />
      )}

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
        @keyframes spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
