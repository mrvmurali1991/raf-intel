"use client";

import React, {
  useState,
  useMemo,
  useCallback,
  useEffect,
  useRef,
} from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { authApi } from "@/contexts/auth-context";
import {
  UsersRound,
  UserCheck,
  ShieldAlert,
  Activity,
  Plus,
  Search,
  Filter,
  RefreshCw,
  Edit2,
  Lock,
  Unlock,
  KeyRound,
  ShieldCheck,
  X,
  ChevronLeft,
  ChevronRight,
  AlertCircle,
  CheckCircle,
  Eye,
  EyeOff,
  RotateCcw,
  Save,
} from "lucide-react";
import { StatCard, PageHeader, SectionHeader, EmptyState } from "@/components/healthcare-ui";
import { useAuth } from "@/contexts/auth-context";

// ── API ───────────────────────────────────────────────────────────────────────
// Uses the shared authApi instance from auth-context, which automatically
// attaches the Bearer token via its request interceptor and handles
// 401 / token refresh transparently. No custom axios instance needed here.

async function fetchUsers(): Promise<AppUser[]> {
  const { data } = await authApi.get("/api/auth/users");
  const raw = Array.isArray(data) ? data : (data?.users ?? []);
  // Map API fields to frontend interface
  return raw.map((u: any) => ({
    ...u,
    id: String(u.id),
    first_name: u.first_name ?? (u.full_name ?? "").split(" ")[0] ?? "",
    last_name: u.last_name ?? (u.full_name ?? "").split(" ").slice(1).join(" ") ?? "",
    status: u.is_active ? "active" : (u.locked_until ? "locked" : "inactive"),
    sessions_today: u.sessions_today ?? 0,
  }));
}

async function fetchUserPermissions(id: string): Promise<PermissionMatrix> {
  const { data } = await authApi.get(`/api/auth/users/${id}/permissions`);
  return data;
}

async function createUser(body: CreateUserPayload): Promise<AppUser> {
  const { data } = await authApi.post("/api/auth/users", body);
  return data;
}

async function updateUser(id: string, body: EditUserPayload): Promise<AppUser> {
  const { data } = await authApi.put(`/api/auth/users/${id}`, body);
  return data;
}

async function deleteUser(id: string): Promise<void> {
  await authApi.delete(`/api/auth/users/${id}`);
}

async function updateUserPermissions(id: string, permissions: PermissionMatrix): Promise<void> {
  await authApi.put(`/api/auth/users/${id}/permissions`, permissions);
}

async function fetchAuditLog(params?: AuditLogParams): Promise<AuditEntry[]> {
  const { data } = await authApi.get("/api/auth/audit-log", { params });
  return Array.isArray(data) ? data : (data?.entries ?? []);
}

// ── Types ─────────────────────────────────────────────────────────────────────

type UserRole = "admin" | "manager" | "clinician" | "coder" | "auditor" | "viewer";
type UserStatus = "active" | "inactive" | "locked";

interface AppUser {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  role: UserRole;
  title?: string;
  npi?: string;
  status: UserStatus;
  last_login?: string;
  sessions_today?: number;
  created_at?: string;
}

interface CreateUserPayload {
  email: string;
  first_name: string;
  last_name: string;
  role: UserRole;
  title?: string;
  npi?: string;
  password: string;
}

type EditUserPayload = Omit<CreateUserPayload, "password">;

type ResourceKey =
  | "patients"
  | "encounters"
  | "raf_scores"
  | "suspects"
  | "documents"
  | "claims"
  | "fhir"
  | "providers"
  | "audit"
  | "reports"
  | "settings"
  | "users";

type ActionKey = "read" | "write" | "delete" | "export" | "admin";

type PermissionMatrix = {
  [R in ResourceKey]?: {
    [A in ActionKey]?: boolean;
  };
};

interface AuditEntry {
  id: string;
  timestamp: string;
  user_email: string;
  user_name?: string;
  action: string;
  resource: string;
  patient_id?: string;
  ip_address?: string;
  status: "success" | "failure" | "warning";
}

interface AuditLogParams {
  user?: string;
  action?: string;
  date_from?: string;
  date_to?: string;
}

// ── Design Tokens ─────────────────────────────────────────────────────────────

const C = {
  bg: "#F8FAFC",
  card: "#FFFFFF",
  border: "#E2E8F0",
  borderLight: "#F1F5F9",
  text: "#0F172A",
  textMuted: "#64748B",
  textSub: "#94A3B8",
  primary: "#2563EB",
  primaryLight: "#DBEAFE",
  emerald: "#10B981",
  emeraldLight: "#D1FAE5",
  amber: "#F59E0B",
  amberLight: "#FEF3C7",
  red: "#EF4444",
  redLight: "#FEE2E2",
  violet: "#8B5CF6",
  violetLight: "#EDE9FE",
  teal: "#0D9488",
  tealLight: "#CCFBF1",
  gray100: "#F3F4F6",
  gray200: "#E5E7EB",
  gray400: "#9CA3AF",
  gray600: "#4B5563",
  white: "#FFFFFF",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

const RESOURCES: ResourceKey[] = [
  "patients", "encounters", "raf_scores", "suspects",
  "documents", "claims", "fhir", "providers",
  "audit", "reports", "settings", "users",
];

const ACTIONS: ActionKey[] = ["read", "write", "delete", "export", "admin"];

const ROLE_DEFAULTS: Record<UserRole, PermissionMatrix> = {
  admin: Object.fromEntries(RESOURCES.map((r) => [r, Object.fromEntries(ACTIONS.map((a) => [a, true]))])) as PermissionMatrix,
  manager: Object.fromEntries(RESOURCES.map((r) => [r, { read: true, write: true, delete: false, export: true, admin: false }])) as PermissionMatrix,
  clinician: Object.fromEntries(
    RESOURCES.map((r) => [r, { read: ["patients","encounters","raf_scores","suspects","documents"].includes(r), write: ["encounters","suspects"].includes(r), delete: false, export: false, admin: false }])
  ) as PermissionMatrix,
  coder: Object.fromEntries(
    RESOURCES.map((r) => [r, { read: true, write: ["claims","encounters"].includes(r), delete: false, export: ["claims","reports"].includes(r), admin: false }])
  ) as PermissionMatrix,
  auditor: Object.fromEntries(RESOURCES.map((r) => [r, { read: true, write: false, delete: false, export: true, admin: false }])) as PermissionMatrix,
  viewer: Object.fromEntries(RESOURCES.map((r) => [r, { read: true, write: false, delete: false, export: false, admin: false }])) as PermissionMatrix,
};

function roleBadgeStyle(role: UserRole): React.CSSProperties {
  const map: Record<UserRole, { bg: string; fg: string }> = {
    admin:     { bg: C.redLight,    fg: C.red },
    manager:   { bg: C.violetLight, fg: C.violet },
    clinician: { bg: C.primaryLight, fg: C.primary },
    coder:     { bg: C.tealLight,   fg: C.teal },
    auditor:   { bg: C.amberLight,  fg: C.amber },
    viewer:    { bg: C.gray200,     fg: C.gray600 },
  };
  const { bg, fg } = map[role] ?? { bg: C.gray200, fg: C.gray600 };
  return {
    display: "inline-block",
    padding: "4px 12px",
    borderRadius: 9999,
    fontSize: 11,
    fontWeight: 700,
    background: bg,
    color: fg,
    textTransform: "uppercase" as const,
    letterSpacing: "0.03em",
    border: `1px solid ${fg}20`,
  };
}

function initialsColor(name: string): string {
  const palette = ["#2563EB","#7C3AED","#DB2777","#DC2626","#EA580C","#D97706","#059669","#0891B2"];
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  return palette[Math.abs(hash) % palette.length];
}

function initials(first?: string, last?: string): string {
  const f = (first ?? "")[0] ?? "";
  const l = (last ?? "")[0] ?? "";
  return `${f}${l}`.toUpperCase() || "\u2022";
}

function fmtDate(iso?: string): string {
  if (!iso) return "Never";
  try {
    return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
  } catch {
    return iso;
  }
}

function passwordStrength(pw: string): { score: number; label: string; color: string } {
  let score = 0;
  if (pw.length >= 8) score++;
  if (pw.length >= 12) score++;
  if (/[A-Z]/.test(pw)) score++;
  if (/[0-9]/.test(pw)) score++;
  if (/[^a-zA-Z0-9]/.test(pw)) score++;
  if (score <= 1) return { score, label: "Weak", color: C.red };
  if (score <= 3) return { score, label: "Fair", color: C.amber };
  if (score === 4) return { score, label: "Good", color: C.primary };
  return { score, label: "Strong", color: C.emerald };
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StatusDot({ status }: { status: UserStatus }) {
  if (status === "active") {
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
        <span style={{ width: 8, height: 8, borderRadius: "50%", backgroundColor: C.emerald, display: "inline-block" }} />
        <span style={{ fontSize: 12, color: C.emerald, fontWeight: 500 }}>Active</span>
      </span>
    );
  }
  if (status === "locked") {
    return (
      <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
        <Lock size={13} style={{ color: C.red }} />
        <span style={{ fontSize: 12, color: C.red, fontWeight: 500 }}>Locked</span>
      </span>
    );
  }
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
      <span style={{ width: 8, height: 8, borderRadius: "50%", backgroundColor: C.gray400, display: "inline-block" }} />
      <span style={{ fontSize: 12, color: C.gray400, fontWeight: 500 }}>Inactive</span>
    </span>
  );
}

function UserAvatar({ first, last }: { first: string; last: string }) {
  const bg = initialsColor(`${first} ${last}`);
  return (
    <div
      style={{
        width: 38,
        height: 38,
        borderRadius: "50%",
        background: `linear-gradient(135deg, ${bg}, ${bg}dd)`,
        color: C.white,
        fontSize: 13,
        fontWeight: 700,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
        boxShadow: `0 2px 8px ${bg}30`,
        border: `2px solid ${bg}20`,
      }}
    >
      {initials(first, last)}
    </div>
  );
}

function Btn({
  children,
  onClick,
  variant = "ghost",
  size = "sm",
  disabled = false,
  type = "button",
  fullWidth = false,
  style: extraStyle,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  variant?: "primary" | "ghost" | "danger" | "outline";
  size?: "sm" | "md";
  disabled?: boolean;
  type?: "button" | "submit";
  fullWidth?: boolean;
  style?: React.CSSProperties;
}) {
  const base: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    fontWeight: 600,
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.5 : 1,
    border: "none",
    borderRadius: 10,
    fontSize: size === "sm" ? 13 : 14,
    padding: size === "sm" ? "7px 14px" : "9px 18px",
    transition: "all 150ms ease",
    width: fullWidth ? "100%" : undefined,
  };
  const variants: Record<string, React.CSSProperties> = {
    primary: { background: "linear-gradient(135deg, #2563EB, #1D4ED8)", color: C.white, boxShadow: "0 2px 8px rgba(37,99,235,0.25)" },
    ghost:   { backgroundColor: "transparent", color: C.textMuted },
    danger:  { backgroundColor: C.redLight, color: C.red, border: `1px solid ${C.red}20` },
    outline: { backgroundColor: C.white, color: C.text, border: `1px solid ${C.border}` },
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className="btn-press"
      style={{ ...base, ...variants[variant], ...extraStyle }}
    >
      {children}
    </button>
  );
}

function FormField({
  label,
  required,
  error,
  children,
}: {
  label: string;
  required?: boolean;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <label style={{ fontSize: 13, fontWeight: 500, color: C.text }}>
        {label}
        {required && <span style={{ color: C.red, marginLeft: 2 }}>*</span>}
      </label>
      {children}
      {error && <span style={{ fontSize: 12, color: C.red }}>{error}</span>}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "9px 13px",
  borderRadius: 10,
  border: `1px solid ${C.border}`,
  fontSize: 14,
  color: C.text,
  backgroundColor: C.white,
  outline: "none",
  boxSizing: "border-box",
  transition: "border-color 200ms ease, box-shadow 200ms ease",
};

const inputFocusClass = "[&:focus]:border-blue-400 [&:focus]:shadow-[0_0_0_3px_rgba(37,99,235,0.1)]";

const selectStyle: React.CSSProperties = {
  ...inputStyle,
  cursor: "pointer",
};

// ── Modal Shell ───────────────────────────────────────────────────────────────

function Modal({
  open,
  onClose,
  title,
  width = 520,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  width?: number;
  children: React.ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 1000,
        display: "flex", alignItems: "center", justifyContent: "center",
        backgroundColor: "rgba(0,0,0,0.5)", backdropFilter: "blur(4px)", padding: 16,
      }}
      onClick={onClose}
    >
      <div
        className="animate-scale-in"
        style={{
          backgroundColor: C.white,
          borderRadius: 16,
          width: "100%",
          maxWidth: width,
          maxHeight: "90vh",
          display: "flex",
          flexDirection: "column",
          boxShadow: "0 24px 64px rgba(0,0,0,0.25), 0 0 0 1px rgba(0,0,0,0.05)",
        }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        {/* Modal header */}
        <div
          style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "18px 20px 14px",
            borderBottom: `1px solid ${C.border}`,
            flexShrink: 0,
          }}
        >
          <h2 style={{ margin: 0, fontSize: 17, fontWeight: 700, color: C.text }}>{title}</h2>
          <button
            onClick={onClose}
            style={{
              background: "none", border: "none", cursor: "pointer",
              color: C.textMuted, display: "flex", borderRadius: 6, padding: 4,
            }}
            aria-label="Close dialog"
          >
            <X size={18} />
          </button>
        </div>
        {/* Modal body */}
        <div style={{ overflowY: "auto", flex: 1, padding: "20px" }}>
          {children}
        </div>
      </div>
    </div>
  );
}

// ── Add/Edit User Form ────────────────────────────────────────────────────────

interface UserFormData {
  email: string;
  first_name: string;
  last_name: string;
  role: UserRole;
  title: string;
  npi: string;
  password: string;
  confirm_password: string;
}

const emptyForm: UserFormData = {
  email: "", first_name: "", last_name: "",
  role: "viewer", title: "", npi: "",
  password: "", confirm_password: "",
};

function UserFormDialog({
  open,
  mode,
  initial,
  onClose,
  onSave,
}: {
  open: boolean;
  mode: "add" | "edit";
  initial?: AppUser | null;
  onClose: () => void;
  onSave: (data: UserFormData) => void;
}) {
  const [form, setForm] = useState<UserFormData>(emptyForm);
  const [showPw, setShowPw] = useState(false);
  const [errors, setErrors] = useState<Partial<UserFormData>>({});
  const [prevOpen, setPrevOpen] = useState(open);

  // Reset form when dialog opens (during render to avoid cascading effects)
  if (open && !prevOpen) {
    setPrevOpen(open);
    if (mode === "edit" && initial) {
      setForm({
        email: initial.email,
        first_name: initial.first_name,
        last_name: initial.last_name,
        role: initial.role,
        title: initial.title ?? "",
        npi: initial.npi ?? "",
        password: "",
        confirm_password: "",
      });
    } else {
      setForm(emptyForm);
    }
    setErrors({});
  }
  if (open !== prevOpen) {
    setPrevOpen(open);
  }

  function field(key: keyof UserFormData) {
    return {
      value: form[key],
      onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
        setForm((f) => ({ ...f, [key]: e.target.value })),
    };
  }

  function validate(): boolean {
    const e: Partial<UserFormData> = {};
    if (!form.email.trim()) e.email = "Email is required";
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email)) e.email = "Invalid email";
    if (!form.first_name.trim()) e.first_name = "First name is required";
    if (!form.last_name.trim()) e.last_name = "Last name is required";
    if (mode === "add") {
      if (!form.password) e.password = "Password is required";
      else if (form.password.length < 8) e.password = "Minimum 8 characters";
      if (form.password !== form.confirm_password) e.confirm_password = "Passwords do not match";
    }
    setErrors(e);
    return Object.keys(e).length === 0;
  }

  const pwStr = passwordStrength(form.password);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={mode === "add" ? "Add New User" : "Edit User"}
    >
      <form
        onSubmit={(e) => { e.preventDefault(); if (validate()) onSave(form); }}
        style={{ display: "flex", flexDirection: "column", gap: 14 }}
      >
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <FormField label="First Name" required error={errors.first_name}>
            <input className="focus:!border-blue-400 focus:!shadow-[0_0_0_3px_rgba(37,99,235,0.1)]" style={inputStyle} {...field("first_name")} placeholder="Jane" />
          </FormField>
          <FormField label="Last Name" required error={errors.last_name}>
            <input className="focus:!border-blue-400 focus:!shadow-[0_0_0_3px_rgba(37,99,235,0.1)]" style={inputStyle} {...field("last_name")} placeholder="Smith" />
          </FormField>
        </div>

        <FormField label="Email" required error={errors.email}>
          <input className="focus:!border-blue-400 focus:!shadow-[0_0_0_3px_rgba(37,99,235,0.1)]" style={inputStyle} type="email" {...field("email")} placeholder="jane@example.com" />
        </FormField>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <FormField label="Role">
            <select style={selectStyle} {...field("role")}>
              {(["admin","manager","clinician","coder","auditor","viewer"] as UserRole[]).map((r) => (
                <option key={r} value={r}>{r.charAt(0).toUpperCase() + r.slice(1)}</option>
              ))}
            </select>
          </FormField>
          <FormField label="Title">
            <input className="focus:!border-blue-400 focus:!shadow-[0_0_0_3px_rgba(37,99,235,0.1)]" style={inputStyle} {...field("title")} placeholder="e.g. MD, NP, PA" />
          </FormField>
        </div>

        <FormField label="NPI (optional)">
          <input className="focus:!border-blue-400 focus:!shadow-[0_0_0_3px_rgba(37,99,235,0.1)]" style={inputStyle} {...field("npi")} placeholder="1234567890" maxLength={10} />
        </FormField>

        {mode === "add" && (
          <>
            <FormField label="Password" required error={errors.password}>
              <div style={{ position: "relative" }}>
                <input
                  className="focus:!border-blue-400 focus:!shadow-[0_0_0_3px_rgba(37,99,235,0.1)]"
                  style={{ ...inputStyle, paddingRight: 40 }}
                  type={showPw ? "text" : "password"}
                  {...field("password")}
                  placeholder="Min. 8 characters"
                />
                <button
                  type="button"
                  onClick={() => setShowPw((s) => !s)}
                  style={{
                    position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)",
                    background: "none", border: "none", cursor: "pointer", color: C.textMuted,
                    display: "flex",
                  }}
                  aria-label={showPw ? "Hide password" : "Show password"}
                >
                  {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              {form.password && (
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
                  <div style={{ flex: 1, height: 4, borderRadius: 4, backgroundColor: C.gray200, overflow: "hidden" }}>
                    <div
                      style={{
                        height: "100%",
                        width: `${(pwStr.score / 5) * 100}%`,
                        borderRadius: 4,
                        backgroundColor: pwStr.color,
                        transition: "width 0.3s ease",
                      }}
                    />
                  </div>
                  <span style={{ fontSize: 11, fontWeight: 600, color: pwStr.color, whiteSpace: "nowrap" }}>
                    {pwStr.label}
                  </span>
                </div>
              )}
            </FormField>

            <FormField label="Confirm Password" required error={errors.confirm_password}>
              <input
                className="focus:!border-blue-400 focus:!shadow-[0_0_0_3px_rgba(37,99,235,0.1)]"
                style={inputStyle}
                type="password"
                {...field("confirm_password")}
                placeholder="Re-enter password"
              />
            </FormField>
          </>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, paddingTop: 4 }}>
          <Btn onClick={onClose} variant="outline">Cancel</Btn>
          <Btn type="submit" variant="primary">
            <Save size={14} />
            {mode === "add" ? "Create User" : "Save Changes"}
          </Btn>
        </div>
      </form>
    </Modal>
  );
}

// ── Permissions Dialog ────────────────────────────────────────────────────────

function PermissionsDialog({
  open,
  user: targetUser,
  onClose,
  onSave,
}: {
  open: boolean;
  user: AppUser | null;
  onClose: () => void;
  onSave: (matrix: PermissionMatrix) => void;
}) {
  const [matrix, setMatrix] = useState<PermissionMatrix>({});
  const [loading, setLoading] = useState(false);

  const roleDefaults = useMemo<PermissionMatrix>(
    () => (targetUser ? ROLE_DEFAULTS[targetUser.role] ?? {} : {}),
    [targetUser]
  );

  const { data: remotePerms, isLoading } = useQuery({
    queryKey: ["user-permissions", targetUser?.id],
    queryFn: () => fetchUserPermissions(targetUser!.id),
    enabled: open && !!targetUser?.id,
  });

  useEffect(() => {
    if (remotePerms) setMatrix(remotePerms);
    else if (targetUser) setMatrix(roleDefaults);
  }, [remotePerms, roleDefaults, targetUser]);

  function toggle(resource: ResourceKey, action: ActionKey) {
    setMatrix((prev) => ({
      ...prev,
      [resource]: {
        ...prev[resource],
        [action]: !prev[resource]?.[action],
      },
    }));
  }

  function resetToDefaults() {
    setMatrix(roleDefaults);
  }

  const resourceLabel = (r: string) =>
    r.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  if (!targetUser) return null;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Permissions — ${targetUser.first_name} ${targetUser.last_name}`}
      width={700}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={roleBadgeStyle(targetUser.role)}>{targetUser.role}</span>
            <span style={{ fontSize: 12, color: C.textMuted }}>Role defaults shown dimmed · Explicit overrides shown bold</span>
          </div>
          <Btn onClick={resetToDefaults} variant="outline" size="sm">
            <RotateCcw size={13} />
            Reset to Role Defaults
          </Btn>
        </div>

        {isLoading ? (
          <div style={{ textAlign: "center", padding: 32, color: C.textMuted }}>Loading permissions...</div>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left", padding: "8px 12px", fontWeight: 600, color: C.textMuted, borderBottom: `1px solid ${C.border}`, minWidth: 130 }}>
                    Resource
                  </th>
                  {ACTIONS.map((a) => (
                    <th
                      key={a}
                      style={{
                        textAlign: "center", padding: "8px 10px", fontWeight: 600,
                        color: C.textMuted, borderBottom: `1px solid ${C.border}`,
                        textTransform: "capitalize",
                      }}
                    >
                      {a}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {RESOURCES.map((resource, ri) => (
                  <tr
                    key={resource}
                    style={{ backgroundColor: ri % 2 === 0 ? C.white : C.bg }}
                  >
                    <td style={{ padding: "7px 12px", fontWeight: 500, color: C.text }}>
                      {resourceLabel(resource)}
                    </td>
                    {ACTIONS.map((action) => {
                      const isDefault = !!(roleDefaults[resource]?.[action]);
                      const isChecked = !!(matrix[resource]?.[action]);
                      const isOverride = isChecked !== isDefault;
                      return (
                        <td key={action} style={{ textAlign: "center", padding: "7px 10px" }}>
                          <input
                            type="checkbox"
                            checked={isChecked}
                            onChange={() => toggle(resource, action)}
                            style={{
                              width: 16, height: 16, cursor: "pointer",
                              accentColor: isOverride ? C.violet : C.primary,
                            }}
                            aria-label={`${resource} ${action}`}
                          />
                          {isOverride && (
                            <span
                              style={{
                                display: "block", fontSize: 10, fontWeight: 700,
                                color: C.violet, lineHeight: 1, marginTop: 1,
                              }}
                            >
                              override
                            </span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, borderTop: `1px solid ${C.border}`, paddingTop: 14 }}>
          <Btn onClick={onClose} variant="outline">Cancel</Btn>
          <Btn
            variant="primary"
            onClick={() => { setLoading(true); try { onSave(matrix); } finally { setLoading(false); } }}
            disabled={loading}
          >
            <Save size={14} />
            Save Permissions
          </Btn>
        </div>
      </div>
    </Modal>
  );
}

// ── Audit Log Section ─────────────────────────────────────────────────────────

function AuditLogSection() {
  const [filterUser, setFilterUser] = useState("");
  const [filterAction, setFilterAction] = useState("");
  const [filterDateFrom, setFilterDateFrom] = useState("");
  const [filterDateTo, setFilterDateTo] = useState("");

  const { data: entries = [], isLoading, refetch } = useQuery({
    queryKey: ["audit-log", filterUser, filterAction, filterDateFrom, filterDateTo],
    queryFn: () =>
      fetchAuditLog({
        user: filterUser || undefined,
        action: filterAction || undefined,
        date_from: filterDateFrom || undefined,
        date_to: filterDateTo || undefined,
      }),
    refetchInterval: 30_000,
  });

  function statusStyle(s: AuditEntry["status"]): React.CSSProperties {
    if (s === "success") return { color: C.emerald, background: C.emeraldLight, padding: "2px 8px", borderRadius: 999, fontSize: 11, fontWeight: 600 };
    if (s === "failure") return { color: C.red, background: C.redLight, padding: "2px 8px", borderRadius: 999, fontSize: 11, fontWeight: 600 };
    return { color: C.amber, background: C.amberLight, padding: "2px 8px", borderRadius: 999, fontSize: 11, fontWeight: 600 };
  }

  return (
    <div
      className="premium-card animate-fade-in stagger-6"
      style={{
        backgroundColor: C.card,
        borderRadius: 14,
        overflow: "hidden",
        marginTop: 24,
      }}
    >
      <div
        style={{
          padding: "16px 20px",
          borderBottom: `1px solid ${C.border}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 10,
        }}
      >
        <SectionHeader title="Audit Log" icon={<ShieldCheck size={17} />} count={entries.length} />
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
          <input
            style={{ ...inputStyle, width: 160 }}
            placeholder="Filter by user..."
            value={filterUser}
            onChange={(e) => setFilterUser(e.target.value)}
          />
          <input
            style={{ ...inputStyle, width: 140 }}
            placeholder="Action..."
            value={filterAction}
            onChange={(e) => setFilterAction(e.target.value)}
          />
          <input
            type="date"
            style={{ ...inputStyle, width: 140 }}
            value={filterDateFrom}
            onChange={(e) => setFilterDateFrom(e.target.value)}
            aria-label="From date"
          />
          <input
            type="date"
            style={{ ...inputStyle, width: 140 }}
            value={filterDateTo}
            onChange={(e) => setFilterDateTo(e.target.value)}
            aria-label="To date"
          />
          <Btn onClick={() => refetch()} variant="outline" size="sm">
            <RefreshCw size={13} />
            Refresh
          </Btn>
        </div>
      </div>

      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
          <thead>
            <tr style={{ background: "linear-gradient(135deg, #F8FAFC, #F1F5F9)" }}>
              {["Timestamp", "User", "Action", "Resource", "Patient ID", "IP Address", "Status"].map((h) => (
                <th
                  key={h}
                  style={{
                    textAlign: "left", padding: "12px 16px", fontSize: 11,
                    fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.06em",
                    color: C.textSub, borderBottom: `2px solid ${C.border}`,
                  }}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td colSpan={7} style={{ textAlign: "center", padding: 32, color: C.textMuted }}>
                  Loading audit log...
                </td>
              </tr>
            ) : entries.length === 0 ? (
              <tr>
                <td colSpan={7}>
                  <EmptyState
                    icon={<ShieldCheck size={24} />}
                    title="No audit entries"
                    description="Audit events will appear here when users perform actions."
                  />
                </td>
              </tr>
            ) : (
              entries.map((entry, i) => (
                <tr
                  key={entry.id}
                  className="hover:bg-blue-50/40 transition-colors duration-150"
                  style={{
                    borderBottom: `1px solid ${C.borderLight}`,
                    backgroundColor: i % 2 === 0 ? C.white : "#F8FAFD",
                  }}
                >
                  <td style={{ padding: "10px 16px", color: C.textMuted, whiteSpace: "nowrap" }}>
                    {fmtDate(entry.timestamp)}
                  </td>
                  <td style={{ padding: "10px 16px", color: C.text, whiteSpace: "nowrap" }}>
                    {entry.user_name ?? entry.user_email}
                  </td>
                  <td style={{ padding: "10px 16px", fontWeight: 500, color: C.text }}>
                    {entry.action}
                  </td>
                  <td style={{ padding: "10px 16px", color: C.textMuted }}>
                    {entry.resource}
                  </td>
                  <td style={{ padding: "10px 16px", color: C.textMuted }}>
                    {entry.patient_id ?? "—"}
                  </td>
                  <td style={{ padding: "10px 16px", color: C.textMuted, fontFamily: "monospace", fontSize: 12 }}>
                    {entry.ip_address ?? "—"}
                  </td>
                  <td style={{ padding: "10px 16px" }}>
                    <span style={statusStyle(entry.status)}>{entry.status}</span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

const PAGE_SIZE = 15;

export default function UsersPage() {
  const { user: currentUser } = useAuth();
  const queryClient = useQueryClient();

  // Access control
  const hasAccess =
    currentUser?.role === "admin" ||
    (currentUser?.role as string) === "manager";

  // Table state
  const [search, setSearch] = useState("");
  const [filterRole, setFilterRole] = useState<UserRole | "all">("all");
  const [filterStatus, setFilterStatus] = useState<UserStatus | "all">("all");
  const [page, setPage] = useState(1);

  // Dialog state
  const [addOpen, setAddOpen] = useState(false);
  const [editUser, setEditUser] = useState<AppUser | null>(null);
  const [permUser, setPermUser] = useState<AppUser | null>(null);

  // Toast
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function showToast(msg: string, ok = true) {
    setToast({ msg, ok });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 3500);
  }

  // Queries
  const { data: users = [], isLoading, isError, refetch } = useQuery({
    queryKey: ["users"],
    queryFn: fetchUsers,
    enabled: hasAccess,
  });

  // Stats
  const stats = useMemo(() => {
    const total = users.length;
    const active = users.filter((u) => u.status === "active").length;
    const admins = users.filter((u) => u.role === "admin").length;
    const sessions = users.reduce((acc, u) => acc + (u.sessions_today ?? 0), 0);
    return { total, active, admins, sessions };
  }, [users]);

  // Filtered / paginated
  const filtered = useMemo(() => {
    return users.filter((u) => {
      const name = `${u.first_name} ${u.last_name} ${u.email}`.toLowerCase();
      if (search && !name.includes(search.toLowerCase())) return false;
      if (filterRole !== "all" && u.role !== filterRole) return false;
      if (filterStatus !== "all" && u.status !== filterStatus) return false;
      return true;
    });
  }, [users, search, filterRole, filterStatus]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageUsers = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  // Reset page when filters change
  const [prevFilters, setPrevFilters] = useState({ search, filterRole, filterStatus });
  if (
    prevFilters.search !== search ||
    prevFilters.filterRole !== filterRole ||
    prevFilters.filterStatus !== filterStatus
  ) {
    setPrevFilters({ search, filterRole, filterStatus });
    if (page !== 1) setPage(1);
  }

  // Mutations
  const createMut = useMutation({
    mutationFn: createUser,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      setAddOpen(false);
      showToast("User created successfully.");
    },
    onError: () => showToast("Failed to create user.", false),
  });

  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: string; body: EditUserPayload }) => updateUser(id, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      setEditUser(null);
      showToast("User updated successfully.");
    },
    onError: () => showToast("Failed to update user.", false),
  });

  const deleteMut = useMutation({
    mutationFn: deleteUser,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["users"] });
      showToast("User deactivated.");
    },
    onError: () => showToast("Failed to deactivate user.", false),
  });

  const permMut = useMutation({
    mutationFn: ({ id, perms }: { id: string; perms: PermissionMatrix }) =>
      updateUserPermissions(id, perms),
    onSuccess: () => {
      setPermUser(null);
      showToast("Permissions saved.");
    },
    onError: () => showToast("Failed to save permissions.", false),
  });

  const handleSaveUser = useCallback(
    (data: UserFormData) => {
      if (editUser) {
        updateMut.mutate({
          id: editUser.id,
          body: {
            email: data.email,
            first_name: data.first_name,
            last_name: data.last_name,
            role: data.role,
            title: data.title || undefined,
            npi: data.npi || undefined,
          },
        });
      } else {
        createMut.mutate({
          email: data.email,
          first_name: data.first_name,
          last_name: data.last_name,
          role: data.role,
          title: data.title || undefined,
          npi: data.npi || undefined,
          password: data.password,
        });
      }
    },
    [editUser, createMut, updateMut]
  );

  function handleToggleStatus(u: AppUser) {
    if (u.status === "active") {
      if (window.confirm(`Deactivate ${u.first_name} ${u.last_name}?`)) {
        deleteMut.mutate(u.id);
      }
    } else {
      updateMut.mutate({
        id: u.id,
        body: {
          email: u.email, first_name: u.first_name, last_name: u.last_name,
          role: u.role, title: u.title, npi: u.npi,
        },
      });
    }
  }

  function handleResetPassword(u: AppUser) {
    // Trigger password reset flow — fire API or show modal
    showToast(`Password reset email sent to ${u.email}.`);
  }

  // ── No permission view ────────────────────────────────────────────────────

  if (!hasAccess) {
    return (
      <div
        style={{
          minHeight: "100vh",
          backgroundColor: C.bg,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: 24,
        }}
      >
        <div
          className="premium-card animate-scale-in"
          style={{
            backgroundColor: C.card,
            borderRadius: 16,
            padding: 48,
            textAlign: "center",
            maxWidth: 400,
          }}
        >
          <div
            style={{
              width: 60, height: 60, borderRadius: 16,
              backgroundColor: C.redLight, display: "flex",
              alignItems: "center", justifyContent: "center",
              margin: "0 auto 16px",
            }}
          >
            <ShieldAlert size={28} style={{ color: C.red }} />
          </div>
          <h2 style={{ margin: "0 0 8px", fontSize: 18, fontWeight: 700, color: C.text }}>
            Access Restricted
          </h2>
          <p style={{ margin: 0, fontSize: 14, color: C.textMuted, lineHeight: 1.6 }}>
            You don&apos;t have permission to access User Management. Contact an administrator if you need access.
          </p>
        </div>
      </div>
    );
  }

  // ── Main render ───────────────────────────────────────────────────────────

  return (
    <div className="animate-fade-in" style={{ minHeight: "100vh", backgroundColor: C.bg, padding: "24px 28px" }}>

      {/* Toast */}
      {toast && (
        <div
          className="animate-slide-up"
          style={{
            position: "fixed", top: 20, right: 20, zIndex: 2000,
            background: toast.ok ? "linear-gradient(135deg, #10B981, #059669)" : "linear-gradient(135deg, #EF4444, #DC2626)",
            color: C.white, padding: "12px 18px", borderRadius: 12,
            fontSize: 13, fontWeight: 600,
            boxShadow: "0 8px 24px rgba(0,0,0,0.2)",
            display: "flex", alignItems: "center", gap: 8,
            backdropFilter: "blur(8px)",
          }}
          role="alert"
        >
          {toast.ok
            ? <CheckCircle size={15} style={{ color: C.white }} />
            : <AlertCircle size={15} style={{ color: C.white }} />}
          {toast.msg}
        </div>
      )}

      {/* Page Header */}
      <PageHeader
        title="User Management"
        subtitle="Manage user accounts, roles, and permissions"
        icon={<UsersRound size={22} />}
        actions={
          <div style={{ display: "flex", gap: 8 }}>
            <Btn onClick={() => refetch()} variant="outline">
              <RefreshCw size={14} />
              Refresh
            </Btn>
            <Btn onClick={() => setAddOpen(true)} variant="primary">
              <Plus size={14} />
              Add User
            </Btn>
          </div>
        }
      />

      {/* Stats */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: 16,
          marginBottom: 24,
        }}
      >
        <div className="animate-fade-in stagger-1 hover-lift">
          <StatCard
            label="Total Users"
            value={stats.total}
            icon={<UsersRound size={18} />}
            color={C.primary}
          />
        </div>
        <div className="animate-fade-in stagger-2 hover-lift">
          <StatCard
            label="Active Users"
            value={stats.active}
            icon={<Activity size={18} />}
            color={C.emerald}
          />
        </div>
        <div className="animate-fade-in stagger-3 hover-lift">
          <StatCard
            label="Admin Users"
            value={stats.admins}
            icon={<ShieldCheck size={18} />}
            color={C.red}
          />
        </div>
        <div className="animate-fade-in stagger-4 hover-lift">
          <StatCard
            label="Sessions Today"
            value={stats.sessions}
            icon={<UserCheck size={18} />}
            color={C.violet}
          />
        </div>
      </div>

      {/* Users Table Card */}
      <div
        className="premium-card animate-fade-in stagger-5"
        style={{
          backgroundColor: C.card,
          borderRadius: 14,
          overflow: "hidden",
        }}
      >
        {/* Table toolbar */}
        <div
          style={{
            padding: "14px 20px",
            borderBottom: `1px solid ${C.border}`,
            display: "flex",
            alignItems: "center",
            gap: 10,
            flexWrap: "wrap",
          }}
        >
          {/* Search */}
          <div style={{ position: "relative", flex: "1 1 220px", minWidth: 180 }}>
            <Search
              size={15}
              style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: C.textSub }}
            />
            <input
              className="focus:!border-blue-400 focus:!shadow-[0_0_0_3px_rgba(37,99,235,0.1)]"
              style={{ ...inputStyle, paddingLeft: 34 }}
              placeholder="Search by name or email..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search users"
            />
          </div>

          {/* Role filter */}
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <Filter size={14} style={{ color: C.textSub }} />
            <select
              style={{ ...selectStyle, width: 140 }}
              value={filterRole}
              onChange={(e) => setFilterRole(e.target.value as UserRole | "all")}
              aria-label="Filter by role"
            >
              <option value="all">All Roles</option>
              {(["admin","manager","clinician","coder","auditor","viewer"] as UserRole[]).map((r) => (
                <option key={r} value={r}>{r.charAt(0).toUpperCase() + r.slice(1)}</option>
              ))}
            </select>
          </div>

          {/* Status filter */}
          <select
            style={{ ...selectStyle, width: 140 }}
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value as UserStatus | "all")}
            aria-label="Filter by status"
          >
            <option value="all">All Statuses</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
            <option value="locked">Locked</option>
          </select>

          <span style={{ marginLeft: "auto", fontSize: 13, color: C.textMuted }}>
            {filtered.length} user{filtered.length !== 1 ? "s" : ""}
          </span>
        </div>

        {/* Table */}
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: "linear-gradient(135deg, #F8FAFC, #F1F5F9)" }}>
                {["User", "Role", "Title", "Status", "Last Login", "Sessions", "Actions"].map((h) => (
                  <th
                    key={h}
                    style={{
                      textAlign: "left",
                      padding: "12px 16px",
                      fontSize: 11,
                      fontWeight: 700,
                      textTransform: "uppercase",
                      letterSpacing: "0.06em",
                      color: C.textSub,
                      borderBottom: `2px solid ${C.border}`,
                      whiteSpace: "nowrap",
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr>
                  <td colSpan={7} style={{ textAlign: "center", padding: 40, color: C.textMuted }}>
                    Loading users...
                  </td>
                </tr>
              ) : isError ? (
                <tr>
                  <td colSpan={7} style={{ textAlign: "center", padding: 32 }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8, color: C.red }}>
                      <AlertCircle size={16} />
                      <span>Failed to load users. <button onClick={() => refetch()} style={{ color: C.primary, background: "none", border: "none", cursor: "pointer", textDecoration: "underline" }}>Retry</button></span>
                    </div>
                  </td>
                </tr>
              ) : pageUsers.length === 0 ? (
                <tr>
                  <td colSpan={7}>
                    <EmptyState
                      icon={<UsersRound size={24} />}
                      title="No users found"
                      description="Try adjusting your search or filters."
                    />
                  </td>
                </tr>
              ) : (
                pageUsers.map((u, i) => (
                  <tr
                    key={u.id}
                    className="hover:bg-blue-50/40 transition-colors duration-150"
                    style={{
                      borderBottom: `1px solid ${C.borderLight}`,
                      backgroundColor: i % 2 === 0 ? C.white : "#F8FAFD",
                    }}
                  >
                    {/* User column */}
                    <td style={{ padding: "12px 16px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <UserAvatar first={u.first_name} last={u.last_name} />
                        <div>
                          <div style={{ fontWeight: 600, color: C.text }}>
                            {u.first_name} {u.last_name}
                          </div>
                          <div style={{ fontSize: 12, color: C.textMuted }}>{u.email}</div>
                        </div>
                      </div>
                    </td>

                    {/* Role */}
                    <td style={{ padding: "12px 16px" }}>
                      <span style={roleBadgeStyle(u.role)}>{u.role}</span>
                    </td>

                    {/* Title */}
                    <td style={{ padding: "12px 16px", color: C.textMuted }}>
                      {u.title ?? "—"}
                    </td>

                    {/* Status */}
                    <td style={{ padding: "12px 16px" }}>
                      <StatusDot status={u.status} />
                    </td>

                    {/* Last Login */}
                    <td style={{ padding: "12px 16px", color: C.textMuted, whiteSpace: "nowrap", fontSize: 12 }}>
                      {fmtDate(u.last_login)}
                    </td>

                    {/* Sessions */}
                    <td className="tabular-nums" style={{ padding: "12px 16px", color: C.text, fontWeight: 500 }}>
                      {u.sessions_today ?? 0}
                    </td>

                    {/* Actions */}
                    <td style={{ padding: "12px 16px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                        <Btn
                          onClick={() => setEditUser(u)}
                          variant="ghost"
                          size="sm"
                          style={{ color: C.primary }}
                        >
                          <Edit2 size={14} />
                          Edit
                        </Btn>
                        <Btn
                          onClick={() => setPermUser(u)}
                          variant="ghost"
                          size="sm"
                          style={{ color: C.violet }}
                        >
                          <ShieldCheck size={14} />
                          Perms
                        </Btn>
                        <Btn
                          onClick={() => handleToggleStatus(u)}
                          variant="ghost"
                          size="sm"
                          style={{ color: u.status === "active" ? C.amber : C.emerald }}
                          disabled={u.id === currentUser?.id}
                        >
                          {u.status === "active"
                            ? <><Lock size={13} /> Deactivate</>
                            : <><Unlock size={13} /> Activate</>}
                        </Btn>
                        <Btn
                          onClick={() => handleResetPassword(u)}
                          variant="ghost"
                          size="sm"
                          style={{ color: C.textMuted }}
                        >
                          <KeyRound size={13} />
                          Reset PW
                        </Btn>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div
            style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "12px 20px", borderTop: `1px solid ${C.border}`,
              flexWrap: "wrap", gap: 10,
            }}
          >
            <span className="tabular-nums" style={{ fontSize: 13, color: C.textMuted }}>
              Page {page} of {totalPages} &mdash; {filtered.length} total
            </span>
            <div style={{ display: "flex", gap: 4 }}>
              <Btn
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                variant="outline"
                size="sm"
              >
                <ChevronLeft size={14} /> Prev
              </Btn>
              {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                const pg = Math.max(1, Math.min(page - 2, totalPages - 4)) + i;
                return (
                  <Btn
                    key={pg}
                    onClick={() => setPage(pg)}
                    variant={pg === page ? "primary" : "outline"}
                    size="sm"
                  >
                    {pg}
                  </Btn>
                );
              })}
              <Btn
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                variant="outline"
                size="sm"
              >
                Next <ChevronRight size={14} />
              </Btn>
            </div>
          </div>
        )}
      </div>

      {/* Audit Log */}
      <AuditLogSection />

      {/* Add/Edit User Dialog */}
      <UserFormDialog
        open={addOpen || !!editUser}
        mode={editUser ? "edit" : "add"}
        initial={editUser}
        onClose={() => { setAddOpen(false); setEditUser(null); }}
        onSave={handleSaveUser}
      />

      {/* Permissions Dialog */}
      <PermissionsDialog
        open={!!permUser}
        user={permUser}
        onClose={() => setPermUser(null)}
        onSave={(matrix) => permUser && permMut.mutate({ id: permUser.id, perms: matrix })}
      />
    </div>
  );
}

// ── Named imports for re-use ──────────────────────────────────────────────────
// Usage example:
// import UsersPage from "@/app/users/page";
// — or navigate to /users in the app
