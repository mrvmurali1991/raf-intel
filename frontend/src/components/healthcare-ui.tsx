"use client";

import React from "react";
import { ArrowUp, ArrowDown, ChevronLeft } from "lucide-react";
import Link from "next/link";

// ─── Design Tokens ───────────────────────────────────────────────────────────

const colors = {
  primary: "#2563EB",
  slate900: "#0F172A",
  slate600: "#475569",
  slate400: "#94A3B8",
  slate200: "#E2E8F0",
  slate100: "#F1F5F9",
  slate50: "#F8FAFC",
  white: "#FFFFFF",
  red600: "#DC2626",
  amber500: "#F59E0B",
  emerald500: "#10B981",
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
  value: string | number;
  subtitle?: string;
  icon?: React.ReactNode;
  trend?: { value: number; label: string };
  color?: string;
}

export function StatCard({ label, value, subtitle, icon, trend, color = colors.primary }: StatCardProps) {
  const cardStyle: React.CSSProperties = {
    background: colors.white,
    border: `1px solid ${colors.slate200}`,
    borderRadius: 12,
    padding: 20,
    display: "flex",
    flexDirection: "column",
    gap: 12,
  };

  const iconBg: React.CSSProperties = {
    width: 40,
    height: 40,
    borderRadius: 10,
    backgroundColor: `${color}1A`,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    color,
    flexShrink: 0,
  };

  return (
    <div style={cardStyle}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: 12, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: colors.slate400 }}>
          {label}
        </span>
        {icon && <div style={iconBg}>{icon}</div>}
      </div>
      <div>
        <div style={{ fontSize: 28, fontWeight: 700, color: colors.slate900, lineHeight: 1.1 }}>{value}</div>
        {subtitle && <div style={{ fontSize: 12, color: colors.subtleText, marginTop: 4 }}>{subtitle}</div>}
      </div>
      {trend && (
        <div style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 12 }}>
          {trend.value >= 0 ? (
            <ArrowUp size={14} style={{ color: colors.emerald500 }} />
          ) : (
            <ArrowDown size={14} style={{ color: colors.red600 }} />
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

  const style: React.CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 4,
    padding: "4px 10px",
    borderRadius: 999,
    fontSize: fontMap[size],
    fontWeight: 600,
    lineHeight: 1,
    backgroundColor: `${c}1A`,
    color: c,
    whiteSpace: "nowrap",
  };

  return <span style={style}>{label}</span>;
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
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
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
        <div style={{ fontSize: size * 0.28, fontWeight: 700, color: c, lineHeight: 1 }}>
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
          {showPercent && <span style={{ color: colors.slate900, fontWeight: 600 }}>{Math.round(clamped)}%</span>}
        </div>
      )}
      <div style={{ height, borderRadius: height, backgroundColor: colors.slate200, overflow: "hidden", width: "100%" }}>
        <div
          style={{
            height: "100%",
            width: `${clamped}%`,
            borderRadius: height,
            backgroundColor: color,
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
      <span style={{ fontSize: 12, fontWeight: 600, color: c }}>{pct}%</span>
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

export function MeatIndicator({ meat }: MeatIndicatorProps) {
  const letters = ["M", "E", "A", "T"] as const;

  return (
    <div style={{ display: "inline-flex", gap: 4 }}>
      {letters.map((l) => {
        const filled = meat ? !!meat[l] : false;
        const c = meatColors[l];
        return (
          <div
            key={l}
            title={filled && meat?.[l] ? meat[l] : `${l} not documented`}
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
              cursor: "default",
            }}
          >
            {l}
          </div>
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
        <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: colors.slate900 }}>{title}</h3>
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
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "48px 24px", textAlign: "center" }}>
      {icon && (
        <div style={{ width: 56, height: 56, borderRadius: 16, backgroundColor: colors.slate100, display: "flex", alignItems: "center", justifyContent: "center", color: colors.slate400, marginBottom: 16 }}>
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
  title: string;
  subtitle?: string;
  icon?: React.ReactNode;
  actions?: React.ReactNode;
  backHref?: string;
}

export function PageHeader({ title, subtitle, icon, actions, backHref }: PageHeaderProps) {
  return (
    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 24, gap: 16, flexWrap: "wrap" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {backHref && (
          <Link
            href={backHref}
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
