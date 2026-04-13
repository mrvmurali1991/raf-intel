"use client";

import React from "react";
import { ArrowUp, ArrowDown, ChevronLeft, Info, X } from "lucide-react";
import Link from "next/link";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";
import { tokens } from "@/styles/tokens";

// ─── Design Tokens (derived from shared tokens) ────────────────────────────

const colors = {
  primary: tokens.primary,
  slate900: tokens.slate900,
  slate600: tokens.slate600,
  slate400: tokens.slate400,
  slate200: tokens.slate200,
  slate100: tokens.slate100,
  slate50: tokens.slate50,
  white: tokens.white,
  red600: tokens.red600,
  amber500: tokens.amber500,
  emerald500: tokens.emerald500,
  gray400: tokens.gray400,
  gray200: tokens.gray200,
  subtleText: tokens.subtleText,
};

function riskColor(score: number | null): string {
  if (score === null) return colors.gray400;
  if (score >= 2.0) return colors.red600;
  if (score >= 1.0) return colors.amber500;
  if (score >= 0.5) return colors.emerald500;
  return colors.gray400;
}

function riskLabel(score: number | null): string {
  if (score === null) return "\u2014";
  if (score >= 2.0) return "High Risk";
  if (score >= 1.0) return "Medium";
  if (score >= 0.5) return "Low";
  return "Baseline";
}

// ─── 1. StatCard ─────────────────────────────────────────────────────────────

export interface StatCardProps {
  label: React.ReactNode;
  value: React.ReactNode;
  subtitle?: string;
  icon?: React.ReactNode;
  trend?: { value: number; label: string };
  color?: string;
  loading?: boolean;
  href?: string;
  info?: string;
}

export function StatCard({ label, value, subtitle, icon, trend, color = colors.primary, loading, href, info }: StatCardProps) {
  const [showInfo, setShowInfo] = React.useState(false);
  const infoId = React.useId();
  const iconBg: React.CSSProperties = {
    width: 44,
    height: 44,
    borderRadius: 12,
    backgroundColor: `${color}1A`,
    color,
  };

  if (loading) {
    return (
      <div
        className="animate-fade-in stat-card-gradient-border flex flex-col gap-3 rounded-3xl bg-white p-6"
        style={{
          border: `1px solid ${colors.slate200}`,
          boxShadow: "0 25px 50px -12px rgba(226, 232, 240, 0.5)",
        }}
      >
        <div className="flex items-center justify-between">
          <div className="skeleton" style={{ width: 80, height: 14, borderRadius: 6 }} />
          <div className="skeleton" style={{ width: 44, height: 44, borderRadius: 12 }} />
        </div>
        <div>
          <div className="skeleton" style={{ width: 100, height: 28, borderRadius: 8 }} />
          <div className="skeleton mt-2" style={{ width: 140, height: 12, borderRadius: 6 }} />
        </div>
      </div>
    );
  }

  const cardContent = (
    <div
      className="animate-fade-in hover-lift stat-card-gradient-border flex flex-col gap-3 rounded-3xl bg-white p-6"
      style={{
        border: `1px solid ${colors.slate200}`,
        boxShadow: "0 25px 50px -12px rgba(226, 232, 240, 0.5)",
        cursor: href ? "pointer" : undefined,
      }}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: colors.slate400 }}>
            {label}
          </span>
          {info && (
            <button
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); setShowInfo(!showInfo); }}
              className="flex items-center border-none bg-transparent p-0.5 transition-colors"
              style={{
                cursor: "pointer",
                color: showInfo ? color : colors.slate400,
              }}
              aria-label={`Info about ${label}`}
              aria-expanded={showInfo}
              aria-controls={infoId}
            >
              <Info size={14} />
            </button>
          )}
        </div>
        {icon && <div className="flex shrink-0 items-center justify-center" style={iconBg} aria-hidden="true">{icon}</div>}
      </div>
      {info && showInfo && (
        <div
          id={infoId}
          role="tooltip"
          className="relative mb-1 rounded-lg text-xs leading-relaxed"
          style={{
            background: colors.slate50, border: `1px solid ${colors.slate200}`,
            padding: "10px 14px", color: colors.slate600,
          }}
        >
          <button
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); setShowInfo(false); }}
            className="absolute right-1.5 top-1.5 flex border-none bg-transparent p-0.5"
            style={{ cursor: "pointer", color: colors.slate400 }}
          >
            <X size={12} />
          </button>
          {info}
        </div>
      )}
      <div>
        <div className="tabular-nums text-[28px] font-bold leading-none" style={{ color: colors.slate900 }}>{value}</div>
        {subtitle && <div className="mt-1 text-xs" style={{ color: colors.subtleText }}>{subtitle}</div>}
      </div>
      {trend && (
        <div className="flex items-center gap-1 text-xs">
          {trend.value >= 0 ? (
            <ArrowUp size={14} style={{ color: colors.emerald500 }} aria-hidden="true" />
          ) : (
            <ArrowDown size={14} style={{ color: colors.red600 }} aria-hidden="true" />
          )}
          <span className="font-semibold" style={{ color: trend.value >= 0 ? colors.emerald500 : colors.red600 }}>
            {trend.value >= 0 ? "+" : ""}
            {trend.value}%
          </span>
          <span style={{ color: colors.slate400 }}>{trend.label}</span>
        </div>
      )}
    </div>
  );

  if (href) {
    return <Link href={href} className="no-underline" style={{ color: "inherit" }}>{cardContent}</Link>;
  }
  return cardContent;
}

// ─── 2. RiskBadge ────────────────────────────────────────────────────────────

export interface RiskBadgeProps {
  score: number | null;
  size?: "sm" | "md" | "lg";
}

export function RiskBadge({ score, size = "md" }: RiskBadgeProps) {
  const c = riskColor(score);
  const label = riskLabel(score);
  const fontMap = { sm: 11, md: 12, lg: 14 };
  const isHighRisk = score !== null && score >= 2.0;
  const dotSize = size === "sm" ? 6 : size === "lg" ? 9 : 7;

  const style: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "4px 10px",
    borderRadius: 999,
    fontSize: fontMap[size],
    fontWeight: 600,
    lineHeight: 1,
    backgroundColor: `${c}1A`,
    color: c,
    whiteSpace: "nowrap",
  };

  const ariaLabel = score !== null
    ? `Risk level: ${label}, RAF score ${score.toFixed(3)}`
    : "Risk level: not scored";

  return (
    <Tooltip>
      <TooltipTrigger>
        <span style={style} className={isHighRisk ? "soft-pulse cursor-help" : "cursor-help"} aria-label={ariaLabel} role="status">
          <span
            style={{
              width: dotSize,
              height: dotSize,
              borderRadius: "50%",
              backgroundColor: c,
              flexShrink: 0,
            }}
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

export function RiskGauge({ score, size = 120, label = "RAF Score" }: RiskGaugeProps) {
  const c = riskColor(score);
  const strokeWidth = size * 0.08;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  // Map score 0-4 to 0-1 fraction for the arc
  const fraction = score !== null ? Math.min(score / 4, 1) : 0;
  const offset = circumference * (1 - fraction);

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }} role="img" aria-label={`RAF Score: ${score ?? 'Not scored'}`}>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke={colors.slate200} strokeWidth={strokeWidth} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={c}
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
        <div className="tabular-nums font-bold leading-none" style={{ fontSize: size * 0.28, color: c }}>
          {score !== null ? score.toFixed(2) : "\u2014"}
        </div>
      </div>
      <span className="text-xs font-medium" style={{ color: colors.slate400 }}>{label}</span>
    </div>
  );
}

// ─── 4. ProgressBar ──────────────────────────────────────────────────────────

export interface ProgressBarProps {
  value: number;
  label?: string;
  color?: string;
  showPercent?: boolean;
  height?: number;
}

export function ProgressBar({ value, label, color = colors.primary, showPercent = true, height = 6 }: ProgressBarProps) {
  const clamped = Math.max(0, Math.min(100, value));

  return (
    <div className="flex w-full flex-col gap-1">
      {(label || showPercent) && (
        <div className="flex justify-between text-xs">
          {label && <span style={{ color: colors.subtleText }}>{label}</span>}
          {showPercent && <span className="tabular-nums font-semibold" style={{ color: colors.slate900 }}>{Math.round(clamped)}%</span>}
        </div>
      )}
      <div
        className="w-full overflow-hidden"
        style={{ height, borderRadius: height, backgroundColor: colors.slate200 }}
        role="progressbar"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label}
      >
        <div
          className="progress-fill-animate"
          style={{
            height: "100%",
            width: `${clamped}%`,
            borderRadius: height,
            background: `linear-gradient(90deg, ${color}, ${color}CC, ${color})`,
            transition: "width 0.4s ease",
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

export function ConfidencePill({ value }: ConfidencePillProps) {
  const c = value >= 0.85 ? colors.emerald500 : value >= 0.7 ? colors.primary : value >= 0.5 ? colors.amber500 : colors.red600;
  const pct = Math.round(value * 100);

  return (
    <div className="inline-flex items-center gap-1.5">
      <div className="overflow-hidden" style={{ width: 48, height: 6, borderRadius: 3, backgroundColor: colors.slate200 }}>
        <div style={{ height: "100%", width: `${pct}%`, borderRadius: 3, backgroundColor: c, transition: "width 0.3s ease" }} />
      </div>
      <span className="tabular-nums text-xs font-semibold" style={{ color: c }}>{pct}%</span>
    </div>
  );
}

// ─── 6. MeatIndicator ────────────────────────────────────────────────────────

export interface MeatIndicatorProps {
  meat: { M?: string; E?: string; A?: string; T?: string } | null;
}

const meatColors: Record<string, string> = {
  M: tokens.primary,
  E: tokens.violet500,
  A: tokens.amber500,
  T: tokens.emerald500,
};

const meatTooltips: Record<string, string> = {
  M: "Monitoring — ongoing patient monitoring",
  E: "Evaluation — clinical evaluation performed",
  A: "Assessment — diagnosis assessment documented",
  T: "Treatment — treatment plan in place",
};

export function MeatIndicator({ meat }: MeatIndicatorProps) {
  const letters = ["M", "E", "A", "T"] as const;

  return (
    <div className="inline-flex gap-1">
      {letters.map((l) => {
        const filled = meat ? !!meat[l] : false;
        const c = meatColors[l];
        const detail = filled && meat?.[l] ? meat[l] : `${l} not documented`;
        const tooltipText = `${meatTooltips[l]}${filled ? ` — ${detail}` : " (not documented)"}`;
        return (
          <Tooltip key={l}>
            <TooltipTrigger>
              <div
                title={meatTooltips[l]}
                className="flex cursor-help items-center justify-center"
                style={{
                  width: 22,
                  height: 22,
                  borderRadius: 4,
                  fontSize: 11,
                  fontWeight: 700,
                  backgroundColor: filled ? `${c}1A` : "transparent",
                  color: filled ? c : colors.gray400,
                  border: filled ? `1.5px solid ${c}` : `1.5px solid ${colors.gray200}`,
                }}
              >
                {l}
              </div>
            </TooltipTrigger>
            <TooltipContent>{tooltipText}</TooltipContent>
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
    <div
      className="flex items-center justify-between py-2.5"
      style={{ borderBottom: `1px solid ${colors.slate100}` }}
    >
      <span className="text-[13px]" style={{ color: colors.subtleText }}>{label}</span>
      <span className="text-right text-[13px] font-semibold" style={{ color: colors.slate900 }}>{value}</span>
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
    <div className="mb-4 flex items-center justify-between">
      <div className="flex items-center gap-2">
        {icon && <span className="flex" style={{ color: colors.primary }}>{icon}</span>}
        <div className="flex flex-col">
          <h3 className="m-0 text-base font-bold" style={{ color: colors.slate900 }}>{title}</h3>
          <div
            className="mt-1 opacity-70"
            style={{
              width: 32,
              height: 3,
              borderRadius: 2,
              backgroundColor: colors.primary,
            }}
          />
        </div>
        {count !== undefined && (
          <span
            className="rounded-full text-[11px] font-semibold"
            style={{
              color: colors.primary,
              backgroundColor: `${colors.primary}1A`,
              padding: "2px 8px",
            }}
          >
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
      className="animate-fade-in flex flex-col items-center justify-center rounded-2xl text-center"
      style={{
        padding: "48px 24px",
        border: `2px dashed ${colors.gray200}`,
      }}
      role="status"
    >
      {icon && (
        <div
          className="animate-gentle-bounce mb-4 flex items-center justify-center"
          style={{
            width: 56,
            height: 56,
            borderRadius: 16,
            backgroundColor: colors.slate100,
            color: colors.slate400,
          }}
        >
          {icon}
        </div>
      )}
      <h4 className="m-0 text-[15px] font-semibold" style={{ color: colors.slate900 }}>{title}</h4>
      {description && <p className="mx-0 mt-2 max-w-xs leading-relaxed" style={{ fontSize: 13, color: colors.subtleText }}>{description}</p>}
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
    <div
      className="mb-6 flex flex-wrap items-start justify-between gap-4 pb-5"
      style={{ borderBottom: `1px solid ${colors.slate200}` }}
    >
      <div className="flex items-center gap-3">
        {backHref && (
          <Link
            href={backHref}
            className="hover-lift flex shrink-0 items-center justify-center no-underline"
            style={{
              width: 36,
              height: 36,
              borderRadius: 10,
              border: `1px solid ${colors.slate200}`,
              color: colors.slate600,
            }}
          >
            <ChevronLeft size={18} />
          </Link>
        )}
        {icon && (
          <div
            className="flex shrink-0 items-center justify-center"
            style={{
              width: 44,
              height: 44,
              borderRadius: 12,
              backgroundColor: `${colors.primary}1A`,
              color: colors.primary,
              boxShadow: `0 2px 8px ${colors.primary}20`,
            }}
          >
            {icon}
          </div>
        )}
        <div>
          <h1 className="m-0 text-h1" style={{ color: colors.slate900 }}>{title}</h1>
          {subtitle && <p className="mt-1 text-body-sm" style={{ margin: "4px 0 0", color: colors.subtleText }}>{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
