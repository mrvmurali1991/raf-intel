"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/contexts/auth-context";
import { authApi } from "@/contexts/auth-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
  X,
} from "lucide-react";

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
  qr_code_url: string;   // data URI or external URL for QR image
  secret: string;        // base32 secret for manual entry
  recovery_codes: string[];
}

// ---------------------------------------------------------------------------
// Toast component (self-contained)
// ---------------------------------------------------------------------------

interface ToastMessage {
  id: number;
  type: "success" | "error";
  message: string;
}

let toastIdCounter = 0;
let globalSetToasts: React.Dispatch<React.SetStateAction<ToastMessage[]>> | null = null;

function showToast(type: "success" | "error", message: string) {
  const id = ++toastIdCounter;
  globalSetToasts?.((prev) => [...prev, { id, type, message }]);
  setTimeout(() => {
    globalSetToasts?.((prev) => prev.filter((t) => t.id !== id));
  }, 4000);
}

function ToastContainer() {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  globalSetToasts = setToasts;

  if (toasts.length === 0) return null;
  return (
    <div className="fixed top-5 right-5 z-[100] flex flex-col gap-2 max-w-sm">
      {toasts.map((t) => (
        <div
          key={t.id}
          role="status"
          className={`flex items-center gap-2.5 rounded-xl px-4 py-3 text-sm font-medium shadow-lg border animate-slide-up ${
            t.type === "success"
              ? "bg-emerald-50 dark:bg-emerald-950/90 border-emerald-200 dark:border-emerald-800/60 text-emerald-700 dark:text-emerald-300"
              : "bg-red-50 dark:bg-red-950/90 border-red-200 dark:border-red-800/60 text-red-700 dark:text-red-300"
          }`}
        >
          {t.type === "success" ? (
            <CheckCircle2 className="h-4 w-4 shrink-0" />
          ) : (
            <AlertCircle className="h-4 w-4 shrink-0" />
          )}
          <span className="flex-1">{t.message}</span>
          <button
            onClick={() => setToasts((prev) => prev.filter((x) => x.id !== t.id))}
            className="shrink-0 text-current opacity-60 hover:opacity-100 transition-opacity"
            aria-label="Dismiss"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Unsaved changes banner
// ---------------------------------------------------------------------------

function UnsavedChangesBanner({ visible }: { visible: boolean }) {
  if (!visible) return null;
  return (
    <div
      role="alert"
      className="flex items-center gap-2.5 rounded-xl px-4 py-3 text-sm font-medium border border-amber-300 dark:border-amber-700/60 bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 animate-scale-in"
    >
      <AlertCircle className="h-4 w-4 shrink-0" />
      You have unsaved changes
    </div>
  );
}

// ---------------------------------------------------------------------------
// Navigation guard hook
// ---------------------------------------------------------------------------

function useNavigationGuard(dirty: boolean) {
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);
}

// ---------------------------------------------------------------------------
// Section navigation tabs
// ---------------------------------------------------------------------------

interface NavTab {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

function SectionNav({
  tabs,
  activeTab,
  onTabChange,
}: {
  tabs: NavTab[];
  activeTab: string;
  onTabChange: (id: string) => void;
}) {
  return (
    <nav className="premium-card p-1.5 flex gap-1 overflow-x-auto animate-slide-up" aria-label="Settings sections">
      {tabs.map((tab) => {
        const Icon = tab.icon;
        const isActive = activeTab === tab.id;
        return (
          <button
            key={tab.id}
            onClick={() => {
              onTabChange(tab.id);
              document.getElementById(`section-${tab.id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
            }}
            className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-semibold whitespace-nowrap transition-all duration-200 btn-press ${
              isActive
                ? "bg-gradient-to-r from-blue-600 to-blue-500 text-white shadow-md shadow-blue-500/25"
                : "text-muted-foreground hover:text-foreground hover:bg-muted/60"
            }`}
            aria-current={isActive ? "true" : undefined}
          >
            <Icon className="h-3.5 w-3.5" />
            {tab.label}
          </button>
        );
      })}
    </nav>
  );
}

// ---------------------------------------------------------------------------
// Section wrapper — premium-card with entrance animation
// ---------------------------------------------------------------------------

function Section({
  id,
  icon: Icon,
  title,
  description,
  staggerIndex = 0,
  children,
}: {
  id?: string;
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  description?: string;
  staggerIndex?: number;
  children: React.ReactNode;
}) {
  const staggerClass = staggerIndex > 0 && staggerIndex <= 6 ? `stagger-${staggerIndex}` : "";
  return (
    <section
      id={id ? `section-${id}` : undefined}
      className={`premium-card hover-lift overflow-hidden animate-slide-up ${staggerClass}`}
      style={{ scrollMarginTop: "6rem" }}
    >
      <div className="px-6 py-5 border-b border-border/60 flex items-start gap-3">
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
      <div className="px-6 py-6">{children}</div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Form field wrapper — consistent label styling
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Styled input — focus ring animation
// ---------------------------------------------------------------------------

const inputClasses =
  "h-10 rounded-xl border-border/60 bg-muted/30 transition-all duration-200 focus:bg-background focus:border-blue-500/50 focus:ring-2 focus:ring-blue-500/20 focus:shadow-[0_0_0_3px_rgba(59,130,246,0.1)] placeholder:text-muted-foreground/50";

// ---------------------------------------------------------------------------
// Inline feedback
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Form error summary
// ---------------------------------------------------------------------------

function ErrorSummary({ errors }: { errors: string[] }) {
  if (errors.length === 0) return null;
  return (
    <div
      role="alert"
      className="rounded-xl border border-red-200 dark:border-red-800/60 bg-red-50 dark:bg-red-950/40 p-4 space-y-1.5 animate-scale-in"
    >
      <p className="text-sm font-semibold text-red-700 dark:text-red-300 flex items-center gap-2">
        <AlertCircle className="h-4 w-4 shrink-0" />
        Please fix the following errors:
      </p>
      <ul className="list-disc list-inside text-sm text-red-600 dark:text-red-400 space-y-0.5 ml-6">
        {errors.map((err, i) => (
          <li key={i}>{err}</li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Password requirements inline indicator
// ---------------------------------------------------------------------------

function PasswordRequirements({ password }: { password: string }) {
  const requirements = [
    { label: "At least 8 characters", met: password.length >= 8 },
    { label: "One uppercase letter", met: /[A-Z]/.test(password) },
    { label: "One number", met: /[0-9]/.test(password) },
    { label: "One special character (!@#$%...)", met: /[^A-Za-z0-9]/.test(password) },
  ];

  if (!password) return null;

  return (
    <div className="space-y-1 mt-2">
      {requirements.map((req) => (
        <div key={req.label} className="flex items-center gap-2 text-xs">
          {req.met ? (
            <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500 shrink-0" />
          ) : (
            <AlertCircle className="h-3.5 w-3.5 text-muted-foreground/50 shrink-0" />
          )}
          <span className={req.met ? "text-emerald-600 dark:text-emerald-400" : "text-muted-foreground/70"}>
            {req.label}
          </span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Gradient primary button classes
// ---------------------------------------------------------------------------

const primaryBtnClasses =
  "h-10 rounded-xl font-semibold text-sm bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-700 hover:to-blue-600 shadow-lg shadow-blue-500/20 hover:shadow-blue-500/30 transition-all duration-200 btn-press";

const disabledPrimaryBtnClasses =
  "h-10 rounded-xl font-semibold text-sm bg-gradient-to-r from-blue-600 to-blue-500 shadow-lg shadow-blue-500/20 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed disabled:shadow-none";

const outlineBtnClasses =
  "h-9 rounded-xl text-sm font-medium border-2 border-border/60 text-foreground hover:bg-muted/50 hover:border-border transition-all duration-200 btn-press";

// ---------------------------------------------------------------------------
// Profile section
// ---------------------------------------------------------------------------

function ProfileSection() {
  const { user, updateProfile } = useAuth();
  const [firstName, setFirstName] = useState(user?.first_name ?? "");
  const [lastName, setLastName] = useState(user?.last_name ?? "");
  const [title, setTitle] = useState(user?.title ?? "");
  const [avatarUrl, setAvatarUrl] = useState(user?.avatar_url ?? "");
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; message: string } | null>(
    null
  );
  const [errors, setErrors] = useState<string[]>([]);

  const isDirty = useMemo(() => {
    return (
      firstName !== (user?.first_name ?? "") ||
      lastName !== (user?.last_name ?? "") ||
      title !== (user?.title ?? "") ||
      avatarUrl !== (user?.avatar_url ?? "")
    );
  }, [firstName, lastName, title, avatarUrl, user]);

  useNavigationGuard(isDirty);

  const validate = (): string[] => {
    const errs: string[] = [];
    if (!firstName.trim()) errs.push("First name is required.");
    if (!lastName.trim()) errs.push("Last name is required.");
    return errs;
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setFeedback(null);
    const validationErrors = validate();
    setErrors(validationErrors);
    if (validationErrors.length > 0) return;

    setSaving(true);
    try {
      await updateProfile({ first_name: firstName, last_name: lastName, title, avatar_url: avatarUrl });
      setFeedback({ type: "success", message: "Profile updated successfully." });
      showToast("success", "Settings saved successfully");
    } catch (err: any) {
      setFeedback({
        type: "error",
        message: err?.response?.data?.detail ?? err?.message ?? "Failed to update profile.",
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Section id="profile" icon={User} title="Profile" description="Update your personal information." staggerIndex={1}>
      <form onSubmit={handleSave} className="space-y-5">
        <ErrorSummary errors={errors} />
        <UnsavedChangesBanner visible={isDirty} />

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <FormField label="First name" htmlFor="profile-first-name">
            <Input
              id="profile-first-name"
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              placeholder="First name"
              className={inputClasses}
              required
            />
          </FormField>
          <FormField label="Last name" htmlFor="profile-last-name">
            <Input
              id="profile-last-name"
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
              placeholder="Last name"
              className={inputClasses}
              required
            />
          </FormField>
        </div>

        <FormField label="Email address" htmlFor="profile-email" hint="Email cannot be changed here. Contact your administrator.">
          <Input
            id="profile-email"
            value={user?.email ?? ""}
            disabled
            className="h-10 rounded-xl opacity-50 cursor-not-allowed bg-muted/40"
          />
        </FormField>

        <FormField label="Title / Credentials" htmlFor="profile-title">
          <Input
            id="profile-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. MD, RN, CPC"
            className={inputClasses}
          />
        </FormField>

        <FormField label="Avatar URL" htmlFor="profile-avatar-url">
          <Input
            id="profile-avatar-url"
            value={avatarUrl}
            onChange={(e) => setAvatarUrl(e.target.value)}
            placeholder="https://..."
            type="url"
            className={inputClasses}
          />
        </FormField>

        {feedback && <Feedback type={feedback.type} message={feedback.message} />}

        <div className="flex items-center gap-3 pt-1">
          <Button
            type="submit"
            disabled={saving || !isDirty}
            className={isDirty ? primaryBtnClasses : disabledPrimaryBtnClasses}
          >
            {saving ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Saving...
              </>
            ) : (
              "Save Changes"
            )}
          </Button>
        </div>
      </form>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Change password section
// ---------------------------------------------------------------------------

function ChangePasswordSection({ forceChange = false }: { forceChange?: boolean }) {
  const { changePassword } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; message: string } | null>(
    null
  );
  const [errors, setErrors] = useState<string[]>([]);

  const isDirty = current !== "" || next !== "" || confirm !== "";

  useNavigationGuard(isDirty);

  const validate = (): string[] => {
    const errs: string[] = [];
    if (!current) errs.push("Current password is required.");
    if (next.length < 8) errs.push("Password must be at least 8 characters.");
    if (!/[A-Z]/.test(next)) errs.push("Password must contain at least one uppercase letter.");
    if (!/[0-9]/.test(next)) errs.push("Password must contain at least one number.");
    if (!/[^A-Za-z0-9]/.test(next)) errs.push("Password must contain at least one special character.");
    if (next !== confirm) errs.push("New passwords do not match.");
    return errs;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFeedback(null);
    const validationErrors = validate();
    setErrors(validationErrors);
    if (validationErrors.length > 0) return;

    setSaving(true);
    try {
      await changePassword(current, next);
      setFeedback({ type: "success", message: "Password changed successfully." });
      showToast("success", "Settings saved successfully");
      setCurrent("");
      setNext("");
      setConfirm("");
      setErrors([]);
    } catch (err: any) {
      setFeedback({
        type: "error",
        message: err?.response?.data?.detail ?? err?.message ?? "Failed to change password.",
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Section id="password" icon={KeyRound} title="Change Password" description="Update your login password." staggerIndex={2}>
      {forceChange && (
        <div className="mb-5 flex items-start gap-3 rounded-xl border border-amber-300 dark:border-amber-700/60 bg-amber-50 dark:bg-amber-950/40 p-4 animate-scale-in">
          <ShieldAlert className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-semibold text-amber-700 dark:text-amber-300">
              You must change your default password before continuing
            </p>
            <p className="text-xs text-amber-600/80 dark:text-amber-400/70 mt-0.5">
              Your account was created with a temporary password. Please set a new secure password to proceed.
            </p>
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-5">
        <ErrorSummary errors={errors} />
        <UnsavedChangesBanner visible={isDirty} />

        <FormField label="Current password" htmlFor="pwd-current">
          <Input
            id="pwd-current"
            type="password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            placeholder="Current password"
            className={inputClasses}
            required
            autoComplete="current-password"
          />
        </FormField>

        <FormField label="New password" htmlFor="pwd-new">
          <Input
            id="pwd-new"
            type="password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            placeholder="New password"
            className={inputClasses}
            required
            autoComplete="new-password"
            aria-describedby="pwd-hint"
          />
          <PasswordRequirements password={next} />
        </FormField>

        <FormField label="Confirm new password" htmlFor="pwd-confirm">
          <Input
            id="pwd-confirm"
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder="Confirm new password"
            className={inputClasses}
            required
            autoComplete="new-password"
          />
          {confirm && next !== confirm && (
            <p className="text-xs text-red-500 mt-1 flex items-center gap-1.5">
              <AlertCircle className="h-3.5 w-3.5" />
              Passwords do not match
            </p>
          )}
        </FormField>

        {feedback && <Feedback type={feedback.type} message={feedback.message} />}

        <div className="pt-1">
          <Button
            type="submit"
            disabled={saving || !isDirty}
            className={isDirty ? primaryBtnClasses : disabledPrimaryBtnClasses}
          >
            {saving ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Changing...
              </>
            ) : (
              "Save Changes"
            )}
          </Button>
        </div>
      </form>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// MFA section
// ---------------------------------------------------------------------------

function MfaSection() {
  const { user } = useAuth();
  const router = useRouter();
  const mfaEnabled = !!user?.mfa_enabled;

  // Setup flow state
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
    setFeedback(null);
    setLoading(true);
    try {
      const { data } = await authApi.post<MfaSetupData>("/api/auth/mfa/setup");
      setSetupData(data);
    } catch (err: any) {
      setFeedback({ type: "error", message: err?.response?.data?.detail ?? "Failed to start MFA setup." });
    } finally {
      setLoading(false);
    }
  }

  async function activateMfa(e: React.FormEvent) {
    e.preventDefault();
    if (activateCode.length !== 6) {
      setFeedback({ type: "error", message: "Enter the 6-digit code from your authenticator app." });
      return;
    }
    setFeedback(null);
    setLoading(true);
    try {
      await authApi.post("/api/auth/mfa/activate", { code: activateCode });
      setActivated(true);
      setFeedback({ type: "success", message: "Two-factor authentication enabled successfully." });
      showToast("success", "Settings saved successfully");
    } catch (err: any) {
      setFeedback({ type: "error", message: err?.response?.data?.detail ?? "Invalid code. Please try again." });
    } finally {
      setLoading(false);
    }
  }

  async function disableMfa(e: React.FormEvent) {
    e.preventDefault();
    setFeedback(null);
    setLoading(true);
    try {
      await authApi.post("/api/auth/mfa/disable", { password: disablePassword });
      setDisablePassword("");
      setFeedback({ type: "success", message: "Two-factor authentication has been disabled." });
      showToast("success", "Settings saved successfully");
      router.refresh();
    } catch (err: any) {
      setFeedback({ type: "error", message: err?.response?.data?.detail ?? "Failed to disable MFA." });
    } finally {
      setLoading(false);
    }
  }

  function copySecret() {
    if (!setupData?.secret) return;
    navigator.clipboard.writeText(setupData.secret).then(() => {
      setCopiedSecret(true);
      setTimeout(() => setCopiedSecret(false), 2000);
    });
  }

  return (
    <Section id="mfa" icon={ShieldCheck} title="Two-Factor Authentication" description="Add an extra layer of security to your account using a TOTP authenticator app." staggerIndex={3}>
      {feedback && (
        <div className="mb-4">
          <Feedback type={feedback.type} message={feedback.message} />
        </div>
      )}

      {mfaEnabled ? (
        /* ---- MFA already enabled ---- */
        <div className="space-y-5">
          <div className="flex items-center gap-2.5 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800/60 p-3.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-500/15">
              <ShieldCheck className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
            </div>
            <p className="text-sm text-emerald-700 dark:text-emerald-300 font-semibold">
              Two-factor authentication is active
            </p>
          </div>

          <form onSubmit={disableMfa} className="space-y-4">
            <p className="text-xs text-muted-foreground leading-relaxed">
              To disable two-factor authentication, enter your current password to confirm.
            </p>
            <div className="relative">
              <Input
                type={showDisablePassword ? "text" : "password"}
                value={disablePassword}
                onChange={(e) => setDisablePassword(e.target.value)}
                placeholder="Current password"
                className={`${inputClasses} pr-10`}
                required
                autoComplete="current-password"
              />
              <button
                type="button"
                onClick={() => setShowDisablePassword((v) => !v)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                tabIndex={-1}
                aria-label={showDisablePassword ? "Hide password" : "Show password"}
              >
                {showDisablePassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
            <Button
              type="submit"
              variant="outline"
              disabled={loading || !disablePassword}
              className="h-9 rounded-xl text-sm font-medium text-red-600 dark:text-red-400 border-2 border-red-200 dark:border-red-800/60 hover:bg-red-50 dark:hover:bg-red-950/40 hover:border-red-300 dark:hover:border-red-700 transition-all duration-200 btn-press"
            >
              {loading ? (
                <><Loader2 className="mr-2 h-3.5 w-3.5 animate-spin" />Disabling...</>
              ) : (
                "Disable Two-Factor Authentication"
              )}
            </Button>
          </form>
        </div>
      ) : setupData && !activated ? (
        /* ---- Setup in progress: show QR + verify ---- */
        <div className="space-y-6">
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-500/15 text-[11px] font-bold text-blue-600 dark:text-blue-400">1</span>
              <p className="text-sm font-semibold text-foreground">
                Scan this QR code with your authenticator app
              </p>
            </div>
            <p className="text-xs text-muted-foreground ml-8 leading-relaxed">
              Use Google Authenticator, Authy, 1Password, or any TOTP-compatible app.
            </p>
            <div className="flex justify-center py-3">
              { }
              <img
                src={setupData.qr_code_url}
                alt="MFA QR code"
                className="w-44 h-44 rounded-xl border border-border/60 bg-white p-1.5 shadow-sm"
              />
            </div>
          </div>

          <div className="space-y-2 rounded-xl bg-muted/40 border border-border/40 p-4">
            <p className="text-xs text-muted-foreground font-medium">
              Can&apos;t scan? Enter this secret manually:
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 rounded-lg border border-border/60 bg-background px-3 py-2 text-xs font-mono tracking-wider break-all">
                {setupData.secret}
              </code>
              <button
                type="button"
                onClick={copySecret}
                className={`shrink-0 flex items-center gap-1 rounded-lg border px-2.5 py-2 text-xs font-medium transition-all duration-200 btn-press ${
                  copiedSecret
                    ? "border-emerald-300 dark:border-emerald-700 text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40"
                    : "border-border/60 text-muted-foreground hover:text-foreground hover:bg-muted/50"
                }`}
                aria-label="Copy secret"
              >
                <Copy className="h-3.5 w-3.5" />
                {copiedSecret ? "Copied!" : "Copy"}
              </button>
            </div>
          </div>

          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-500/15 text-[11px] font-bold text-blue-600 dark:text-blue-400">2</span>
              <p className="text-sm font-semibold text-foreground">
                Save your recovery codes
              </p>
            </div>
            <p className="text-xs text-muted-foreground ml-8 leading-relaxed">
              Store these in a safe place. Each code can be used once to access your account if you lose your device.
            </p>
            <button
              type="button"
              onClick={() => setRecoveryVisible((v) => !v)}
              className="ml-8 text-xs font-medium text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 link-underline transition-colors"
            >
              {recoveryVisible ? "Hide recovery codes" : "Show recovery codes"}
            </button>
            {recoveryVisible && (
              <div className="grid grid-cols-2 gap-1.5 mt-2 ml-8 animate-scale-in">
                {setupData.recovery_codes.map((c) => (
                  <code
                    key={c}
                    className="rounded-lg border border-border/60 bg-muted/40 px-3 py-1.5 text-xs font-mono text-center"
                  >
                    {c}
                  </code>
                ))}
              </div>
            )}
          </div>

          <form onSubmit={activateMfa} className="space-y-4">
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-blue-500/15 text-[11px] font-bold text-blue-600 dark:text-blue-400">3</span>
              <p className="text-sm font-semibold text-foreground">
                Enter the 6-digit code to verify
              </p>
            </div>
            <Input
              type="tel"
              inputMode="numeric"
              pattern="[0-9]*"
              maxLength={6}
              placeholder="000000"
              value={activateCode}
              onChange={(e) => setActivateCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              required
              autoComplete="one-time-code"
              className={`${inputClasses} text-center tracking-[0.3em] text-base font-mono`}
            />
            <Button
              type="submit"
              disabled={loading || activateCode.length !== 6}
              className={`${primaryBtnClasses} w-full`}
            >
              {loading ? (
                <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Activating...</>
              ) : (
                "Enable Two-Factor Authentication"
              )}
            </Button>
          </form>
        </div>
      ) : !activated ? (
        /* ---- MFA not enabled, setup not started ---- */
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground leading-relaxed">
            Two-factor authentication adds an extra layer of security. After enabling, you will
            need your authenticator app every time you sign in.
          </p>
          <Button
            onClick={startSetup}
            disabled={loading}
            className={primaryBtnClasses}
          >
            {loading ? (
              <><Loader2 className="mr-2 h-4 w-4 animate-spin" />Starting setup...</>
            ) : (
              <><QrCode className="mr-2 h-4 w-4" />Enable Two-Factor Authentication</>
            )}
          </Button>
        </div>
      ) : null}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Active sessions section — visible to ALL authenticated users
// ---------------------------------------------------------------------------

function SessionsSection() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ type: "success" | "error"; message: string } | null>(
    null
  );

  async function fetchSessions() {
    try {
      const { data } = await authApi.get<Session[]>("/api/auth/sessions");
      setSessions(data);
    } catch (err: any) {
      setFeedback({ type: "error", message: err?.response?.data?.detail ?? err?.message ?? "Failed to load sessions." });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchSessions();
  }, []);

  async function revokeSession(id: string) {
    setRevoking(id);
    setFeedback(null);
    try {
      await authApi.delete(`/api/auth/sessions/${id}`);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      setFeedback({ type: "success", message: "Session revoked." });
    } catch (err: any) {
      setFeedback({ type: "error", message: err?.response?.data?.detail ?? "Failed to revoke session." });
    } finally {
      setRevoking(null);
    }
  }

  async function revokeAll() {
    setRevoking("all");
    setFeedback(null);
    try {
      await authApi.delete("/api/auth/sessions");
      setSessions((prev) => prev.filter((s) => s.is_current));
      setFeedback({ type: "success", message: "All other sessions revoked." });
    } catch (err: any) {
      setFeedback({ type: "error", message: err?.response?.data?.detail ?? "Failed to revoke sessions." });
    } finally {
      setRevoking(null);
    }
  }

  function formatDate(iso: string) {
    try {
      return new Date(iso).toLocaleString();
    } catch {
      return iso;
    }
  }

  function truncateAgent(agent: string) {
    return agent.length > 60 ? agent.slice(0, 57) + "..." : agent;
  }

  return (
    <Section id="sessions" icon={MonitorSmartphone} title="Active Sessions" description="Manage devices and sessions that are signed in to your account." staggerIndex={4}>
      {feedback && (
        <div className="mb-4">
          <Feedback type={feedback.type} message={feedback.message} />
        </div>
      )}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading sessions...
        </div>
      ) : sessions.length === 0 ? (
        <p className="text-sm text-muted-foreground py-2">No active sessions found.</p>
      ) : (
        <>
          <div className="overflow-x-auto rounded-xl border border-border/40">
            <table className="w-full text-sm premium-table">
              <thead>
                <tr className="border-b border-border/60 bg-muted/30">
                  <th className="text-left text-[10px] font-bold uppercase tracking-wider text-muted-foreground py-3 px-4">IP</th>
                  <th className="text-left text-[10px] font-bold uppercase tracking-wider text-muted-foreground py-3 px-4">
                    Browser / Device
                  </th>
                  <th className="text-left text-[10px] font-bold uppercase tracking-wider text-muted-foreground py-3 px-4">
                    Created
                  </th>
                  <th className="text-left text-[10px] font-bold uppercase tracking-wider text-muted-foreground py-3 px-4">
                    Last used
                  </th>
                  <th className="py-3 px-4" />
                </tr>
              </thead>
              <tbody>
                {sessions.map((s) => (
                  <tr
                    key={s.id}
                    className="border-b border-border/30 last:border-0 hover:bg-muted/20 transition-colors duration-150"
                  >
                    <td className="py-3 px-4 font-mono text-xs text-foreground">{s.ip_address}</td>
                    <td className="py-3 px-4 text-xs text-muted-foreground">
                      {truncateAgent(s.user_agent)}
                      {s.is_current && (
                        <span className="ml-2 inline-flex items-center rounded-full bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800/60 px-2 py-0.5 text-[10px] font-bold text-emerald-600 dark:text-emerald-400">
                          Current
                        </span>
                      )}
                    </td>
                    <td className="py-3 px-4 text-xs text-muted-foreground whitespace-nowrap tabular-nums">
                      {formatDate(s.created_at)}
                    </td>
                    <td className="py-3 px-4 text-xs text-muted-foreground whitespace-nowrap tabular-nums">
                      {formatDate(s.last_used_at)}
                    </td>
                    <td className="py-3 px-4">
                      {!s.is_current && (
                        <button
                          onClick={() => revokeSession(s.id)}
                          disabled={revoking === s.id}
                          className="flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40 transition-all duration-200 disabled:opacity-50 btn-press"
                          aria-label="Revoke this session"
                        >
                          {revoking === s.id ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <Trash2 className="h-3 w-3" />
                          )}
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {sessions.filter((s) => !s.is_current).length > 0 && (
            <div className="mt-4">
              <Button
                variant="outline"
                size="sm"
                onClick={revokeAll}
                disabled={revoking === "all"}
                className="h-9 rounded-xl text-sm font-medium text-red-600 dark:text-red-400 border-2 border-red-200 dark:border-red-800/60 hover:bg-red-50 dark:hover:bg-red-950/40 hover:border-red-300 dark:hover:border-red-700 transition-all duration-200 btn-press"
              >
                {revoking === "all" ? (
                  <>
                    <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                    Revoking...
                  </>
                ) : (
                  <>
                    <Trash2 className="mr-2 h-3 w-3" />
                    Revoke All Other Sessions
                  </>
                )}
              </Button>
            </div>
          )}
        </>
      )}
    </Section>
  );
}

// ---------------------------------------------------------------------------
// User management section (admin only)
// ---------------------------------------------------------------------------

function UserManagementSection() {
  return (
    <Section id="users" icon={Users} title="User Management" description="Manage team members and their access levels." staggerIndex={5}>
      <div className="flex items-start gap-3 rounded-xl border border-amber-200 dark:border-amber-800/60 bg-amber-50 dark:bg-amber-950/30 p-4">
        <ShieldAlert className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
        <div className="space-y-1">
          <p className="text-sm font-semibold text-amber-700 dark:text-amber-300">Admin access required</p>
          <p className="text-xs text-amber-600/80 dark:text-amber-400/70 leading-relaxed">
            Full user management (invite, edit roles, deactivate accounts) is available
            in the admin panel. Navigate to{" "}
            <a
              href="/users"
              className="underline underline-offset-2 font-medium hover:text-amber-800 dark:hover:text-amber-200 transition-colors"
            >
              Admin &rarr; Users
            </a>{" "}
            to manage team access.
          </p>
        </div>
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Page header
// ---------------------------------------------------------------------------

function PageHeader() {
  return (
    <div className="flex items-center gap-4 animate-fade-in">
      <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-blue-500/15 to-cyan-500/10 border border-blue-500/20 shadow-sm">
        <Settings className="h-5 w-5 text-blue-500 dark:text-blue-400" />
      </div>
      <div>
        <h1 className="text-xl font-bold tracking-tight text-foreground">Settings</h1>
        <p className="text-sm text-muted-foreground">Manage your account and preferences</p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function SettingsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const searchParams = useSearchParams();
  const forcePasswordChange = searchParams.get("force_password_change") === "true";
  const [activeTab, setActiveTab] = useState("profile");

  const tabs: NavTab[] = [
    { id: "profile", label: "Profile", icon: User },
    { id: "password", label: "Password", icon: KeyRound },
    { id: "mfa", label: "Two-Factor Auth", icon: ShieldCheck },
    { id: "sessions", label: "Sessions", icon: MonitorSmartphone },
    ...(isAdmin ? [{ id: "users", label: "User Management", icon: Users }] : []),
  ];

  return (
    <div className="max-w-2xl space-y-5">
      <ToastContainer />
      <PageHeader />
      <SectionNav tabs={tabs} activeTab={activeTab} onTabChange={setActiveTab} />
      <div className="space-y-5">
        <ProfileSection />
        <ChangePasswordSection forceChange={forcePasswordChange} />
        <MfaSection />
        {/* Active sessions — visible to ALL authenticated users (Fix 6) */}
        <SessionsSection />
        {isAdmin && <UserManagementSection />}
      </div>
    </div>
  );
}
