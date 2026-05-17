"use client";

/**
 * Visual Cohort Builder
 * ---------------------
 * Drag filter chips from the left palette onto the centre canvas, configure
 * operator + value per clause, see a live preview (count + sample patients)
 * on the right, and save the cohort via the bottom action bar.
 *
 * HTML5 drag-and-drop only — no external deps.  Backend contract lives in
 * ``backend/app/routers/cohorts_v2.py``.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Filter, Save, Trash2, Users, Calendar, Activity, UserCircle, Stethoscope, Plus } from "lucide-react";
import api from "@/lib/api";
import { PageHeader } from "@/components/healthcare-ui";

// ---------------------------------------------------------------------------
// Domain types — keep aligned with cohorts_v2.py
// ---------------------------------------------------------------------------

type FieldName = "age" | "raf_score" | "has_hcc" | "sex";
type Operator = "AND" | "OR";
type ClauseOp = "gte" | "lte" | "eq";

interface Clause {
  // Local-only identity for stable React keys / drag re-ordering.
  uid: string;
  field: FieldName;
  op: ClauseOp;
  value: string;
}

interface FieldSpec {
  field: FieldName;
  label: string;
  icon: React.ComponentType<{ size?: number }>;
  allowedOps: ClauseOp[];
  defaultOp: ClauseOp;
  defaultValue: string;
  inputType: "number" | "text" | "select";
  selectOptions?: { value: string; label: string }[];
  hint: string;
}

const FIELDS: FieldSpec[] = [
  {
    field: "age",
    label: "Age",
    icon: Calendar,
    allowedOps: ["gte", "lte", "eq"],
    defaultOp: "gte",
    defaultValue: "65",
    inputType: "number",
    hint: "years",
  },
  {
    field: "raf_score",
    label: "RAF score",
    icon: Activity,
    allowedOps: ["gte", "lte", "eq"],
    defaultOp: "gte",
    defaultValue: "1.5",
    inputType: "number",
    hint: "final_raf",
  },
  {
    field: "has_hcc",
    label: "HCC",
    icon: Stethoscope,
    allowedOps: ["eq"],
    defaultOp: "eq",
    defaultValue: "18",
    inputType: "number",
    hint: "code",
  },
  {
    field: "sex",
    label: "Sex",
    icon: UserCircle,
    allowedOps: ["eq"],
    defaultOp: "eq",
    defaultValue: "F",
    inputType: "select",
    selectOptions: [
      { value: "F", label: "Female" },
      { value: "M", label: "Male" },
    ],
    hint: "",
  },
];

const OP_LABELS: Record<ClauseOp, string> = {
  gte: ">=",
  lte: "<=",
  eq: "=",
};

// ---------------------------------------------------------------------------
// Local helpers
// ---------------------------------------------------------------------------

function makeUid(): string {
  return Math.random().toString(36).slice(2, 10);
}

function specFor(field: FieldName): FieldSpec {
  const s = FIELDS.find((f) => f.field === field);
  if (!s) throw new Error(`unknown field ${field}`);
  return s;
}

function clauseFromSpec(spec: FieldSpec): Clause {
  return {
    uid: makeUid(),
    field: spec.field,
    op: spec.defaultOp,
    value: spec.defaultValue,
  };
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

interface PreviewResponse {
  matched_count: number;
  sample_patient_ids: number[];
  sample_patients: { id: number; first_name: string; last_name: string; mrn: string }[];
}

async function fetchPreview(definition: {
  operator: Operator;
  clauses: { field: FieldName; op: ClauseOp; value: string | number }[];
}): Promise<PreviewResponse> {
  const resp = await api.post<PreviewResponse>("/api/cohorts/v2/preview", { definition });
  return resp.data;
}

async function saveCohort(
  name: string,
  definition: {
    operator: Operator;
    clauses: { field: FieldName; op: ClauseOp; value: string | number }[];
  },
): Promise<{ id: number }> {
  const resp = await api.post<{ id: number }>("/api/cohorts/v2", { name, definition });
  return resp.data;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function CohortBuilderPage() {
  const [operator, setOperator] = useState<Operator>("AND");
  const [clauses, setClauses] = useState<Clause[]>([]);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);

  // ---- Compile clauses → API payload ---------------------------------------
  const definitionPayload = useMemo(() => {
    return {
      operator,
      clauses: clauses.map((c) => ({
        field: c.field,
        op: c.op,
        // Numeric fields → coerce; sex/string stays as-is.  Empty values are
        // filtered out before request so partial input doesn't 400 the API.
        value: c.value,
      })),
    };
  }, [operator, clauses]);

  // ---- Debounced preview ---------------------------------------------------
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    // Filter out clauses with empty value so we don't ping API with junk.
    const valid = definitionPayload.clauses.filter(
      (c) => c.value !== "" && c.value !== null && c.value !== undefined,
    );
    const payload = { operator: definitionPayload.operator, clauses: valid };
    debounceRef.current = setTimeout(() => {
      setPreviewLoading(true);
      setPreviewError(null);
      fetchPreview(payload)
        .then((r) => setPreview(r))
        .catch((err: unknown) => {
          // axios error → message; fall back to generic
          const msg =
            (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
            (err as Error)?.message ||
            "Preview failed";
          setPreviewError(String(msg));
        })
        .finally(() => setPreviewLoading(false));
    }, 350);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [definitionPayload]);

  // ---- Drag-and-drop handlers ---------------------------------------------
  const onPaletteDragStart = useCallback(
    (e: React.DragEvent<HTMLElement>, field: FieldName) => {
      e.dataTransfer.setData("application/x-cohort-field", field);
      e.dataTransfer.effectAllowed = "copy";
    },
    [],
  );

  const onCanvasDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  }, []);

  const onCanvasDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    const field = e.dataTransfer.getData("application/x-cohort-field") as FieldName;
    if (!field) return;
    const spec = FIELDS.find((f) => f.field === field);
    if (!spec) return;
    setClauses((prev) => [...prev, clauseFromSpec(spec)]);
  }, []);

  const addClauseByClick = useCallback((field: FieldName) => {
    const spec = specFor(field);
    setClauses((prev) => [...prev, clauseFromSpec(spec)]);
  }, []);

  const removeClause = useCallback((uid: string) => {
    setClauses((prev) => prev.filter((c) => c.uid !== uid));
  }, []);

  const updateClause = useCallback((uid: string, patch: Partial<Clause>) => {
    setClauses((prev) => prev.map((c) => (c.uid === uid ? { ...c, ...patch } : c)));
  }, []);

  // ---- Save flow -----------------------------------------------------------
  const handleSave = useCallback(async () => {
    const name = window.prompt("Name this cohort:");
    if (!name || !name.trim()) return;
    const valid = definitionPayload.clauses.filter(
      (c) => c.value !== "" && c.value !== null && c.value !== undefined,
    );
    setSaving(true);
    setSavedMessage(null);
    try {
      const res = await saveCohort(name.trim(), { operator: definitionPayload.operator, clauses: valid });
      setSavedMessage(`Saved cohort #${res.id}: ${name.trim()}`);
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        (err as Error)?.message ||
        "Save failed";
      setSavedMessage(`Error: ${String(msg)}`);
    } finally {
      setSaving(false);
    }
  }, [definitionPayload]);

  // ---- Render --------------------------------------------------------------
  return (
    <div style={{ padding: "1.5rem", maxWidth: 1400, margin: "0 auto" }}>
      <PageHeader
        title="Cohort Builder"
        subtitle="Drag filter chips onto the canvas to define a patient population"
        icon={<Filter size={22} />}
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "240px 1fr 320px",
          gap: "1rem",
          marginTop: "1.5rem",
          alignItems: "start",
        }}
      >
        {/* -------------- Left: palette -------------- */}
        <aside
          style={{
            background: "#f8fafc",
            border: "1px solid #e2e8f0",
            borderRadius: 8,
            padding: "1rem",
          }}
          aria-label="Filter palette"
        >
          <h3 style={{ margin: "0 0 0.75rem", fontSize: 14, fontWeight: 600, color: "#475569" }}>
            Filter fields
          </h3>
          <p style={{ margin: "0 0 0.75rem", fontSize: 12, color: "#64748b" }}>
            Drag a chip onto the canvas or click <strong>Add filter</strong> to add a clause.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {FIELDS.map((spec) => {
              const Icon = spec.icon;
              return (
                <button
                  key={spec.field}
                  type="button"
                  draggable
                  onDragStart={(e) => onPaletteDragStart(e, spec.field)}
                  onClick={() => addClauseByClick(spec.field)}
                  aria-label={`Add ${spec.label} filter clause`}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    background: "#fff",
                    border: "1px solid #cbd5e1",
                    borderRadius: 6,
                    padding: "0.5rem 0.75rem",
                    cursor: "grab",
                    fontSize: 14,
                    textAlign: "left",
                    width: "100%",
                  }}
                  data-testid={`palette-chip-${spec.field}`}
                >
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
                    <Icon size={16} aria-hidden="true" />
                    {spec.label}
                  </span>
                  <span
                    aria-hidden="true"
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 4,
                      fontSize: 11,
                      color: "#475569",
                    }}
                  >
                    <Plus size={13} />
                    Add filter
                  </span>
                </button>
              );
            })}
          </div>
        </aside>

        {/* -------------- Center: canvas -------------- */}
        <section
          style={{
            background: "#ffffff",
            border: "1px solid #e2e8f0",
            borderRadius: 8,
            padding: "1rem",
            minHeight: 360,
            display: "flex",
            flexDirection: "column",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: "0.75rem",
            }}
          >
            <h3 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: "#475569" }}>
              Clauses ({clauses.length})
            </h3>
            <div role="group" aria-label="Combine clauses with" style={{ display: "inline-flex", gap: 4 }}>
              {(["AND", "OR"] as Operator[]).map((op) => {
                const active = operator === op;
                return (
                  <button
                    key={op}
                    type="button"
                    onClick={() => setOperator(op)}
                    aria-pressed={active}
                    style={{
                      padding: "0.25rem 0.75rem",
                      borderRadius: 6,
                      border: "1px solid",
                      borderColor: active ? "#2563eb" : "#cbd5e1",
                      background: active ? "#2563eb" : "#fff",
                      color: active ? "#fff" : "#475569",
                      fontWeight: 600,
                      cursor: "pointer",
                      fontSize: 12,
                    }}
                  >
                    {op}
                  </button>
                );
              })}
            </div>
          </div>

          <div
            onDragOver={onCanvasDragOver}
            onDrop={onCanvasDrop}
            data-testid="cohort-canvas-dropzone"
            style={{
              flex: 1,
              border: "2px dashed #cbd5e1",
              borderRadius: 6,
              padding: "1rem",
              display: "flex",
              flexDirection: "column",
              gap: 8,
              minHeight: 280,
            }}
          >
            {clauses.length === 0 ? (
              <div
                style={{
                  flex: 1,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "#94a3b8",
                  fontSize: 14,
                  textAlign: "center",
                }}
              >
                Drag a filter chip here, or click + on a chip in the palette.
              </div>
            ) : (
              clauses.map((c, idx) => {
                const spec = specFor(c.field);
                const Icon = spec.icon;
                return (
                  <div key={c.uid}>
                    {idx > 0 && (
                      <div
                        style={{
                          textAlign: "center",
                          fontSize: 11,
                          color: "#64748b",
                          margin: "4px 0",
                          fontWeight: 700,
                        }}
                      >
                        {operator}
                      </div>
                    )}
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        background: "#f1f5f9",
                        border: "1px solid #cbd5e1",
                        borderRadius: 6,
                        padding: "0.5rem 0.75rem",
                      }}
                      data-testid={`clause-${idx}`}
                    >
                      <Icon size={14} />
                      <span style={{ fontWeight: 600, fontSize: 13, color: "#0f172a" }}>{spec.label}</span>
                      <select
                        aria-label={`Operator for ${spec.label}`}
                        value={c.op}
                        onChange={(e) => updateClause(c.uid, { op: e.target.value as ClauseOp })}
                        style={{
                          padding: "0.25rem 0.5rem",
                          borderRadius: 4,
                          border: "1px solid #cbd5e1",
                          fontSize: 13,
                          background: "#fff",
                        }}
                      >
                        {spec.allowedOps.map((op) => (
                          <option key={op} value={op}>
                            {OP_LABELS[op]}
                          </option>
                        ))}
                      </select>
                      {spec.inputType === "select" ? (
                        <select
                          aria-label={`Value for ${spec.label}`}
                          value={c.value}
                          onChange={(e) => updateClause(c.uid, { value: e.target.value })}
                          style={{
                            padding: "0.25rem 0.5rem",
                            borderRadius: 4,
                            border: "1px solid #cbd5e1",
                            fontSize: 13,
                            background: "#fff",
                          }}
                        >
                          {spec.selectOptions?.map((o) => (
                            <option key={o.value} value={o.value}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          type={spec.inputType === "number" ? "number" : "text"}
                          aria-label={`Value for ${spec.label}`}
                          value={c.value}
                          onChange={(e) => updateClause(c.uid, { value: e.target.value })}
                          step={spec.field === "raf_score" ? "0.1" : "1"}
                          style={{
                            padding: "0.25rem 0.5rem",
                            borderRadius: 4,
                            border: "1px solid #cbd5e1",
                            fontSize: 13,
                            width: 90,
                          }}
                        />
                      )}
                      {spec.hint && (
                        <span style={{ fontSize: 11, color: "#94a3b8" }}>{spec.hint}</span>
                      )}
                      <button
                        type="button"
                        onClick={() => removeClause(c.uid)}
                        aria-label={`Remove ${spec.label} clause`}
                        style={{
                          marginLeft: "auto",
                          background: "transparent",
                          border: "none",
                          cursor: "pointer",
                          color: "#dc2626",
                          padding: 4,
                        }}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>

          {/* Save action bar */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginTop: "1rem",
              paddingTop: "0.75rem",
              borderTop: "1px solid #e2e8f0",
            }}
          >
            <div style={{ fontSize: 12, color: "#64748b" }}>
              {savedMessage}
            </div>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || clauses.length === 0}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "0.5rem 1rem",
                borderRadius: 6,
                border: "none",
                background: saving || clauses.length === 0 ? "#94a3b8" : "#2563eb",
                color: "#fff",
                fontWeight: 600,
                cursor: saving || clauses.length === 0 ? "not-allowed" : "pointer",
              }}
            >
              <Save size={14} />
              {saving ? "Saving..." : "Save cohort"}
            </button>
          </div>
        </section>

        {/* -------------- Right: live preview -------------- */}
        <aside
          style={{
            background: "#f8fafc",
            border: "1px solid #e2e8f0",
            borderRadius: 8,
            padding: "1rem",
            position: "sticky",
            top: "1rem",
          }}
          aria-label="Cohort preview"
        >
          <h3
            style={{
              margin: "0 0 0.75rem",
              fontSize: 14,
              fontWeight: 600,
              color: "#475569",
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <Users size={16} /> Live preview
          </h3>
          <div
            style={{
              background: "#fff",
              border: "1px solid #e2e8f0",
              borderRadius: 6,
              padding: "0.75rem",
              marginBottom: "0.75rem",
              textAlign: "center",
            }}
          >
            <div style={{ fontSize: 11, color: "#64748b", textTransform: "uppercase", letterSpacing: 0.5 }}>
              Patients matching
            </div>
            <div style={{ fontSize: 28, fontWeight: 700, color: "#0f172a", marginTop: 4 }}>
              {previewLoading ? "…" : preview?.matched_count?.toLocaleString() ?? "—"}
            </div>
          </div>
          {previewError && (
            <div
              style={{
                background: "#fee2e2",
                color: "#991b1b",
                fontSize: 12,
                padding: "0.5rem",
                borderRadius: 4,
                marginBottom: "0.75rem",
              }}
              role="alert"
            >
              {previewError}
            </div>
          )}
          <div>
            <div style={{ fontSize: 12, color: "#64748b", marginBottom: 4 }}>
              Sample (first 20)
            </div>
            <ul
              style={{
                listStyle: "none",
                padding: 0,
                margin: 0,
                maxHeight: 320,
                overflowY: "auto",
                fontSize: 13,
              }}
              data-testid="cohort-preview-samples"
            >
              {(preview?.sample_patients ?? []).map((p) => (
                <li
                  key={p.id}
                  style={{
                    padding: "0.35rem 0.5rem",
                    borderBottom: "1px solid #e2e8f0",
                    display: "flex",
                    justifyContent: "space-between",
                    gap: 8,
                  }}
                >
                  <span>
                    {p.first_name} {p.last_name}
                  </span>
                  <span style={{ color: "#94a3b8", fontSize: 11 }}>
                    {p.mrn || `id ${p.id}`}
                  </span>
                </li>
              ))}
              {!previewLoading && (preview?.sample_patients?.length ?? 0) === 0 && (
                <li style={{ color: "#94a3b8", padding: "0.5rem", fontStyle: "italic" }}>
                  No patients match yet.
                </li>
              )}
            </ul>
          </div>
        </aside>
      </div>
    </div>
  );
}
