"use client";

/**
 * AuditRadvScenariosCard — lazy-loaded RADV scenario selector.
 * Extracted from audit/page.tsx to defer ~8 KB from initial paint.
 */

import React, { useState } from "react";
import { ClipboardList, CheckSquare, PlayCircle } from "lucide-react";

type ScenarioStatus = "active" | "complete" | "draft";

interface RadvScenario {
  id: string;
  name: string;
  charts: number;
  status: ScenarioStatus;
  description: string;
}

const RADV_SCENARIOS: RadvScenario[] = [
  { id: "radv-2024-cohort-a", name: "RADV 2024 Cohort A", charts: 50, status: "active", description: "Primary CMS submission — high-RAF members, 2024 DOS" },
  { id: "mock-cms-audit-q3", name: "Mock CMS Audit Q3", charts: 30, status: "complete", description: "Internal dry-run simulating CMS RADV sample selection" },
  { id: "internal-qa-sample", name: "Internal QA Sample", charts: 20, status: "draft", description: "Coder QA cross-check — not yet submitted for review" },
];

function ScenarioStatusPill({ status }: { status: ScenarioStatus }) {
  const cfg: Record<ScenarioStatus, { bg: string; border: string; color: string; label: string }> = {
    active:   { bg: "rgba(37,99,235,0.08)", border: "#2563EB", color: "#2563EB", label: "Active" },
    complete: { bg: "#ECFDF5", border: "#6EE7B7", color: "#047857", label: "Complete" },
    draft:    { bg: "#F1F5F9", border: "#CBD5E1", color: "#64748B", label: "Draft" },
  };
  const { bg, border, color, label } = cfg[status];
  return (
    <span style={{ display: "inline-flex", alignItems: "center", padding: "2px 10px", borderRadius: 9999, backgroundColor: bg, border: `1px solid ${border}`, color, fontSize: 11, fontWeight: 700, letterSpacing: "0.04em", textTransform: "uppercase" }}>
      {label}
    </span>
  );
}

export default function AuditRadvScenariosCard() {
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <div style={{ backgroundColor: "#fff", borderRadius: 10, border: "1px solid #E2E8F0", overflow: "hidden", marginBottom: 24 }} aria-label="RADV Scenarios">
      {/* Header */}
      <div style={{ padding: "20px 24px", borderBottom: "1px solid #F1F5F9", display: "flex", alignItems: "center", gap: 10, background: "linear-gradient(135deg, #F5F3FF 0%, #F8FAFC 100%)" }}>
        <div style={{ width: 32, height: 32, borderRadius: 8, backgroundColor: "#8B5CF6", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
          <ClipboardList size={16} color="#fff" aria-hidden="true" />
        </div>
        <div>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: "#0F172A" }}>RADV Scenarios</h2>
          <span style={{ fontSize: 12, color: "#64748B" }}>Select a scenario to scope your audit package</span>
        </div>
      </div>

      {/* Scenario list */}
      <ul role="listbox" aria-label="RADV audit scenarios" style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {RADV_SCENARIOS.map((scenario, idx) => {
          const isSelected = selected === scenario.id;
          return (
            <li
              key={scenario.id}
              role="option"
              aria-selected={isSelected}
              onClick={() => setSelected(isSelected ? null : scenario.id)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelected(isSelected ? null : scenario.id); } }}
              tabIndex={0}
              style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "16px 24px", gap: 16, borderBottom: idx < RADV_SCENARIOS.length - 1 ? "1px solid #F1F5F9" : "none", backgroundColor: isSelected ? "rgba(37,99,235,0.06)" : "transparent", cursor: "pointer", transition: "background-color 0.15s ease" }}
              onFocus={(e) => { e.currentTarget.style.outline = "2px solid #2563EB"; e.currentTarget.style.outlineOffset = "-2px"; }}
              onBlur={(e) => { e.currentTarget.style.outline = "none"; }}
              onMouseEnter={(e) => { if (!isSelected) e.currentTarget.style.backgroundColor = "#F8FAFC"; }}
              onMouseLeave={(e) => { if (!isSelected) e.currentTarget.style.backgroundColor = "transparent"; }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 12, flex: 1, minWidth: 0 }}>
                <div aria-hidden="true" style={{ width: 20, height: 20, borderRadius: 4, border: isSelected ? "2px solid #2563EB" : "2px solid #CBD5E1", backgroundColor: isSelected ? "#2563EB" : "transparent", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0, transition: "all 0.15s ease" }}>
                  {isSelected && <CheckSquare size={14} color="#fff" />}
                </div>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontWeight: 600, fontSize: 14, color: "#0F172A", marginBottom: 2 }}>{scenario.name}</div>
                  <div style={{ fontSize: 12, color: "#64748B", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{scenario.description}</div>
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
                <span style={{ fontSize: 13, color: "#64748B", fontVariantNumeric: "tabular-nums" }}>{scenario.charts} charts</span>
                <ScenarioStatusPill status={scenario.status} />
              </div>
            </li>
          );
        })}
      </ul>

      {/* Action footer when a scenario is selected */}
      {selected && (
        <div style={{ padding: "14px 24px", borderTop: "1px solid #F1F5F9", backgroundColor: "rgba(37,99,235,0.06)", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
          <span style={{ fontSize: 13, color: "#2563EB", fontWeight: 500 }}>
            Scenario selected — use &ldquo;Generate Audit Package&rdquo; below to scope this run
          </span>
          <button
            type="button"
            aria-label="Begin audit with selected scenario"
            onClick={() => { const el = document.getElementById("generate-audit-section"); el?.scrollIntoView({ behavior: "smooth" }); }}
            style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "7px 16px", borderRadius: 8, border: "none", backgroundColor: "#2563EB", color: "#fff", fontSize: 13, fontWeight: 600, cursor: "pointer" }}
          >
            <PlayCircle size={14} /> Begin Audit
          </button>
        </div>
      )}
    </div>
  );
}
