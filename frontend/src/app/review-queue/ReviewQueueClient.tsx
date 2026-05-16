"use client";

/**
 * ReviewQueueClient — the interactive review queue table.
 *
 * Extracted from page.tsx so it can be lazy-loaded with dynamic({ ssr: false }).
 * This eliminates SSR parse cost (~661 lines) and avoids server-side execution
 * of axios / react-query hooks.
 *
 * TODO(rsc): Full RSC shell with server-side initial-items fetch is blocked by
 * the auth model: the Bearer token lives in client memory (registered via
 * registerAuthInterceptors in auth-context). To unblock server-side fetch:
 *   1. Switch to HttpOnly cookie auth so the token is forwarded automatically.
 *   2. Add a server action or Route Handler that reads the cookie and calls
 *      GET /api/review/candidates, then passes initialItems as a prop.
 *   3. Remove this TODO and convert page.tsx to a true Server Component.
 */

import React, { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Sparkles, ClipboardList, Stethoscope, MessageSquare,
  Check, X, Pencil, FileSearch, ChevronRight, AlertCircle, RefreshCw,
} from "lucide-react";
import api from "@/lib/api";
import { tokens } from "@/styles/tokens";
import { DataQualityBanner } from "@/components/DataQualityBanner";
import { useToast } from "@/components/Toast";
import { C, FONT_SYS, FONT_MONO, initialsColor, deriveInitials } from "@/lib/ui-utils";
import { needsAcceptGate } from "@/lib/confidence";
import {
  AcceptConfirmDialog,
  type AcceptOverridePayload,
} from "@/components/AcceptConfirmDialog";

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
  /** Added by Agent-G — MEAT completeness status string. */
  meat_status?: string | null;
  /** Added by Agent-G — number of present MEAT elements (0-4). */
  meat_count?: number | null;
  /** Added by Agent-N — truthy when a clinical sanity rule is violated. */
  clinical_rule_violation?: boolean | string | null;
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
  override_reason?: string;
  defense_basis?: string;
}): Promise<{ ok: boolean; audit_id: number | null }> {
  try {
    const { data } = await api.post("/api/review/decision", args);
    return data;
  } catch (err: unknown) {
    // Backend may not yet accept override fields — strip and retry once.
    const status = (err as { response?: { status?: number } })?.response?.status;
    if (status === 400 && (args.override_reason !== undefined || args.defense_basis !== undefined)) {
      const { override_reason: _or, defense_basis: _db, ...safeArgs } = args;
      const { data } = await api.post("/api/review/decision", safeArgs);
      return data;
    }
    throw err;
  }
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
          backgroundColor: v ? C.brandSoft : tokens.slate100,
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
        <span style={{ fontSize: 12, color: tokens.slate500, fontStyle: "italic" }}>
          {leadEllipsis ? "…" : ""}{pre}
          <mark style={{
            backgroundColor: tokens.warningSoft, borderRadius: 3,
            padding: "0 2px", fontStyle: "normal",
          }}>{mid}</mark>
          {post}{trailEllipsis ? "…" : ""}
        </span>
        {it.evidence_source_id != null && (
          <button
            onClick={() => onOpen(it)}
            title="Open full note"
            style={{
              marginLeft: 8, padding: "1px 6px", border: `1px solid ${tokens.slate200}`,
              borderRadius: 5, background: tokens.white, fontSize: 11,
              fontWeight: 600, color: tokens.slate500, cursor: "pointer",
            }}
          >Open full note</button>
        )}
      </div>
    );
  }

  return (
    <button
      onClick={() => onOpen(it)}
      title="Open source note"
      style={{
        marginTop: 4, padding: 0, border: "none", background: "none",
        cursor: "pointer", textAlign: "left",
        fontSize: 12, color: tokens.slate500, fontStyle: "italic",
        textDecoration: "underline dotted", textUnderlineOffset: 2,
      }}
    ><strong>&ldquo;{snip}&rdquo;</strong></button>
  );
}

/* ====================================================================== */
/* Main client component                                                   */
/* ====================================================================== */

export default function ReviewQueueClient() {
  const router = useRouter();
  const qc = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState<ItemKind>("hcc_candidate");
  const [editing, setEditing] = useState<{ id: string; icd10: string } | null>(null);
  const [sortBy, setSortBy] = useState<SortBy>("deadline");
  const [pendingAccept, setPendingAccept] = useState<ReviewItem | null>(null);

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

  const handleAcceptClick = (it: ReviewItem) => {
    if (needsAcceptGate(it.confidence, it.meat_status, it.clinical_rule_violation)) {
      setPendingAccept(it);
    } else {
      decideMut.mutate({ candidate_id: it.id, decision: "accept" });
    }
  };

  const handleAcceptConfirmed = (payload: AcceptOverridePayload) => {
    if (!pendingAccept) return;
    decideMut.mutate({
      candidate_id: pendingAccept.id,
      decision: "accept",
      override_reason: payload.override_reason,
      defense_basis: payload.defense_basis,
    });
    setPendingAccept(null);
  };

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
    <>
    <div style={{
      background: C.bgPage, minHeight: "100vh", padding: "32px 40px 48px",
      fontFamily: FONT_SYS, color: C.text,
    }} className="rci-page-pad-desktop">
      <style>{`
        @keyframes rq-shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
        @media (max-width: 640px) { .rci-page-pad-desktop { padding: 20px 16px 32px !important; } }
        button:focus-visible { outline: 2px solid ${tokens.primary}; outline-offset: 2px; border-radius: 4px; }
      `}</style>
      <DataQualityBanner />

      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 24 }}>
        <div style={{
          width: 48, height: 48, borderRadius: 14,
          background: `linear-gradient(135deg, ${C.brand} 0%, ${C.brandDark} 100%)`,
          display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: "0 6px 16px rgba(15, 118, 110, 0.25)",
        }}>
          <Sparkles size={22} color={tokens.white} strokeWidth={2.25} />
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
          display: "flex", alignItems: "center", justifyContent: "space-between",
          gap: 12, background: C.highSoft,
          border: `1px solid ${tokens.dangerBorder}`, borderRadius: 12, padding: "12px 16px",
          marginBottom: 16, fontSize: 13, color: C.high, fontWeight: 600,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <AlertCircle size={18} aria-hidden="true" />
            <div>
              <div>Failed to load review queue.</div>
              <div style={{ fontSize: 12, fontWeight: 400, marginTop: 2 }}>
                Coder decisions cannot be recorded while data is unavailable — this is a compliance risk.
              </div>
            </div>
          </div>
          <button
            onClick={() => window.location.reload()}
            aria-label="Retry loading review queue"
            style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              padding: "6px 12px", borderRadius: 6, fontSize: 12, fontWeight: 600,
              border: `1px solid ${tokens.dangerBorder}`, backgroundColor: tokens.white,
              color: C.high, cursor: "pointer", flexShrink: 0,
            }}
          >
            <RefreshCw size={13} /> Retry
          </button>
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
          <div aria-busy="true" aria-label="Loading review queue items">
            {Array.from({ length: 5 }).map((_, i) => (
              <div
                key={i}
                aria-hidden="true"
                style={{
                  display: "grid",
                  gridTemplateColumns: "minmax(200px,1.4fr) minmax(240px,2fr) 110px 140px 120px 200px",
                  gap: 14,
                  padding: "14px 22px",
                  borderBottom: `1px solid ${C.rowDivider}`,
                  alignItems: "center",
                }}
              >
                {[160, 220, 80, 110, 80, 160].map((w, j) => (
                  <div
                    key={j}
                    style={{
                      height: 14,
                      width: w,
                      borderRadius: 6,
                      background: `linear-gradient(90deg, ${tokens.slate100} 25%, ${tokens.slate200} 50%, ${tokens.slate100} 75%)`,
                      backgroundSize: "200% 100%",
                      animation: "rq-shimmer 1.4s infinite",
                      animationDelay: `${i * 0.08}s`,
                    }}
                  />
                ))}
              </div>
            ))}
          </div>
        )}

        {!isLoading && !isError && items.length === 0 && (
          <div style={{ padding: 56, textAlign: "center" }}>
            <FileSearch size={30} color={C.brand} aria-hidden="true" />
            <div style={{ marginTop: 10, fontWeight: 700 }}>Queue is empty</div>
            <div style={{ fontSize: 13, color: C.textSubtle }}>
              No open items in this category. All candidates have been reviewed.
            </div>
          </div>
        )}

        {!isLoading && items.map((it, idx) => {
          const initials = deriveInitials(it.patient_name, undefined, it.patient_id);
          const aColor = initialsColor(it.patient_name || String(it.patient_id));
          const c = it.confidence ?? 0;
          const isEditing = editing?.id === it.id;
          const createdAgo = it.created_at
            ? (() => {
                const diff = Date.now() - new Date(it.created_at).getTime();
                const mins = Math.floor(diff / 60000);
                if (mins < 1) return "just now";
                if (mins < 60) return `${mins}m ago`;
                const hrs = Math.floor(mins / 60);
                if (hrs < 24) return `${hrs}h ago`;
                return `${Math.floor(hrs / 24)}d ago`;
              })()
            : null;
          const daysLeft = it.days_to_cutoff;
          const hasRuleViolation =
            it.clinical_rule_violation === true ||
            (typeof it.clinical_rule_violation === "string" &&
              it.clinical_rule_violation.length > 0 &&
              it.clinical_rule_violation.toLowerCase() !== "false");
          const isTier1 = (daysLeft != null && daysLeft <= 7) || hasRuleViolation;
          const isTier2 =
            !isTier1 &&
            (
              (daysLeft != null && daysLeft >= 8 && daysLeft <= 21) ||
              (it.meat_count != null && it.meat_count <= 1)
            );
          const tierBg = isTier1 ? tokens.riskHighSoft : isTier2 ? tokens.riskMediumSoft : undefined;
          const tierBorder = isTier1 ? tokens.riskHigh : isTier2 ? tokens.riskMedium : null;
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
              borderLeft: tierBorder ? `3px solid ${tierBorder}` : "3px solid transparent",
              backgroundColor: tierBg,
            }}>
              {/* Patient + audit trail timestamp */}
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div style={{
                  width: 36, height: 36, borderRadius: 10, color: tokens.white,
                  background: `linear-gradient(135deg, ${aColor}, ${aColor}CC)`,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: 12, fontWeight: 700, flexShrink: 0,
                }} aria-hidden="true">{initials}</div>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 14, fontWeight: 600 }}>
                    {it.patient_name ?? `Patient ${it.patient_id}`}
                  </div>
                  <div style={{ fontSize: 11, color: C.label }}>PID {it.patient_id}</div>
                  {createdAgo && (
                    <div style={{ fontSize: 10, color: C.label, marginTop: 1 }}>
                      Added {createdAgo}
                    </div>
                  )}
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
                <div style={{ flex: 1, height: 6, borderRadius: 4, backgroundColor: tokens.slate100, overflow: "hidden" }}>
                  <div style={{ width: `${Math.max(4, c * 100)}%`, height: "100%", backgroundColor: confColor(c) }} />
                </div>
                <span style={{ fontSize: 12, fontWeight: 700, color: confColor(c), minWidth: 34, textAlign: "right" }}>
                  {Math.round(c * 100)}%
                </span>
              </div>

              {/* MEAT */}
              <div>{it.meat ? <MeatPills m={it.meat} /> : <span style={{ color: C.textSubtle }}>—</span>}</div>

              {/* Days to cutoff */}
              {hasCutoff && (
                it.days_to_cutoff != null && it.days_to_cutoff <= 7 ? (
                  <div style={{ display: "inline-flex", alignItems: "center", gap: 4, fontSize: 12, fontWeight: 600, color: tokens.riskHigh, fontFamily: FONT_MONO }}
                    aria-label={`Urgent: ${it.days_to_cutoff} days remaining`}>
                    <span aria-hidden="true">⚠</span>
                    <span>{it.days_to_cutoff} days</span>
                  </div>
                ) : (
                  <div style={{ fontSize: 12, fontWeight: 700, color: C.text, fontFamily: FONT_MONO }}>
                    {it.days_to_cutoff != null ? `${it.days_to_cutoff}d` : "—"}
                  </div>
                )
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
              <div style={{ justifySelf: "end", display: "flex", alignItems: "center", gap: 6 }}>
                <button
                  title="Accept HCC candidate"
                  aria-label={`Accept HCC candidate for ${it.patient_name ?? `Patient ${it.patient_id}`}`}
                  onClick={() => handleAcceptClick(it)}
                  disabled={decideMut.isPending}
                  style={{ width: 34, height: 34, borderRadius: 8, border: `1px solid ${C.low}`, background: "transparent", color: C.low, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}
                ><Check size={15} strokeWidth={2.5} /></button>
                <button
                  title="Reject HCC candidate"
                  aria-label={`Reject HCC candidate for ${it.patient_name ?? `Patient ${it.patient_id}`}`}
                  onClick={() => decideMut.mutate({ candidate_id: it.id, decision: "reject" })}
                  disabled={decideMut.isPending}
                  style={{ width: 34, height: 34, borderRadius: 8, border: `1px solid ${C.high}`, background: "transparent", color: C.high, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}
                ><X size={15} strokeWidth={2.5} /></button>
                <button
                  title="Edit ICD-10 code"
                  aria-label={`Edit ICD-10 code for ${it.patient_name ?? `Patient ${it.patient_id}`}`}
                  onClick={() => setEditing({ id: it.id, icd10: it.icd10 ?? "" })}
                  style={{ width: 34, height: 34, borderRadius: 8, border: `1px solid ${C.border}`, background: tokens.white, color: C.textMuted, cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}
                ><Pencil size={14} /></button>
                <ChevronRight size={14} color={tokens.slate300} aria-hidden="true" />
              </div>
            </div>
          );
        })}
      </div>
    </div>

    <AcceptConfirmDialog
      open={pendingAccept !== null}
      onClose={() => setPendingAccept(null)}
      onConfirm={handleAcceptConfirmed}
      suspect={pendingAccept ? {
        hcc_code: pendingAccept.hcc,
        icd10_code: pendingAccept.icd10,
        confidence: pendingAccept.confidence,
        meat_status: pendingAccept.meat_status,
        meat_count: pendingAccept.meat_count,
        clinical_rule_violation: pendingAccept.clinical_rule_violation,
        expected_dollar_impact: pendingAccept.expected_dollar_impact,
        patient_name: pendingAccept.patient_name,
      } : {}}
    />
    </>
  );
}
