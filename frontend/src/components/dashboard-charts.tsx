"use client";

import React, { useEffect, useRef, useState, useCallback, useId } from "react";
import { ArrowUp, ArrowDown, Download } from "lucide-react";

// ─── Design Tokens ───────────────────────────────────────────────────────────

const colors = {
  primary: "#0f766e",
  slate900: "#0F172A",
  slate600: "#475569",
  slate400: "#64748B",
  slate200: "#F1F5F9",
  white: "#FFFFFF",
  red: "#EF4444",
  amber: "#F59E0B",
  green: "#10B981",
  greenDark: "#059669",
  blue: "#3B82F6",
  subtleText: "#64748B",
  gray200: "#E5E7EB",
  gray400: "#9CA3AF",
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

function easeOut(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

function formatNumber(value: number): string {
  return Math.round(value).toLocaleString("en-US");
}

function formatCurrency(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(0)}K`;
  return `${sign}$${formatNumber(abs)}`;
}

function formatPercent(value: number): string {
  return `${Math.round(value)}%`;
}

function formatRaf(value: number): string {
  return value.toFixed(3);
}

// ─── 1. AnimatedNumber ───────────────────────────────────────────────────────

export interface AnimatedNumberProps {
  value: number;
  format?: "number" | "currency" | "percent" | "raf";
  duration?: number;
}

export function AnimatedNumber({ value, format = "number", duration = 600 }: AnimatedNumberProps) {
  const [display, setDisplay] = useState("0");
  const rafRef = useRef<number>(0);

  useEffect(() => {
    const start = performance.now();
    const formatter =
      format === "currency" ? formatCurrency
        : format === "percent" ? formatPercent
          : format === "raf" ? formatRaf
            : formatNumber;

    function tick(now: number) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      const current = value * easeOut(progress);
      setDisplay(formatter(current));
      if (progress < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        setDisplay(formatter(value));
      }
    }

    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [value, format, duration]);

  return <span className="tabular-nums">{display}</span>;
}

// ─── 2. Sparkline ────────────────────────────────────────────────────────────

export interface SparklineProps {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
  showArea?: boolean;
}

export function Sparkline({ data, width = 80, height = 28, color = colors.primary, showArea = false }: SparklineProps) {
  const reactId = useId();
  const pathId = `sparkline-${reactId.replace(/:/g, "")}`;

  if (!data || data.length === 0) {
    return <svg width={width} height={height} />;
  }

  if (data.length === 1) {
    return (
      <svg width={width} height={height}>
        <circle cx={width / 2} cy={height / 2} r={2} fill={color} />
      </svg>
    );
  }

  const padding = 2;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  const points = data.map((v, i) => ({
    x: padding + (i / (data.length - 1)) * (width - padding * 2),
    y: padding + (1 - (v - min) / range) * (height - padding * 2),
  }));

  // Build quadratic bezier path
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 0; i < points.length - 1; i++) {
    const curr = points[i];
    const next = points[i + 1];
    const mx = (curr.x + next.x) / 2;
    const my = (curr.y + next.y) / 2;
    if (i === 0) {
      d += ` Q ${curr.x} ${curr.y} ${mx} ${my}`;
    } else {
      d += ` Q ${curr.x} ${curr.y} ${mx} ${my}`;
    }
  }
  const last = points[points.length - 1];
  d += ` L ${last.x} ${last.y}`;

  const areaD = `${d} L ${last.x} ${height} L ${points[0].x} ${height} Z`;

  const pathLength = width * 2;

  return (
    <>
      <style>{`
        @keyframes sparkline-draw-${pathId} {
          from { stroke-dashoffset: ${pathLength}; }
          to { stroke-dashoffset: 0; }
        }
      `}</style>
      <svg width={width} height={height} style={{ overflow: "visible" }} role="img" aria-label={`Trend chart with ${data.length} data points`}>
        {showArea && (
          <path d={areaD} fill={color} opacity={0.15} />
        )}
        <path
          d={d}
          fill="none"
          stroke={color}
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeDasharray={pathLength}
          strokeDashoffset={0}
          style={{
            animation: `sparkline-draw-${pathId} 600ms ease-out forwards`,
          }}
        />
      </svg>
    </>
  );
}

// ─── 3. MiniBarChart ─────────────────────────────────────────────────────────

export interface MiniBarChartProps {
  data: Array<{ label: string; value: number; color: string }>;
  height?: number;
  showValues?: boolean;
  animate?: boolean;
}

export function MiniBarChart({ data, height = 24, showValues = true, animate = true }: MiniBarChartProps) {
  const [mounted, setMounted] = useState(!animate);

  useEffect(() => {
    if (animate) {
      const id = requestAnimationFrame(() => setMounted(true));
      return () => cancelAnimationFrame(id);
    }
  }, [animate]);

  if (!data || data.length === 0) return null;

  const maxValue = Math.max(...data.map((d) => d.value), 1);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, width: "100%" }} role="img" aria-label={`Bar chart: ${data.map(d => `${d.label} ${d.value}`).join(", ")}`}>
      {data.map((item, i) => {
        const pct = (item.value / maxValue) * 100;
        return (
          <div
            key={item.label}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              height,
            }}
          >
            <span
              style={{
                fontSize: 12,
                color: colors.subtleText,
                width: 80,
                flexShrink: 0,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {item.label}
            </span>
            <div
              style={{
                flex: 1,
                height: Math.max(height - 8, 8),
                backgroundColor: colors.slate200,
                borderRadius: 4,
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  height: "100%",
                  width: mounted ? `${pct}%` : "0%",
                  backgroundColor: item.color,
                  borderRadius: 4,
                  transition: `width 400ms ease-out ${i * 50}ms`,
                }}
              />
            </div>
            {showValues && (
              <span
                className="tabular-nums"
                style={{
                  fontSize: 12,
                  fontWeight: 600,
                  color: colors.slate900,
                  width: 40,
                  textAlign: "right",
                  flexShrink: 0,
                }}
              >
                {item.value}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── 4. WaterfallChart ───────────────────────────────────────────────────────

export interface WaterfallChartProps {
  data: Array<{ label: string; value: number; color?: string }>;
  totalLabel?: string;
  height?: number;
}

export function WaterfallChart({ data, totalLabel = "Total", height = 36 }: WaterfallChartProps) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const id = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(id);
  }, []);

  if (!data || data.length === 0) return null;

  const total = data.reduce((sum, d) => sum + d.value, 0);
  const maxValue = Math.max(...data.map((d) => Math.abs(d.value)), Math.abs(total), 1);
  const allItems = [...data, { label: totalLabel, value: total, color: colors.primary }];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, width: "100%" }} role="img" aria-label={`Waterfall chart: ${allItems.map(d => `${d.label} $${Math.abs(d.value).toLocaleString()}`).join(", ")}`}>
      {allItems.map((item, i) => {
        const isTotal = i === allItems.length - 1;
        const pct = (Math.abs(item.value) / maxValue) * 100;
        const barColor = isTotal
          ? colors.primary
          : item.color || (item.value >= 0 ? colors.green : colors.red);

        return (
          <div
            key={item.label}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              height,
            }}
          >
            <span
              style={{
                fontSize: 12,
                color: colors.subtleText,
                fontWeight: isTotal ? 700 : 400,
                width: 100,
                flexShrink: 0,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {item.label}
            </span>
            <div
              style={{
                flex: 1,
                height: Math.max(height - 12, 8),
                backgroundColor: colors.slate200,
                borderRadius: 4,
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  height: "100%",
                  width: mounted ? `${pct}%` : "0%",
                  borderRadius: 4,
                  background: isTotal
                    ? `linear-gradient(90deg, ${colors.primary}, ${colors.primary}CC)`
                    : item.value >= 0
                      ? `linear-gradient(90deg, ${colors.green}, ${colors.greenDark})`
                      : barColor,
                  transition: `width 400ms ease-out ${i * 100}ms`,
                }}
              />
            </div>
            <span
              className="tabular-nums"
              style={{
                fontSize: 12,
                fontWeight: isTotal ? 700 : 600,
                color: isTotal ? colors.slate900 : colors.subtleText,
                width: 60,
                textAlign: "right",
                flexShrink: 0,
              }}
            >
              {formatCurrency(item.value)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ─── 5. CircularGauge ────────────────────────────────────────────────────────

export interface CircularGaugeProps {
  value: number;
  size?: number;
  strokeWidth?: number;
  color?: string;
  label?: string;
}

export function CircularGauge({ value, size = 120, strokeWidth = 10, color = colors.primary, label }: CircularGaugeProps) {
  const [animatedValue, setAnimatedValue] = useState(0);
  const rafRef = useRef<number>(0);

  const clamped = Math.max(0, Math.min(100, value));
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - animatedValue / 100);

  useEffect(() => {
    const start = performance.now();
    function tick(now: number) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / 800, 1);
      setAnimatedValue(clamped * easeOut(progress));
      if (progress < 1) {
        rafRef.current = requestAnimationFrame(tick);
      }
    }
    rafRef.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafRef.current);
  }, [clamped]);

  return (
    <div style={{ position: "relative", width: size, height: size, display: "inline-flex", alignItems: "center", justifyContent: "center" }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)", position: "absolute" }} role="img" aria-label={`${label}: ${Math.round(clamped)}%`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={colors.slate200}
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
        />
      </svg>
      <div style={{ textAlign: "center", zIndex: 1 }}>
        <div className="tabular-nums" style={{ fontSize: size * 0.26, fontWeight: 700, color: colors.slate900, lineHeight: 1 }}>
          {Math.round(animatedValue)}
        </div>
        {label && (
          <div style={{ fontSize: Math.max(size * 0.09, 10), color: colors.slate400, fontWeight: 500, marginTop: 2 }}>
            {label}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── 6. TrendBadge ───────────────────────────────────────────────────────────

export interface TrendBadgeProps {
  value: number;
  label?: string;
  size?: "sm" | "md";
}

export function TrendBadge({ value, label, size = "md" }: TrendBadgeProps) {
  const isPositive = value >= 0;
  const c = isPositive ? colors.greenDark : colors.red;
  const bgColor = isPositive ? `${colors.green}1A` : `${colors.red}1A`;
  const fontSize = size === "sm" ? 11 : 12;
  const iconSize = size === "sm" ? 12 : 14;
  const py = size === "sm" ? 2 : 4;
  const px = size === "sm" ? 6 : 8;

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 3,
        padding: `${py}px ${px}px`,
        borderRadius: 999,
        backgroundColor: bgColor,
        color: c,
        fontSize,
        fontWeight: 600,
        lineHeight: 1,
        whiteSpace: "nowrap",
      }}
    >
      {isPositive ? <ArrowUp size={iconSize} /> : <ArrowDown size={iconSize} />}
      {isPositive ? "+" : ""}{value}%
      {label && <span style={{ color: colors.slate400, fontWeight: 400, marginLeft: 2 }}>{label}</span>}
    </span>
  );
}

// ─── 7. DateRangeSelector ────────────────────────────────────────────────────

export interface DateRangeSelectorProps {
  value: string;
  onChange: (range: string) => void;
  customStart?: string;
  customEnd?: string;
  onCustomChange?: (start: string, end: string) => void;
}

const dateRangeOptions = [
  { key: "30d", label: "30D" },
  { key: "90d", label: "90D" },
  { key: "ytd", label: "YTD" },
  { key: "1y", label: "1Y" },
  { key: "custom", label: "Custom" },
];

export function DateRangeSelector({ value, onChange, customStart, customEnd, onCustomChange }: DateRangeSelectorProps) {
  const [showCustom, setShowCustom] = useState(value === "custom");
  const [start, setStart] = useState(customStart || "");
  const [end, setEnd] = useState(customEnd || "");

  const handleClick = (key: string) => {
    if (key === "custom") {
      setShowCustom(true);
      onChange("custom");
    } else {
      setShowCustom(false);
      onChange(key);
    }
  };

  const handleDateChange = (newStart: string, newEnd: string) => {
    setStart(newStart);
    setEnd(newEnd);
    if (newStart && newEnd && onCustomChange) {
      onCustomChange(newStart, newEnd);
    }
  };

  return (
    <div style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
      <div
        style={{
          display: "inline-flex",
          borderRadius: 8,
          border: `1px solid ${colors.gray200}`,
          overflow: "hidden",
          backgroundColor: colors.white,
        }}
      >
        {dateRangeOptions.map((opt) => {
          const active = value === opt.key;
          return (
            <button
              key={opt.key}
              onClick={() => handleClick(opt.key)}
              style={{
                border: "none",
                cursor: "pointer",
                padding: "6px 14px",
                fontSize: 12,
                fontWeight: 600,
                lineHeight: 1,
                backgroundColor: active ? colors.primary : "transparent",
                color: active ? colors.white : colors.slate400,
                transition: "background-color 150ms ease, color 150ms ease",
              }}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
      {showCustom && (
        <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
          <input
            type="date"
            value={start}
            onChange={(e) => handleDateChange(e.target.value, end)}
            style={{
              padding: "5px 8px",
              fontSize: 12,
              borderRadius: 6,
              border: `1px solid ${colors.gray200}`,
              color: colors.slate900,
            }}
          />
          <span style={{ fontSize: 12, color: colors.slate400 }}>to</span>
          <input
            type="date"
            value={end}
            onChange={(e) => handleDateChange(start, e.target.value)}
            style={{
              padding: "5px 8px",
              fontSize: 12,
              borderRadius: 6,
              border: `1px solid ${colors.gray200}`,
              color: colors.slate900,
            }}
          />
        </div>
      )}
    </div>
  );
}

// ─── 8. ExportButton ─────────────────────────────────────────────────────────

export interface ExportButtonProps {
  onExport: () => void;
  label?: string;
}

export function ExportButton({ onExport, label = "Export" }: ExportButtonProps) {
  const [hovered, setHovered] = useState(false);

  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <button
        onClick={onExport}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        aria-label={label}
        style={{
          border: "none",
          cursor: "pointer",
          width: 32,
          height: 32,
          borderRadius: 8,
          backgroundColor: hovered ? colors.slate200 : "transparent",
          color: colors.gray400,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          transition: "background-color 150ms ease",
        }}
      >
        <Download size={15} />
      </button>
      {hovered && (
        <div
          style={{
            position: "absolute",
            bottom: "100%",
            left: "50%",
            transform: "translateX(-50%)",
            marginBottom: 6,
            padding: "4px 8px",
            borderRadius: 6,
            backgroundColor: colors.slate900,
            color: colors.white,
            fontSize: 11,
            fontWeight: 500,
            whiteSpace: "nowrap",
            pointerEvents: "none",
          }}
        >
          {label}
        </div>
      )}
    </div>
  );
}
