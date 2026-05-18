"use client";

/**
 * RiskSummaryCard — animated RAF risk summary with V24→V28 delta.
 *
 * Shows: current RAF, prior-year RAF, V24→V28 delta (color-coded),
 * dollar-at-stake estimate, and click-to-open V28 impact drawer.
 *
 * The count-up animation runs on first render (800 ms).
 * The final value is announced by an aria-live region so screen readers
 * receive the settled number, not the in-progress animation frames.
 *
 * Usage:
 *   <RiskSummaryCard pid={pid} rafScore={1.42} priorYearRaf={1.65} v28Delta={-0.23} onOpenV28Drawer={fn} />
 */

import React, { useEffect, useRef, useState } from "react";
import { TrendingDown, TrendingUp, DollarSign, ChevronRight } from "lucide-react";
import { C, rafScoreColor } from "./shared";
import type { ExtendedRafBreakdown } from "./shared";

// ---- count-up hook ----------------------------------------------------------

function useCountUp(target: number | null, durationMs = 800) {
  const [display, setDisplay] = useState<number | null>(target);
  const rafRef = useRef<number | null>(null);
  const startRef = useRef<number | null>(null);

  useEffect(() => {
    if (target === null) {
      setDisplay(null);
      return;
    }
    const start = performance.now();
    startRef.current = start;

    const tick = (now: number) => {
      const elapsed = now - (startRef.current ?? now);
      const progress = Math.min(elapsed / durationMs, 1);
      // Ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(target * eased);
      if (progress < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        setDisplay(target);
      }
    };

    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
    // Only animate when the target value first becomes available (mount) or changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target]);

  return display;
}

// ---- helpers ----------------------------------------------------------------

function fmt(n: number | null | undefined, decimals = 3): string {
  if (n == null) return "—";
  return Number(n).toFixed(decimals);
}

function fmtDollar(n: number | null | undefined): string {
  if (n == null) return "—";
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "+";
  return `${sign}$${abs.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

// CMS rough payment factor: ~$10,000 per 1.0 RAF per member per year
const RAF_TO_DOLLAR = 10_000;

// ---- sub-components ---------------------------------------------------------

function MetricCell({
  label,
  value,
  sub,
  color,
  bordered = true,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  color?: string;
  bordered?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
        alignItems: "center",
        padding: "0 20px",
        borderLeft: bordered ? `1px solid ${C.slate100}` : undefined,
        minWidth: 110,
      }}
    >
      <div
        className="text-muted-foreground"
        style={{
          fontSize: 10,
          fontWeight: 600,
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          marginBottom: 4,
          whiteSpace: "nowrap",
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 22,
          fontWeight: 800,
          color: color ?? undefined,
          fontFamily: "monospace",
          lineHeight: 1,
        }}
        className={color ? undefined : "text-foreground"}
      >
        {value}
      </div>
      {sub && (
        <div className="text-muted-foreground" style={{ marginTop: 3, fontSize: 11 }}>{sub}</div>
      )}
    </div>
  );
}

// ---- main component ---------------------------------------------------------

interface RiskSummaryCardProps {
  rafScore: number | null;
  breakdown?: ExtendedRafBreakdown;
  priorYearRaf?: number | null;
  v28Delta?: number | null;
  selectedYear: number;
  onOpenV28Drawer?: () => void;
}

export function RiskSummaryCard({
  rafScore,
  breakdown,
  priorYearRaf,
  v28Delta,
  selectedYear,
  onOpenV28Drawer,
}: RiskSummaryCardProps) {
  const animatedRaf = useCountUp(rafScore);
  const hccCount = breakdown?.hcc_details?.length ?? 0;

  // Dollar at stake = difference from threshold (1.0) × payment factor
  const dollarAtStake =
    rafScore != null ? Math.round((rafScore - 1.0) * RAF_TO_DOLLAR) : null;

  const deltaColor =
    v28Delta == null
      ? C.slate400
      : v28Delta >= 0
      ? C.emerald600
      : C.red600;

  const DeltaIcon =
    v28Delta == null ? null : v28Delta >= 0 ? TrendingUp : TrendingDown;

  // Announced value for screen readers — settles after animation
  const [announced, setAnnounced] = useState<string>("");
  useEffect(() => {
    if (rafScore == null) return;
    // Delay by animation duration so we announce the final value
    const t = setTimeout(() => {
      setAnnounced(`RAF score: ${Number(rafScore).toFixed(3)}`);
    }, 900);
    return () => clearTimeout(t);
  }, [rafScore]);

  return (
    <div
      className="bg-card border-b border-border"
      style={{
        display: "flex",
        alignItems: "center",
        overflowX: "auto",
        padding: "0 8px",
        minHeight: 84,
        gap: 0,
      }}
    >
      {/* Screen-reader live region announces settled RAF */}
      <div role="status" aria-live="polite" className="sr-only">
        {announced}
      </div>

      {/* 1. Animated RAF Score */}
      <MetricCell
        label={`RAF Score ${selectedYear}`}
        bordered={false}
        color={animatedRaf != null ? rafScoreColor(animatedRaf) : C.slate400}
        value={
          animatedRaf != null ? (
            <span
              className="tabular-nums"
              style={{
                textShadow:
                  animatedRaf != null
                    ? `0 0 20px ${rafScoreColor(animatedRaf)}33`
                    : "none",
              }}
            >
              {fmt(animatedRaf, 3)}
            </span>
          ) : (
            "—"
          )
        }
      />

      {/* 2. Prior year RAF */}
      <MetricCell
        label="Prior Year RAF"
        value={priorYearRaf != null ? fmt(priorYearRaf, 3) : "—"}
        color={priorYearRaf != null ? rafScoreColor(priorYearRaf) : C.slate400}
      />

      {/* 3. V24 → V28 delta — color-coded, click opens drawer */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          padding: "0 20px",
          borderLeft: `1px solid ${C.slate100}`,
          minWidth: 130,
          cursor: onOpenV28Drawer ? "pointer" : "default",
        }}
        role={onOpenV28Drawer ? "button" : undefined}
        tabIndex={onOpenV28Drawer ? 0 : undefined}
        aria-label={
          onOpenV28Drawer
            ? `V24 to V28 delta ${v28Delta != null ? fmt(v28Delta, 3) : "unavailable"}. Click to view per-HCC breakdown.`
            : undefined
        }
        onClick={onOpenV28Drawer}
        onKeyDown={(e) => {
          if (onOpenV28Drawer && (e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            onOpenV28Drawer();
          }
        }}
      >
        <div
          className="text-muted-foreground"
          style={{
            fontSize: 10,
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.05em",
            marginBottom: 4,
            whiteSpace: "nowrap",
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}
        >
          V24 → V28 Delta
          {onOpenV28Drawer && (
            <ChevronRight
              size={11}
              aria-hidden="true"
              className="text-muted-foreground"
            />
          )}
        </div>
        <div
          style={{
            fontSize: 22,
            fontWeight: 800,
            color: deltaColor,
            fontFamily: "monospace",
            lineHeight: 1,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          {DeltaIcon && (
            <DeltaIcon
              size={16}
              aria-hidden="true"
              style={{ color: deltaColor }}
            />
          )}
          {v28Delta != null ? fmt(v28Delta, 3) : "—"}
        </div>
        {v28Delta != null && (
          <div className="text-muted-foreground" style={{ marginTop: 3, fontSize: 10 }}>
            {v28Delta >= 0 ? "model improvement" : "model erosion"}
          </div>
        )}
      </div>

      {/* 4. HCC Count */}
      <MetricCell
        label="Active HCCs"
        value={hccCount}
        sub="conditions"
        color={C.slate900}
      />

      {/* 5. Dollar at stake */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          padding: "0 20px",
          borderLeft: `1px solid ${C.slate100}`,
          minWidth: 130,
        }}
      >
        <div
          className="text-muted-foreground"
          style={{
            fontSize: 10,
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.05em",
            marginBottom: 4,
            whiteSpace: "nowrap",
            display: "flex",
            alignItems: "center",
            gap: 3,
          }}
        >
          <DollarSign size={10} aria-hidden="true" />
          Est. Annual Revenue
        </div>
        <div
          style={{
            fontSize: 22,
            fontWeight: 800,
            color:
              dollarAtStake == null
                ? C.slate400
                : dollarAtStake >= 0
                ? C.emerald600
                : C.red600,
            fontFamily: "monospace",
            lineHeight: 1,
          }}
        >
          {fmtDollar(dollarAtStake)}
        </div>
        <div className="text-muted-foreground" style={{ marginTop: 3, fontSize: 10 }}>
          vs baseline
        </div>
      </div>
    </div>
  );
}
