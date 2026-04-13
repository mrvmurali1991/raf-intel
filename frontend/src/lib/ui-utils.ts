import { tokens } from "@/styles/tokens";

export const C = {
  text: tokens.slate900,
  textMuted: tokens.slate600,
  textSubtle: tokens.slate500,
  label: tokens.slate400,
  border: tokens.slate200,
  borderSoft: "#EEF2F6",
  rowDivider: tokens.slate100,
  bgPage: tokens.slate50,
  bgCard: tokens.white,
  bgSubtle: tokens.slate50,
  bgBand: "#FAFBFC",
  bgBandHover: tokens.slate100,
  brand: "#0F766E",
  brandDark: "#134E4A",
  brandSoft: "rgba(15, 118, 110, 0.06)",
  brandRing: "rgba(15, 118, 110, 0.18)",
  high: tokens.riskHigh,
  medium: tokens.riskMedium,
  low: tokens.riskLow,
  highSoft: tokens.riskHighSoft,
  mediumSoft: tokens.riskMediumSoft,
  lowSoft: tokens.riskLowSoft,
  blue: "#0EA5E9",
  blueSoft: "rgba(14, 165, 233, 0.10)",
  white: "#FFFFFF",
} as const;

export const FONT_SYS =
  '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, Roboto, Helvetica, Arial, sans-serif';
export const FONT_MONO =
  'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Monaco, Consolas, monospace';

const AVATAR_COLORS = [
  "#2563EB", "#7C3AED", "#DB2777", "#0EA5E9",
  "#9333EA", "#0891B2", "#4F46E5", "#0D9488",
  "#0F766E", "#7C3AED", "#1D4ED8", "#0369A1",
];

export function initialsColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
}

export function deriveInitials(
  firstName?: string | null,
  lastName?: string | null,
  pid?: string | number | null,
): string {
  const f = (firstName || "").trim();
  const l = (lastName || "").trim();
  const a = f ? f[0] : "";
  const b = l ? l[0] : "";
  const out = (a + b).toUpperCase();
  if (out) return out;
  const pidStr = pid != null ? String(pid).replace(/\D/g, "") : "";
  if (pidStr) return pidStr.slice(-2).padStart(2, "0");
  return "\u2022";
}

export function riskAccentColor(score: number | null | undefined): string {
  if (score == null || score === 0) return C.borderSoft;
  if (score >= 2.0) return C.high;
  if (score >= 1.0) return C.medium;
  if (score >= 0.5) return C.low;
  return C.borderSoft;
}

export function riskTone(score: number | null | undefined): { fg: string; bg: string; label: string } {
  if (score == null || score === 0) return { fg: C.label, bg: "#F1F5F9", label: "Unscored" };
  if (score >= 2.0) return { fg: C.high, bg: C.highSoft, label: "High" };
  if (score >= 1.0) return { fg: C.medium, bg: C.mediumSoft, label: "Medium" };
  return { fg: C.low, bg: C.lowSoft, label: "Low" };
}
