"use client";

/**
 * /admin/demo  — Executive Demo Mode
 *
 * 5-section scroll-snapped walkthrough for CMO / MA-plan exec demos.
 * Role-gated: admin | manager only.
 *
 * Sections
 * --------
 *   1. Hero          — animated stat counters from live tenant data
 *   2. NLP Mining    — 3 highlighted suspect extractions from clinical notes
 *   3. Doc Ingestion — 9 source cards with live status + animated connector
 *   4. Huddle        — embedded /md/today iframe + point-of-care stats
 *   5. Audit-ready   — hash-chain + RFC 3161 + WORM archive summary
 *
 * Demo controls (top-right):
 *   - "Start demo tour"  — auto-scrolls through sections with 8s dwell each
 *   - "Reset demo data"  — admin-only, calls POST /api/admin/demo/reset
 *
 * Accessibility:
 *   - prefers-reduced-motion disables CSS animations and auto-scroll behavior
 *   - Page Down / Page Up navigates between sections
 *   - aria-labels on all interactive elements (axe-core 0 violations target)
 */

import React, {
  useEffect,
  useRef,
  useState,
  useCallback,
  CSSProperties,
} from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  Sparkles,
  Users,
  TrendingUp,
  Search,
  DollarSign,
  Cloud,
  FileText,
  Server,
  Link2,
  Database,
  FlaskConical,
  Zap,
  FileStack,
  Activity,
  ShieldCheck,
  Link as LinkIcon,
  ChevronDown,
  Play,
  RotateCcw,
  CheckCircle,
  Loader2,
  AlertTriangle,
} from "lucide-react";
import { useAuth } from "@/contexts/auth-context";
import api from "@/lib/api";
import { tokens } from "@/styles/tokens";

// ---------------------------------------------------------------------------
// Color palette
// ---------------------------------------------------------------------------

const NAVY       = "#0B1437";
const NAVY_MID   = "#0D1A45";
const NAVY_LIGHT = "#132054";
const GOLD       = "#F59E0B";
const GOLD_SOFT  = "#FEF3C7";
const WHITE      = tokens.white;
const SLATE50    = tokens.slate50;
const SLATE200   = tokens.slate200;
const SLATE700   = tokens.slate700;
const SLATE800   = tokens.slate800;
const PRIMARY    = tokens.primary;
const SUCCESS    = tokens.success;
const TEAL       = tokens.teal700;

// ---------------------------------------------------------------------------
// Section identifiers
// ---------------------------------------------------------------------------

const SECTION_IDS = ["hero", "nlp", "ingestion", "huddle", "audit"] as const;
type SectionId = (typeof SECTION_IDS)[number];

// ---------------------------------------------------------------------------
// API types
// ---------------------------------------------------------------------------

interface DemoStats {
  patient_count: number;
  avg_raf_score: number;
  suspects_ytd: number;
  revenue_at_stake: number;
}

interface SuspectRow {
  id: number;
  patient_initials: string;
  hcc_label: string;
  icd10: string;
  confidence: number;
  evidence_sentence: string;
  page_number: number;
  source_doc: string;
}

interface IngestionSource {
  id: string;
  status: "active" | "idle" | "not_configured";
  docs_24h: number;
}

interface IngestionDashboard {
  sources: IngestionSource[];
}

// ---------------------------------------------------------------------------
// API fetchers
// ---------------------------------------------------------------------------

async function fetchDemoStats(): Promise<DemoStats> {
  const { data } = await api.get<DemoStats>("/api/admin/demo/stats");
  return data;
}

async function fetchDemoSuspects(): Promise<SuspectRow[]> {
  const { data } = await api.get<SuspectRow[]>("/api/admin/demo/suspects");
  return data;
}

async function fetchIngestionDashboard(): Promise<IngestionDashboard> {
  const { data } = await api.get<IngestionDashboard>(
    "/api/admin/document-ingestion/dashboard"
  );
  return data;
}

async function postDemoReset(): Promise<{ job_id: string }> {
  const { data } = await api.post<{ job_id: string }>("/api/admin/demo/reset");
  return data;
}

// ---------------------------------------------------------------------------
// Animated count-up hook
// ---------------------------------------------------------------------------

function useCountUp(
  target: number,
  duration = 1500,
  reducedMotion = false
): number {
  const [value, setValue] = useState(reducedMotion ? target : 0);
  const rafRef = useRef<number>(0);

  useEffect(() => {
    if (reducedMotion) {
      setValue(target);
      return;
    }
    if (target === 0) return;
    const start = performance.now();
    function tick(now: number) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      // Ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      setValue(Math.round(target * eased));
      if (progress < 1) {
        rafRef.current = requestAnimationFrame(tick);
      }
    }
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [target, duration, reducedMotion]);

  return value;
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

function fmtCount(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(0) + "K";
  return n.toLocaleString();
}

function fmtDollar(n: number): string {
  if (n >= 1_000_000) return "$" + (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return "$" + (n / 1_000).toFixed(0) + "K";
  return "$" + n.toLocaleString();
}

function fmtRaf(n: number): string {
  return (n / 100).toFixed(2);
}

// ---------------------------------------------------------------------------
// Fallback data (shown when backend endpoints are unavailable)
// ---------------------------------------------------------------------------

const FALLBACK_STATS: DemoStats = {
  patient_count: 12480,
  avg_raf_score: 118, // ÷100 in UI = 1.18
  suspects_ytd: 3740,
  revenue_at_stake: 4_200_000,
};

const FALLBACK_SUSPECTS: SuspectRow[] = [
  {
    id: 1,
    patient_initials: "J.M.",
    hcc_label: "Chronic Kidney Disease, Stage 3",
    icd10: "N18.3",
    confidence: 0.92,
    evidence_sentence:
      "eGFR consistently below 45 mL/min/1.73m² for the past 18 months per lab records dated 2024-11-08.",
    page_number: 4,
    source_doc: "Nephrology Consult Note 2024-11-12",
  },
  {
    id: 2,
    patient_initials: "R.T.",
    hcc_label: "Major Depressive Disorder, Moderate",
    icd10: "F32.1",
    confidence: 0.87,
    evidence_sentence:
      "Patient endorses persistent depressed mood, anhedonia, and sleep disturbance consistent with MDD per PHQ-9 score of 14.",
    page_number: 2,
    source_doc: "Behavioral Health Assessment 2025-01-20",
  },
  {
    id: 3,
    patient_initials: "A.K.",
    hcc_label: "Peripheral Vascular Disease",
    icd10: "I73.9",
    confidence: 0.83,
    evidence_sentence:
      "ABI of 0.72 bilaterally noted; claudication symptoms reported with ambulation > 1 block.",
    page_number: 7,
    source_doc: "Vascular Surgery Consult 2025-02-03",
  },
];

// ---------------------------------------------------------------------------
// Source metadata (9 ingestion sources)
// ---------------------------------------------------------------------------

const SOURCE_META = [
  { id: "fhir-bulk",   name: "FHIR Bulk",   icon: Cloud },
  { id: "fhir-docref", name: "FHIR DocRef", icon: FileText },
  { id: "hl7v2-mdm",   name: "HL7 v2",      icon: Server },
  { id: "direct-ccda", name: "Direct",       icon: Link2 },
  { id: "hie",         name: "HIE",          icon: Database },
  { id: "datavant",    name: "Datavant",     icon: FlaskConical },
  { id: "inovalon",    name: "Inovalon",     icon: Zap },
  { id: "reveleer",    name: "Reveleer",     icon: FileStack },
  { id: "openemr",     name: "OpenEMR",      icon: Activity },
] as const;

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface StatTileProps {
  icon: React.ReactNode;
  label: string;
  value: number;
  format: (n: number) => string;
  reducedMotion: boolean;
}

function StatTile({ icon, label, value, format, reducedMotion }: StatTileProps) {
  const animated = useCountUp(value, 1500, reducedMotion);
  return (
    <div
      style={{
        flex: "1 1 180px",
        minWidth: 160,
        backgroundColor: "rgba(255,255,255,0.07)",
        border: "1px solid rgba(255,255,255,0.12)",
        borderRadius: 14,
        padding: "28px 24px",
        display: "flex",
        flexDirection: "column",
        gap: 12,
        backdropFilter: "blur(8px)",
      }}
    >
      <div
        style={{
          width: 44,
          height: 44,
          borderRadius: 10,
          backgroundColor: "rgba(245,158,11,0.18)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: GOLD,
        }}
        aria-hidden="true"
      >
        {icon}
      </div>
      <div
        style={{
          fontSize: 38,
          fontWeight: 800,
          color: WHITE,
          lineHeight: 1.1,
          letterSpacing: "-0.02em",
          fontVariantNumeric: "tabular-nums",
        }}
        aria-live="polite"
        aria-label={`${label}: ${format(value)}`}
      >
        {format(animated)}
      </div>
      <div style={{ fontSize: 13, color: "rgba(255,255,255,0.6)", fontWeight: 500 }}>
        {label}
      </div>
    </div>
  );
}

// ---- Ingestion source card ----

interface IngestionCardProps {
  id: string;
  name: string;
  icon: React.ComponentType<{ style?: CSSProperties }>;
  status: "active" | "idle" | "not_configured";
  docs24h: number;
  highlighted: boolean;
  onClick: () => void;
}

function IngestionCard({
  name,
  icon: Icon,
  status,
  docs24h,
  highlighted,
  onClick,
}: IngestionCardProps) {
  const statusColor =
    status === "active"
      ? SUCCESS
      : status === "idle"
      ? tokens.warningStrong
      : tokens.slate400;
  const statusLabel =
    status === "active" ? "Active" : status === "idle" ? "Idle" : "Not configured";

  return (
    <button
      onClick={onClick}
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 10,
        padding: "20px 14px",
        borderRadius: 14,
        border: highlighted ? `2px solid ${GOLD}` : `1px solid ${SLATE200}`,
        backgroundColor: highlighted ? GOLD_SOFT : WHITE,
        cursor: "pointer",
        transition: "all 250ms cubic-bezier(0.4,0,0.2,1)",
        boxShadow: highlighted
          ? `0 0 0 3px ${GOLD}40, 0 4px 20px rgba(245,158,11,0.18)`
          : "0 1px 4px rgba(0,0,0,0.05)",
        transform: highlighted ? "scale(1.04)" : "scale(1)",
        textAlign: "center",
        width: "100%",
      }}
      aria-label={`${name} — ${statusLabel}`}
      aria-pressed={highlighted}
    >
      <div
        style={{
          width: 42,
          height: 42,
          borderRadius: 10,
          backgroundColor: highlighted ? "rgba(245,158,11,0.12)" : tokens.slate100,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: highlighted ? GOLD : SLATE700,
        }}
        aria-hidden="true"
      >
        <Icon style={{ width: 20, height: 20 }} />
      </div>
      <div style={{ fontSize: 12, fontWeight: 600, color: SLATE800, lineHeight: 1.3 }}>
        {name}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
        <span
          role="img"
          aria-label={statusLabel}
          style={{
            width: 7,
            height: 7,
            borderRadius: "50%",
            backgroundColor: statusColor,
            display: "inline-block",
          }}
        />
        <span style={{ fontSize: 10, color: statusColor, fontWeight: 600 }}>
          {docs24h > 0 ? `${docs24h} docs` : statusLabel}
        </span>
      </div>
    </button>
  );
}

// ---- Suspect row (NLP section) ----

interface SuspectItemProps {
  suspect: SuspectRow;
  isHighlighted: boolean;
  onClick: () => void;
}

function SuspectItem({ suspect, isHighlighted, onClick }: SuspectItemProps) {
  const confidencePct = Math.round(suspect.confidence * 100);
  return (
    <div
      style={{
        border: `1px solid ${isHighlighted ? PRIMARY : SLATE200}`,
        borderRadius: 10,
        padding: "18px 20px",
        backgroundColor: isHighlighted ? tokens.primarySoft : WHITE,
        cursor: "pointer",
        transition: "all 200ms",
      }}
      onClick={onClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && onClick()}
      aria-label={`Suspect: ${suspect.hcc_label}. Click to see evidence.`}
      aria-pressed={isHighlighted}
    >
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 12,
          marginBottom: 10,
        }}
      >
        <div>
          <span
            style={{
              fontSize: 11,
              fontWeight: 700,
              color: TEAL,
              backgroundColor: tokens.tealSoft,
              padding: "2px 8px",
              borderRadius: 4,
              marginRight: 8,
            }}
          >
            {suspect.icd10}
          </span>
          <span style={{ fontSize: 14, fontWeight: 600, color: SLATE800 }}>
            {suspect.hcc_label}
          </span>
        </div>
        <div
          style={{
            fontSize: 11,
            fontWeight: 700,
            color: PRIMARY,
            backgroundColor: tokens.primarySoft,
            padding: "3px 10px",
            borderRadius: 14,
            whiteSpace: "nowrap",
            flexShrink: 0,
          }}
        >
          {confidencePct}% confidence
        </div>
      </div>

      <p style={{ fontSize: 13, lineHeight: 1.7, color: tokens.slate600, margin: 0 }}>
        {isHighlighted ? (
          <>
            <mark
              style={{
                backgroundColor: "#FDE68A",
                color: SLATE800,
                padding: "1px 2px",
                borderRadius: 3,
              }}
            >
              {suspect.evidence_sentence}
            </mark>{" "}
            <span style={{ fontSize: 11, color: tokens.slate500, marginLeft: 4 }}>
              (p. {suspect.page_number} — {suspect.source_doc})
            </span>
          </>
        ) : (
          <span style={{ color: tokens.slate400, fontStyle: "italic" }}>
            &ldquo;{suspect.evidence_sentence.slice(0, 80)}&hellip;&rdquo;
          </span>
        )}
      </p>

      {!isHighlighted && (
        <div
          style={{
            marginTop: 8,
            display: "flex",
            alignItems: "center",
            gap: 4,
            fontSize: 12,
            color: PRIMARY,
            fontWeight: 600,
          }}
        >
          <Search style={{ width: 12, height: 12 }} aria-hidden="true" />
          Show me
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

export default function AdminDemoPage() {
  const { user } = useAuth();
  const router = useRouter();

  // ---- Role gate ----
  const role = (user as { role?: string } | null)?.role ?? "";
  const isAdmin = role === "admin";
  const isManager = role === "manager";

  useEffect(() => {
    if (user && !isAdmin && !isManager) {
      router.replace("/");
    }
  }, [user, isAdmin, isManager, router]);

  // ---- Reduced motion ----
  const [reducedMotion, setReducedMotion] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReducedMotion(mq.matches);
    const handler = () => setReducedMotion(mq.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  // ---- Scroll container / section refs ----
  const containerRef = useRef<HTMLDivElement>(null);
  const sectionRefs = useRef<Record<SectionId, HTMLElement | null>>({
    hero: null,
    nlp: null,
    ingestion: null,
    huddle: null,
    audit: null,
  });

  // ---- Active section tracking ----
  const [activeSection, setActiveSection] = useState<SectionId>("hero");

  // ---- Tour state ----
  const [tourRunning, setTourRunning] = useState(false);
  const tourTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ---- NLP section state ----
  const [highlightedSuspect, setHighlightedSuspect] = useState<number | null>(null);

  // ---- Ingestion section state ----
  const [highlightedSource, setHighlightedSource] = useState<string | null>(null);

  // ---- Data ----
  const { data: statsData } = useQuery({
    queryKey: ["demo-stats"],
    queryFn: fetchDemoStats,
    retry: false,
    staleTime: 60_000,
  });
  const { data: suspectsData } = useQuery({
    queryKey: ["demo-suspects"],
    queryFn: fetchDemoSuspects,
    retry: false,
    staleTime: 60_000,
  });
  const { data: ingestionData } = useQuery({
    queryKey: ["demo-ingestion-dashboard"],
    queryFn: fetchIngestionDashboard,
    retry: false,
    staleTime: 60_000,
  });

  const stats    = statsData ?? FALLBACK_STATS;
  const suspects = (suspectsData && suspectsData.length > 0)
    ? suspectsData.slice(0, 3)
    : FALLBACK_SUSPECTS;

  const sourceStatusMap = new Map<string, IngestionSource>(
    (ingestionData?.sources ?? []).map((s) => [s.id, s])
  );

  // ---- Reset mutation ----
  const [resetJobId, setResetJobId] = useState<string | null>(null);
  const resetMutation = useMutation({
    mutationFn: postDemoReset,
    onSuccess: (d) => setResetJobId(d.job_id),
  });

  // ---- Scroll helpers ----
  const scrollToSection = useCallback(
    (id: SectionId) => {
      const el = sectionRefs.current[id];
      if (!el) return;
      el.scrollIntoView({
        behavior: reducedMotion ? "instant" : "smooth",
        block: "start",
      });
      setActiveSection(id);
    },
    [reducedMotion]
  );

  // Track active section via IntersectionObserver
  useEffect(() => {
    const observers: IntersectionObserver[] = [];
    SECTION_IDS.forEach((id) => {
      const el = sectionRefs.current[id];
      if (!el) return;
      const obs = new IntersectionObserver(
        ([entry]) => {
          if (entry.isIntersecting) setActiveSection(id);
        },
        { threshold: 0.4, root: containerRef.current }
      );
      obs.observe(el);
      observers.push(obs);
    });
    return () => observers.forEach((o) => o.disconnect());
  }, []);

  // ---- Demo tour ----
  const startTour = useCallback(() => {
    if (tourRunning) return;
    setTourRunning(true);
    let idx = 0;
    function advance() {
      if (idx >= SECTION_IDS.length) {
        setTourRunning(false);
        return;
      }
      scrollToSection(SECTION_IDS[idx]);
      idx++;
      tourTimerRef.current = setTimeout(advance, 8000);
    }
    advance();
  }, [tourRunning, scrollToSection]);

  const stopTour = useCallback(() => {
    if (tourTimerRef.current) clearTimeout(tourTimerRef.current);
    setTourRunning(false);
  }, []);

  useEffect(() => () => { if (tourTimerRef.current) clearTimeout(tourTimerRef.current); }, []);

  // ---- Keyboard navigation (Page Up / Page Down) ----
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      const currentIdx = SECTION_IDS.indexOf(activeSection);
      if (e.key === "PageDown" || (e.key === "ArrowDown" && e.altKey)) {
        e.preventDefault();
        const next = SECTION_IDS[Math.min(currentIdx + 1, SECTION_IDS.length - 1)];
        scrollToSection(next);
      } else if (e.key === "PageUp" || (e.key === "ArrowUp" && e.altKey)) {
        e.preventDefault();
        const prev = SECTION_IDS[Math.max(currentIdx - 1, 0)];
        scrollToSection(prev);
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [activeSection, scrollToSection]);

  if (user && !isAdmin && !isManager) return null;

  // ---- Reusable style helpers ----
  function sectionStyle(bg: string, minH = 700): CSSProperties {
    return {
      minHeight: minH,
      backgroundColor: bg,
      padding: "64px clamp(24px, 6vw, 80px)",
      display: "flex",
      flexDirection: "column",
      justifyContent: "center",
      scrollSnapAlign: "start",
      scrollSnapStop: "always",
      position: "relative",
    };
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <>
      {/* Global keyframe animations — suppressed by prefers-reduced-motion */}
      <style>{`
        @media (prefers-reduced-motion: no-preference) {
          @keyframes fadeSlideUp {
            from { opacity: 0; transform: translateY(20px); }
            to   { opacity: 1; transform: translateY(0); }
          }
          @keyframes pulseGold {
            0%,100% { box-shadow: 0 0 0 0 rgba(245,158,11,0); }
            50%      { box-shadow: 0 0 0 8px rgba(245,158,11,0.2); }
          }
          @keyframes spin {
            from { transform: rotate(0deg); }
            to   { transform: rotate(360deg); }
          }
          .demo-section > * { animation: fadeSlideUp 0.5s ease both; }
          .demo-gold-pulse  { animation: pulseGold 2.5s ease-in-out infinite; }
          .spin-icon        { animation: spin 1s linear infinite; }
        }
        :focus-visible {
          outline: 3px solid #F59E0B;
          outline-offset: 2px;
          border-radius: 4px;
        }
      `}</style>

      {/* ------------------------------------------------------------------ */}
      {/* Fixed demo controls — top-right                                     */}
      {/* ------------------------------------------------------------------ */}
      <div
        style={{
          position: "fixed",
          top: 16,
          right: 24,
          zIndex: 200,
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
        aria-label="Demo controls"
      >
        {/* Section progress dots */}
        <div
          role="tablist"
          aria-label="Demo sections"
          style={{ display: "flex", alignItems: "center", gap: 6, marginRight: 6 }}
        >
          {SECTION_IDS.map((id, i) => (
            <button
              key={id}
              role="tab"
              aria-selected={activeSection === id}
              aria-label={`Go to section ${i + 1}: ${id}`}
              onClick={() => scrollToSection(id)}
              style={{
                width: activeSection === id ? 22 : 8,
                height: 8,
                borderRadius: 4,
                border: "none",
                backgroundColor: activeSection === id ? GOLD : "rgba(15,20,55,0.3)",
                cursor: "pointer",
                transition: "all 250ms",
                padding: 0,
              }}
            />
          ))}
        </div>

        {/* Start / stop tour */}
        <button
          onClick={tourRunning ? stopTour : startTour}
          className={tourRunning ? undefined : "demo-gold-pulse"}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 7,
            padding: "9px 18px",
            borderRadius: 24,
            border: "none",
            backgroundColor: tourRunning ? tokens.slate600 : GOLD,
            color: tourRunning ? WHITE : SLATE800,
            fontSize: 13,
            fontWeight: 700,
            cursor: "pointer",
            boxShadow: "0 2px 12px rgba(0,0,0,0.2)",
            transition: "background-color 200ms",
          }}
          aria-label={tourRunning ? "Stop demo tour" : "Start demo tour"}
        >
          {tourRunning ? (
            <>
              <Loader2 className="spin-icon" style={{ width: 14, height: 14 }} aria-hidden="true" />
              Stop tour
            </>
          ) : (
            <>
              <Play style={{ width: 14, height: 14 }} aria-hidden="true" />
              Start demo tour
            </>
          )}
        </button>

        {/* Reset demo data — admin only */}
        {isAdmin && (
          <button
            onClick={() => resetMutation.mutate()}
            disabled={resetMutation.isPending}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 7,
              padding: "9px 18px",
              borderRadius: 24,
              border: `1px solid ${SLATE200}`,
              backgroundColor: WHITE,
              color: SLATE700,
              fontSize: 13,
              fontWeight: 600,
              cursor: resetMutation.isPending ? "not-allowed" : "pointer",
              opacity: resetMutation.isPending ? 0.7 : 1,
              boxShadow: "0 2px 8px rgba(0,0,0,0.1)",
            }}
            aria-label="Reset demo data"
            title="Re-seeds realistic demo data (admin only)"
          >
            {resetMutation.isPending ? (
              <Loader2 className="spin-icon" style={{ width: 14, height: 14 }} aria-hidden="true" />
            ) : (
              <RotateCcw style={{ width: 14, height: 14 }} aria-hidden="true" />
            )}
            {resetMutation.isSuccess
              ? resetJobId
                ? `Job ${resetJobId.slice(0, 6)}…`
                : "Done"
              : "Reset demo data"}
          </button>
        )}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Scroll container                                                     */}
      {/* ------------------------------------------------------------------ */}
      <div
        ref={containerRef}
        id="main-content"
        style={{
          height: "100vh",
          overflowY: "auto",
          scrollSnapType: reducedMotion ? "none" : "y mandatory",
          scrollBehavior: reducedMotion ? "auto" : "smooth",
        }}
        aria-label="Demo mode walkthrough"
      >

        {/* ============================================================== */}
        {/* SECTION 1: HERO                                                 */}
        {/* ============================================================== */}
        <section
          id="demo-hero"
          ref={(el) => { sectionRefs.current.hero = el; }}
          style={{
            ...sectionStyle(NAVY, 700),
            background: `linear-gradient(135deg, ${NAVY} 0%, ${NAVY_MID} 50%, ${NAVY_LIGHT} 100%)`,
          }}
          className="demo-section"
          aria-label="Section 1: Platform overview"
          tabIndex={-1}
        >
          {/* Decorative radial glow */}
          <div
            aria-hidden="true"
            style={{
              position: "absolute",
              top: -80,
              right: -80,
              width: 400,
              height: 400,
              borderRadius: "50%",
              background: "radial-gradient(circle, rgba(245,158,11,0.12) 0%, transparent 70%)",
              pointerEvents: "none",
            }}
          />

          <div style={{ maxWidth: 1100, width: "100%", margin: "0 auto" }}>
            {/* Badge */}
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                backgroundColor: "rgba(245,158,11,0.15)",
                border: "1px solid rgba(245,158,11,0.3)",
                borderRadius: 24,
                padding: "6px 16px",
                marginBottom: 28,
              }}
            >
              <Sparkles style={{ width: 14, height: 14, color: GOLD }} aria-hidden="true" />
              <span style={{ fontSize: 12, fontWeight: 700, color: GOLD, letterSpacing: "0.06em", textTransform: "uppercase" }}>
                RAF Intelligence — Executive Overview
              </span>
            </div>

            <h1
              style={{
                fontSize: "clamp(28px, 4vw, 48px)",
                fontWeight: 800,
                color: WHITE,
                letterSpacing: "-0.025em",
                lineHeight: 1.15,
                marginBottom: 20,
              }}
            >
              The complete HCC risk-adjustment platform — from clinical note to CMS submission.
            </h1>

            <p
              style={{
                fontSize: 16,
                color: "rgba(255,255,255,0.65)",
                lineHeight: 1.7,
                maxWidth: 560,
                marginBottom: 52,
              }}
            >
              One platform that mines suspects from unstructured notes, closes gaps at the point of care, and delivers an audit-ready evidence chain for every dollar captured.
            </p>

            {/* Stat counter tiles */}
            <div
              style={{ display: "flex", flexWrap: "wrap", gap: 16 }}
              aria-label="Key platform metrics"
            >
              <StatTile
                icon={<Users style={{ width: 22, height: 22 }} />}
                label="Patients managed"
                value={stats.patient_count}
                format={fmtCount}
                reducedMotion={reducedMotion}
              />
              <StatTile
                icon={<TrendingUp style={{ width: 22, height: 22 }} />}
                label="Average RAF score"
                value={stats.avg_raf_score}
                format={fmtRaf}
                reducedMotion={reducedMotion}
              />
              <StatTile
                icon={<Search style={{ width: 22, height: 22 }} />}
                label="Suspects identified YTD"
                value={stats.suspects_ytd}
                format={fmtCount}
                reducedMotion={reducedMotion}
              />
              <StatTile
                icon={<DollarSign style={{ width: 22, height: 22 }} />}
                label="Revenue at stake"
                value={stats.revenue_at_stake}
                format={fmtDollar}
                reducedMotion={reducedMotion}
              />
            </div>

            {/* Scroll cue */}
            <button
              style={{
                marginTop: 48,
                display: "flex",
                alignItems: "center",
                gap: 8,
                color: "rgba(255,255,255,0.4)",
                fontSize: 12,
                cursor: "pointer",
                background: "none",
                border: "none",
                padding: 0,
              }}
              onClick={() => scrollToSection("nlp")}
              aria-label="Scroll to NLP section"
            >
              <ChevronDown style={{ width: 18, height: 18 }} aria-hidden="true" />
              Scroll to see NLP mining
            </button>
          </div>
        </section>

        {/* ============================================================== */}
        {/* SECTION 2: NLP SUSPECT MINING                                   */}
        {/* ============================================================== */}
        <section
          id="demo-nlp"
          ref={(el) => { sectionRefs.current.nlp = el; }}
          style={{
            ...sectionStyle(SLATE50, 700),
            background: `linear-gradient(180deg, ${WHITE} 0%, ${SLATE50} 100%)`,
          }}
          className="demo-section"
          aria-label="Section 2: NLP suspect mining"
          tabIndex={-1}
        >
          <div style={{ maxWidth: 900, width: "100%", margin: "0 auto" }}>
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                backgroundColor: tokens.primarySoft,
                borderRadius: 24,
                padding: "5px 14px",
                marginBottom: 20,
              }}
            >
              <Search style={{ width: 13, height: 13, color: PRIMARY }} aria-hidden="true" />
              <span style={{ fontSize: 11, fontWeight: 700, color: PRIMARY, letterSpacing: "0.06em", textTransform: "uppercase" }}>
                NLP Suspect Extraction
              </span>
            </div>

            <h2
              style={{
                fontSize: "clamp(26px, 3.5vw, 42px)",
                fontWeight: 800,
                color: SLATE800,
                letterSpacing: "-0.025em",
                lineHeight: 1.15,
                marginBottom: 12,
              }}
            >
              Every clinical note, automatically mined for HCC suspects.
            </h2>

            <p
              style={{
                fontSize: 16,
                color: tokens.slate500,
                lineHeight: 1.7,
                maxWidth: 560,
                marginBottom: 36,
              }}
            >
              Our Gemini-powered NLP pipeline reads every uploaded note and surfaces suspect conditions with verbatim evidence sentences — so coders review, not hunt.
            </p>

            {/* Mock clinical note */}
            <div
              style={{
                backgroundColor: NAVY,
                borderRadius: 14,
                padding: "18px 22px",
                marginBottom: 28,
                fontSize: 12,
                color: "rgba(255,255,255,0.7)",
                fontFamily: '"JetBrains Mono", monospace',
                lineHeight: 1.8,
                borderLeft: `4px solid ${GOLD}`,
              }}
              aria-label="Sample clinical note fragment"
            >
              <div style={{ color: GOLD, fontWeight: 700, marginBottom: 6, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                Progress Note — Primary Care Visit
              </div>
              Patient is a 68-year-old male presenting for quarterly follow-up. Lab results show{" "}
              <span style={{ color: "#FDE68A", fontWeight: 600 }}>
                eGFR consistently below 45 mL/min/1.73m&sup2;
              </span>{" "}
              for the past 18 months. Patient also reports{" "}
              <span style={{ color: "#FDE68A", fontWeight: 600 }}>
                PHQ-9 score of 14
              </span>
              , consistent with moderate MDD&hellip;
            </div>

            {/* Suspect cards */}
            <div
              style={{ display: "flex", flexDirection: "column", gap: 12 }}
              aria-label="Extracted suspects"
            >
              {suspects.map((s) => (
                <SuspectItem
                  key={s.id}
                  suspect={s}
                  isHighlighted={highlightedSuspect === s.id}
                  onClick={() =>
                    setHighlightedSuspect(highlightedSuspect === s.id ? null : s.id)
                  }
                />
              ))}
            </div>
          </div>
        </section>

        {/* ============================================================== */}
        {/* SECTION 3: DOCUMENT INGESTION                                   */}
        {/* ============================================================== */}
        <section
          id="demo-ingestion"
          ref={(el) => { sectionRefs.current.ingestion = el; }}
          style={{
            ...sectionStyle(WHITE, 720),
            background: `linear-gradient(180deg, ${SLATE50} 0%, ${WHITE} 100%)`,
          }}
          className="demo-section"
          aria-label="Section 3: Document ingestion sources"
          tabIndex={-1}
        >
          <div style={{ maxWidth: 960, width: "100%", margin: "0 auto" }}>
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                backgroundColor: tokens.successSoft,
                borderRadius: 24,
                padding: "5px 14px",
                marginBottom: 20,
              }}
            >
              <FileStack style={{ width: 13, height: 13, color: SUCCESS }} aria-hidden="true" />
              <span style={{ fontSize: 11, fontWeight: 700, color: SUCCESS, letterSpacing: "0.06em", textTransform: "uppercase" }}>
                9 Ingestion Sources
              </span>
            </div>

            <h2
              style={{
                fontSize: "clamp(26px, 3.5vw, 42px)",
                fontWeight: 800,
                color: SLATE800,
                letterSpacing: "-0.025em",
                lineHeight: 1.15,
                marginBottom: 12,
              }}
            >
              Every document pathway — unified.
            </h2>

            <p
              style={{
                fontSize: 16,
                color: tokens.slate500,
                lineHeight: 1.7,
                maxWidth: 560,
                marginBottom: 40,
              }}
            >
              FHIR Bulk, DocRef, HL7 v2, Direct, HIE, Datavant, Inovalon, Reveleer, and OpenEMR — all wired into a single ingestion pipeline. Click any source to see which one processed the suspect above.
            </p>

            {/* 9-card grid */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(130px, 1fr))",
                gap: 14,
                marginBottom: 32,
              }}
              role="list"
              aria-label="Ingestion source cards"
            >
              {SOURCE_META.map((src) => {
                const apiSrc   = sourceStatusMap.get(src.id);
                const status   = (apiSrc?.status as "active" | "idle" | "not_configured") ?? "idle";
                const docs24h  = apiSrc?.docs_24h ?? 0;
                return (
                  <div key={src.id} role="listitem">
                    <IngestionCard
                      id={src.id}
                      name={src.name}
                      icon={src.icon}
                      status={status}
                      docs24h={docs24h}
                      highlighted={highlightedSource === src.id}
                      onClick={() =>
                        setHighlightedSource(highlightedSource === src.id ? null : src.id)
                      }
                    />
                  </div>
                );
              })}
            </div>

            <Link
              href="/admin/document-ingestion"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                color: PRIMARY,
                fontSize: 13,
                fontWeight: 600,
                textDecoration: "none",
                borderBottom: `1px solid ${PRIMARY}`,
                paddingBottom: 1,
              }}
            >
              View full ingestion dashboard
              <ChevronDown style={{ width: 14, height: 14, transform: "rotate(-90deg)" }} aria-hidden="true" />
            </Link>
          </div>
        </section>

        {/* ============================================================== */}
        {/* SECTION 4: DOCTOR'S HUDDLE PREVIEW                              */}
        {/* ============================================================== */}
        <section
          id="demo-huddle"
          ref={(el) => { sectionRefs.current.huddle = el; }}
          style={{
            ...sectionStyle(NAVY_MID, 720),
            background: `linear-gradient(135deg, ${NAVY} 0%, ${NAVY_MID} 100%)`,
          }}
          className="demo-section"
          aria-label="Section 4: Doctor's huddle preview"
          tabIndex={-1}
        >
          <div
            aria-hidden="true"
            style={{
              position: "absolute",
              bottom: -60,
              left: -60,
              width: 320,
              height: 320,
              borderRadius: "50%",
              background: "radial-gradient(circle, rgba(37,99,235,0.18) 0%, transparent 70%)",
              pointerEvents: "none",
            }}
          />

          <div
            style={{
              maxWidth: 1060,
              width: "100%",
              margin: "0 auto",
              display: "flex",
              gap: 56,
              alignItems: "center",
              flexWrap: "wrap",
            }}
          >
            {/* Left: text */}
            <div style={{ flex: "1 1 280px", minWidth: 240 }}>
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 8,
                  backgroundColor: "rgba(37,99,235,0.2)",
                  borderRadius: 24,
                  padding: "5px 14px",
                  marginBottom: 20,
                }}
              >
                <Activity style={{ width: 13, height: 13, color: tokens.infoBlue }} aria-hidden="true" />
                <span style={{ fontSize: 11, fontWeight: 700, color: tokens.infoBlue, letterSpacing: "0.06em", textTransform: "uppercase" }}>
                  Pre-visit Huddle
                </span>
              </div>

              <h2
                style={{
                  fontSize: "clamp(26px, 3.5vw, 42px)",
                  fontWeight: 800,
                  color: WHITE,
                  letterSpacing: "-0.025em",
                  lineHeight: 1.15,
                  marginBottom: 16,
                }}
              >
                Close gaps at the point of care — not months later.
              </h2>

              <p
                style={{
                  fontSize: 16,
                  color: "rgba(255,255,255,0.65)",
                  lineHeight: 1.7,
                  marginBottom: 32,
                }}
              >
                The pre-visit huddle surfaces every open HCC gap, suspect, and AWV item before the patient walks in — empowering providers to act in the same visit.
              </p>

              {/* KPI pair */}
              <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
                {[
                  { pct: "67%", color: SUCCESS, label: "HCC gaps closed at point-of-care" },
                  { pct: "33%", color: tokens.infoBlue, label: "Retrospective capture (chart review)" },
                ].map(({ pct, color, label }) => (
                  <div
                    key={pct}
                    style={{
                      flex: "1 1 120px",
                      minWidth: 110,
                      backgroundColor: "rgba(255,255,255,0.07)",
                      border: "1px solid rgba(255,255,255,0.1)",
                      borderRadius: 10,
                      padding: "16px 20px",
                    }}
                  >
                    <div style={{ fontSize: 30, fontWeight: 800, color, marginBottom: 4 }}>
                      {pct}
                    </div>
                    <div style={{ fontSize: 12, color: "rgba(255,255,255,0.55)", lineHeight: 1.4 }}>
                      {label}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Right: iframe preview */}
            <div
              style={{
                flex: "1 1 460px",
                minWidth: 300,
                borderRadius: 14,
                overflow: "hidden",
                border: "1px solid rgba(255,255,255,0.12)",
                boxShadow: "0 20px 60px rgba(0,0,0,0.5)",
                aspectRatio: "16/9",
                backgroundColor: NAVY,
                position: "relative",
              }}
              aria-label="Huddle preview window"
            >
              <iframe
                src="/md/today"
                title="Pre-visit huddle preview"
                style={{
                  position: "absolute",
                  inset: 0,
                  width: "117.6%",
                  height: "117.6%",
                  border: "none",
                  transform: "scale(0.85)",
                  transformOrigin: "top left",
                }}
                sandbox="allow-same-origin allow-scripts"
                loading="lazy"
              />
            </div>
          </div>
        </section>

        {/* ============================================================== */}
        {/* SECTION 5: AUDIT-READY                                          */}
        {/* ============================================================== */}
        <section
          id="demo-audit"
          ref={(el) => { sectionRefs.current.audit = el; }}
          style={{
            ...sectionStyle(WHITE, 700),
            background: `linear-gradient(180deg, ${WHITE} 0%, ${SLATE50} 100%)`,
          }}
          className="demo-section"
          aria-label="Section 5: Audit readiness"
          tabIndex={-1}
        >
          <div style={{ maxWidth: 800, width: "100%", margin: "0 auto" }}>
            <div
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                backgroundColor: tokens.tealSoft,
                borderRadius: 24,
                padding: "5px 14px",
                marginBottom: 20,
              }}
            >
              <ShieldCheck style={{ width: 13, height: 13, color: TEAL }} aria-hidden="true" />
              <span style={{ fontSize: 11, fontWeight: 700, color: TEAL, letterSpacing: "0.06em", textTransform: "uppercase" }}>
                Audit Readiness
              </span>
            </div>

            <h2
              style={{
                fontSize: "clamp(26px, 3.5vw, 42px)",
                fontWeight: 800,
                color: SLATE800,
                letterSpacing: "-0.025em",
                lineHeight: 1.15,
                marginBottom: 12,
              }}
            >
              Every action, immutably recorded.
            </h2>

            <p
              style={{
                fontSize: 16,
                color: tokens.slate500,
                lineHeight: 1.7,
                maxWidth: 560,
                marginBottom: 44,
              }}
            >
              Regulators, RADV auditors, and your compliance team need a complete, tamper-evident chain of custody for every risk-adjustment action. We deliver it out of the box.
            </p>

            {/* Feature list */}
            <div style={{ display: "flex", flexDirection: "column", gap: 16, marginBottom: 44 }}>
              {[
                {
                  icon: <LinkIcon style={{ width: 20, height: 20 }} />,
                  title: "Hash-chained audit log",
                  desc: "Every write event is SHA-256 chained to the previous entry — a single bit flip is instantly detectable.",
                },
                {
                  icon: <ShieldCheck style={{ width: 20, height: 20 }} />,
                  title: "RFC 3161 timestamping",
                  desc: "Every chain head is RFC 3161-timestamped by a trusted TSA, giving cryptographic proof of time to any external auditor.",
                },
                {
                  icon: <CheckCircle style={{ width: 20, height: 20 }} />,
                  title: "WORM-archived for 7 years",
                  desc: "Audit records are written to immutable object storage — compliant with CMS RADV retention requirements and HIPAA §164.530(j).",
                },
                {
                  icon: <AlertTriangle style={{ width: 20, height: 20 }} />,
                  title: "Tamper-alert monitoring",
                  desc: "Automated chain-integrity sweeps run every 6 hours; any break triggers an immediate alert to the compliance team.",
                },
              ].map(({ icon, title, desc }) => (
                <div
                  key={title}
                  style={{
                    display: "flex",
                    gap: 16,
                    padding: "18px 20px",
                    borderRadius: 10,
                    border: `1px solid ${SLATE200}`,
                    backgroundColor: WHITE,
                  }}
                >
                  <div
                    style={{
                      width: 40,
                      height: 40,
                      borderRadius: 10,
                      backgroundColor: tokens.tealSoft,
                      border: `1px solid ${tokens.tealRing}`,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      color: TEAL,
                      flexShrink: 0,
                    }}
                    aria-hidden="true"
                  >
                    {icon}
                  </div>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: SLATE800, marginBottom: 4 }}>
                      {title}
                    </div>
                    <div style={{ fontSize: 13, color: tokens.slate500, lineHeight: 1.6 }}>
                      {desc}
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* CTA */}
            <Link
              href="/audit"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 10,
                padding: "13px 28px",
                borderRadius: 10,
                backgroundColor: NAVY,
                color: WHITE,
                fontSize: 14,
                fontWeight: 700,
                textDecoration: "none",
                boxShadow: "0 4px 16px rgba(11,20,55,0.25)",
                transition: "background-color 200ms",
              }}
              onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = NAVY_LIGHT)}
              onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = NAVY)}
            >
              <ShieldCheck style={{ width: 16, height: 16 }} aria-hidden="true" />
              Open audit chain viewer
            </Link>
          </div>
        </section>

      </div>
    </>
  );
}
