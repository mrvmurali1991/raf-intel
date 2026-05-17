"use client";

/**
 * OutreachTemplateManager — list templates + create-template dialog.
 *
 * Includes a "Seed defaults" button that calls
 * POST /api/recapture/outreach/templates/seed-defaults to insert the canonical
 * SMS / portal / phone templates if they don't already exist.
 */

import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Sparkles, X } from "lucide-react";

import { EmptyState } from "@/components/healthcare-ui";
import {
  createOutreachTemplate,
  getOutreachTemplates,
  seedOutreachDefaults,
  type OutreachChannel,
  type OutreachTemplate,
} from "@/lib/api";

const CHANNELS: { value: OutreachChannel; label: string }[] = [
  { value: "sms", label: "SMS" },
  { value: "portal", label: "Portal" },
  { value: "phone", label: "Phone" },
  { value: "email", label: "Email" },
  { value: "letter", label: "Letter" },
];

const CHANNEL_COLORS: Record<OutreachChannel, string> = {
  sms: "#3B82F6",
  portal: "#8B5CF6",
  phone: "#10B981",
  email: "#F59E0B",
  letter: "#64748B",
};

const colors = {
  slate900: "#0F172A",
  slate600: "#475569",
  slate400: "#64748B",
  slate200: "#E2E8F0",
  slate100: "#F1F5F9",
  slate50: "#F8FAFC",
  white: "#FFFFFF",
  primary: "#2563EB",
  red600: "#DC2626",
};

export function OutreachTemplateManager() {
  const queryClient = useQueryClient();
  const [dialogOpen, setDialogOpen] = React.useState(false);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["outreach-templates"],
    queryFn: () => getOutreachTemplates(),
  });

  const seedMutation = useMutation({
    mutationFn: seedOutreachDefaults,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["outreach-templates"] });
    },
  });

  const templates = data ?? [];

  return (
    <div
      className="premium-card"
      style={{ padding: 24, borderRadius: 12 }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 16,
          gap: 12,
        }}
      >
        <div>
          <h3
            className="gradient-text"
            style={{ margin: 0, fontSize: 16, fontWeight: 700 }}
          >
            Outreach Templates
          </h3>
          <p
            style={{
              margin: "4px 0 0",
              fontSize: 12,
              color: colors.slate600,
            }}
          >
            Reusable messages for SMS, portal, phone, email, and letter campaigns.
          </p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            onClick={() => seedMutation.mutate()}
            disabled={seedMutation.isPending}
            className="btn-press"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "8px 14px",
              borderRadius: 8,
              border: `1px solid ${colors.slate200}`,
              background: colors.white,
              color: colors.slate900,
              fontSize: 13,
              fontWeight: 600,
              cursor: seedMutation.isPending ? "wait" : "pointer",
            }}
          >
            <Sparkles size={14} /> Seed Defaults
          </button>
          <button
            type="button"
            onClick={() => setDialogOpen(true)}
            className="btn-press"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "8px 14px",
              borderRadius: 8,
              border: "none",
              background: "linear-gradient(135deg, #2563EB, #1D4ED8)",
              color: colors.white,
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
              boxShadow: "0 2px 8px rgba(37,99,235,0.3)",
            }}
          >
            <Plus size={14} /> New Template
          </button>
        </div>
      </div>

      {isError ? (
        <EmptyState
          title="Failed to load templates"
          description="Please try again."
        />
      ) : isLoading ? (
        <div
          className="shimmer"
          style={{ height: 160, borderRadius: 8 }}
        />
      ) : templates.length === 0 ? (
        <EmptyState
          title="No templates yet"
          description="Click Seed Defaults to add SMS / portal / phone starters, or create your own."
        />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {templates.map((tpl) => (
            <TemplateRow key={tpl.id} tpl={tpl} />
          ))}
        </div>
      )}

      {dialogOpen && (
        <CreateTemplateDialog onClose={() => setDialogOpen(false)} />
      )}
    </div>
  );
}

function TemplateRow({ tpl }: { tpl: OutreachTemplate }) {
  const c = CHANNEL_COLORS[tpl.channel] ?? "#64748B";
  return (
    <div
      style={{
        padding: "12px 14px",
        borderRadius: 10,
        background: colors.slate50,
        border: `1px solid ${colors.slate200}`,
        borderLeft: `4px solid ${c}`,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 4,
        }}
      >
        <span
          style={{
            display: "inline-block",
            padding: "2px 8px",
            borderRadius: 999,
            fontSize: 10,
            fontWeight: 700,
            color: c,
            backgroundColor: `${c}1A`,
            textTransform: "uppercase",
            letterSpacing: "0.05em",
          }}
        >
          {tpl.channel}
        </span>
        <strong style={{ fontSize: 13, color: colors.slate900 }}>{tpl.name}</strong>
        {!tpl.is_active && (
          <span
            style={{
              fontSize: 10,
              fontWeight: 600,
              color: colors.slate400,
              textTransform: "uppercase",
            }}
          >
            inactive
          </span>
        )}
      </div>
      {tpl.subject && (
        <div style={{ fontSize: 12, color: colors.slate600, fontWeight: 500 }}>
          Subject: {tpl.subject}
        </div>
      )}
      <p
        style={{
          margin: "4px 0 0",
          fontSize: 12,
          color: colors.slate600,
          whiteSpace: "pre-wrap",
        }}
      >
        {tpl.message_text}
      </p>
    </div>
  );
}

function CreateTemplateDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [channel, setChannel] = React.useState<OutreachChannel>("sms");
  const [name, setName] = React.useState("");
  const [subject, setSubject] = React.useState("");
  const [messageText, setMessageText] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: () =>
      createOutreachTemplate({
        channel,
        name,
        subject: subject || null,
        message_text: messageText,
        is_active: true,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["outreach-templates"] });
      onClose();
    },
    onError: (err: unknown) => {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ||
        "Failed to create template";
      setError(msg);
    },
  });

  const canSubmit =
    name.trim().length > 0 && messageText.trim().length > 0 && !createMutation.isPending;

  return (
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15,23,42,0.4)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          width: 520,
          maxWidth: "90vw",
          background: colors.white,
          borderRadius: 12,
          padding: 24,
          boxShadow: "0 20px 60px rgba(0,0,0,0.2)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 16,
          }}
        >
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: colors.slate900 }}>
            New Outreach Template
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            style={{
              border: "none",
              background: "transparent",
              cursor: "pointer",
              padding: 4,
              color: colors.slate600,
            }}
          >
            <X size={18} />
          </button>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <Field label="Channel">
            <select
              value={channel}
              onChange={(e) => setChannel(e.target.value as OutreachChannel)}
              style={inputStyle}
            >
              {CHANNELS.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Name">
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Quarterly outreach for diabetic patients"
              style={inputStyle}
            />
          </Field>
          {(channel === "email" || channel === "portal" || channel === "letter") && (
            <Field label="Subject">
              <input
                type="text"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                placeholder="Subject line"
                style={inputStyle}
              />
            </Field>
          )}
          <Field label="Message">
            <textarea
              value={messageText}
              onChange={(e) => setMessageText(e.target.value)}
              rows={6}
              placeholder="Hi {first_name}, time to schedule your follow-up…"
              style={{ ...inputStyle, resize: "vertical", fontFamily: "inherit" }}
            />
          </Field>

          {error && (
            <div
              style={{
                padding: "8px 12px",
                borderRadius: 8,
                background: "#FEF2F2",
                color: colors.red600,
                fontSize: 12,
                border: "1px solid #FECACA",
              }}
            >
              {error}
            </div>
          )}
        </div>

        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: 8,
            marginTop: 20,
          }}
        >
          <button
            type="button"
            onClick={onClose}
            style={{
              padding: "8px 14px",
              borderRadius: 8,
              border: `1px solid ${colors.slate200}`,
              background: colors.white,
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
              color: colors.slate600,
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => {
              setError(null);
              createMutation.mutate();
            }}
            disabled={!canSubmit}
            style={{
              padding: "8px 14px",
              borderRadius: 8,
              border: "none",
              background: canSubmit
                ? "linear-gradient(135deg, #2563EB, #1D4ED8)"
                : colors.slate200,
              color: colors.white,
              fontSize: 13,
              fontWeight: 600,
              cursor: canSubmit ? "pointer" : "not-allowed",
              opacity: canSubmit ? 1 : 0.7,
            }}
          >
            {createMutation.isPending ? "Saving…" : "Create Template"}
          </button>
        </div>
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  padding: "8px 10px",
  borderRadius: 8,
  border: `1px solid ${colors.slate200}`,
  fontSize: 13,
  color: colors.slate900,
  background: colors.white,
};

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label
      style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, color: colors.slate600, fontWeight: 600 }}
    >
      {label}
      {children}
    </label>
  );
}

export default OutreachTemplateManager;
