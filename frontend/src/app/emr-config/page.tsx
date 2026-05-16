"use client";

import { useState, useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import {
  Heart,
  Zap,
  Database,
  Activity,
  FileText,
  Clock,
  ArrowRight,
  Leaf,
  Globe,
  Link2,
  Plus,
  RefreshCw,
  TestTube2,
  Pencil,
  Trash2,
  ChevronDown,
  ChevronUp,
  X,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  Server,
  Settings2,
  Stethoscope,
  FlaskConical,
} from "lucide-react";
import { PageHeader, StatCard, SectionHeader, EmptyState } from "@/components/healthcare-ui";
import { tokens } from "@/styles/tokens";

// ---------------------------------------------------------------------------
// Design tokens — shared slate palette and risk colors imported from
// @/styles/tokens. Page-specific accents remain local.
// ---------------------------------------------------------------------------

const C = {
  primary:    tokens.primary,
  slate900:   tokens.slate900,
  slate800:   tokens.slate800,
  slate700:   tokens.slate700,
  slate600:   tokens.slate600,
  slate500:   tokens.slate500,
  slate400:   tokens.slate400,
  slate300:   tokens.slate300,
  slate200:   tokens.slate200,
  slate100:   tokens.slate100,
  slate50:    tokens.slate50,
  white:      tokens.white,
  emerald600: tokens.riskLow,
  emerald100: tokens.emerald100,
  emerald500: tokens.success,
  red600:     tokens.riskHigh,
  red100:     tokens.dangerSoft,
  red500:     tokens.danger,
  amber600:   tokens.riskMedium,
  amber100:   tokens.warningSoft,
  amber500:   tokens.warningStrong,
  blue600:    tokens.primary,
  blue100:    tokens.primarySoft,
  blue500:    tokens.infoBlue,
  gray100:    tokens.slate100,
  gray400:    tokens.slate400,
  gray600:    tokens.slate600,
};

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

interface PipelineSettings {
  pipeline_mode: "auto_ai" | "auto_basic" | "manual";
  ai_analysis_enabled: boolean;
}

async function getPipelineSettings(): Promise<PipelineSettings> {
  const { data } = await api.get("/api/pipeline/settings");
  return data;
}

async function updatePipelineSettings(body: Partial<PipelineSettings>): Promise<PipelineSettings> {
  const { data } = await api.put("/api/pipeline/settings", body);
  return data;
}

async function getVendorPresets(): Promise<VendorPreset[]> {
  const { data } = await api.get("/api/emr/vendors");
  const list = Array.isArray(data) ? data : (data?.vendors ?? []);
  return list.map((v: any) => ({ ...v, name: v.name || v.display_name || v.vendor, description: v.description || v.notes || "" }));
}

function fromBackendConnection(raw: any): EmrConnection {
  return {
    ...raw,
    name: raw.name || raw.display_name || "",
    fhir_base_url: raw.fhir_base_url || raw.base_url || "",
    auth_type: raw.auth_type || raw.fhir_auth_type || raw.api_auth_type || "oauth2",
    client_id: raw.client_id || raw.fhir_client_id || "",
    client_secret: raw.client_secret || raw.fhir_client_secret || "",
    token_url: raw.token_url || raw.fhir_token_url || "",
    host: raw.host || raw.db_host || "",
    port: raw.port || raw.db_port,
    database_name: raw.database_name || raw.db_name || "",
    username: raw.username || raw.db_user || "",
    password: raw.password || raw.db_password || "",
    status: raw.is_active === false || raw.is_active === 0 ? "inactive" : (raw.status || "active"),
  };
}

async function getEmrConnections(): Promise<EmrConnection[]> {
  const { data } = await api.get("/api/emr/connections");
  const list = Array.isArray(data) ? data : (data?.connections ?? []);
  return list.map(fromBackendConnection);
}

function toBackendPayload(form: ConnectionFormData | Partial<ConnectionFormData>): Record<string, unknown> {
  const payload: Record<string, unknown> = { ...form };
  // Map frontend field names to backend expected names
  if (form.connection_type === "fhir_r4") {
    if (form.auth_type) payload.fhir_auth_type = form.auth_type;
    if (form.client_id) payload.fhir_client_id = form.client_id;
    if (form.client_secret) payload.fhir_client_secret = form.client_secret;
    if (form.token_url) payload.fhir_token_url = form.token_url;
  } else if (form.connection_type === "rest_api") {
    if (form.api_base_url) payload.api_base_url = form.api_base_url;
    if (form.auth_type) payload.api_auth_type = form.auth_type;
    if (form.username) payload.api_username = form.username;
    if (form.password) payload.api_password = form.password;
    if (form.client_secret) payload.api_token = form.client_secret;
  }
  // Remove frontend-only keys that backend doesn't recognize
  delete payload.host;
  delete payload.port;
  delete payload.database_name;
  delete payload.username;
  delete payload.password;
  delete payload.auth_type;
  delete payload.client_id;
  delete payload.client_secret;
  delete payload.token_url;
  delete payload.scope;
  delete payload.ssl_enabled;
  delete payload.api_version;
  delete payload.vendor_id;
  return payload;
}

async function createEmrConnection(body: ConnectionFormData): Promise<EmrConnection> {
  const payload = toBackendPayload(body);
  const { data } = await api.post("/api/emr/connections", payload);
  return data;
}

async function updateEmrConnection(id: string, body: Partial<ConnectionFormData>): Promise<EmrConnection> {
  const { data } = await api.put(`/api/emr/connections/${id}`, toBackendPayload(body));
  return data;
}

async function toggleEmrConnectionActive(id: string, isActive: boolean): Promise<EmrConnection> {
  const { data } = await api.put(`/api/emr/connections/${id}`, { is_active: isActive });
  return data;
}

async function deleteEmrConnection(id: string): Promise<void> {
  await api.delete(`/api/emr/connections/${id}`);
}

async function testEmrConnection(id: string): Promise<{ success: boolean; message: string; latency_ms?: number }> {
  const { data } = await api.post(`/api/emr/connections/${id}/test`);
  return data;
}

async function syncEmrConnection(id: string, syncType: string = "full"): Promise<{ job_id: string; status: string }> {
  const { data } = await api.post(`/api/emr/connections/${id}/sync`, { sync_type: syncType });
  return data;
}

async function getSyncHistory(id: string): Promise<SyncRecord[]> {
  const { data } = await api.get(`/api/emr/connections/${id}/sync/history`);
  return Array.isArray(data) ? data : (data?.history ?? []);
}

// ---------------------------------------------------------------------------
// Auto-sync status
// ---------------------------------------------------------------------------

interface AutoSyncStatus {
  enabled: boolean;
  last_run_at: string | null;
  next_run_in_seconds: number | null;
  new_patients_last_cycle: number;
  total_synced_today: number;
  current_cycle_running: boolean;
  last_error: string | null;
}

async function getAutoSyncStatus(): Promise<AutoSyncStatus | null> {
  try {
    const { data } = await api.get("/api/emr/auto-sync/status");
    return data;
  } catch (err: any) {
    if (err?.response?.status === 404) return null;
    throw err;
  }
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ConnectionType = "fhir_r4" | "rest_api";
type ConnectionStatus = "active" | "inactive" | "error" | "testing";
type AuthType = "none" | "basic" | "bearer" | "oauth2" | "api_key";
type DbType = "mysql" | "postgresql";

interface VendorPreset {
  id: string;
  name: string;
  vendor: string;
  connection_type: ConnectionType;
  description: string;
  defaults?: Partial<ConnectionFormData>;
}

interface EmrConnection {
  id: string;
  name: string;
  vendor: string;
  vendor_id?: string;
  connection_type: ConnectionType;
  status: ConnectionStatus;
  last_sync_at?: string;
  created_at: string;
  host?: string;
  port?: number;
  database_name?: string;
  username?: string;
  ssl_enabled?: boolean;
  db_type?: DbType;
  fhir_base_url?: string;
  auth_type?: AuthType;
  client_id?: string;
  token_url?: string;
  scope?: string;
  api_base_url?: string;
  api_version?: string;
  field_mappings?: FieldMapping[];
  error_message?: string;
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

interface FieldMapping {
  source_field: string;
  target_field: string;
  transform?: string;
}

interface ConnectionFormData {
  name: string;
  vendor: string;
  vendor_id?: string;
  connection_type: ConnectionType;
  // direct_db
  host?: string;
  port?: number;
  database_name?: string;
  username?: string;
  password?: string;
  ssl_enabled?: boolean;
  db_type?: DbType;
  // fhir_r4
  fhir_base_url?: string;
  auth_type?: AuthType;
  client_id?: string;
  client_secret?: string;
  token_url?: string;
  scope?: string;
  // rest_api
  api_base_url?: string;
  api_version?: string;
}

// ---------------------------------------------------------------------------
// Vendor icon map
// ---------------------------------------------------------------------------

const VENDOR_ICONS: Record<string, React.ReactNode> = {
  openemr:        <Heart size={20} />,
  epic:           <Zap size={20} />,
  cerner:         <Database size={20} />,
  athenahealth:   <Activity size={20} />,
  allscripts:     <FileText size={20} />,
  eclinicalworks: <Stethoscope size={20} />,
  drchrono:       <Clock size={20} />,
  nextgen:        <ArrowRight size={20} />,
  greenway:       <Leaf size={20} />,
  practice_fusion: <FlaskConical size={20} />,
  generic_fhir:   <Globe size={20} />,
  generic_rest:   <Link2 size={20} />,
};

const VENDOR_COLORS: Record<string, string> = {
  openemr:        "#059669",
  epic:           "#4F46E5",
  cerner:         "#0891B2",
  athenahealth:   "#7C3AED",
  allscripts:     "#EA580C",
  eclinicalworks: "#0369A1",
  drchrono:       "#D97706",
  nextgen:        "#64748B",
  greenway:       "#16A34A",
  practice_fusion: "#DB2777",
  generic_fhir:   "#2563EB",
  generic_rest:   "#64748B",
};

const CONNECTION_TYPE_LABELS: Record<string, string> = {
  direct_db: "Direct DB (Legacy)",
  fhir_r4:   "FHIR R4",
  rest_api:  "REST API",
};

const CONNECTION_TYPE_COLORS: Record<string, { bg: string; color: string }> = {
  direct_db: { bg: tokens.warningSoft,             color: tokens.warningStrong },
  fhir_r4:   { bg: `${tokens.primary}18`,          color: tokens.primary },
  rest_api:  { bg: `${tokens.accentPurple}18`,     color: tokens.accentPurple },
};

const AUTH_TYPES: { value: AuthType; label: string }[] = [
  { value: "none",    label: "No Authentication" },
  { value: "basic",   label: "Basic Auth" },
  { value: "bearer",  label: "Bearer Token" },
  { value: "oauth2",  label: "OAuth 2.0" },
  { value: "api_key", label: "API Key" },
];

const DEFAULT_FORM: ConnectionFormData = {
  name: "",
  vendor: "generic_fhir",
  connection_type: "fhir_r4",
  auth_type: "oauth2",
  ssl_enabled: true,
  db_type: "postgresql",
  scope: "system/*.read",
};

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

// Visual hierarchy: Connected (green) / Failing (red) / Never-Connected (grey) / Testing (amber)
function StatusBadge({ status, neverSynced = false }: { status: ConnectionStatus; neverSynced?: boolean }) {
  const map: Record<ConnectionStatus, { color: string; bg: string; dot: string; label: string; glow: string }> = {
    active:   { color: C.emerald600, bg: C.emerald100, dot: C.emerald500, label: neverSynced ? "Configured" : "Connected", glow: "0 0 8px rgba(16,185,129,0.4)" },
    inactive: { color: C.gray600,    bg: C.gray100,    dot: C.gray400,    label: neverSynced ? "Not Connected" : "Inactive", glow: "none" },
    error:    { color: C.red600,     bg: C.red100,     dot: C.red500,     label: "Failing",  glow: "0 0 8px rgba(239,68,68,0.4)" },
    testing:  { color: C.amber600,   bg: C.amber100,   dot: C.amber500,   label: "Testing",  glow: "0 0 8px rgba(245,158,11,0.4)" },
  };
  const s = map[status] ?? map.inactive;
  const isPulsing = status === "active" || status === "testing";
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: "4px 12px", borderRadius: 999,
      backgroundColor: s.bg, color: s.color,
      fontSize: 12, fontWeight: 600,
      border: `1px solid ${s.dot}20`,
      letterSpacing: "0.01em",
    }}>
      <span style={{
        width: 7, height: 7, borderRadius: "50%", backgroundColor: s.dot, flexShrink: 0,
        boxShadow: s.glow,
        animation: isPulsing ? "pulse 2s ease-in-out infinite" : "none",
      }} />
      {s.label}
    </span>
  );
}

function ConnectionTypeBadge({ type }: { type: ConnectionType }) {
  const s = CONNECTION_TYPE_COLORS[type];
  return (
    <span style={{
      display: "inline-flex", alignItems: "center",
      padding: "2px 8px", borderRadius: 4,
      backgroundColor: s.bg, color: s.color,
      fontSize: 11, fontWeight: 600,
    }}>
      {CONNECTION_TYPE_LABELS[type]}
    </span>
  );
}

function SyncStatusBadge({ status }: { status: SyncRecord["status"] }) {
  const map = {
    success: { color: C.emerald600, bg: C.emerald100 },
    failed:  { color: C.red600,     bg: C.red100 },
    running: { color: C.blue600,    bg: C.blue100 },
    partial: { color: C.amber600,   bg: C.amber100 },
  };
  const s = map[status] ?? map.failed;
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 999,
      backgroundColor: s.bg, color: s.color,
      fontSize: 11, fontWeight: 600,
    }}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

function VendorIcon({ vendor }: { vendor: string }) {
  const key = vendor.toLowerCase().replace(/\s+/g, "_");
  const icon = VENDOR_ICONS[key] ?? <Server size={20} />;
  const color = VENDOR_COLORS[key] ?? C.slate500;
  return (
    <div style={{
      width: 42, height: 42, borderRadius: 11,
      backgroundColor: `${color}14`,
      border: `1px solid ${color}20`,
      display: "flex", alignItems: "center", justifyContent: "center",
      color, flexShrink: 0,
      transition: "transform 200ms",
    }}>
      {icon}
    </div>
  );
}

function formatRelativeTime(iso?: string): string {
  if (!iso) return "Never";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function formatDateTime(iso?: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function formatDuration(seconds?: number): string {
  if (!seconds) return "—";
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

// ---------------------------------------------------------------------------
// Input / Label helpers
// ---------------------------------------------------------------------------

function Label({ children }: { children: React.ReactNode }) {
  return (
    <label style={{
      fontSize: 12, fontWeight: 600, color: C.slate600, display: "block", marginBottom: 6,
      letterSpacing: "0.03em", textTransform: "uppercase",
    }}>
      {children}
    </label>
  );
}

function Input({
  value, onChange, placeholder, type = "text", disabled,
}: {
  value: string | number | undefined;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  disabled?: boolean;
}) {
  return (
    <input
      type={type}
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      disabled={disabled}
      className="emr-input"
      style={{
        width: "100%", boxSizing: "border-box",
        padding: "9px 12px", borderRadius: 8,
        border: `1px solid ${C.slate200}`,
        fontSize: 13, color: C.slate900,
        background: disabled ? C.slate50 : C.white,
        transition: "border-color 200ms, box-shadow 200ms",
      }}
    />
  );
}

function Select({
  value, onChange, options, disabled,
}: {
  value: string | undefined;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  disabled?: boolean;
}) {
  return (
    <select
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      className="emr-input"
      style={{
        width: "100%", boxSizing: "border-box",
        padding: "9px 12px", borderRadius: 8,
        border: `1px solid ${C.slate200}`,
        fontSize: 13, color: C.slate900,
        background: disabled ? C.slate50 : C.white,
        transition: "border-color 200ms, box-shadow 200ms",
      }}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label style={{ display: "flex", alignItems: "center", gap: 8, cursor: "pointer", fontSize: 13, color: C.slate700 }}>
      <div
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        style={{
          width: 36, height: 20, borderRadius: 10,
          backgroundColor: checked ? C.primary : C.slate300,
          position: "relative", flexShrink: 0,
          transition: "background 150ms", cursor: "pointer",
        }}
      >
        <div style={{
          position: "absolute",
          width: 14, height: 14,
          borderRadius: "50%",
          backgroundColor: C.white,
          top: 3, left: checked ? 19 : 3,
          transition: "left 150ms",
          boxShadow: "0 1px 3px rgba(0,0,0,0.2)",
        }} />
      </div>
      {label}
    </label>
  );
}

function Btn({
  children, onClick, variant = "primary", disabled, loading, size = "md",
}: {
  children: React.ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "danger" | "ghost";
  disabled?: boolean;
  loading?: boolean;
  size?: "sm" | "md";
}) {
  const base: React.CSSProperties = {
    display: "inline-flex", alignItems: "center", gap: 6,
    borderRadius: 8, fontWeight: 600, cursor: disabled || loading ? "not-allowed" : "pointer",
    border: "none", transition: "opacity 150ms",
    opacity: disabled || loading ? 0.6 : 1,
    fontSize: size === "sm" ? 12 : 13,
    padding: size === "sm" ? "5px 10px" : "8px 14px",
  };
  const styles: Record<string, React.CSSProperties> = {
    primary:   { ...base, background: `linear-gradient(135deg, ${tokens.primary} 0%, ${tokens.infoBlue} 100%)`, color: C.white, boxShadow: "0 2px 8px rgba(37,99,235,0.3)" },
    secondary: { ...base, backgroundColor: C.white,   color: C.slate700, border: `1px solid ${C.slate200}`, boxShadow: "0 1px 2px rgba(0,0,0,0.04)" },
    danger:    { ...base, backgroundColor: C.red100,     color: C.red600, border: `1px solid ${C.red600}20` },
    ghost:     { ...base, backgroundColor: "transparent", color: C.slate600 },
  };
  return (
    <button className="btn-press" style={styles[variant]} onClick={onClick} disabled={disabled || loading} aria-busy={loading}>
      {loading && <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} />}
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Sync History Panel
// ---------------------------------------------------------------------------

function SyncHistoryPanel({ connectionId }: { connectionId: string }) {
  const { data: history = [], isLoading } = useQuery({
    queryKey: ["sync-history", connectionId],
    queryFn: () => getSyncHistory(connectionId),
    staleTime: 30_000,
  });

  if (isLoading) {
    return (
      <div style={{ padding: "16px 20px", color: C.slate400, fontSize: 13, display: "flex", alignItems: "center", gap: 8 }}>
        <Loader2 size={14} style={{ animation: "spin 1s linear infinite" }} /> Loading history...
      </div>
    );
  }

  if (history.length === 0) {
    return (
      <div style={{ padding: "16px 20px", color: C.slate400, fontSize: 13 }}>
        No sync history yet.
      </div>
    );
  }

  return (
    <div style={{ padding: "0 20px 16px" }}>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${C.slate100}` }}>
              {["Started", "Status", "Fetched", "Processed", "Failed", "Duration", "Error"].map((h) => (
                <th key={h} style={{ padding: "6px 10px", textAlign: "left", color: C.slate400, fontWeight: 600, whiteSpace: "nowrap" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {history.slice(0, 10).map((r) => (
              <tr key={r.id} style={{ borderBottom: `1px solid ${C.slate50}` }}>
                <td style={{ padding: "7px 10px", color: C.slate600, whiteSpace: "nowrap" }}>{formatDateTime(r.started_at)}</td>
                <td style={{ padding: "7px 10px" }}><SyncStatusBadge status={r.status} /></td>
                <td style={{ padding: "7px 10px", color: C.slate700, fontWeight: 600 }}>{r.records_fetched.toLocaleString()}</td>
                <td style={{ padding: "7px 10px", color: C.emerald600, fontWeight: 600 }}>{r.records_processed.toLocaleString()}</td>
                <td style={{ padding: "7px 10px", color: r.records_failed > 0 ? C.red600 : C.slate400, fontWeight: 600 }}>{r.records_failed.toLocaleString()}</td>
                <td style={{ padding: "7px 10px", color: C.slate500 }}>{formatDuration(r.duration_seconds)}</td>
                <td style={{ padding: "7px 10px", color: C.red600, maxWidth: 200, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.error_message ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Field Mapping Table
// ---------------------------------------------------------------------------

function FieldMappingTable({ mappings }: { mappings?: FieldMapping[] }) {
  if (!mappings || mappings.length === 0) {
    return (
      <div style={{ padding: "12px 20px 16px", color: C.slate400, fontSize: 13 }}>
        No field mappings configured.
      </div>
    );
  }
  return (
    <div style={{ padding: "0 20px 16px" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${C.slate100}` }}>
            <th style={{ padding: "6px 10px", textAlign: "left", color: C.slate400, fontWeight: 600 }}>Source Field</th>
            <th style={{ padding: "6px 10px", textAlign: "left", color: C.slate400, fontWeight: 600 }}>Target Field</th>
            <th style={{ padding: "6px 10px", textAlign: "left", color: C.slate400, fontWeight: 600 }}>Transform</th>
          </tr>
        </thead>
        <tbody>
          {mappings.map((m, i) => (
            <tr key={`${m.source_field}-${m.target_field}`} style={{ borderBottom: `1px solid ${C.slate50}` }}>
              <td style={{ padding: "6px 10px", color: C.slate700, fontFamily: "monospace", fontSize: 11 }}>{m.source_field}</td>
              <td style={{ padding: "6px 10px", color: C.primary,  fontFamily: "monospace", fontSize: 11 }}>{m.target_field}</td>
              <td style={{ padding: "6px 10px", color: C.slate500, fontFamily: "monospace", fontSize: 11 }}>{m.transform ?? "—"}</td>
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

interface ConnectionCardProps {
  conn: EmrConnection;
  onEdit: (conn: EmrConnection) => void;
  onDelete: (id: string) => void;
  onTest: (id: string) => void;
  onSync: (id: string) => void;
  onToggleActive: (id: string, isActive: boolean) => void;
  onAuthorize: (id: string) => void;
  testingId: string | null;
  syncingId: string | null;
}

function ConnectionCard({ conn, onEdit, onDelete, onTest, onSync, onToggleActive, onAuthorize, testingId, syncingId }: ConnectionCardProps) {
  const [expandedSection, setExpandedSection] = useState<"history" | "mappings" | null>(null);

  function toggleSection(s: "history" | "mappings") {
    setExpandedSection((prev) => (prev === s ? null : s));
  }

  const isTestLoading = testingId === conn.id;
  const isSyncLoading = syncingId === conn.id;

  return (
    <div className={`premium-card hover-lift animate-fade-in ${conn.status === "error" ? "card-glow-rose" : conn.status === "active" ? "card-glow-emerald" : ""}`} style={{
      overflow: "hidden",
      borderRadius: 12,
    }}>
      {/* Main row */}
      <div style={{ padding: "18px 20px", display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
        {/* Vendor icon */}
        <VendorIcon vendor={conn.vendor} />

        {/* Info */}
        <div style={{ flex: 1, minWidth: 180 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.slate900, marginBottom: 4 }}>{conn.name}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontSize: 12, color: C.slate500, textTransform: "capitalize" }}>{conn.vendor.replace(/_/g, " ")}</span>
            <ConnectionTypeBadge type={conn.connection_type} />
          </div>
        </div>

        {/* Status + last sync */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4, minWidth: 120 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <StatusBadge status={conn.status} neverSynced={!conn.last_sync_at} />
            <button
              onClick={() => onToggleActive(conn.id, conn.status === "inactive")}
              title={conn.status === "inactive" ? "Activate" : "Deactivate"}
              style={{
                fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: 4, cursor: "pointer", border: "none",
                backgroundColor: conn.status === "inactive" ? C.emerald100 : C.gray100,
                color: conn.status === "inactive" ? C.emerald600 : C.gray600,
              }}
            >
              {conn.status === "inactive" ? "Activate" : "Deactivate"}
            </button>
          </div>
          <span style={{
            fontSize: 11,
            color: conn.last_sync_at ? C.slate400 : C.amber600,
            fontWeight: conn.last_sync_at ? 400 : 600,
          }}>
            {conn.last_sync_at ? `Last sync: ${formatRelativeTime(conn.last_sync_at)}` : "Never synced"}
          </span>
        </div>

        {/* Error message if present */}
        {conn.status === "error" && conn.error_message && (
          <div style={{
            width: "100%",
            padding: "8px 12px",
            borderRadius: 6,
            backgroundColor: C.red100,
            color: C.red600,
            fontSize: 12,
            display: "flex", alignItems: "center", gap: 6,
          }}>
            <AlertTriangle size={13} />
            {conn.error_message}
          </div>
        )}

        {/* Actions */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
          {conn.connection_type === "fhir_r4" && (
            <Btn variant="secondary" size="sm" onClick={() => onAuthorize(conn.id)}>
              <Link2 size={13} />
              Authorize
            </Btn>
          )}
          <Btn variant="secondary" size="sm" onClick={() => onTest(conn.id)} loading={isTestLoading}>
            <TestTube2 size={13} />
            Test
          </Btn>
          <Btn variant="secondary" size="sm" onClick={() => onSync(conn.id)} loading={isSyncLoading}>
            <RefreshCw size={13} />
            Sync
          </Btn>
          <Btn variant="ghost" size="sm" onClick={() => onEdit(conn)}>
            <Pencil size={13} />
            Edit
          </Btn>
          <Btn variant="danger" size="sm" onClick={() => onDelete(conn.id)}>
            <Trash2 size={13} />
          </Btn>
        </div>
      </div>

      {/* Expandable sections */}
      <div style={{ borderTop: `1px solid ${C.slate100}`, display: "flex" }}>
        {(["history", "mappings"] as const).map((section) => {
          const isOpen = expandedSection === section;
          const label = section === "history" ? "Sync History" : "Field Mappings";
          return (
            <button
              key={section}
              onClick={() => toggleSection(section)}
              style={{
                flex: 1,
                display: "flex", alignItems: "center", justifyContent: "center", gap: 6,
                padding: "8px 12px",
                background: isOpen ? C.slate50 : "transparent",
                border: "none",
                borderRight: section === "history" ? `1px solid ${C.slate100}` : "none",
                cursor: "pointer",
                fontSize: 12, fontWeight: 600, color: isOpen ? C.primary : C.slate500,
                transition: "background 150ms",
              }}
              aria-expanded={isOpen}
            >
              {isOpen ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              {label}
            </button>
          );
        })}
      </div>

      {expandedSection === "history" && (
        <div style={{ borderTop: `1px solid ${C.slate100}` }}>
          <SyncHistoryPanel connectionId={conn.id} />
        </div>
      )}
      {expandedSection === "mappings" && (
        <div style={{ borderTop: `1px solid ${C.slate100}` }}>
          <FieldMappingTable mappings={conn.field_mappings} />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Add / Edit Modal — Step-based
// ---------------------------------------------------------------------------

type ModalStep = 1 | 2 | 3;

interface ModalProps {
  editTarget: EmrConnection | null;
  onClose: () => void;
  onSaved: () => void;
}

function ConnectionModal({ editTarget, onClose, onSaved }: ModalProps) {
  const isEdit = !!editTarget;
  const [step, setStep] = useState<ModalStep>(isEdit ? 2 : 1);
  const [form, setForm] = useState<ConnectionFormData>(
    isEdit
      ? {
          name: editTarget.name || "",
          vendor: editTarget.vendor,
          vendor_id: editTarget.vendor_id,
          connection_type: editTarget.connection_type,
          host: editTarget.host,
          port: editTarget.port,
          database_name: editTarget.database_name,
          username: editTarget.username,
          ssl_enabled: editTarget.ssl_enabled ?? true,
          db_type: editTarget.db_type ?? "postgresql",
          fhir_base_url: editTarget.fhir_base_url,
          auth_type: editTarget.auth_type ?? "oauth2",
          client_id: editTarget.client_id,
          token_url: editTarget.token_url,
          scope: editTarget.scope,
          api_base_url: editTarget.api_base_url,
          api_version: editTarget.api_version,
        }
      : { ...DEFAULT_FORM }
  );

  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [isTesting, setIsTesting] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const { data: vendors = [], isLoading: vendorsLoading } = useQuery({
    queryKey: ["emr-vendors"],
    queryFn: getVendorPresets,
    staleTime: 300_000,
    enabled: !isEdit,
  });

  function patch(updates: Partial<ConnectionFormData>) {
    setForm((prev) => ({ ...prev, ...updates }));
  }

  function validate(): boolean {
    const e: Record<string, string> = {};
    if (!(form.name || "").trim()) e.name = "Name is required";
    if (form.connection_type === "fhir_r4") {
      if (!form.fhir_base_url) e.fhir_base_url = "FHIR base URL is required";
    }
    if (form.connection_type === "rest_api") {
      if (!form.api_base_url) e.api_base_url = "API base URL is required";
    }
    setErrors(e);
    return Object.keys(e).length === 0;
  }

  async function handleTestConnection() {
    if (!editTarget) return;
    setIsTesting(true);
    setTestResult(null);
    try {
      const result = await testEmrConnection(editTarget.id);
      setTestResult(result);
    } catch {
      setTestResult({ success: false, message: "Connection test failed. Check your settings." });
    } finally {
      setIsTesting(false);
    }
  }

  async function handleSave() {
    if (!validate()) return;
    setIsSaving(true);
    try {
      if (isEdit) {
        await updateEmrConnection(editTarget.id, form);
      } else {
        await createEmrConnection(form);
      }
      onSaved();
      onClose();
    } catch (err: unknown) {
      const axErr = err as { response?: { data?: any; status?: number } };
      // Log save error for troubleshooting (non-debug)
      const detail = axErr?.response?.data?.detail;
      const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d: any) => `${d.loc?.join(".")}: ${d.msg}`).join("; ") : "Save failed. Please try again.";
      setErrors({ _global: msg });
    } finally {
      setIsSaving(false);
    }
  }

  // Step 1 — vendor grid
  function renderStep1() {
    return (
      <div>
        <p style={{ margin: "0 0 16px", fontSize: 13, color: C.slate500 }}>
          Select a vendor preset to auto-fill defaults, then configure connection details.
        </p>
        {vendorsLoading ? (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 12 }}>
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} style={{ height: 100, borderRadius: 10, border: `1px solid ${C.slate200}`, background: C.slate50, animation: "pulse 1.5s ease-in-out infinite" }} />
            ))}
          </div>
        ) : vendors.length === 0 ? (
          // Fallback static vendors when API is unavailable
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 12 }}>
            {FALLBACK_VENDORS.map((v) => renderVendorCard(v))}
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 12 }}>
            {vendors.map((v) => renderVendorCard(v))}
          </div>
        )}
      </div>
    );
  }

  function renderVendorCard(v: VendorPreset) {
    const isSelected = form.vendor_id === v.id || form.vendor === v.vendor;
    const color = VENDOR_COLORS[v.vendor] ?? C.slate500;
    return (
      <button
        key={v.id}
        onClick={() => {
          patch({
            vendor: v.vendor,
            vendor_id: v.id,
            connection_type: v.connection_type,
            ...(v.defaults ?? {}),
          });
        }}
        className="hover-lift"
        style={{
          padding: 14, borderRadius: 10, textAlign: "left",
          border: `2px solid ${isSelected ? color : C.slate200}`,
          background: isSelected ? `${color}0D` : C.white,
          cursor: "pointer", transition: "border-color 200ms, box-shadow 200ms, transform 200ms",
          boxShadow: isSelected ? `0 0 0 3px ${color}18` : "0 1px 3px rgba(0,0,0,0.04)",
        }}
      >
        <div style={{ color, marginBottom: 8 }}>
          {VENDOR_ICONS[v.vendor] ?? <Server size={20} />}
        </div>
        <div style={{ fontSize: 13, fontWeight: 700, color: C.slate900, marginBottom: 4 }}>{v.name}</div>
        <ConnectionTypeBadge type={v.connection_type} />
        {v.description && (
          <div style={{ fontSize: 11, color: C.slate400, marginTop: 6, lineHeight: 1.4 }}>{v.description}</div>
        )}
      </button>
    );
  }

  // Step 2 — connection details
  function renderStep2() {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {/* Name */}
        <div>
          <Label>Connection Name *</Label>
          <Input value={form.name} onChange={(v) => patch({ name: v })} placeholder="My OpenEMR Connection" />
          {errors.name && <div style={{ fontSize: 11, color: C.red600, marginTop: 4 }}>{errors.name}</div>}
        </div>

        {/* Connection type (read-only if vendor pre-filled) */}
        <div>
          <Label>Connection Type</Label>
          <Select
            value={form.connection_type}
            onChange={(v) => patch({ connection_type: v as ConnectionType })}
            options={[
              { value: "fhir_r4",   label: "FHIR R4" },
              { value: "rest_api",  label: "REST API" },
            ]}
          />
        </div>

        {/* FHIR R4 fields */}
        {form.connection_type === "fhir_r4" && (
          <>
            <div>
              <Label>FHIR Base URL *</Label>
              <Input value={form.fhir_base_url} onChange={(v) => patch({ fhir_base_url: v })} placeholder="https://your-emr.example.com/fhir/R4" />
              {errors.fhir_base_url && <div style={{ fontSize: 11, color: C.red600, marginTop: 4 }}>{errors.fhir_base_url}</div>}
            </div>
            <div>
              <Label>Auth Type</Label>
              <Select value={form.auth_type} onChange={(v) => patch({ auth_type: v as AuthType })} options={AUTH_TYPES} />
            </div>
            {(form.auth_type === "oauth2" || form.auth_type === "bearer") && (
              <>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                  <div>
                    <Label>Client ID</Label>
                    <Input value={form.client_id} onChange={(v) => patch({ client_id: v })} placeholder="client_id" />
                  </div>
                  <div>
                    <Label>Client Secret</Label>
                    <Input value={form.client_secret} onChange={(v) => patch({ client_secret: v })} type="password" placeholder="••••••••" />
                  </div>
                </div>
                <div>
                  <Label>Token URL</Label>
                  <Input value={form.token_url} onChange={(v) => patch({ token_url: v })} placeholder="https://auth.example.com/oauth2/token" />
                </div>
                <div>
                  <Label>Scope</Label>
                  <Input value={form.scope} onChange={(v) => patch({ scope: v })} placeholder="system/*.read" />
                </div>
              </>
            )}
          </>
        )}

        {/* REST API fields */}
        {form.connection_type === "rest_api" && (
          <>
            <div>
              <Label>API Base URL *</Label>
              <Input value={form.api_base_url} onChange={(v) => patch({ api_base_url: v })} placeholder="https://api.example.com" />
              {errors.api_base_url && <div style={{ fontSize: 11, color: C.red600, marginTop: 4 }}>{errors.api_base_url}</div>}
            </div>
            <div>
              <Label>API Version</Label>
              <Input value={form.api_version} onChange={(v) => patch({ api_version: v })} placeholder="v1" />
            </div>
            <div>
              <Label>Auth Type</Label>
              <Select value={form.auth_type} onChange={(v) => patch({ auth_type: v as AuthType })} options={AUTH_TYPES} />
            </div>
            {form.auth_type === "basic" && (
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <div>
                  <Label>Username</Label>
                  <Input value={form.username} onChange={(v) => patch({ username: v })} placeholder="username" />
                </div>
                <div>
                  <Label>Password</Label>
                  <Input value={form.password} onChange={(v) => patch({ password: v })} type="password" placeholder="••••••••" />
                </div>
              </div>
            )}
            {(form.auth_type === "bearer" || form.auth_type === "api_key") && (
              <div>
                <Label>{form.auth_type === "bearer" ? "Bearer Token" : "API Key"}</Label>
                <Input value={form.client_secret} onChange={(v) => patch({ client_secret: v })} type="password" placeholder="••••••••" />
              </div>
            )}
          </>
        )}

        {errors._global && (
          <div style={{ padding: "10px 14px", borderRadius: 8, backgroundColor: C.red100, color: C.red600, fontSize: 13, display: "flex", alignItems: "center", gap: 8 }}>
            <AlertTriangle size={14} />
            {errors._global}
          </div>
        )}
      </div>
    );
  }

  // Step 3 — test & save
  function renderStep3() {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div className="premium-card" style={{ padding: 16, borderRadius: 10 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: C.slate900, marginBottom: 12 }}>Connection Summary</div>
          {[
            ["Name",       form.name],
            ["Vendor",     form.vendor.replace(/_/g, " ")],
            ["Type",       CONNECTION_TYPE_LABELS[form.connection_type]],
            ...(form.connection_type === "fhir_r4"
              ? [["FHIR URL", form.fhir_base_url ?? ""], ["Auth", form.auth_type ?? ""]]
              : []),
            ...(form.connection_type === "rest_api"
              ? [["API URL", form.api_base_url ?? ""], ["Version", form.api_version ?? ""], ["Auth", form.auth_type ?? ""]]
              : []),
          ].map(([label, value]) => (
            <div key={label} style={{ display: "flex", justifyContent: "space-between", fontSize: 12, padding: "4px 0", borderBottom: `1px solid ${C.slate200}` }}>
              <span style={{ color: C.slate500 }}>{label}</span>
              <span style={{ color: C.slate800, fontWeight: 600, textAlign: "right", maxWidth: "60%", overflow: "hidden", textOverflow: "ellipsis" }}>{value}</span>
            </div>
          ))}
        </div>

        {isEdit && (
          <div>
            <Btn variant="secondary" onClick={handleTestConnection} loading={isTesting} disabled={isTesting}>
              <TestTube2 size={14} />
              Test Connection
            </Btn>
            {testResult && (
              <div style={{
                marginTop: 10,
                padding: "10px 14px",
                borderRadius: 8,
                backgroundColor: testResult.success ? C.emerald100 : C.red100,
                color: testResult.success ? C.emerald600 : C.red600,
                fontSize: 13, display: "flex", alignItems: "center", gap: 8,
              }}>
                {testResult.success ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
                {testResult.message}
              </div>
            )}
          </div>
        )}

        {errors._global && (
          <div style={{ padding: "10px 14px", borderRadius: 8, backgroundColor: C.red100, color: C.red600, fontSize: 13, display: "flex", alignItems: "center", gap: 8 }}>
            <AlertTriangle size={14} />
            {errors._global}
          </div>
        )}
      </div>
    );
  }

  const STEPS = isEdit ? [2, 3] : [1, 2, 3];

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{ position: "fixed", inset: 0, backgroundColor: "rgba(0,0,0,0.5)", zIndex: 99, backdropFilter: "blur(2px)" }}
        aria-hidden="true"
      />

      {/* Modal panel */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={isEdit ? "Edit EMR Connection" : "Add EMR Connection"}
        className="animate-fade-in"
        style={{
          position: "fixed", right: 0, top: 0, bottom: 0, zIndex: 100,
          width: "min(540px, 100vw)",
          backgroundColor: C.white,
          boxShadow: "-12px 0 50px rgba(0,0,0,0.18)",
          display: "flex", flexDirection: "column",
          fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        }}
      >
        {/* Header */}
        <div style={{
          padding: "20px 24px",
          borderBottom: `1px solid ${C.slate200}`,
          display: "flex", alignItems: "center", justifyContent: "space-between",
          flexShrink: 0,
        }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 700, color: C.slate900 }}>
              {isEdit ? "Edit Connection" : "Add EMR Connection"}
            </div>
            <div style={{ fontSize: 12, color: C.slate400, marginTop: 2 }}>
              {step === 1 ? "Step 1 — Select Vendor" : step === 2 ? "Step 2 — Connection Details" : "Step 3 — Test & Save"}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", cursor: "pointer", color: C.slate400, display: "flex", padding: 4, borderRadius: 6 }}
            aria-label="Close"
          >
            <X size={20} />
          </button>
        </div>

        {/* Progress steps */}
        <div style={{
          display: "flex", padding: "12px 24px", gap: 8, flexShrink: 0,
          borderBottom: `1px solid ${C.slate100}`, background: C.slate50,
        }}>
          {(isEdit ? ["Details", "Save"] : ["Vendor", "Details", "Save"]).map((label, i) => {
            const s = isEdit ? i + 2 : i + 1;
            const isDone = step > s;
            const isActive = step === s;
            return (
              <div key={label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                {i > 0 && <div style={{ width: 24, height: 1, backgroundColor: C.slate200 }} />}
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <div style={{
                    width: 22, height: 22, borderRadius: "50%",
                    backgroundColor: isDone ? C.emerald500 : isActive ? C.primary : C.slate200,
                    color: isDone || isActive ? C.white : C.slate400,
                    fontSize: 11, fontWeight: 700,
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}>
                    {isDone ? <CheckCircle2 size={13} /> : i + 1}
                  </div>
                  <span style={{ fontSize: 12, fontWeight: isActive ? 700 : 500, color: isActive ? C.slate900 : C.slate400 }}>
                    {label}
                  </span>
                </div>
              </div>
            );
          })}
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: "auto", padding: "24px" }}>
          {step === 1 && renderStep1()}
          {step === 2 && renderStep2()}
          {step === 3 && renderStep3()}
        </div>

        {/* Footer */}
        <div style={{
          padding: "16px 24px",
          borderTop: `1px solid ${C.slate200}`,
          display: "flex", alignItems: "center", justifyContent: "space-between",
          flexShrink: 0,
        }}>
          <Btn variant="ghost" onClick={step > (isEdit ? 2 : 1) ? () => setStep((s) => (s - 1) as ModalStep) : onClose}>
            {step > (isEdit ? 2 : 1) ? "Back" : "Cancel"}
          </Btn>
          <div style={{ display: "flex", gap: 8 }}>
            {step < 3 ? (
              <Btn
                variant="primary"
                onClick={() => {
                  if (step === 2 && !validate()) return;
                  setStep((s) => (s + 1) as ModalStep);
                }}
              >
                Continue
              </Btn>
            ) : (
              <Btn variant="primary" onClick={handleSave} loading={isSaving}>
                {isEdit ? "Save Changes" : "Create Connection"}
              </Btn>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Live Auto-Sync Panel
// ---------------------------------------------------------------------------

function useRelativeTime(iso: string | null | undefined): string {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!iso) return;
    const id = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [iso]);

  if (!iso) return "Never";
  const diffSec = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diffSec < 5) return "Just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const mins = Math.floor(diffSec / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  return `${hrs}h ago`;
}

function useCountdown(seconds: number | null | undefined): string {
  const [, setTick] = useState(0);
  const startRef = useRef<{ at: number; val: number }>({ at: Date.now(), val: seconds ?? 0 });
  useEffect(() => {
    if (seconds == null) return;
    startRef.current.at = Date.now();
    startRef.current.val = seconds;
    const id = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [seconds]);

  if (seconds == null) return "";
  const elapsed = Math.floor((Date.now() - startRef.current.at) / 1000);
  const remaining = Math.max(0, startRef.current.val - elapsed);
  return `${remaining}s`;
}

function LiveAutoSyncPanel() {
  const { data: status, isError } = useQuery({
    queryKey: ["auto-sync-status"],
    queryFn: getAutoSyncStatus,
    refetchInterval: 5000,
    staleTime: 4000,
    retry: 1,
  });

  const relTime = useRelativeTime(status?.last_run_at);
  const countdown = useCountdown(status?.next_run_in_seconds);

  // 404 / not configured yet
  if (status === null || isError) {
    return (
      <div className="premium-card animate-slide-up" style={{
        borderRadius: 14,
        overflow: "hidden",
        marginBottom: 24,
        padding: "20px 24px",
        display: "flex",
        alignItems: "center",
        gap: 14,
      }}>
        <div style={{
          width: 36, height: 36, borderRadius: 9,
          backgroundColor: C.slate100, display: "flex", alignItems: "center", justifyContent: "center",
          color: C.slate400, flexShrink: 0,
        }}>
          <RefreshCw size={18} />
        </div>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.slate700 }}>Live Auto-Sync</div>
          <div style={{ fontSize: 12, color: C.slate400, marginTop: 2 }}>Auto-sync not yet configured</div>
        </div>
      </div>
    );
  }

  if (status === undefined) {
    // loading skeleton
    return (
      <div className="premium-card animate-slide-up" style={{
        borderRadius: 14, overflow: "hidden", marginBottom: 24,
        height: 100, animation: "pulse 1.5s ease-in-out infinite", backgroundColor: C.slate50,
      }} />
    );
  }

  const isEnabled = status.enabled;
  const hasError = !!status.last_error;
  const isRunning = status.current_cycle_running;

  // Status pill config
  const statusConfig = hasError
    ? { label: "Error", bg: C.red100, color: C.red600, dot: C.red500, glow: "0 0 8px rgba(239,68,68,0.4)" }
    : !isEnabled
    ? { label: "Paused", bg: C.slate100, color: C.slate600, dot: C.slate400, glow: "none" }
    : isRunning
    ? { label: "Running", bg: C.amber100, color: C.amber600, dot: C.amber500, glow: "0 0 8px rgba(245,158,11,0.4)" }
    : { label: "Active", bg: C.emerald100, color: C.emerald600, dot: C.emerald500, glow: "0 0 8px rgba(16,185,129,0.4)" };

  return (
    <div
      className="premium-card animate-slide-up"
      style={{ borderRadius: 14, overflow: "hidden", marginBottom: 24 }}
    >
      {/* Header row */}
      <div style={{
        padding: "16px 24px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: 12,
        background: isEnabled
          ? `linear-gradient(135deg, ${C.emerald100} 0%, ${C.white} 100%)`
          : `linear-gradient(135deg, ${C.slate50} 0%, ${C.white} 100%)`,
        borderBottom: `1px solid ${C.slate100}`,
      }}>
        {/* Title + pulse dot */}
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ position: "relative", width: 10, height: 10, flexShrink: 0 }}>
            <span style={{
              position: "absolute", inset: 0, borderRadius: "50%",
              backgroundColor: statusConfig.dot,
              animation: isEnabled && !hasError ? "liveAutoSyncPing 1.5s ease-in-out infinite" : "none",
              opacity: 0.5,
            }} />
            <span style={{
              position: "absolute", inset: 1, borderRadius: "50%",
              backgroundColor: statusConfig.dot,
            }} />
          </div>
          <span style={{ fontSize: 15, fontWeight: 700, color: C.slate900 }}>Live Auto-Sync</span>
          {countdown && isEnabled && !hasError && (
            <span style={{
              fontSize: 11, fontWeight: 600,
              padding: "2px 8px", borderRadius: 4,
              backgroundColor: C.slate100, color: C.slate500,
            }}>
              Next: {countdown}
            </span>
          )}
        </div>

        {/* Status pill */}
        <span style={{
          display: "inline-flex", alignItems: "center", gap: 6,
          padding: "5px 14px", borderRadius: 999,
          backgroundColor: statusConfig.bg, color: statusConfig.color,
          fontSize: 12, fontWeight: 700,
          border: `1px solid ${statusConfig.dot}30`,
          boxShadow: statusConfig.glow,
        }}>
          <span style={{
            width: 7, height: 7, borderRadius: "50%",
            backgroundColor: statusConfig.dot,
            animation: isEnabled && !hasError ? "pulse 2s ease-in-out infinite" : "none",
          }} />
          {statusConfig.label}
        </span>
      </div>

      {/* KPI tiles */}
      <div className="auto-sync-kpi-grid" style={{
        display: "grid",
        gridTemplateColumns: "repeat(3, 1fr)",
        gap: 0,
        padding: "0",
      }}>
        {/* Status tile */}
        <div style={{
          padding: "16px 20px",
          borderRight: `1px solid ${C.slate100}`,
          display: "flex", flexDirection: "column", gap: 4,
        }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: C.slate400, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Status
          </div>
          <div style={{ fontSize: 20, fontWeight: 800, color: statusConfig.color, lineHeight: 1.2 }}>
            {statusConfig.label}
          </div>
          <div style={{ fontSize: 11, color: C.slate400 }}>
            {isRunning ? "Cycle in progress..." : isEnabled ? "Polling active" : "Sync paused"}
          </div>
        </div>

        {/* Last sync tile */}
        <div style={{
          padding: "16px 20px",
          borderRight: `1px solid ${C.slate100}`,
          display: "flex", flexDirection: "column", gap: 4,
        }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: C.slate400, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Last Sync
          </div>
          <div style={{ fontSize: 20, fontWeight: 800, color: C.slate900, lineHeight: 1.2 }}>
            {relTime}
          </div>
          <div style={{ fontSize: 11, color: C.slate400 }}>
            {status.new_patients_last_cycle > 0
              ? `+${status.new_patients_last_cycle} new patient${status.new_patients_last_cycle !== 1 ? "s" : ""}`
              : "No new patients"}
          </div>
        </div>

        {/* Total synced today tile */}
        <div style={{
          padding: "16px 20px",
          display: "flex", flexDirection: "column", gap: 4,
        }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: C.slate400, textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Total Synced Today
          </div>
          <div style={{ fontSize: 20, fontWeight: 800, color: C.primary, lineHeight: 1.2 }}>
            {status.total_synced_today.toLocaleString()}
          </div>
          <div style={{ fontSize: 11, color: C.slate400 }}>patients ingested</div>
        </div>
      </div>

      {/* Error strip */}
      {status.last_error && (
        <div style={{
          padding: "10px 20px",
          backgroundColor: C.red100,
          borderTop: `1px solid ${C.red500}20`,
          display: "flex", alignItems: "center", gap: 8,
          color: C.red600, fontSize: 12,
        }}>
          <AlertTriangle size={13} style={{ flexShrink: 0 }} />
          <span style={{ fontWeight: 600 }}>Last error:&nbsp;</span>
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{status.last_error}</span>
        </div>
      )}
    </div>
  );
}

// Fallback vendors rendered when /api/emr/vendors is unavailable
const FALLBACK_VENDORS: VendorPreset[] = [
  { id: "openemr",        vendor: "openemr",        name: "OpenEMR",           connection_type: "fhir_r4",   description: "OpenEMR FHIR R4 endpoint" },
  { id: "epic",           vendor: "epic",            name: "Epic",              connection_type: "fhir_r4",   description: "Epic FHIR R4 endpoint" },
  { id: "cerner",         vendor: "cerner",          name: "Cerner / Oracle",   connection_type: "fhir_r4",   description: "Cerner Millennium FHIR R4" },
  { id: "athenahealth",   vendor: "athenahealth",    name: "athenahealth",      connection_type: "rest_api",  description: "athenaNet REST API" },
  { id: "allscripts",     vendor: "allscripts",      name: "Allscripts",        connection_type: "rest_api",  description: "Allscripts REST integration" },
  { id: "eclinicalworks", vendor: "eclinicalworks",  name: "eClinicalWorks",    connection_type: "fhir_r4",   description: "eCW FHIR R4 endpoint" },
  { id: "drchrono",       vendor: "drchrono",        name: "DrChrono",          connection_type: "rest_api",  description: "DrChrono REST API" },
  { id: "nextgen",        vendor: "nextgen",         name: "NextGen",           connection_type: "fhir_r4",   description: "NextGen FHIR R4 endpoint" },
  { id: "greenway",       vendor: "greenway",        name: "Greenway Health",   connection_type: "rest_api",  description: "Greenway PrimeSUITE REST" },
  { id: "practice_fusion", vendor: "practice_fusion", name: "Practice Fusion",  connection_type: "fhir_r4",   description: "Practice Fusion FHIR R4" },
  { id: "generic_fhir",   vendor: "generic_fhir",    name: "Generic FHIR R4",   connection_type: "fhir_r4",   description: "Any FHIR R4 compliant server" },
  { id: "generic_rest",   vendor: "generic_rest",    name: "Generic REST API",  connection_type: "rest_api",  description: "Custom REST API integration" },
];

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function EmrConfigPage() {
  const qc = useQueryClient();

  const [showModal, setShowModal] = useState(false);
  const [editTarget, setEditTarget] = useState<EmrConnection | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ message: string; type: "success" | "error" } | null>(null);
  const [aiToggling, setAiToggling] = useState(false);

  const { data: pipelineSettings, refetch: refetchPipeline } = useQuery({
    queryKey: ["pipeline-settings"],
    queryFn: getPipelineSettings,
    staleTime: 10_000,
    retry: 1,
  });

  const { data: connections = [], isLoading, isError, refetch } = useQuery({
    queryKey: ["emr-connections"],
    queryFn: getEmrConnections,
    staleTime: 30_000,
    retry: 1,
  });

  async function handleToggleAI() {
    setAiToggling(true);
    try {
      const newMode = pipelineSettings?.pipeline_mode === "auto_ai" ? "auto_basic" : "auto_ai";
      const newAi = newMode === "auto_ai";
      await updatePipelineSettings({ pipeline_mode: newMode, ai_analysis_enabled: newAi });
      refetchPipeline();
      showToast(
        newAi
          ? "AI Analysis enabled. Every EMR sync will trigger Gemini AI analysis."
          : "AI Analysis disabled. Pipeline runs without AI (basic mode).",
        "success",
      );
    } catch {
      showToast("Failed to update pipeline settings.", "error");
    } finally {
      setAiToggling(false);
    }
  }

  function showToast(message: string, type: "success" | "error") {
    setToast({ message, type });
    setTimeout(() => setToast(null), 4000);
  }

  async function handleTest(id: string) {
    setTestingId(id);
    try {
      const result = await testEmrConnection(id);
      showToast(result.message, result.success ? "success" : "error");
    } catch {
      showToast("Test failed. Unable to reach connection.", "error");
    } finally {
      setTestingId(null);
      qc.invalidateQueries({ queryKey: ["emr-connections"] });
    }
  }

  async function handleSync(id: string) {
    setSyncingId(id);
    try {
      await syncEmrConnection(id);
      showToast("Sync job started successfully.", "success");
      qc.invalidateQueries({ queryKey: ["emr-connections"] });
      qc.invalidateQueries({ queryKey: ["sync-history", id] });
    } catch {
      showToast("Failed to start sync.", "error");
    } finally {
      setSyncingId(null);
    }
  }

  async function handleAuthorize(id: string) {
    try {
      const res = await api.get(`/api/emr/connections/${id}/oauth2/authorize`);
      const url = res.data.authorize_url;
      if (url) {
        window.location.href = url;
      } else {
        showToast("No authorization URL returned.", "error");
      }
    } catch (err: any) {
      const detail = err.response?.data?.detail || err.message || "Failed to get authorization URL";
      showToast(String(detail), "error");
    }
  }

  async function handleToggleActive(id: string, activate: boolean) {
    try {
      await toggleEmrConnectionActive(id, activate);
      showToast(
        activate
          ? "Connection activated. Syncing data & calculating RAF scores..."
          : "Connection deactivated.",
        "success",
      );
      // Clear ALL cached queries — switching connections changes everything
      qc.clear();
      qc.invalidateQueries();
      // Auto-refresh after pipeline has time to complete
      if (activate) {
        setTimeout(() => qc.invalidateQueries(), 15000);
        setTimeout(() => qc.invalidateQueries(), 45000);
      }
    } catch {
      showToast("Failed to update connection status.", "error");
    }
  }

  async function handleDelete(id: string) {
    setDeleteConfirmId(null);
    try {
      await deleteEmrConnection(id);
      showToast("Connection deleted.", "success");
      qc.invalidateQueries({ queryKey: ["emr-connections"] });
    } catch {
      showToast("Failed to delete connection.", "error");
    }
  }

  function handleEdit(conn: EmrConnection) {
    setEditTarget(conn);
    setShowModal(true);
  }

  function handleAdd() {
    setEditTarget(null);
    setShowModal(true);
  }

  function handleModalClose() {
    setShowModal(false);
    setEditTarget(null);
  }

  function handleModalSaved() {
    qc.invalidateQueries({ queryKey: ["emr-connections"] });
    showToast(editTarget ? "Connection updated." : "Connection created.", "success");
  }

  // Derived stats
  const activeCount = connections.filter((c) => c.status === "active").length;
  const errorCount  = connections.filter((c) => c.status === "error").length;
  const lastSyncTimes = connections.map((c) => c.last_sync_at).filter(Boolean) as string[];
  const mostRecentSync = lastSyncTimes.length
    ? lastSyncTimes.sort((a, b) => new Date(b).getTime() - new Date(a).getTime())[0]
    : undefined;

  // ─── Render ────────────────────────────────────────────────────────────────

  return (
    <div style={{
      minHeight: "100vh",
      backgroundColor: C.slate50,
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    }}>
      {/* Inject keyframes for spinner + input focus */}
      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        @keyframes liveAutoSyncPing { 0% { transform: scale(1); opacity: 0.5; } 70% { transform: scale(2.4); opacity: 0; } 100% { transform: scale(2.4); opacity: 0; } }
        .emr-input:focus { border-color: ${tokens.infoBlue} !important; box-shadow: 0 0 0 3px rgba(59,130,246,0.12) !important; }
        .emr-input::placeholder { color: ${tokens.slate400}; }
        @media (max-width: 480px) {
          .auto-sync-kpi-grid { grid-template-columns: 1fr !important; }
          .auto-sync-kpi-grid > div { border-right: none !important; border-bottom: 1px solid ${tokens.slate100}; }
          .auto-sync-kpi-grid > div:last-child { border-bottom: none; }
        }
      `}</style>

      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "32px 24px" }}>
        {/* Page header */}
        <PageHeader
          title="EMR Configuration"
          subtitle="Manage EMR connections, sync schedules, and field mappings for data ingestion."
          icon={<Settings2 size={22} className="animate-fade-in" />}
          actions={
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <Btn variant="secondary" onClick={() => refetch()}>
                <RefreshCw size={14} />
                Refresh
              </Btn>
              <Btn variant="primary" onClick={handleAdd}>
                <Plus size={14} />
                Add EMR Connection
              </Btn>
            </div>
          }
        />

        {/* Live Auto-Sync Panel */}
        <LiveAutoSyncPanel />

        {/* Stats bar */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 16, marginBottom: 32 }}>
          <div className="animate-slide-up stagger-1">
            <StatCard
              label="Total Connections"
              value={connections.length}
              icon={<Database size={18} />}
              color={C.primary}
            />
          </div>
          <div className="animate-slide-up stagger-2">
            <StatCard
              label="Active"
              value={activeCount}
              icon={<CheckCircle2 size={18} />}
              color={C.emerald600}
              subtitle={`${connections.length - activeCount} inactive`}
            />
          </div>
          <div className="animate-slide-up stagger-3">
            <StatCard
              label="Last Sync"
              value={formatRelativeTime(mostRecentSync)}
              icon={<Clock size={18} />}
              color={C.amber600}
              subtitle={mostRecentSync ? formatDateTime(mostRecentSync) : "No syncs yet"}
            />
          </div>
          <div className="animate-slide-up stagger-4">
            <StatCard
              label="Errors"
              value={errorCount}
              icon={<AlertTriangle size={18} />}
              color={errorCount > 0 ? C.red600 : C.emerald600}
              subtitle={errorCount > 0 ? "Connections need attention" : "All connections healthy"}
            />
          </div>
        </div>

        {/* AI Pipeline Control */}
        <div className="premium-card animate-slide-up stagger-4" style={{
          borderRadius: 14,
          overflow: "hidden",
          marginBottom: 24,
        }}>
          <div style={{
            padding: "20px 24px",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background: pipelineSettings?.pipeline_mode === "auto_ai"
              ? `linear-gradient(135deg, ${tokens.primarySoft} 0%, ${tokens.primary}18 100%)`
              : `linear-gradient(135deg, ${C.slate50} 0%, ${C.white} 100%)`,
            borderBottom: `1px solid ${C.slate100}`,
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
              <div style={{
                width: 40, height: 40, borderRadius: 10,
                display: "flex", alignItems: "center", justifyContent: "center",
                background: pipelineSettings?.pipeline_mode === "auto_ai"
                  ? `linear-gradient(135deg, ${tokens.primary}, ${tokens.accentPurple})`
                  : C.slate200,
                color: pipelineSettings?.pipeline_mode === "auto_ai" ? tokens.white : C.slate500,
              }}>
                <Zap size={20} />
              </div>
              <div>
                <div style={{ fontWeight: 700, fontSize: 15, color: C.slate900 }}>
                  AI Analysis Pipeline
                </div>
                <div style={{ fontSize: 12, color: C.slate500, marginTop: 2 }}>
                  {pipelineSettings?.pipeline_mode === "auto_ai"
                    ? "Gemini AI runs automatically on every EMR sync (8-phase pipeline)"
                    : pipelineSettings?.pipeline_mode === "manual"
                    ? "Manual mode — all pipeline steps triggered manually"
                    : "Basic mode — EMR Sync, Normalize, RAF Calc only (no AI)"}
                </div>
              </div>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              {/* Mode badge */}
              <span style={{
                padding: "4px 10px",
                borderRadius: 6,
                fontSize: 11,
                fontWeight: 600,
                letterSpacing: "0.02em",
                background: pipelineSettings?.pipeline_mode === "auto_ai" ? `${tokens.primary}18` : C.slate100,
                color: pipelineSettings?.pipeline_mode === "auto_ai" ? tokens.primaryDark : C.slate600,
              }}>
                {pipelineSettings?.pipeline_mode === "auto_ai" ? "AUTO AI" : pipelineSettings?.pipeline_mode === "manual" ? "MANUAL" : "BASIC"}
              </span>

              {/* Toggle switch */}
              <button
                onClick={handleToggleAI}
                disabled={aiToggling}
                style={{
                  position: "relative",
                  width: 52,
                  height: 28,
                  borderRadius: 14,
                  border: "none",
                  cursor: aiToggling ? "wait" : "pointer",
                  background: pipelineSettings?.pipeline_mode === "auto_ai"
                    ? `linear-gradient(135deg, ${tokens.primary}, ${tokens.accentPurple})`
                    : C.slate300,
                  transition: "background 0.3s ease",
                  flexShrink: 0,
                }}
                title={pipelineSettings?.pipeline_mode === "auto_ai" ? "Disable AI Analysis" : "Enable AI Analysis"}
              >
                <div style={{
                  position: "absolute",
                  top: 3,
                  left: pipelineSettings?.pipeline_mode === "auto_ai" ? 27 : 3,
                  width: 22,
                  height: 22,
                  borderRadius: 11,
                  background: "#fff",
                  boxShadow: "0 1px 3px rgba(0,0,0,0.2)",
                  transition: "left 0.3s ease",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}>
                  {aiToggling && <Loader2 size={12} style={{ animation: "spin 1s linear infinite", color: C.slate400 }} />}
                </div>
              </button>
            </div>
          </div>

          {/* Pipeline phases indicator */}
          {pipelineSettings?.pipeline_mode === "auto_ai" && (
            <div style={{
              padding: "12px 24px",
              display: "flex",
              alignItems: "center",
              gap: 6,
              fontSize: 11,
              color: C.slate500,
              overflowX: "auto",
            }}>
              {["EMR Sync", "Normalize", "AI Analysis", "RAF Calc", "HCC Hierarchy", "Suspects", "Gap Generation", "Webhooks"].map((phase, i) => (
                <span key={phase} style={{ display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap" }}>
                  <span style={{
                    padding: "2px 8px",
                    borderRadius: 4,
                    background: i === 2 ? `${tokens.primary}18` : C.slate100,
                    color: i === 2 ? tokens.primaryDark : C.slate600,
                    fontWeight: i === 2 ? 700 : 500,
                    fontSize: 10,
                  }}>
                    {phase}
                  </span>
                  {i < 7 && <ArrowRight size={10} style={{ color: C.slate300 }} />}
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Connection list */}
        <div className="premium-card animate-slide-up stagger-5" style={{
          overflow: "hidden",
          borderRadius: 14,
        }}>
          {/* Section header */}
          <div style={{ padding: "18px 20px", borderBottom: `1px solid ${C.slate100}`, background: `linear-gradient(135deg, ${C.slate50} 0%, ${C.white} 100%)` }}>
            <SectionHeader
              title="Connections"
              icon={<Server size={16} />}
              count={connections.length}
              action={
                <Btn variant="secondary" size="sm" onClick={handleAdd}>
                  <Plus size={12} />
                  Add
                </Btn>
              }
            />
          </div>

          {/* Loading */}
          {isLoading && (
            <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} style={{ height: 88, borderRadius: 10, border: `1px solid ${C.slate200}`, background: C.slate50, animation: "pulse 1.5s ease-in-out infinite" }} />
              ))}
            </div>
          )}

          {/* Error */}
          {isError && !isLoading && (
            <div style={{ padding: "24px 20px" }}>
              <div style={{
                padding: "14px 18px", borderRadius: 10,
                backgroundColor: C.red100, color: C.red600,
                fontSize: 13, display: "flex", alignItems: "center", gap: 8,
              }}>
                <AlertTriangle size={15} />
                Failed to load EMR connections. The backend endpoint may not be configured yet.
                <button
                  onClick={() => refetch()}
                  style={{ marginLeft: "auto", background: "none", border: "none", cursor: "pointer", color: C.red600, fontWeight: 600, fontSize: 13 }}
                >
                  Retry
                </button>
              </div>
            </div>
          )}

          {/* Empty state */}
          {!isLoading && !isError && connections.length === 0 && (
            <div style={{ padding: "48px 24px", textAlign: "center" }}>
              <div style={{
                display: "inline-flex", alignItems: "center", justifyContent: "center",
                width: 60, height: 60, borderRadius: 16,
                backgroundColor: C.blue100, color: C.blue600, marginBottom: 16,
              }}>
                <Database size={28} />
              </div>
              <div style={{ fontSize: 15, fontWeight: 700, color: C.slate900, marginBottom: 6 }}>
                No EMR connections yet
              </div>
              <div style={{ fontSize: 13, color: C.slate500, marginBottom: 20, maxWidth: 380, margin: "0 auto 20px" }}>
                Connect your first EMR to start syncing patient data for RAF scoring. Supports FHIR R4 and REST API integrations.
              </div>
              <Btn variant="primary" onClick={handleAdd}>
                <Plus size={14} />
                Connect an EMR
              </Btn>
            </div>
          )}

          {/* Connection cards */}
          {!isLoading && !isError && connections.length > 0 && (
            <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 14 }}>
              {connections.map((conn, idx) => (
                <div key={conn.id} className={`animate-slide-up stagger-${Math.min(idx + 1, 6)}`}>
                  <ConnectionCard
                    conn={conn}
                    onEdit={handleEdit}
                    onDelete={(id) => setDeleteConfirmId(id)}
                    onTest={handleTest}
                    onSync={handleSync}
                    onToggleActive={handleToggleActive}
                    onAuthorize={handleAuthorize}
                    testingId={testingId}
                    syncingId={syncingId}
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Delete confirmation dialog */}
      {deleteConfirmId && (
        <>
          <div
            onClick={() => setDeleteConfirmId(null)}
            style={{ position: "fixed", inset: 0, backgroundColor: "rgba(0,0,0,0.4)", zIndex: 99 }}
            aria-hidden="true"
          />
          <div
            role="alertdialog"
            aria-modal="true"
            aria-label="Confirm deletion"
            className="premium-card animate-scale-in"
            style={{
              position: "fixed", top: "50%", left: "50%",
              transform: "translate(-50%, -50%)",
              zIndex: 100,
              padding: 28,
              width: "min(420px, 90vw)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
              <div style={{ width: 40, height: 40, borderRadius: 10, backgroundColor: C.red100, display: "flex", alignItems: "center", justifyContent: "center", color: C.red600, flexShrink: 0 }}>
                <Trash2 size={18} />
              </div>
              <div>
                <div style={{ fontSize: 15, fontWeight: 700, color: C.slate900 }}>Delete Connection</div>
                <div style={{ fontSize: 13, color: C.slate500, marginTop: 2 }}>This action cannot be undone.</div>
              </div>
            </div>
            <p style={{ margin: "0 0 20px", fontSize: 13, color: C.slate600, lineHeight: 1.5 }}>
              Are you sure you want to delete this EMR connection? All sync history and configuration will be permanently removed.
            </p>
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <Btn variant="secondary" onClick={() => setDeleteConfirmId(null)}>Cancel</Btn>
              <Btn variant="danger" onClick={() => handleDelete(deleteConfirmId)}>Delete</Btn>
            </div>
          </div>
        </>
      )}

      {/* Add/Edit modal */}
      {showModal && (
        <ConnectionModal
          editTarget={editTarget}
          onClose={handleModalClose}
          onSaved={handleModalSaved}
        />
      )}

      {/* Toast notification */}
      {toast && (
        <div
          role="alert"
          aria-live="polite"
          className="animate-slide-up premium-shadow"
          style={{
            position: "fixed", bottom: 24, right: 24, zIndex: 200,
            padding: "14px 20px",
            borderRadius: 12,
            backgroundColor: toast.type === "success" ? C.emerald600 : C.red600,
            color: C.white,
            fontSize: 13, fontWeight: 600,
            display: "flex", alignItems: "center", gap: 8,
            maxWidth: 360,
          }}
        >
          {toast.type === "success" ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
          {toast.message}
        </div>
      )}
    </div>
  );
}
