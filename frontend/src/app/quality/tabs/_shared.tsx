"use client";

/**
 * Shared helpers for quality tab components.
 * Extracted so MeasuresTab, StarsTab, CareGapsTab can be lazy-loaded
 * via dynamic() without duplicating constants.
 */

import React from "react";
import { Star, AlertCircle, RefreshCw } from "lucide-react";
import { tokens } from "@/styles/tokens";
import type { CareGap } from "@/lib/api";

// ── Design tokens ─────────────────────────────────────────────────────────────
export const C = {
  bg:           tokens.slate50,
  card:         tokens.white,
  border:       tokens.slate200,
  borderLight:  tokens.slate100,
  text:         tokens.slate900,
  textMuted:    tokens.slate500,
  textSub:      tokens.slate400,
  primary:      tokens.primary,
  primaryLight: tokens.primarySoft,
  emerald:      tokens.success,
  emeraldLight: tokens.successSoft,
  emeraldDark:  tokens.successDark,
  amber:        tokens.warningStrong,
  amberLight:   tokens.warningSoft,
  amberDark:    tokens.warningText,
  red:          tokens.riskHigh,
  redLight:     tokens.riskHighSoft,
  redDark:      tokens.danger,
  blue:         tokens.infoBlue,
  violet:       tokens.accentPurple,
};

export const T = {
  card: {
    background: C.card,
    border: `1px solid ${C.border}`,
    borderRadius: 10,
    boxShadow: "0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.02)",
    padding: 24,
  } as React.CSSProperties,
};

export function starsColor(s: number): string {
  if (s >= 4.5) return tokens.success;
  if (s >= 3.5) return tokens.infoBlue;
  if (s >= 2.5) return tokens.warningStrong;
  if (s >= 1.5) return tokens.riskMedium;
  return tokens.riskHigh;
}

export function starsLabel(s: number): string {
  if (s >= 4.5) return "Excellent";
  if (s >= 3.5) return "Good";
  if (s >= 2.5) return "Average";
  if (s >= 1.5) return "Below Average";
  return "Poor";
}

export function complianceColor(r: number): string {
  if (r >= 80) return C.emerald;
  if (r >= 60) return C.amber;
  return C.red;
}

export function complianceBg(r: number): string {
  if (r >= 80) return C.emeraldLight;
  if (r >= 60) return C.amberLight;
  return C.redLight;
}

export function complianceTextColor(r: number): string {
  if (r >= 80) return C.emeraldDark;
  if (r >= 60) return C.amberDark;
  return C.redDark;
}

export function gapStatusStyle(status: CareGap["status"]): React.CSSProperties {
  if (status === "closed")
    return { background: C.emeraldLight, color: C.emeraldDark, padding: "2px 10px", borderRadius: 99, fontSize: 12, fontWeight: 600 };
  if (status === "excluded")
    return { background: C.amberLight, color: C.amberDark, padding: "2px 10px", borderRadius: 99, fontSize: 12, fontWeight: 600 };
  return { background: C.redLight, color: C.redDark, padding: "2px 10px", borderRadius: 99, fontSize: 12, fontWeight: 600 };
}

export function renderStars(rating: number) {
  const full = Math.floor(rating);
  const half = rating % 1 >= 0.5;
  const empty = 5 - full - (half ? 1 : 0);
  const goldFill = tokens.warningStrong;
  const goldStroke = tokens.riskMedium;
  const emptyFill = tokens.slate200;
  const emptyStroke = tokens.slate300;
  return (
    <div style={{ display: "flex", gap: 3, alignItems: "center" }}>
      {Array.from({ length: full }).map((_, i) => (
        <span key={`f${i}`} className="qs-star-icon" style={{ display: "inline-flex", filter: "drop-shadow(0 1px 2px rgba(245,158,11,0.4))", animationDelay: `${i * 0.08}s` }}>
          <Star size={20} fill={goldFill} color={goldStroke} strokeWidth={1.5} />
        </span>
      ))}
      {half && (
        <span className="qs-star-icon" style={{ position: "relative", display: "inline-flex", filter: "drop-shadow(0 1px 2px rgba(245,158,11,0.25))" }}>
          <Star size={20} color={emptyStroke} fill={emptyFill} strokeWidth={1.5} />
          <span style={{ position: "absolute", left: 0, top: 0, width: "50%", overflow: "hidden", display: "inline-flex" }}>
            <Star size={20} fill={goldFill} color={goldStroke} strokeWidth={1.5} />
          </span>
        </span>
      )}
      {Array.from({ length: empty }).map((_, i) => (
        <span key={`e${i}`} className="qs-star-icon" style={{ display: "inline-flex", opacity: 0.5 }}>
          <Star size={20} color={emptyStroke} fill={emptyFill} strokeWidth={1.5} />
        </span>
      ))}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "80px 0", color: C.textMuted }}>
      <div
        style={{
          width: 32,
          height: 32,
          border: `3px solid ${C.borderLight}`,
          borderTopColor: C.primary,
          borderRadius: "50%",
          animation: "qs-spin 0.8s linear infinite",
        }}
      />
      <p style={{ marginTop: 12, fontSize: 13 }}>{label ?? "Loading data..."}</p>
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "80px 0", color: C.red, gap: 12 }}>
      <AlertCircle size={32} />
      <p style={{ margin: 0, fontSize: 13 }}>{message ?? "Failed to load data."}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "8px 16px", border: `1px solid ${C.border}`, borderRadius: 8, background: C.card, color: C.textMuted, fontSize: 13, cursor: "pointer" }}
        >
          <RefreshCw size={14} />
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyRow({ colSpan, message }: { colSpan: number; message?: string }) {
  return (
    <tr>
      <td colSpan={colSpan} style={{ padding: "48px 16px", textAlign: "center", color: C.textSub, fontSize: 14 }}>
        {message ?? "No data available."}
      </td>
    </tr>
  );
}

export function StarsGauge({ rating }: { rating: number }) {
  const size = 180;
  const strokeWidth = 14;
  const radius = (size - strokeWidth) / 2;
  const sweepAngle = 240;
  const startAngle = 150;
  const fraction = Math.min(rating / 5, 1);
  const color = starsColor(rating);

  function polarToCart(cx: number, cy: number, r: number, angleDeg: number) {
    const rad = ((angleDeg - 90) * Math.PI) / 180;
    return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
  }

  const cx = size / 2;
  const cy = size / 2;

  function describeArc(startDeg: number, endDeg: number) {
    const s = polarToCart(cx, cy, radius, startDeg);
    const e = polarToCart(cx, cy, radius, endDeg);
    const large = endDeg - startDeg > 180 ? 1 : 0;
    return `M ${s.x} ${s.y} A ${radius} ${radius} 0 ${large} 1 ${e.x} ${e.y}`;
  }

  const trackEnd = startAngle + sweepAngle;
  const fillEnd = startAngle + sweepAngle * fraction;

  return (
    <div style={{ position: "relative", width: size, height: size }}>
      <svg width={size} height={size}>
        <defs>
          <linearGradient id={`gaugeGrad-${rating}`} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={color} stopOpacity={0.7} />
            <stop offset="50%" stopColor={color} />
            <stop offset="100%" stopColor={color} stopOpacity={0.85} />
          </linearGradient>
          <filter id={`gaugeShadow-${rating}`}>
            <feDropShadow dx="0" dy="0" stdDeviation="3" floodColor={color} floodOpacity="0.35" />
          </filter>
        </defs>
        <path d={describeArc(startAngle, trackEnd)} fill="none" stroke={C.borderLight} strokeWidth={strokeWidth} strokeLinecap="round" opacity={0.5} />
        {fraction > 0 && (
          <path
            className="qs-gauge-path"
            d={describeArc(startAngle, fillEnd)}
            fill="none"
            stroke={`url(#gaugeGrad-${rating})`}
            strokeWidth={strokeWidth}
            strokeLinecap="round"
            filter={`url(#gaugeShadow-${rating})`}
            style={{ transition: "all 0.8s ease" }}
          />
        )}
      </svg>
      <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", paddingTop: 16 }}>
        <div style={{ fontSize: 48, fontWeight: 800, color, lineHeight: 1, textShadow: `0 2px 12px ${color}40` }}>{(rating ?? 0).toFixed(1)}</div>
        <div style={{ fontSize: 13, fontWeight: 600, color, marginTop: 4, letterSpacing: "0.03em" }}>{starsLabel(rating)}</div>
        <div style={{ marginTop: 6 }}>{renderStars(rating)}</div>
      </div>
    </div>
  );
}
