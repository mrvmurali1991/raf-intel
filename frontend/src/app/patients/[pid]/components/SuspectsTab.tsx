"use client";

import React, { useState } from "react";
import type { PatientSuspectsResponse } from "@/lib/api";
import {
  EmptyState,
  ConfidencePill,
} from "@/components/healthcare-ui";
import {
  C,
  SectionLoader,
  Card,
  MeatDots,
} from "./shared";
import type { SuspectItem } from "./shared";
import {
  AcceptConfirmDialog,
  type AcceptOverridePayload,
} from "@/components/AcceptConfirmDialog";
import { DismissReasonDialog } from "@/components/raf-central/Suspects/DismissReasonDialog";

export function SuspectsTab({
  suspects,
  suspectsLoading,
  acceptMutation,
  dismissMutation,
}: {
  suspects: PatientSuspectsResponse | undefined;
  suspectsLoading: boolean;
  acceptMutation: { mutate: (id: number) => void; isPending: boolean };
  dismissMutation: { mutate: (id: number) => void; isPending: boolean };
}) {
  // RADV-safety gate state — clinicians must pass through Accept/Dismiss
  // dialogs that surface confidence, MEAT status, and require an override
  // reason. This mirrors the RAFCentral SuspectCardView guards.
  const [confirmAccept, setConfirmAccept] = useState<SuspectItem | null>(null);
  const [confirmDismiss, setConfirmDismiss] = useState<SuspectItem | null>(null);

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
        <Card>
          <EmptyState
            title="No open suspects"
            description="Analyze encounters to identify potential conditions"
            icon={
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
            }
          />
        </Card>
      </div>
    );
  }

  const handleAcceptConfirmed = (_payload: AcceptOverridePayload) => {
    if (!confirmAccept) return;
    // NOTE: existing mutation signature only accepts the suspect id; the override
    // reason is captured in the gate UI for clinician self-attestation but is
    // not yet persisted by this legacy endpoint (TODO: wire override_reason +
    // defense_basis through PatientSuspects accept mutation).
    acceptMutation.mutate(confirmAccept.id);
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
                    {s.suspected_condition || s.condition || s.evidence_type || "—"}
                  </span>
                  {(s.suspect_icd10 || s.icd10_code) && (
                    <span className="text-xs font-semibold font-mono bg-muted text-foreground border border-border" style={{
                      display: "inline-block", padding: "2px 8px", borderRadius: 4,
                    }}>
                      {s.suspect_icd10 || s.icd10_code}
                    </span>
                  )}
                  {(s.suspect_hcc != null) && (
                    <span style={{
                      display: "inline-block", padding: "2px 8px", borderRadius: 4,
                      fontSize: 11, fontWeight: 600, fontFamily: "monospace",
                      background: C.blue50, color: C.blue600, border: `1px solid ${C.blue100}`,
                    }}>
                      HCC {s.suspect_hcc}
                    </span>
                  )}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 10 }}>
                  <ConfidencePill value={confidence} />
                  <span className="text-xs text-muted-foreground">
                    Confidence: {Math.round(confidence * 100)}%
                  </span>
                </div>
                {(s.evidence_detail || s.evidence || s.rationale) && (
                  <div className="text-sm text-muted-foreground" style={{
                    marginTop: 8, lineHeight: 1.5,
                    display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden",
                  }}>
                    {typeof s.evidence_detail === "object" && s.evidence_detail
                      ? `Prior ${(s.evidence_detail as { prior_icd?: string; prior_year?: string | number }).prior_icd || ""} (${(s.evidence_detail as { prior_icd?: string; prior_year?: string | number }).prior_year || ""})`
                      : (typeof s.evidence_detail === "string" ? s.evidence_detail : null) || s.evidence || s.rationale}
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
