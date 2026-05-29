"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Heart, Upload, Play, CheckCircle, ChevronRight,
  RefreshCw, Database, FileSearch, Package, X, BookOpen,
} from "lucide-react";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from "@/components/ui/tooltip";

// ---------------------------------------------------------------------------
// Shared card style (local copy — avoids cross-file coupling)
// ---------------------------------------------------------------------------

const card: React.CSSProperties = {
  background: "hsl(var(--card))",
  border: "1px solid hsl(var(--border))",
  borderRadius: 12,
  boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
  padding: 20,
};

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface OnboardingCardProps {
  emrConnected: boolean;
  patientCount: number;
  analysisRunCount: number;
  attestationCount: number;
  auditPackageCount: number;
  demoLoading: boolean;
  onTryDemo: () => void;
  "data-testid"?: string;
}

// ---------------------------------------------------------------------------
// Persistence key
// ---------------------------------------------------------------------------

const HIDDEN_KEY = "raf_onboarding_hidden";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function OnboardingCard({
  emrConnected,
  patientCount,
  analysisRunCount,
  attestationCount,
  auditPackageCount,
  demoLoading,
  onTryDemo,
  "data-testid": testId = "onboarding-card",
}: OnboardingCardProps) {
  // Read persisted hide flag on mount; write it when user clicks Hide.
  const [hiddenByUser, setHiddenByUser] = useState(false);

  useEffect(() => {
    try {
      setHiddenByUser(localStorage.getItem(HIDDEN_KEY) === "1");
    } catch {
      // localStorage unavailable (SSR, privacy mode) — keep showing
    }
  }, []);

  const handleHide = () => {
    try {
      localStorage.setItem(HIDDEN_KEY, "1");
    } catch { /* ignore */ }
    setHiddenByUser(true);
  };

  const steps = [
    {
      number: 1,
      title: "Connect EMR",
      description: "Link OpenEMR, Epic, or any FHIR source to import patient records automatically.",
      tooltip: "Connecting your EMR enables automatic patient sync so RAF Intelligence always has up-to-date clinical data for scoring and gap detection.",
      icon: <Heart size={20} color={emrConnected ? "#10B981" : "#3B82F6"} />,
      ctaLabel: "Go to EMR Config",
      ctaHref: "/emr-config" as string | undefined,
      ctaAction: undefined as (() => void) | undefined,
      complete: emrConnected,
    },
    {
      number: 2,
      title: "Import / Sync Patients",
      description: "No EMR? Upload a CSV directly — or sync via your connected source.",
      tooltip: "Patient records are required before analysis can run. Import via FHIR sync or CSV upload to populate the roster.",
      icon: <Upload size={20} color={patientCount > 0 ? "#10B981" : "#8B5CF6"} />,
      ctaLabel: demoLoading ? "Connecting..." : "Try Demo Data",
      ctaHref: undefined as string | undefined,
      ctaAction: onTryDemo,
      complete: patientCount > 0,
    },
    {
      number: 3,
      title: "Run First Clinical Analysis",
      description: "Trigger an AI analysis run to score patients and surface HCC coding gaps.",
      tooltip: "The AI engine reads clinical notes, diagnoses, and vitals to assign RAF scores and identify HCC codes that may be missing or under-documented.",
      icon: <Database size={20} color={analysisRunCount > 0 ? "#10B981" : "#F59E0B"} />,
      ctaLabel: "Go to Analysis",
      ctaHref: "/analysis",
      ctaAction: undefined,
      complete: analysisRunCount > 0,
    },
    {
      number: 4,
      title: "Review First Gaps",
      description: "Open the review queue, attest or dismiss your first suggested gap.",
      tooltip: "Attesting a gap confirms the AI suggestion and queues it for coding submission to CMS. Dismissing it removes false positives from your workflow.",
      icon: <FileSearch size={20} color={attestationCount > 0 ? "#10B981" : "#EF4444"} />,
      ctaLabel: "Go to Review Queue",
      ctaHref: "/review-queue",
      ctaAction: undefined,
      complete: attestationCount > 0,
    },
    {
      number: 5,
      title: "Generate First Audit Package",
      description: "Bundle evidence into a HIPAA-ready audit package for your payer.",
      tooltip: "Audit packages compile clinical evidence, attestations, and HCC documentation into a single file you can submit to your payer or retain for CMS RADV audits.",
      icon: <Package size={20} color={auditPackageCount > 0 ? "#10B981" : "#6366F1"} />,
      ctaLabel: "Go to Audit",
      ctaHref: "/radv",
      ctaAction: undefined,
      complete: auditPackageCount > 0,
    },
  ];

  const allComplete = steps.every((s) => s.complete);

  // Hide once all complete AND user clicked Hide.
  if (hiddenByUser) return null;

  return (
    <TooltipProvider delay={200}>
    <div
      style={{
        ...card,
        padding: "28px 32px",
        marginBottom: 24,
        position: "relative",
      }}
      role="region"
      aria-label="Getting started checklist"
      data-testid={testId}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 22 }}>
        <div
          style={{
            background: "#EFF6FF",
            borderRadius: 10,
            padding: 10,
            border: "1px solid #BFDBFE",
            flexShrink: 0,
          }}
        >
          <BookOpen size={22} color="#3B82F6" />
        </div>
        <div style={{ flex: 1 }}>
          <h2 className="text-foreground text-base font-bold tracking-tight m-0">
            Get started — 5 steps to go live
          </h2>
          <p className="text-muted-foreground text-[12px] mt-0.5 mb-0">
            {allComplete
              ? "All steps complete. Your dashboard is fully set up."
              : `${steps.filter((s) => s.complete).length} of 5 complete`}
          </p>
        </div>
        {/* Hide button — always visible so user can dismiss at any time */}
        <button
          type="button"
          onClick={handleHide}
          aria-label="Hide checklist"
          title="Hide checklist"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 4,
            padding: "4px 10px",
            border: "1px solid #E2E8F0",
            borderRadius: 6,
            background: "#F8FAFC",
            color: "#64748B",
            fontSize: 12,
            fontWeight: 500,
            cursor: "pointer",
            flexShrink: 0,
          }}
        >
          <X size={12} />
          Hide
        </button>
      </div>

      {/* Progress bar */}
      <div
        style={{
          height: 4,
          borderRadius: 4,
          background: "#E2E8F0",
          marginBottom: 20,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            borderRadius: 4,
            background: allComplete ? "#10B981" : "#3B82F6",
            width: `${(steps.filter((s) => s.complete).length / 5) * 100}%`,
            transition: "width 0.4s ease",
          }}
        />
      </div>

      {/* Steps */}
      <div
        className="onboarding-steps"
        style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12 }}
      >
        <style>{`
          @media (max-width: 1100px) {
            .onboarding-steps { grid-template-columns: repeat(2, 1fr) !important; }
          }
          @media (max-width: 640px) {
            .onboarding-steps { grid-template-columns: 1fr !important; }
          }
        `}</style>
        {steps.map((s) => (
          <Tooltip key={s.number}>
            <TooltipTrigger
              style={{ background: "none", border: "none", padding: 0, textAlign: "left", cursor: "default" }}
              data-testid={`tooltip-onboarding-step-${s.number}`}
            >
          <div
            style={{
              background: s.complete ? "hsl(var(--success-soft))" : "hsl(var(--card))",
              border: s.complete ? "1px solid hsl(var(--success-base))" : "1px solid hsl(var(--border))",
              borderRadius: 10,
              padding: "16px 16px 14px",
              display: "flex",
              flexDirection: "column",
              gap: 8,
            }}
          >
            {/* Step number + icon */}
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div
                style={{
                  width: 26,
                  height: 26,
                  borderRadius: "50%",
                  background: s.complete ? "#10B981" : "#EFF6FF",
                  border: s.complete ? "none" : "1px solid #BFDBFE",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 12,
                  fontWeight: 700,
                  color: s.complete ? "#FFFFFF" : "#3B82F6",
                  flexShrink: 0,
                }}
              >
                {s.complete ? (
                  <CheckCircle size={14} color="#FFFFFF" strokeWidth={2.5} />
                ) : (
                  s.number
                )}
              </div>
              <div style={{ opacity: 0.75 }}>{s.icon}</div>
            </div>

            {/* Text */}
            <div>
              <div className="text-foreground text-xs font-bold mb-1 leading-snug">{s.title}</div>
              <div className="text-muted-foreground text-[11px] leading-snug">{s.description}</div>
            </div>

            {/* CTA / Done pill */}
            {s.complete ? (
              <div
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                  padding: "5px 10px",
                  borderRadius: 8,
                  background: "#D1FAE5",
                  color: "#065F46",
                  fontSize: 11,
                  fontWeight: 600,
                  width: "fit-content",
                  marginTop: "auto",
                }}
              >
                <CheckCircle size={11} strokeWidth={2.5} />
                Done
              </div>
            ) : s.ctaHref ? (
              <Link
                href={s.ctaHref}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 5,
                  marginTop: "auto",
                  padding: "7px 12px",
                  border: "1px solid #BFDBFE",
                  borderRadius: 8,
                  background: "#EFF6FF",
                  color: "#1D4ED8",
                  fontSize: 11,
                  fontWeight: 600,
                  textDecoration: "none",
                  width: "fit-content",
                }}
              >
                {s.ctaLabel}
                <ChevronRight size={11} />
              </Link>
            ) : (
              <button
                onClick={s.ctaAction}
                disabled={demoLoading}
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 5,
                  marginTop: "auto",
                  padding: "7px 12px",
                  border: "none",
                  borderRadius: 8,
                  background: "#FEF3C7",
                  color: "#92400E",
                  fontSize: 11,
                  fontWeight: 600,
                  cursor: demoLoading ? "wait" : "pointer",
                  width: "fit-content",
                  opacity: demoLoading ? 0.7 : 1,
                }}
              >
                {demoLoading ? (
                  <RefreshCw size={11} style={{ animation: "spin 1s linear infinite" }} />
                ) : (
                  <Play size={11} />
                )}
                {s.ctaLabel}
              </button>
            )}
          </div>
            </TooltipTrigger>
            <TooltipContent>{s.tooltip}</TooltipContent>
          </Tooltip>
        ))}
      </div>
    </div>
    </TooltipProvider>
  );
}
