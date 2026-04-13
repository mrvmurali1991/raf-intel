"use client";

import React from "react";
import type {
  PatientEncountersResponse,
  PatientSuspectsResponse,
  RafHistoryResponse,
  AuditPackagesResponse,
} from "@/lib/api";
import {
  C,
  formatDate,
  SectionLoader,
  Card,
} from "./shared";
import type {
  EncounterItem,
  SuspectItem,
  ScoreHistoryEntry,
  AuditPackageItem,
} from "./shared";

type TimelineEventType = "encounter" | "analysis" | "suspect" | "raf" | "audit";

interface TimelineEvent {
  id: string;
  date: string;
  type: TimelineEventType;
  title: string;
  detail?: string;
}

const ACTIVITY_TYPE_META: Record<
  TimelineEventType,
  { color: string; bgColor: string; label: string }
> = {
  encounter: { color: "#2563EB", bgColor: "#DBEAFE", label: "Encounter" },
  analysis:  { color: "#9333EA", bgColor: "#F3E8FF", label: "Analysis" },
  suspect:   { color: "#D97706", bgColor: "#FEF3C7", label: "Suspect" },
  raf:       { color: "#059669", bgColor: "#D1FAE5", label: "RAF" },
  audit:     { color: "#0D9488", bgColor: "#CCFBF1", label: "Audit" },
};

function ActivityDot({ type }: { type: TimelineEventType }) {
  const meta = ACTIVITY_TYPE_META[type];
  return (
    <div
      style={{
        width: 32, height: 32, borderRadius: "50%",
        background: meta.bgColor, border: `2px solid ${meta.color}`,
        display: "flex", alignItems: "center", justifyContent: "center",
        flexShrink: 0, zIndex: 1,
      }}
    >
      <div style={{ width: 10, height: 10, borderRadius: "50%", background: meta.color }} />
    </div>
  );
}

export function ActivityTab({
  encounters,
  encountersLoading,
  suspects,
  suspectsLoading,
  rafHistory,
  rafHistoryLoading,
  audits,
  auditsLoading,
}: {
  encounters: PatientEncountersResponse | undefined;
  encountersLoading: boolean;
  suspects: PatientSuspectsResponse | undefined;
  suspectsLoading: boolean;
  rafHistory: RafHistoryResponse | undefined;
  rafHistoryLoading: boolean;
  audits: AuditPackagesResponse | undefined;
  auditsLoading: boolean;
}) {
  const isLoading = encountersLoading || suspectsLoading || rafHistoryLoading || auditsLoading;

  const events: TimelineEvent[] = [];

  const encounterList: EncounterItem[] = (encounters?.encounters ?? []) as EncounterItem[];
  for (const enc of encounterList) {
    const reason = enc.reason || "Office Visit";
    const provider = enc.provider_fname || enc.provider_lname
      ? `${enc.provider_fname ?? ""} ${enc.provider_lname ?? ""}`.trim()
      : null;
    events.push({
      id: `enc-${enc.encounter_id}`,
      date: enc.date,
      type: "encounter",
      title: reason,
      detail: provider ? `Provider: ${provider}` : undefined,
    });
    if (enc.analyzed_at || enc.has_analysis) {
      events.push({
        id: `analysis-${enc.encounter_id}`,
        date: enc.analyzed_at ?? enc.date,
        type: "analysis",
        title: "AI Analysis completed",
        detail: `Encounter #${enc.encounter_id}`,
      });
    }
  }

  const suspectList: SuspectItem[] = (suspects?.suspects ?? []) as SuspectItem[];
  for (const s of suspectList) {
    const dateField = s.created_at ?? s.identified_at ?? s.updated_at ?? null;
    if (dateField) {
      events.push({
        id: `suspect-${s.id ?? s.suspect_id}`,
        date: dateField,
        type: "suspect",
        title: `Suspect condition identified: ${s.condition ?? s.hcc_description ?? "Unknown"}`,
        detail: s.icd10_code ? `ICD-10: ${s.icd10_code}` : undefined,
      });
    }
  }

  const rafScores: ScoreHistoryEntry[] = (Array.isArray(rafHistory)
    ? rafHistory
    : rafHistory?.scores ?? rafHistory?.history ?? []) as ScoreHistoryEntry[];
  for (const r of rafScores) {
    const dateField = r.calculated_at ?? r.created_at ?? null;
    const score = r.raf_score ?? r.total_score ?? r.score ?? null;
    if (dateField && score !== null) {
      events.push({
        id: `raf-${r.id ?? dateField}-${rafScores.indexOf(r)}`,
        date: dateField,
        type: "raf",
        title: `RAF score calculated: ${Number(score).toFixed(3)}`,
        detail: r.model ? `Model: ${r.model}` : undefined,
      });
    }
  }

  const auditList: AuditPackageItem[] = audits?.packages ?? [];
  for (const a of auditList) {
    events.push({
      id: `audit-${a.id}`,
      date: a.created_at,
      type: "audit",
      title: "Audit package generated",
      detail: a.year ? `Year: ${a.year}` : undefined,
    });
  }

  events.sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime());

  return (
    <div style={{ maxWidth: 800 }}>
      <Card className="animate-slide-up stagger-1">
        <div style={{ marginBottom: 20 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: C.slate900 }}>
            Patient Activity Timeline
          </h3>
          <p style={{ margin: "4px 0 0", fontSize: 13, color: C.slate500 }}>
            Chronological history of all patient events
          </p>
        </div>

        {/* Legend */}
        <div style={{
          display: "flex", flexWrap: "wrap", gap: 12, marginBottom: 24,
          padding: "12px 16px", background: C.slate100, borderRadius: 8,
        }}>
          {(Object.entries(ACTIVITY_TYPE_META) as [TimelineEventType, (typeof ACTIVITY_TYPE_META)[TimelineEventType]][]).map(([type, meta]) => (
            <div key={type} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ width: 10, height: 10, borderRadius: "50%", background: meta.color }} />
              <span style={{ fontSize: 12, color: C.slate600, fontWeight: 500 }}>{meta.label}</span>
            </div>
          ))}
        </div>

        {/* Timeline body */}
        {isLoading ? (
          <SectionLoader label="Loading activity..." />
        ) : events.length === 0 ? (
          <div style={{
            display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
            padding: "48px 0", color: C.slate400, gap: 12,
          }}>
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <span style={{ fontSize: 14, fontWeight: 500 }}>No activity found</span>
            <span style={{ fontSize: 13, color: C.slate400 }}>
              Events will appear here as encounters, analyses, and RAF calculations are recorded.
            </span>
          </div>
        ) : (
          <div style={{ position: "relative" }}>
            <div style={{
              position: "absolute", left: 15, top: 0, bottom: 0,
              width: 2, background: C.slate200, zIndex: 0,
            }} />
            <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
              {events.map((event, idx) => {
                const meta = ACTIVITY_TYPE_META[event.type];
                const isLast = idx === events.length - 1;
                return (
                  <div key={event.id} style={{ display: "flex", gap: 16, alignItems: "flex-start", paddingBottom: isLast ? 0 : 20 }}>
                    <ActivityDot type={event.type} />
                    <div style={{ flex: 1, paddingTop: 4, minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 2, flexWrap: "wrap" }}>
                        <span style={{ fontSize: 13, fontWeight: 600, color: C.slate900 }}>{event.title}</span>
                        <span style={{
                          display: "inline-flex", alignItems: "center",
                          padding: "1px 8px", borderRadius: 12,
                          fontSize: 11, fontWeight: 600, background: meta.bgColor, color: meta.color,
                        }}>
                          {meta.label}
                        </span>
                      </div>
                      <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
                        <span style={{ fontSize: 12, color: C.slate400 }}>{formatDate(event.date)}</span>
                        {event.detail && <span style={{ fontSize: 12, color: C.slate500 }}>{event.detail}</span>}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
