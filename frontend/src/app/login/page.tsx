"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/contexts/auth-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Shield, Loader2, Eye, EyeOff, AlertCircle, CheckCircle2,
  Activity, Brain, FileCheck, Lock,
} from "lucide-react";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { login, isAuthenticated, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.push("/");
    }
  }, [isLoading, isAuthenticated, router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setIsSubmitting(true);
    try {
      await login(email, password);
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[#0f1117]">
        <Loader2 className="h-8 w-8 animate-spin text-blue-400" />
      </div>
    );
  }

  const features = [
    {
      icon: Brain,
      title: "Automated HCC Extraction",
      desc: "Extract diagnoses from clinical notes using advanced NLP and LLM models.",
    },
    {
      icon: Activity,
      title: "Real-Time RAF Scoring",
      desc: "Instantly calculate and track Risk Adjustment Factor scores across your patient population.",
    },
    {
      icon: FileCheck,
      title: "Audit Package Generation",
      desc: "Generate compliant audit-ready PDF packages with one click.",
    },
  ];

  const demoAccounts = [
    { email: "admin@raf.health", password: "admin123", role: "Admin" },
    { email: "clinician@raf.health", password: "clinician123", role: "Clinician" },
    { email: "coder@raf.health", password: "coder123", role: "Coder" },
  ];

  return (
    <div className="min-h-screen flex">
      {/* Left panel — dark gradient with product info */}
      <div className="hidden lg:flex lg:w-[52%] flex-col justify-between p-12 relative overflow-hidden"
        style={{ background: "linear-gradient(145deg, #0f1117 0%, #0d1f3c 50%, #0f1117 100%)" }}>

        {/* Background mesh */}
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute top-0 left-1/4 w-[600px] h-[600px] rounded-full opacity-10"
            style={{ background: "radial-gradient(circle, #2563eb 0%, transparent 70%)" }} />
          <div className="absolute bottom-0 right-0 w-[400px] h-[400px] rounded-full opacity-8"
            style={{ background: "radial-gradient(circle, #0891b2 0%, transparent 70%)" }} />
        </div>

        {/* Grid pattern overlay */}
        <div className="absolute inset-0 opacity-[0.03]"
          style={{
            backgroundImage: "linear-gradient(rgba(255,255,255,0.5) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.5) 1px, transparent 1px)",
            backgroundSize: "40px 40px"
          }} />

        {/* Logo */}
        <div className="relative z-10 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-cyan-400 shadow-lg shadow-blue-500/30">
            <Shield className="h-6 w-6 text-white" />
          </div>
          <div>
            <p className="text-white font-bold text-lg tracking-tight">TMIAB-RAF</p>
            <p className="text-blue-400/70 text-[11px] font-semibold uppercase tracking-[0.2em]">Healthcare Risk Analytics</p>
          </div>
        </div>

        {/* Hero content */}
        <div className="relative z-10 space-y-8">
          <div className="space-y-4">
            <div className="inline-flex items-center gap-2 rounded-full bg-blue-500/10 border border-blue-500/20 px-4 py-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-blue-400 animate-pulse" />
              <span className="text-blue-300 text-xs font-semibold tracking-wide">Clinical Intelligence Platform</span>
            </div>
            <h1 className="text-4xl font-bold text-white leading-tight tracking-tight">
              Risk Adjustment<br />
              <span style={{ background: "linear-gradient(90deg, #60a5fa, #22d3ee)", WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
                Intelligence Platform
              </span>
            </h1>
            <p className="text-slate-400 text-base leading-relaxed max-w-md">
              Automate HCC coding, track RAF scores, and generate compliant audit packages for your entire patient population.
            </p>
          </div>

          <div className="space-y-4">
            {features.map(({ icon: Icon, title, desc }) => (
              <div key={title} className="flex items-start gap-4 group">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-blue-500/10 border border-blue-500/20 group-hover:bg-blue-500/20 transition-colors">
                  <Icon className="h-4 w-4 text-blue-400" />
                </div>
                <div>
                  <p className="text-white text-sm font-semibold">{title}</p>
                  <p className="text-slate-500 text-xs mt-0.5 leading-relaxed">{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Bottom tagline */}
        <div className="relative z-10">
          <p className="text-slate-600 text-xs">
            Trusted by healthcare risk adjustment teams &bull; HIPAA Compliant &bull; SOC 2 Ready
          </p>
        </div>
      </div>

      {/* Right panel — login form */}
      <div className="flex flex-1 flex-col items-center justify-center p-8 bg-white dark:bg-[#0f1117]">
        {/* Mobile logo */}
        <div className="lg:hidden flex items-center gap-3 mb-10">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-cyan-400 shadow-lg shadow-blue-500/25">
            <Shield className="h-5 w-5 text-white" />
          </div>
          <p className="text-foreground font-bold text-lg">TMIAB-RAF</p>
        </div>

        <div className="w-full max-w-[420px] space-y-8">
          {/* Heading */}
          <div className="space-y-1.5">
            <h2 className="text-2xl font-bold tracking-tight text-foreground">Sign in to your account</h2>
            <p className="text-sm text-muted-foreground">Enter your credentials to access the dashboard</p>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-5">
            {error && (
              <div className="flex items-center gap-2.5 rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800/60 p-3.5 text-sm text-red-700 dark:text-red-300">
                <AlertCircle className="h-4 w-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <div className="space-y-1.5">
              <label htmlFor="email" className="text-sm font-medium text-foreground">
                Email address
              </label>
              <Input
                id="email"
                type="email"
                placeholder="admin@raf.health"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="h-11 rounded-xl border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500 transition-colors"
                autoComplete="email"
              />
            </div>

            <div className="space-y-1.5">
              <label htmlFor="password" className="text-sm font-medium text-foreground">
                Password
              </label>
              <div className="relative">
                <Input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  placeholder="Enter your password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  className="h-11 pr-10 rounded-xl border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 focus:ring-2 focus:ring-blue-500/40 focus:border-blue-500 transition-colors"
                  autoComplete="current-password"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            <Button
              type="submit"
              className="w-full h-11 rounded-xl font-semibold text-sm bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-700 hover:to-blue-600 shadow-lg shadow-blue-500/25 hover:shadow-blue-500/40 transition-all"
              disabled={isSubmitting}
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Signing in...
                </>
              ) : (
                "Sign In"
              )}
            </Button>
          </form>

          {/* Demo credentials */}
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <div className="flex-1 h-px bg-border" />
              <p className="text-xs text-muted-foreground font-medium">Demo Credentials</p>
              <div className="flex-1 h-px bg-border" />
            </div>
            <div className="rounded-xl border border-border bg-muted/30 p-1 space-y-0.5">
              {demoAccounts.map((account) => (
                <button
                  key={account.email}
                  type="button"
                  onClick={() => { setEmail(account.email); setPassword(account.password); }}
                  className="flex w-full items-center justify-between rounded-lg px-3 py-2.5 text-xs hover:bg-background transition-colors group"
                >
                  <div className="flex items-center gap-2">
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                    <span className="font-medium text-foreground group-hover:text-blue-600 dark:group-hover:text-blue-400 transition-colors">{account.email}</span>
                  </div>
                  <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">
                    {account.role}
                  </span>
                </button>
              ))}
            </div>
            <p className="text-[11px] text-center text-muted-foreground/60">
              Click any row to auto-fill credentials
            </p>
          </div>

          {/* Compliance badges */}
          <div className="flex items-center justify-center gap-4 mt-4 text-xs text-muted-foreground">
            <span className="flex items-center gap-1"><Shield className="h-3 w-3" /> HIPAA</span>
            <span className="flex items-center gap-1"><Lock className="h-3 w-3" /> Encrypted</span>
            <span className="flex items-center gap-1"><FileCheck className="h-3 w-3" /> BAA Active</span>
          </div>
        </div>
      </div>
    </div>
  );
}
