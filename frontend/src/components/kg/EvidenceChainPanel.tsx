"use client";

/**
 * EvidenceChainPanel — the user-visible "Why this HCC?" panel.
 *
 * Layout (top → bottom):
 *   1. Header        — HCC code + label + final confidence pill
 *   2. Trigger       — list of contributing evidence facts (icon + source line)
 *   3. Reasoning     — stepwise traversal narrative (decision_tree)
 *   4. Citation      — source rule with link
 *   5. Confidence    — stacked-bar breakdown of base × demo × specialty = final
 *   6. Graph toggle  — opens an inline `KgGraphView` of the path that fired.
 */

import { useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  getEvidenceChain,
  getSuspectEvidenceChain,
  type KgEvidenceChain,
  type KgEvidenceItem,
} from "@/lib/api";
import KgGraphView, {
  type KgGraphEdge,
  type KgGraphNode,
  type OntologyKind,
} from "@/components/kg/KgGraphView";

interface EvidenceChainPanelProps {
  suspectId?: number;
  hccCode: string;
  patientId?: number;
  /** When true, the component renders only — no fetching. */
  preloaded?: KgEvidenceChain;
  year?: number;
  style?: CSSProperties;
}

// ---------------------------------------------------------------------------
// Confidence helpers
// ---------------------------------------------------------------------------

function confidenceColor(score: number): { bg: string; fg: string; border: string; label: string } {
  if (score >= 0.75) {
    return { bg: "#D1FAE5", fg: "#047857", border: "#A7F3D0", label: "High" };
  }
  if (score >= 0.5) {
    return { bg: "#FEF3C7", fg: "#92400E", border: "#FDE68A", label: "Medium" };
  }
  return { bg: "#FEE2E2", fg: "#B91C1C", border: "#FECACA", label: "Low" };
}

function ConfidencePill({ score }: { score: number }) {
  const palette = confidenceColor(score);
  return (
    <span
      aria-label={`Confidence ${(score * 100).toFixed(0)} percent (${palette.label})`}
      data-testid="confidence-pill"
      data-confidence={palette.label.toLowerCase()}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "4px 12px",
        borderRadius: 999,
        background: palette.bg,
        color: palette.fg,
        border: `1px solid ${palette.border}`,
        fontSize: 12,
        fontWeight: 700,
      }}
    >
      <span
        aria-hidden
        style={{
          width: 7,
          height: 7,
          borderRadius: "50%",
          background: palette.fg,
        }}
      />
      {palette.label} {(score * 100).toFixed(0)}%
    </span>
  );
}

// ---------------------------------------------------------------------------
// Evidence-item icon
// ---------------------------------------------------------------------------

function EvidenceIcon({ kind }: { kind: string }) {
  const k = (kind ?? "").toLowerCase();
  if (k.includes("drug") || k.includes("med") || k === "atc") {
    return <PillIcon />;
  }
  if (k.includes("lab") || k === "loinc") {
    return <LabVialIcon />;
  }
  if (k.includes("icd") || k.includes("dx") || k.includes("diagnosis")) {
    return <IcdChipIcon />;
  }
  if (k.includes("comorb")) {
    return <ComorbidityIcon />;
  }
  return <DotIcon />;
}

const ICON_BG = "#F1F5F9";

function IconWrap({ children }: { children: ReactNode }) {
  return (
    <span
      aria-hidden
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        width: 28,
        height: 28,
        borderRadius: 8,
        background: ICON_BG,
        color: "#1E293B",
        flexShrink: 0,
      }}
    >
      {children}
    </span>
  );
}

function PillIcon() {
  return (
    <IconWrap>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="3" y="9" width="18" height="6" rx="3" />
        <line x1="12" y1="9" x2="12" y2="15" />
      </svg>
    </IconWrap>
  );
}

function LabVialIcon() {
  return (
    <IconWrap>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M9 3h6v3l-2 2v9a3 3 0 0 1-6 0V8L9 6V3z" />
        <line x1="9" y1="13" x2="13" y2="13" />
      </svg>
    </IconWrap>
  );
}

function IcdChipIcon() {
  return (
    <IconWrap>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="3" y="6" width="18" height="12" rx="2" />
        <path d="M7 10h2M7 14h2M11 10h6M11 14h6" />
      </svg>
    </IconWrap>
  );
}

function ComorbidityIcon() {
  return (
    <IconWrap>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="9" cy="12" r="4" />
        <circle cx="15" cy="12" r="4" />
      </svg>
    </IconWrap>
  );
}

function DotIcon() {
  return (
    <IconWrap>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
        <circle cx="12" cy="12" r="3" />
      </svg>
    </IconWrap>
  );
}

// ---------------------------------------------------------------------------
// Citation extraction
// ---------------------------------------------------------------------------

interface ParsedCitation {
  text: string;
  href?: string;
}

function parseCitation(raw?: string): ParsedCitation | null {
  if (!raw) return null;
  // Looks for "label [view source](http://...)" or just a URL.
  const linkMatch = raw.match(/\[([^\]]+)]\(([^)]+)\)/);
  if (linkMatch) {
    return { text: raw.replace(linkMatch[0], linkMatch[1]).trim(), href: linkMatch[2] };
  }
  const urlMatch = raw.match(/https?:\/\/\S+/);
  if (urlMatch) {
    return { text: raw.replace(urlMatch[0], "").trim() || urlMatch[0], href: urlMatch[0] };
  }
  return { text: raw };
}

// ---------------------------------------------------------------------------
// Confidence breakdown (base × demo × specialty)
// ---------------------------------------------------------------------------

interface ConfidenceFactors {
  base?: number;
  demo?: number;
  specialty?: number;
  final: number;
}

function deriveFactors(chain: KgEvidenceChain): ConfidenceFactors {
  // The backend may surface multipliers in evidence_chain items with kind=multiplier.
  let demo: number | undefined;
  let specialty: number | undefined;
  for (const item of chain.evidence_chain) {
    const kind = (item.kind ?? "").toLowerCase();
    const value = typeof item.value === "number" ? item.value : undefined;
    if (kind.includes("demo") && value) demo = value;
    if (kind.includes("specialty") && value) specialty = value;
  }
  // Fall back to deriving base = final / (demo*specialty) when both are known.
  const final = chain.total_score;
  let base: number | undefined;
  if (demo && specialty && demo * specialty !== 0) {
    base = final / (demo * specialty);
  } else if (demo && demo !== 0) {
    base = final / demo;
  } else if (specialty && specialty !== 0) {
    base = final / specialty;
  }
  return { base, demo, specialty, final };
}

function ConfidenceBreakdown({ factors }: { factors: ConfidenceFactors }) {
  const segments = [
    { key: "base", label: "Base", value: factors.base, color: "#3B82F6" },
    { key: "demo", label: "Demographic", value: factors.demo, color: "#8B5CF6" },
    { key: "specialty", label: "Specialty", value: factors.specialty, color: "#10B981" },
  ].filter((s): s is { key: string; label: string; value: number; color: string } =>
    typeof s.value === "number",
  );

  if (segments.length === 0) {
    // Show only the final
    return (
      <div data-testid="confidence-breakdown" style={{ fontSize: 12, color: "#475569" }}>
        Final confidence:&nbsp;
        <strong style={{ color: "#0F172A" }}>{(factors.final * 100).toFixed(0)}%</strong>
      </div>
    );
  }

  const product = segments.reduce((acc, s) => acc * s.value, 1);

  return (
    <div data-testid="confidence-breakdown">
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontSize: 11,
          color: "#475569",
          marginBottom: 8,
        }}
      >
        {segments.map((s, i) => (
          <span key={s.key}>
            <span style={{ color: s.color, fontWeight: 700 }}>{s.value.toFixed(2)}</span>
            <span style={{ color: "#94A3B8" }}> {s.label}</span>
            {i < segments.length - 1 ? (
              <span style={{ margin: "0 6px", color: "#CBD5E1" }}>×</span>
            ) : null}
          </span>
        ))}
        <span style={{ margin: "0 6px", color: "#CBD5E1" }}>=</span>
        <strong style={{ color: "#0F172A" }}>{product.toFixed(2)}</strong>
      </div>
      <div
        style={{
          display: "flex",
          width: "100%",
          height: 12,
          borderRadius: 6,
          overflow: "hidden",
          background: "#F1F5F9",
        }}
      >
        {segments.map((s) => (
          <div
            key={s.key}
            title={`${s.label}: ${s.value.toFixed(2)}`}
            style={{
              flex: s.value,
              background: s.color,
              transition: "flex 0.3s ease",
            }}
          />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Graph derivation (decision tree → nodes + edges)
// ---------------------------------------------------------------------------

function ontologyForKind(kind: string): OntologyKind {
  const k = kind.toLowerCase();
  if (k.includes("snomed")) return "SNOMED";
  if (k.includes("icd")) return "ICD10";
  if (k.includes("hcc")) return "HCC";
  if (k.includes("atc") || k.includes("drug") || k.includes("med")) return "ATC";
  if (k.includes("loinc") || k.includes("lab")) return "LOINC";
  return "OTHER";
}

function deriveGraph(
  chain: KgEvidenceChain,
): { nodes: KgGraphNode[]; edges: KgGraphEdge[] } {
  const nodes: KgGraphNode[] = chain.evidence_chain.map((item, i) => ({
    id: `ev-${i}`,
    label: item.value != null ? String(item.value) : item.kind,
    ontology: ontologyForKind(item.kind),
    onPath: true,
    definition: item.verbatim,
    source: item.source,
  }));
  nodes.push({
    id: "final-hcc",
    label: `HCC ${chain.hcc_code}`,
    ontology: "HCC",
    onPath: true,
    source: chain.suggested_icd10 ? `via ${chain.suggested_icd10}` : undefined,
  });
  const edges: KgGraphEdge[] = nodes.slice(0, -1).map((node, i) => ({
    from: node.id,
    to: nodes[i + 1].id,
    onPath: true,
  }));
  return { nodes, edges };
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

const SECTION_TITLE: CSSProperties = {
  fontSize: 11,
  fontWeight: 700,
  letterSpacing: 0.6,
  textTransform: "uppercase",
  color: "#64748B",
  marginBottom: 8,
};

export function EvidenceChainPanel({
  suspectId,
  hccCode,
  patientId,
  preloaded,
  year = 2026,
  style,
}: EvidenceChainPanelProps) {
  const [showGraph, setShowGraph] = useState(false);

  const query = useQuery<KgEvidenceChain>({
    queryKey: ["kg-evidence", suspectId, hccCode, patientId, year],
    enabled: !preloaded && (suspectId != null || (!!hccCode && patientId != null)),
    queryFn: async () => {
      if (suspectId != null) {
        return getSuspectEvidenceChain(suspectId);
      }
      if (hccCode && patientId != null) {
        return getEvidenceChain(hccCode, patientId, year);
      }
      throw new Error("EvidenceChainPanel: need suspectId or (hccCode + patientId)");
    },
  });

  const chain: KgEvidenceChain | undefined = preloaded ?? query.data;

  // Hooks must be called unconditionally — derive graph even if chain is missing.
  const graph = useMemo(
    () => (chain ? deriveGraph(chain) : { nodes: [], edges: [] }),
    [chain],
  );

  if (!preloaded && query.isLoading) {
    return (
      <div data-testid="evidence-chain-loading" style={{ padding: 24 }}>
        Loading evidence...
      </div>
    );
  }

  if (!preloaded && query.isError) {
    return (
      <div
        data-testid="evidence-chain-error"
        style={{
          padding: 24,
          color: "#B91C1C",
          background: "#FEF2F2",
          border: "1px solid #FECACA",
          borderRadius: 10,
        }}
      >
        Could not load evidence chain.
      </div>
    );
  }

  if (!chain || chain.evidence_chain.length === 0) {
    return (
      <div
        data-testid="evidence-chain-empty"
        style={{
          padding: 24,
          color: "#475569",
          background: "#F8FAFC",
          border: "1px dashed #CBD5E1",
          borderRadius: 10,
          textAlign: "center",
        }}
      >
        <div style={{ fontWeight: 600, color: "#1E293B", marginBottom: 4 }}>
          HCC {chain?.hcc_code ?? hccCode}
        </div>
        No KG evidence is available for this suggestion yet.
      </div>
    );
  }

  const factors = deriveFactors(chain);
  const citationItem = chain.evidence_chain.find((i) => !!i.citation);
  const parsedCitation = parseCitation(citationItem?.citation);

  return (
    <section
      data-testid="evidence-chain-panel"
      data-hcc={chain.hcc_code}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 20,
        ...style,
      }}
    >
      {/* HEADER */}
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div>
          <div style={{ fontSize: 11, color: "#64748B", letterSpacing: 0.5, fontWeight: 600 }}>
            WHY THIS HCC?
          </div>
          <h3 style={{ margin: "4px 0 0", fontSize: 18, color: "#0F172A" }}>
            HCC {chain.hcc_code}
            {chain.suggested_icd10 ? (
              <span
                style={{
                  marginLeft: 10,
                  fontSize: 12,
                  fontFamily: "monospace",
                  background: "#EDE9FE",
                  color: "#6D28D9",
                  padding: "2px 6px",
                  borderRadius: 4,
                }}
              >
                {chain.suggested_icd10}
              </span>
            ) : null}
          </h3>
        </div>
        <ConfidencePill score={chain.total_score} />
      </header>

      {/* TRIGGER EVIDENCE */}
      <div>
        <div style={SECTION_TITLE}>Trigger evidence</div>
        <ul
          data-testid="trigger-evidence-list"
          style={{
            margin: 0,
            padding: 0,
            listStyle: "none",
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          {chain.evidence_chain.map((item, i) => (
            <EvidenceLineItem key={`ev-${i}`} item={item} />
          ))}
        </ul>
      </div>

      {/* REASONING CHAIN */}
      {chain.decision_tree && chain.decision_tree.length > 0 ? (
        <div>
          <div style={SECTION_TITLE}>Reasoning chain</div>
          <ol
            data-testid="reasoning-chain"
            style={{
              margin: 0,
              paddingLeft: 22,
              display: "flex",
              flexDirection: "column",
              gap: 6,
              fontSize: 13,
              color: "#1E293B",
            }}
          >
            {chain.decision_tree.map((step, i) => (
              <li key={`step-${i}`} style={{ lineHeight: 1.55 }}>
                {step}
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      {/* CITATION */}
      {parsedCitation ? (
        <div>
          <div style={SECTION_TITLE}>Citation</div>
          <div
            data-testid="citation"
            style={{
              fontSize: 12,
              color: "#475569",
              padding: 10,
              borderRadius: 8,
              background: "#F8FAFC",
              border: "1px solid #E2E8F0",
            }}
          >
            {parsedCitation.text}
            {parsedCitation.href ? (
              <>
                {" "}
                <a
                  href={parsedCitation.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ color: "#2563EB", textDecoration: "underline" }}
                >
                  view source
                </a>
              </>
            ) : null}
          </div>
        </div>
      ) : null}

      {/* CONFIDENCE BREAKDOWN */}
      <div>
        <div style={SECTION_TITLE}>Confidence breakdown</div>
        <ConfidenceBreakdown factors={factors} />
      </div>

      {/* GRAPH VIEW TOGGLE */}
      <div>
        <button
          type="button"
          data-testid="toggle-graph-btn"
          onClick={() => setShowGraph((s) => !s)}
          style={{
            border: "1px solid #CBD5E1",
            background: "#FFFFFF",
            color: "#1E293B",
            fontSize: 12,
            fontWeight: 600,
            padding: "6px 12px",
            borderRadius: 8,
            cursor: "pointer",
          }}
        >
          {showGraph ? "Hide KG path" : "View KG path"}
        </button>
        {showGraph ? (
          <div style={{ marginTop: 12 }} data-testid="kg-graph-wrapper">
            <KgGraphView
              nodes={graph.nodes}
              edges={graph.edges}
              title={`Path → HCC ${chain.hcc_code}`}
            />
          </div>
        ) : null}
      </div>
    </section>
  );
}

function EvidenceLineItem({ item }: { item: KgEvidenceItem }) {
  const valueText = item.value != null ? String(item.value) : null;
  return (
    <li
      style={{
        display: "flex",
        gap: 10,
        alignItems: "flex-start",
      }}
    >
      <EvidenceIcon kind={item.kind} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, color: "#475569" }}>
          <span style={{ color: "#0F172A", fontWeight: 600 }}>{item.kind}</span>
          {" · "}
          <span style={{ fontFamily: "monospace" }}>{item.source}</span>
          {valueText ? (
            <>
              {" · "}
              <span>{valueText}</span>
            </>
          ) : null}
        </div>
        {item.verbatim ? (
          <div
            style={{
              fontStyle: "italic",
              fontFamily: "monospace",
              fontSize: 12,
              color: "#1E293B",
              background: "#F1F5F9",
              padding: "4px 8px",
              borderRadius: 6,
              marginTop: 4,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            “{item.verbatim}”
          </div>
        ) : null}
      </div>
    </li>
  );
}

export default EvidenceChainPanel;
