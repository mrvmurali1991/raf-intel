"use client";

/**
 * ActionFeedback — satisfying visual celebration overlay for key clinical actions.
 *
 * Renders as a fixed, pointer-events-none overlay (z-50) so the underlying page
 * stays fully interactive while the animation plays. Calls onDone() and removes
 * itself from the DOM after the animation completes.
 *
 * Usage examples:
 *
 *   // After accepting a HCC suspect
 *   <ActionFeedback
 *     show={accepted}
 *     type="success"
 *     title="Suspect Accepted"
 *     onDone={() => setAccepted(false)}
 *   />
 *
 *   // After closing a care gap (with revenue impact)
 *   <ActionFeedback
 *     show={gapClosed}
 *     type="revenue"
 *     title="Revenue Captured"
 *     detail="HCC 19 — Diabetes, type 2"
 *     revenue={3200}
 *     onDone={() => setGapClosed(false)}
 *   />
 *
 *   // After reaching a workflow milestone
 *   <ActionFeedback
 *     show={milestone}
 *     type="milestone"
 *     title="All Gaps Closed"
 *     detail="100 suspects reviewed this month"
 *     onDone={() => setMilestone(false)}
 *   />
 */

import * as React from "react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface ActionFeedbackProps {
  /** When true the animation mounts and begins; set to false to reset. */
  show: boolean;
  /** Visual treatment to render. */
  type: "success" | "revenue" | "milestone";
  /** Primary label shown below the icon / number. */
  title: string;
  /** Optional secondary line (condition name, milestone description, etc.) */
  detail?: string;
  /**
   * Dollar amount for the "revenue" type.
   * Counts up from $0 to this value over ~900 ms.
   */
  revenue?: number;
  /** Called once after the exit-fade animation fully completes. */
  onDone?: () => void;
}

// ---------------------------------------------------------------------------
// Timing constants (ms) — drives both CSS animation durations and JS timers
// ---------------------------------------------------------------------------

const DURATIONS = {
  success: 2000,
  revenue: 2500,
  milestone: 3000,
} as const;

// How long the exit fade takes (must match @keyframes af-fade-out duration)
const FADE_OUT_MS = 400;

// ---------------------------------------------------------------------------
// Count-up hook (reused from RevenueDisplay pattern in the codebase)
// ---------------------------------------------------------------------------

function useCountUp(target: number, enabled: boolean): number {
  const [display, setDisplay] = React.useState(0);
  const rafRef = React.useRef<number | null>(null);
  const firedRef = React.useRef(false);

  React.useEffect(() => {
    if (!enabled) {
      setDisplay(0);
      firedRef.current = false;
      return;
    }
    if (firedRef.current) return;
    firedRef.current = true;

    const duration = 900;
    const start = performance.now();

    function step(now: number) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      // ease-out cubic: 1 - (1 - t)³
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(Math.round(target * eased));
      if (progress < 1) {
        rafRef.current = requestAnimationFrame(step);
      } else {
        setDisplay(target);
      }
    }

    rafRef.current = requestAnimationFrame(step);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [target, enabled]);

  return display;
}

// ---------------------------------------------------------------------------
// Confetti particles — 5 small colored dots that float upward and fade
// ---------------------------------------------------------------------------

interface ParticleConfig {
  color: string;
  /** horizontal offset from centre, in px */
  dx: number;
  /** animation delay in ms */
  delay: number;
  /** random size multiplier */
  size: number;
}

const PARTICLES: ParticleConfig[] = [
  { color: "#10b981", dx: -48, delay: 0,   size: 8 },
  { color: "#3b82f6", dx:  28, delay: 80,  size: 6 },
  { color: "#f59e0b", dx: -18, delay: 40,  size: 7 },
  { color: "#8b5cf6", dx:  52, delay: 120, size: 5 },
  { color: "#ec4899", dx:   4, delay: 60,  size: 6 },
];

function Particles({ active }: { active: boolean }) {
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
      {PARTICLES.map((p, i) => (
        <span
          key={i}
          className={cn(
            "absolute bottom-1/2 left-1/2 rounded-full",
            active ? "animate-[af-particle_700ms_ease-out_forwards]" : "opacity-0",
          )}
          style={{
            width: p.size,
            height: p.size,
            backgroundColor: p.color,
            marginLeft: p.dx,
            animationDelay: `${p.delay}ms`,
          }}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Success variant — spring-scale circle + SVG checkmark draw
// ---------------------------------------------------------------------------

function SuccessAnimation() {
  return (
    <div className="flex flex-col items-center gap-4">
      {/* Circle scales in with spring overshoot */}
      <div
        aria-hidden="true"
        className="flex h-20 w-20 items-center justify-center rounded-full
                   bg-emerald-500 dark:bg-emerald-400
                   shadow-[0_0_32px_rgba(16,185,129,0.45)]
                   animate-[af-spring-in_500ms_cubic-bezier(0.34,1.56,0.64,1)_forwards]"
      >
        {/* Checkmark: stroke-dasharray animation draws the path */}
        <svg
          viewBox="0 0 40 40"
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="h-10 w-10"
          aria-hidden="true"
        >
          <polyline
            points="8,20 17,29 32,12"
            stroke="white"
            strokeWidth="3.5"
            strokeDasharray="40"
            strokeDashoffset="40"
            className="animate-[af-draw-check_380ms_ease-out_200ms_forwards]"
          />
        </svg>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Revenue variant — animated dollar amount + confetti particles
// ---------------------------------------------------------------------------

function RevenueAnimation({ revenue }: { revenue: number }) {
  const count = useCountUp(revenue, true);
  const formatted = `+$${count.toLocaleString("en-US")}`;

  return (
    <div className="relative flex flex-col items-center gap-3">
      <Particles active />

      {/* Dollar icon badge */}
      <div
        aria-hidden="true"
        className="flex h-16 w-16 items-center justify-center rounded-full
                   bg-emerald-500 dark:bg-emerald-400
                   shadow-[0_0_28px_rgba(16,185,129,0.40)]
                   animate-[af-spring-in_450ms_cubic-bezier(0.34,1.56,0.64,1)_forwards]"
      >
        {/* Inline dollar-circle SVG — no external icon dependency */}
        <svg viewBox="0 0 24 24" fill="none" className="h-8 w-8" aria-hidden="true">
          <path
            d="M12 2v2m0 16v2M8.5 7.5C8.5 6.12 10.07 5 12 5s3.5 1.12 3.5 2.5
               c0 1.38-1.57 2.5-3.5 2.5s-3.5 1.12-3.5 2.5C8.5 13.88 10.07 15 12 15
               s3.5-1.12 3.5-2.5"
            stroke="white"
            strokeWidth="2"
            strokeLinecap="round"
          />
        </svg>
      </div>

      {/* Counted-up revenue text */}
      <span
        className="tabular-nums font-bold text-3xl text-emerald-600 dark:text-emerald-400
                   animate-[af-scale-up_350ms_cubic-bezier(0.34,1.56,0.64,1)_150ms_both]"
        aria-live="polite"
        aria-atomic="true"
      >
        {formatted}
      </span>

      <span className="text-sm font-medium text-muted-foreground animate-[af-fade-in_300ms_ease_400ms_both]">
        captured
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Milestone variant — trophy icon with glow + pulse ring
// ---------------------------------------------------------------------------

function MilestoneAnimation() {
  return (
    <div className="flex flex-col items-center gap-4">
      {/* Outer pulse ring */}
      <div className="relative flex items-center justify-center">
        <span
          aria-hidden="true"
          className="absolute h-28 w-28 rounded-full bg-amber-400/20 dark:bg-amber-500/15
                     animate-[af-pulse-ring_1.4s_ease-out_300ms_2]"
        />
        {/* Trophy badge */}
        <div
          aria-hidden="true"
          className="relative flex h-20 w-20 items-center justify-center rounded-full
                     bg-gradient-to-br from-amber-400 to-amber-600
                     shadow-[0_0_36px_rgba(245,158,11,0.55)]
                     animate-[af-spring-in_500ms_cubic-bezier(0.34,1.56,0.64,1)_forwards]"
        >
          {/* Trophy cup SVG */}
          <svg viewBox="0 0 24 24" fill="none" className="h-10 w-10" aria-hidden="true">
            <path
              d="M8 21h8M12 17v4M7 4H5a2 2 0 0 0-2 2v1a4 4 0 0 0 4 4h10
                 a4 4 0 0 0 4-4V6a2 2 0 0 0-2-2h-2"
              stroke="white"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <rect x="7" y="2" width="10" height="11" rx="2"
              stroke="white"
              strokeWidth="2"
              strokeLinejoin="round"
            />
          </svg>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ActionFeedback
// ---------------------------------------------------------------------------

export function ActionFeedback({
  show,
  type,
  title,
  detail,
  revenue = 0,
  onDone,
}: ActionFeedbackProps) {
  // "mounted" = in the DOM; "exiting" = playing the exit fade
  const [mounted, setMounted] = React.useState(false);
  const [exiting, setExiting] = React.useState(false);
  const holdTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const exitTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(() => {
    if (show) {
      // Reset and mount fresh
      setExiting(false);
      setMounted(true);

      const holdMs = DURATIONS[type];

      holdTimer.current = setTimeout(() => {
        setExiting(true);
        exitTimer.current = setTimeout(() => {
          setMounted(false);
          setExiting(false);
          onDone?.();
        }, FADE_OUT_MS);
      }, holdMs);
    } else {
      // Caller turned show off externally — immediately tear down
      if (holdTimer.current) clearTimeout(holdTimer.current);
      if (exitTimer.current) clearTimeout(exitTimer.current);
      setMounted(false);
      setExiting(false);
    }

    return () => {
      if (holdTimer.current) clearTimeout(holdTimer.current);
      if (exitTimer.current) clearTimeout(exitTimer.current);
    };
  }, [show, type, onDone]);

  if (!mounted) return null;

  return (
    <>
      {/* ------------------------------------------------------------------ */}
      {/* Keyframe definitions — injected once via a <style> tag so they are  */}
      {/* colocated with the component and need no globals.css edit.           */}
      {/* ------------------------------------------------------------------ */}
      <style>{`
        @keyframes af-spring-in {
          0%   { opacity: 0; transform: scale(0); }
          100% { opacity: 1; transform: scale(1); }
        }
        @keyframes af-scale-up {
          0%   { opacity: 0; transform: scale(0.6); }
          100% { opacity: 1; transform: scale(1); }
        }
        @keyframes af-fade-in {
          from { opacity: 0; transform: translateY(4px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes af-fade-out {
          from { opacity: 1; }
          to   { opacity: 0; }
        }
        @keyframes af-draw-check {
          to { stroke-dashoffset: 0; }
        }
        @keyframes af-particle {
          0%   { opacity: 1; transform: translate(-50%, 0); }
          80%  { opacity: 0.6; }
          100% { opacity: 0; transform: translate(-50%, -80px) scale(0.5); }
        }
        @keyframes af-pulse-ring {
          0%   { transform: scale(0.85); opacity: 0.7; }
          70%  { transform: scale(1.15); opacity: 0.25; }
          100% { transform: scale(1.25); opacity: 0; }
        }
        @keyframes af-content-in {
          0%   { opacity: 0; transform: translateY(8px) scale(0.97); }
          100% { opacity: 1; transform: translateY(0) scale(1); }
        }
        @media (prefers-reduced-motion: reduce) {
          [class*="animate-[af-"] {
            animation: none !important;
            opacity: 1 !important;
          }
        }
      `}</style>

      {/*
        Fixed overlay: pointer-events-none so users can continue clicking
        the page while the animation plays.
      */}
      <div
        role="status"
        aria-live="assertive"
        aria-atomic="true"
        aria-label={title}
        className={cn(
          // Layout — centered, full-screen, non-blocking
          "fixed inset-0 z-50 flex items-center justify-center pointer-events-none",
          // Semi-transparent backdrop (very subtle — non-blocking feel)
          "bg-black/[0.06] dark:bg-black/[0.18]",
          exiting
            ? "animate-[af-fade-out_400ms_ease_forwards]"
            : "animate-[af-fade-in_200ms_ease_forwards]",
        )}
      >
        {/*
          Content card — pointer-events-auto so it is selectable, but
          sits in the centre without occluding the page edges.
        */}
        <div
          className={cn(
            "pointer-events-auto relative flex flex-col items-center gap-5 px-10 py-8",
            "rounded-2xl border border-border/60 bg-card/95 shadow-xl backdrop-blur-sm",
            "min-w-[220px] max-w-xs text-center",
            "animate-[af-content-in_300ms_cubic-bezier(0.34,1.56,0.64,1)_forwards]",
          )}
        >
          {/* Per-type animation */}
          {type === "success" && <SuccessAnimation />}
          {type === "revenue" && <RevenueAnimation revenue={revenue} />}
          {type === "milestone" && <MilestoneAnimation />}

          {/* Title */}
          <p
            className={cn(
              "font-semibold leading-tight text-foreground",
              type === "milestone" ? "text-lg" : "text-base",
              "animate-[af-fade-in_300ms_ease_250ms_both]",
            )}
          >
            {title}
          </p>

          {/* Optional detail line */}
          {detail && (
            <p className="text-sm text-muted-foreground leading-snug -mt-2 animate-[af-fade-in_300ms_ease_350ms_both]">
              {detail}
            </p>
          )}
        </div>
      </div>
    </>
  );
}

export default ActionFeedback;
