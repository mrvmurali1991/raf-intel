"use client";

import React, { useState, useMemo } from "react";
import Link from "next/link";
import { X, Download, ChevronRight } from "lucide-react";
import { tokens } from "@/styles/tokens";
import type { CareGap } from "@/lib/api";
import { C, T, EmptyRow, gapStatusStyle } from "./_shared";

export default function CareGapsTab({ gaps, total }: { gaps: CareGap[]; total: number }) {
  const [statusFilter, setStatusFilter] = useState<"all" | "open" | "closed" | "excluded">("all");
  const [measureFilter, setMeasureFilter] = useState("all");

  const measureIds = useMemo(() => {
    const ids = Array.from(new Set(gaps.map((g) => g.measure_id)));
    return ids.sort();
  }, [gaps]);

  const filtered = useMemo(() => {
    return gaps.filter((g) => {
      const matchStatus = statusFilter === "all" || g.status === statusFilter;
      const matchMeasure = measureFilter === "all" || g.measure_id === measureFilter;
      return matchStatus && matchMeasure;
    });
  }, [gaps, statusFilter, measureFilter]);

  function handleExport() {
    const rows = [
      ["Gap ID", "Patient ID", "Patient Name", "Measure ID", "Measure Name", "Due Date", "Status"],
      ...filtered.map((g) => [g.gap_id, g.pid, g.patient_name, g.measure_id, g.measure_name, g.due_date ?? "", g.status]),
    ];
    const csv = rows.map((r) => r.map(String).map((v) => `"${v}"`).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "care_gaps.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* Filter bar */}
      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}
          style={{ padding: "8px 12px", border: `1px solid ${C.border}`, borderRadius: 8, fontSize: 13, background: C.card, color: C.text, cursor: "pointer" }}
        >
          <option value="all">All Statuses</option>
          <option value="open">Open</option>
          <option value="closed">Closed</option>
          <option value="excluded">Excluded</option>
        </select>

        <select
          value={measureFilter}
          onChange={(e) => setMeasureFilter(e.target.value)}
          style={{ padding: "8px 12px", border: `1px solid ${C.border}`, borderRadius: 8, fontSize: 13, background: C.card, color: C.text, cursor: "pointer" }}
        >
          <option value="all">All Measures</option>
          {measureIds.map((id) => (
            <option key={id} value={id}>{id}</option>
          ))}
        </select>

        <button
          onClick={() => { setStatusFilter("all"); setMeasureFilter("all"); }}
          style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "8px 14px", border: `1px solid ${C.border}`, borderRadius: 8, background: C.card, color: C.textMuted, fontSize: 13, cursor: "pointer" }}
        >
          <X size={14} />
          Clear
        </button>

        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 12, color: C.textSub }}>
            {filtered.length} of {total.toLocaleString()} gaps
          </span>
          <button
            onClick={handleExport}
            style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "8px 16px", border: `1px solid ${C.border}`, borderRadius: 8, background: C.card, color: C.textMuted, fontSize: 13, fontWeight: 500, cursor: "pointer" }}
          >
            <Download size={14} />
            Export CSV
          </button>
        </div>
      </div>

      {/* Gaps table */}
      <div className="premium-card premium-shadow qs-fade-in qs-fade-in-1" style={{ ...T.card, padding: 0, overflow: "hidden", borderRadius: 14 }}>
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                {["Patient", "Measure", "Measure Name", "Due Date", "Status", "Actions"].map((h) => (
                  <th
                    key={h}
                    style={{
                      padding: "12px 16px", fontSize: 11, fontWeight: 700, textTransform: "uppercase",
                      letterSpacing: "0.05em", color: C.textMuted, textAlign: "left",
                      background: tokens.slate50, borderBottom: `1px solid ${C.border}`, whiteSpace: "nowrap",
                    }}
                  >{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 ? (
                <EmptyRow colSpan={6} message="No care gaps match the selected filters." />
              ) : (
                filtered.map((gap, idx) => (
                  <tr
                    key={gap.gap_id}
                    style={{ borderBottom: `1px solid ${C.borderLight}`, background: idx % 2 === 0 ? C.card : tokens.slate50 }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = tokens.primarySoft)}
                    onMouseLeave={(e) => (e.currentTarget.style.background = idx % 2 === 0 ? C.card : tokens.slate50)}
                  >
                    <td style={{ padding: "12px 16px", verticalAlign: "middle" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div style={{ width: 32, height: 32, borderRadius: "50%", background: C.primary, color: "#FFF", fontSize: 12, fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                          {gap.patient_name.split(/[\s,]+/).filter(Boolean).slice(0, 2).map((w) => w[0]?.toUpperCase() ?? "").join("")}
                        </div>
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 600, color: C.text }}>{gap.patient_name}</div>
                          <div style={{ fontSize: 11, color: C.textSub }}>PID {gap.pid}</div>
                        </div>
                      </div>
                    </td>
                    <td style={{ padding: "12px 16px", verticalAlign: "middle" }}>
                      <span style={{ fontSize: 12, fontWeight: 700, color: C.primary, fontFamily: "monospace" }}>{gap.measure_id}</span>
                    </td>
                    <td style={{ padding: "12px 16px", verticalAlign: "middle" }}>
                      <span style={{ fontSize: 13, color: C.text }}>{gap.measure_name}</span>
                    </td>
                    <td style={{ padding: "12px 16px", verticalAlign: "middle" }}>
                      {gap.due_date ? (
                        <span style={{ fontSize: 13, color: C.textMuted }}>{gap.due_date}</span>
                      ) : (
                        <span style={{ fontSize: 11, color: C.textSub }}>—</span>
                      )}
                    </td>
                    <td style={{ padding: "12px 16px", verticalAlign: "middle" }}>
                      <span style={gapStatusStyle(gap.status)}>
                        {gap.status.charAt(0).toUpperCase() + gap.status.slice(1)}
                      </span>
                    </td>
                    <td style={{ padding: "12px 16px", verticalAlign: "middle" }}>
                      <Link
                        href={`/patients/${gap.pid}`}
                        className="hover-lift"
                        style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12, fontWeight: 600, color: C.primary, textDecoration: "none", padding: "6px 14px", borderRadius: 8, border: `1px solid ${C.primaryLight}`, background: `linear-gradient(135deg, ${tokens.primarySoft}, ${tokens.primarySoft})` }}
                      >
                        View Patient <ChevronRight size={13} />
                      </Link>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
