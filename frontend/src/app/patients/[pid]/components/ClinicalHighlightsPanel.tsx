"use client";

/**
 * ClinicalHighlightsPanel
 * -----------------------
 * Surfaces AI-extracted insights from the most recent analyzed encounter:
 *   - NLP summary sentence
 *   - Top diagnoses with confidence chips
 *   - Avg confidence score + source badge
 *
 * Uses GET /api/analysis/patient/{pid}/highlights (stubs to suspect fallback
 * when no encounter has been analyzed yet).
 */

import { useQuery } from "@tanstack/react-query";
import { Sparkles, Brain, BookOpen } from "lucide-react";
import api from "@/lib/api";
import { C } from "./shared";

interface HighlightDx {
  icd10_code: string;
  description: string;
  hcc_code?: string | null;
  confidence: number;
}

interface ClinicalHighlightsResponse {
  patient_id: number;
  encounter_id?: number | null;
  encounter_date?: string | null;
  top_diagnoses: HighlightDx[];
  nlp_summary: string;
  confidence: number;
  source: "cached" | "fallback";
}

function ConfidencePill({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 85 ? "#059669" : pct >= 65 ? "#D97706" : "#94A3B8";
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "1px 7px",
        borderRadius: 999,
        fontSize: 10,
        fontWeight: 700,
        fontVariantNumeric: "tabular-nums",
        background: `${color}18`,
        color,
        border: `1px solid ${color}40`,
      }}
    >
      {pct}%
    </span>
  );
}

export function ClinicalHighlightsPanel({ pid }: { pid: string }) {
  const { data, isLoading, isError } = useQuery<ClinicalHighlightsResponse>({
    queryKey: ["clinical-highlights", pid],
    queryFn: async () => {
      const { data } = await api.get<ClinicalHighlightsResponse>(
        `/api/analysis/patient/${pid}/highlights`
      );
      return data;
    },
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });

  if (isLoading) {
    return (
      <div
        style={{
          borderRadius: 10,
          border: `1px solid ${C.slate200}`,
          padding: "16px 20px",
          background: "#F8FAFC",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 12 }}>
          <Sparkles size={15} style={{ color: "#0284C7" }} />
          <span style={{ fontSize: 12, fontWeight: 700, color: "#0284C7", textTransform: "uppercase", letterSpacing: "0.07em" }}>
            Clinical Highlights
          </span>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {[80, 60, 70].map((w, i) => (
            <div
              key={i}
              style={{
                height: 12,
                borderRadius: 6,
                background: "#E2E8F0",
                width: `${w}%`,
                animation: "pulse 1.5s ease-in-out infinite",
              }}
            />
          ))}
        </div>
      </div>
    );
  }

  if (isError || !data) return null;

  const isFallback = data.source === "fallback";

  return (
    <div
      style={{
        borderRadius: 10,
        border: `1px solid ${isFallback ? C.slate200 : "#BAE6FD"}`,
        background: isFallback ? "#F8FAFC" : "linear-gradient(135deg, #F0F9FF, #ECFDF5)",
        overflow: "hidden",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "12px 16px",
          borderBottom: `1px solid ${isFallback ? C.slate100 : "#BAE6FD"}`,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <Brain size={15} style={{ color: "#0284C7" }} />
          <span
            style={{
              fontSize: 12,
              fontWeight: 700,
              color: "#0369A1",
              textTransform: "uppercase",
              letterSpacing: "0.07em",
            }}
          >
            Clinical Highlights
          </span>
          {!isFallback && data.encounter_date && (
            <span
              style={{
                fontSize: 10,
                color: "#64748B",
                background: "#E0F2FE",
                borderRadius: 999,
                padding: "1px 7px",
                fontWeight: 500,
              }}
            >
              Enc {data.encounter_date}
            </span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {data.confidence > 0 && <ConfidencePill value={data.confidence} />}
          {isFallback && (
            <span
              style={{
                fontSize: 9,
                color: "#94A3B8",
                background: "#F1F5F9",
                borderRadius: 4,
                padding: "2px 6px",
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
              }}
            >
              Suspect Data
            </span>
          )}
          {!isFallback && (
            <span
              style={{
                fontSize: 9,
                color: "#0284C7",
                background: "#E0F2FE",
                borderRadius: 4,
                padding: "2px 6px",
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
                display: "inline-flex",
                alignItems: "center",
                gap: 3,
              }}
            >
              <Sparkles size={8} />
              NLP
            </span>
          )}
        </div>
      </div>

      {/* Body */}
      <div style={{ padding: "12px 16px", display: "flex", flexDirection: "column", gap: 12 }}>
        {/* NLP Summary */}
        <div
          style={{
            fontSize: 13,
            lineHeight: 1.6,
            color: "#334155",
            padding: "8px 12px",
            borderRadius: 8,
            background: "#FFFFFF",
            border: `1px solid ${isFallback ? C.slate100 : "#E0F2FE"}`,
          }}
        >
          {data.nlp_summary}
        </div>

        {/* Top diagnoses */}
        {data.top_diagnoses.length > 0 && (
          <div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 5,
                marginBottom: 6,
              }}
            >
              <BookOpen size={11} style={{ color: "#64748B" }} />
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 600,
                  color: "#64748B",
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                }}
              >
                Top Extracted Diagnoses
              </span>
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {data.top_diagnoses.map((dx, i) => (
                <div
                  key={dx.icd10_code || i}
                  style={{
                    display: "inline-flex",
                    alignItems: "center",
                    gap: 5,
                    padding: "4px 10px",
                    borderRadius: 6,
                    background: "#FFFFFF",
                    border: `1px solid ${C.slate200}`,
                    fontSize: 11,
                  }}
                >
                  <span
                    style={{
                      fontFamily: "monospace",
                      fontWeight: 700,
                      color: "#0369A1",
                      fontSize: 11,
                    }}
                  >
                    {dx.icd10_code}
                  </span>
                  {dx.description && (
                    <span style={{ color: "#475569", maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {dx.description}
                    </span>
                  )}
                  {dx.hcc_code && (
                    <span
                      style={{
                        fontSize: 9,
                        fontWeight: 700,
                        padding: "1px 5px",
                        borderRadius: 4,
                        background: "#EFF6FF",
                        color: "#1D4ED8",
                        border: "1px solid #BFDBFE",
                      }}
                    >
                      {dx.hcc_code}
                    </span>
                  )}
                  {dx.confidence > 0 && <ConfidencePill value={dx.confidence} />}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
