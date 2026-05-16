"use client";

import React from "react";
import { ArrowUp, ArrowDown, ChevronLeft, Info, X } from "lucide-react";
import Link from "next/link";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";

// ─── Design Tokens ───────────────────────────────────────────────────────────
//
// Literal-hex constants were removed in favor of semantic Tailwind classes
// driven by CSS variables in globals.css (--background, --foreground,
// --primary, --destructive, --warning, --muted-foreground, etc.).
//
// This keeps the component dark-mode safe, eliminates duplicate token sources,
// and improves color-blind accessibility (semantic classes pair with
// iconography rather than raw color).

/**
 * Returns a Tailwind class name for the score's semantic risk level.
 * Pair with iconography (▲ ● etc.) so color is never the sole signal.
 */
function riskColor(score: number | null): string {
  if (score === null) return "text-muted-foreground";
  if (score >= 2.0) return "text-destructive";
  if (score >= 1.0) return "text-warning";
  if (score >= 0.5) return "text-emerald-700";
  return "text-muted-foreground";
}

function riskLabel(score: number | null): string {
  if (score === null) return "—";
  if (score >= 2.0) return "High Risk";
  if (score >= 1.0) return "Medium";
  if (score >= 0.5) return "Low";
  return "Baseline";
}

/** Returns a short shape glyph for color-blind safe risk indicators. */
function riskGlyph(score: number | null): string {
  if (score === null) return "";
  if (score >= 2.0) return "▲"; // up-triangle for high
  if (score >= 1.0) return "●"; // dot for medium
  if (score >= 0.5) return "■"; // square for low
  return "";
}

// ─── 1. StatCard ─────────────────────────────────────────────────────────────

export interface StatCardEmptyState {
  /** Short friendly message shown instead of the bare value. */
  message: string;
  /** Label for the CTA button. When omitted only the message is shown. */
  ctaLabel?: string;
  /** href for the CTA link. Required when ctaLabel is provided. */
  ctaHref?: string;
}

export interface StatCardProps {
  label: string;
  value: React.ReactNode;
  subtitle?: string;
  icon?: React.ReactNode;
  trend?: { value: number; label: string };
  /**
   * @deprecated Pass a semantic Tailwind class via `accentClassName` instead.
   * Retained only so existing call sites compile; the value is ignored.
   */
  color?: string;
  /** Optional Tailwind class controlling the accent (icon tile, CTA). */
  accentClassName?: string;
  loading?: boolean;
  href?: string;
  info?: string;
  /**
   * When value is 0 / null / undefined AND this prop is provided the card
   * renders a friendly two-line empty-state layout with an optional CTA link
   * instead of the bare numeric value.
   */
  emptyState?: StatCardEmptyState;
}

/** Returns true when a value should trigger the empty-state layout. */
function isEmptyValue(value: React.ReactNode): boolean {
  if (value === null || value === undefined) return true;
  if (typeof value === "number") return value === 0;
  if (typeof value === "string") return value === "0" || value === "—" || value === "";
  return false;
}

export function StatCard({ label, value, subtitle, icon, trend, accentClassName = "text-primary bg-primary/10", loading, href, info, emptyState }: StatCardProps) {
  const [showInfo, setShowInfo] = React.useState(false);

  if (loading) {
    return (
      <div className="animate-fade-in stat-card-gradient-border bg-card border border-border rounded-3xl shadow-lg p-6 flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <div className="skeleton" style={{ width: 80, height: 14, borderRadius: 6 }} />
          <div className="skeleton" style={{ width: 44, height: 44, borderRadius: 12 }} />
        </div>
        <div>
          <div className="skeleton" style={{ width: 100, height: 28, borderRadius: 8 }} />
          <div className="skeleton" style={{ width: 140, height: 12, borderRadius: 6, marginTop: 8 }} />
        </div>
      </div>
    );
  }

  const cardContent = (
    <div
      className={`animate-fade-in hover-lift stat-card-gradient-border bg-card border border-border rounded-3xl shadow-lg p-6 flex flex-col gap-3 ${href ? "cursor-pointer" : ""}`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            {label}
          </span>
          {info && (
            <button
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); setShowInfo(!showInfo); }}
              className={`border-none bg-transparent cursor-pointer p-0.5 flex items-center transition-colors ${showInfo ? "text-primary" : "text-muted-foreground"}`}
              aria-label={`Info about ${label}`}
            >
              <Info size={14} />
            </button>
          )}
        </div>
        {icon && (
          <div
            className={`w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0 ${accentClassName}`}
            aria-hidden="true"
          >
            {icon}
          </div>
        )}
      </div>
      {info && showInfo && (
        <div className="bg-muted border border-border rounded-lg px-3.5 py-2.5 text-xs leading-relaxed text-muted-foreground relative mb-1">
          <button
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); setShowInfo(false); }}
            className="absolute top-1.5 right-1.5 border-none bg-transparent cursor-pointer text-muted-foreground p-0.5 flex"
          >
            <X size={12} />
          </button>
          {info}
        </div>
      )}
      {emptyState && isEmptyValue(value) ? (
        <div className="flex flex-col gap-1.5 pt-1">
          <div className="text-[13px] font-medium text-muted-foreground leading-snug">
            {emptyState.message}
          </div>
          {emptyState.ctaLabel && emptyState.ctaHref && (
            <Link
              href={emptyState.ctaHref}
              onClick={(e) => e.stopPropagation()}
              className={`inline-flex items-center gap-1 text-xs font-semibold no-underline px-2.5 py-1 rounded-md border w-fit transition-colors ${accentClassName} border-current/30`}
            >
              {emptyState.ctaLabel} &rarr;
            </Link>
          )}
        </div>
      ) : (
        <div>
          <div className="tabular-nums text-[28px] font-bold text-foreground leading-tight">{value}</div>
          {subtitle && <div className="text-xs text-muted-foreground mt-1">{subtitle}</div>}
        </div>
      )}
      {trend && (
        <div className="flex items-center gap-1 text-xs">
          {trend.value >= 0 ? (
            <ArrowUp size={14} className="text-emerald-700" aria-hidden="true" />
          ) : (
            <ArrowDown size={14} className="text-destructive" aria-hidden="true" />
          )}
          <span className={`font-semibold ${trend.value >= 0 ? "text-emerald-700" : "text-destructive"}`}>
            {trend.value >= 0 ? "+" : ""}
            {trend.value}%
          </span>
          <span className="text-muted-foreground">{trend.label}</span>
        </div>
      )}
    </div>
  );

  if (href) {
    return <Link href={href} className="no-underline text-inherit">{cardContent}</Link>;
  }
  return cardContent;
}

// ─── 2. RiskBadge ────────────────────────────────────────────────────────────

export interface RiskBadgeProps {
  score: number | null;
  size?: "sm" | "md" | "lg";
}

/** Background class paired with riskColor() so the dot/pill is also semantic. */
function riskBg(score: number | null): string {
  if (score === null) return "bg-muted-foreground/10";
  if (score >= 2.0) return "bg-destructive/10";
  if (score >= 1.0) return "bg-warning/15";
  if (score >= 0.5) return "bg-emerald-700/10";
  return "bg-muted-foreground/10";
}

function riskDotBg(score: number | null): string {
  if (score === null) return "bg-muted-foreground";
  if (score >= 2.0) return "bg-destructive";
  if (score >= 1.0) return "bg-warning";
  if (score >= 0.5) return "bg-emerald-700";
  return "bg-muted-foreground";
}

export function RiskBadge({ score, size = "md" }: RiskBadgeProps) {
  const colorClass = riskColor(score);
  const bgClass = riskBg(score);
  const dotBg = riskDotBg(score);
  const label = riskLabel(score);
  const glyph = riskGlyph(score);
  const fontMap = { sm: "text-[11px]", md: "text-xs", lg: "text-sm" } as const;
  const isHighRisk = score !== null && score >= 2.0;
  const dotSize = size === "sm" ? 6 : size === "lg" ? 9 : 7;

  return (
    <Tooltip>
      <TooltipTrigger>
        <span
          className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full font-semibold leading-none whitespace-nowrap ${fontMap[size]} ${colorClass} ${bgClass} ${isHighRisk ? "soft-pulse cursor-help" : "cursor-help"}`}
          aria-label={`Risk level: ${riskLabel(score)}, RAF score ${score?.toFixed(3) ?? "N/A"}`}
          role="status"
        >
          {/* Color-blind safety: glyph supplements color. */}
          {glyph && (
            <span aria-hidden="true" className="text-[0.85em] leading-none">{glyph}</span>
          )}
          <span
            className={`rounded-full flex-shrink-0 ${dotBg}`}
            style={{ width: dotSize, height: dotSize }}
            aria-hidden="true"
          />
          {label}
        </span>
      </TooltipTrigger>
      <TooltipContent>RAF Score: {score !== null ? score.toFixed(3) : "No Score"}</TooltipContent>
    </Tooltip>
  );
}

// ─── 3. RiskGauge ────────────────────────────────────────────────────────────

export interface RiskGaugeProps {
  score: number | null;
  size?: number;
  label?: string;
}

/** Raw stroke color for SVG circles. Returns CSS var() expression. */
function riskStroke(score: number | null): string {
  if (score === null) return "var(--muted-foreground)";
  if (score >= 2.0) return "var(--destructive)";
  if (score >= 1.0) return "var(--warning)";
  if (score >= 0.5) return "var(--color-emerald-700, #047857)";
  return "var(--muted-foreground)";
}

export function RiskGauge({ score, size = 120, label = "RAF Score" }: RiskGaugeProps) {
  const stroke = riskStroke(score);
  const colorClass = riskColor(score);
  const strokeWidth = size * 0.08;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  // Map score 0-4 to 0-1 fraction for the arc
  const fraction = score !== null ? Math.min(score / 4, 1) : 0;
  const offset = circumference * (1 - fraction);

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }} role="img" aria-label={`RAF Score: ${score ?? 'Not scored'}`}>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="var(--border)" strokeWidth={strokeWidth} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={stroke}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{ transition: "stroke-dashoffset 0.6s ease" }}
        />
      </svg>
      <div
        className="relative text-center"
        style={{
          marginTop: -size * 0.65,
          marginBottom: size * 0.65 - 40,
        }}
      >
        <div
          className={`tabular-nums font-bold leading-none ${colorClass}`}
          style={{ fontSize: size * 0.28 }}
        >
          {score !== null ? score.toFixed(2) : "—"}
        </div>
      </div>
      <span className="text-xs text-muted-foreground font-medium">{label}</span>
    </div>
  );
}

// ─── 4. ProgressBar ──────────────────────────────────────────────────────────

export interface ProgressBarProps {
  value: number;
  label?: string;
  /** Optional Tailwind background class for the fill, e.g. "bg-primary". */
  fillClassName?: string;
  /**
   * @deprecated Pass a Tailwind class via `fillClassName` instead. If a
   * literal CSS color is passed it is rendered via inline style as a fallback
   * so existing call sites continue to work without dark-mode regressions.
   */
  color?: string;
  showPercent?: boolean;
  height?: number;
}

export function ProgressBar({ value, label, fillClassName, color, showPercent = true, height = 6 }: ProgressBarProps) {
  const clamped = Math.max(0, Math.min(100, value));
  const useInlineColor = !fillClassName && !!color;
  const fillClass = fillClassName ?? (useInlineColor ? "" : "bg-primary");

  return (
    <div className="flex flex-col gap-1 w-full">
      {(label || showPercent) && (
        <div className="flex justify-between text-xs">
          {label && <span className="text-muted-foreground">{label}</span>}
          {showPercent && <span className="tabular-nums text-foreground font-semibold">{Math.round(clamped)}%</span>}
        </div>
      )}
      <div
        className="bg-muted overflow-hidden w-full"
        style={{ height, borderRadius: height }}
        role="progressbar"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label}
      >
        <div
          className={`progress-fill-animate h-full transition-[width] duration-300 ease-out ${fillClass}`}
          style={{
            width: `${clamped}%`,
            borderRadius: height,
            ...(useInlineColor ? { backgroundColor: color } : {}),
          }}
        />
      </div>
    </div>
  );
}

// ─── 5. ConfidencePill ───────────────────────────────────────────────────────

export interface ConfidencePillProps {
  value: number;
}

function confidenceClasses(value: number): { text: string; bg: string } {
  if (value >= 0.85) return { text: "text-emerald-700", bg: "bg-emerald-700" };
  if (value >= 0.7) return { text: "text-primary", bg: "bg-primary" };
  if (value >= 0.5) return { text: "text-warning", bg: "bg-warning" };
  return { text: "text-destructive", bg: "bg-destructive" };
}

export function ConfidencePill({ value }: ConfidencePillProps) {
  const { text, bg } = confidenceClasses(value);
  const pct = Math.round(value * 100);

  return (
    <div className="inline-flex items-center gap-1.5">
      <div className="w-12 h-1.5 rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full transition-[width] duration-300 ease-out ${bg}`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={`tabular-nums text-xs font-semibold ${text}`}>{pct}%</span>
    </div>
  );
}

// ─── 6. MeatIndicator ────────────────────────────────────────────────────────

export interface MeatIndicatorProps {
  meat: { M?: string; E?: string; A?: string; T?: string } | null;
}

const meatClasses: Record<string, { text: string; bg: string; border: string }> = {
  M: { text: "text-primary", bg: "bg-primary/10", border: "border-primary" },
  E: { text: "text-violet-600", bg: "bg-violet-600/10", border: "border-violet-600" },
  A: { text: "text-warning", bg: "bg-warning/15", border: "border-warning" },
  T: { text: "text-emerald-700", bg: "bg-emerald-700/10", border: "border-emerald-700" },
};

const meatLabels: Record<string, string> = {
  M: "Monitoring",
  E: "Evaluation",
  A: "Assessment",
  T: "Treatment",
};

export function MeatIndicator({ meat }: MeatIndicatorProps) {
  const letters = ["M", "E", "A", "T"] as const;

  return (
    <div className="inline-flex gap-1">
      {letters.map((l) => {
        const filled = meat ? !!meat[l] : false;
        const c = meatClasses[l];
        return (
          <Tooltip key={l}>
            <TooltipTrigger>
              <div
                className={`w-[22px] h-[22px] rounded flex items-center justify-center text-[11px] font-bold cursor-help border-[1.5px] ${
                  filled
                    ? `${c.text} ${c.bg} ${c.border}`
                    : "text-muted-foreground border-border bg-transparent"
                }`}
              >
                {l}
              </div>
            </TooltipTrigger>
            <TooltipContent>{meatLabels[l]}: {filled && meat?.[l] ? meat[l] : "Not documented"}</TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
}

// ─── 7. DataRow ──────────────────────────────────────────────────────────────

export interface DataRowProps {
  label: string;
  value: React.ReactNode;
}

export function DataRow({ label, value }: DataRowProps) {
  return (
    <div className="flex justify-between items-center py-2.5 border-b border-border">
      <span className="text-[13px] text-muted-foreground">{label}</span>
      <span className="text-[13px] font-semibold text-foreground text-right">{value}</span>
    </div>
  );
}

// ─── 8. SectionHeader ────────────────────────────────────────────────────────

export interface SectionHeaderProps {
  title: string;
  icon?: React.ReactNode;
  count?: number;
  action?: React.ReactNode;
}

export function SectionHeader({ title, icon, count, action }: SectionHeaderProps) {
  return (
    <div className="flex items-center justify-between mb-4">
      <div className="flex items-center gap-2">
        {icon && <span className="text-primary flex">{icon}</span>}
        <div className="flex flex-col">
          <h3 className="m-0 text-base font-bold text-foreground">{title}</h3>
          <div className="w-8 h-[3px] rounded-sm bg-primary mt-1 opacity-70" />
        </div>
        {count !== undefined && (
          <span className="text-[11px] font-semibold text-primary bg-primary/10 px-2 py-0.5 rounded-full">
            {count}
          </span>
        )}
      </div>
      {action && <div>{action}</div>}
    </div>
  );
}

// ─── 9. EmptyState ───────────────────────────────────────────────────────────

export interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
}

export function EmptyState({ icon, title, description }: EmptyStateProps) {
  return (
    <div
      className="animate-fade-in flex flex-col items-center justify-center px-6 py-12 text-center border-2 border-dashed border-border rounded-2xl"
      role="status"
    >
      {icon && (
        <div className="animate-gentle-bounce w-14 h-14 rounded-2xl bg-muted flex items-center justify-center text-muted-foreground mb-4">
          {icon}
        </div>
      )}
      <h4 className="m-0 text-[15px] font-semibold text-foreground">{title}</h4>
      {description && (
        <p className="mt-2 text-[13px] text-muted-foreground max-w-[320px] leading-relaxed">
          {description}
        </p>
      )}
    </div>
  );
}

// ─── 10. PageHeader ──────────────────────────────────────────────────────────

export interface PageHeaderProps {
  title: React.ReactNode;
  subtitle?: string;
  icon?: React.ReactNode;
  actions?: React.ReactNode;
  backHref?: string;
}

export function PageHeader({ title, subtitle, icon, actions, backHref }: PageHeaderProps) {
  return (
    <div className="flex items-start justify-between mb-6 pb-5 border-b border-border gap-4 flex-wrap">
      <div className="flex items-center gap-3">
        {backHref && (
          <Link
            href={backHref}
            className="hover-lift w-9 h-9 rounded-lg border border-border flex items-center justify-center text-muted-foreground no-underline flex-shrink-0"
          >
            <ChevronLeft size={18} />
          </Link>
        )}
        {icon && (
          <div className="w-11 h-11 rounded-xl bg-primary/10 flex items-center justify-center text-primary flex-shrink-0 shadow-sm">
            {icon}
          </div>
        )}
        <div>
          <h1 className="m-0 text-[22px] font-bold text-foreground leading-tight">{title}</h1>
          {subtitle && <p className="mt-1 mb-0 text-[13px] text-muted-foreground">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
