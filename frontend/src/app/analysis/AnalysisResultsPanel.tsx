"use client";

/**
 * AnalysisResultsPanel — heavy results section lazy-loaded after analysis runs.
 * Extracted from analysis/page.tsx to defer ~40 kB of inline JSX (diagnoses
 * table, MEAT grid, suspects list, pipeline details) until a result exists.
 */

import { useState, Fragment } from "react";
import type { AnalysisResult, AIDiagnosis, AISuspect } from "@/types";
import { tokens } from "@/styles/tokens";
import {
  FileText,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  ChevronDown,
  ChevronRight,
  Clock,
  ShieldCheck,
  TrendingUp,
  Sparkles,
} from "lucide-react";

/* ── helpers (duplicated from page to keep this chunk self-contained) ── */

function dxCondition(dx: AIDiagnosis): string {
  return dx.condition || dx.description || "Unknown condition";
}
function dxIcd10(dx: AIDiagnosis): string {
  return dx.icd10_code || dx.icd10 || "—";
}
function dxHcc(dx: AIDiagnosis): string | null | undefined {
  return dx.hcc_code || dx.hcc || dx.hcc_mapping?.hcc_code;
}
function dxCoeff(dx: AIDiagnosis): number | undefined {
  return dx.hcc_weight || dx.hcc_mapping?.coefficient;
}
function meatVal(
  dx: AIDiagnosis,
  key: "monitoring" | "evaluation" | "assessment" | "treatment"
): string {
  const short = { monitoring: "M", evaluation: "E", assessment: "A", treatment: "T" }[key] as "M" | "E" | "A" | "T";
  return dx.meat?.[key] || dx.meat?.[short] || "";
}
function suspIcd(s: AISuspect): string {
  return s.icd10_code || s.suspect_icd10 || s.icd10 || "—";
}
function suspConf(s: AISuspect): number {
  return s.confidence_score ?? s.confidence ?? 0;
}
function suspEvidence(s: AISuspect): string {
  return s.rationale || s.evidence || "";
}

/* ── sub-components ── */

function MeatPills({ dx }: { dx: AIDiagnosis }) {
  const keys = ["monitoring", "evaluation", "assessment", "treatment"] as const;
  const labels = ["M", "E", "A", "T"];
  const colors = [tokens.infoBlue, tokens.accentPurple, tokens.warningStrong, tokens.success];
  const bgColors = [tokens.primarySoft.replace("0.08", "0.12"), tokens.primarySoft, tokens.warningSoft, tokens.successSoft];
  return (
    <div style={{ display: "flex", gap: 5 }}>
      {keys.map((k, i) => {
        const present = !!meatVal(dx, k);
        return (
          <div
            key={k}
            title={`${labels[i]}: ${present ? meatVal(dx, k) : "Not documented"}`}
            aria-label={`${k}: ${present ? "documented" : "not documented"}`}
            style={{
              width: 28, height: 28, borderRadius: 8, display: "flex", alignItems: "center",
              justifyContent: "center", fontSize: 11, fontWeight: 800, letterSpacing: "0.02em",
              background: present ? bgColors[i] : tokens.slate100,
              color: present ? colors[i] : tokens.slate300,
              border: `2px solid ${present ? colors[i] + "50" : tokens.slate200}`,
              transition: "all 0.2s ease",
              boxShadow: present ? `0 2px 8px ${colors[i]}20` : "none",
            }}
          >
            {labels[i]}
          </div>
        );
      })}
    </div>
  );
}

function ConfBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = value >= 0.85 ? tokens.success : value >= 0.7 ? tokens.infoBlue : value >= 0.5 ? tokens.warningStrong : tokens.riskHigh;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 110 }}>
      <div style={{ flex: 1, height: 7, borderRadius: 4, background: tokens.slate100, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", borderRadius: 4, background: `linear-gradient(90deg, ${color}CC, ${color})`, transition: "width 0.5s cubic-bezier(0.4, 0, 0.2, 1)" }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 700, color, minWidth: 34, textAlign: "right", fontFamily: "monospace" }}>{pct}%</span>
    </div>
  );
}

function SectionHeader({ icon, title, count, countColor, countBg }: {
  icon: React.ReactNode; title: string; count?: number; countColor?: string; countBg?: string;
}) {
  return (
    <div style={{ padding: "16px 20px", borderBottom: `1px solid ${tokens.slate100}`, display: "flex", alignItems: "center", gap: 10 }}>
      <div style={{ width: 32, height: 32, borderRadius: 8, background: countBg || tokens.primarySoft, display: "flex", alignItems: "center", justifyContent: "center" }}>
        {icon}
      </div>
      <span className="text-foreground" style={{ fontSize: 16, fontWeight: 700 }}>{title}</span>
      {count != null && (
        <span style={{ fontSize: 12, fontWeight: 700, background: countBg || tokens.primarySoft, color: countColor || tokens.primary, padding: "3px 10px", borderRadius: 10 }}>
          {count}
        </span>
      )}
    </div>
  );
}

/* ── main export ── */

export interface AnalysisResultsPanelProps {
  result: AnalysisResult;
}

export default function AnalysisResultsPanel({ result }: AnalysisResultsPanelProps) {
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());
  const [pipelineOpen, setPipelineOpen] = useState(false);

  const diagnoses = result.diagnoses ?? [];
  const suspects = result.suspect_conditions ?? [];
  const confidence = result.overall_confidence ?? 0;
  const routing = result.confidence_routing;
  const meta = result._meta;

  const hccCount = diagnoses.filter((d) => !!dxHcc(d)).length;
  const meatCount = diagnoses.reduce((sum, dx) => {
    const keys = ["monitoring", "evaluation", "assessment", "treatment"] as const;
    return sum + keys.filter((k) => !!meatVal(dx, k)).length;
  }, 0);
  const meatTotal = diagnoses.length * 4;

  function toggle(i: number) {
    setExpandedRows((prev) => { const n = new Set(prev); if (n.has(i)) n.delete(i); else n.add(i); return n; });
  }

  return (
    <div className="animate-fade-in">
      {/* Summary Stats */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 16, marginBottom: 24 }}>
        {[
          { label: "Diagnoses", value: diagnoses.length, icon: <FileText size={18} />, gradient: "stat-card-blue" },
          { label: "HCC Codes", value: hccCount, icon: <ShieldCheck size={18} />, gradient: "stat-card-emerald" },
          { label: "Confidence", value: `${Math.round(confidence * 100)}%`, icon: <TrendingUp size={18} />, gradient: confidence >= 0.7 ? "stat-card-emerald" : "stat-card-amber" },
          { label: "MEAT Score", value: `${meatCount}/${meatTotal}`, icon: <Sparkles size={18} />, gradient: "stat-card-rose" },
        ].map((s, i) => (
          <div key={s.label} className={`${s.gradient} hover-lift animate-fade-in stagger-${i + 1}`} style={{ padding: "18px 20px", borderRadius: 14, display: "flex", alignItems: "center", gap: 14, color: tokens.white }}>
            <div style={{ width: 42, height: 42, borderRadius: 10, background: "rgba(255,255,255,0.2)", display: "flex", alignItems: "center", justifyContent: "center", backdropFilter: "blur(4px)" }}>
              {s.icon}
            </div>
            <div>
              <div style={{ fontSize: 24, fontWeight: 800, lineHeight: 1 }}>{s.value}</div>
              <div style={{ fontSize: 12, opacity: 0.85, marginTop: 3, fontWeight: 500 }}>{s.label}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Routing Banner */}
      {!!routing && (
        <div className="premium-card animate-fade-in" style={{ padding: "14px 20px", marginBottom: 24, display: "flex", alignItems: "center", gap: 12, borderLeft: `4px solid ${confidence >= 0.85 ? tokens.success : confidence >= 0.6 ? tokens.warningStrong : tokens.riskHigh}` }}>
          {confidence >= 0.85 ? <CheckCircle2 size={20} color={tokens.success} /> : confidence >= 0.6 ? <AlertTriangle size={20} color={tokens.warningStrong} /> : <XCircle size={20} color={tokens.riskHigh} />}
          <div style={{ flex: 1 }}>
            <span className="text-foreground" style={{ fontSize: 15, fontWeight: 700 }}>
              {confidence >= 0.85 ? "Auto-Accept" : confidence >= 0.6 ? "Needs Review" : "Full Audit Required"}
            </span>
            <span style={{ fontSize: 13, color: tokens.slate500, marginLeft: 10 }}>
              Overall confidence: {Math.round(confidence * 100)}%
            </span>
          </div>
        </div>
      )}

      {/* Diagnoses Table */}
      {diagnoses.length > 0 && (
        <div className="premium-card premium-shadow animate-fade-in" style={{ marginBottom: 24, overflow: "hidden" }}>
          <SectionHeader icon={<FileText size={16} color={tokens.infoBlue} />} title="Extracted Diagnoses" count={diagnoses.length} countColor={tokens.primary} countBg={tokens.primarySoft} />
          <div style={{ overflowX: "auto" }}>
            <table aria-label="Extracted diagnoses" className="premium-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: tokens.slate50, borderBottom: `2px solid ${tokens.slate200}` }}>
                  <th style={{ width: 32, padding: "12px 8px" }} />
                  {["ICD-10", "Description", "HCC", "Coeff", "Confidence", "MEAT"].map((h, idx) => (
                    <th key={h} style={{ padding: "12px 14px", textAlign: idx === 3 ? "right" : "left", fontWeight: 700, color: tokens.slate500, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em", minWidth: h === "Confidence" ? 130 : undefined }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {diagnoses.map((dx, i) => {
                  const hcc = dxHcc(dx);
                  const exp = expandedRows.has(i);
                  return (
                    <Fragment key={dxIcd10(dx) || i}>
                      <tr onClick={() => toggle(i)} style={{ cursor: "pointer", borderBottom: `1px solid ${tokens.slate100}`, borderLeft: hcc ? `3px solid ${tokens.infoBlue}` : "3px solid transparent", transition: "background 0.15s" }} onMouseEnter={(e) => (e.currentTarget.style.background = tokens.slate50)} onMouseLeave={(e) => (e.currentTarget.style.background = "")}>
                        <td style={{ padding: "12px 8px", textAlign: "center" }}>
                          {exp ? <ChevronDown size={14} color={tokens.infoBlue} /> : <ChevronRight size={14} color={tokens.slate400} />}
                        </td>
                        <td style={{ padding: "12px 14px" }}>
                          <code style={{ fontSize: 12, fontWeight: 700, background: tokens.primarySoft, color: tokens.primaryDark, padding: "4px 8px", borderRadius: 6, border: `1px solid ${tokens.slate200}` }}>{dxIcd10(dx)}</code>
                        </td>
                        <td style={{ padding: "12px 14px", fontWeight: 500, color: tokens.slate900, maxWidth: 280 }}>
                          <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{dxCondition(dx)}</div>
                        </td>
                        <td style={{ padding: "12px 14px" }}>
                          {hcc ? <span style={{ fontSize: 11, fontWeight: 700, background: tokens.primarySoft, color: tokens.primaryDark, padding: "4px 10px", borderRadius: 8, border: `1px solid ${tokens.slate200}` }}>{hcc}</span> : <span style={{ color: tokens.slate300 }}>--</span>}
                        </td>
                        <td style={{ padding: "12px 14px", textAlign: "right", fontFamily: "monospace", fontWeight: 700, color: tokens.slate700, fontSize: 13 }}>
                          {dxCoeff(dx) != null ? dxCoeff(dx)!.toFixed(3) : "--"}
                        </td>
                        <td style={{ padding: "12px 14px" }}><ConfBar value={dx.confidence} /></td>
                        <td style={{ padding: "12px 14px" }}><MeatPills dx={dx} /></td>
                      </tr>
                      {exp && (
                        <tr style={{ background: tokens.slate50 }}>
                          <td colSpan={7} style={{ padding: "18px 24px 18px 52px" }}>
                            {dx.supporting_text && (
                              <div className="bg-card" style={{ marginBottom: 16, padding: "12px 16px", borderRadius: 10, border: `1px solid hsl(var(--border))` }}>
                                <span style={{ fontSize: 11, fontWeight: 700, color: tokens.slate500, textTransform: "uppercase", letterSpacing: "0.05em" }}>Supporting Evidence</span>
                                <div style={{ fontSize: 13, color: tokens.slate700, fontStyle: "italic", marginTop: 6, lineHeight: 1.6 }}>&ldquo;{dx.supporting_text}&rdquo;</div>
                              </div>
                            )}
                            <div style={{ fontSize: 11, fontWeight: 700, color: tokens.slate500, textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 10 }}>MEAT Documentation</div>
                            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10 }}>
                              {(["monitoring", "evaluation", "assessment", "treatment"] as const).map((k, idx) => {
                                const v = meatVal(dx, k);
                                const colors = [tokens.infoBlue, tokens.accentPurple, tokens.warningStrong, tokens.success];
                                const bgColors = [tokens.primarySoft, tokens.primarySoft, tokens.warningSoft, tokens.successSoft];
                                const letters = ["M", "E", "A", "T"];
                                return (
                                  <div key={k} style={{ padding: "12px 14px", borderRadius: 10, background: v ? bgColors[idx] : tokens.slate50, border: `1px solid ${v ? colors[idx] + "30" : tokens.slate200}`, transition: "all 0.2s" }}>
                                    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                                      <div style={{ width: 22, height: 22, borderRadius: 6, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 10, fontWeight: 800, background: v ? colors[idx] : tokens.slate300, color: tokens.white }}>{letters[idx]}</div>
                                      <span style={{ fontSize: 11, fontWeight: 700, color: tokens.slate500, textTransform: "capitalize" }}>{k}</span>
                                    </div>
                                    <div style={{ fontSize: 12, color: v ? tokens.slate700 : tokens.slate400, fontStyle: v ? "normal" : "italic", lineHeight: 1.5 }}>{v || "Not documented"}</div>
                                  </div>
                                );
                              })}
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Suspect Conditions */}
      {suspects.length > 0 && (
        <div className="premium-card premium-shadow animate-fade-in" style={{ marginBottom: 24, overflow: "hidden" }}>
          <SectionHeader icon={<AlertTriangle size={16} color={tokens.riskMedium} />} title="Suspect Conditions" count={suspects.length} countColor={tokens.riskMedium} countBg={tokens.warningSoft} />
          <div style={{ padding: "4px 0" }}>
            {suspects.map((s, i) => (
              <div key={suspIcd(s) || i} className="hover-lift" style={{ padding: "16px 20px", margin: "6px 12px", borderRadius: 10, background: tokens.warningSoft, border: `1px solid ${tokens.warningBorder}`, display: "flex", alignItems: "center", gap: 14, transition: "all 0.2s" }}>
                <div style={{ width: 36, height: 36, borderRadius: 10, background: tokens.warningSoft, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                  <AlertTriangle size={16} color={tokens.riskMedium} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <span style={{ fontSize: 14, fontWeight: 600, color: tokens.slate900 }}>{s.condition || "Unknown"}</span>
                    <code style={{ fontSize: 11, fontWeight: 700, background: tokens.warningSoft, color: tokens.warningText, padding: "3px 8px", borderRadius: 6, border: `1px solid ${tokens.warningBorder}` }}>{suspIcd(s)}</code>
                    {(s.hcc_code || s.suspect_hcc) && (
                      <span style={{ fontSize: 11, fontWeight: 700, background: tokens.primarySoft, color: tokens.primaryDark, padding: "3px 8px", borderRadius: 6, border: `1px solid ${tokens.slate200}` }}>{s.hcc_code || s.suspect_hcc}</span>
                    )}
                  </div>
                  {suspEvidence(s) && <div style={{ fontSize: 12, color: tokens.slate500, marginTop: 6, lineHeight: 1.6 }}>{suspEvidence(s)}</div>}
                </div>
                <div style={{ width: 120, flexShrink: 0 }}><ConfBar value={suspConf(s)} /></div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Pipeline Details (collapsible) */}
      {meta && (
        <div className="premium-card animate-fade-in" style={{ overflow: "hidden" }}>
          <button onClick={() => setPipelineOpen(!pipelineOpen)} style={{ width: "100%", padding: "16px 20px", display: "flex", alignItems: "center", gap: 10, background: "none", border: "none", cursor: "pointer", borderBottom: pipelineOpen ? `1px solid ${tokens.slate100}` : "none" }}>
            <div style={{ width: 32, height: 32, borderRadius: 8, background: tokens.slate100, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <Clock size={15} color={tokens.slate500} />
            </div>
            <span style={{ fontSize: 15, fontWeight: 700, color: tokens.slate700 }}>Pipeline Details</span>
            <ChevronDown size={14} color={tokens.slate400} style={{ marginLeft: "auto", transform: pipelineOpen ? "none" : "rotate(-90deg)", transition: "transform 0.2s" }} />
          </button>
          {pipelineOpen && (
            <div style={{ padding: "18px 20px" }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 16 }}>
                {meta.pipeline_version && (
                  <div style={{ padding: "12px 14px", borderRadius: 10, background: tokens.slate50, border: `1px solid ${tokens.slate100}` }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: tokens.slate400, textTransform: "uppercase", marginBottom: 6 }}>Version</div>
                    <div style={{ fontSize: 13, fontFamily: "monospace", color: tokens.slate700, fontWeight: 600 }}>{meta.pipeline_version}</div>
                  </div>
                )}
                {meta.total_time_seconds != null && (
                  <div style={{ padding: "12px 14px", borderRadius: 10, background: tokens.slate50, border: `1px solid ${tokens.slate100}` }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: tokens.slate400, textTransform: "uppercase", marginBottom: 6 }}>Total Time</div>
                    <div style={{ fontSize: 13, fontFamily: "monospace", color: tokens.slate700, fontWeight: 600 }}>{Number(meta.total_time_seconds).toFixed(1)}s</div>
                  </div>
                )}
                {meta.turns != null && (
                  <div style={{ padding: "12px 14px", borderRadius: 10, background: tokens.slate50, border: `1px solid ${tokens.slate100}` }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: tokens.slate400, textTransform: "uppercase", marginBottom: 6 }}>Turns</div>
                    <div style={{ fontSize: 13, fontFamily: "monospace", color: tokens.slate700, fontWeight: 600 }}>{meta.turns}</div>
                  </div>
                )}
              </div>
              {(meta.stages?.length ?? 0) > 0 && (
                <div style={{ marginTop: 16 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: tokens.slate400, textTransform: "uppercase", marginBottom: 8 }}>Stages</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                    {meta.stages!.map((s: string, i: number) => (
                      <span key={i} style={{ fontSize: 11, fontFamily: "monospace", padding: "4px 10px", borderRadius: 6, border: `1px solid ${tokens.slate200}`, color: tokens.slate500, background: tokens.slate50 }}>{s}</span>
                    ))}
                  </div>
                </div>
              )}
              {meta.timings && Object.keys(meta.timings).length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: tokens.slate400, textTransform: "uppercase", marginBottom: 8 }}>Timing</div>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 8 }}>
                    {Object.entries(meta.timings).map(([k, v]) => (
                      <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "8px 12px", borderRadius: 8, background: tokens.slate50, border: `1px solid ${tokens.slate100}`, fontSize: 12 }}>
                        <span style={{ fontFamily: "monospace", color: tokens.slate500 }}>{k}</span>
                        <span style={{ fontFamily: "monospace", fontWeight: 700, color: tokens.slate700 }}>
                          {typeof v === "number" ? `${(v as number).toFixed(2)}s` : String(v)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Coding Notes */}
      {result.coding_notes && (
        <div className="premium-card animate-fade-in" style={{ padding: "18px 20px", marginTop: 20 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: tokens.slate700, marginBottom: 10, display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 28, height: 28, borderRadius: 7, background: tokens.slate100, display: "flex", alignItems: "center", justifyContent: "center" }}>
              <FileText size={13} color={tokens.slate500} />
            </div>
            Coding Notes
          </div>
          <div style={{ fontSize: 13, color: tokens.slate500, lineHeight: 1.7, whiteSpace: "pre-wrap", padding: "14px 16px", borderRadius: 10, background: tokens.slate50, border: `1px solid ${tokens.slate100}` }}>{result.coding_notes}</div>
        </div>
      )}
    </div>
  );
}
