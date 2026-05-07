"use client";

/**
 * HccExplainCard — static "What is HCC X?" card surfaced as a hover popover
 * on every HCC chip across the app. Calls GET /api/kg/query/explain/{hcc}.
 */

import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { getHccExplanation } from "@/lib/api";
import { tokens } from "@/styles/tokens";

interface HccExplainCardProps {
  hccCode: string;
  /** Render mode: inline card or anchored popover. */
  mode?: "card" | "popover";
  style?: CSSProperties;
}

/**
 * Matches the live API response from kg_lookup_service.explain_hcc:
 * {
 *   hcc: string,
 *   definition: { label?: string; model?: string },
 *   icd10_codes: string[],
 *   common_drugs: string[],
 *   common_labs: string[],
 *   common_comorbidities: string[],
 *   citations: string[],
 * }
 */
interface HccApiDefinition {
  label?: string;
  model?: string;
}

interface HccExplainShape {
  hcc?: string;
  definition?: HccApiDefinition;
  icd10_codes?: string[];
  common_drugs?: string[];
  common_labs?: string[];
  common_comorbidities?: string[];
  citations?: string[];
}

function isHccExplainShape(x: unknown): x is HccExplainShape {
  return typeof x === "object" && x !== null;
}

const SECTION_TITLE: CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: 0.6,
  textTransform: "uppercase",
  color: tokens.slate500,
  marginTop: 12,
  marginBottom: 4,
};

export function HccExplainCard({ hccCode, mode = "card", style }: HccExplainCardProps) {
  const query = useQuery({
    queryKey: ["hcc-explain", hccCode],
    queryFn: () => getHccExplanation(hccCode),
    enabled: !!hccCode,
    staleTime: 5 * 60 * 1000,
  });

  if (query.isLoading) {
    return (
      <CardShell mode={mode} style={style}>
        <div style={{ fontSize: 12, color: "#64748B" }}>Loading HCC {hccCode}...</div>
      </CardShell>
    );
  }

  if (query.isError || !isHccExplainShape(query.data)) {
    return (
      <CardShell mode={mode} style={style}>
        <div style={{ fontSize: 12, color: "#B91C1C" }}>
          Could not load HCC {hccCode}.
        </div>
      </CardShell>
    );
  }

  const data = query.data;

  // Map the real API field names → display values
  const displayCode = data.hcc ?? hccCode;
  const label = data.definition?.label ?? "";
  const modelLabel = data.definition?.model ?? "";
  const icds = Array.isArray(data.icd10_codes) ? data.icd10_codes.filter(Boolean) : [];
  const drugs = Array.isArray(data.common_drugs) ? data.common_drugs.filter(Boolean) : [];
  const labs = Array.isArray(data.common_labs) ? data.common_labs.filter(Boolean) : [];
  const comorbid = Array.isArray(data.common_comorbidities)
    ? data.common_comorbidities.filter(Boolean)
    : [];
  const citations = Array.isArray(data.citations) ? data.citations.filter(Boolean) : [];

  const hasContent =
    label || icds.length > 0 || drugs.length > 0 || labs.length > 0 ||
    comorbid.length > 0 || citations.length > 0;

  return (
    <CardShell mode={mode} style={style}>
      <div style={{ fontSize: 11, color: tokens.slate500, letterSpacing: 0.5, fontWeight: 600 }}>
        WHAT IS THIS?
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 2 }}>
        <span
          style={{
            fontSize: 14,
            fontWeight: 700,
            fontFamily: "monospace",
            background: tokens.dangerSoft,
            color: tokens.danger,
            padding: "2px 6px",
            borderRadius: 4,
          }}
        >
          HCC {displayCode}
        </span>
        {label ? (
          <span style={{ fontSize: 13, color: tokens.slate900, fontWeight: 600 }}>{label}</span>
        ) : null}
      </div>

      {modelLabel ? (
        <div style={{ marginTop: 4, fontSize: 10, color: tokens.slate400, fontStyle: "italic" }}>
          {modelLabel}
        </div>
      ) : null}

      {!hasContent ? (
        <p style={{ fontSize: 12, color: tokens.slate500, margin: "8px 0 0", lineHeight: 1.5 }}>
          No additional detail available for HCC {displayCode}.
        </p>
      ) : null}

      {icds.length > 0 ? (
        <>
          <div style={SECTION_TITLE}>Top ICD-10 Codes</div>
          <ChipRow items={icds} tone="purple" />
        </>
      ) : null}

      {drugs.length > 0 ? (
        <>
          <div style={SECTION_TITLE}>Common Drugs</div>
          <ChipRow items={drugs} tone="green" />
        </>
      ) : null}

      {labs.length > 0 ? (
        <>
          <div style={SECTION_TITLE}>Common Labs</div>
          <ChipRow items={labs} tone="orange" />
        </>
      ) : null}

      {comorbid.length > 0 ? (
        <>
          <div style={SECTION_TITLE}>Comorbid HCCs</div>
          <ChipRow
            items={comorbid.map((h) => (h.startsWith("HCC") ? h : `HCC ${h}`))}
            tone="red"
          />
        </>
      ) : null}

      {citations.length > 0 ? (
        <>
          <div style={SECTION_TITLE}>Citations</div>
          <ul
            style={{
              margin: 0,
              padding: 0,
              listStyle: "none",
              fontSize: 11,
              color: tokens.slate600,
              display: "flex",
              flexDirection: "column",
              gap: 3,
            }}
          >
            {citations.map((c, i) => (
              <li key={`citation-${i}`}>{c}</li>
            ))}
          </ul>
        </>
      ) : null}
    </CardShell>
  );
}

function CardShell({
  mode,
  style,
  children,
}: {
  mode: "card" | "popover";
  style?: CSSProperties;
  children: ReactNode;
}) {
  return (
    <div
      data-testid="hcc-explain-card"
      style={{
        background: tokens.white,
        border: `1px solid ${tokens.slate200}`,
        borderRadius: 10,
        padding: 14,
        boxShadow: mode === "popover" ? "0 8px 24px rgba(15, 23, 42, 0.12)" : undefined,
        maxWidth: mode === "popover" ? 320 : undefined,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

const TONE_PALETTE: Record<string, { bg: string; fg: string; border: string }> = {
  purple: { bg: tokens.violetBg, fg: tokens.violetText, border: tokens.violetBorder },
  green:  { bg: tokens.emerald100, fg: tokens.successDark, border: tokens.emerald300 },
  orange: { bg: tokens.orangeBg, fg: tokens.orangeText, border: tokens.orangeBorder },
  red:    { bg: tokens.dangerSoft, fg: tokens.danger, border: tokens.dangerBorder },
};

function ChipRow({ items, tone }: { items: string[]; tone: keyof typeof TONE_PALETTE }) {
  const palette = TONE_PALETTE[tone];
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
      {items.slice(0, 8).map((it, i) => (
        <span
          key={`${it}-${i}`}
          style={{
            display: "inline-block",
            fontSize: 11,
            fontFamily: "monospace",
            fontWeight: 600,
            padding: "2px 6px",
            borderRadius: 4,
            background: palette.bg,
            color: palette.fg,
            border: `1px solid ${palette.border}`,
          }}
        >
          {it}
        </span>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// HccChipWithPopover — a wrapper that renders an HCC chip and shows the
// HccExplainCard as an anchored popover on hover/focus. Drop-in replacement
// across recapture/providers/suspects pages.
// ---------------------------------------------------------------------------

interface HccChipWithPopoverProps {
  hccCode: string;
  /** Children rendered as the visible chip; defaults to "HCC {code}". */
  children?: ReactNode;
  style?: CSSProperties;
}

export function HccChipWithPopover({ hccCode, children, style }: HccChipWithPopoverProps) {
  const [open, setOpen] = useState(false);
  const [hovering, setHovering] = useState(false);

  // Defer mounting the card until the user hovers — avoids N x kg/explain calls
  // when long lists of HCCs render at once.
  useEffect(() => {
    if (!hovering) {
      const t = window.setTimeout(() => setOpen(false), 100);
      return () => window.clearTimeout(t);
    }
    setOpen(true);
    return undefined;
  }, [hovering]);

  return (
    <span
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
      onFocus={() => setHovering(true)}
      onBlur={() => setHovering(false)}
      tabIndex={0}
      style={{ position: "relative", display: "inline-block", ...style }}
    >
      {children ?? (
        <span
          style={{
            display: "inline-block",
            fontSize: 11,
            fontFamily: "monospace",
            fontWeight: 700,
            padding: "2px 6px",
            borderRadius: 4,
            background: tokens.dangerSoft,
            color: tokens.danger,
            border: `1px solid ${tokens.dangerBorder}`,
            cursor: "help",
          }}
        >
          HCC {hccCode}
        </span>
      )}
      {open ? (
        <span
          role="tooltip"
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            zIndex: 50,
            marginTop: 4,
          }}
        >
          <HccExplainCard hccCode={hccCode} mode="popover" />
        </span>
      ) : null}
    </span>
  );
}

export default HccExplainCard;
