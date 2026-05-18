"use client";

/**
 * SuspectDrawer — inline expanded-row detail panel.
 * Extracted from suspects/page.tsx to defer ~30 kB of evidence detail JSX
 * until the user clicks a suspect row to expand it.
 */

import { C, FONT_MONO } from "@/lib/ui-utils";
import { tokens } from "@/styles/tokens";
import type { DBSuspect } from "@/types";
import FeatureFlag from "@/components/FeatureFlag";
import { HccChipWithPopover } from "@/components/kg/HccExplainCard";
import { Check, X, FileSearch, ChevronRight, Sparkles, BookOpen, AlertCircle } from "lucide-react";

// ── AI Evidence helpers ──

/**
 * Extract NLP-derived insight fields from evidence_detail JSON.
 * Gracefully handles string/object/null shapes written by different pipeline engines.
 */
function parseAIEvidence(evidenceDetail: unknown): {
  sourceExcerpt: string | null;
  highlightTerm: string | null;
  whyItMatters: string | null;
  codingGuidance: string | null;
} {
  const empty = { sourceExcerpt: null, highlightTerm: null, whyItMatters: null, codingGuidance: null };
  if (!evidenceDetail) return empty;
  let obj: Record<string, unknown>;
  try {
    obj = typeof evidenceDetail === "string" && evidenceDetail.trim().startsWith("{")
      ? JSON.parse(evidenceDetail)
      : typeof evidenceDetail === "object" && evidenceDetail !== null
        ? (evidenceDetail as Record<string, unknown>)
        : null;
    if (!obj) return empty;
  } catch {
    return empty;
  }
  const sourceExcerpt =
    (obj.source_excerpt as string) ||
    (obj.nlp_excerpt as string) ||
    (obj.excerpt as string) ||
    (obj.note_snippet as string) ||
    null;
  const highlightTerm =
    (obj.highlight_term as string) ||
    (obj.term as string) ||
    (obj.entity as string) ||
    null;
  const whyItMatters =
    (obj.why_it_matters as string) ||
    (obj.clinical_reasoning as string) ||
    (obj.clinical_rationale as string) ||
    (obj.rationale as string) ||
    (obj.summary as string) ||
    null;
  const codingGuidance =
    (obj.coding_guidance as string) ||
    (obj.icd10_note as string) ||
    (obj.coding_note as string) ||
    null;
  return { sourceExcerpt, highlightTerm, whyItMatters, codingGuidance };
}

function HighlightedExcerpt({ text, term }: { text: string; term: string | null }) {
  if (!term) {
    return <span style={{ fontStyle: "italic", color: C.text }}>&ldquo;{text}&rdquo;</span>;
  }
  const idx = text.toLowerCase().indexOf(term.toLowerCase());
  if (idx === -1) {
    return <span style={{ fontStyle: "italic", color: C.text }}>&ldquo;{text}&rdquo;</span>;
  }
  return (
    <span style={{ fontStyle: "italic", color: C.text }}>
      &ldquo;{text.slice(0, idx)}
      <mark style={{ background: "#FEF08A", color: "#713F12", borderRadius: 3, padding: "0 2px" }}>
        {text.slice(idx, idx + term.length)}
      </mark>
      {text.slice(idx + term.length)}&rdquo;
    </span>
  );
}

// ── helpers (mirror of page.tsx so this chunk is self-contained) ──

function confColor(score: number): string {
  if (score >= 0.85) return C.low;
  if (score >= 0.65) return C.medium;
  return C.textSubtle;
}

function confAccent(score: number): string {
  if (score >= 0.85) return C.low;
  if (score >= 0.65) return C.medium;
  return tokens.slate300;
}

function formatCurrency(n: number): string {
  if (!isFinite(n)) return "$0";
  return `$${Math.round(n).toLocaleString()}`;
}

function fmtDate(d?: string): string {
  if (!d) return "—";
  try {
    return new Date(d).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return d;
  }
}

// ── types ──

export interface SuspectDrawerProps {
  suspect: DBSuspect;
  conf: number;
  coef: number;
  revenue: number;
  rationale: string;
  conditionLabel: string;
  onOpenChart: () => void;
  onAccept: () => void;
  onDismiss: () => void;
  acceptPending: boolean;
  dismissPending: boolean;
}

// ── component ──

export default function SuspectDrawer({
  suspect,
  conf,
  coef,
  revenue,
  rationale,
  conditionLabel,
  onOpenChart,
  onAccept,
  onDismiss,
  acceptPending,
  dismissPending,
}: SuspectDrawerProps) {
  const s = suspect;
  const isOpen = (s.status || "open") === "open";
  const cConf = confColor(conf);

  // Parse evidence_detail if it's a JSON string
  const evidenceLines: { label: string; value: string }[] = [];
  const detail = s.evidence_detail;
  try {
    const obj =
      typeof detail === "string" && detail.trim().startsWith("{")
        ? JSON.parse(detail)
        : detail && typeof detail === "object"
          ? detail
          : null;
    if (obj && typeof obj === "object") {
      for (const [k, v] of Object.entries(obj)) {
        if (v == null || v === "") continue;
        const label = k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
        const value = typeof v === "object" ? JSON.stringify(v) : String(v);
        evidenceLines.push({ label, value });
      }
    }
  } catch {
    // ignore malformed JSON
  }

  const aiEvidence = parseAIEvidence(s.evidence_detail);
  const hasAIEvidence = !!(aiEvidence.sourceExcerpt || aiEvidence.whyItMatters || aiEvidence.codingGuidance);

  return (
    <div
      onClick={(e) => e.stopPropagation()}
      style={{
        padding: "18px 22px 22px 22px",
        backgroundColor: tokens.bgFaintCard,
        borderTop: `1px solid ${C.borderSoft}`,
        borderLeft: `3px solid ${confAccent(conf)}`,
        display: "grid",
        gridTemplateColumns: "minmax(0, 1.4fr) minmax(0, 1fr)",
        gap: 24,
        animation: "drawerFadeIn 0.22s ease",
      }}
    >
      <style>{`
        @keyframes drawerFadeIn {
          from { opacity: 0; transform: translateY(-4px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>

      {/* LEFT — Clinical evidence */}
      <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 16 }}>
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, color: C.label, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>
            Why we flagged this
          </div>
          <div style={{ fontSize: 14, lineHeight: 1.55, color: C.text, fontStyle: "italic", padding: "12px 14px", borderRadius: 10, backgroundColor: "hsl(var(--card))", border: `1px solid ${C.borderSoft}` }}>
            &ldquo;{rationale}&rdquo;
          </div>
        </div>

        {evidenceLines.length > 0 && (
          <div>
            <div style={{ fontSize: 10, fontWeight: 700, color: C.label, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>
              Supporting evidence
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 8, padding: 12, borderRadius: 10, backgroundColor: "hsl(var(--card))", border: `1px solid ${C.borderSoft}` }}>
              {evidenceLines.map((ln, i) => (
                <div key={i} style={{ minWidth: 0 }}>
                  <div style={{ fontSize: 10, color: C.label, textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 600, marginBottom: 2 }}>
                    {ln.label}
                  </div>
                  <div style={{ fontSize: 12, color: C.text, fontFamily: FONT_MONO, wordBreak: "break-word" }}>
                    {ln.value}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* AI Evidence section */}
        {hasAIEvidence && (
          <div style={{ padding: "12px 14px", borderRadius: 10, backgroundColor: "#F0F9FF", border: "1px solid #BAE6FD" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10 }}>
              <Sparkles size={13} style={{ color: "#0284C7" }} />
              <span style={{ fontSize: 10, fontWeight: 700, color: "#0284C7", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                AI Evidence
              </span>
            </div>

            {aiEvidence.sourceExcerpt && (
              <div style={{ marginBottom: 8 }}>
                <div style={{ fontSize: 10, fontWeight: 600, color: C.label, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
                  Source Excerpt
                </div>
                <div style={{ fontSize: 12, lineHeight: 1.6, padding: "8px 10px", borderRadius: 6, background: "#FFFFFF", border: "1px solid #E0F2FE" }}>
                  <HighlightedExcerpt text={aiEvidence.sourceExcerpt} term={aiEvidence.highlightTerm} />
                </div>
              </div>
            )}

            {aiEvidence.whyItMatters && (
              <div style={{ marginBottom: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 3 }}>
                  <AlertCircle size={11} style={{ color: "#0369A1" }} />
                  <span style={{ fontSize: 10, fontWeight: 600, color: C.label, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    Why this matters
                  </span>
                </div>
                <div style={{ fontSize: 12, color: C.text, lineHeight: 1.55 }}>
                  {aiEvidence.whyItMatters}
                </div>
              </div>
            )}

            {aiEvidence.codingGuidance && (
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 3 }}>
                  <BookOpen size={11} style={{ color: "#0369A1" }} />
                  <span style={{ fontSize: 10, fontWeight: 600, color: C.label, textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    Coding guidance
                  </span>
                </div>
                <div style={{ fontSize: 12, color: C.text, lineHeight: 1.55, fontFamily: FONT_MONO }}>
                  {aiEvidence.codingGuidance}
                </div>
              </div>
            )}
          </div>
        )}

        <div style={{ display: "flex", gap: 16, fontSize: 11, color: C.textSubtle }}>
          <span><span style={{ color: C.label }}>Detected </span>{fmtDate(s.created_at)}</span>
          {s.reviewed_at && (
            <span>
              <span style={{ color: C.label }}>Reviewed </span>
              {fmtDate(s.reviewed_at)}
              {s.reviewed_by && <span style={{ color: C.label }}> · {s.reviewed_by}</span>}
            </span>
          )}
        </div>
      </div>

      {/* RIGHT — Code card + actions */}
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ padding: 16, borderRadius: 10, backgroundColor: "hsl(var(--card))", border: `1px solid ${C.border}` }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: C.label, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>
            Suspected Code
          </div>
          <div style={{ fontSize: 15, fontWeight: 700, color: C.text, marginBottom: 6, letterSpacing: "-0.01em" }}>
            {conditionLabel}
          </div>
          <div style={{ display: "flex", gap: 8, fontFamily: FONT_MONO, fontSize: 11, color: C.textMuted, marginBottom: 12 }}>
            {s.suspect_hcc != null && (
              <FeatureFlag
                flagKey="kg_evidence_panel"
                fallback={<span style={{ padding: "2px 8px", borderRadius: 6, backgroundColor: C.brandSoft, color: C.brand, fontWeight: 700 }}>HCC {s.suspect_hcc}</span>}
              >
                <HccChipWithPopover hccCode={String(s.suspect_hcc)}>
                  <span style={{ padding: "2px 8px", borderRadius: 6, backgroundColor: C.brandSoft, color: C.brand, fontWeight: 700 }}>HCC {s.suspect_hcc}</span>
                </HccChipWithPopover>
              </FeatureFlag>
            )}
            {s.suspect_icd10 && (
              <span style={{ padding: "2px 8px", borderRadius: 6, backgroundColor: C.bgSubtle, border: `1px solid ${C.borderSoft}`, fontWeight: 700 }}>
                ICD {s.suspect_icd10}
              </span>
            )}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, paddingTop: 12, borderTop: `1px solid ${C.borderSoft}` }}>
            <div>
              <div style={{ fontSize: 9, color: C.label, textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 700 }}>Confidence</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: cConf, fontVariantNumeric: "tabular-nums" }}>{(conf * 100).toFixed(0)}%</div>
            </div>
            <div>
              <div style={{ fontSize: 9, color: C.label, textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 700 }}>RAF Lift</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: C.brand, fontVariantNumeric: "tabular-nums" }}>+{coef.toFixed(3)}</div>
            </div>
            <div>
              <div style={{ fontSize: 9, color: C.label, textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 700 }}>Revenue</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: C.text, fontVariantNumeric: "tabular-nums" }}>{formatCurrency(revenue)}</div>
            </div>
          </div>
        </div>

        {isOpen && (
          <div style={{ display: "flex", gap: 8 }}>
            <button
              onClick={onAccept}
              disabled={acceptPending}
              style={{ flex: 1, height: 40, borderRadius: 10, border: "none", backgroundColor: C.low, color: tokens.white, fontSize: 13, fontWeight: 700, cursor: acceptPending ? "default" : "pointer", opacity: acceptPending ? 0.6 : 1, display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6, letterSpacing: "0.01em" }}
            >
              <Check size={15} strokeWidth={2.5} /> Push to EMR
            </button>
            <button
              onClick={onDismiss}
              disabled={dismissPending}
              style={{ flex: 1, height: 40, borderRadius: 10, border: `1px solid ${C.high}`, backgroundColor: tokens.white, color: C.high, fontSize: 13, fontWeight: 700, cursor: dismissPending ? "default" : "pointer", opacity: dismissPending ? 0.6 : 1, display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6, letterSpacing: "0.01em" }}
            >
              <X size={15} strokeWidth={2.5} /> Dismiss
            </button>
          </div>
        )}

        <button
          onClick={onOpenChart}
          style={{ height: 40, borderRadius: 10, border: `1px solid ${C.brand}`, backgroundColor: C.brandSoft, color: C.brand, fontSize: 13, fontWeight: 700, cursor: "pointer", display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 8, letterSpacing: "0.01em" }}
        >
          <FileSearch size={15} strokeWidth={2.2} /> Open Patient Chart <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );
}
