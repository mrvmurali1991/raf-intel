"use client";

/**
 * ROI Calculator
 *
 * perf(rsc): RafBarChart extracted to RafBarChart.tsx and lazy-loaded via
 * dynamic({ ssr: false }). The component uses SVG <animate> elements that are
 * below-the-fold and not needed for initial render.
 *
 * NOTE: The original task mentioned recharts (150kb) but this file uses a
 * custom SVG bar chart with zero recharts imports. No recharts was found.
 * If recharts is added in the future, wrap it with dynamic({ ssr: false }).
 */

import { useState, useEffect, useCallback, useRef } from "react";
import dynamic from "next/dynamic";
import {
  Calculator,
  DollarSign,
  TrendingUp,
  Users,
  Download,
  Share2,
  CheckCircle,
  Zap,
  Star,
  ArrowRight,
  Building2,
  Activity,
  Target,
  Clock,
  ChevronRight,
} from "lucide-react";
import { PageHeader } from "@/components/healthcare-ui";
import { fmtCurrencyCompact, fmtCurrencyFull } from "@/lib/format";
import { tokens } from "@/styles/tokens";

// ─── Lazy-loaded chart (below-the-fold SVG — deferred to cut initial JS parse)
function ChartSkeleton() {
  return (
    <div
      style={{
        width: "100%",
        maxWidth: 320,
        height: 160,
        borderRadius: 8,
        background: `linear-gradient(90deg, ${tokens.slate100} 25%, ${tokens.slate200} 50%, ${tokens.slate100} 75%)`,
        backgroundSize: "200% 100%",
        animation: "roi-shimmer 1.4s infinite",
      }}
      aria-label="Loading chart..."
    />
  );
}

const RafBarChart = dynamic(() => import("./RafBarChart"), {
  ssr: false,
  loading: ChartSkeleton,
});

// ─── Types ────────────────────────────────────────────────────────────────────

interface Inputs {
  orgName: string;
  members: number;
  currentRaf: number;
  hccGapRate: number;
  baseRate: number;
  awvRate: number;
  providers: number;
}

interface Results {
  rafGapRevenue: number;
  awvRevenue: number;
  recaptureRevenue: number;
  totalOpportunity: number;
  platformCost: number;
  netRevenue: number;
  roi: number;
  paybackMonths: number;
  npv3yr: number;
  targetRaf: number;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt$(n: number): string {
  return fmtCurrencyCompact(n);
}

function fmtFull$(n: number): string {
  return fmtCurrencyFull(n);
}

function calcResults(inp: Inputs): Results {
  const avgHccValue = 0.12; // average HCC coefficient
  const targetAwvRate = Math.min(inp.awvRate + 25, 85);

  const rafGapRevenue =
    inp.members * (inp.hccGapRate / 100) * avgHccValue * inp.baseRate;

  const awvRevenue =
    inp.members * ((targetAwvRate - inp.awvRate) / 100) * 200;

  const recaptureRevenue = inp.members * 0.05 * inp.baseRate * 0.08;

  const totalOpportunity = rafGapRevenue + awvRevenue + recaptureRevenue;

  const platformCost = 1.25 * inp.members * 12;

  const netRevenue = totalOpportunity - platformCost;

  const roi = platformCost > 0 ? (netRevenue / platformCost) * 100 : 0;

  const monthlyRevenue = totalOpportunity / 12;
  const paybackMonths =
    monthlyRevenue > 0 ? Math.ceil(platformCost / monthlyRevenue) : 99;

  // 3-Year NPV at 10% discount rate
  const r = 0.10;
  let npv3yr = 0;
  for (let yr = 1; yr <= 3; yr++) {
    npv3yr += netRevenue / Math.pow(1 + r, yr);
  }

  const targetRaf = Math.min(
    inp.currentRaf + inp.currentRaf * (inp.hccGapRate / 100) * avgHccValue * 2,
    2.5
  );

  return {
    rafGapRevenue,
    awvRevenue,
    recaptureRevenue,
    totalOpportunity,
    platformCost,
    netRevenue,
    roi,
    paybackMonths,
    npv3yr,
    targetRaf,
  };
}

// ─── Animated Number ─────────────────────────────────────────────────────────

function AnimatedNumber({
  value,
  format,
  className,
  style,
}: {
  value: number;
  format: (n: number) => string;
  className?: string;
  style?: React.CSSProperties;
}) {
  const [display, setDisplay] = useState(value);
  const [flash, setFlash] = useState(false);
  const [prevValue, setPrevValue] = useState(value);
  const [animStart, setAnimStart] = useState(value);

  // Detect value change during render
  if (prevValue !== value) {
    setPrevValue(value);
    setAnimStart(display);
    setFlash(true);
  }

  useEffect(() => {
    if (!flash) return;
    const start = animStart;
    const diff = value - start;
    const duration = 600;
    const startTime = performance.now();

    function step(now: number) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const next = progress < 1 ? start + diff * eased : value;
      setDisplay(next);
      if (progress < 1) requestAnimationFrame(step);
    }

    requestAnimationFrame(step);
    const t = setTimeout(() => setFlash(false), 400);
    return () => clearTimeout(t);
  }, [flash, animStart, value]);

  return (
    <span
      className={className}
      style={{
        ...style,
        transition: "color 0.3s, transform 0.3s, text-shadow 0.3s",
        color: flash ? tokens.success : undefined,
        transform: flash ? "scale(1.04)" : "scale(1)",
        display: "inline-block",
        textShadow: flash ? "0 0 20px rgba(16,185,129,0.3)" : "none",
      }}
    >
      {format(display)}
    </span>
  );
}

// ─── Revenue Breakdown Horizontal Bars ───────────────────────────────────────

function RevenueBreakdownChart({ results }: { results: Results }) {
  const items = [
    {
      label: "RAF Gap Closure",
      value: results.rafGapRevenue,
      color: tokens.infoBlue,
    },
    { label: "AWV Optimization", value: results.awvRevenue, color: tokens.success },
    {
      label: "Recapture Lift",
      value: results.recaptureRevenue,
      color: tokens.accentPurple,
    },
  ];
  const max = Math.max(...items.map((i) => i.value), 1);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {items.map((item) => {
        const pct = (item.value / max) * 100;
        return (
          <div key={item.label}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                marginBottom: 8,
                fontSize: 13,
              }}
            >
              <span style={{ color: tokens.slate600, fontWeight: 600 }}>
                {item.label}
              </span>
              <span style={{ color: item.color, fontWeight: 800, fontSize: 14 }}>
                {fmt$(item.value)}
              </span>
            </div>
            <div
              style={{
                height: 12,
                borderRadius: 6,
                background: tokens.slate100,
                overflow: "hidden",
                position: "relative",
              }}
            >
              <div
                style={{
                  height: "100%",
                  width: `${pct}%`,
                  borderRadius: 6,
                  background: `linear-gradient(90deg, ${item.color}99, ${item.color})`,
                  transition: "width 0.8s cubic-bezier(0.4, 0, 0.2, 1)",
                  boxShadow: `0 2px 8px ${item.color}40`,
                  position: "relative",
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Timeline Chart ───────────────────────────────────────────────────────────

function TimelineChart({ monthlyRevenue }: { monthlyRevenue: number }) {
  const months = Array.from({ length: 12 }, (_, i) => i + 1);
  // Ramp up: starts slow, accelerates (S-curve approximation)
  function rampFactor(m: number): number {
    return 1 / (1 + Math.exp(-0.6 * (m - 6)));
  }
  const values = months.map((m) => monthlyRevenue * rampFactor(m) * m);
  const maxVal = Math.max(...values, 1);
  const svgW = 400;
  const svgH = 140;
  const padL = 48;
  const padR = 12;
  const padT = 12;
  const padB = 32;
  const chartW = svgW - padL - padR;
  const chartH = svgH - padT - padB;

  const pts = months.map((m, i) => {
    const x = padL + (i / 11) * chartW;
    const y = padT + chartH - (values[i] / maxVal) * chartH;
    return { x, y, m, v: values[i] };
  });

  const pathD =
    pts
      .map((p, i) => {
        if (i === 0) return `M ${p.x} ${p.y}`;
        const prev = pts[i - 1];
        const cpX = (prev.x + p.x) / 2;
        return `C ${cpX} ${prev.y} ${cpX} ${p.y} ${p.x} ${p.y}`;
      })
      .join(" ") +
    ` L ${pts[pts.length - 1].x} ${padT + chartH} L ${pts[0].x} ${padT + chartH} Z`;

  const linePath = pts
    .map((p, i) => {
      if (i === 0) return `M ${p.x} ${p.y}`;
      const prev = pts[i - 1];
      const cpX = (prev.x + p.x) / 2;
      return `C ${cpX} ${prev.y} ${cpX} ${p.y} ${p.x} ${p.y}`;
    })
    .join(" ");

  // Y-axis labels
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => ({
    y: padT + chartH - f * chartH,
    label: fmt$(maxVal * f),
  }));

  return (
    <svg
      viewBox={`0 0 ${svgW} ${svgH}`}
      style={{ width: "100%", height: "auto" }}
      role="img"
      aria-label="12-month cumulative revenue projection"
    >
      <defs>
        <linearGradient id="timelineGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={tokens.infoBlue} stopOpacity="0.35" />
          <stop offset="50%" stopColor={tokens.infoBlue} stopOpacity="0.15" />
          <stop offset="100%" stopColor={tokens.accentPurple} stopOpacity="0.02" />
        </linearGradient>
        <linearGradient id="timelineLineGrad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor={tokens.infoBlue} />
          <stop offset="50%" stopColor={tokens.infoBlue} />
          <stop offset="100%" stopColor={tokens.accentPurple} />
        </linearGradient>
        <filter id="lineShadow">
          <feDropShadow dx="0" dy="2" stdDeviation="3" floodColor={tokens.infoBlue} floodOpacity="0.3" />
        </filter>
      </defs>

      {/* Grid lines */}
      {yTicks.map((t) => (
        <g key={t.y}>
          <line
            x1={padL}
            y1={t.y}
            x2={svgW - padR}
            y2={t.y}
            stroke={tokens.slate200}
            strokeWidth={1}
            strokeDasharray="4 4"
          />
          <text x={padL - 4} y={t.y + 4} textAnchor="end" fontSize={9} fill={tokens.slate400}>
            {t.label}
          </text>
        </g>
      ))}

      {/* Area fill */}
      <path d={pathD} fill="url(#timelineGrad)" />

      {/* Line */}
      <path
        d={linePath}
        fill="none"
        stroke="url(#timelineLineGrad)"
        strokeWidth={3}
        strokeLinecap="round"
        strokeLinejoin="round"
        filter="url(#lineShadow)"
      />

      {/* Dots + labels for key months */}
      {pts
        .filter((_, i) => i % 2 === 0 || i === 11)
        .map((p) => (
          <g key={p.m}>
            <circle cx={p.x} cy={p.y} r={6} fill={tokens.white} stroke="url(#timelineLineGrad)" strokeWidth={2.5} />
            <circle cx={p.x} cy={p.y} r={3} fill={tokens.infoBlue} />
            <text
              x={p.x}
              y={padT + chartH + 14}
              textAnchor="middle"
              fontSize={9}
              fill={tokens.slate400}
            >
              M{p.m}
            </text>
          </g>
        ))}
    </svg>
  );
}

// ─── Pricing Card ─────────────────────────────────────────────────────────────

interface PricingCardProps {
  name: string;
  price: string;
  priceNote: string;
  highlight?: boolean;
  badge?: string;
  features: string[];
  cta: string;
  ctaHref?: string;
  annualCost?: string;
}

function PricingCard({
  name,
  price,
  priceNote,
  highlight,
  badge,
  features,
  cta,
  ctaHref,
  annualCost,
}: PricingCardProps) {
  const [hovered, setHovered] = useState(false);

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        background: highlight
          ? `linear-gradient(160deg, #1E3A8A 0%, ${tokens.primaryDark} 50%, ${tokens.primary} 100%)`
          : tokens.white,
        border: highlight
          ? "none"
          : `1px solid ${hovered ? tokens.infoBlue : tokens.slate200}`,
        borderRadius: 14,
        padding: 28,
        display: "flex",
        flexDirection: "column",
        position: "relative",
        overflow: "hidden",
        boxShadow: highlight
          ? "0 20px 60px rgba(37,99,235,0.35)"
          : hovered
          ? "0 8px 24px rgba(0,0,0,0.10)"
          : "0 2px 8px rgba(0,0,0,0.04)",
        transition: "box-shadow 0.2s, border-color 0.2s, transform 0.2s",
        transform: hovered && !highlight ? "translateY(-4px)" : highlight ? "scale(1.02)" : "translateY(0)",
        flex: "1 1 0",
        minWidth: 240,
      }}
    >
      {/* Decorative blobs for highlighted card */}
      {highlight && (
        <>
          <div
            style={{
              position: "absolute",
              top: -40,
              right: -40,
              width: 160,
              height: 160,
              borderRadius: "50%",
              background: "rgba(255,255,255,0.06)",
              pointerEvents: "none",
            }}
          />
          <div
            style={{
              position: "absolute",
              bottom: -60,
              left: -20,
              width: 200,
              height: 200,
              borderRadius: "50%",
              background: "rgba(255,255,255,0.04)",
              pointerEvents: "none",
            }}
          />
        </>
      )}

      {badge && (
        <div style={{ marginBottom: 12 }}>
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              background: highlight ? "rgba(255,255,255,0.2)" : tokens.primarySoft,
              color: highlight ? tokens.white : tokens.primary,
              fontSize: 11,
              fontWeight: 700,
              padding: "4px 10px",
              borderRadius: 999,
              letterSpacing: "0.04em",
            }}
          >
            <Star size={10} />
            {badge}
          </span>
        </div>
      )}

      <div style={{ marginBottom: 20 }}>
        <div
          style={{
            fontSize: 18,
            fontWeight: 700,
            color: highlight ? tokens.white : tokens.slate800,
            marginBottom: 6,
          }}
        >
          {name}
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 4 }}>
          <span
            style={{
              fontSize: 36,
              fontWeight: 800,
              color: highlight ? tokens.white : tokens.slate800,
              lineHeight: 1,
            }}
          >
            {price}
          </span>
          <span
            style={{
              fontSize: 13,
              color: highlight ? "rgba(255,255,255,0.7)" : tokens.slate400,
            }}
          >
            {priceNote}
          </span>
        </div>
        {annualCost && (
          <div
            style={{
              fontSize: 12,
              color: highlight ? "rgba(255,255,255,0.6)" : tokens.slate400,
              marginTop: 4,
            }}
          >
            {annualCost}
          </div>
        )}
      </div>

      <div
        style={{
          width: "100%",
          height: 1,
          background: highlight ? "rgba(255,255,255,0.15)" : tokens.slate100,
          marginBottom: 20,
        }}
      />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 10, marginBottom: 24 }}>
        {features.map((f) => (
          <div
            key={f}
            style={{ display: "flex", alignItems: "flex-start", gap: 10 }}
          >
            <CheckCircle
              size={16}
              style={{
                color: highlight ? tokens.emerald300 : tokens.success,
                flexShrink: 0,
                marginTop: 1,
              }}
            />
            <span
              style={{
                fontSize: 13,
                color: highlight ? "rgba(255,255,255,0.88)" : tokens.slate600,
                lineHeight: 1.5,
              }}
            >
              {f}
            </span>
          </div>
        ))}
      </div>

      <a
        href={ctaHref ?? "#"}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: 8,
          padding: "13px 20px",
          borderRadius: 10,
          fontSize: 14,
          fontWeight: 600,
          background: highlight ? tokens.white : tokens.primary,
          color: highlight ? tokens.primary : tokens.white,
          textDecoration: "none",
          transition: "opacity 0.15s, transform 0.15s",
          cursor: "pointer",
          border: "none",
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.opacity = "0.9";
          e.currentTarget.style.transform = "translateY(-1px)";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.opacity = "1";
          e.currentTarget.style.transform = "translateY(0)";
        }}
      >
        {cta}
        <ArrowRight size={16} />
      </a>
    </div>
  );
}

// ─── Input Field ──────────────────────────────────────────────────────────────

function InputField({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <label
        style={{ fontSize: 13, fontWeight: 600, color: tokens.slate700 }}
      >
        {label}
      </label>
      {children}
      {hint && (
        <span style={{ fontSize: 11, color: tokens.slate400 }}>{hint}</span>
      )}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "10px 12px",
  borderRadius: 8,
  border: `1px solid ${tokens.slate200}`,
  fontSize: 14,
  color: tokens.slate800,
  background: tokens.white,
  boxSizing: "border-box",
  transition: "border-color 0.15s, box-shadow 0.15s",
};

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function ROICalculatorPage() {
  const [inputs, setInputs] = useState<Inputs>({
    orgName: "",
    members: 50000,
    currentRaf: 1.05,
    hccGapRate: 15,
    baseRate: 12000,
    awvRate: 40,
    providers: 50,
  });

  const [results, setResults] = useState<Results>(() => calcResults({
    orgName: "",
    members: 50000,
    currentRaf: 1.05,
    hccGapRate: 15,
    baseRate: 12000,
    awvRate: 40,
    providers: 50,
  }));

  const [copied, setCopied] = useState(false);
  const [focusedInput, setFocusedInput] = useState<string | null>(null);

  // Recalculate on input change
  useEffect(() => {
    setResults(calcResults(inputs));
  }, [inputs]);

  // Load from URL params on mount
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const fromUrl: Partial<Inputs> = {};
    if (params.get("members")) fromUrl.members = Number(params.get("members"));
    if (params.get("raf")) fromUrl.currentRaf = Number(params.get("raf"));
    if (params.get("gap")) fromUrl.hccGapRate = Number(params.get("gap"));
    if (params.get("base")) fromUrl.baseRate = Number(params.get("base"));
    if (params.get("awv")) fromUrl.awvRate = Number(params.get("awv"));
    if (params.get("providers")) fromUrl.providers = Number(params.get("providers"));
    if (params.get("org")) fromUrl.orgName = params.get("org") || "";
    if (Object.keys(fromUrl).length > 0) {
      setInputs((prev) => ({ ...prev, ...fromUrl }));
    }
  }, []);

  const set = useCallback(
    <K extends keyof Inputs>(key: K, value: Inputs[K]) => {
      setInputs((prev) => ({ ...prev, [key]: value }));
    },
    []
  );

  function handleShareLink() {
    const params = new URLSearchParams({
      members: String(inputs.members),
      raf: String(inputs.currentRaf),
      gap: String(inputs.hccGapRate),
      base: String(inputs.baseRate),
      awv: String(inputs.awvRate),
      providers: String(inputs.providers),
      org: inputs.orgName,
    });
    const url = `${window.location.origin}/roi?${params.toString()}`;
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    });
  }

  function handleDownload() {
    const lines = [
      `RAF Intelligence — ROI Analysis`,
      inputs.orgName ? `Organization: ${inputs.orgName}` : "",
      `Generated: ${new Date().toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })}`,
      ``,
      `=== INPUTS ===`,
      `Medicare Advantage Members: ${inputs.members.toLocaleString()}`,
      `Current Average RAF Score: ${inputs.currentRaf}`,
      `HCC Gap Rate: ${inputs.hccGapRate}%`,
      `Base Rate per Member: $${inputs.baseRate.toLocaleString()}`,
      `AWV Completion Rate: ${inputs.awvRate}%`,
      `Number of Providers: ${inputs.providers}`,
      ``,
      `=== REVENUE OPPORTUNITY ===`,
      `RAF Gap Closure: ${fmtFull$(results.rafGapRevenue)}`,
      `AWV Optimization: ${fmtFull$(results.awvRevenue)}`,
      `Recapture Improvement: ${fmtFull$(results.recaptureRevenue)}`,
      `Total Annual Opportunity: ${fmtFull$(results.totalOpportunity)}`,
      ``,
      `=== ROI SUMMARY ===`,
      `Estimated Platform Cost: ${fmtFull$(results.platformCost)}/year`,
      `Net Revenue Impact: ${fmtFull$(results.netRevenue)}`,
      `ROI: ${Math.round(results.roi)}%`,
      `Payback Period: ${results.paybackMonths} months`,
      `3-Year NPV (10% discount): ${fmtFull$(results.npv3yr)}`,
      ``,
      `RAF Intelligence | rafIntelligence.ai`,
    ]
      .filter((l) => l !== undefined)
      .join("\n");

    const blob = new Blob([lines], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `ROI-Analysis-${inputs.orgName || "RAF-Intelligence"}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }

  const PMPM_PRO = 1.5;
  const annualPro = fmtFull$(PMPM_PRO * Math.min(inputs.members, 100000) * 12);

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div
      className="roi-page-root"
      style={{
        background: tokens.slate50,
        minHeight: "100vh",
        padding: "32px 40px 60px",
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
        overflowX: "hidden",
      }}
    >
      <style>{`
        @keyframes fadeSlideIn {
          from { opacity: 0; transform: translateY(16px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes shimmer {
          0% { background-position: -400px 0; }
          100% { background-position: 400px 0; }
        }
        @keyframes pulse-glow {
          0%, 100% { box-shadow: 0 0 0 0 rgba(16,185,129,0), 0 2px 8px rgba(0,0,0,0.04); }
          50% { box-shadow: 0 0 0 8px rgba(16,185,129,0.08), 0 4px 20px rgba(16,185,129,0.1); }
        }
        @keyframes flowArrow {
          0%, 100% { opacity: 0.3; transform: translateX(0); }
          50% { opacity: 0.7; transform: translateX(3px); }
        }
        .roi-grid { display: grid; grid-template-columns: 420px 1fr; gap: 32px; align-items: start; }
        .results-2col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
        .charts-3col { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; }
        .pricing-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; }
        @media (max-width: 1200px) {
          .roi-grid { grid-template-columns: 1fr !important; }
          .charts-3col { grid-template-columns: 1fr 1fr !important; }
        }
        @media (max-width: 768px) {
          .results-2col { grid-template-columns: 1fr !important; }
          .charts-3col { grid-template-columns: 1fr !important; }
          .pricing-row { grid-template-columns: 1fr !important; }
          .roi-page-root { padding: 20px 16px 40px !important; }
        }
        .roi-slider {
          -webkit-appearance: none;
          width: 100%;
          height: 8px;
          border-radius: 4px;
          outline: none;
          transition: box-shadow 0.2s;
        }
        .roi-slider:focus-visible {
          outline: 2px solid #2563EB;
          outline-offset: 3px;
          border-radius: 4px;
        }
        .roi-slider::-webkit-slider-thumb {
          -webkit-appearance: none;
          width: 22px;
          height: 22px;
          border-radius: 50%;
          background: #FFFFFF;
          cursor: pointer;
          border: 3px solid #2563EB;
          box-shadow: 0 2px 8px rgba(37,99,235,0.35), 0 0 0 0 rgba(37,99,235,0);
          transition: box-shadow 0.2s, transform 0.15s;
        }
        .roi-slider::-webkit-slider-thumb:hover {
          transform: scale(1.15);
          box-shadow: 0 2px 12px rgba(37,99,235,0.45), 0 0 0 6px rgba(37,99,235,0.08);
        }
        .roi-slider:active::-webkit-slider-thumb {
          transform: scale(1.2);
          box-shadow: 0 2px 12px rgba(37,99,235,0.5), 0 0 0 8px rgba(37,99,235,0.12);
        }
        .roi-slider-green::-webkit-slider-thumb {
          border-color: #10B981;
          box-shadow: 0 2px 8px rgba(16,185,129,0.35);
        }
        .roi-slider-green::-webkit-slider-thumb:hover {
          box-shadow: 0 2px 12px rgba(16,185,129,0.45), 0 0 0 6px rgba(16,185,129,0.08);
        }
        input:focus { border-color: #3B82F6 !important; box-shadow: 0 0 0 3px rgba(59,130,246,0.12) !important; }
        .animate-in { animation: fadeSlideIn 0.5s ease both; }
        .opportunity-card { animation: pulse-glow 3s infinite; }
        .roi-result-card {
          transition: transform 0.25s cubic-bezier(0.4,0,0.2,1), box-shadow 0.25s cubic-bezier(0.4,0,0.2,1);
        }
        .roi-result-card:hover {
          transform: translateY(-2px);
          box-shadow: 0 8px 24px rgba(0,0,0,0.08);
        }
        .roi-chart-card {
          transition: transform 0.25s cubic-bezier(0.4,0,0.2,1), box-shadow 0.25s cubic-bezier(0.4,0,0.2,1);
        }
        .roi-chart-card:hover {
          transform: translateY(-2px);
          box-shadow: 0 8px 24px rgba(0,0,0,0.08);
        }
        .section-flow-label {
          display: flex;
          align-items: center;
          gap: 8px;
          font-size: 11px;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: 0.08em;
          color: #64748B;
          margin-bottom: 12px;
        }
        .section-flow-label::after {
          content: '';
          flex: 1;
          height: 1px;
          background: linear-gradient(90deg, #E2E8F0, transparent);
        }
      `}</style>

      {/* ── Page Header ── */}
      <PageHeader
        title="ROI Calculator"
        subtitle="Estimate your revenue opportunity and return on investment with RAF Intelligence"
        icon={<Calculator size={24} />}
        actions={
          <div style={{ display: "flex", gap: 10 }}>
            <button
              onClick={handleDownload}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 7,
                padding: "9px 16px",
                borderRadius: 8,
                border: `1px solid ${tokens.slate200}`,
                background: tokens.white,
                color: tokens.slate700,
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
                transition: "all 0.15s",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = tokens.slate50;
                e.currentTarget.style.borderColor = tokens.slate300;
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = tokens.white;
                e.currentTarget.style.borderColor = tokens.slate200;
              }}
            >
              <Download size={14} />
              Download Report
            </button>
            <button
              onClick={handleShareLink}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 7,
                padding: "9px 16px",
                borderRadius: 8,
                border: "none",
                background: copied ? tokens.success : tokens.primary,
                color: tokens.white,
                fontSize: 13,
                fontWeight: 600,
                cursor: "pointer",
                transition: "background 0.2s",
              }}
            >
              <Share2 size={14} />
              {copied ? "Link Copied!" : "Share via Link"}
            </button>
          </div>
        }
      />

      {/* ── Hero Band ── */}
      <div
        className="animate-in mesh-pattern"
        style={{
          background: `linear-gradient(135deg, ${tokens.slate900} 0%, #1E3A8A 40%, ${tokens.primary} 70%, ${tokens.infoBlue} 100%)`,
          borderRadius: 14,
          padding: "32px 36px",
          marginBottom: 32,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 24,
          boxShadow: "0 8px 32px rgba(37,99,235,0.25), 0 2px 8px rgba(0,0,0,0.1)",
          position: "relative",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: -60,
            right: -60,
            width: 260,
            height: 260,
            borderRadius: "50%",
            background: "rgba(255,255,255,0.05)",
            pointerEvents: "none",
          }}
        />
        <div
          style={{
            position: "absolute",
            bottom: -80,
            right: 200,
            width: 200,
            height: 200,
            borderRadius: "50%",
            background: "rgba(255,255,255,0.04)",
            pointerEvents: "none",
          }}
        />
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <span style={{ fontSize: 13, color: "rgba(255,255,255,0.7)", fontWeight: 500 }}>
              Estimated Annual Revenue Opportunity
            </span>
            <span
              aria-label="This is a projection"
              style={{
                fontSize: 9,
                fontWeight: 800,
                textTransform: "uppercase" as const,
                letterSpacing: "0.08em",
                color: tokens.warningStrong,
                background: tokens.warningSoft,
                padding: "2px 6px",
                borderRadius: 4,
              }}
            >
              PROJECTED
            </span>
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
            <AnimatedNumber
              value={results.totalOpportunity}
              format={fmtFull$}
              style={{
                fontSize: 42,
                fontWeight: 800,
                color: tokens.white,
                lineHeight: 1,
                letterSpacing: "-0.02em",
              }}
            />
          </div>
          {inputs.orgName && (
            <div style={{ fontSize: 13, color: "rgba(255,255,255,0.6)", marginTop: 4 }}>
              for {inputs.orgName}
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
          {[
            { label: "ROI", value: `${Math.round(results.roi)}%`, icon: TrendingUp },
            { label: "Payback", value: `${results.paybackMonths}mo`, icon: Clock },
            { label: "3-Yr NPV", value: fmt$(results.npv3yr), icon: Target },
          ].map((m) => {
            const Icon = m.icon;
            return (
              <div key={m.label} style={{ textAlign: "center" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 5, marginBottom: 2 }}>
                  <Icon size={13} style={{ color: "rgba(255,255,255,0.6)" }} />
                  <span style={{ fontSize: 11, color: "rgba(255,255,255,0.6)", fontWeight: 500 }}>{m.label}</span>
                </div>
                <div style={{ fontSize: 22, fontWeight: 800, color: tokens.white }}>{m.value}</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Main Grid: Inputs + Results ── */}
      <div className="roi-grid animate-in" style={{ marginBottom: 28, animationDelay: "0.1s" }}>

        {/* ── LEFT: Input Panel ── */}
        <div
          className="premium-card premium-shadow"
          style={{
            padding: 28,
            position: "sticky",
            top: 20,
            maxWidth: "100%",
            boxSizing: "border-box",
            overflowX: "hidden",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 24 }}>
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: 10,
                background: tokens.primarySoft,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <Building2 size={18} color={tokens.primary} />
            </div>
            <div>
              <div style={{ fontSize: 16, fontWeight: 700, color: tokens.slate800 }}>
                Your Organization
              </div>
              <div style={{ fontSize: 12, color: tokens.slate400 }}>
                Adjust inputs to see real-time results
              </div>
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            <InputField label="Organization Name" hint="Optional — appears in your report">
              <input
                type="text"
                value={inputs.orgName}
                placeholder="e.g. Sunrise Health Plan"
                onChange={(e) => set("orgName", e.target.value)}
                onFocus={() => setFocusedInput("orgName")}
                onBlur={() => setFocusedInput(null)}
                style={inputStyle}
              />
            </InputField>

            <InputField
              label="Total Medicare Advantage Members"
              hint="Total attributed MA lives in your population"
            >
              <input
                type="number"
                value={inputs.members}
                min={1000}
                max={500000}
                step={1000}
                onChange={(e) => set("members", Number(e.target.value))}
                onFocus={() => setFocusedInput("members")}
                onBlur={() => setFocusedInput(null)}
                style={inputStyle}
              />
            </InputField>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              <InputField label="Avg RAF Score" hint="Current average">
                <input
                  type="number"
                  value={inputs.currentRaf}
                  min={0.5}
                  max={3.0}
                  step={0.01}
                  onChange={(e) => set("currentRaf", Number(e.target.value))}
                  onFocus={() => setFocusedInput("raf")}
                  onBlur={() => setFocusedInput(null)}
                  style={inputStyle}
                />
              </InputField>
              <InputField label="Base Rate / Member" hint="Annual CMS base">
                <input
                  type="number"
                  value={inputs.baseRate}
                  min={5000}
                  max={30000}
                  step={500}
                  onChange={(e) => set("baseRate", Number(e.target.value))}
                  onFocus={() => setFocusedInput("base")}
                  onBlur={() => setFocusedInput(null)}
                  style={inputStyle}
                />
              </InputField>
            </div>

            <InputField
              label="HCC Gap Capture Rate"
              hint="Estimated % of HCC conditions not currently captured"
            >
              <div style={{ position: "relative" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <input
                    type="range"
                    className="roi-slider"
                    min={5}
                    max={30}
                    step={1}
                    value={inputs.hccGapRate}
                    onChange={(e) => set("hccGapRate", Number(e.target.value))}
                    style={{
                      background: `linear-gradient(to right, ${tokens.primaryDark} 0%, ${tokens.infoBlue} ${((inputs.hccGapRate - 5) / 25) * 100}%, ${tokens.slate200} ${((inputs.hccGapRate - 5) / 25) * 100}%)`,
                    }}
                  />
                  <span
                    style={{
                      minWidth: 48,
                      padding: "4px 10px",
                      borderRadius: 8,
                      background: `linear-gradient(135deg, ${tokens.primaryDark}, ${tokens.infoBlue})`,
                      color: tokens.white,
                      fontSize: 13,
                      fontWeight: 700,
                      textAlign: "center",
                      flexShrink: 0,
                      boxShadow: "0 2px 8px rgba(37,99,235,0.3)",
                    }}
                  >
                    {inputs.hccGapRate}%
                  </span>
                </div>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: 10,
                    color: tokens.slate400,
                    marginTop: 6,
                  }}
                >
                  <span>5%</span>
                  <span>30%</span>
                </div>
              </div>
            </InputField>

            <InputField
              label="AWV Completion Rate"
              hint="Current annual wellness visit completion"
            >
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <input
                    type="range"
                    className="roi-slider roi-slider-green"
                    min={0}
                    max={100}
                    step={1}
                    value={inputs.awvRate}
                    onChange={(e) => set("awvRate", Number(e.target.value))}
                    style={{
                      background: `linear-gradient(to right, ${tokens.emerald800} 0%, ${tokens.success} ${inputs.awvRate}%, ${tokens.slate200} ${inputs.awvRate}%)`,
                    }}
                  />
                  <span
                    style={{
                      minWidth: 48,
                      padding: "4px 10px",
                      borderRadius: 8,
                      background: `linear-gradient(135deg, ${tokens.emerald800}, ${tokens.success})`,
                      color: tokens.white,
                      fontSize: 13,
                      fontWeight: 700,
                      textAlign: "center",
                      flexShrink: 0,
                      boxShadow: "0 2px 8px rgba(16,185,129,0.3)",
                    }}
                  >
                    {inputs.awvRate}%
                  </span>
                </div>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    fontSize: 10,
                    color: tokens.slate400,
                    marginTop: 6,
                  }}
                >
                  <span>0%</span>
                  <span>100%</span>
                </div>
              </div>
            </InputField>

            <InputField label="Number of Providers" hint="Physicians and APPs in your network">
              <input
                type="number"
                value={inputs.providers}
                min={1}
                max={2000}
                step={1}
                onChange={(e) => set("providers", Number(e.target.value))}
                onFocus={() => setFocusedInput("providers")}
                onBlur={() => setFocusedInput(null)}
                style={inputStyle}
              />
            </InputField>
          </div>

          {/* Quick stats under inputs */}
          <div
            style={{
              marginTop: 24,
              padding: 18,
              background: `linear-gradient(135deg, ${tokens.slate50} 0%, ${tokens.primarySoft} 100%)`,
              borderRadius: 10,
              border: `1px solid ${tokens.slate200}`,
            }}
          >
            <div style={{ fontSize: 11, fontWeight: 700, color: tokens.slate500, marginBottom: 12, textTransform: "uppercase" as const, letterSpacing: "0.06em", display: "flex", alignItems: "center", gap: 6 }}>
              <Users size={12} />
              Per-Provider Impact
            </div>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <div style={{ textAlign: "center" }}>
                <div className="gradient-text" style={{ fontSize: 20, fontWeight: 800 }}>
                  {fmt$(results.totalOpportunity / Math.max(inputs.providers, 1))}
                </div>
                <div style={{ fontSize: 11, color: tokens.slate400, marginTop: 2 }}>Revenue/Provider</div>
              </div>
              <div style={{ width: 1, background: tokens.slate200 }} />
              <div style={{ textAlign: "center" }}>
                <div className="gradient-text" style={{ fontSize: 20, fontWeight: 800 }}>
                  {Math.round(inputs.members / Math.max(inputs.providers, 1)).toLocaleString()}
                </div>
                <div style={{ fontSize: 11, color: tokens.slate400, marginTop: 2 }}>Members/Provider</div>
              </div>
              <div style={{ width: 1, background: tokens.slate200 }} />
              <div style={{ textAlign: "center" }}>
                <div style={{ fontSize: 20, fontWeight: 800, color: tokens.success }}>
                  {results.paybackMonths}mo
                </div>
                <div style={{ fontSize: 11, color: tokens.slate400, marginTop: 2 }}>Payback</div>
              </div>
            </div>
          </div>
        </div>

        {/* ── RIGHT: Results ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

          <div className="section-flow-label">
            <Zap size={12} />
            Revenue Projection Results
          </div>

          {/* Revenue Opportunity Card */}
          <div
            className="opportunity-card gradient-border"
            style={{
              background: `linear-gradient(135deg, ${tokens.successSoft} 0%, ${tokens.successSoft} 50%, ${tokens.emerald100} 100%)`,
              borderRadius: 14,
              padding: 28,
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 20 }}>
              <DollarSign size={20} color={tokens.successDark} />
              <span style={{ fontSize: 16, fontWeight: 700, color: tokens.successDark }}>
                Revenue Opportunity Breakdown
              </span>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 14, marginBottom: 20 }}>
              {[
                {
                  label: "RAF Gap Closure",
                  desc: `${inputs.members.toLocaleString()} members × ${inputs.hccGapRate}% gap rate × HCC coefficients`,
                  value: results.rafGapRevenue,
                  color: tokens.infoBlue,
                },
                {
                  label: "AWV Optimization",
                  desc: `${inputs.members.toLocaleString()} members × AWV uplift × $200/visit`,
                  value: results.awvRevenue,
                  color: tokens.success,
                },
                {
                  label: "Recapture Improvement",
                  desc: `${inputs.members.toLocaleString()} members × 5% recapture lift`,
                  value: results.recaptureRevenue,
                  color: tokens.accentPurple,
                },
              ].map((item) => (
                <div
                  key={item.label}
                  className="hover-lift"
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    padding: "14px 16px",
                    background: tokens.white,
                    borderRadius: 10,
                    border: `1px solid ${item.color}20`,
                    gap: 12,
                    boxShadow: `0 1px 4px ${item.color}08`,
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: 10, flex: 1, minWidth: 0 }}>
                    <div
                      style={{
                        width: 10,
                        height: 10,
                        borderRadius: "50%",
                        background: item.color,
                        flexShrink: 0,
                      }}
                    />
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 600, color: tokens.slate800 }}>
                        {item.label}
                      </div>
                      <div
                        style={{
                          fontSize: 11,
                          color: tokens.slate400,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {item.desc}
                      </div>
                    </div>
                  </div>
                  <AnimatedNumber
                    value={item.value}
                    format={fmtFull$}
                    style={{
                      fontSize: 16,
                      fontWeight: 700,
                      color: item.color,
                      flexShrink: 0,
                    }}
                  />
                </div>
              ))}
            </div>

            {/* Total */}
            <div
              className="mesh-pattern"
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                padding: "18px 22px",
                background: `linear-gradient(135deg, ${tokens.emerald800} 0%, ${tokens.successDark} 50%, ${tokens.success} 100%)`,
                borderRadius: 14,
                boxShadow: "0 4px 16px rgba(22,163,74,0.25)",
              }}
            >
              <div>
                <div style={{ fontSize: 13, color: "rgba(255,255,255,0.8)", fontWeight: 500 }}>
                  Total Annual Opportunity
                </div>
                <div style={{ fontSize: 11, color: "rgba(255,255,255,0.55)", marginTop: 1 }}>
                  Achievable with RAF Intelligence
                </div>
              </div>
              <AnimatedNumber
                value={results.totalOpportunity}
                format={fmtFull$}
                style={{
                  fontSize: 26,
                  fontWeight: 800,
                  color: tokens.white,
                  letterSpacing: "-0.01em",
                }}
              />
            </div>
          </div>

          {/* ROI Summary */}
          <div className="results-2col">
            {[
              {
                label: "Platform Cost",
                value: results.platformCost,
                format: fmtFull$,
                sub: "$1.25 PMPM × 12 months",
                color: tokens.slate500,
                bg: tokens.slate50,
                border: tokens.slate200,
                icon: Activity,
              },
              {
                label: "Net Revenue Impact",
                value: results.netRevenue,
                format: fmtFull$,
                sub: "Opportunity minus cost",
                color: results.netRevenue >= 0 ? tokens.successDark : tokens.riskHigh,
                bg: results.netRevenue >= 0 ? tokens.successSoft : tokens.riskHighSoft,
                border: results.netRevenue >= 0 ? tokens.emerald300 : tokens.dangerBorder,
                icon: DollarSign,
              },
              {
                label: "Return on Investment",
                value: results.roi,
                format: (n: number) => `${Math.round(n)}%`,
                sub: "(Net Revenue ÷ Cost) × 100",
                color: tokens.primary,
                bg: tokens.primarySoft,
                border: "rgba(37,99,235,0.20)",
                icon: TrendingUp,
              },
              {
                label: "3-Year NPV",
                value: results.npv3yr,
                format: fmtFull$,
                sub: "At 10% discount rate",
                color: tokens.accentPurple,
                bg: "rgba(139,92,246,0.08)",
                border: "rgba(139,92,246,0.20)",
                icon: Target,
              },
            ].map((m) => {
              const Icon = m.icon;
              return (
                <div
                  key={m.label}
                  className="roi-result-card"
                  style={{
                    background: m.bg,
                    border: `1px solid ${m.border}`,
                    borderRadius: 14,
                    padding: 20,
                    position: "relative",
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      position: "absolute",
                      top: -20,
                      right: -20,
                      width: 80,
                      height: 80,
                      borderRadius: "50%",
                      background: `${m.color}08`,
                      pointerEvents: "none",
                    }}
                  />
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                    <div
                      style={{
                        width: 28,
                        height: 28,
                        borderRadius: 8,
                        background: `${m.color}15`,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                      }}
                    >
                      <Icon size={14} color={m.color} />
                    </div>
                    <span style={{ fontSize: 11, fontWeight: 700, color: tokens.slate500, textTransform: "uppercase" as const, letterSpacing: "0.05em" }}>
                      {m.label}
                    </span>
                  </div>
                  <AnimatedNumber
                    value={m.value}
                    format={m.format}
                    style={{
                      fontSize: 28,
                      fontWeight: 800,
                      color: m.color,
                      display: "block",
                      marginBottom: 4,
                      letterSpacing: "-0.02em",
                    }}
                  />
                  <div style={{ fontSize: 11, color: tokens.slate400 }}>{m.sub}</div>
                </div>
              );
            })}
          </div>

          {/* Payback Banner */}
          <div
            style={{
              background: results.paybackMonths <= 6
                ? `linear-gradient(135deg, #1E3A8A, ${tokens.primary})`
                : `linear-gradient(135deg, ${tokens.slate700}, ${tokens.slate600})`,
              borderRadius: 10,
              padding: "16px 20px",
              display: "flex",
              alignItems: "center",
              gap: 14,
            }}
          >
            <div
              style={{
                width: 44,
                height: 44,
                borderRadius: 10,
                background: "rgba(255,255,255,0.15)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              <Clock size={22} color={tokens.white} />
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 13, color: "rgba(255,255,255,0.75)", fontWeight: 500 }}>
                Estimated Payback Period
              </div>
              <div style={{ fontSize: 20, fontWeight: 800, color: tokens.white }}>
                {results.paybackMonths} months
              </div>
            </div>
            <div style={{ fontSize: 12, color: "rgba(255,255,255,0.6)", textAlign: "right", maxWidth: 160 }}>
              Based on monthly revenue ramp and platform cost
            </div>
          </div>
        </div>
      </div>

      {/* ── Visual Charts ── */}
      <div className="section-flow-label animate-in" style={{ animationDelay: "0.18s", marginBottom: 0 }}>
        <Activity size={12} />
        Detailed Analytics
      </div>
      <div
        className="charts-3col animate-in"
        style={{ marginBottom: 28, animationDelay: "0.2s" }}
      >
        {/* RAF Comparison Bar */}
        <div
          className="premium-card premium-shadow roi-chart-card"
          style={{
            padding: 24,
          }}
        >
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: tokens.slate800, letterSpacing: "-0.01em" }}>
              RAF Score Comparison
            </div>
            <div style={{ fontSize: 12, color: tokens.slate400, marginTop: 3 }}>
              Current vs Target vs Industry Benchmark
            </div>
          </div>
          <RafBarChart current={inputs.currentRaf} target={results.targetRaf} />
          <div style={{ display: "flex", gap: 16, marginTop: 12, flexWrap: "wrap" }}>
            {[
              { label: "Current", color: tokens.warningStrong },
              { label: "Target", color: tokens.success },
              { label: "Industry (1.15)", color: tokens.infoBlue },
            ].map((l) => (
              <div key={l.label} style={{ display: "flex", alignItems: "center", gap: 5 }}>
                <div style={{ width: 10, height: 10, borderRadius: 2, background: l.color }} />
                <span style={{ fontSize: 11, color: tokens.slate500 }}>{l.label}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Revenue Breakdown Horizontal */}
        <div
          className="premium-card premium-shadow roi-chart-card"
          style={{
            padding: 24,
          }}
        >
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: tokens.slate800 }}>
              Revenue by Source
            </div>
            <div style={{ fontSize: 12, color: tokens.slate400, marginTop: 2 }}>
              Annual opportunity breakdown
            </div>
          </div>
          <RevenueBreakdownChart results={results} />
          <div
            style={{
              marginTop: 20,
              padding: "14px 16px",
              background: `linear-gradient(135deg, ${tokens.slate50}, ${tokens.primarySoft})`,
              borderRadius: 10,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              border: `1px solid ${tokens.slate200}`,
            }}
          >
            <span style={{ fontSize: 12, color: tokens.slate500, fontWeight: 700, textTransform: "uppercase" as const, letterSpacing: "0.05em" }}>Total</span>
            <AnimatedNumber
              value={results.totalOpportunity}
              format={fmtFull$}
              className="gradient-text"
              style={{ fontSize: 17, fontWeight: 800 }}
            />
          </div>
        </div>

        {/* Timeline */}
        <div
          className="premium-card premium-shadow roi-chart-card"
          style={{
            padding: 24,
          }}
        >
          <div style={{ marginBottom: 16 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: tokens.slate800 }}>
                12-Month Revenue Ramp
              </div>
              <span
                aria-label="This is a projection"
                style={{
                  fontSize: 9,
                  fontWeight: 800,
                  textTransform: "uppercase" as const,
                  letterSpacing: "0.08em",
                  color: tokens.warningStrong,
                  background: tokens.warningSoft,
                  padding: "2px 6px",
                  borderRadius: 4,
                }}
              >
                PROJECTED
              </span>
            </div>
            <div style={{ fontSize: 12, color: tokens.slate400, marginTop: 2 }}>
              Cumulative revenue impact — projection, not a guarantee
            </div>
          </div>
          <TimelineChart monthlyRevenue={results.totalOpportunity / 12} />
          <div style={{ fontSize: 11, color: tokens.slate400, marginTop: 6, textAlign: "center" }}>
            S-curve ramp assumes gradual workflow adoption
          </div>
        </div>
      </div>

      {/* ── Pricing Section ── */}
      <div className="animate-in" style={{ animationDelay: "0.3s" }}>
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              background: tokens.primarySoft,
              color: tokens.primary,
              fontSize: 12,
              fontWeight: 700,
              padding: "5px 14px",
              borderRadius: 999,
              marginBottom: 14,
              letterSpacing: "0.04em",
            }}
          >
            <Zap size={12} />
            TRANSPARENT PRICING
          </div>
          <h2
            style={{
              margin: 0,
              fontSize: 30,
              fontWeight: 800,
              color: tokens.slate800,
              letterSpacing: "-0.02em",
            }}
          >
            Choose Your Plan
          </h2>
          <p
            style={{
              margin: "10px auto 0",
              fontSize: 15,
              color: tokens.slate500,
              maxWidth: 480,
              lineHeight: 1.6,
            }}
          >
            All plans include a 30-day free trial. No credit card required.
            {inputs.members > 0 && (
              <>
                {" "}For {inputs.members.toLocaleString()} members, Professional would cost{" "}
                <strong style={{ color: tokens.primary }}>{annualPro}/yr</strong>.
              </>
            )}
          </p>
        </div>

        <div className="pricing-row">
          <PricingCard
            name="Starter"
            price="$0.75"
            priceNote="PMPM"
            annualCost={`~${fmtFull$(0.75 * Math.min(inputs.members, 25000) * 12)}/yr for your size`}
            features={[
              "Up to 25,000 members",
              "RAF calculation engine",
              "HCC suspect detection",
              "Basic reporting dashboard",
              "CSV data export",
              "Email support",
            ]}
            cta="Start Free Trial"
          />
          <PricingCard
            name="Professional"
            price="$1.50"
            priceNote="PMPM"
            highlight
            badge="Most Popular"
            annualCost={`~${fmtFull$(1.5 * Math.min(inputs.members, 100000) * 12)}/yr for your size`}
            features={[
              "Up to 100,000 members",
              "Everything in Starter",
              "NLP clinical note analysis",
              "Provider scorecards",
              "FHIR R4 integration",
              "Document upload & parsing",
              "AWV optimization module",
              "Priority support (4h SLA)",
            ]}
            cta="Start Free Trial"
          />
          <PricingCard
            name="Enterprise"
            price="Custom"
            priceNote="pricing"
            badge="Full Platform"
            features={[
              "Unlimited members",
              "Everything in Professional",
              "RAPS/EDPS submission",
              "Custom EHR integrations",
              "Dedicated success manager",
              "99.9% uptime SLA",
              "HIPAA BAA included",
              "On-premise deployment option",
            ]}
            cta="Contact Sales"
            ctaHref="mailto:sales@rafintelligence.ai"
          />
        </div>

        {/* Trust Badges */}
        <div
          style={{
            marginTop: 32,
            display: "flex",
            justifyContent: "center",
            gap: 32,
            flexWrap: "wrap",
          }}
        >
          {[
            "HIPAA Compliant",
            "SOC 2 Type II",
            "HITRUST Certified",
            "99.9% Uptime SLA",
            "No Credit Card Required",
          ].map((badge) => (
            <div
              key={badge}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 7,
                fontSize: 13,
                color: tokens.slate500,
                fontWeight: 500,
              }}
            >
              <CheckCircle size={15} color={tokens.success} />
              {badge}
            </div>
          ))}
        </div>
      </div>

      {/* ── CTA Footer Band ── */}
      <div
        className="animate-in mesh-pattern"
        style={{
          marginTop: 40,
          background: `linear-gradient(135deg, ${tokens.slate900} 0%, #1E3A8A 60%, ${tokens.primary} 100%)`,
          borderRadius: 14,
          padding: "40px 48px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 24,
          position: "relative",
          overflow: "hidden",
          animationDelay: "0.4s",
        }}
      >
        <div
          style={{
            position: "absolute",
            top: -80,
            right: -80,
            width: 320,
            height: 320,
            borderRadius: "50%",
            background: "rgba(59,130,246,0.1)",
            pointerEvents: "none",
          }}
        />
        <div>
          <h3
            style={{
              margin: "0 0 8px",
              fontSize: 24,
              fontWeight: 800,
              color: tokens.white,
              letterSpacing: "-0.02em",
            }}
          >
            Ready to capture{" "}
            <span style={{ color: tokens.infoBlue }}>
              {fmt$(results.totalOpportunity)}
            </span>{" "}
            in revenue?
          </h3>
          <p style={{ margin: 0, fontSize: 14, color: "rgba(255,255,255,0.65)", maxWidth: 480 }}>
            Join leading health plans and medical groups using RAF Intelligence to close
            documentation gaps and optimize risk adjustment revenue.
          </p>
        </div>
        <div style={{ display: "flex", gap: 12, flexShrink: 0 }}>
          <a
            href="mailto:sales@rafintelligence.ai"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              padding: "13px 24px",
              borderRadius: 10,
              background: tokens.white,
              color: tokens.slate900,
              fontSize: 14,
              fontWeight: 700,
              textDecoration: "none",
              transition: "opacity 0.15s",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.opacity = "0.92")}
            onMouseLeave={(e) => (e.currentTarget.style.opacity = "1")}
          >
            Talk to Sales
            <ChevronRight size={16} />
          </a>
          <a
            href="#"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
              padding: "13px 24px",
              borderRadius: 10,
              background: "rgba(255,255,255,0.12)",
              color: tokens.white,
              fontSize: 14,
              fontWeight: 600,
              textDecoration: "none",
              border: "1px solid rgba(255,255,255,0.2)",
              transition: "background 0.15s",
            }}
            onMouseEnter={(e) =>
              (e.currentTarget.style.background = "rgba(255,255,255,0.18)")
            }
            onMouseLeave={(e) =>
              (e.currentTarget.style.background = "rgba(255,255,255,0.12)")
            }
          >
            Start Free Trial
          </a>
        </div>
      </div>
    </div>
  );
}
