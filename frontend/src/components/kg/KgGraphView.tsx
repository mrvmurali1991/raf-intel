"use client";

/**
 * KgGraphView — minimal directed-graph visualisation of a KG path.
 *
 * Implementation choice: plain SVG. We considered reactflow but it isn't in
 * this branch's package.json and pulling it in for ~40 lines of layout code
 * is overkill. SVG keeps the bundle slim and avoids a build-time dependency
 * that other parallel branches don't yet require.
 *
 * Nodes are colour-coded by ontology:
 *   SNOMED  → blue
 *   ICD-10  → purple
 *   HCC     → red
 *   ATC     → green
 *   LOINC   → orange
 *   default → slate
 */

import type { CSSProperties } from "react";

export type OntologyKind =
  | "SNOMED"
  | "ICD10"
  | "HCC"
  | "ATC"
  | "LOINC"
  | "OTHER";

export interface KgGraphNode {
  id: string;
  label: string;
  ontology: OntologyKind;
  /** True if this node lies on the path that fired. Highlighted when set. */
  onPath?: boolean;
  /** Optional definition shown in the tooltip. */
  definition?: string;
  /** Optional source of this node (e.g. "CMS V28 HCC table"). */
  source?: string;
}

export interface KgGraphEdge {
  from: string;
  to: string;
  /** Relationship label (e.g. "indicates", "upgrades_to"). */
  label?: string;
  onPath?: boolean;
}

interface KgGraphViewProps {
  nodes: KgGraphNode[];
  edges: KgGraphEdge[];
  width?: number;
  height?: number;
  style?: CSSProperties;
  /** Title rendered above the graph. */
  title?: string;
}

const ONTOLOGY_COLORS: Record<OntologyKind, { fill: string; stroke: string; text: string }> = {
  SNOMED: { fill: "#DBEAFE", stroke: "#2563EB", text: "#1E3A8A" },
  ICD10: { fill: "#EDE9FE", stroke: "#7C3AED", text: "#4C1D95" },
  HCC: { fill: "#FEE2E2", stroke: "#DC2626", text: "#7F1D1D" },
  ATC: { fill: "#D1FAE5", stroke: "#059669", text: "#064E3B" },
  LOINC: { fill: "#FFEDD5", stroke: "#EA580C", text: "#7C2D12" },
  OTHER: { fill: "#F1F5F9", stroke: "#64748B", text: "#1E293B" },
};

const NODE_WIDTH = 140;
const NODE_HEIGHT = 56;
const HORIZONTAL_GAP = 40;
const VERTICAL_GAP = 90;

/** Lay out nodes in topological order along a single column / wrapping rows. */
function layoutNodes(
  nodes: KgGraphNode[],
  width: number,
): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  const innerWidth = width - 24;
  const cols = Math.max(1, Math.floor(innerWidth / (NODE_WIDTH + HORIZONTAL_GAP)));
  nodes.forEach((node, i) => {
    const col = i % cols;
    const row = Math.floor(i / cols);
    const x = 12 + col * (NODE_WIDTH + HORIZONTAL_GAP);
    const y = 12 + row * (NODE_HEIGHT + VERTICAL_GAP);
    positions.set(node.id, { x, y });
  });
  return positions;
}

export function KgGraphView({
  nodes,
  edges,
  width = 720,
  height,
  style,
  title,
}: KgGraphViewProps) {
  const positions = layoutNodes(nodes, width);
  const lastY =
    Math.max(0, ...Array.from(positions.values()).map((p) => p.y)) + NODE_HEIGHT + 24;
  const computedHeight = height ?? Math.max(220, lastY);

  return (
    <div style={{ width: "100%", ...style }}>
      {title ? (
        <div
          style={{
            fontSize: 13,
            fontWeight: 600,
            color: "#334155",
            marginBottom: 8,
          }}
        >
          {title}
        </div>
      ) : null}
      <svg
        role="img"
        aria-label={title ?? "Knowledge graph path"}
        width={width}
        height={computedHeight}
        viewBox={`0 0 ${width} ${computedHeight}`}
        style={{
          background: "#FFFFFF",
          border: "1px solid #E2E8F0",
          borderRadius: 10,
        }}
      >
        <defs>
          <marker
            id="arrow"
            viewBox="0 0 10 10"
            refX="8"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#64748B" />
          </marker>
          <marker
            id="arrow-active"
            viewBox="0 0 10 10"
            refX="8"
            refY="5"
            markerWidth="6"
            markerHeight="6"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#0F172A" />
          </marker>
        </defs>

        {/* Edges first so nodes paint on top */}
        {edges.map((edge, i) => {
          const a = positions.get(edge.from);
          const b = positions.get(edge.to);
          if (!a || !b) return null;
          const x1 = a.x + NODE_WIDTH / 2;
          const y1 = a.y + NODE_HEIGHT;
          const x2 = b.x + NODE_WIDTH / 2;
          const y2 = b.y;
          const midX = (x1 + x2) / 2;
          const midY = (y1 + y2) / 2;
          return (
            <g key={`edge-${i}`}>
              <line
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                stroke={edge.onPath ? "#0F172A" : "#94A3B8"}
                strokeWidth={edge.onPath ? 2 : 1.2}
                strokeDasharray={edge.onPath ? undefined : "4 3"}
                markerEnd={`url(#${edge.onPath ? "arrow-active" : "arrow"})`}
              />
              {edge.label ? (
                <text
                  x={midX}
                  y={midY}
                  textAnchor="middle"
                  fontSize="10"
                  fill="#475569"
                  style={{
                    paintOrder: "stroke",
                    stroke: "#FFFFFF",
                    strokeWidth: 3,
                  }}
                >
                  {edge.label}
                </text>
              ) : null}
            </g>
          );
        })}

        {nodes.map((node) => {
          const pos = positions.get(node.id);
          if (!pos) return null;
          const palette = ONTOLOGY_COLORS[node.ontology] ?? ONTOLOGY_COLORS.OTHER;
          return (
            <g key={node.id} transform={`translate(${pos.x}, ${pos.y})`}>
              <title>
                {node.label}
                {node.definition ? ` — ${node.definition}` : ""}
                {node.source ? ` (source: ${node.source})` : ""}
              </title>
              <rect
                width={NODE_WIDTH}
                height={NODE_HEIGHT}
                rx={8}
                ry={8}
                fill={palette.fill}
                stroke={node.onPath ? "#0F172A" : palette.stroke}
                strokeWidth={node.onPath ? 2 : 1}
              />
              <text
                x={NODE_WIDTH / 2}
                y={20}
                textAnchor="middle"
                fontSize="10"
                fontWeight={600}
                fill={palette.stroke}
                style={{ textTransform: "uppercase", letterSpacing: 0.5 }}
              >
                {node.ontology}
              </text>
              <text
                x={NODE_WIDTH / 2}
                y={40}
                textAnchor="middle"
                fontSize="12"
                fontWeight={600}
                fill={palette.text}
              >
                {node.label.length > 18 ? `${node.label.slice(0, 17)}...` : node.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export default KgGraphView;
