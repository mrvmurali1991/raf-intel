"use client";

/**
 * HccExplainCard — static "What is HCC X?" card surfaced as a hover popover
 * on every HCC chip across the app. Calls GET /api/kg/query/explain/{hcc}.
 */

import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import { getHccExplanation } from "@/lib/api";

interface HccExplainCardProps {
  hccCode: string;
  /** Render mode: inline card or anchored popover. */
  mode?: "card" | "popover";
  style?: CSSProperties;
}

interface HccExplainShape {
  hcc_code?: string;
  label?: string;
  name?: string;
  description?: string;
  definition?: string;
  top_icd10s?: Array<string | { code: string; description?: string }>;
  common_drugs?: Array<string | { name?: string; atc?: string }>;
  common_labs?: Array<string | { code?: string; name?: string }>;
  comorbid_hccs?: Array<string | { hcc_code?: string; label?: string }>;
  citations?: Array<string | { text?: string; href?: string }>;
}

function isHccExplainShape(x: unknown): x is HccExplainShape {
  return typeof x === "object" && x !== null;
}

function asString(item: string | { [k: string]: unknown }, ...keys: string[]): string {
  if (typeof item === "string") return item;
  for (const k of keys) {
    const v = item?.[k];
    if (typeof v === "string" && v) return v;
  }
  return "";
}

function asListString(
  list: HccExplainShape["top_icd10s" | "common_drugs" | "common_labs" | "comorbid_hccs"] | undefined,
  ...keys: string[]
): string[] {
  if (!Array.isArray(list)) return [];
  return list
    .map((item) => {
      if (typeof item === "string") return item;
      if (typeof item === "object" && item !== null) {
        return asString(item as { [k: string]: unknown }, ...keys);
      }
      return "";
    })
    .filter(Boolean);
}

const SECTION_TITLE: CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  letterSpacing: 0.6,
  textTransform: "uppercase",
  color: "#64748B",
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
  const label = data.label ?? data.name ?? "";
  const description = data.description ?? data.definition ?? "";
  const icds = asListString(data.top_icd10s, "code", "icd10");
  const drugs = asListString(data.common_drugs, "name", "atc");
  const labs = asListString(data.common_labs, "name", "code");
  const comorbid = asListString(data.comorbid_hccs, "hcc_code", "label");
  const citations = (data.citations ?? []).map((c) => {
    if (typeof c === "string") return { text: c, href: undefined as string | undefined };
    if (typeof c === "object" && c !== null) {
      const obj = c as { text?: string; href?: string };
      return { text: obj.text ?? "", href: obj.href };
    }
    return { text: "", href: undefined };
  });

  return (
    <CardShell mode={mode} style={style}>
      <div style={{ fontSize: 11, color: "#64748B", letterSpacing: 0.5, fontWeight: 600 }}>
        WHAT IS THIS?
      </div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 2 }}>
        <span
          style={{
            fontSize: 14,
            fontWeight: 700,
            fontFamily: "monospace",
            background: "#FEE2E2",
            color: "#B91C1C",
            padding: "2px 6px",
            borderRadius: 4,
          }}
        >
          HCC {data.hcc_code ?? hccCode}
        </span>
        {label ? <span style={{ fontSize: 13, color: "#0F172A", fontWeight: 600 }}>{label}</span> : null}
      </div>
      {description ? (
        <p style={{ fontSize: 12, color: "#475569", margin: "8px 0 0", lineHeight: 1.5 }}>
          {description}
        </p>
      ) : null}

      {icds.length > 0 ? (
        <>
          <div style={SECTION_TITLE}>Top ICD-10s</div>
          <ChipRow items={icds} tone="purple" />
        </>
      ) : null}

      {drugs.length > 0 ? (
        <>
          <div style={SECTION_TITLE}>Common drugs</div>
          <ChipRow items={drugs} tone="green" />
        </>
      ) : null}

      {labs.length > 0 ? (
        <>
          <div style={SECTION_TITLE}>Common labs</div>
          <ChipRow items={labs} tone="orange" />
        </>
      ) : null}

      {comorbid.length > 0 ? (
        <>
          <div style={SECTION_TITLE}>Comorbid HCCs</div>
          <ChipRow items={comorbid.map((h) => (h.startsWith("HCC") ? h : `HCC ${h}`))} tone="red" />
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
              color: "#475569",
              display: "flex",
              flexDirection: "column",
              gap: 3,
            }}
          >
            {citations.map((c, i) => (
              <li key={i}>
                {c.href ? (
                  <a
                    href={c.href}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: "#2563EB", textDecoration: "underline" }}
                  >
                    {c.text || c.href}
                  </a>
                ) : (
                  c.text
                )}
              </li>
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
        background: "#FFFFFF",
        border: "1px solid #E2E8F0",
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
  purple: { bg: "#EDE9FE", fg: "#6D28D9", border: "#DDD6FE" },
  green: { bg: "#D1FAE5", fg: "#047857", border: "#A7F3D0" },
  orange: { bg: "#FFEDD5", fg: "#C2410C", border: "#FED7AA" },
  red: { bg: "#FEE2E2", fg: "#B91C1C", border: "#FECACA" },
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
            background: "#FEE2E2",
            color: "#B91C1C",
            border: "1px solid #FECACA",
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
