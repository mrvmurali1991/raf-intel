"use client";

/**
 * /review-queue — Coder's unified work queue.
 *
 * Tabs: HCC Candidates · Suspects · Provider Queries
 * Each row: patient, condition, HCC, confidence, evidence snippet (click →
 * opens source note with span highlighted), MEAT badges, Accept/Reject/Edit.
 *
 * Consumes:
 *   GET  /api/review/candidates?kind=&status=open
 *   POST /api/review/decision  { candidate_id, decision, notes?, edited_icd10? }
 */

import React, { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Sparkles, ClipboardList, Stethoscope, MessageSquare,
  Check, X, Pencil, FileSearch, ChevronRight, AlertCircle,
} from "lucide-react";
import api from "@/lib/api";
import { useToast } from "@/components/Toast";
import { C, FONT_SYS, FONT_MONO, initialsColor, deriveInitials } from "@/lib/ui-utils";

type ItemKind = "hcc_candidate" | "suspect" | "provider_query";

interface ReviewItem {
  id: string;
  kind: ItemKind;
  patient_id: number;
  patient_name: string | null;
  hcc: number | null;
  icd10: string | null;
  condition: string | null;
  confidence: number | null;
  evidence_snippet: string | null;
  evidence_source_id?: number | null;
  evidence_span?: [number, number] | null;
  meat?: { monitor: boolean; evaluate: boolean; assess: boolean; treat: boolean } | null;
  status: string;
  created_at?: string | null;
  days_to_cutoff?: number | null;
  expected_dollar_impact?: number | null;
}

interface CandidatesResponse { items: ReviewItem[]; total: number; }

const TABS: { key: ItemKind; label: string; Icon: React.ComponentType<{ size?: number }> }[] = [
  { key: "hcc_candidate",  label: "HCC Candidates",  Icon: ClipboardList },
  { key: "suspect",        label: "Suspects",        Icon: Stethoscope },
  { key: "provider_query", label: "Provider Queries", Icon: MessageSquare },
];

function confColor(c: number | null): string {
  const v = c ?? 0;
  if (v >= 0.85) return C.low;
  if (v >= 0.65) return C.medium;
  return C.textSubtle;
}

type SortBy = "deadline" | "dollars" | "priority";

async function fetchCandidates(kind: ItemKind, sortBy: SortBy): Promise<CandidatesResponse> {
  const { data } = await api.get<CandidatesResponse>("/api/review/candidates", {
    params: { kind, status: "open", limit: 500, sort_by: sortBy },
  });
  return data;
}

async function postDecision(args: {
  candidate_id: string;
  decision: "accept" | "reject" | "edit";
  notes?: string;
  edited_icd10?: string;
}): Promise<{ ok: boolean; audit_id: number | null }> {
  const { data } = await api.post("/api/review/decision", args);
  return data;
}

/* ====================================================================== */
/* MEAT badge                                                              */
/* ====================================================================== */
function MeatPills({ m }: { m: ReviewItem["meat"] }) {
  if (!m) return null;
  const entries: [string, boolean][] = [
    ["M", m.monitor], ["E", m.evaluate], ["A", m.assess], ["T", m.treat],
  ];
  return (
    <div style={{ display: "inline-flex", gap: 4 }}>
      {entries.map(([k, v]) => (
        <span key={k} title={`${k} ${v ? "present" : "missing"}`} style={{
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          width: 20, height: 20, borderRadius: 6, fontSize: 10, fontWeight: 700,
          fontFamily: FONT_MONO,
          backgroundColor: v ? C.brandSoft : "#F1F5F9",
          color: v ? C.brand : C.textSubtle,
          border: `1px solid ${v ? C.brandRing : C.border}`,
        }}>{k}</span>
      ))}
    </div>
  );
}

/* ====================================================================== */
/* Evidence snippet with optional span highlight                           */
/* ====================================================================== */
function EvidenceSnippet({
  it, onOpen,
}: {
  it: ReviewItem;
  onOpen: (it: ReviewItem) => void;
}) {
  const snip = it.evidence_snippet;
  if (!snip) return null;

  const span = it.evidence_span;
  const hasOffsets = span != null && span[0] >= 0 && span[1] > span[0] && span[1] <= snip.length;

  if (hasOffsets) {
    const [s, e] = span as [number, number];
    const CTX = 20;
    const leadEllipsis = s > CTX;
    const trailEllipsis = (e + CTX) < snip.length;
    const pre  = snip.slice(Math.max(0, s - CTX), s);
    const mid  = snip.slice(s, e);
    const post = snip.slice(e, Math.min(snip.length, e + CTX));
    return (
      <div style={{ marginTop: 4 }}>
        <span style={{ fontSize: 12, color: "#64748B", fontStyle: "italic" }}>
          {leadEllipsis ? "…" : ""}{pre}
          <mark style={{
            backgroundColor: "#FEF08A", borderRadius: 3,
            padding: "0 2px", fontStyle: "normal",
          }}>{mid}</mark>
          {post}{trailEllipsis ? "…" : ""}
        </span>
        {it.evidence_source_id != null && (
          <button
            onClick={() => onOpen(it)}
            title="Open full note"
            style={{
              marginLeft: 8, padding: "1px 6px", border: "1px solid #E2E8F0",
              borderRadius: 5, background: "#fff", fontSize: 11,
              fontWeight: 600, color: "#64748B", cursor: "pointer",
            }}
          >Open full note</button>
        )}
      </div>
    );
  }

  // Fallback: offsets absent — bold-wrap the whole snippet
  return (
    <button
      onClick={() => onOpen(it)}
      title="Open source note"
      style={{
        marginTop: 4, padding: 0, border: "none", background: "none",
        cursor: "pointer", textAlign: "left",
        fontSize: 12, color: "#64748B", fontStyle: "italic",
        textDecoration: "underline dotted", textUnderlineOffset: 2,
      }}
    ><strong>&ldquo;{snip}&rdquo;</strong></button>
  );
}

/* ====================================================================== */
/* Page                                                                    */
/* ====================================================================== */

export default function ReviewQueuePage() {
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState<ItemKind>("hcc_candidate");
  const [editing, setEditing] = useState<{ id: string; icd10: string } | null>(null);
  const [sortBy, setSortBy] = useState<SortBy>("deadline");

  const { data, isLoading, isError } = useQuery({
    queryKey: ["review-queue", tab, sortBy],
    queryFn: () => fetchCandidates(tab, sortBy),
  });

  const counts = useMemo(() => ({
    hcc_candidate: tab === "hcc_candidate" ? data?.total ?? 0 : undefined,
    suspect:       tab === "suspect" ? data?.total ?? 0 : undefined,
    provider_query: tab === "provider_query" ? data?.total ?? 0 : undefined,
  }), [tab, data?.total]);

  const decideMut = useMutation({
    mutationFn: postDecision,
    onSuccess: (_r, vars) => {
      qc.invalidateQueries({ queryKey: ["review-queue"] });
      toast.success("Recorded",
        `Decision '${vars.decision}' saved${_r.audit_id ? ` · audit #${_r.audit_id}` : ""}`);
      setEditing(null);
    },
    onError: () => toast.error("Error", "Could not save decision."),
  });

  const openEvidence = (it: ReviewItem) => {
    const q = new URLSearchParams();
    if (it.evidence_source_id != null) q.set("doc", String(it.evidence_source_id));
    if (it.evidence_span)
      q.set("span", `${it.evidence_span[0]}-${it.evidence_span[1]}`);
    q.set("highlight", it.evidence_snippet ?? "");
    router.push(`/patients/${it.patient_id}?${q.toString()}`);
  };

  const items = data?.items ?? [];
  const hasCutoff = items.some((it) => it.days_to_cutoff != null);
  const hasDollars = items.some((it) => it.expected_dollar_impact != null);

  return (
    <div style={{
      background: C.bgPage, minHeight: "100vh", padding: "32px 40px 48px",
      fontFamily: FONT_SYS, color: C.text,
    }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 24 }}>
        <div style={{
          width: 48, height: 48, borderRadius: 14,
          background: `linear-gradient(135deg, ${C.brand} 0%, ${C.brandDark} 100%)`,
          display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: "0 6px 16px rgba(15, 118, 110, 0.25)",
        }}>
          <Sparkles size={22} color="#fff" strokeWidth={2.25} />
        </div>
        <div style={{ flex: 1 }}>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700, letterSpacing: "-0.02em" }}>
            Review Queue
          </h1>
          <p style={{ margin: "4px 0 0", fontSize: 13, color: C.textSubtle }}>
            AI-generated work items pending coder review.
            Every decision is written to the audit log.
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <label htmlFor="rq-sort" style={{ fontSize: 12, fontWeight: 600, color: C.label }}>
            Sort by
          </label>
          <select
            id="rq-sort"
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as SortBy)}
            style={{
              height: 32, padding: "0 10px", borderRadius: 8,
              border: `1px solid ${C.border}`, backgroundColor: "#fff",
              fontSize: 12, fontWeight: 600, color: C.text,
              fontFamily: FONT_SYS, cursor: "pointer",
            }}
          >
            <option value="deadline">Deadline</option>
            <option value="dollars">Dollar Impact</option>
            <option value="priority">Priority</option>
          </select>
        </div>
      </div>

      {/* Tabs */}
      <div style={{
        display: "inline-flex", backgroundColor: "#fff",
        border: `1px solid ${C.border}`, borderRadius: 10, padding: 3,
        gap: 2, height: 38, marginBottom: 16,
      }}>
        {TABS.map(({ key, label, Icon }) => {
          const active = tab === key;
          const c = counts[key];
          return (
            <button key={key} onClick={() => setTab(key)} style={{
              display: "inline-flex", alignItems: "center", gap: 8,
              height: 30, padding: "0 14px", borderRadius: 7, border: "none",
              backgroundColor: active ? C.text : "transparent",
              color: active ? "#fff" : C.textMuted,
              fontSize: 13, fontWeight: 600, cursor: "pointer",
              fontFamily: FONT_SYS,
            }}>
              <Icon size={14} />
              {label}
              {c !== undefined && (
                <span style={{
                  fontSize: 11, fontWeight: 600,
                  color: active ? "rgba(255,255,255,0.7)" : C.label,
                }}>{c}</span>
              )}
            </button>
          );
        })}
      </div>

      {isError && (
        <div role="alert" style={{
          display: "flex", alignItems: "center", gap: 12, background: C.highSoft,
          border: `1px solid #FCA5A5`, borderRadius: 12, padding: "12px 16px",
          marginBottom: 16, fontSize: 13, color: C.high, fontWeight: 600,
        }}>
          <AlertCircle size={18} /> Failed to load review queue.
        </div>
      )}

      {/* Table */}
      <div style={{
        backgroundColor: C.bgCard, border: `1px solid ${C.border}`,
        borderRadius: 14, overflow: "hidden",
      }}>
        <div style={{
          display: "grid",
          gridTemplateColumns: [
            "minmax(200px,1.4fr)",
            "minmax(240px,2fr)",
            "110px",
            "140px",
            "120px",
            hasCutoff ? "90px" : null,
            hasDollars ? "110px" : null,
            "200px",
          ].filter(Boolean).join(" "),
          gap: 14, padding: "12px 22px", backgroundColor: C.bgBand,
          borderBottom: `1px solid ${C.border}`,
          fontSize: 11, fontWeight: 600, textTransform: "uppercase",
          letterSpacing: "0.06em", color: C.label,
        }}>
          <div>Patient</div>
          <div>Condition / Evidence</div>
          <div>HCC</div>
          <div>Confidence</div>
          <div>MEAT</div>
          {hasCutoff && <div>Days Left</div>}
          {hasDollars && <div>$ Impact</div>}
          <div style={{ justifySelf: "end" }}>Actions</div>
        </div>

        {isLoading && (
          <div style={{ padding: 48, textAlign: "center", color: C.textSubtle }}>
            Loading…
          </div>
        )}

        {!isLoading && items.length === 0 && (
          <div style={{ padding: 56, textAlign: "center" }}>
            <FileSearch size={30} color={C.brand} />
            <div style={{ marginTop: 10, fontWeight: 700 }}>Queue is empty</div>
            <div style={{ fontSize: 13, color: C.textSubtle }}>
              No open items for this tab.
            </div>
          </div>
        )}

        {!isLoading && items.map((it, idx) => {
          const initials = deriveInitials(it.patient_name, undefined, it.patient_id);
          const aColor = initialsColor(it.patient_name || String(it.patient_id));
          const c = it.confidence ?? 0;
          const isEditing = editing?.id === it.id;
          return (
            <div key={it.id} style={{
              display: "grid",
              gridTemplateColumns: [
                "minmax(200px,1.4fr)",
                "minmax(240px,2fr)",
                "110px",
                "140px",
                "120px",
                hasCutoff ? "90px" : null,
                hasDollars ? "110px" : null,
                "200px",
              ].filter(Boolean).join(" "),
              gap: 14, padding: "14px 22px", alignItems: "center",
              borderBottom: idx < items.length - 1 ? `1px solid ${C.rowDivider}` : "none",
              borderLeft: `3px solid ${confColor(c)}`,
            }}>
              {/* Patient */}
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{
                  width: 36, height: 36, borderRadius: 10, color: "#fff",
                  background: `linear-gradient(135deg, ${aColor}, ${aColor}CC)`,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 12, fontWeight: 700,
                }}>{initials}</div>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 600 }}>
                    {it.patient_name ?? `Patient ${it.patient_id}`}
                  </div>
                  <div style={{ fontSize: 11, color: C.label }}>PID {it.patient_id}</div>
                </div>
              </div>

              {/* Condition / evidence */}
              <div>
                <div style={{ fontSize: 14, fontWeight: 600 }}>
                  {it.condition ?? (it.hcc ? `HCC ${it.hcc}` : "—")}
                </div>
                <EvidenceSnippet it={it} onOpen={openEvidence} />
                {isEditing && (
                  <div style={{ marginTop: 8, display: "flex", gap: 6 }}>
                    <input
                      value={editing.icd10}
                      onChange={(e) => setEditing({ ...editing, icd10: e.target.value })}
                      placeholder="Corrected ICD-10"
                      style={{
                        height: 30, flex: 1, borderRadius: 8,
                        border: `1px solid ${C.border}`, padding: "0 10px",
                        fontFamily: FONT_MONO, fontSize: 12,
                      }}
                    />
                    <button
                      onClick={() => decideMut.mutate({
                        candidate_id: it.id, decision: "edit",
                        edited_icd10: editing.icd10,
                      })}
                      disabled={decideMut.isPending || !editing.icd10}
                      style={{
                        height: 30, padding: "0 12px", borderRadius: 8,
                        border: "none", backgroundColor: C.brand, color: "#fff",
                        fontSize: 12, fontWeight: 700, cursor: "pointer",
                      }}
                    >Save</button>
                    <button onClick={() => setEditing(null)} style={{
                      height: 30, padding: "0 10px", borderRadius: 8,
                      border: `1px solid ${C.border}`, background: "#fff",
                      fontSize: 12, fontWeight: 600, cursor: "pointer",
                    }}>Cancel</button>
                  </div>
                )}
              </div>

              {/* HCC */}
              <div style={{ fontFamily: FONT_MONO, fontSize: 13, fontWeight: 700 }}>
                {it.hcc != null ? `HCC ${it.hcc}` : "—"}
                {it.icd10 && (
                  <div style={{ fontSize: 11, color: C.textSubtle }}>{it.icd10}</div>
                )}
              </div>

              {/* Confidence */}
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{
                  flex: 1, height: 6, borderRadius: 4, backgroundColor: "#F1F5F9",
                  overflow: "hidden",
                }}>
                  <div style={{
                    width: `${Math.max(4, c * 100)}%`, height: "100%",
                    backgroundColor: confColor(c),
                  }} />
                </div>
                <span style={{
                  fontSize: 12, fontWeight: 700, color: confColor(c),
                  minWidth: 34, textAlign: "right",
                }}>{Math.round(c * 100)}%</span>
              </div>

              {/* MEAT */}
              <div><MeatPills m={it.meat} /></div>

              {/* Days to cutoff */}
              {hasCutoff && (
                <div style={{
                  fontSize: 12, fontWeight: 700,
                  color: it.days_to_cutoff != null && it.days_to_cutoff <= 7 ? C.high : C.text,
                  fontFamily: FONT_MONO,
                }}>
                  {it.days_to_cutoff != null ? `${it.days_to_cutoff}d` : "—"}
                </div>
              )}

              {/* Expected dollar impact */}
              {hasDollars && (
                <div style={{ fontSize: 12, fontWeight: 700, fontFamily: FONT_MONO, color: C.text }}>
                  {it.expected_dollar_impact != null
                    ? `$${it.expected_dollar_impact.toLocaleString("en-US", { maximumFractionDigits: 0 })}`
                    : "—"}
                </div>
              )}

              {/* Actions */}
              <div style={{
                justifySelf: "end", display: "flex", alignItems: "center", gap: 6,
              }}>
                <button
                  title="Accept"
                  onClick={() => decideMut.mutate({ candidate_id: it.id, decision: "accept" })}
                  disabled={decideMut.isPending}
                  style={{
                    width: 34, height: 34, borderRadius: 8,
                    border: `1px solid ${C.low}`, background: "transparent",
                    color: C.low, cursor: "pointer",
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}><Check size={15} strokeWidth={2.5} /></button>
                <button
                  title="Reject"
                  onClick={() => decideMut.mutate({ candidate_id: it.id, decision: "reject" })}
                  disabled={decideMut.isPending}
                  style={{
                    width: 34, height: 34, borderRadius: 8,
                    border: `1px solid ${C.high}`, background: "transparent",
                    color: C.high, cursor: "pointer",
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}><X size={15} strokeWidth={2.5} /></button>
                <button
                  title="Edit ICD-10"
                  onClick={() => setEditing({ id: it.id, icd10: it.icd10 ?? "" })}
                  style={{
                    width: 34, height: 34, borderRadius: 8,
                    border: `1px solid ${C.border}`, background: "#fff",
                    color: C.textMuted, cursor: "pointer",
                    display: "flex", alignItems: "center", justifyContent: "center",
                  }}><Pencil size={14} /></button>
                <ChevronRight size={14} color="#CBD5E1" />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
