"use client";

/**
 * GapOutreachHistoryDrawer — slide-in panel showing every outreach event for
 * a single recapture gap.  Renders a vertical timeline with channel chips,
 * status icons, response text, and outcome badges.
 */

import React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Check,
  CheckCheck,
  Clock,
  MessageCircle,
  Phone,
  Mail,
  FileText,
  Smartphone,
  X,
  XOctagon,
  AlertTriangle,
} from "lucide-react";

import {
  getGapOutreachHistory,
  type OutreachChannel,
  type OutreachEvent,
  type OutreachStatus,
} from "@/lib/api";

interface Props {
  gapId: number | null;
  open: boolean;
  onClose: () => void;
}

const colors = {
  slate900: "#0F172A",
  slate700: "#334155",
  slate600: "#475569",
  slate400: "#64748B",
  slate200: "#E2E8F0",
  slate100: "#F1F5F9",
  slate50: "#F8FAFC",
  white: "#FFFFFF",
  primary: "#2563EB",
  emerald: "#10B981",
  amber: "#F59E0B",
  red: "#DC2626",
  violet: "#8B5CF6",
  gray: "#64748B",
};

const STATUS_META: Record<
  OutreachStatus,
  { label: string; color: string; icon: React.ComponentType<{ size?: number }> }
> = {
  queued: { label: "Queued", color: colors.gray, icon: Clock },
  sent: { label: "Sent", color: colors.primary, icon: Check },
  delivered: { label: "Delivered", color: colors.violet, icon: CheckCheck },
  responded: { label: "Responded", color: colors.emerald, icon: MessageCircle },
  failed: { label: "Failed", color: colors.red, icon: AlertTriangle },
  opted_out: { label: "Opted Out", color: colors.slate600, icon: XOctagon },
};

const CHANNEL_META: Record<
  OutreachChannel,
  { label: string; color: string; icon: React.ComponentType<{ size?: number }> }
> = {
  sms: { label: "SMS", color: colors.primary, icon: Smartphone },
  portal: { label: "Portal", color: colors.violet, icon: MessageCircle },
  phone: { label: "Phone", color: colors.emerald, icon: Phone },
  email: { label: "Email", color: colors.amber, icon: Mail },
  letter: { label: "Letter", color: colors.gray, icon: FileText },
};

function formatDateTime(s: string | null | undefined): string {
  if (!s) return "—";
  try {
    return new Date(s).toLocaleString();
  } catch {
    return s;
  }
}

export function GapOutreachHistoryDrawer({ gapId, open, onClose }: Props) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["gap-outreach-history", gapId],
    queryFn: () => getGapOutreachHistory(gapId as number),
    enabled: open && gapId != null,
  });

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Gap outreach history"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15,23,42,0.4)",
        zIndex: 200,
        display: "flex",
        justifyContent: "flex-end",
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <aside
        style={{
          width: 520,
          maxWidth: "100vw",
          height: "100%",
          background: colors.white,
          boxShadow: "-12px 0 40px rgba(0,0,0,0.15)",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <header
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "16px 20px",
            borderBottom: `1px solid ${colors.slate200}`,
          }}
        >
          <div>
            <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: colors.slate900 }}>
              Outreach Timeline
            </h3>
            <p style={{ margin: "2px 0 0", fontSize: 12, color: colors.slate600 }}>
              Gap #{gapId ?? "—"}
              {data ? ` · ${data.length} event${data.length === 1 ? "" : "s"}` : ""}
            </p>
          </div>
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
        </header>

        <div style={{ flex: 1, overflowY: "auto", padding: "16px 20px" }}>
          {isError ? (
            <div
              style={{
                padding: 16,
                borderRadius: 10,
                background: "#FEF2F2",
                color: colors.red,
                border: "1px solid #FECACA",
                fontSize: 13,
              }}
            >
              Failed to load outreach history.
            </div>
          ) : isLoading ? (
            <div
              className="shimmer"
              style={{ height: 200, borderRadius: 8 }}
            />
          ) : !data || data.length === 0 ? (
            <div
              style={{
                padding: 24,
                borderRadius: 10,
                background: colors.slate50,
                border: `1px solid ${colors.slate200}`,
                textAlign: "center",
                fontSize: 13,
                color: colors.slate600,
              }}
            >
              No outreach has been queued for this gap yet.
            </div>
          ) : (
            <Timeline events={data} />
          )}
        </div>
      </aside>
    </div>
  );
}

function Timeline({ events }: { events: OutreachEvent[] }) {
  return (
    <ol
      style={{
        listStyle: "none",
        margin: 0,
        padding: 0,
        position: "relative",
      }}
    >
      {/* vertical rail */}
      <div
        aria-hidden
        style={{
          position: "absolute",
          left: 14,
          top: 12,
          bottom: 12,
          width: 2,
          background: colors.slate200,
        }}
      />
      {events.map((evt) => (
        <TimelineRow key={evt.id} event={evt} />
      ))}
    </ol>
  );
}

function TimelineRow({ event }: { event: OutreachEvent }) {
  const statusMeta = STATUS_META[event.status];
  const channelMeta = CHANNEL_META[event.channel];
  const StatusIcon = statusMeta?.icon ?? Clock;
  const ChannelIcon = channelMeta?.icon ?? MessageCircle;

  // The most relevant timestamp for the row is the latest set status timestamp
  const relevantTime =
    event.responded_at || event.delivered_at || event.sent_at || event.scheduled_for ||
    event.created_at;

  return (
    <li
      style={{
        position: "relative",
        paddingLeft: 40,
        paddingBottom: 16,
      }}
    >
      <span
        aria-hidden
        style={{
          position: "absolute",
          left: 4,
          top: 4,
          width: 22,
          height: 22,
          borderRadius: 999,
          background: statusMeta?.color ?? colors.gray,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          color: colors.white,
          boxShadow: "0 0 0 4px white",
        }}
      >
        <StatusIcon size={12} />
      </span>

      <div
        style={{
          padding: 12,
          borderRadius: 10,
          background: colors.slate50,
          border: `1px solid ${colors.slate200}`,
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            flexWrap: "wrap",
            marginBottom: 4,
          }}
        >
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              padding: "2px 8px",
              borderRadius: 999,
              background: `${channelMeta?.color}1A`,
              color: channelMeta?.color,
              fontSize: 11,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
            }}
          >
            <ChannelIcon size={12} />
            {channelMeta?.label ?? event.channel}
          </span>
          <span
            style={{
              fontSize: 11,
              fontWeight: 700,
              color: statusMeta?.color,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
            }}
          >
            {statusMeta?.label}
          </span>
          {event.template_name && (
            <span style={{ fontSize: 12, color: colors.slate700, fontWeight: 600 }}>
              · {event.template_name}
            </span>
          )}
        </div>

        <div style={{ fontSize: 11, color: colors.slate600, marginBottom: 6 }}>
          {formatDateTime(relevantTime)}
        </div>

        {event.response_text && (
          <p
            style={{
              margin: "4px 0 6px",
              fontSize: 13,
              color: colors.slate900,
              fontStyle: "italic",
              borderLeft: `3px solid ${colors.emerald}`,
              paddingLeft: 8,
            }}
          >
            “{event.response_text}”
          </p>
        )}

        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {event.resulted_in_visit && (
            <Badge color={colors.amber}>Resulted in visit</Badge>
          )}
          {event.resulted_in_closure && (
            <Badge color={colors.emerald}>Gap closed</Badge>
          )}
        </div>
      </div>
    </li>
  );
}

function Badge({ color, children }: { color: string; children: React.ReactNode }) {
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: 999,
        background: `${color}1A`,
        color,
        fontSize: 10,
        fontWeight: 700,
        textTransform: "uppercase",
        letterSpacing: "0.05em",
      }}
    >
      {children}
    </span>
  );
}

export default GapOutreachHistoryDrawer;
