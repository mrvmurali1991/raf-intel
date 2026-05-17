"use client";

/**
 * ProviderSuspectHotlist
 * ----------------------
 * Real-time "what should I action THIS WEEK" panel for the provider drawer.
 *
 * Backed by GET /api/providers/{id}/suspect-hotlist which returns the top
 * open suspects across the provider's panel ranked by a blended urgency
 * score (confidence + expected $ + days_open).
 *
 * UX:
 *   - Header strip with "X open / Y high-confidence / $Z avg per code".
 *   - Confidence threshold filter (0.5 / 0.7 / 0.9).
 *   - List of compact cards, color-coded by urgency:
 *       red    : urgency >= 0.8
 *       amber  : 0.6 <= urgency < 0.8
 *       blue   : urgency < 0.6
 *   - Each card links to the patient detail page.
 *   - Auto-refreshes every 60s via React Query.
 *
 * Design language matches the rest of the providers page (slate / blue /
 * emerald / amber / red palette).
 */
import React from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  getProviderSuspectHotlist,
  type ProviderSuspectHotlist,
  type SuspectHotlistItem,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Tokens (mirrors providers/page.tsx so the panel feels native to the drawer)
// ---------------------------------------------------------------------------
const T = {
  white: "#FFFFFF",
  slate900: "#0F172A",
  slate700: "#334155",
  slate500: "#64748B",
  slate400: "#64748B",
  slate300: "#CBD5E1",
  slate200: "#E2E8F0",
  slate100: "#F1F5F9",
  slate50: "#F8FAFC",
  blue600: "#2563EB",
  blue50: "#EFF6FF",
  amber600: "#D97706",
  amber500: "#F59E0B",
  amber50: "#FFFBEB",
  red600: "#DC2626",
  red500: "#EF4444",
  red50: "#FEF2F2",
  emerald600: "#059669",
  emerald50: "#ECFDF5",
};

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------
function fmt$(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "—";
  const abs = Math.abs(n);
  if (abs >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `$${(n / 1_000).toFixed(1)}k`;
  return `$${Math.round(n).toLocaleString()}`;
}

function urgencyTone(score: number): { fg: string; bg: string; border: string; label: string } {
  if (score >= 0.8) {
    return { fg: T.red600, bg: T.red50, border: T.red500, label: "Urgent" };
  }
  if (score >= 0.6) {
    return { fg: T.amber600, bg: T.amber50, border: T.amber500, label: "High" };
  }
  return { fg: T.blue600, bg: T.blue50, border: T.blue600, label: "Watch" };
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------
interface Props {
  providerId: number | string;
  year?: number;
  limit?: number;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
const CONFIDENCE_OPTIONS = [
  { label: "All", value: 0.0 },
  { label: ">= 0.50", value: 0.5 },
  { label: ">= 0.70", value: 0.7 },
  { label: ">= 0.90", value: 0.9 },
];

export default function ProviderSuspectHotlist({
  providerId,
  year,
  limit = 20,
}: Props) {
  const [minConfidence, setMinConfidence] = React.useState<number>(0.0);

  const q = useQuery<ProviderSuspectHotlist>({
    queryKey: ["provider-suspect-hotlist", providerId, year, limit, minConfidence],
    queryFn: () =>
      getProviderSuspectHotlist(providerId, {
        year,
        limit,
        minConfidence,
      }),
    // Real-time feel: poll every 60s, treat as stale immediately on focus.
    refetchInterval: 60_000,
    staleTime: 60_000,
    refetchOnWindowFocus: true,
  });

  return (
    <Card>
      <Header
        loading={q.isLoading}
        summary={q.data?.summary}
        minConfidence={minConfidence}
        onChangeMinConfidence={setMinConfidence}
      />

      {q.isError ? (
        <div style={{ padding: 16, color: T.red600, fontSize: 13 }}>
          Hot-list unavailable. {(q.error as Error)?.message ?? ""}
        </div>
      ) : q.isLoading ? (
        <div style={{ padding: 24, color: T.slate500, fontSize: 13, textAlign: "center" }}>
          Calculating urgency scores…
        </div>
      ) : !q.data || q.data.items.length === 0 ? (
        <EmptyState minConfidence={minConfidence} />
      ) : (
        <ItemList items={q.data.items} />
      )}

      <Footer year={q.data?.measurement_year ?? year} />
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------
function Card({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        background: T.white,
        border: `1px solid ${T.slate200}`,
        borderRadius: 12,
        boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)",
        overflow: "hidden",
      }}
    >
      {children}
    </div>
  );
}

function Header({
  loading,
  summary,
  minConfidence,
  onChangeMinConfidence,
}: {
  loading: boolean;
  summary: ProviderSuspectHotlist["summary"] | undefined;
  minConfidence: number;
  onChangeMinConfidence: (v: number) => void;
}) {
  return (
    <div
      style={{
        padding: "16px 18px",
        borderBottom: `1px solid ${T.slate100}`,
        background: T.slate50,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "flex-start",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div>
          <div
            style={{
              fontSize: 10,
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.06em",
              color: T.slate400,
              marginBottom: 4,
            }}
          >
            Real-Time Suspect Hot-List
          </div>
          <div style={{ fontSize: 16, fontWeight: 700, color: T.slate900 }}>
            Action this week
          </div>
        </div>

        {/* Confidence filter */}
        <div
          role="radiogroup"
          aria-label="Minimum confidence filter"
          style={{
            display: "inline-flex",
            background: T.white,
            border: `1px solid ${T.slate200}`,
            borderRadius: 8,
            padding: 2,
          }}
        >
          {CONFIDENCE_OPTIONS.map((opt) => {
            const active = Math.abs(opt.value - minConfidence) < 1e-6;
            return (
              <button
                key={opt.value}
                role="radio"
                aria-checked={active}
                onClick={() => onChangeMinConfidence(opt.value)}
                style={{
                  border: "none",
                  background: active ? T.blue600 : "transparent",
                  color: active ? T.white : T.slate500,
                  fontSize: 11,
                  fontWeight: 600,
                  padding: "5px 10px",
                  borderRadius: 6,
                  cursor: "pointer",
                  letterSpacing: "0.02em",
                }}
              >
                {opt.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Summary strip */}
      <div
        style={{
          marginTop: 12,
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 12,
        }}
      >
        <Stat
          label="Open"
          value={loading ? "…" : (summary?.total_open ?? 0).toLocaleString()}
          color={T.slate900}
        />
        <Stat
          label={`High-Confidence (>= ${
            summary?.high_confidence_threshold
              ? Math.round(summary.high_confidence_threshold * 100)
              : 80
          }%)`}
          value={loading ? "…" : (summary?.high_confidence_count ?? 0).toLocaleString()}
          color={T.emerald600}
        />
        <Stat
          label="Avg $ / Code"
          value={loading ? "…" : fmt$(summary?.avg_dollars_per_suspect ?? 0)}
          color={T.blue600}
        />
      </div>
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div>
      <div
        style={{
          fontSize: 10,
          fontWeight: 600,
          textTransform: "uppercase",
          letterSpacing: "0.04em",
          color: T.slate400,
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: 16, fontWeight: 700, color, lineHeight: 1.1 }}>
        {value}
      </div>
    </div>
  );
}

function ItemList({ items }: { items: SuspectHotlistItem[] }) {
  return (
    <ul
      style={{
        listStyle: "none",
        margin: 0,
        padding: "12px 12px 14px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      {items.map((it) => (
        <SuspectCard key={it.suspect_id} item={it} />
      ))}
    </ul>
  );
}

function SuspectCard({ item }: { item: SuspectHotlistItem }) {
  const tone = urgencyTone(item.urgency_score);
  return (
    <li>
      <Link
        href={`/patients/${item.patient_id}`}
        style={{
          display: "block",
          textDecoration: "none",
          color: "inherit",
        }}
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr auto",
            gap: 12,
            alignItems: "center",
            padding: "12px 14px",
            border: `1px solid ${T.slate200}`,
            borderLeft: `4px solid ${tone.border}`,
            borderRadius: 10,
            background: T.white,
            transition: "background 120ms ease",
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLDivElement).style.background = T.slate50;
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLDivElement).style.background = T.white;
          }}
        >
          <div style={{ minWidth: 0 }}>
            {/* Top row: patient + urgency tag */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                marginBottom: 6,
                flexWrap: "wrap",
              }}
            >
              <span
                style={{
                  fontSize: 13,
                  fontWeight: 700,
                  color: T.slate900,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  maxWidth: 220,
                }}
              >
                {item.patient_name}
              </span>
              <Pill
                fg={tone.fg}
                bg={tone.bg}
                label={`${tone.label} · ${(item.urgency_score * 100).toFixed(0)}`}
              />
            </div>

            {/* Bottom row: HCC chip + label + confidence + $ + days */}
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                flexWrap: "wrap",
                fontSize: 12,
              }}
            >
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  padding: "2px 8px",
                  background: T.blue50,
                  color: T.blue600,
                  borderRadius: 6,
                  fontWeight: 700,
                  fontSize: 11,
                  letterSpacing: "0.02em",
                }}
              >
                HCC {item.hcc_code}
              </span>
              <span
                style={{
                  color: T.slate700,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  maxWidth: 260,
                }}
                title={item.hcc_label}
              >
                {item.hcc_label}
              </span>
              {item.icd10 ? (
                <span
                  style={{
                    color: T.slate500,
                    fontFamily: "monospace",
                    fontSize: 11,
                  }}
                >
                  {item.icd10}
                </span>
              ) : null}
              <Pill
                fg={T.emerald600}
                bg={T.emerald50}
                label={`${(item.confidence * 100).toFixed(0)}% conf`}
              />
              <Pill
                fg={T.slate700}
                bg={T.slate100}
                label={fmt$(item.expected_dollars)}
              />
              <span style={{ color: T.slate400, fontSize: 11 }}>
                {item.days_open} day{item.days_open === 1 ? "" : "s"} open
              </span>
            </div>
          </div>
        </div>
      </Link>
    </li>
  );
}

function Pill({ fg, bg, label }: { fg: string; bg: string; label: string }) {
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        background: bg,
        color: fg,
        fontSize: 11,
        fontWeight: 700,
        borderRadius: 999,
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </span>
  );
}

function EmptyState({ minConfidence }: { minConfidence: number }) {
  return (
    <div
      style={{
        padding: 24,
        textAlign: "center",
        color: T.slate500,
        fontSize: 13,
      }}
    >
      {minConfidence > 0 ? (
        <>No open suspects at confidence ≥ {Math.round(minConfidence * 100)}%.</>
      ) : (
        <>No open suspects in this panel. Run a suspect scan to surface coding opportunities.</>
      )}
    </div>
  );
}

function Footer({ year }: { year: number | undefined }) {
  return (
    <div
      style={{
        padding: "8px 16px",
        borderTop: `1px solid ${T.slate100}`,
        fontSize: 10,
        color: T.slate400,
        background: T.slate50,
        lineHeight: 1.5,
      }}
    >
      Urgency = 0.5·confidence + 0.3·($/max panel $) + 0.2·(days open / 90) ·
      auto-refresh 60s{year ? ` · year ${year}` : ""}
    </div>
  );
}
