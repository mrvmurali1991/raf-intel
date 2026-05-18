"use client";

import { useState, useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/contexts/auth-context";
import { authApi } from "@/contexts/auth-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Shield, Loader2, Eye, EyeOff, AlertCircle,
  Activity, FileCheck, Lock, ChevronRight,
  KeyRound, RotateCcw, HeartPulse, Stethoscope, FileText, Zap
} from "lucide-react";
import { loginSchema } from "@/lib/validators";
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from "@/components/ui/tooltip";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getApiError(err: unknown): string {
  if (err && typeof err === "object" && "response" in err) {
    const res = (err as { response?: { data?: { detail?: string; message?: string; error?: string }; status?: number } }).response;
    const detail = res?.data?.detail ?? res?.data?.message ?? res?.data?.error;
    if (detail) return String(detail);
    if (res?.status === 401) return "Invalid email or password.";
    if (res?.status === 403) return "Your account is locked. Please contact your administrator.";
    if (res?.status === 429) return "Too many login attempts. Please wait and try again.";
  }
  if (err instanceof Error) return err.message;
  return "Login failed. Please try again.";
}

// ---------------------------------------------------------------------------
// Forgot-password inline form
// ---------------------------------------------------------------------------

function ForgotPasswordForm({ onCancel }: { onCancel: () => void }) {
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      await authApi.post("/api/auth/forgot-password", { email });
      setSent(true);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (sent) {
    return (
      <div className="rounded-xl border border-teal-200 dark:border-teal-800/60 bg-teal-50 dark:bg-teal-950/40 p-4 text-sm text-teal-700 dark:text-teal-300 space-y-2">
        <p className="font-semibold">Password reset email sent.</p>
        <p className="text-teal-600 dark:text-teal-400 text-xs">
          If an account exists for <strong>{email}</strong> you will receive instructions
          within a few minutes. Check your spam folder if it does not arrive.
        </p>
        <button
          type="button"
          onClick={onCancel}
          className="text-xs font-medium text-blue-600 dark:text-blue-400 hover:underline mt-1"
        >
          Back to sign in
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-1">
        <p className="text-sm font-semibold text-foreground">Reset your password</p>
        <p className="text-xs text-muted-foreground">
          Enter your account email and we will send you a reset link.
        </p>
      </div>

      {error && (
        <div role="alert" className="flex items-center gap-2.5 rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800/60 p-3 text-sm text-red-700 dark:text-red-300">
          <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span>{error}</span>
        </div>
      )}

      <div className="space-y-1.5">
        <label htmlFor="reset-email" className="text-sm font-medium text-foreground">
          Email address
        </label>
        <Input
          id="reset-email"
          type="email"
          placeholder="you@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          className="h-11 rounded-xl border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 focus:ring-2 focus:ring-teal-500/40 focus:border-teal-500 transition-colors"
          autoComplete="email"
        />
      </div>

      <div className="flex items-center gap-3">
        <Button
          type="submit"
          className="flex-1 h-10 rounded-xl font-semibold text-sm bg-gradient-to-r from-teal-600 to-teal-500 hover:from-teal-700 hover:to-teal-600 shadow-md shadow-teal-500/20 text-white transition-all"
          disabled={submitting}
        >
          {submitting ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Sending...
            </>
          ) : (
            "Send reset link"
          )}
        </Button>
        <Button
          type="button"
          variant="ghost"
          className="h-10 rounded-xl text-sm text-muted-foreground"
          onClick={onCancel}
        >
          Cancel
        </Button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Reset-password form (shown when URL contains ?reset_token=...)
// ---------------------------------------------------------------------------

function ResetPasswordForm({ token }: { token: string }) {
  const router = useRouter();
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (newPassword !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      await authApi.post("/api/auth/reset-password", {
        token,
        new_password: newPassword,
      });
      setSuccess(true);
      // Redirect to clean login after a short delay
      setTimeout(() => router.replace("/login"), 3000);
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (success) {
    return (
      <div className="rounded-xl border border-teal-200 dark:border-teal-800/60 bg-teal-50 dark:bg-teal-950/40 p-5 text-sm text-teal-700 dark:text-teal-300 space-y-2">
        <p className="font-semibold text-base">Password reset successfully.</p>
        <p className="text-teal-600 dark:text-teal-400 text-xs">
          Your password has been updated. Redirecting you to sign in…
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5" noValidate>
      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-50 border border-teal-100 dark:bg-teal-500/10 dark:border-teal-500/20" aria-hidden="true">
            <Lock className="h-4 w-4 text-teal-600 dark:text-teal-400" />
          </div>
          <h2 className="text-base font-semibold text-foreground">Set a new password</h2>
        </div>
        <p className="text-xs text-muted-foreground">
          Choose a strong password with at least 12 characters.
        </p>
      </div>

      {error && (
        <div role="alert" className="flex items-center gap-2.5 rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800/60 p-3 text-sm text-red-700 dark:text-red-300">
          <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span>{error}</span>
        </div>
      )}

      <div className="space-y-1.5">
        <label htmlFor="new-password" className="text-sm font-medium text-foreground">
          New password
        </label>
        <div className="relative">
          <Input
            id="new-password"
            type={showNew ? "text" : "password"}
            placeholder="••••••••••••"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            required
            autoComplete="new-password"
            className="h-11 pr-10 rounded-xl border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 focus:ring-2 focus:ring-teal-500/40 focus:border-teal-500 transition-colors"
          />
          <button
            type="button"
            onClick={() => setShowNew((v) => !v)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
            aria-label={showNew ? "Hide password" : "Show password"}
          >
            {showNew ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
      </div>

      <div className="space-y-1.5">
        <label htmlFor="confirm-password" className="text-sm font-medium text-foreground">
          Confirm new password
        </label>
        <div className="relative">
          <Input
            id="confirm-password"
            type={showConfirm ? "text" : "password"}
            placeholder="••••••••••••"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
            autoComplete="new-password"
            className="h-11 pr-10 rounded-xl border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 focus:ring-2 focus:ring-teal-500/40 focus:border-teal-500 transition-colors"
          />
          <button
            type="button"
            onClick={() => setShowConfirm((v) => !v)}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
            aria-label={showConfirm ? "Hide password" : "Show password"}
          >
            {showConfirm ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
      </div>

      <Button
        type="submit"
        disabled={submitting || newPassword.length === 0}
        className="w-full h-11 rounded-xl font-semibold text-sm bg-gradient-to-r from-teal-600 to-teal-500 hover:from-teal-700 hover:to-teal-600 shadow-md shadow-teal-500/20 text-white transition-all"
      >
        {submitting ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Resetting…
          </>
        ) : (
          "Reset password"
        )}
      </Button>
    </form>
  );
}

// ---------------------------------------------------------------------------
// MFA verification form
// ---------------------------------------------------------------------------

interface MfaFormProps {
  mfaToken: string;
  onSuccess: () => void;
  onCancel: () => void;
}

function MfaForm({ mfaToken, onSuccess, onCancel }: MfaFormProps) {
  const { completeMfaVerify } = useAuth();
  const [code, setCode] = useState("");
  const [isRecovery, setIsRecovery] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, [isRecovery]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!isRecovery && (code.length !== 6 || !/^\d{6}$/.test(code))) {
      setError("Enter the 6-digit code from your authenticator app.");
      return;
    }
    setSubmitting(true);
    try {
      await completeMfaVerify(mfaToken, code, isRecovery);
      onSuccess();
    } catch (err) {
      setError(getApiError(err));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5" noValidate>
      <div className="space-y-1.5">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-50 border border-teal-100 dark:bg-teal-500/10 dark:border-teal-500/20" aria-hidden="true">
            <KeyRound className="h-4 w-4 text-teal-600 dark:text-teal-400" />
          </div>
          <h2 className="text-base font-semibold text-foreground">Two-factor verification</h2>
        </div>
        <p className="text-xs text-muted-foreground">
          {isRecovery
            ? "Enter one of your saved recovery codes."
            : "Open your authenticator app and enter the 6-digit code."}
        </p>
      </div>

      {error && (
        <div role="alert" className="flex items-center gap-2.5 rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800/60 p-3 text-sm text-red-700 dark:text-red-300">
          <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span>{error}</span>
        </div>
      )}

      <div className="space-y-1.5">
        <label htmlFor="mfa-code" className="text-sm font-medium text-foreground">
          {isRecovery ? "Recovery code" : "Authentication code"}
        </label>
        <Input
          ref={inputRef}
          id="mfa-code"
          type={isRecovery ? "text" : "tel"}
          inputMode={isRecovery ? "text" : "numeric"}
          pattern={isRecovery ? undefined : "[0-9]*"}
          maxLength={isRecovery ? 32 : 6}
          placeholder={isRecovery ? "xxxxxxxx-xxxx-..." : "000000"}
          value={code}
          onChange={(e) => {
            const val = isRecovery
              ? e.target.value
              : e.target.value.replace(/\D/g, "").slice(0, 6);
            setCode(val);
          }}
          required
          autoComplete={isRecovery ? "off" : "one-time-code"}
          className="h-11 rounded-xl border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 focus:ring-2 focus:ring-teal-500/40 focus:border-teal-500 transition-colors text-center tracking-[0.3em] text-lg font-mono"
        />
      </div>

      <Button
        type="submit"
        disabled={submitting || code.length === 0}
        className="w-full h-11 rounded-xl font-semibold text-sm bg-gradient-to-r from-teal-600 to-teal-500 hover:from-teal-700 hover:to-teal-600 shadow-md shadow-teal-500/20 text-white transition-all"
      >
        {submitting ? (
          <>
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            Verifying...
          </>
        ) : (
          <>
            Verify
            <ChevronRight className="ml-1.5 h-4 w-4 opacity-60" />
          </>
        )}
      </Button>

      <div className="flex flex-col items-center gap-2">
        <button
          type="button"
          onClick={() => {
            setIsRecovery((v) => !v);
            setCode("");
            setError("");
          }}
          className="flex items-center gap-1.5 text-xs text-teal-600 dark:text-teal-400 hover:underline font-medium"
        >
          <RotateCcw className="h-3 w-3" />
          {isRecovery ? "Use authenticator code instead" : "Use a recovery code"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          Back to sign in
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Feature list (left panel)
// ---------------------------------------------------------------------------

const features = [
  {
    icon: Stethoscope,
    title: "Automated HCC Extraction",
    desc: "Extract diagnoses from clinical notes using advanced NLP and medical LLM models.",
  },
  {
    icon: Activity,
    title: "Real-Time RAF Scoring",
    desc: "Instantly calculate and track Risk Adjustment Factor scores across your patient population.",
  },
  {
    icon: FileText,
    title: "Audit Package Generation",
    desc: "Generate compliant, HIPAA-ready audit packages with a single click.",
  },
];

// ---------------------------------------------------------------------------
// Main login page
// ---------------------------------------------------------------------------

type LoginStep = "credentials" | "mfa";

interface LoginFieldErrors {
  email?: string;
  password?: string;
}

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<LoginFieldErrors>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showForgot, setShowForgot] = useState(false);
  const [mounted, setMounted] = useState(false);

  // Validate a single field against the shared loginSchema. Stores per-field
  // error text in `fieldErrors` so we can render it directly under the input
  // instead of dumping into the top-level banner (which is now reserved for
  // submit-time server errors).
  function validateField(field: "email" | "password", value: string) {
    const fieldSchema = loginSchema.shape[field];
    const result = fieldSchema.safeParse(value);
    setFieldErrors((prev) => ({
      ...prev,
      [field]: result.success ? undefined : result.error.issues[0]?.message,
    }));
  }

  // MFA state
  const [step, setStep] = useState<LoginStep>("credentials");
  const [pendingMfaToken, setPendingMfaToken] = useState<string>("");

  // Password reset token from URL query param
  const searchParams = useSearchParams();
  const resetToken = searchParams.get("reset_token");

  const { login, isAuthenticated, isLoading, user } = useAuth();
  const router = useRouter();

  /** Resolve the post-login destination based on role, with `next` taking precedence. */
  function resolveDestination(role?: string): string {
    const dest: Record<string, string> = {
      provider: "/md/today",
      md: "/md/today",
      coder: "/review-queue",
      admin: "/",
      manager: "/",
    };
    return searchParams.get("next") ?? dest[role ?? ""] ?? "/";
  }

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.push(resolveDestination(user?.role));
    }
  }, [isLoading, isAuthenticated, router]);

  useEffect(() => {
    setMounted(true);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    const parsed = loginSchema.safeParse({ email, password });
    if (!parsed.success) {
      // Surface every field error inline (not in the top banner) so the user
      // can see exactly which input is wrong.
      const nextFieldErrors: LoginFieldErrors = {};
      for (const issue of parsed.error.issues) {
        const key = issue.path[0] as keyof LoginFieldErrors | undefined;
        if (key && !nextFieldErrors[key]) nextFieldErrors[key] = issue.message;
      }
      setFieldErrors(nextFieldErrors);
      return;
    }
    // Cleared on a successful client-side validation.
    setFieldErrors({});

    setIsSubmitting(true);
    try {
      const result = await login(parsed.data.email, parsed.data.password);
      if (result.mfa_required && result.mfa_token) {
        setPendingMfaToken(result.mfa_token);
        setStep("mfa");
      } else {
        // Use window.location for reliable navigation after auth state change
        window.location.href = resolveDestination(result.user?.role);
      }
    } catch (err) {
      // Login error handled by UI state below
      setError(getApiError(err));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleMfaSuccess = () => {
    // user state is populated by completeMfaVerify before this callback fires
    router.push(resolveDestination(user?.role));
  };

  const handleMfaCancel = () => {
    setStep("credentials");
    setPendingMfaToken("");
    setPassword("");
    setError("");
  };

  if (isLoading) {
    return (
      <div
        className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-950"
        aria-live="assertive"
        role="status"
        aria-label="Signing in"
      >
        <Loader2 className="h-8 w-8 animate-spin text-teal-600" aria-hidden="true" />
        <span className="sr-only">Signing in, please wait…</span>
      </div>
    );
  }

  return (
    <TooltipProvider delay={200}>
    <div className="min-h-screen flex">
      {/* Left panel - Clinical Aesthetic with Aurora */}
      <div
        className="hidden lg:flex lg:w-[52%] flex-col justify-between p-12 relative overflow-hidden aurora-bg"
        style={{
          borderRight: "1px solid rgba(20, 184, 166, 0.12)",
        }}
      >
        {/* Glassmorphism gradient overlay for legibility */}
        <div className="absolute inset-0 pointer-events-none bg-white/50 dark:bg-slate-950/60 backdrop-blur-[1px]" />

        {/* Aurora orb accents — softly animated */}
        <div className="absolute inset-0 pointer-events-none overflow-hidden">
          <div
            className="absolute top-[-15%] left-[-10%] w-[550px] h-[550px] rounded-full opacity-35 dark:opacity-20 blur-[90px] login-orb-1"
            style={{ background: "radial-gradient(circle, #2dd4bf 0%, transparent 65%)" }}
          />
          <div
            className="absolute bottom-[-15%] right-[-12%] w-[650px] h-[650px] rounded-full opacity-25 dark:opacity-15 blur-[110px] login-orb-2"
            style={{ background: "radial-gradient(circle, #3b82f6 0%, transparent 65%)" }}
          />
          <div
            className="absolute top-[40%] right-[15%] w-[300px] h-[300px] rounded-full opacity-15 dark:opacity-10 blur-[70px] login-orb-3"
            style={{ background: "radial-gradient(circle, #818cf8 0%, transparent 65%)" }}
          />
        </div>

        {/* Clean minimal grid overlay */}
        <div
          className="absolute inset-0 opacity-[0.2] dark:opacity-[0.05]"
          style={{
            backgroundImage:
              "linear-gradient(#cbd5e1 1px, transparent 1px), linear-gradient(90deg, #cbd5e1 1px, transparent 1px)",
            backgroundSize: "64px 64px",
          }}
        />

        {/* Logo */}
        <div className="relative z-10 flex items-center gap-3">
          <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-gradient-to-br from-teal-500 to-blue-500 shadow-lg shadow-teal-500/20 text-white">
            <HeartPulse className="h-6 w-6" aria-hidden="true" />
          </div>
          <div>
            <p className="text-slate-900 dark:text-white font-bold text-xl tracking-tight">RAF Intelligence</p>
            <p className="text-teal-600 dark:text-teal-400 text-[11px] font-bold uppercase tracking-[0.2em]">
              Clinical Intelligence
            </p>
          </div>
        </div>

        {/* Hero content */}
        <div className="relative z-10 space-y-10">
          <div className="space-y-4">
            <Tooltip>
              <TooltipTrigger>
                <div className="inline-flex cursor-help items-center gap-2 rounded-full bg-white/80 dark:bg-slate-800/80 border border-teal-100 dark:border-teal-900 px-4 py-1.5 shadow-sm backdrop-blur-sm transition-colors hover:bg-white dark:hover:bg-slate-800">
                  <span className="h-1.5 w-1.5 rounded-full bg-teal-500 animate-pulse" />
                  <span className="text-slate-700 dark:text-slate-300 text-xs font-semibold tracking-wide">
                    Trusted by Healthcare Payers & Providers
                  </span>
                </div>
              </TooltipTrigger>
              <TooltipContent>Trusted by 50+ leading healthcare organizations</TooltipContent>
            </Tooltip>
            <h1 className="text-4xl font-bold text-slate-900 dark:text-white leading-[1.15] tracking-tight">
              Precision Risk Adjustment
              <br />
              <span className="text-teal-600 dark:text-teal-400">
                At Enterprise Scale
              </span>
            </h1>
            <p className="text-slate-600 dark:text-slate-400 text-[15px] leading-relaxed max-w-[440px]">
              Securely automate HCC coding, visualize RAF score impacts, and generate fully compliant audit packages directly from patient charts.
            </p>
          </div>

          <div className="space-y-6">
            {features.map(({ icon: Icon, title, desc }) => (
              <div key={title} className="flex items-start gap-4 group bg-white/50 dark:bg-slate-900/50 p-4 rounded-2xl border border-slate-200/50 dark:border-slate-800/50 shadow-sm backdrop-blur-sm transition-all hover:bg-white dark:hover:bg-slate-900 hover:shadow-md hover:border-teal-100 dark:hover:border-teal-900">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-teal-50 dark:bg-teal-500/10 text-teal-600 dark:text-teal-400 transition-transform group-hover:scale-110">
                  <Icon className="h-5 w-5" aria-hidden="true" />
                </div>
                <div>
                  <p className="text-slate-900 dark:text-slate-100 text-[15px] font-semibold">{title}</p>
                  <p className="text-slate-600 dark:text-slate-500 text-[13px] mt-1 leading-relaxed">{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Bottom tagline */}
        <div className="relative z-10 flex items-center gap-6 text-[13px] font-medium text-slate-500 dark:text-slate-400 border-t border-slate-200 dark:border-slate-800 pt-6 pr-6">
          <Tooltip>
            <TooltipTrigger>
              <span className="flex cursor-help items-center gap-1.5 hover:text-slate-700 dark:hover:text-slate-300 transition-colors"><Shield className="h-4 w-4 text-teal-600 dark:text-teal-500" /> HIPAA Compliant</span>
            </TooltipTrigger>
            <TooltipContent>Data handling adheres to HIPAA standards</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger>
              <span className="flex cursor-help items-center gap-1.5 hover:text-slate-700 dark:hover:text-slate-300 transition-colors"><Lock className="h-4 w-4 text-teal-600 dark:text-teal-500" /> SOC 2 Certified</span>
            </TooltipTrigger>
            <TooltipContent>Type II SOC 2 Certified for Security</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger>
              <span className="flex cursor-help items-center gap-1.5 hover:text-slate-700 dark:hover:text-slate-300 transition-colors"><FileCheck className="h-4 w-4 text-teal-600 dark:text-teal-500" /> BAA Ready</span>
            </TooltipTrigger>
            <TooltipContent>Business Associate Agreements available</TooltipContent>
          </Tooltip>
        </div>
      </div>

      {/* Right panel — aurora background */}
      <div className="flex flex-1 flex-col items-center justify-center p-4 sm:p-8 aurora-bg relative overflow-hidden">
        {/* Animated floating gradient orbs */}
        <div className="absolute inset-0 pointer-events-none overflow-hidden">
          <div className="login-orb login-orb-1 absolute w-[480px] h-[480px] rounded-full opacity-25 dark:opacity-[0.12] blur-[100px]"
            style={{ background: "radial-gradient(circle, #2dd4bf 0%, transparent 65%)" }} />
          <div className="login-orb login-orb-2 absolute w-[400px] h-[400px] rounded-full opacity-20 dark:opacity-10 blur-[90px]"
            style={{ background: "radial-gradient(circle, #818cf8 0%, transparent 65%)" }} />
          <div className="login-orb login-orb-3 absolute w-[350px] h-[350px] rounded-full opacity-[0.18] dark:opacity-[0.08] blur-[80px]"
            style={{ background: "radial-gradient(circle, #3b82f6 0%, transparent 65%)" }} />
        </div>

        {/* Heartbeat line SVG decorative element */}
        <svg className="absolute bottom-0 left-0 w-full h-24 opacity-[0.06] dark:opacity-[0.04] pointer-events-none" viewBox="0 0 1200 100" preserveAspectRatio="none" aria-hidden="true">
          <path
            d="M0,50 L200,50 L230,50 L250,20 L270,80 L290,10 L310,90 L330,50 L360,50 L600,50 L630,50 L650,25 L670,75 L690,15 L710,85 L730,50 L760,50 L1200,50"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            className="text-teal-600 dark:text-teal-400 login-heartbeat"
          />
        </svg>

        {/* Mobile logo */}
        <div className="lg:hidden flex flex-col items-center gap-3 mb-10 text-center relative z-10">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-teal-500 via-teal-400 to-blue-500 shadow-lg shadow-teal-500/30 text-white ring-4 ring-teal-500/10">
            <HeartPulse className="h-7 w-7" aria-hidden="true" />
          </div>
          <div>
             <p className="text-slate-900 dark:text-white font-bold text-xl tracking-tight">RAF Intelligence</p>
             <p className="text-teal-600 dark:text-teal-400 text-[11px] font-bold uppercase tracking-[0.2em]">
               Clinical Intelligence
             </p>
          </div>
        </div>

        <div
          className={`w-full max-w-[460px] relative z-10 transition-all duration-700 ease-out ${
            mounted ? "opacity-100 translate-y-0" : "opacity-0 translate-y-6"
          }`}
        >
          <div className="space-y-8 glass-frosted shadow-2xl shadow-slate-200/40 dark:shadow-black/40 p-9 sm:p-11 rounded-[2rem]">
            {/* Brand area inside card */}
            <div className="flex flex-col items-center lg:items-start gap-4">
              <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-teal-500 via-teal-400 to-blue-500 shadow-lg shadow-teal-500/25 text-white ring-4 ring-teal-500/10 lg:hidden">
                <HeartPulse className="h-7 w-7" aria-hidden="true" />
              </div>
            </div>

          {resetToken ? (
            <ResetPasswordForm token={resetToken} />
          ) : step === "mfa" ? (
            <MfaForm
              mfaToken={pendingMfaToken}
              onSuccess={handleMfaSuccess}
              onCancel={handleMfaCancel}
            />
          ) : showForgot ? (
            <ForgotPasswordForm onCancel={() => setShowForgot(false)} />
          ) : (
            <>
              <div className="space-y-3 text-center lg:text-left">
                <h2 className="text-3xl font-bold tracking-tight text-slate-900 dark:text-white">
                  Welcome Back
                </h2>
                <p className="text-[15px] text-slate-500 dark:text-slate-400 leading-relaxed">
                  Sign in to access the clinical intelligence dashboard
                </p>
              </div>

              {/* Form */}
              <form onSubmit={handleSubmit} className="space-y-6" noValidate>
                {error && (
                  <div role="alert" className="flex items-center gap-2.5 rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800/60 p-3.5 text-sm text-red-700 dark:text-red-300">
                    <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
                    <span>{error}</span>
                  </div>
                )}

                <div className="space-y-2">
                  <label htmlFor="email" className="text-sm font-semibold text-slate-700 dark:text-slate-300">
                    Professional Email
                  </label>
                  <Input
                    id="email"
                    type="email"
                    placeholder="dr.smith@hospital.org"
                    value={email}
                    onChange={(e) => {
                      setEmail(e.target.value);
                      // Clear inline error as the user fixes it; re-validate on blur.
                      if (fieldErrors.email) {
                        setFieldErrors((prev) => ({ ...prev, email: undefined }));
                      }
                    }}
                    onBlur={(e) => validateField("email", e.target.value)}
                    required
                    aria-invalid={!!fieldErrors.email}
                    aria-describedby={fieldErrors.email ? "email-error" : undefined}
                    className="h-12 rounded-xl border-slate-200 dark:border-slate-800 bg-white/60 dark:bg-slate-800/60 focus:bg-white dark:focus:bg-slate-900 login-input-focus transition-all duration-300 text-base"
                    autoComplete="email"
                  />
                  {fieldErrors.email && (
                    <p
                      id="email-error"
                      role="alert"
                      className="text-xs text-red-600 dark:text-red-400 mt-1"
                    >
                      {fieldErrors.email}
                    </p>
                  )}
                </div>

                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <label htmlFor="password" className="text-sm font-semibold text-slate-700 dark:text-slate-300">
                      Password
                    </label>
                    <button
                      type="button"
                      onClick={() => setShowForgot(true)}
                      className="text-sm text-teal-600 dark:text-teal-400 hover:text-teal-700 dark:hover:text-teal-300 font-medium transition-colors"
                    >
                      Forgot password?
                    </button>
                  </div>
                  <div className="relative">
                    <Input
                      id="password"
                      type={showPassword ? "text" : "password"}
                      placeholder="••••••••••••"
                      value={password}
                      onChange={(e) => {
                        setPassword(e.target.value);
                        if (fieldErrors.password) {
                          setFieldErrors((prev) => ({ ...prev, password: undefined }));
                        }
                      }}
                      onBlur={(e) => validateField("password", e.target.value)}
                      required
                      aria-invalid={!!fieldErrors.password}
                      aria-describedby={fieldErrors.password ? "password-error" : undefined}
                      className="h-12 pr-10 rounded-xl border-slate-200 dark:border-slate-800 bg-white/60 dark:bg-slate-800/60 focus:bg-white dark:focus:bg-slate-900 login-input-focus transition-all duration-300 text-base"
                      autoComplete="current-password"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
                      aria-label={showPassword ? "Hide password" : "Show password"}
                    >
                      {showPassword ? (
                        <EyeOff className="h-4 w-4" />
                      ) : (
                        <Eye className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                  {fieldErrors.password && (
                    <p
                      id="password-error"
                      role="alert"
                      className="text-xs text-red-600 dark:text-red-400 mt-1"
                    >
                      {fieldErrors.password}
                    </p>
                  )}
                </div>

                <Button
                  type="submit"
                  className="w-full h-12 mt-2 rounded-xl font-semibold text-base bg-teal-700 hover:bg-teal-800 text-white shadow-md shadow-teal-700/20 hover:shadow-lg hover:shadow-teal-700/30 hover:-translate-y-0.5 active:translate-y-0 active:scale-95 transition-all duration-200 disabled:opacity-70 disabled:hover:translate-y-0 disabled:hover:scale-100"
                  disabled={isSubmitting}
                >
                  {isSubmitting ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Authenticating...
                    </>
                  ) : (
                    <>
                      Secure Sign In
                      <ChevronRight className="ml-1.5 h-4 w-4 opacity-70" />
                    </>
                  )}
                </Button>
              </form>

              {/* Demo login */}
              <div className="relative my-3">
                <div className="absolute inset-0 flex items-center">
                  <div className="w-full border-t border-slate-200 dark:border-slate-700" />
                </div>
                <div className="relative flex justify-center text-xs">
                  <span className="bg-white dark:bg-slate-900 px-3 text-slate-600 dark:text-slate-400">or</span>
                </div>
              </div>
              <button
                type="button"
                aria-describedby="demo-hint"
                onClick={() => {
                  setEmail("admin@raf.health");
                  setPassword("Admin@123");
                  setError("");
                  setFieldErrors({});
                }}
                className="w-full h-11 rounded-xl font-semibold text-sm border-2 border-dashed border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-800/50 text-slate-600 dark:text-slate-300 hover:border-teal-400 hover:text-teal-600 dark:hover:border-teal-500 dark:hover:text-teal-400 hover:bg-teal-50 dark:hover:bg-teal-950/30 transition-all duration-200 flex items-center justify-center gap-2"
              >
                <Zap className="h-4 w-4" />
                Demo Login — Fill Credentials
              </button>
              <p id="demo-hint" className="text-[11px] text-center text-slate-600 dark:text-slate-400 mt-1.5">
                Fills demo credentials — click &quot;Secure Sign In&quot; to continue
              </p>
            </>
          )}
          </div>
        </div>
      </div>
    </div>
    </TooltipProvider>
  );
}
