"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import {
  BarChart3,
  Heart,
  Upload,
  Brain,
  FileBarChart,
  X,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Tour steps definition
// ---------------------------------------------------------------------------

const TOUR_STEPS = [
  {
    title: "Population Health Intelligence",
    body: "The dashboard shows your full patient population. KPI tiles at the top surface revenue opportunity, member count, analyzed patients, and average RAF score at a glance.",
    icon: <BarChart3 size={28} color="#3B82F6" />,
    cta: null as string | null,
    ctaHref: null as string | null,
  },
  {
    title: "Connect your EMR",
    body: "Go to EMR Config to connect OpenEMR, Epic, or any FHIR-compatible source. Once connected, patients sync automatically and analysis runs on the next scheduled cycle.",
    icon: <Heart size={28} color="#EF4444" />,
    cta: "Go to EMR Config",
    ctaHref: "/emr-config",
  },
  {
    title: "Upload a Patient CSV",
    body: "No EMR? Upload a CSV of patient records directly from the Uploads page. The system maps columns automatically and ingests data within minutes.",
    icon: <Upload size={28} color="#8B5CF6" />,
    cta: "Go to Uploads",
    ctaHref: "/uploads",
  },
  {
    title: "Run RAF Analysis",
    body: "After patients are loaded, trigger an analysis run from the Analysis page. The AI engine scores each patient, surfaces HCC coding gaps, and calculates revenue opportunity.",
    icon: <Brain size={28} color="#10B981" />,
    cta: "Go to Analysis",
    ctaHref: "/analysis",
  },
  {
    title: "Review Reports",
    body: "Explore the Reports section for per-patient scorecards, HCC gap lists, provider leaderboards, and CMS sweep deadline tracking.",
    icon: <FileBarChart size={28} color="#F59E0B" />,
    cta: "Go to Reports",
    ctaHref: "/reports",
  },
];

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface TourModalProps {
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TourModal({ onClose }: TourModalProps) {
  const [step, setStep] = useState(0);
  const router = useRouter();
  const overlayRef = useRef<HTMLDivElement>(null);
  const total = TOUR_STEPS.length;
  const current = TOUR_STEPS[step];

  const handleKey = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight" && step < total - 1) setStep((s) => s + 1);
      if (e.key === "ArrowLeft" && step > 0) setStep((s) => s - 1);
    },
    [step, total, onClose],
  );

  useEffect(() => {
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [handleKey]);

  return (
    <div
      ref={overlayRef}
      role="dialog"
      aria-modal="true"
      aria-label="Product tour"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15,23,42,0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 9998,
        backdropFilter: "blur(2px)",
      }}
      onClick={(e) => {
        if (e.target === overlayRef.current) onClose();
      }}
    >
      <div
        style={{
          background: "hsl(var(--card))",
          borderRadius: 14,
          padding: "36px 36px 28px",
          maxWidth: 480,
          width: "90%",
          boxShadow: "0 24px 64px rgba(0,0,0,0.18)",
          position: "relative",
        }}
      >
        {/* Close */}
        <button
          onClick={onClose}
          aria-label="Close tour"
          style={{
            position: "absolute",
            top: 16,
            right: 16,
            border: "none",
            background: "#F1F5F9",
            borderRadius: 8,
            padding: 6,
            cursor: "pointer",
            color: "#64748B",
            display: "flex",
            alignItems: "center",
          }}
        >
          <X size={16} />
        </button>

        {/* Step indicator */}
        <div style={{ display: "flex", gap: 6, marginBottom: 24 }}>
          {TOUR_STEPS.map((_, i) => (
            <button
              key={i}
              onClick={() => setStep(i)}
              aria-label={`Go to step ${i + 1}`}
              style={{
                flex: 1,
                height: 4,
                borderRadius: 2,
                border: "none",
                cursor: "pointer",
                background: i <= step ? "#3B82F6" : "#E2E8F0",
                transition: "background 0.2s",
                padding: 0,
              }}
            />
          ))}
        </div>

        {/* Icon */}
        <div
          style={{
            background: "#F8FAFC",
            borderRadius: 14,
            padding: 16,
            display: "inline-flex",
            marginBottom: 18,
            border: "1px solid #E2E8F0",
          }}
        >
          {current.icon}
        </div>

        {/* Content */}
        <div className="text-muted-foreground text-[11px] font-semibold tracking-widest uppercase mb-1.5">
          Step {step + 1} of {total}
        </div>
        <h3
          className="text-foreground text-[19px] font-bold tracking-tight"
          style={{ margin: "0 0 10px" }}
        >
          {current.title}
        </h3>
        <p
          className="text-muted-foreground text-sm leading-relaxed"
          style={{ margin: "0 0 24px" }}
        >
          {current.body}
        </p>

        {/* Nav */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 10,
          }}
        >
          <button
            onClick={() => setStep((s) => s - 1)}
            disabled={step === 0}
            className="text-muted-foreground text-[13px] font-medium border border-border bg-background rounded-lg px-[18px] py-[9px]"
            style={{ cursor: step === 0 ? "default" : "pointer", opacity: step === 0 ? 0.35 : 1 }}
          >
            Back
          </button>

          <div style={{ display: "flex", gap: 8 }}>
            {current.cta && current.ctaHref && (
              <button
                onClick={() => {
                  onClose();
                  router.push(current.ctaHref!);
                }}
                className="text-foreground text-[13px] font-semibold bg-muted border-0 rounded-lg px-[18px] py-[9px] cursor-pointer"
              >
                {current.cta}
              </button>
            )}
            {step < total - 1 ? (
              <button
                onClick={() => setStep((s) => s + 1)}
                className="text-white text-[13px] font-semibold bg-blue-500 border-0 rounded-lg px-5 py-[9px] cursor-pointer"
              >
                Next
              </button>
            ) : (
              <button
                onClick={onClose}
                className="text-white text-[13px] font-semibold bg-emerald-500 border-0 rounded-lg px-5 py-[9px] cursor-pointer"
              >
                Finish
              </button>
            )}
          </div>
        </div>

        <p className="text-muted-foreground/60 text-[11px] text-center mt-4 mb-0">
          Use arrow keys to navigate &middot; Esc to close
        </p>
      </div>
    </div>
  );
}
