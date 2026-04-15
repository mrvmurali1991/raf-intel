"use client";

import React from "react";
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
  if (suspectsLoading) {
    return <SectionLoader label="Loading suspect conditions..." />;
  }

  const suspectList: SuspectItem[] = (suspects?.suspects ?? []) as SuspectItem[];
  if (!suspectList.length) {
    return (
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
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {suspectList.map((s: SuspectItem, idx: number) => {
        const confidence = s.confidence_score ?? s.confidence ?? 0;
        const confidenceColor = confidence >= 0.8 ? C.emerald600 : confidence >= 0.5 ? C.amber600 : C.red600;
        return (
          <Card key={s.id} className={`hover-lift animate-slide-up stagger-${Math.min(idx + 1, 6)}`} style={{ padding: 20, borderLeft: `4px solid ${confidenceColor}` }}>
            <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16 }}>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 14, fontWeight: 600, color: C.slate800 }}>
                    {s.suspected_condition || (s as any).description || s.evidence_type || "\u2014"}
                  </span>
                  {(s.suspect_icd10 || (s as any).icd10_code) && (
                    <span style={{
                      display: "inline-block", padding: "2px 8px", borderRadius: 4,
                      fontSize: 11, fontWeight: 600, fontFamily: "monospace",
                      background: C.slate100, color: C.slate700, border: `1px solid ${C.slate200}`,
                    }}>
                      {s.suspect_icd10 || (s as any).icd10_code}
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
                </div>
                {(s.evidence_detail || (s as any).evidence || (s as any).rationale) && (
                  <div style={{
                    fontSize: 13, color: C.slate500, marginTop: 8, lineHeight: 1.5,
                    display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden",
                  }}>
                    {typeof s.evidence_detail === "object" && s.evidence_detail
                      ? `Prior ${(s.evidence_detail as any).prior_icd || ""} (${(s.evidence_detail as any).prior_year || ""})`
                      : s.evidence_detail || (s as any).evidence || (s as any).rationale}
                  </div>
                )}
                {s.meat_evidence && (
                  <div style={{ marginTop: 8 }}>
                    <MeatDots evidence={s.meat_evidence || (s as any).meat} />
                  </div>
                )}
                {s.source && (
                  <div style={{ fontSize: 11, color: C.slate400, marginTop: 6 }}>
                    Source: {s.source}
                  </div>
                )}
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: 6, flexShrink: 0 }}>
                <button
                  onClick={() => acceptMutation.mutate(s.id)}
                  disabled={acceptMutation.isPending}
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
                  onClick={() => dismissMutation.mutate(s.id)}
                  disabled={dismissMutation.isPending}
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
    </div>
  );
}
