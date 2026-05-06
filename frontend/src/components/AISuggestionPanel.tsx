"use client";

/**
 * AISuggestionPanel — Apixio HCC Complete / Reveleer EVE-style assistant.
 *
 * Renders a per-gap "Scan for evidence" button and a list of Gemini-extracted
 * verbatim quote suggestions. Each suggestion can be Accepted (promoting the
 * evidence to the recapture_gap row) or Rejected.
 */

import { useState } from "react";
import {
  AISuggestion,
  acceptAiSuggestion,
  aiSuggestRecapture,
  listAiSuggestions,
  rejectAiSuggestion,
} from "@/lib/api";

type Props = {
  gapId: number;
  onAccepted?: (suggestion: AISuggestion) => void;
};

const MEAT_LABEL: Record<string, string> = {
  M: "Monitor",
  E: "Evaluate",
  A: "Assess",
  T: "Treat",
};

function confidenceColor(conf: number): { bg: string; fg: string; label: string } {
  if (conf >= 0.75) return { bg: "#d1fae5", fg: "#065f46", label: "High" };
  if (conf >= 0.5) return { bg: "#fef3c7", fg: "#92400e", label: "Medium" };
  return { bg: "#fee2e2", fg: "#991b1b", label: "Low" };
}

export function AISuggestionPanel({ gapId, onAccepted }: Props) {
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [suggestions, setSuggestions] = useState<AISuggestion[]>([]);
  const [scanned, setScanned] = useState<number | null>(null);
  const [model, setModel] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);

  async function handleScan() {
    setLoading(true);
    setError(null);
    try {
      const res = await aiSuggestRecapture(gapId);
      setSuggestions(res.suggestions);
      setScanned(res.scanned_note_count);
      setModel(res.llm_model_used);
      if (res.error) setError(res.error);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Scan failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }

  async function handleRefresh() {
    setRefreshing(true);
    setError(null);
    try {
      const res = await listAiSuggestions(gapId);
      setSuggestions(res);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Refresh failed";
      setError(msg);
    } finally {
      setRefreshing(false);
    }
  }

  async function handleAccept(s: AISuggestion) {
    setBusyId(s.id);
    try {
      await acceptAiSuggestion(s.id);
      setSuggestions((prev) => prev.filter((x) => x.id !== s.id));
      onAccepted?.(s);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Accept failed";
      setError(msg);
    } finally {
      setBusyId(null);
    }
  }

  async function handleReject(s: AISuggestion) {
    setBusyId(s.id);
    try {
      await rejectAiSuggestion(s.id);
      setSuggestions((prev) => prev.filter((x) => x.id !== s.id));
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Reject failed";
      setError(msg);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div
      style={{
        padding: 16,
        background: "#f9fafb",
        border: "1px solid #e5e7eb",
        borderRadius: 8,
      }}
    >
      <div
        style={{
          display: "flex",
          gap: 8,
          alignItems: "center",
          marginBottom: 12,
          flexWrap: "wrap",
        }}
      >
        <button
          onClick={handleScan}
          disabled={loading}
          style={{
            background: loading ? "#9ca3af" : "#4f46e5",
            color: "white",
            border: "none",
            padding: "8px 14px",
            borderRadius: 6,
            cursor: loading ? "wait" : "pointer",
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          {loading ? "Scanning notes…" : "Scan for evidence"}
        </button>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          style={{
            background: "transparent",
            color: "#4f46e5",
            border: "1px solid #4f46e5",
            padding: "7px 12px",
            borderRadius: 6,
            cursor: refreshing ? "wait" : "pointer",
            fontSize: 12,
            fontWeight: 600,
          }}
        >
          {refreshing ? "Loading…" : "Show pending"}
        </button>
        {scanned !== null && (
          <span style={{ fontSize: 12, color: "#6b7280" }}>
            {scanned} note{scanned === 1 ? "" : "s"} scanned
            {model ? ` · ${model}` : ""}
          </span>
        )}
      </div>

      {error && (
        <div
          style={{
            background: "#fef2f2",
            border: "1px solid #fecaca",
            color: "#991b1b",
            padding: "8px 12px",
            borderRadius: 6,
            fontSize: 12,
            marginBottom: 12,
          }}
        >
          {error}
        </div>
      )}

      {!loading && suggestions.length === 0 && scanned !== null && (
        <p style={{ fontSize: 13, color: "#6b7280", margin: 0 }}>
          No verbatim evidence found in the past 12 months of notes.
        </p>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {suggestions.map((s) => {
          const conf = confidenceColor(s.confidence);
          return (
            <div
              key={s.id}
              style={{
                background: "white",
                border: "1px solid #e5e7eb",
                borderRadius: 8,
                padding: 12,
                display: "flex",
                gap: 12,
                alignItems: "flex-start",
              }}
            >
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                    flexWrap: "wrap",
                    marginBottom: 6,
                  }}
                >
                  <span
                    title={`Confidence: ${(s.confidence * 100).toFixed(0)}%`}
                    style={{
                      background: conf.bg,
                      color: conf.fg,
                      padding: "2px 8px",
                      borderRadius: 999,
                      fontSize: 11,
                      fontWeight: 700,
                    }}
                  >
                    {conf.label} · {(s.confidence * 100).toFixed(0)}%
                  </span>
                  {s.meat_element && (
                    <span
                      title={MEAT_LABEL[s.meat_element]}
                      style={{
                        background: "#eef2ff",
                        color: "#3730a3",
                        padding: "2px 8px",
                        borderRadius: 999,
                        fontSize: 11,
                        fontWeight: 700,
                      }}
                    >
                      {s.meat_element} — {MEAT_LABEL[s.meat_element]}
                    </span>
                  )}
                  {s.encounter_date && (
                    <span style={{ fontSize: 11, color: "#6b7280" }}>
                      {s.encounter_date}
                    </span>
                  )}
                  {s.source_note_id && (
                    <span
                      style={{
                        fontFamily: "monospace",
                        fontSize: 11,
                        color: "#6b7280",
                      }}
                    >
                      {s.source_note_id}
                    </span>
                  )}
                </div>
                <p
                  style={{
                    margin: 0,
                    fontStyle: "italic",
                    color: "#111827",
                    fontSize: 13,
                    lineHeight: 1.5,
                  }}
                >
                  &ldquo;{s.evidence_phrase}&rdquo;
                </p>
              </div>
              <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                <button
                  onClick={() => handleAccept(s)}
                  disabled={busyId === s.id}
                  style={{
                    background: "#10b981",
                    color: "white",
                    border: "none",
                    padding: "6px 10px",
                    borderRadius: 5,
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: busyId === s.id ? "wait" : "pointer",
                  }}
                >
                  Accept
                </button>
                <button
                  onClick={() => handleReject(s)}
                  disabled={busyId === s.id}
                  style={{
                    background: "white",
                    color: "#991b1b",
                    border: "1px solid #fecaca",
                    padding: "6px 10px",
                    borderRadius: 5,
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: busyId === s.id ? "wait" : "pointer",
                  }}
                >
                  Reject
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default AISuggestionPanel;
