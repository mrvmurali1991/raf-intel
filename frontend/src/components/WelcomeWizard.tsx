"use client";

/**
 * WelcomeWizard — Enterprise-grade first-time onboarding.
 *
 * Full-screen guided setup that walks the user through:
 *   Step 1: Welcome + role selection
 *   Step 2: Connect EMR (vendor selection → connection form → test) OR Demo mode
 *   Step 3: Data preview after connection
 *   Step 4: Ready — quick-start links
 *
 * Triggered automatically when localStorage `raf_onboarding_complete` is absent.
 * Can be re-triggered from Settings.
 */

import { useEffect, useState, useRef, useCallback, CSSProperties } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import {
  Sparkles,
  Database,
  Users,
  CheckCircle2,
  ArrowRight,
  ArrowLeft,
  X,
  Stethoscope,
  Shield,
  BarChart3,
  FileText,
  Heart,
  Loader2,
  Zap,
  Globe,
  Lock,
  Check,
  AlertCircle,
  Play,
} from "lucide-react";
import api from "@/lib/api";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const ONBOARDING_KEY = "raf_onboarding_complete";
export const GETTING_STARTED_KEY = "raf_getting_started";

export interface GettingStartedState {
  connect_emr: boolean;
  upload_document: boolean;
  review_suspects: boolean;
  configure_worklists: boolean;
}

export const GETTING_STARTED_DEFAULT: GettingStartedState = {
  connect_emr: false,
  upload_document: false,
  review_suspects: false,
  configure_worklists: false,
};

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function getVendorPresets() {
  const { data } = await api.get("/api/emr/vendors");
  const list = Array.isArray(data) ? data : (data?.vendors ?? []);
  return list.map((v: any) => ({
    ...v,
    name: v.name || v.display_name || v.vendor,
    description: v.description || v.notes || "",
  }));
}

async function createEmrConnection(body: any) {
  const { data } = await api.post("/api/emr/connections", body);
  return data;
}

async function testEmrConnection(id: string) {
  const { data } = await api.post(`/api/emr/connections/${id}/test`);
  return data;
}

async function connectDemoEmr() {
  const { data } = await api.post("/api/emr/demo-connect");
  return data;
}

async function getEmrStatus() {
  const { data } = await api.get("/api/emr/status");
  return data;
}

async function getDashboardStats() {
  const { data } = await api.get("/api/dashboard/stats");
  return data;
}

// ---------------------------------------------------------------------------
// Design tokens
// ---------------------------------------------------------------------------
const BG = "#FFFFFF";
const BG_SUBTLE = "#F8FAFC";
const BG_ACCENT = "#F0F9FF";
const BORDER = "#E2E8F0";
const TEXT = "#0F172A";
const TEXT_SEC = "#64748B";
const TEXT_MUTED = "#94A3B8";
const PRIMARY = "#2563EB";
const PRIMARY_LIGHT = "#DBEAFE";
const SUCCESS = "#10B981";
const SUCCESS_LIGHT = "#D1FAE5";
const WARNING = "#F59E0B";
const WARNING_LIGHT = "#FEF3C7";
const DANGER = "#EF4444";

// ---------------------------------------------------------------------------
// Vendor icon/color map
// ---------------------------------------------------------------------------
const VENDOR_ICONS: Record<string, { icon: string; color: string; bg: string }> = {
  openemr:        { icon: "🏥", color: "#059669", bg: "#D1FAE5" },
  epic:           { icon: "🔷", color: "#2563EB", bg: "#DBEAFE" },
  cerner:         { icon: "🔶", color: "#D97706", bg: "#FEF3C7" },
  athenahealth:   { icon: "💜", color: "#7C3AED", bg: "#EDE9FE" },
  eclinicalworks: { icon: "🟢", color: "#059669", bg: "#D1FAE5" },
  nextgen:        { icon: "🔵", color: "#2563EB", bg: "#DBEAFE" },
  allscripts:     { icon: "🟠", color: "#EA580C", bg: "#FFEDD5" },
};

// ---------------------------------------------------------------------------
// Roles
// ---------------------------------------------------------------------------
const ROLES = [
  { id: "admin", label: "Administrator", desc: "Full system access & configuration", icon: Shield, color: "#2563EB" },
  { id: "coder", label: "HCC Coder", desc: "Review & validate coding opportunities", icon: FileText, color: "#7C3AED" },
  { id: "provider", label: "Provider / Clinician", desc: "Patient care & documentation", icon: Heart, color: "#059669" },
  { id: "analyst", label: "Data Analyst", desc: "Reports, dashboards & population insights", icon: BarChart3, color: "#D97706" },
];

// ---------------------------------------------------------------------------
// Shared styles
// ---------------------------------------------------------------------------
const btnPrimary: CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 8,
  padding: "12px 28px", border: "none", borderRadius: 10,
  background: PRIMARY, color: "#FFF",
  fontSize: 15, fontWeight: 600, cursor: "pointer",
  transition: "all 150ms",
};
const btnSecondary: CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 8,
  padding: "12px 28px", border: `1px solid ${BORDER}`, borderRadius: 10,
  background: BG, color: TEXT,
  fontSize: 15, fontWeight: 600, cursor: "pointer",
  transition: "all 150ms",
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface WelcomeWizardProps {
  forceOpen?: boolean;
  onClose?: () => void;
}

export function WelcomeWizard({ forceOpen, onClose }: WelcomeWizardProps) {
  const router = useRouter();
  const qc = useQueryClient();
  const [visible, setVisible] = useState(() => {
    if (typeof window === "undefined") return false;
    return !localStorage.getItem(ONBOARDING_KEY) || !!forceOpen;
  });
  const [step, setStep] = useState(0);

  // Step 1 state
  const [selectedRole, setSelectedRole] = useState("admin");

  // Step 2 state
  const [vendors, setVendors] = useState<any[]>([]);
  const [selectedVendor, setSelectedVendor] = useState<string | null>(null);
  const [connectionMode, setConnectionMode] = useState<"vendor" | "form" | "testing" | "success" | "demo">("vendor");
  const [formData, setFormData] = useState({
    display_name: "", fhir_base_url: "", client_id: "", client_secret: "", token_url: "", auth_type: "oauth2",
  });
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Step 3 state
  const [previewData, setPreviewData] = useState<any>(null);

  // Handle forceOpen
  const [prevForce, setPrevForce] = useState(forceOpen);
  if (forceOpen && !prevForce) { setPrevForce(forceOpen); setVisible(true); setStep(0); }
  if (forceOpen !== prevForce) setPrevForce(forceOpen);

  // Re-trigger event
  useEffect(() => {
    const h = () => { setStep(0); setVisible(true); };
    window.addEventListener("open-welcome-wizard", h);
    return () => window.removeEventListener("open-welcome-wizard", h);
  }, []);

  // Load vendors when entering step 2
  useEffect(() => {
    if (step === 2 && vendors.length === 0) {
      getVendorPresets().then(setVendors).catch(() => {});
    }
  }, [step]);

  // Load preview data when entering step 3
  useEffect(() => {
    if (step === 3 && !previewData) {
      getDashboardStats().then(setPreviewData).catch(() => setPreviewData({ total_patients: 0 }));
    }
  }, [step]);

  function complete() {
    localStorage.setItem(ONBOARDING_KEY, "true");
    // Initialize getting started checklist if not already present
    if (!localStorage.getItem(GETTING_STARTED_KEY)) {
      localStorage.setItem(GETTING_STARTED_KEY, JSON.stringify(GETTING_STARTED_DEFAULT));
    }
    setVisible(false);
    qc.invalidateQueries();
    onClose?.();
  }

  function skip() { complete(); }

  async function handleCreateConnection() {
    setLoading(true);
    setError("");
    try {
      const vendor = vendors.find((v: any) => v.vendor === selectedVendor || v.name === selectedVendor);
      const res = await createEmrConnection({
        display_name: formData.display_name || `${vendor?.name || selectedVendor} Connection`,
        vendor: selectedVendor,
        connection_type: "fhir_r4",
        fhir_base_url: formData.fhir_base_url,
        fhir_auth_type: formData.auth_type,
        fhir_client_id: formData.client_id,
        fhir_client_secret: formData.client_secret,
        fhir_token_url: formData.token_url,
        is_active: 1,
      });
      setConnectionId(res.id?.toString());
      setConnectionMode("testing");
      // Auto-test
      const test = await testEmrConnection(res.id?.toString());
      setTestResult(test);
      setConnectionMode(test.success ? "success" : "testing");
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || "Connection failed");
    } finally {
      setLoading(false);
    }
  }

  async function handleDemoConnect() {
    setLoading(true);
    setError("");
    try {
      const res = await connectDemoEmr();
      if (res.success) {
        setConnectionMode("success");
        qc.invalidateQueries();
      } else {
        setError(res.message || "Could not connect demo");
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Demo connection failed");
    } finally {
      setLoading(false);
    }
  }

  // Focus trap
  const wizardRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!visible) return;
    const el = wizardRef.current;
    if (!el) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== "Tab") return;
      const focusable = el.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey) {
        if (document.activeElement === first) { e.preventDefault(); last.focus(); }
      } else {
        if (document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    // Focus first focusable element
    const firstFocusable = el.querySelector<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    );
    firstFocusable?.focus();

    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [visible, step]);

  if (!visible) return null;

  const totalSteps = 4;

  return (
    <div
      ref={wizardRef}
      style={{
        position: "fixed", inset: 0, zIndex: 9998,
        display: "flex", alignItems: "center", justifyContent: "center",
        background: "linear-gradient(135deg, #0F172A 0%, #1E293B 50%, #0F172A 100%)",
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      }}
      role="dialog" aria-modal="true" aria-label={`Setup wizard — step ${step + 1} of ${totalSteps}`}
    >
      {/* Background pattern */}
      <div style={{ position: "absolute", inset: 0, opacity: 0.03, backgroundImage: "radial-gradient(circle at 25% 25%, #3B82F6 1px, transparent 1px), radial-gradient(circle at 75% 75%, #3B82F6 1px, transparent 1px)", backgroundSize: "50px 50px" }} />

      <div style={{ position: "relative", width: "100%", maxWidth: 800, margin: "0 24px" }}>
        {/* Progress bar */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24, padding: "0 4px" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 32, height: 32, borderRadius: 8, background: "linear-gradient(135deg, #3B82F6, #2563EB)", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Zap size={16} color="#FFF" />
            </div>
            <span style={{ fontSize: 14, fontWeight: 600, color: "#94A3B8" }}>RAF Intelligence Setup</span>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {[1, 2, 3, 4].map((s) => (
              <div key={s} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <div style={{
                  width: 28, height: 28, borderRadius: "50%",
                  background: step >= s ? "linear-gradient(135deg, #3B82F6, #2563EB)" : "rgba(255,255,255,0.08)",
                  border: step >= s ? "none" : "1px solid rgba(255,255,255,0.15)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 12, fontWeight: 700, color: step >= s ? "#FFF" : "#64748B",
                  transition: "all 300ms",
                }}>
                  {step > s ? <Check size={14} /> : s}
                </div>
                {s < 4 && <div style={{ width: 32, height: 2, background: step > s ? "#3B82F6" : "rgba(255,255,255,0.08)", borderRadius: 1, transition: "background 300ms" }} />}
              </div>
            ))}
            <button onClick={skip} style={{ background: "none", border: "none", cursor: "pointer", color: "#64748B", fontSize: 12, marginLeft: 8, display: "flex", alignItems: "center", gap: 4 }}>
              <X size={14} /> Skip
            </button>
          </div>
        </div>

        {/* Card */}
        <div style={{ background: BG, borderRadius: 20, overflow: "hidden", boxShadow: "0 25px 80px rgba(0,0,0,0.3)" }}>

          {/* ── STEP 1: Welcome ── */}
          {step === 1 && (
            <div style={{ padding: "48px 48px 40px" }}>
              <div style={{ textAlign: "center", marginBottom: 36 }}>
                <div style={{ width: 72, height: 72, borderRadius: 18, background: PRIMARY_LIGHT, display: "inline-flex", alignItems: "center", justifyContent: "center", marginBottom: 20 }}>
                  <Sparkles size={32} color={PRIMARY} />
                </div>
                <h1 style={{ fontSize: 28, fontWeight: 800, color: TEXT, margin: "0 0 8px" }}>Welcome to RAF Intelligence</h1>
                <p style={{ fontSize: 15, color: TEXT_SEC, maxWidth: 500, margin: "0 auto" }}>
                  Let&apos;s set up your workspace. Tell us about your role so we can tailor the experience.
                </p>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 32 }}>
                {ROLES.map((r) => {
                  const active = selectedRole === r.id;
                  const Icon = r.icon;
                  return (
                    <button key={r.id} onClick={() => setSelectedRole(r.id)} style={{
                      display: "flex", alignItems: "flex-start", gap: 14, padding: 18,
                      border: `2px solid ${active ? r.color : BORDER}`, borderRadius: 14,
                      background: active ? `${r.color}08` : BG, cursor: "pointer", textAlign: "left",
                      transition: "all 150ms",
                    }}>
                      <div style={{ width: 42, height: 42, borderRadius: 10, background: active ? `${r.color}15` : BG_SUBTLE, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                        <Icon size={20} color={active ? r.color : TEXT_MUTED} />
                      </div>
                      <div>
                        <div style={{ fontSize: 14, fontWeight: 700, color: TEXT }}>{r.label}</div>
                        <div style={{ fontSize: 12, color: TEXT_SEC, marginTop: 2 }}>{r.desc}</div>
                      </div>
                      {active && <Check size={16} color={r.color} style={{ marginLeft: "auto", marginTop: 2 }} />}
                    </button>
                  );
                })}
              </div>
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <button onClick={() => setStep(2)} style={btnPrimary}>
                  Continue <ArrowRight size={16} />
                </button>
              </div>
            </div>
          )}

          {/* ── STEP 0: Splash ── */}
          {step === 0 && (
            <div style={{ padding: "60px 48px 48px", textAlign: "center" }}>
              <div style={{ width: 88, height: 88, borderRadius: 22, background: "linear-gradient(135deg, #DBEAFE, #EDE9FE)", display: "inline-flex", alignItems: "center", justifyContent: "center", marginBottom: 28 }}>
                <Stethoscope size={40} color={PRIMARY} />
              </div>
              <h1 style={{ fontSize: 32, fontWeight: 800, color: TEXT, margin: "0 0 12px", lineHeight: 1.2 }}>
                AI-Powered Risk Adjustment
              </h1>
              <p style={{ fontSize: 16, color: TEXT_SEC, maxWidth: 520, margin: "0 auto 36px", lineHeight: 1.6 }}>
                Automate HCC coding, identify missed diagnoses, and maximize RAF scores with clinical-grade AI analysis.
              </p>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 40, maxWidth: 560, margin: "0 auto 40px" }}>
                {[
                  { icon: Database, label: "Connect EMR", sub: "Sync patient data" },
                  { icon: Sparkles, label: "AI Analysis", sub: "Find missed HCCs" },
                  { icon: BarChart3, label: "Track Revenue", sub: "Maximize RAF scores" },
                ].map((f) => (
                  <div key={f.label} style={{ padding: 16, background: BG_SUBTLE, borderRadius: 12, border: `1px solid ${BORDER}` }}>
                    <f.icon size={22} color={PRIMARY} style={{ marginBottom: 8 }} />
                    <div style={{ fontSize: 13, fontWeight: 700, color: TEXT }}>{f.label}</div>
                    <div style={{ fontSize: 11, color: TEXT_SEC, marginTop: 2 }}>{f.sub}</div>
                  </div>
                ))}
              </div>
              <button onClick={() => setStep(1)} style={{ ...btnPrimary, padding: "14px 40px", fontSize: 16 }}>
                Get Started <ArrowRight size={18} />
              </button>
            </div>
          )}

          {/* ── STEP 2: Connect EMR ── */}
          {step === 2 && (
            <div style={{ padding: "40px 48px 40px" }}>
              {connectionMode === "vendor" && (
                <>
                  <div style={{ marginBottom: 28 }}>
                    <h2 style={{ fontSize: 24, fontWeight: 800, color: TEXT, margin: "0 0 8px" }}>Connect Your EMR</h2>
                    <p style={{ fontSize: 14, color: TEXT_SEC, margin: 0 }}>
                      Select your EMR vendor to get started, or try the demo with sample data.
                    </p>
                  </div>

                  {/* Demo card — prominent */}
                  <div
                    onClick={() => setConnectionMode("demo")}
                    style={{
                      display: "flex", alignItems: "center", justifyContent: "space-between",
                      padding: 20, borderRadius: 14, cursor: "pointer",
                      background: "linear-gradient(135deg, #FEF3C7 0%, #FFF7ED 100%)",
                      border: `2px solid ${WARNING}`, marginBottom: 20,
                      transition: "all 150ms",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                      <div style={{ width: 48, height: 48, borderRadius: 12, background: "#FFF", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 24 }}>
                        <Play size={22} color={WARNING} />
                      </div>
                      <div>
                        <div style={{ fontSize: 15, fontWeight: 700, color: "#92400E" }}>Try Demo Mode</div>
                        <div style={{ fontSize: 12, color: "#A16207" }}>Explore with sample OpenEMR patient data — no setup required</div>
                      </div>
                    </div>
                    <ArrowRight size={18} color="#92400E" />
                  </div>

                  <div style={{ fontSize: 12, fontWeight: 600, color: TEXT_MUTED, textTransform: "uppercase", letterSpacing: 1, marginBottom: 12 }}>
                    Or connect your EMR system
                  </div>

                  {/* Vendor grid */}
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, marginBottom: 28 }}>
                    {vendors.map((v: any) => {
                      const vi = VENDOR_ICONS[v.vendor] || { icon: "🏥", color: "#64748B", bg: "#F1F5F9" };
                      return (
                        <button key={v.vendor} onClick={() => {
                          setSelectedVendor(v.vendor);
                          setFormData((f) => ({
                            ...f,
                            display_name: v.name,
                            fhir_base_url: v.fhir_base_url || "",
                          }));
                          setConnectionMode("form");
                        }} style={{
                          display: "flex", alignItems: "center", gap: 10, padding: 14,
                          border: `1px solid ${BORDER}`, borderRadius: 12,
                          background: BG, cursor: "pointer", textAlign: "left",
                          transition: "all 150ms",
                        }}>
                          <div style={{ width: 36, height: 36, borderRadius: 8, background: vi.bg, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18 }}>
                            {vi.icon}
                          </div>
                          <div style={{ fontSize: 13, fontWeight: 600, color: TEXT }}>{v.name}</div>
                        </button>
                      );
                    })}
                  </div>

                  <div style={{ display: "flex", justifyContent: "space-between" }}>
                    <button onClick={() => setStep(1)} style={btnSecondary}><ArrowLeft size={16} /> Back</button>
                    <button onClick={() => setStep(3)} style={{ ...btnSecondary, color: TEXT_SEC }}>Skip for now <ArrowRight size={16} /></button>
                  </div>
                </>
              )}

              {/* Demo confirmation */}
              {connectionMode === "demo" && (
                <div style={{ textAlign: "center", padding: "20px 0" }}>
                  <div style={{ width: 72, height: 72, borderRadius: 18, background: WARNING_LIGHT, display: "inline-flex", alignItems: "center", justifyContent: "center", marginBottom: 24 }}>
                    <Stethoscope size={32} color={WARNING} />
                  </div>
                  <h2 style={{ fontSize: 24, fontWeight: 800, color: TEXT, margin: "0 0 8px" }}>Connect Demo OpenEMR?</h2>
                  <p style={{ fontSize: 14, color: TEXT_SEC, maxWidth: 420, margin: "0 auto 24px", lineHeight: 1.6 }}>
                    This will connect to the bundled OpenEMR demo instance with sample patient data. You can explore all features of RAF Intelligence.
                  </p>
                  <div style={{
                    background: SUCCESS_LIGHT, border: `1px solid ${SUCCESS}40`, borderRadius: 12,
                    padding: "16px 20px", marginBottom: 28, textAlign: "left", maxWidth: 380, margin: "0 auto 28px",
                    fontSize: 13, color: "#166534", lineHeight: 1.6,
                  }}>
                    <strong>What you&apos;ll get:</strong>
                    <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                      <li>Sample patient records from OpenEMR</li>
                      <li>Clinical data, diagnoses, and encounters</li>
                      <li>Full RAF scoring and AI analysis ready</li>
                    </ul>
                  </div>
                  {error && (
                    <div style={{ background: "#FEE2E2", border: `1px solid ${DANGER}40`, borderRadius: 8, padding: "10px 14px", marginBottom: 16, fontSize: 13, color: DANGER }}>
                      {error}
                    </div>
                  )}
                  <div style={{ display: "flex", gap: 12, justifyContent: "center" }}>
                    <button onClick={() => { setConnectionMode("vendor"); setError(""); }} style={btnSecondary}>
                      <ArrowLeft size={16} /> Back
                    </button>
                    <button onClick={handleDemoConnect} disabled={loading} style={{ ...btnPrimary, background: WARNING, opacity: loading ? 0.7 : 1 }}>
                      {loading ? <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> : <Stethoscope size={16} />}
                      {loading ? "Connecting..." : "Yes, Connect Demo"}
                    </button>
                  </div>
                </div>
              )}

              {/* Connection form */}
              {connectionMode === "form" && (
                <>
                  <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 24 }}>
                    <button onClick={() => { setConnectionMode("vendor"); setError(""); }} style={{ background: "none", border: "none", cursor: "pointer", color: TEXT_SEC, display: "flex", alignItems: "center", gap: 4, fontSize: 13 }}>
                      <ArrowLeft size={14} /> Back to vendors
                    </button>
                    <span style={{ fontSize: 13, color: TEXT_MUTED }}>|</span>
                    <span style={{ fontSize: 14, fontWeight: 700, color: TEXT }}>{formData.display_name || selectedVendor} Connection</span>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr", gap: 14, marginBottom: 20 }}>
                    {[
                      { key: "fhir_base_url", label: "FHIR Base URL *", placeholder: "https://your-emr.example.com/apis/fhir/R4", icon: Globe },
                      { key: "token_url", label: "Token URL", placeholder: "https://your-emr.example.com/oauth2/token", icon: Lock },
                      { key: "client_id", label: "Client ID", placeholder: "OAuth2 Client ID", icon: Users },
                    ].map((f) => (
                      <div key={f.key}>
                        <label style={{ fontSize: 12, fontWeight: 600, color: TEXT_SEC, marginBottom: 6, display: "block" }}>{f.label}</label>
                        <div style={{ position: "relative" }}>
                          <f.icon size={14} color={TEXT_MUTED} style={{ position: "absolute", left: 12, top: 12 }} />
                          <input
                            value={(formData as any)[f.key]}
                            onChange={(e) => setFormData((d) => ({ ...d, [f.key]: e.target.value }))}
                            placeholder={f.placeholder}
                            style={{
                              width: "100%", padding: "10px 12px 10px 34px", border: `1px solid ${BORDER}`,
                              borderRadius: 8, fontSize: 14, color: TEXT, background: BG_SUBTLE,
                              outline: "none", boxSizing: "border-box",
                            }}
                          />
                        </div>
                      </div>
                    ))}
                    <div>
                      <label style={{ fontSize: 12, fontWeight: 600, color: TEXT_SEC, marginBottom: 6, display: "block" }}>Client Secret</label>
                      <div style={{ position: "relative" }}>
                        <Lock size={14} color={TEXT_MUTED} style={{ position: "absolute", left: 12, top: 12 }} />
                        <input
                          type="password"
                          value={formData.client_secret}
                          onChange={(e) => setFormData((d) => ({ ...d, client_secret: e.target.value }))}
                          placeholder="OAuth2 Client Secret"
                          style={{
                            width: "100%", padding: "10px 12px 10px 34px", border: `1px solid ${BORDER}`,
                            borderRadius: 8, fontSize: 14, color: TEXT, background: BG_SUBTLE,
                            outline: "none", boxSizing: "border-box",
                          }}
                        />
                      </div>
                    </div>
                  </div>
                  {error && (
                    <div style={{ background: "#FEE2E2", border: `1px solid ${DANGER}40`, borderRadius: 8, padding: "10px 14px", marginBottom: 16, fontSize: 13, color: DANGER, display: "flex", alignItems: "center", gap: 8 }}>
                      <AlertCircle size={14} /> {error}
                    </div>
                  )}
                  <div style={{ display: "flex", justifyContent: "flex-end" }}>
                    <button onClick={handleCreateConnection} disabled={loading || !formData.fhir_base_url} style={{ ...btnPrimary, opacity: (loading || !formData.fhir_base_url) ? 0.6 : 1 }}>
                      {loading ? <Loader2 size={16} style={{ animation: "spin 1s linear infinite" }} /> : <Database size={16} />}
                      {loading ? "Connecting..." : "Connect & Test"}
                    </button>
                  </div>
                </>
              )}

              {/* Testing / Success */}
              {(connectionMode === "testing" || connectionMode === "success") && (
                <div style={{ textAlign: "center", padding: "40px 0" }}>
                  {connectionMode === "testing" && !testResult?.success && (
                    <>
                      <Loader2 size={48} color={PRIMARY} style={{ animation: "spin 1s linear infinite", marginBottom: 20 }} />
                      <h3 style={{ fontSize: 20, fontWeight: 700, color: TEXT, margin: "0 0 8px" }}>Testing Connection...</h3>
                      <p style={{ fontSize: 14, color: TEXT_SEC }}>Verifying database connectivity</p>
                      {testResult && !testResult.success && (
                        <div style={{ background: "#FEE2E2", borderRadius: 8, padding: "12px 16px", marginTop: 20, fontSize: 13, color: DANGER }}>
                          {testResult.message}
                          <br />
                          <button onClick={() => { setConnectionMode("form"); setTestResult(null); }} style={{ ...btnSecondary, marginTop: 12, padding: "8px 16px", fontSize: 13 }}>
                            Edit Connection
                          </button>
                        </div>
                      )}
                    </>
                  )}
                  {connectionMode === "success" && (
                    <>
                      <div style={{ width: 72, height: 72, borderRadius: "50%", background: SUCCESS_LIGHT, display: "inline-flex", alignItems: "center", justifyContent: "center", marginBottom: 20 }}>
                        <CheckCircle2 size={36} color={SUCCESS} />
                      </div>
                      <h3 style={{ fontSize: 24, fontWeight: 800, color: TEXT, margin: "0 0 8px" }}>Connected Successfully!</h3>
                      <p style={{ fontSize: 14, color: TEXT_SEC, marginBottom: 28 }}>
                        {testResult?.message || "Your EMR is now linked. Patient data is ready."}
                      </p>
                      <button onClick={() => setStep(3)} style={btnPrimary}>
                        See Your Data <ArrowRight size={16} />
                      </button>
                    </>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ── STEP 3: Data Preview ── */}
          {step === 3 && (
            <div style={{ padding: "48px 48px 40px", textAlign: "center" }}>
              <div style={{ width: 72, height: 72, borderRadius: 18, background: BG_ACCENT, display: "inline-flex", alignItems: "center", justifyContent: "center", marginBottom: 24 }}>
                <Users size={32} color={PRIMARY} />
              </div>
              <h2 style={{ fontSize: 24, fontWeight: 800, color: TEXT, margin: "0 0 8px" }}>Your Data at a Glance</h2>
              <p style={{ fontSize: 14, color: TEXT_SEC, marginBottom: 32 }}>
                Here&apos;s a quick overview of what&apos;s available in your system.
              </p>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16, marginBottom: 36, maxWidth: 480, margin: "0 auto 36px" }}>
                {[
                  { label: "Total Patients", value: previewData?.total_patients ?? "...", color: PRIMARY },
                  { label: "Analyzed", value: previewData?.patients_analyzed ?? "0", color: SUCCESS },
                  { label: "Avg RAF Score", value: previewData?.average_raf_score ? Number(previewData.average_raf_score).toFixed(2) : "--", color: WARNING },
                ].map((m) => (
                  <div key={m.label} style={{ padding: 20, background: BG_SUBTLE, borderRadius: 14, border: `1px solid ${BORDER}` }}>
                    <div style={{ fontSize: 28, fontWeight: 800, color: m.color }}>{m.value}</div>
                    <div style={{ fontSize: 12, color: TEXT_SEC, marginTop: 4 }}>{m.label}</div>
                  </div>
                ))}
              </div>
              <div style={{ display: "flex", justifyContent: "center", gap: 12 }}>
                <button onClick={() => setStep(2)} style={btnSecondary}><ArrowLeft size={16} /> Back</button>
                <button onClick={() => setStep(4)} style={btnPrimary}>Continue <ArrowRight size={16} /></button>
              </div>
            </div>
          )}

          {/* ── STEP 4: Ready ── */}
          {step === 4 && (
            <div style={{ padding: "48px 48px 40px", textAlign: "center" }}>
              <div style={{ width: 80, height: 80, borderRadius: "50%", background: SUCCESS_LIGHT, display: "inline-flex", alignItems: "center", justifyContent: "center", marginBottom: 24 }}>
                <CheckCircle2 size={40} color={SUCCESS} />
              </div>
              <h2 style={{ fontSize: 28, fontWeight: 800, color: TEXT, margin: "0 0 8px" }}>You&apos;re All Set!</h2>
              <p style={{ fontSize: 15, color: TEXT_SEC, maxWidth: 460, margin: "0 auto 36px", lineHeight: 1.6 }}>
                Your workspace is ready. Start exploring patients, running AI analysis, and tracking RAF scores.
              </p>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginBottom: 36, maxWidth: 520, margin: "0 auto 36px" }}>
                {[
                  { label: "View Patients", href: "/patients", icon: Users, color: "#3B82F6" },
                  { label: "Run Analysis", href: "/analysis", icon: Sparkles, color: "#7C3AED" },
                  { label: "View Reports", href: "/reports", icon: BarChart3, color: "#D97706" },
                ].map((a) => (
                  <button key={a.label} onClick={() => { complete(); router.push(a.href); }} style={{
                    display: "flex", flexDirection: "column", alignItems: "center", gap: 8,
                    padding: 20, border: `1px solid ${BORDER}`, borderRadius: 14,
                    background: BG, cursor: "pointer", transition: "all 150ms",
                  }}>
                    <div style={{ width: 42, height: 42, borderRadius: 10, background: `${a.color}12`, display: "flex", alignItems: "center", justifyContent: "center" }}>
                      <a.icon size={20} color={a.color} />
                    </div>
                    <span style={{ fontSize: 13, fontWeight: 600, color: TEXT }}>{a.label}</span>
                  </button>
                ))}
              </div>
              <button onClick={complete} style={{ ...btnPrimary, padding: "14px 40px", fontSize: 16 }}>
                Go to Dashboard <ArrowRight size={18} />
              </button>
            </div>
          )}
        </div>
      </div>

      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Getting Started Checklist — render on dashboard after onboarding
// ---------------------------------------------------------------------------

const CHECKLIST_ITEMS: { key: keyof GettingStartedState; label: string; href: string }[] = [
  { key: "connect_emr", label: "Connect your EMR", href: "/settings" },
  { key: "upload_document", label: "Upload your first document", href: "/uploads" },
  { key: "review_suspects", label: "Review suspect conditions", href: "/analysis" },
  { key: "configure_worklists", label: "Configure provider worklists", href: "/coder-worklist" },
];

export function GettingStartedChecklist() {
  const router = useRouter();
  const [state, setState] = useState<GettingStartedState | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    const raw = localStorage.getItem(GETTING_STARTED_KEY);
    if (raw) {
      try { setState(JSON.parse(raw)); } catch { setState(null); }
    }
  }, []);

  if (!state || dismissed) return null;

  const completed = Object.values(state).filter(Boolean).length;
  const total = CHECKLIST_ITEMS.length;
  if (completed >= total) return null;

  function toggle(key: keyof GettingStartedState) {
    setState((prev) => {
      if (!prev) return prev;
      const next = { ...prev, [key]: !prev[key] };
      localStorage.setItem(GETTING_STARTED_KEY, JSON.stringify(next));
      return next;
    });
  }

  function dismiss() {
    localStorage.removeItem(GETTING_STARTED_KEY);
    setDismissed(true);
  }

  return (
    <div
      style={{
        background: BG, border: `1px solid ${BORDER}`, borderRadius: 16,
        padding: "24px 28px", marginBottom: 24, boxShadow: "0 2px 12px rgba(0,0,0,0.06)",
      }}
      role="region"
      aria-label="Getting started checklist"
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <div>
          <h3 style={{ fontSize: 16, fontWeight: 700, color: TEXT, margin: 0 }}>Getting Started</h3>
          <p style={{ fontSize: 13, color: TEXT_SEC, margin: "4px 0 0" }}>
            {completed} of {total} complete
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ width: 120, height: 6, borderRadius: 3, background: "#E2E8F0", overflow: "hidden" }}>
            <div style={{ width: `${(completed / total) * 100}%`, height: "100%", background: SUCCESS, borderRadius: 3, transition: "width 300ms" }} />
          </div>
          <button
            onClick={dismiss}
            style={{ background: "none", border: "none", cursor: "pointer", color: TEXT_MUTED, fontSize: 12 }}
            aria-label="Dismiss getting started checklist"
          >
            <X size={16} />
          </button>
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {CHECKLIST_ITEMS.map((item) => {
          const checked = state[item.key];
          return (
            <div
              key={item.key}
              style={{
                display: "flex", alignItems: "center", gap: 12,
                padding: "10px 14px", borderRadius: 10,
                background: checked ? SUCCESS_LIGHT : BG_SUBTLE,
                border: `1px solid ${checked ? `${SUCCESS}30` : BORDER}`,
                transition: "all 200ms",
              }}
            >
              <button
                onClick={() => toggle(item.key)}
                style={{
                  width: 22, height: 22, borderRadius: 6, flexShrink: 0,
                  border: `2px solid ${checked ? SUCCESS : "#CBD5E1"}`,
                  background: checked ? SUCCESS : "transparent",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  cursor: "pointer", transition: "all 150ms",
                }}
                aria-label={`Mark "${item.label}" as ${checked ? "incomplete" : "complete"}`}
              >
                {checked && <Check size={14} color="#FFF" />}
              </button>
              <span style={{
                fontSize: 14, fontWeight: 500, flex: 1,
                color: checked ? TEXT_MUTED : TEXT,
                textDecoration: checked ? "line-through" : "none",
              }}>
                {item.label}
              </span>
              {!checked && (
                <button
                  onClick={() => router.push(item.href)}
                  style={{
                    background: "none", border: "none", cursor: "pointer",
                    color: PRIMARY, fontSize: 12, fontWeight: 600,
                    display: "flex", alignItems: "center", gap: 4,
                  }}
                >
                  Go <ArrowRight size={12} />
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
