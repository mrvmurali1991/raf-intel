"use client";

import React from "react";
import { ArrowUp, ArrowDown, ChevronLeft, Info, X } from "lucide-react";
import Link from "next/link";
import { Tooltip, TooltipTrigger, TooltipContent } from "@/components/ui/tooltip";

// ─── Design Tokens ───────────────────────────────────────────────────────────

const colors = {
  primary: "#0f766e",
  slate900: "#0F172A",
  slate600: "#475569",
  slate400: "#94A3B8",
  slate200: "#f1f5f9",
  slate100: "#F1F5F9",
  slate50: "#F8FAFC",
  white: "#FFFFFF",
  red600: "#e11d48",
  amber500: "#d97706",
  emerald500: "#059669",
  gray400: "#9CA3AF",
  gray200: "#E5E7EB",
  subtleText: "#64748B",
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
  label: string;
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
  const iconBg: React.CSSProperties = {
    width: 44,
    height: 44,
    borderRadius: 12,
    backgroundColor: `${color}1A`,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    color,
    flexShrink: 0,
  };

  if (loading) {
    return (
      <div
        className="animate-fade-in stat-card-gradient-border"
        style={{
          background: colors.white,
          border: `1px solid ${colors.slate200}`,
          borderRadius: 24,
          boxShadow: "0 25px 50px -12px rgba(226, 232, 240, 0.5)",
          padding: 24,
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
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
      className="animate-fade-in hover-lift stat-card-gradient-border"
      style={{
        background: colors.white,
        border: `1px solid ${colors.slate200}`,
        borderRadius: 24,
        boxShadow: "0 25px 50px -12px rgba(226, 232, 240, 0.5)",
        padding: 24,
        display: "flex",
        flexDirection: "column",
        gap: 12,
        cursor: href ? "pointer" : undefined,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 12, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: colors.slate400 }}>
            {label}
          </span>
          {info && (
            <button
              onClick={(e) => { e.preventDefault(); e.stopPropagation(); setShowInfo(!showInfo); }}
              style={{
                border: "none", background: "none", cursor: "pointer", padding: 2,
                color: showInfo ? color : colors.slate400, display: "flex", alignItems: "center",
                transition: "color 0.15s",
              }}
              aria-label={`Info about ${label}`}
            >
              <Info size={14} />
            </button>
          )}
        </div>
        {icon && <div style={iconBg} aria-hidden="true">{icon}</div>}
      </div>
      {info && showInfo && (
        <div style={{
          background: "#F8FAFC", border: `1px solid ${colors.slate200}`, borderRadius: 10,
          padding: "10px 14px", fontSize: 12, lineHeight: 1.6, color: colors.slate600,
          position: "relative", marginBottom: 4,
        }}>
          <button
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); setShowInfo(false); }}
            style={{
              position: "absolute", top: 6, right: 6, border: "none", background: "none",
              cursor: "pointer", color: colors.slate400, padding: 2, display: "flex",
            }}
          >
            <X size={12} />
          </button>
          {info}
        </div>
      )}
      <div>
        <div className="tabular-nums" style={{ fontSize: 28, fontWeight: 700, color: colors.slate900, lineHeight: 1.1 }}>{value}</div>
        {subtitle && <div style={{ fontSize: 12, color: colors.subtleText, marginTop: 4 }}>{subtitle}</div>}
      </div>
      {trend && (
        <div style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
          {trend.value >= 0 ? (
            <ArrowUp size={14} style={{ color: colors.emerald500 }} aria-hidden="true" />
          ) : (
            <ArrowDown size={14} style={{ color: colors.red600 }} aria-hidden="true" />
          )}
          <span style={{ fontWeight: 600, color: trend.value >= 0 ? colors.emerald500 : colors.red600 }}>
            {trend.value >= 0 ? "+" : ""}
            {trend.value}%
          </span>
          <span style={{ color: colors.slate400 }}>{trend.label}</span>
        </div>
      )}
    </div>
  );

  if (href) {
    return <Link href={href} style={{ textDecoration: "none", color: "inherit" }}>{cardContent}</Link>;
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

  return (
    <Tooltip>
      <TooltipTrigger>
        <span style={style} className={isHighRisk ? "soft-pulse cursor-help" : "cursor-help"} aria-label={`Risk level: ${riskLabel(score)}, RAF score ${score?.toFixed(3) ?? "N/A"}`} role="status">
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
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
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
        style={{
          position: "relative",
          marginTop: -size * 0.65,
          marginBottom: size * 0.65 - 40,
          textAlign: "center",
        }}
      >
        <div className="tabular-nums" style={{ fontSize: size * 0.28, fontWeight: 700, color: c, lineHeight: 1 }}>
          {score !== null ? score.toFixed(2) : "\u2014"}
        </div>
      </div>
      <span style={{ fontSize: 12, color: colors.slate400, fontWeight: 500 }}>{label}</span>
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
    <div style={{ display: "flex", flexDirection: "column", gap: 4, width: "100%" }}>
      {(label || showPercent) && (
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
          {label && <span style={{ color: colors.subtleText }}>{label}</span>}
          {showPercent && <span className="tabular-nums" style={{ color: colors.slate900, fontWeight: 600 }}>{Math.round(clamped)}%</span>}
        </div>
      )}
      <div
        style={{ height, borderRadius: height, backgroundColor: colors.slate200, overflow: "hidden", width: "100%" }}
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
    <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <div style={{ width: 48, height: 6, borderRadius: 3, backgroundColor: colors.slate200, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${pct}%`, borderRadius: 3, backgroundColor: c, transition: "width 0.3s ease" }} />
      </div>
      <span className="tabular-nums" style={{ fontSize: 12, fontWeight: 600, color: c }}>{pct}%</span>
    </div>
  );
}

// ─── 6. MeatIndicator ────────────────────────────────────────────────────────

export interface MeatIndicatorProps {
  meat: { M?: string; E?: string; A?: string; T?: string } | null;
}

const meatColors: Record<string, string> = {
  M: colors.primary,
  E: "#8B5CF6",
  A: colors.amber500,
  T: colors.emerald500,
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
    <div style={{ display: "inline-flex", gap: 4 }}>
      {letters.map((l) => {
        const filled = meat ? !!meat[l] : false;
        const c = meatColors[l];
        return (
          <Tooltip key={l}>
            <TooltipTrigger>
              <div
                style={{
                  width: 22,
                  height: 22,
                  borderRadius: 4,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 11,
                  fontWeight: 700,
                  backgroundColor: filled ? `${c}1A` : "transparent",
                  color: filled ? c : colors.gray400,
                  border: filled ? `1.5px solid ${c}` : `1.5px solid ${colors.gray200}`,
                  cursor: "help",
                }}
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
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "10px 0",
        borderBottom: `1px solid ${colors.slate100}`,
      }}
    >
      <span style={{ fontSize: 13, color: colors.subtleText }}>{label}</span>
      <span style={{ fontSize: 13, fontWeight: 600, color: colors.slate900, textAlign: "right" }}>{value}</span>
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
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {icon && <span style={{ color: colors.primary, display: "flex" }}>{icon}</span>}
        <div style={{ display: "flex", flexDirection: "column" }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: colors.slate900 }}>{title}</h3>
          <div
            style={{
              width: 32,
              height: 3,
              borderRadius: 2,
              backgroundColor: colors.primary,
              marginTop: 4,
              opacity: 0.7,
            }}
          />
        </div>
        {count !== undefined && (
          <span
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: colors.primary,
              backgroundColor: `${colors.primary}1A`,
              padding: "2px 8px",
              borderRadius: 999,
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
      className="animate-fade-in"
      role="status"
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "48px 24px",
        textAlign: "center",
        border: `2px dashed ${colors.gray200}`,
        borderRadius: 16,
      }}
    >
      {icon && (
        <div
          className="animate-gentle-bounce"
          style={{
            width: 56,
            height: 56,
            borderRadius: 16,
            backgroundColor: colors.slate100,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: colors.slate400,
            marginBottom: 16,
          }}
        >
          {icon}
        </div>
      )}
      <h4 style={{ margin: 0, fontSize: 15, fontWeight: 600, color: colors.slate900 }}>{title}</h4>
      {description && <p style={{ margin: "8px 0 0", fontSize: 13, color: colors.subtleText, maxWidth: 320, lineHeight: 1.5 }}>{description}</p>}
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
      style={{
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "space-between",
        marginBottom: 24,
        paddingBottom: 20,
        borderBottom: `1px solid ${colors.slate200}`,
        gap: 16,
        flexWrap: "wrap",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {backHref && (
          <Link
            href={backHref}
            className="hover-lift"
            style={{
              width: 36,
              height: 36,
              borderRadius: 10,
              border: `1px solid ${colors.slate200}`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: colors.slate600,
              textDecoration: "none",
              flexShrink: 0,
            }}
          >
            <ChevronLeft size={18} />
          </Link>
        )}
        {icon && (
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: 12,
              backgroundColor: `${colors.primary}1A`,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: colors.primary,
              flexShrink: 0,
              boxShadow: `0 2px 8px ${colors.primary}20`,
            }}
          >
            {icon}
          </div>
        )}
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: colors.slate900, lineHeight: 1.2 }}>{title}</h1>
          {subtitle && <p style={{ margin: "4px 0 0", fontSize: 13, color: colors.subtleText }}>{subtitle}</p>}
        </div>
      </div>
      {actions && <div style={{ display: "flex", alignItems: "center", gap: 8 }}>{actions}</div>}
    </div>
  );
}
