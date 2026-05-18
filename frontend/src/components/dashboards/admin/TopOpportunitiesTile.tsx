"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Target, ChevronRight, CheckCircle } from "lucide-react";
import type { TopOpportunity } from "@/lib/api";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from "@/components/ui/tooltip";

// ---------------------------------------------------------------------------
// Shared card style
// ---------------------------------------------------------------------------

const card: React.CSSProperties = {
  background: "hsl(var(--card))",
  border: "1px solid hsl(var(--border))",
  borderRadius: 14,
  boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
  padding: 24,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmt$(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `$${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `$${Math.round(abs / 1_000)}K`;
  return `$${Math.round(abs)}`;
}

function Pulse({ w, h, r = 6 }: { w: string | number; h: number; r?: number }) {
  return (
    <div
      className="shimmer"
      style={{ width: w, height: h, borderRadius: r }}
    />
  );
}

function ConfidenceDots({ score }: { score: number }) {
  const filled = Math.round(score * 5);
  return (
    <span
      style={{ display: "inline-flex", gap: 3, alignItems: "center" }}
      aria-label={`Confidence ${Math.round(score * 100)}%`}
    >
      {Array.from({ length: 5 }, (_, i) => (
        <span
          key={i}
          style={{
            width: 7,
            height: 7,
            borderRadius: "50%",
            background: i < filled ? "#10B981" : "#E2E8F0",
            boxShadow: i < filled ? "0 0 4px rgba(16,185,129,0.5)" : "none",
            flexShrink: 0,
          }}
        />
      ))}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface TopOpportunitiesTileProps {
  opportunities: TopOpportunity[];
  isLoading: boolean;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TopOpportunitiesTile({
  opportunities,
  isLoading,
}: TopOpportunitiesTileProps) {
  const router = useRouter();

  return (
    <TooltipProvider delay={200}>
    <div
      style={{
        ...card,
        marginBottom: 24,
      }}
      role="region"
      aria-label="Top 5 RAF Capture Opportunities"
      data-testid="top-opportunities-tile"
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 16,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div
            style={{
              background: "#D1FAE5",
              borderRadius: 10,
              padding: 8,
              border: "1px solid #6EE7B7",
            }}
          >
            <Target size={18} color="#059669" />
          </div>
          <div>
            <h3 className="text-foreground text-[15px] font-bold m-0 leading-tight">
              Top 5 RAF Capture Opportunities
            </h3>
            <p className="text-muted-foreground text-[12px] mt-0.5 mb-0">
              Closing in 14 days — ranked by RAF lift x confidence
            </p>
          </div>
        </div>
        <Link
          href="/suspects"
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: "#059669",
            textDecoration: "none",
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}
        >
          View All <ChevronRight size={13} />
        </Link>
      </div>

      {/* Table */}
      {isLoading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {Array.from({ length: 3 }, (_, i) => (
            <Pulse key={i} w="100%" h={40} r={8} />
          ))}
        </div>
      ) : opportunities.length === 0 ? (
        <div style={{ padding: "24px 0", textAlign: "center", color: "#6B7280", fontSize: 13 }}>
          <CheckCircle
            size={28}
            color="#10B981"
            style={{ margin: "0 auto 8px", display: "block" }}
          />
          No more high-priority opportunities this period
        </div>
      ) : (
        <>
          {/* Column headers */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "2fr 2fr 1fr 1fr 80px",
              gap: 8,
              padding: "0 8px 6px",
              borderBottom: "1px solid #D1FAE5",
              marginBottom: 4,
            }}
          >
            {["Patient", "Condition", "Confidence", "$ At Risk", "Days Left"].map((h) => (
              <span
                key={h}
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  color: "#6B7280",
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                }}
              >
                {h}
              </span>
            ))}
          </div>

          {/* Rows */}
          {opportunities.map((opp, i) => (
            <div
              key={opp.patient_id}
              role="button"
              tabIndex={0}
              aria-label={`Open details for ${opp.patient_name}`}
              onClick={() =>
                router.push(`/suspects?patient_id=${opp.patient_id}`)
              }
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  router.push(`/suspects?patient_id=${opp.patient_id}`);
                }
              }}
              style={{
                display: "grid",
                gridTemplateColumns: "2fr 2fr 1fr 1fr 80px",
                gap: 8,
                padding: "10px 8px",
                borderRadius: 8,
                cursor: "pointer",
                borderBottom:
                  i < opportunities.length - 1 ? "1px solid #ECFDF5" : "none",
                transition: "background 0.15s",
                alignItems: "center",
              }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.background = "rgba(16,185,129,0.06)")
              }
              onMouseLeave={(e) =>
                (e.currentTarget.style.background = "transparent")
              }
            >
              <span
                style={{
                  fontSize: 13,
                  fontWeight: 600,
                  color: "#111827",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {opp.patient_name}
              </span>

              <span
                style={{
                  fontSize: 12,
                  color: "#374151",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
                title={opp.condition}
              >
                {opp.condition}
              </span>

              <Tooltip>
                <TooltipTrigger
                  style={{ background: "none", border: "none", padding: 0, cursor: "pointer" }}
                  data-testid={`tooltip-opportunity-confidence-${opp.patient_id}`}
                >
                  <ConfidenceDots score={opp.confidence_score} />
                </TooltipTrigger>
                <TooltipContent>AI confidence that this condition is clinically present and uncoded. {Math.round(opp.confidence_score * 100)}% confidence based on clinical note evidence.</TooltipContent>
              </Tooltip>

              <Tooltip>
                <TooltipTrigger
                  style={{ background: "none", border: "none", padding: 0, cursor: "pointer" }}
                  data-testid={`tooltip-opportunity-revenue-${opp.patient_id}`}
                >
                  <span
                    style={{
                      fontSize: 13,
                      fontWeight: 700,
                      color: "#065F46",
                      fontVariantNumeric: "tabular-nums",
                    }}
                  >
                    {fmt$(opp.revenue_at_risk)}
                  </span>
                </TooltipTrigger>
                <TooltipContent>Estimated annual revenue at risk if this condition is not coded: RAF lift &times; $11,015 per RAF point, weighted by confidence score.</TooltipContent>
              </Tooltip>

              <Tooltip>
                <TooltipTrigger
                  style={{ background: "none", border: "none", padding: 0, cursor: "pointer" }}
                  data-testid={`tooltip-opportunity-days-${opp.patient_id}`}
                >
                  <span
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      justifyContent: "center",
                      padding: "3px 10px",
                      borderRadius: 10,
                      fontSize: 11,
                      fontWeight: 700,
                      fontVariantNumeric: "tabular-nums",
                      background: opp.days_remaining < 7 ? "#FEF3C7" : "#D1FAE5",
                      color: opp.days_remaining < 7 ? "#92400E" : "#065F46",
                      border:
                        opp.days_remaining < 7
                          ? "1px solid #FDE68A"
                          : "1px solid #A7F3D0",
                      width: "fit-content",
                    }}
                    aria-label={`${opp.days_remaining} days remaining`}
                  >
                    {opp.days_remaining}d
                  </span>
                </TooltipTrigger>
                <TooltipContent>Days until the next CMS submission window closes. Code this condition before then to capture the revenue this payment year.</TooltipContent>
              </Tooltip>
            </div>
          ))}

          {opportunities.length < 5 && opportunities.length > 0 && (
            <div
              style={{
                padding: "10px 8px",
                fontSize: 12,
                color: "#6B7280",
                fontStyle: "italic",
                borderTop: "1px solid #ECFDF5",
                marginTop: 4,
              }}
            >
              No more high-priority opportunities this period
            </div>
          )}
        </>
      )}
    </div>
    </TooltipProvider>
  );
}
