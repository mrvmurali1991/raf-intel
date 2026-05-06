"use client";

/**
 * PatientFullInferenceTab — patient-level KG inference view.
 *
 * Renders ranked HCC candidates returned by /api/kg/query/patient-full-inference/{pid}.
 * Each row collapses into a full EvidenceChainPanel.
 */

import { useMemo, useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  getPatientFullInference,
  type KgHccCandidate,
} from "@/lib/api";
import { EvidenceChainPanel } from "@/components/kg/EvidenceChainPanel";

interface PatientFullInferenceTabProps {
  patientId: number;
  year?: number;
  style?: CSSProperties;
}

type SortMode = "confidence" | "impact" | "hcc";

// Rough revenue-impact estimate: confidence × CMS coefficient placeholder.
// Backend may surface a real $ figure later; until then this is a stable
// proxy for relative ranking.
function estImpact(c: KgHccCandidate): number {
  return c.confidence * 1000;
}

function sortCandidates(
  candidates: KgHccCandidate[],
  mode: SortMode,
): KgHccCandidate[] {
  const copy = [...candidates];
  switch (mode) {
    case "confidence":
      return copy.sort((a, b) => b.confidence - a.confidence);
    case "impact":
      return copy.sort((a, b) => estImpact(b) - estImpact(a));
    case "hcc":
      return copy.sort((a, b) => a.hcc.localeCompare(b.hcc, undefined, { numeric: true }));
  }
}

export function PatientFullInferenceTab({
  patientId,
  year = 2026,
  style,
}: PatientFullInferenceTabProps) {
  const [sortMode, setSortMode] = useState<SortMode>("confidence");
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const query = useQuery({
    queryKey: ["kg-patient-full-inference", patientId, year],
    queryFn: () => getPatientFullInference(patientId, year),
    enabled: patientId != null,
  });

  const sorted = useMemo(() => {
    if (!query.data) return [] as KgHccCandidate[];
    return sortCandidates(query.data.candidates, sortMode);
  }, [query.data, sortMode]);

  return (
    <section
      data-testid="patient-full-inference-tab"
      style={{ display: "flex", flexDirection: "column", gap: 14, ...style }}
    >
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
          <h3 style={{ margin: 0, fontSize: 16, color: "#0F172A" }}>KG Inference</h3>
          <p style={{ margin: "2px 0 0", fontSize: 12, color: "#64748B" }}>
            HCC candidates discovered by the knowledge graph for this patient.
          </p>
        </div>
        <SortControl value={sortMode} onChange={setSortMode} />
      </header>

      {query.isLoading ? (
        <div style={{ fontSize: 13, color: "#64748B" }}>Running KG inference...</div>
      ) : null}

      {query.isError ? (
        <div
          style={{
            padding: 12,
            borderRadius: 8,
            background: "#FEF2F2",
            border: "1px solid #FECACA",
            color: "#B91C1C",
            fontSize: 13,
          }}
        >
          Could not run KG inference for this patient.
        </div>
      ) : null}

      {!query.isLoading && !query.isError && sorted.length === 0 ? (
        <div
          style={{
            padding: 16,
            borderRadius: 10,
            background: "#F8FAFC",
            border: "1px dashed #CBD5E1",
            color: "#475569",
            fontSize: 13,
            textAlign: "center",
          }}
        >
          No KG-derived HCC candidates for this patient yet.
        </div>
      ) : null}

      <ul
        data-testid="kg-candidate-list"
        style={{
          margin: 0,
          padding: 0,
          listStyle: "none",
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        {sorted.map((cand) => {
          const key = cand.hcc;
          const isOpen = !!expanded[key];
          return (
            <li
              key={key}
              style={{
                background: "#FFFFFF",
                border: "1px solid #E2E8F0",
                borderRadius: 10,
                padding: 14,
              }}
            >
              <button
                type="button"
                onClick={() =>
                  setExpanded((s) => ({ ...s, [key]: !s[key] }))
                }
                aria-expanded={isOpen}
                aria-controls={`kg-cand-${key}`}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  width: "100%",
                  background: "transparent",
                  border: "none",
                  padding: 0,
                  cursor: "pointer",
                  textAlign: "left",
                }}
              >
                <span
                  style={{
                    fontFamily: "monospace",
                    background: "#FEE2E2",
                    color: "#B91C1C",
                    padding: "2px 6px",
                    borderRadius: 4,
                    fontWeight: 700,
                    fontSize: 12,
                  }}
                >
                  HCC {cand.hcc}
                </span>
                <span style={{ flex: 1, fontSize: 13, color: "#1E293B" }}>
                  {cand.reasoning?.[0] ?? "KG-derived candidate"}
                </span>
                <ConfidenceMini score={cand.confidence} />
                <span style={{ fontSize: 11, color: "#64748B" }}>
                  {isOpen ? "▾" : "▸"}
                </span>
              </button>
              {isOpen ? (
                <div id={`kg-cand-${key}`} style={{ marginTop: 12 }}>
                  <EvidenceChainPanel
                    hccCode={cand.hcc}
                    patientId={patientId}
                    preloaded={cand.final_evidence}
                  />
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function SortControl({
  value,
  onChange,
}: {
  value: SortMode;
  onChange: (m: SortMode) => void;
}) {
  return (
    <label style={{ fontSize: 12, color: "#475569", display: "inline-flex", gap: 6, alignItems: "center" }}>
      Sort by
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as SortMode)}
        style={{
          fontSize: 12,
          padding: "4px 8px",
          borderRadius: 6,
          border: "1px solid #CBD5E1",
          background: "#FFFFFF",
          color: "#0F172A",
        }}
      >
        <option value="confidence">Confidence</option>
        <option value="impact">$ Impact</option>
        <option value="hcc">HCC code</option>
      </select>
    </label>
  );
}

function ConfidenceMini({ score }: { score: number }) {
  const pct = (score * 100).toFixed(0);
  let color = "#B91C1C";
  if (score >= 0.75) color = "#047857";
  else if (score >= 0.5) color = "#92400E";
  return (
    <span
      style={{
        fontSize: 11,
        fontWeight: 700,
        color,
        background: "#F8FAFC",
        border: "1px solid #E2E8F0",
        padding: "2px 6px",
        borderRadius: 4,
        minWidth: 38,
        textAlign: "center",
      }}
    >
      {pct}%
    </span>
  );
}

export default PatientFullInferenceTab;
