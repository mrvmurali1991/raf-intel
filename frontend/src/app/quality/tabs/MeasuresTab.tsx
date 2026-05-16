"use client";

import React, { useState, useMemo } from "react";
import { Filter, ChevronRight, ChevronDown, CheckCircle } from "lucide-react";
import { tokens } from "@/styles/tokens";
import type { QualityMeasure } from "@/lib/api";
import { C, T, EmptyRow, complianceColor, complianceBg, complianceTextColor } from "./_shared";

function MeasureRow({ measure, index }: { measure: QualityMeasure; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const rate = measure.rate * 100;
  const color = complianceColor(rate);
  const bg = complianceBg(rate);
  const tc = complianceTextColor(rate);
  const benchmark = measure.benchmark != null ? measure.benchmark * 100 : null;

  return (
    <>
      <tr
        className="qs-priority-card"
        style={{
          borderBottom: `1px solid ${C.borderLight}`,
          borderLeft: `3px solid ${color}`,
          cursor: "pointer",
          background: expanded ? tokens.slate50 : index % 2 === 0 ? C.card : tokens.slate50,
          transition: "background 0.15s ease",
        }}
        onClick={() => setExpanded(!expanded)}
      >
        <td style={{ padding: "12px 16px", verticalAlign: "middle" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {expanded ? <ChevronDown size={14} color={C.textSub} /> : <ChevronRight size={14} color={C.textSub} />}
            <span style={{ fontSize: 12, fontWeight: 700, color: C.primary, fontFamily: "monospace" }}>
              {measure.measure_id}
            </span>
          </div>
        </td>
        <td style={{ padding: "12px 16px", verticalAlign: "middle" }}>
          <span style={{ fontSize: 13, fontWeight: 500, color: C.text }}>{measure.name}</span>
        </td>
        <td style={{ padding: "12px 16px", verticalAlign: "middle", textAlign: "center" }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{(measure.denominator ?? 0).toLocaleString()}</span>
        </td>
        <td style={{ padding: "12px 16px", verticalAlign: "middle", textAlign: "center" }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: C.emerald }}>{(measure.numerator ?? 0).toLocaleString()}</span>
        </td>
        <td style={{ padding: "12px 16px", verticalAlign: "middle", minWidth: 160 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ flex: 1, height: 7, borderRadius: 4, background: C.borderLight, overflow: "hidden", boxShadow: "inset 0 1px 2px rgba(0,0,0,0.06)" }}>
              <div className="qs-progress-bar" style={{ height: "100%", width: `${Math.min(rate, 100)}%`, borderRadius: 4, background: `linear-gradient(90deg, ${color}CC, ${color})`, boxShadow: `0 1px 4px ${color}40`, transition: "width 0.6s cubic-bezier(0.22,1,0.36,1)" }} />
            </div>
            <span style={{ fontSize: 12, fontWeight: 700, padding: "2px 8px", borderRadius: 999, background: bg, color: tc, minWidth: 44, textAlign: "center" }}>
              {(rate ?? 0).toFixed(1)}%
            </span>
          </div>
        </td>
        <td style={{ padding: "12px 16px", verticalAlign: "middle", textAlign: "center" }}>
          {benchmark != null ? (
            <span style={{ fontSize: 13, color: C.textMuted }}>{(benchmark ?? 0).toFixed(1)}%</span>
          ) : (
            <span style={{ fontSize: 11, color: C.textSub }}>—</span>
          )}
        </td>
        <td style={{ padding: "12px 16px", verticalAlign: "middle", textAlign: "center" }}>
          {measure.gap > 0 ? (
            <span style={{ fontSize: 12, fontWeight: 700, padding: "2px 10px", borderRadius: 999, background: C.redLight, color: C.redDark }}>
              {measure.gap.toLocaleString()}
            </span>
          ) : (
            <CheckCircle size={16} color={C.emerald} />
          )}
        </td>
      </tr>

      {expanded && (
        <tr className="qs-card-enter" style={{ background: `linear-gradient(135deg, ${tokens.primarySoft} 0%, ${tokens.primarySoft} 100%)` }}>
          <td colSpan={7} style={{ padding: "16px 20px 20px 48px", borderLeft: `3px solid ${color}` }}>
            <div style={{ display: "flex", gap: 36, flexWrap: "wrap" }}>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>Compliance Rate</div>
                <div style={{ fontSize: 22, fontWeight: 800, color }}>{(rate ?? 0).toFixed(1)}%</div>
              </div>
              {benchmark != null && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 700, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>Benchmark</div>
                  <div style={{ fontSize: 22, fontWeight: 800, color: C.textMuted }}>{(benchmark ?? 0).toFixed(1)}%</div>
                </div>
              )}
              {benchmark != null && (
                <div>
                  <div style={{ fontSize: 11, fontWeight: 700, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>vs Benchmark</div>
                  <div style={{ fontSize: 22, fontWeight: 800, color: rate >= benchmark ? C.emerald : C.red }}>
                    {rate >= benchmark ? "+" : ""}{((rate ?? 0) - (benchmark ?? 0)).toFixed(1)}%
                  </div>
                </div>
              )}
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: C.textMuted, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>Open Gaps</div>
                <div style={{ fontSize: 22, fontWeight: 800, color: measure.gap > 0 ? C.red : C.emerald }}>{measure.gap.toLocaleString()}</div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function MeasuresTab({ measures }: { measures: QualityMeasure[] }) {
  const [measureFilter, setMeasureFilter] = useState("");

  const filtered = useMemo(
    () =>
      measures.filter(
        (m) =>
          m.name.toLowerCase().includes(measureFilter.toLowerCase()) ||
          m.measure_id.toLowerCase().includes(measureFilter.toLowerCase()),
      ),
    [measures, measureFilter],
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ position: "relative", flex: "1 1 240px", maxWidth: 320 }}>
          <Filter size={14} style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: C.textSub }} />
          <input
            type="text"
            placeholder="Search measures..."
            value={measureFilter}
            onChange={(e) => setMeasureFilter(e.target.value)}
            style={{ width: "100%", paddingLeft: 34, paddingRight: 12, paddingTop: 8, paddingBottom: 8, border: `1px solid ${C.border}`, borderRadius: 8, fontSize: 13, background: C.card, color: C.text, boxSizing: "border-box" }}
          />
        </div>
        <div style={{ marginLeft: "auto", fontSize: 12, color: C.textSub }}>
          Showing {filtered.length} of {measures.length} measures
        </div>
      </div>

      <div className="premium-card premium-shadow qs-fade-in qs-fade-in-1" style={{ ...T.card, padding: 0, overflow: "hidden", borderRadius: 14 }}>
        <div style={{ overflowX: "auto" }}>
          <table className="qs-measure-table" style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {["Measure ID", "Measure Name", "Eligible", "Compliant", "Rate", "Benchmark", "Gap"].map((h) => (
                  <th
                    key={h}
                    style={{
                      padding: "12px 16px", fontSize: 11, fontWeight: 700, textTransform: "uppercase",
                      letterSpacing: "0.05em", color: C.textMuted,
                      textAlign: ["Eligible", "Compliant", "Gap", "Benchmark"].includes(h) ? "center" : "left",
                      borderBottom: `1px solid ${C.border}`, background: tokens.slate50, whiteSpace: "nowrap",
                    }}
                  >{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <EmptyRow colSpan={7} message="No measures match the search." />
              ) : (
                filtered.map((m, i) => <MeasureRow key={`${m.measure_id}-${i}`} measure={m} index={i} />)
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
