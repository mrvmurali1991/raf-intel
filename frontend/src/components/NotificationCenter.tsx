"use client";

import {
  Bell,
  CheckCheck,
  Microscope,
  AlertTriangle,
  RefreshCw,
  AlertCircle,
  CalendarClock,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import {
  CSSProperties,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import api, { API_BASE } from "@/lib/api";
import logger from "@/lib/logger";

// ---------------------------------------------------------------------------
// RAF score silent-refresh event type
// ---------------------------------------------------------------------------

type RafUpdatedEvent = {
  type: "raf_updated";
  pid: number;
  tenant_id: string;
  raf_score: number | null;
  ts: string;
};

function isRafUpdatedEvent(v: unknown): v is RafUpdatedEvent {
  if (!v || typeof v !== "object") return false;
  const o = v as Record<string, unknown>;
  return (
    o.type === "raf_updated" &&
    typeof o.pid === "number" &&
    typeof o.tenant_id === "string" &&
    typeof o.ts === "string"
  );
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type NotificationType =
  | "analysis_complete"
  | "suspect_found"
  | "sync_complete"
  | "sync_failed"
  | "submission_deadline"
  | "system_alert";

export interface AppNotification {
  id: string;
  type: NotificationType;
  title: string;
  description: string;
  href?: string;
  createdAt: number; 
  readAt?: number;   
}

// ---------------------------------------------------------------------------
// Relative time formatter
// ---------------------------------------------------------------------------

function relativeTime(ms: number): string {
  const diff = Date.now() - ms;
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

// ---------------------------------------------------------------------------
// Icon + color map
// ---------------------------------------------------------------------------

interface TypeMeta {
  Icon: React.ComponentType<{ size?: number; style?: CSSProperties }>;
  iconColor: string;
  bgColor: string;
}

const TYPE_META: Record<NotificationType, TypeMeta> = {
  analysis_complete: { Icon: Microscope, iconColor: "#2563eb", bgColor: "#dbeafe" },
  suspect_found: { Icon: AlertTriangle, iconColor: "#ea580c", bgColor: "#ffedd5" },
  sync_complete: { Icon: RefreshCw, iconColor: "#16a34a", bgColor: "#dcfce7" },
  sync_failed: { Icon: AlertCircle, iconColor: "#dc2626", bgColor: "#fee2e2" },
  submission_deadline: { Icon: CalendarClock, iconColor: "#ca8a04", bgColor: "#fef9c3" },
  system_alert: { Icon: AlertCircle, iconColor: "#dc2626", bgColor: "#fee2e2" },
};

// ---------------------------------------------------------------------------
// NotificationRow
// ---------------------------------------------------------------------------

interface NotificationRowProps {
  notification: AppNotification;
  onClick: (n: AppNotification) => void;
  onDismiss: (id: string) => void;
}

function NotificationRow({ notification, onClick, onDismiss }: NotificationRowProps) {
  const meta = TYPE_META[notification.type] ?? TYPE_META.system_alert;
  const isUnread = !notification.readAt;
  const [hovered, setHovered] = useState(false);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onClick(notification)}
      onKeyDown={(e) => e.key === "Enter" && onClick(notification)}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      aria-label={`${notification.title}: ${notification.description}`}
      className="hover-lift"
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 10,
        padding: "10px 14px",
        cursor: "pointer",
        backgroundColor: hovered ? "#f8fafc" : isUnread ? "#f0f9ff" : "#ffffff",
        borderBottom: "1px solid #f1f5f9",
        position: "relative",
        transition: "background-color 120ms, transform 150ms, box-shadow 150ms",
      }}
    >
      <div
        style={{
          width: 34,
          height: 34,
          borderRadius: 8,
          backgroundColor: meta.bgColor,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
          marginTop: 1,
        }}
      >
        <meta.Icon size={16} style={{ color: meta.iconColor }} />
      </div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 13,
            fontWeight: isUnread ? 600 : 500,
            color: "#0f172a",
            marginBottom: 2,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {notification.title}
        </div>
        <div
          style={{
            fontSize: 12,
            color: "#64748b",
            lineHeight: 1.4,
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
          }}
        >
          {notification.description}
        </div>
        <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 3 }}>
          {relativeTime(notification.createdAt)}
        </div>
      </div>

      {isUnread && (
        <div
          aria-label="Unread"
          style={{
            width: 7, height: 7, borderRadius: "50%",
            backgroundColor: meta.iconColor, flexShrink: 0,
            marginTop: 6, boxShadow: `0 0 6px ${meta.iconColor}80`,
          }}
        />
      )}

      {hovered && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDismiss(notification.id);
          }}
          aria-label="Dismiss notification"
          style={{
            position: "absolute", top: 8, right: 8,
            background: "none", border: "none", cursor: "pointer",
            padding: 3, borderRadius: 4, display: "flex", color: "#94a3b8",
          }}
        >
          <X size={13} />
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// NotificationCenter
// ---------------------------------------------------------------------------

interface NotificationCenterProps {
  collapsed?: boolean;
}

export function NotificationCenter({ collapsed = false }: NotificationCenterProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const panelRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  // Fetch persisted alerts
  const fetchAlerts = useCallback(async () => {
    try {
      const res = await api.get("/api/realtime/alerts");
      // Map backend alert format to UI AppNotification map
      if (res.data?.alerts) {
         setNotifications(res.data.alerts);
      }
    } catch {}
  }, []);

  useEffect(() => {
    let emrBlocked = false;
    // Fetch initial alerts asynchronously
    (async () => {
      try {
        const res = await api.get("/api/realtime/alerts");
        if (res.data?.alerts) {
          setNotifications(res.data.alerts);
        }
      } catch (err) {
        // EMR deactivated → the SSE stream will also be blocked by the
        // backend's emr_gate middleware, so don't even attempt to connect.
        const status = (err as { response?: { status?: number } })?.response
          ?.status;
        if (status === 423) emrBlocked = true;
      }
    })();
    if (emrBlocked) return;

    // TODO: Replace this block with proper SSE-ticket auth once the backend
    // endpoint is live. Required endpoint spec:
    //   GET /api/notifications/sse-ticket
    //   Auth: Bearer JWT (standard Authorization header)
    //   Response: { ticket: string }  (short-lived one-time token, e.g. 30 s)
    // Then open: EventSource(`${API_BASE}/api/notifications/stream?ticket=${ticket}`)
    // This avoids sending the long-lived JWT in the URL query string.
    let es: EventSource | null = null;
    (async () => {
      try {
        const ticketRes = await api.get<{ ticket: string }>("/api/notifications/sse-ticket");
        const ticket = ticketRes.data.ticket;
        const apiBase = API_BASE;
        es = new EventSource(
          `${apiBase}/api/notifications/stream?ticket=${ticket}`,
          { withCredentials: true }
        );

        es.onmessage = (e) => {
          try {
            const payload = JSON.parse(e.data);

            // ---------------------------------------------------------------
            // raf_updated — silent cache invalidation, no toast
            // ---------------------------------------------------------------
            if (isRafUpdatedEvent(payload)) {
              const pid = payload.pid;
              logger.info("NotificationCenter", "raf_updated: invalidating caches", { pid });

              queryClient.invalidateQueries({
                predicate: (q) =>
                  Array.isArray(q.queryKey) &&
                  q.queryKey[0] === "raf-breakdown" &&
                  String(q.queryKey[1]) === String(pid),
              });
              queryClient.invalidateQueries({ queryKey: ["raf-history", pid] });
              queryClient.invalidateQueries({ queryKey: ["patient-profile", pid] });
              queryClient.invalidateQueries({ queryKey: ["patient", pid] });
              queryClient.invalidateQueries({ queryKey: ["model-comparison", pid] });
              return; // do NOT show a toast for this event type
            }

            // ---------------------------------------------------------------
            // All other events — push to notification UI (toast/bell)
            // ---------------------------------------------------------------
            if (payload?.type || payload?.title) {
              // Push to UI queue immediately on receive
              setNotifications(prev => {
                // deduplicate checking
                if(prev.find((x) => x.id === payload.id)) return prev;
                return [payload, ...prev].slice(0, 50);
              });
            }
          } catch {}
        };

        // When the backend refuses the connection (e.g. 423 from emr_gate, or
        // auth expiry), EventSource will otherwise retry forever. Close it so
        // the browser doesn't hammer the server in an infinite loop.
        es.onerror = () => {
          if (es && es.readyState === EventSource.CLOSED) return;
          es?.close();
        };
      } catch {
        // SSE ticket endpoint not yet available — SSE disabled until backend is ready.
        logger.error("NotificationCenter", "SSE ticket endpoint unavailable; real-time notifications disabled");
      }
    })();

    return () => { if (es) es.close(); };
  }, [fetchAlerts]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handleOutside(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node) && triggerRef.current && !triggerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [open]);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [open]);

  const unreadCount = notifications.filter((n) => !n.readAt).length;

  async function handleMarkAllRead() {
    setNotifications(prev => prev.map(n => ({ ...n, readAt: Date.now() })));
    try {
      await api.put("/api/realtime/alerts/read-all");
    } catch {}
  }

  async function handleClickNotification(n: AppNotification) {
    // Optimistic UI update
    setNotifications(prev => prev.map(item => item.id === n.id ? { ...item, readAt: Date.now() } : item));
    setOpen(false);
    
    if (n.href) router.push(n.href);
    
    // Remote syncing
    try {
      if (n.id && typeof n.id === "number") {
          await api.put(`/api/realtime/alerts/${n.id}/read`);
      }
    } catch {}
  }

  function handleDismiss(id: string) {
    setNotifications(prev => prev.filter(n => n.id !== id));
  }

  function handleClearAll() {
    setNotifications([]);
  }

  const TEXT_SUBTLE = "#64748b";

  return (
    <div style={{ position: "relative", flexShrink: 0 }}>
      {/* Bell trigger button */}
      <button
        ref={triggerRef}
        onClick={() => setOpen((v) => !v)}
        aria-label={`Notifications${unreadCount > 0 ? `, ${unreadCount} unread` : ""}`}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={collapsed ? "Notifications" : undefined}
        style={{
          position: "relative", display: "flex", alignItems: "center", justifyContent: "center",
          width: 32, height: 32, borderRadius: 6, background: open ? "#1e293b" : "none",
          border: "none", cursor: "pointer", color: TEXT_SUBTLE, transition: "background 150ms, color 150ms",
          flexShrink: 0,
        }}
        onMouseEnter={(e) => {
          if (!open) {
            (e.currentTarget as HTMLButtonElement).style.background = "#1e293b";
            (e.currentTarget as HTMLButtonElement).style.color = "#cbd5e1";
          }
        }}
        onMouseLeave={(e) => {
          if (!open) {
            (e.currentTarget as HTMLButtonElement).style.background = "none";
            (e.currentTarget as HTMLButtonElement).style.color = TEXT_SUBTLE;
          }
        }}
      >
        <Bell style={{ width: 16, height: 16 }} aria-hidden />

        {unreadCount > 0 && (
          <span
            aria-hidden
            style={{
               position: "absolute", top: 3, right: 3, minWidth: 15, height: 15,
               borderRadius: 8, backgroundColor: "#ef4444", color: "#ffffff",
               fontSize: 9, fontWeight: 700, display: "flex", alignItems: "center",
               justifyContent: "center", padding: "0 3px", lineHeight: 1, border: "1.5px solid #0f172a",
            }}
          >
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      {/* Dropdown panel */}
      {open && (
        <div
          ref={(el) => {
            (panelRef as React.MutableRefObject<HTMLDivElement | null>).current = el;
            if (el && triggerRef.current) {
              const rect = triggerRef.current.getBoundingClientRect();
              el.style.top = `${rect.top}px`;
              el.style.left = `${rect.right + 8}px`;
            }
          }}
          role="dialog"
          aria-label="Notifications panel"
          aria-modal="false"
          className="premium-card animate-slide-up"
          style={{
            position: "fixed", top: 0, left: 240, zIndex: 200, width: 400,
            maxHeight: 500, backgroundColor: "#ffffff", borderRadius: 10,
            boxShadow: "0 8px 30px rgba(0,0,0,0.15), 0 2px 8px rgba(0,0,0,0.08)",
            display: "flex", flexDirection: "column", overflow: "hidden",
            border: "1px solid #e2e8f0",
            fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
          }}
        >
          {/* Header */}
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 14px 10px", borderBottom: "1px solid #f1f5f9", flexShrink: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Bell size={15} style={{ color: "#0f172a" }} aria-hidden />
              <span style={{ fontSize: 14, fontWeight: 600, color: "#0f172a" }}>Notifications</span>
              {unreadCount > 0 && (
                <span style={{ fontSize: 11, fontWeight: 600, backgroundColor: "#eff6ff", color: "#2563eb", padding: "1px 6px", borderRadius: 10 }}>
                  {unreadCount} new
                </span>
              )}
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
              {notifications.length > 0 && unreadCount > 0 && (
                <button onClick={handleMarkAllRead} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 11, fontWeight: 500, color: "#2563eb", background: "none", border: "none", cursor: "pointer", padding: "3px 7px", borderRadius: 4 }} aria-label="Mark all notifications as read">
                  <CheckCheck size={13} aria-hidden />
                  Mark all read
                </button>
              )}
              <button onClick={() => setOpen(false)} aria-label="Close notifications" style={{ background: "none", border: "none", cursor: "pointer", color: "#94a3b8", display: "flex", alignItems: "center", padding: 3, borderRadius: 4 }}>
                <X size={15} aria-hidden />
              </button>
            </div>
          </div>

          {/* Notification list */}
          <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }} role="list" aria-live="polite" aria-label="Notification list">
            {notifications.length === 0 ? (
              <div role="listitem" style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "40px 20px", gap: 10 }}>
                <div style={{ width: 44, height: 44, borderRadius: 12, backgroundColor: "#f8fafc", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <Bell size={20} style={{ color: "#cbd5e1" }} aria-hidden />
                </div>
                <div style={{ textAlign: "center" }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "#475569" }}>No notifications yet</div>
                  <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 3 }}>Activity from analysis, sync, and submissions will appear here.</div>
                </div>
              </div>
            ) : (
              notifications.map((n) => (
                <div key={n.id} role="listitem">
                  <NotificationRow notification={n} onClick={handleClickNotification} onDismiss={handleDismiss} />
                </div>
              ))
            )}
          </div>

          {/* Footer */}
          {notifications.length > 0 && (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 14px", borderTop: "1px solid #f1f5f9", flexShrink: 0 }}>
              <button onClick={() => { setOpen(false); router.push("/activity"); }} style={{ fontSize: 12, fontWeight: 500, color: "#2563eb", background: "none", border: "none", cursor: "pointer", padding: 0 }}>
                View all activity
              </button>
              <button onClick={handleClearAll} style={{ fontSize: 12, color: "#94a3b8", background: "none", border: "none", cursor: "pointer", padding: 0 }} aria-label="Clear all notifications">
                Clear all
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Convenience hook
// ---------------------------------------------------------------------------

export function useNotify() {
  const notify = useCallback(
    async (detail: Omit<AppNotification, "id" | "createdAt">) => {
      // Opt-in mechanism: you can either POST this to an endpoint 
      // or rely entirely on Backend SSE pushing to the stream.
      // E.g., await api.post("/api/realtime/alerts", detail);
    },
    []
  );
  return { notify };
}
