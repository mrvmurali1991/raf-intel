"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/contexts/auth-context";
import { authApi } from "@/contexts/auth-context";
import { ProfileServerForm } from "./ProfileServerForm";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Settings,
  User,
  KeyRound,
  MonitorSmartphone,
  Users,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Trash2,
  ShieldAlert,
  ShieldCheck,
  QrCode,
  Copy,
  Eye,
  EyeOff,
  Sparkles,
  ToggleLeft,
  ToggleRight,
  RotateCcw,
  Bell,
  Plug,
  Palette,
  Key,
  FileCheck,
} from "lucide-react";
import { useFeatureFlagsAll } from "@/components/FeatureFlagContext";
import { tokens } from "@/styles/tokens";
import { passwordSchema, PASSWORD_MIN_LENGTH } from "@/lib/validators";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Session {
  id: string;
  ip_address: string;
  user_agent: string;
  created_at: string;
  last_used_at: string;
  is_current: boolean;
}

interface MfaSetupData {
  qr_code_url: string;
  secret: string;
  recovery_codes: string[];
}

// ---------------------------------------------------------------------------
// Shared tab IDs — single source of truth for hash routing
// ---------------------------------------------------------------------------

const TAB_IDS = [
  "profile",
  "security",
  "notifications",
  "emr-connections",
  "branding",
  "team",
  "api-keys",
  "compliance",
] as const;

type TabId = (typeof TAB_IDS)[number];

function isValidTab(v: string): v is TabId {
  return (TAB_IDS as readonly string[]).includes(v);
}

// ---------------------------------------------------------------------------
// Shared UI primitives
// ---------------------------------------------------------------------------

const inputClasses =
  "h-10 rounded-xl border-border/60 bg-muted/30 transition-all duration-200 focus:bg-background focus:border-blue-500/50 focus:ring-2 focus:ring-blue-500/20 focus:shadow-[0_0_0_3px_rgba(59,130,246,0.1)] placeholder:text-muted-foreground/50";

const primaryBtnClasses =
  "h-10 rounded-xl font-semibold text-sm bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-700 hover:to-blue-600 shadow-lg shadow-blue-500/20 hover:shadow-blue-500/30 transition-all duration-200 btn-press";

function FormField({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label
        htmlFor={htmlFor}
        className="text-xs font-semibold uppercase tracking-wider text-muted-foreground"
      >
        {label}
      </label>
      {children}
      {hint && (
        <p className="text-[11px] text-muted-foreground/70 leading-relaxed">{hint}</p>
      )}
    </div>
  );
}

function Feedback({
  type,
  message,
}: {
  type: "success" | "error";
  message: string;
}) {
  const isSuccess = type === "success";
  return (
    <div
      role={type === "error" ? "alert" : "status"}
      className={`flex items-center gap-2.5 rounded-xl p-3 text-sm border animate-scale-in ${
        isSuccess
          ? "bg-emerald-50 dark:bg-emerald-950/40 border-emerald-200 dark:border-emerald-800/60 text-emerald-700 dark:text-emerald-300"
          : "bg-red-50 dark:bg-red-950/40 border-red-200 dark:border-red-800/60 text-red-700 dark:text-red-300"
      }`}
    >
      {isSuccess ? (
        <CheckCircle2 className="h-4 w-4 shrink-0" />
      ) : (
        <AlertCircle className="h-4 w-4 shrink-0" />
      )}
      <span className="font-medium">{message}</span>
    </div>
  );
}

function SectionHeader({
  icon: Icon,
  title,
  description,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description?: string;
}) {
  return (
    <div className="flex items-start gap-3 pb-5 mb-5 border-b border-border/60">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500/15 to-cyan-500/10 border border-blue-500/20 shadow-sm">
        <Icon className="h-4 w-4 text-blue-500 dark:text-blue-400" />
      </div>
      <div>
        <h2 className="text-sm font-bold tracking-tight text-foreground">{title}</h2>
        {description && (
          <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">{description}</p>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Profile tab
// ---------------------------------------------------------------------------

function ProfileTab() {
  const { user } = useAuth();

  return (
    <div className="space-y-6">
      <SectionHeader icon={User} title="Profile" description="Update your personal information." />

      <ProfileServerForm
        defaultFirstName={user?.first_name ?? ""}
        defaultLastName={user?.last_name ?? ""}
        defaultTitle={user?.title ?? ""}
        defaultAvatarUrl={user?.avatar_url ?? ""}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Security tab — password + MFA + sessions collapsed into one pane
// ---------------------------------------------------------------------------

function ChangePasswordPanel({ forceChange = false }: { forceChange?: boolean }) {
  const { changePassword } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFeedback(null);
    if (next !== confirm) { setFeedback({ type: "error", message: "New passwords do not match." }); return; }
    const pwCheck = passwordSchema.safeParse(next);
    if (!pwCheck.success) { setFeedback({ type: "error", message: pwCheck.error.issues[0].message }); return; }
    setSaving(true);
    try {
      await changePassword(current, next);
      setFeedback({ type: "success", message: "Password changed successfully." });
      setCurrent(""); setNext(""); setConfirm("");
    } catch (err: any) {
      setFeedback({ type: "error", message: err?.response?.data?.detail ?? err?.message ?? "Failed to change password." });
    } finally { setSaving(false); }
  };

  return (
    <div className="space-y-5">
      <h3 className="text-sm font-bold text-foreground">Change Password</h3>
      {forceChange && (
        <div className="flex items-start gap-3 rounded-xl border border-amber-300 dark:border-amber-700/60 bg-amber-50 dark:bg-amber-950/40 p-4 animate-scale-in">
          <ShieldAlert className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-amber-700 dark:text-amber-300">You must change your default password before continuing</p>
            <p className="text-xs text-amber-600/80 dark:text-amber-400/70 mt-0.5">Your account was created with a temporary password. Please set a new secure password.</p>
          </div>
        </div>
      )}
      <form onSubmit={handleSubmit} className="space-y-4">
        <FormField label="Current password" htmlFor="pwd-current">
          <Input id="pwd-current" type="password" value={current} onChange={(e) => setCurrent(e.target.value)} placeholder="Current password" className={inputClasses} required autoComplete="current-password" />
        </FormField>
        <FormField label="New password" htmlFor="pwd-new">
          <Input id="pwd-new" type="password" value={next} onChange={(e) => setNext(e.target.value)} placeholder="New password" className={inputClasses} required autoComplete="new-password" />
        </FormField>
        <FormField label="Confirm new password" htmlFor="pwd-confirm" hint={`Minimum ${PASSWORD_MIN_LENGTH} characters with upper, lower, and number.`}>
          <Input id="pwd-confirm" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="Confirm new password" className={inputClasses} required autoComplete="new-password" />
        </FormField>
        {feedback && <Feedback type={feedback.type} message={feedback.message} />}
        <Button type="submit" disabled={saving} className={primaryBtnClasses}>
          {saving ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Changing...</> : "Change Password"}
        </Button>
      </form>
    </div>
  );
}

function MfaPanel() {
  const { user } = useAuth();
  const router = useRouter();
  const mfaEnabled = !!user?.mfa_enabled;
  const [setupData, setSetupData] = useState<MfaSetupData | null>(null);
  const [activateCode, setActivateCode] = useState("");
  const [disablePassword, setDisablePassword] = useState("");
  const [showDisablePassword, setShowDisablePassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);
  const [copiedSecret, setCopiedSecret] = useState(false);
  const [recoveryVisible, setRecoveryVisible] = useState(false);
  const [activated, setActivated] = useState(false);

  async function startSetup() {
    setFeedback(null); setLoading(true);
    try {
      const { data } = await authApi.post<MfaSetupData>("/api/auth/mfa/setup");
      setSetupData(data);
    } catch (err: any) {
      setFeedback({ type: "error", message: err?.response?.data?.detail ?? "Failed to start MFA setup." });
    } finally { setLoading(false); }
  }

  async function activateMfa(e: React.FormEvent) {
    e.preventDefault();
    if (activateCode.length !== 6) { setFeedback({ type: "error", message: "Enter the 6-digit code from your authenticator app." }); return; }
    setFeedback(null); setLoading(true);
    try {
      await authApi.post("/api/auth/mfa/activate", { code: activateCode });
      setActivated(true);
      setFeedback({ type: "success", message: "Two-factor authentication enabled successfully." });
    } catch (err: any) {
      setFeedback({ type: "error", message: err?.response?.data?.detail ?? "Invalid code. Please try again." });
    } finally { setLoading(false); }
  }

  async function disableMfa(e: React.FormEvent) {
    e.preventDefault();
    setFeedback(null); setLoading(true);
    try {
      await authApi.post("/api/auth/mfa/disable", { password: disablePassword });
      setDisablePassword("");
      setFeedback({ type: "success", message: "Two-factor authentication has been disabled." });
      router.refresh();
    } catch (err: any) {
      setFeedback({ type: "error", message: err?.response?.data?.detail ?? "Failed to disable MFA." });
    } finally { setLoading(false); }
  }

  function copySecret() {
    if (!setupData?.secret) return;
    navigator.clipboard.writeText(setupData.secret).then(() => { setCopiedSecret(true); setTimeout(() => setCopiedSecret(false), 2000); });
  }

  return (
    <div className="space-y-5 pt-6 mt-6 border-t border-border/40">
      <h3 className="text-sm font-bold text-foreground">Two-Factor Authentication</h3>
      <p className="text-xs text-muted-foreground leading-relaxed">Add an extra layer of security using a TOTP authenticator app.</p>

      {feedback && <Feedback type={feedback.type} message={feedback.message} />}

      {mfaEnabled ? (
        <div className="space-y-4">
          <div className="flex items-center gap-2.5 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800/60 p-3.5">
            <ShieldCheck className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
            <p className="text-sm text-emerald-700 dark:text-emerald-300 font-semibold">Two-factor authentication is active</p>
          </div>
          <form onSubmit={disableMfa} className="space-y-4">
            <p className="text-xs text-muted-foreground leading-relaxed">To disable 2FA, enter your current password to confirm.</p>
            <div className="relative">
              <Input type={showDisablePassword ? "text" : "password"} value={disablePassword} onChange={(e) => setDisablePassword(e.target.value)} placeholder="Current password" className={`${inputClasses} pr-10`} required autoComplete="current-password" />
              <button type="button" onClick={() => setShowDisablePassword((v) => !v)} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors" tabIndex={-1} aria-label={showDisablePassword ? "Hide password" : "Show password"}>
                {showDisablePassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
            <Button type="submit" variant="outline" disabled={loading || !disablePassword} className="h-9 rounded-xl text-sm font-medium text-red-600 dark:text-red-400 border-2 border-red-200 dark:border-red-800/60 hover:bg-red-50 dark:hover:bg-red-950/40 transition-all duration-200 btn-press">
              {loading ? <><Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />Disabling...</> : "Disable Two-Factor Authentication"}
            </Button>
          </form>
        </div>
      ) : setupData && !activated ? (
        <div className="space-y-6">
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-500/15 text-[11px] font-bold text-blue-600 dark:text-blue-400">1</span>
              <p className="text-sm font-semibold text-foreground">Scan this QR code with your authenticator app</p>
            </div>
            <p className="text-xs text-muted-foreground ml-8 leading-relaxed">Use Google Authenticator, Authy, 1Password, or any TOTP-compatible app.</p>
            <div className="flex justify-center py-3">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={setupData.qr_code_url} alt="MFA QR code" className="w-44 h-44 rounded-xl border border-border/60 bg-white p-1.5 shadow-sm" />
            </div>
          </div>
          <div className="space-y-2 rounded-xl bg-muted/40 border border-border/40 p-4">
            <p className="text-xs text-muted-foreground font-medium">Can&apos;t scan? Enter this secret manually:</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 rounded-lg border border-border/60 bg-background px-3 py-2 text-xs font-mono tracking-wider break-all">{setupData.secret}</code>
              <button type="button" onClick={copySecret} className={`shrink-0 flex items-center gap-1 rounded-lg border px-2.5 py-2 text-xs font-medium transition-all duration-200 btn-press ${copiedSecret ? "border-emerald-300 dark:border-emerald-700 text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40" : "border-border/60 text-muted-foreground hover:text-foreground hover:bg-muted/50"}`} aria-label="Copy secret">
                <Copy className="h-3.5 w-3.5" />{copiedSecret ? "Copied!" : "Copy"}
              </button>
            </div>
          </div>
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-500/15 text-[11px] font-bold text-blue-600 dark:text-blue-400">2</span>
              <p className="text-sm font-semibold text-foreground">Save your recovery codes</p>
            </div>
            <p className="text-xs text-muted-foreground ml-8 leading-relaxed">Store these in a safe place. Each code can be used once if you lose your device.</p>
            <button type="button" onClick={() => setRecoveryVisible((v) => !v)} className="ml-8 text-xs font-medium text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 link-underline transition-colors">
              {recoveryVisible ? "Hide recovery codes" : "Show recovery codes"}
            </button>
            {recoveryVisible && (
              <div className="grid grid-cols-2 gap-1.5 mt-2 ml-8 animate-scale-in">
                {setupData.recovery_codes.map((c) => (
                  <code key={c} className="rounded-lg border border-border/60 bg-muted/40 px-3 py-1.5 text-xs font-mono text-center">{c}</code>
                ))}
              </div>
            )}
          </div>
          <form onSubmit={activateMfa} className="space-y-4">
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-500/15 text-[11px] font-bold text-blue-600 dark:text-blue-400">3</span>
              <p className="text-sm font-semibold text-foreground">Enter the 6-digit code to verify</p>
            </div>
            <Input type="tel" inputMode="numeric" pattern="[0-9]*" maxLength={6} placeholder="000000" value={activateCode} onChange={(e) => setActivateCode(e.target.value.replace(/\D/g, "").slice(0, 6))} required autoComplete="one-time-code" className={`${inputClasses} text-center tracking-[0.3em] text-base font-mono`} />
            <Button type="submit" disabled={loading || activateCode.length !== 6} className={`${primaryBtnClasses} w-full`}>
              {loading ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Activating...</> : "Enable Two-Factor Authentication"}
            </Button>
          </form>
        </div>
      ) : !activated ? (
        <Button onClick={startSetup} disabled={loading} className={primaryBtnClasses}>
          {loading ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Starting setup...</> : <><QrCode className="mr-2 h-4 w-4" />Enable Two-Factor Authentication</>}
        </Button>
      ) : null}
    </div>
  );
}

function SessionsPanel() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);

  const fetchSessions = useCallback(async () => {
    try {
      const { data } = await authApi.get<Session[]>("/api/auth/sessions");
      setSessions(data);
    } catch (err: any) {
      setFeedback({ type: "error", message: err?.response?.data?.detail ?? err?.message ?? "Failed to load sessions." });
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchSessions(); }, [fetchSessions]);

  async function revokeSession(id: string) {
    setRevoking(id); setFeedback(null);
    try {
      await authApi.delete(`/api/auth/sessions/${id}`);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      setFeedback({ type: "success", message: "Session revoked." });
    } catch (err: any) {
      setFeedback({ type: "error", message: err?.response?.data?.detail ?? "Failed to revoke session." });
    } finally { setRevoking(null); }
  }

  async function revokeAll() {
    setRevoking("all"); setFeedback(null);
    try {
      await authApi.delete("/api/auth/sessions");
      setSessions((prev) => prev.filter((s) => s.is_current));
      setFeedback({ type: "success", message: "All other sessions revoked." });
    } catch (err: any) {
      setFeedback({ type: "error", message: err?.response?.data?.detail ?? "Failed to revoke sessions." });
    } finally { setRevoking(null); }
  }

  function formatDate(iso: string) {
    try { return new Date(iso).toLocaleString(); } catch { return iso; }
  }

  return (
    <div className="space-y-4 pt-6 mt-6 border-t border-border/40">
      <h3 className="text-sm font-bold text-foreground">Active Sessions</h3>
      <p className="text-xs text-muted-foreground leading-relaxed">Manage devices and sessions signed in to your account.</p>
      {feedback && <Feedback type={feedback.type} message={feedback.message} />}
      {loading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-4"><Loader2 className="h-4 w-4 animate-spin" />Loading sessions...</div>
      ) : sessions.length === 0 ? (
        <p className="text-sm text-muted-foreground py-2">No active sessions found.</p>
      ) : (
        <>
          <div className="overflow-x-auto rounded-xl border border-border/40">
            <table className="w-full text-sm premium-table">
              <thead>
                <tr className="border-b border-border/60 bg-muted/30">
                  <th className="text-left text-[10px] font-bold uppercase tracking-wider text-muted-foreground py-3 px-4">IP</th>
                  <th className="text-left text-[10px] font-bold uppercase tracking-wider text-muted-foreground py-3 px-4">Browser / Device</th>
                  <th className="text-left text-[10px] font-bold uppercase tracking-wider text-muted-foreground py-3 px-4">Created</th>
                  <th className="text-left text-[10px] font-bold uppercase tracking-wider text-muted-foreground py-3 px-4">Last used</th>
                  <th className="py-3 px-4" />
                </tr>
              </thead>
              <tbody>
                {sessions.map((s) => (
                  <tr key={s.id} className="border-b border-border/30 last:border-0 hover:bg-muted/20 transition-colors duration-150">
                    <td className="py-3 px-4 font-mono text-xs text-foreground">{s.ip_address}</td>
                    <td className="py-3 px-4 text-xs text-muted-foreground">
                      {s.user_agent.length > 60 ? s.user_agent.slice(0, 57) + "..." : s.user_agent}
                      {s.is_current && <span className="ml-2 inline-flex items-center rounded-full bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800/60 px-2 py-0.5 text-[10px] font-bold text-emerald-600 dark:text-emerald-400">Current</span>}
                    </td>
                    <td className="py-3 px-4 text-xs text-muted-foreground whitespace-nowrap tabular-nums">{formatDate(s.created_at)}</td>
                    <td className="py-3 px-4 text-xs text-muted-foreground whitespace-nowrap tabular-nums">{formatDate(s.last_used_at)}</td>
                    <td className="py-3 px-4">
                      {!s.is_current && (
                        <button onClick={() => revokeSession(s.id)} disabled={revoking === s.id} className="flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40 transition-all duration-200 disabled:opacity-50 btn-press" aria-label="Revoke this session">
                          {revoking === s.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {sessions.filter((s) => !s.is_current).length > 0 && (
            <Button variant="outline" size="sm" onClick={revokeAll} disabled={revoking === "all"} className="h-9 rounded-xl text-sm font-medium text-red-600 dark:text-red-400 border-2 border-red-200 dark:border-red-800/60 hover:bg-red-50 dark:hover:bg-red-950/40 transition-all duration-200 btn-press">
              {revoking === "all" ? <><Loader2 className="mr-2 h-3 w-3 animate-spin" />Revoking...</> : <><Trash2 className="mr-2 h-3 w-3" />Revoke All Other Sessions</>}
            </Button>
          )}
        </>
      )}
    </div>
  );
}

function SecurityTab({ forceChange }: { forceChange: boolean }) {
  return (
    <div className="space-y-0">
      <SectionHeader icon={KeyRound} title="Security" description="Manage your password, two-factor authentication, and active sessions." />
      <ChangePasswordPanel forceChange={forceChange} />
      <MfaPanel />
      <SessionsPanel />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Notifications tab (placeholder)
// ---------------------------------------------------------------------------

function NotificationsTab() {
  return (
    <div>
      <SectionHeader icon={Bell} title="Notifications" description="Control how and when you receive alerts." />
      <p className="text-sm text-muted-foreground">Notification preferences will be available in an upcoming release.</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// EMR Connections tab (placeholder)
// ---------------------------------------------------------------------------

function EmrConnectionsTab() {
  return (
    <div>
      <SectionHeader icon={Plug} title="EMR Connections" description="Connect your Electronic Medical Record systems." />
      <p className="text-sm text-muted-foreground">EMR connection management is available via the admin panel.</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Branding tab (placeholder)
// ---------------------------------------------------------------------------

function BrandingTab() {
  return (
    <div>
      <SectionHeader icon={Palette} title="Branding" description="Customize the look and feel of your workspace." />
      <p className="text-sm text-muted-foreground">Branding customization will be available in an upcoming release.</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Team tab
// ---------------------------------------------------------------------------

function TeamTab() {
  return (
    <div>
      <SectionHeader icon={Users} title="Team" description="Manage team members and their access levels." />
      <div className="flex items-start gap-3 rounded-xl border border-amber-200 dark:border-amber-800/60 bg-amber-50 dark:bg-amber-950/30 p-4">
        <ShieldAlert className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
        <div className="space-y-1">
          <p className="text-sm font-semibold text-amber-700 dark:text-amber-300">Admin access required</p>
          <p className="text-xs text-amber-600/80 dark:text-amber-400/70 leading-relaxed">
            Full user management is available in the admin panel. Navigate to{" "}
            <a href="/users" className="underline underline-offset-2 font-medium hover:text-amber-800 dark:hover:text-amber-200 transition-colors">Admin &rarr; Users</a>{" "}
            to manage team access.
          </p>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// API Keys tab — AI Analysis + Feature Flags for admins
// ---------------------------------------------------------------------------

interface AiSettings {
  ai_analysis_cutoff_date: string;
  max_analyses_per_patient_per_day: number;
}

function AiAnalysisPanel() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [cutoffDate, setCutoffDate] = useState("");
  const [maxPerDay, setMaxPerDay] = useState<number>(2);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const { data } = await authApi.get<AiSettings>("/api/config/ai-settings");
        setCutoffDate(data.ai_analysis_cutoff_date);
        setMaxPerDay(data.max_analyses_per_patient_per_day);
      } catch (err: any) {
        setFeedback({ type: "error", message: err?.response?.data?.detail ?? "Failed to load AI settings." });
      } finally { setLoading(false); }
    })();
  }, []);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true); setFeedback(null);
    try {
      const { data } = await authApi.put<AiSettings>("/api/config/ai-settings", {
        ai_analysis_cutoff_date: cutoffDate,
        max_analyses_per_patient_per_day: maxPerDay,
      });
      setCutoffDate(data.ai_analysis_cutoff_date);
      setMaxPerDay(data.max_analyses_per_patient_per_day);
      setFeedback({ type: "success", message: "AI settings saved successfully." });
    } catch (err: any) {
      setFeedback({ type: "error", message: err?.response?.data?.detail ?? "Failed to save AI settings." });
    } finally { setSaving(false); }
  }

  return (
    <div className="space-y-5 pt-6 mt-6 border-t border-border/40">
      <h3 className="text-sm font-bold text-foreground">AI Analysis</h3>
      <p className="text-xs text-muted-foreground leading-relaxed">Control how AI analyses are bounded in time and throttled per patient.</p>
      {loading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-4"><Loader2 className="h-4 w-4 animate-spin" />Loading AI settings...</div>
      ) : (
        <form onSubmit={handleSave} className="space-y-5">
          <FormField label="AI Analysis Cutoff Date" htmlFor="ai-cutoff-date" hint="Clinical data dated after this day is excluded from AI analysis.">
            <Input id="ai-cutoff-date" type="date" value={cutoffDate} onChange={(e) => setCutoffDate(e.target.value)} className={inputClasses} required />
          </FormField>
          <FormField label="Max Analyses per Patient per Day" htmlFor="ai-max-per-day" hint="Upper bound on AI re-analyses of the same patient within a single calendar day.">
            <Input id="ai-max-per-day" type="number" min={1} max={100} value={maxPerDay} onChange={(e) => setMaxPerDay(Number(e.target.value))} className={inputClasses} required />
          </FormField>
          {feedback && <Feedback type={feedback.type} message={feedback.message} />}
          <Button type="submit" disabled={saving} className={primaryBtnClasses}>
            {saving ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Saving...</> : "Save AI Settings"}
          </Button>
        </form>
      )}
    </div>
  );
}

function FeatureFlagsPanel() {
  const { flags, orderedKeys, loading, error, setFlag, resetAll } = useFeatureFlagsAll();
  const [resetting, setResetting] = useState(false);
  const [resetFeedback, setResetFeedback] = useState<{ type: "success" | "error"; message: string } | null>(null);

  const categories = Array.from(new Set(orderedKeys.map((k) => flags[k]?.category ?? "Misc")));

  async function handleReset() {
    setResetting(true); setResetFeedback(null);
    try {
      await resetAll();
      setResetFeedback({ type: "success", message: "All feature flags reset to defaults." });
    } catch {
      setResetFeedback({ type: "error", message: "Failed to reset feature flags." });
    } finally { setResetting(false); }
  }

  return (
    <div className="space-y-5 pt-6 mt-6 border-t border-border/40">
      <h3 className="text-sm font-bold text-foreground">Feature Flags</h3>
      <p className="text-xs text-muted-foreground leading-relaxed">Enable or disable product features. Changes take effect immediately.</p>
      {loading ? (
        <div className="space-y-3">{Array.from({ length: 4 }).map((_, i) => <div key={i} className="skeleton h-10 rounded-xl" />)}</div>
      ) : error ? (
        <Feedback type="error" message={`Failed to load feature flags: ${error}`} />
      ) : orderedKeys.length === 0 ? (
        <p className="text-sm text-muted-foreground py-2">No feature flags configured.</p>
      ) : (
        <div className="space-y-5">
          {categories.map((cat) => {
            const catKeys = orderedKeys.filter((k) => (flags[k]?.category ?? "Misc") === cat);
            return (
              <div key={cat}>
                <p className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground mb-2">{cat}</p>
                <div className="rounded-xl border border-border/40 overflow-hidden divide-y divide-border/30">
                  {catKeys.map((key) => {
                    const flag = flags[key];
                    if (!flag) return null;
                    return (
                      <div key={key} className="flex items-center justify-between gap-4 px-4 py-3 hover:bg-muted/20 transition-colors duration-150">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-semibold text-foreground truncate">{flag.name || key}</span>
                            {flag.enabled !== flag.default_enabled && (
                              <span className="text-[10px] font-bold rounded-full px-1.5 py-0.5 bg-amber-100 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800/60">override</span>
                            )}
                          </div>
                          {flag.description && <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">{flag.description}</p>}
                          <p className="text-[10px] text-muted-foreground/60 font-mono mt-0.5">{key}</p>
                        </div>
                        <button onClick={() => setFlag(key, !flag.enabled)} aria-label={`${flag.enabled ? "Disable" : "Enable"} ${flag.name || key}`} aria-pressed={flag.enabled} className="shrink-0 flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-all duration-200 border btn-press" style={{ background: flag.enabled ? `linear-gradient(135deg, ${tokens.success}, ${tokens.successDark})` : undefined, color: flag.enabled ? "#fff" : undefined }}>
                          {flag.enabled ? <><ToggleRight className="h-3.5 w-3.5" /> Enabled</> : <><ToggleLeft className="h-3.5 w-3.5" /> Disabled</>}
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
          {resetFeedback && <div className="mt-2"><Feedback type={resetFeedback.type} message={resetFeedback.message} /></div>}
          <Button type="button" variant="outline" size="sm" disabled={resetting} onClick={handleReset} className="h-9 rounded-xl text-sm font-medium border-2 border-border/60 hover:bg-muted/50 transition-all duration-200 btn-press">
            {resetting ? <><Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />Resetting...</> : <><RotateCcw className="mr-2 h-3.5 w-3.5" />Reset All to Defaults</>}
          </Button>
        </div>
      )}
    </div>
  );
}

function ApiKeysTab({ isAdmin }: { isAdmin: boolean }) {
  return (
    <div>
      <SectionHeader icon={Key} title="API Keys" description="Manage API keys and configure AI analysis parameters." />
      <p className="text-sm text-muted-foreground mb-6">API key management for external integrations.</p>
      {isAdmin && (
        <>
          <AiAnalysisPanel />
          <FeatureFlagsPanel />
        </>
      )}
      {!isAdmin && <p className="text-sm text-muted-foreground">API key management requires admin access.</p>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Compliance tab (placeholder)
// ---------------------------------------------------------------------------

function ComplianceTab() {
  return (
    <div>
      <SectionHeader icon={FileCheck} title="Compliance" description="HIPAA audit logs, data retention, and compliance settings." />
      <p className="text-sm text-muted-foreground">Compliance settings will be available in an upcoming release.</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tab definition
// ---------------------------------------------------------------------------

interface TabDef {
  id: TabId;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

const ALL_TABS: TabDef[] = [
  { id: "profile", label: "Profile", icon: User },
  { id: "security", label: "Security", icon: ShieldCheck },
  { id: "notifications", label: "Notifications", icon: Bell },
  { id: "emr-connections", label: "EMR Connections", icon: Plug },
  { id: "branding", label: "Branding", icon: Palette },
  { id: "team", label: "Team", icon: Users },
  { id: "api-keys", label: "API Keys", icon: Key },
  { id: "compliance", label: "Compliance", icon: FileCheck },
];

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function SettingsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const searchParams = useSearchParams();
  const forcePasswordChange = searchParams.get("force_password_change") === "true";

  // Hash-driven tab selection: /settings#security → "security"
  const [activeTab, setActiveTab] = useState<TabId>(() => {
    if (typeof window !== "undefined") {
      const hash = window.location.hash.replace("#", "");
      if (isValidTab(hash)) return hash;
    }
    return forcePasswordChange ? "security" : "profile";
  });

  // Sync hash on tab change
  const handleTabChange = useCallback((value: string) => {
    if (!isValidTab(value)) return;
    setActiveTab(value);
    if (typeof window !== "undefined") {
      window.history.replaceState(null, "", `#${value}`);
    }
  }, []);

  // React to external hash changes (back/forward navigation)
  useEffect(() => {
    function onHashChange() {
      const hash = window.location.hash.replace("#", "");
      if (isValidTab(hash)) setActiveTab(hash);
    }
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  return (
    <div className="max-w-5xl space-y-5">
      {/* Page header */}
      <div className="flex items-center gap-4 animate-fade-in">
        <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500/15 to-cyan-500/10 border border-blue-500/20 shadow-sm">
          <Settings className="h-5 w-5 text-blue-500 dark:text-blue-400" />
        </div>
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground">Settings</h1>
          <p className="text-sm text-muted-foreground">Manage your account and preferences</p>
        </div>
      </div>

      {/* Vertical tab layout */}
      <Tabs
        orientation="vertical"
        value={activeTab}
        onValueChange={handleTabChange}
        className="gap-6"
      >
        {/* Left nav */}
        <TabsList
          className="w-52 shrink-0 self-start sticky top-20 flex flex-col h-auto gap-0.5 bg-transparent p-0"
          aria-label="Settings sections"
        >
          {ALL_TABS.map(({ id, label, icon: Icon }) => (
            <TabsTrigger
              key={id}
              value={id}
              className="w-full justify-start gap-2.5 px-3.5 py-2.5 rounded-xl text-sm font-medium data-active:bg-blue-600 data-active:text-white data-active:shadow-md data-active:shadow-blue-500/25 hover:bg-muted/60 hover:text-foreground transition-all duration-200"
            >
              <Icon className="h-4 w-4 shrink-0" />
              {label}
            </TabsTrigger>
          ))}
        </TabsList>

        {/* Right content — only the active panel is rendered */}
        <div className="premium-card flex-1 min-w-0 p-6 animate-slide-up">
          <TabsContent value="profile"><ProfileTab /></TabsContent>
          <TabsContent value="security"><SecurityTab forceChange={forcePasswordChange} /></TabsContent>
          <TabsContent value="notifications"><NotificationsTab /></TabsContent>
          <TabsContent value="emr-connections"><EmrConnectionsTab /></TabsContent>
          <TabsContent value="branding"><BrandingTab /></TabsContent>
          <TabsContent value="team"><TeamTab /></TabsContent>
          <TabsContent value="api-keys"><ApiKeysTab isAdmin={isAdmin} /></TabsContent>
          <TabsContent value="compliance"><ComplianceTab /></TabsContent>
        </div>
      </Tabs>
    </div>
  );
}
