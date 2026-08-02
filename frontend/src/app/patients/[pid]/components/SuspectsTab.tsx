"use client";

import React, { useState } from "react";
import type { PatientSuspectsResponse } from "@/lib/api";
import {
  ConfidencePill,
} from "@/components/healthcare-ui";
import { formatCurrency } from "@/lib/format";
import { SectionBanner } from "@/components/ui/section-banner";
import {
  C,
  SectionLoader,
  Card,
  MeatDots,
  WithTooltip,
} from "./shared";
import type { SuspectItem } from "./shared";
import {
  AcceptConfirmDialog,
  type AcceptOverridePayload,
} from "@/components/AcceptConfirmDialog";
import { DismissReasonDialog } from "@/components/raf-central/Suspects/DismissReasonDialog";
import { humanizeEvidence } from "@/lib/evidence-labels";

export function SuspectsTab({
  suspects,
  suspectsLoading,
  acceptMutation,
  dismissMutation,
}: {
  suspects: PatientSuspectsResponse | undefined;
  suspectsLoading: boolean;
  acceptMutation: { mutate: (args: { id: number; override_reason?: string; defense_basis?: string }) => void; isPending: boolean };
  dismissMutation: { mutate: (id: number) => void; isPending: boolean };
}) {
  // RADV-safety gate state — clinicians must pass through Accept/Dismiss
  // dialogs that surface confidence, MEAT status, and require an override
  // reason. This mirrors the RAFCentral SuspectCardView guards.
  const [confirmAccept, setConfirmAccept] = useState<SuspectItem | null>(null);
  const [confirmDismiss, setConfirmDismiss] = useState<SuspectItem | null>(null);
  const [expandedWhyIds, setExpandedWhyIds] = useState<Set<number>>(new Set());

  if (suspectsLoading) {
    return <SectionLoader label="Loading suspect conditions..." />;
  }

  const suspectList: SuspectItem[] = (suspects?.suspects ?? []) as SuspectItem[];

  // Persistent AI disclaimer bar — rendered above both empty state and list
  // so clinicians always see attestation requirement before acting.
  const DisclaimerBar = (
    <div
      className="bg-muted/50 px-3 py-1.5 text-[11px] text-muted-foreground border-b border-border"
      role="note"
    >
      AI suggestions are decision aids — clinician review and attestation are required before billing.
    </div>
  );

  if (!suspectList.length) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {DisclaimerBar}
        <SectionBanner message="No open suspect conditions for this patient. Analyze encounters to surface HCC opportunities." />
      </div>
    );
  }

  const handleAcceptConfirmed = (payload: AcceptOverridePayload) => {
    if (!confirmAccept) return;
    acceptMutation.mutate({ id: confirmAccept.id, ...payload });
    setConfirmAccept(null);
  };

  const handleDismissConfirmed = (_reason: string) => {
    if (!confirmDismiss) return;
    // TODO: legacy dismiss mutation only takes the suspect id; persist `reason`
    // when the endpoint signature is extended.
    dismissMutation.mutate(confirmDismiss.id);
    setConfirmDismiss(null);
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {DisclaimerBar}
      {suspectList.map((s: SuspectItem, idx: number) => {
        const confidence = s.confidence_score ?? s.confidence ?? 0;
        const confidenceColor = confidence >= 0.8 ? C.emerald600 : confidence >= 0.5 ? C.amber600 : C.red600;
        return (
          <Card key={s.id} className={`hover-lift animate-slide-up stagger-${Math.min(idx + 1, 6)}`} style={{ padding: 20, borderLeft: `4px solid ${confidenceColor}` }}>
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <span className="text-sm font-semibold text-foreground">
                    {s.suspected_condition || s.condition || (s.evidence_type ? humanizeEvidence(s.evidence_type) : null) || "—"}
                  </span>
                  {(s.suspect_icd10 || s.icd10_code) && (
                    <span className="text-xs font-semibold font-mono bg-muted text-foreground border border-border" style={{
                      display: "inline-block", padding: "2px 8px", borderRadius: 4,
                    }}>
                      {s.suspect_icd10 || s.icd10_code}
                    </span>
                  )}
                  {(s.suspect_hcc != null) && (
                    <WithTooltip tip={`HCC ${s.suspect_hcc}${s.hcc_coefficient ? ` — RAF coefficient: +${Number(s.hcc_coefficient).toFixed(3)}` : ""}${s.hcc_coefficient ? `. Estimated annual revenue uplift: ${formatCurrency(Math.round(Number(s.hcc_coefficient) * 10000))} (at $10,000/RAF point). Accepting and attesting this condition adds this coefficient to the patient's total RAF score.` : ""}`}>
                      <span
                        data-testid={`suspect-hcc-chip-${s.suspect_hcc}`}
                        style={{
                          display: "inline-block", padding: "2px 8px", borderRadius: 4,
                          fontSize: 11, fontWeight: 600, fontFamily: "monospace",
                          background: C.blue50, color: C.blue600, border: `1px solid ${C.blue100}`,
                          cursor: "help",
                        }}
                      >
                        HCC {s.suspect_hcc}
                      </span>
                    </WithTooltip>
                  )}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10 }}>
                  <WithTooltip tip={`AI confidence score: ${Math.round(confidence * 100)}%. Reflects the model's certainty that this condition is clinically present based on available evidence (notes, labs, medications, prior codes). Scores ≥80% are high confidence; 50–79% require closer review.`}>
                    <span data-testid={`suspect-confidence-${s.id}`} style={{ cursor: "help", display: "inline-flex" }}>
                      <ConfidencePill value={confidence} />
                    </span>
                  </WithTooltip>
                  <span className="text-xs text-muted-foreground">
                    Confidence: {Math.round(confidence * 100)}%
                  </span>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setExpandedWhyIds(prev => {
                        const next = new Set(prev);
                        if (next.has(s.id)) next.delete(s.id);
                        else next.add(s.id);
                        return next;
                      });
                    }}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold text-sky-600 dark:text-sky-400 bg-sky-50 dark:bg-sky-950 border border-sky-200 dark:border-sky-800 hover:bg-sky-100 dark:hover:bg-sky-900 transition-colors"
                    style={{ cursor: "pointer" }}
                    aria-label="Why was this condition flagged?"
                    aria-expanded={expandedWhyIds.has(s.id)}
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/>
                    </svg>
                    Why?
                  </button>
                </div>
                {expandedWhyIds.has(s.id) && (
                  <div className="mt-2 p-3 rounded-lg bg-sky-50 dark:bg-sky-950 border border-sky-200 dark:border-sky-800" style={{ fontSize: 12, lineHeight: 1.6 }}>
                    <div className="font-bold text-sky-700 dark:text-sky-300 mb-1" style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.05em" }}>
                      Why This Condition Was Flagged
                    </div>
                    <ul className="m-0 pl-4 text-sky-900 dark:text-sky-200" style={{ listStyleType: "disc" }}>
                      {s.source && <li>Source: <strong>{s.source}</strong></li>}
                      {(s.evidence_detail || s.evidence || s.rationale) && (
                        <li>Evidence: {typeof s.evidence_detail === "string" ? s.evidence_detail : s.evidence || s.rationale || "Clinical data suggests this condition"}</li>
                      )}
                      {(s.confidence_score ?? s.confidence ?? 0) > 0 && (
                        <li>AI confidence: <strong>{Math.round((s.confidence_score ?? s.confidence ?? 0) * 100)}%</strong></li>
                      )}
                      {s.suspect_hcc != null && (
                        <li>Maps to HCC {s.suspect_hcc}{s.hcc_coefficient ? ` (RAF +${Number(s.hcc_coefficient).toFixed(3)}, est. ${formatCurrency(Math.round(Number(s.hcc_coefficient) * 10000))}/yr)` : ""}</li>
                      )}
                      {s.meat_evidence && (
                        <li>MEAT status: {
                          (["monitor", "evaluate", "assess", "treat"] as const).filter(k => {
                            const ev = s.meat_evidence as Record<string, unknown>;
                            return ev && (ev[k] || ev[k.charAt(0).toUpperCase()] || ev[k.charAt(0)]);
                          }).length
                        }/4 documented</li>
                      )}
                    </ul>
                  </div>
                )}
                {(s.evidence_detail || s.evidence || s.rationale) && (
                  <div style={{ marginTop: 8 }}>
                    {/* Render evidence_detail with excerpt key first */}
                    {(() => {
                      const ed = s.evidence_detail;
                      // Try to surface excerpt / text from structured JSON
                      let excerpt: string | null = null;
                      if (typeof ed === "object" && ed !== null) {
                        const edObj = ed as Record<string, unknown>;
                        excerpt = (
                          (typeof edObj.excerpt === "string" ? edObj.excerpt : null) ||
                          (typeof edObj.text === "string" ? edObj.text : null) ||
                          (typeof edObj.snippet === "string" ? edObj.snippet : null) ||
                          (typeof edObj.summary === "string" ? edObj.summary : null) ||
                          (typeof edObj.rationale === "string" ? edObj.rationale : null) ||
                          // Legacy: prior_icd recap shape
                          (edObj.prior_icd ? `Prior ${edObj.prior_icd} (${edObj.prior_year || ""})` : null)
                        );
                      } else if (typeof ed === "string") {
                        // Try JSON parse first
                        try {
                          const parsed = JSON.parse(ed) as Record<string, unknown>;
                          excerpt = (typeof parsed.excerpt === "string" ? parsed.excerpt : null)
                            || (typeof parsed.text === "string" ? parsed.text : null)
                            || (typeof parsed.summary === "string" ? parsed.summary : null)
                            || ed;
                        } catch {
                          excerpt = ed;
                        }
                      }
                      const displayText = excerpt || s.evidence || s.rationale || "";
                      if (!displayText) return null;
                      return (
                        <WithTooltip
                          tip={displayText.length > 120 ? displayText : ""}
                          side="left"
                        >
                          <div
                            className="text-sm text-muted-foreground"
                            style={{
                              lineHeight: 1.5,
                              padding: "6px 10px",
                              borderRadius: 6,
                              background: "hsl(var(--muted))",
                              borderLeft: "3px solid hsl(var(--primary) / 0.3)",
                              display: "-webkit-box",
                              WebkitLineClamp: 3,
                              WebkitBoxOrient: "vertical",
                              overflow: "hidden",
                              cursor: displayText.length > 120 ? "help" : "default",
                            }}
                          >
                            {displayText}
                          </div>
                        </WithTooltip>
                      );
                    })()}
                  </div>
                )}
                {s.meat_evidence && (
                  <div style={{ marginTop: 8 }}>
                    <MeatDots evidence={s.meat_evidence} />
                  </div>
                )}
                {s.source && (
                  <div className="text-xs text-muted-foreground" style={{ marginTop: 6 }}>
                    Source: {s.source}
                  </div>
                )}
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: 6, flexShrink: 0 }}>
                <button
                  onClick={() => setConfirmAccept(s)}
                  disabled={acceptMutation.isPending}
                  aria-label="Accept suspect with confirmation"
                  style={{
                    display: "inline-flex", alignItems: "center", gap: 6,
                    padding: "8px 16px", borderRadius: 8,
                    border: `1px solid ${C.emerald500}`, background: C.emerald50, color: C.emerald600,
                    fontSize: 12, fontWeight: 600,
                    cursor: acceptMutation.isPending ? "not-allowed" : "pointer",
                    opacity: acceptMutation.isPending ? 0.6 : 1,
                  }}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                  Accept
                </button>
                <button
                  onClick={() => setConfirmDismiss(s)}
                  disabled={dismissMutation.isPending}
                  aria-label="Dismiss suspect with reason"
                  style={{
                    display: "inline-flex", alignItems: "center", gap: 6,
                    padding: "8px 16px", borderRadius: 8,
                    border: `1px solid ${C.red500}`, background: C.red50, color: C.red600,
                    fontSize: 12, fontWeight: 600,
                    cursor: dismissMutation.isPending ? "not-allowed" : "pointer",
                    opacity: dismissMutation.isPending ? 0.6 : 1,
                  }}
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="18" y1="6" x2="6" y2="18" />
                    <line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                  Dismiss
                </button>
              </div>
            </div>
          </Card>
        );
      })}

      {/* RADV accept gate — surfaces confidence/MEAT risk and forces override
          reason + defense basis before the mutation fires. */}
      <AcceptConfirmDialog
        open={confirmAccept !== null}
        onClose={() => setConfirmAccept(null)}
        onConfirm={handleAcceptConfirmed}
        suspect={{
          hcc_code: confirmAccept?.suspect_hcc ?? confirmAccept?.hcc_code ?? null,
          icd10_code: confirmAccept?.suspect_icd10 ?? confirmAccept?.icd10_code ?? null,
          confidence: confirmAccept?.confidence_score ?? confirmAccept?.confidence ?? null,
          meat_status: null,
          meat_count: null,
          clinical_rule_violation: null,
          expected_dollar_impact: null,
        }}
      />

      <DismissReasonDialog
        open={confirmDismiss !== null}
        suspectLabel={
          confirmDismiss
            ? [
                confirmDismiss.suspected_condition || confirmDismiss.condition || "",
                confirmDismiss.suspect_icd10 || confirmDismiss.icd10_code || "",
              ]
                .filter(Boolean)
                .join(" · ")
            : ""
        }
        onCancel={() => setConfirmDismiss(null)}
        onSubmit={handleDismissConfirmed}
      />
    </div>
  );
}
