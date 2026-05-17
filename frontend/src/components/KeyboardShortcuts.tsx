"use client";

/**
 * KeyboardShortcuts — Global keyboard shortcuts + help modal.
 *
 * Catalog of every shortcut lives in `@/lib/keyboard-shortcuts.ts`
 * (SHORTCUT_CATALOG).  This component owns:
 *
 *   * The single global `keydown` listener.
 *   * Navigation dispatch via Next.js's `useRouter()`.
 *   * Forwarding context-sensitive shortcuts (A / D / R / ← / → / Esc)
 *     to per-page handlers registered through `registerContextShortcut`.
 *   * The `?` help overlay.
 *
 * Components that want their own behaviour for A / D / R / arrows / Esc
 * import `registerContextShortcut` from "@/lib/keyboard-shortcuts" and
 * push a handler on mount / focus.
 */

import { useEffect, useState, useRef, CSSProperties } from "react";
import { useRouter } from "next/navigation";
import { X, Keyboard } from "lucide-react";
import {
  SHORTCUT_CATALOG,
  dispatchContextShortcut,
  dispatchEscape,
  focusPatientSearch,
  type ShortcutCategory,
} from "@/lib/keyboard-shortcuts";

// ---------------------------------------------------------------------------
// localStorage flag — set the first time any shortcut fires
// ---------------------------------------------------------------------------
const KB_USED_KEY = "raf_kb_used";

export function markKeyboardShortcutUsed() {
  try {
    const alreadySet = localStorage.getItem(KB_USED_KEY) === "1";
    localStorage.setItem(KB_USED_KEY, "1");
    if (!alreadySet) {
      window.dispatchEvent(new CustomEvent("raf-kb-used"));
    }
  } catch {
    /* ignore */
  }
}

export function hasUsedKeyboardShortcuts(): boolean {
  try {
    return localStorage.getItem(KB_USED_KEY) === "1";
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Design tokens
// ---------------------------------------------------------------------------
const BG_OVERLAY = "rgba(0,0,0,0.7)";
const BG_MODAL = "#0F172A";
const BG_BADGE = "#1E293B";
const BORDER = "#334155";
const TEXT_PRIMARY = "#F1F5F9";
const TEXT_SECONDARY = "#94A3B8";
const TEXT_CATEGORY = "#64748B";
const ACCENT = "#60A5FA";
const ACCENT_GREEN = "#2dd4bf";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function KeyboardShortcuts() {
  const router = useRouter();
  const [showHelp, setShowHelp] = useState(false);
  const pendingKeyRef = useRef<string | null>(null);
  const pendingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ----- Navigation handler (g <letter>) -----------------------------------
  function handleNavSequence(sequence: string): boolean {
    switch (sequence) {
      case "g h": router.push("/"); return true;
      case "g p": router.push("/patients"); return true;
      case "g w": router.push("/worklist"); return true;
      case "g a": router.push("/analysis"); return true;
      case "g s": router.push("/review-queue"); return true;
      case "g r": router.push("/reports"); return true;
      case "g e": router.push("/emr-config"); return true;
      default: return false;
    }
  }

  // ----- Single-key handler ------------------------------------------------
  function handleSingleKey(key: string): boolean {
    if (key === "?") { setShowHelp(true); return true; }
    if (key === "/") { focusPatientSearch(); return true; }
    if (key === "A" || key === "a") {
      return dispatchContextShortcut("accept-focused-suspect");
    }
    if (key === "D" || key === "d") {
      return dispatchContextShortcut("dismiss-focused-suspect");
    }
    if (key === "R" || key === "r") {
      return dispatchContextShortcut("mark-meat-reviewed");
    }
    if (key === "ArrowLeft")  return dispatchContextShortcut("prev-patient");
    if (key === "ArrowRight") return dispatchContextShortcut("next-patient");
    if (key === "Escape") {
      if (showHelp) { setShowHelp(false); return true; }
      dispatchEscape();
      return true;
    }
    return false;
  }

  // ----- Listener ----------------------------------------------------------
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName ?? "";
      const isEditable = target?.isContentEditable === true;
      const isInInput = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || isEditable;
      // `?` and `Escape` work even when typing — they're universal.
      const universal = e.key === "?" || e.key === "Escape";
      if (isInInput && !universal) return;

      if (e.metaKey || e.ctrlKey || e.altKey) return;

      const key = e.key;
      const pending = pendingKeyRef.current;

      // Two-key sequence first.
      if (pending) {
        const sequence = `${pending} ${key}`;
        if (pendingTimerRef.current) clearTimeout(pendingTimerRef.current);
        pendingKeyRef.current = null;
        if (handleNavSequence(sequence)) {
          e.preventDefault();
          markKeyboardShortcutUsed();
          return;
        }
      }

      // Single-key dispatch.
      if (handleSingleKey(key)) {
        e.preventDefault();
        markKeyboardShortcutUsed();
        return;
      }

      // Begin a new "g" sequence?
      if (key === "g") {
        pendingKeyRef.current = "g";
        if (pendingTimerRef.current) clearTimeout(pendingTimerRef.current);
        pendingTimerRef.current = setTimeout(() => {
          pendingKeyRef.current = null;
        }, 650);
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      if (pendingTimerRef.current) clearTimeout(pendingTimerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showHelp]);

  if (!showHelp) return null;

  return (
    <div
      data-testid="shortcut-help-overlay"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9998,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: BG_OVERLAY,
        backdropFilter: "blur(4px)",
        padding: "16px",
      }}
      onClick={() => setShowHelp(false)}
      role="dialog"
      aria-modal="true"
      aria-label="Keyboard shortcuts reference"
    >
      <div
        style={{
          width: "100%",
          maxWidth: 640,
          maxHeight: "85vh",
          overflowY: "auto",
          backgroundColor: BG_MODAL,
          border: `1px solid ${BORDER}`,
          borderRadius: 14,
          boxShadow: "0 25px 60px rgba(0,0,0,0.6)",
          fontFamily:
            '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "16px 20px",
            borderBottom: `1px solid ${BORDER}`,
            position: "sticky",
            top: 0,
            backgroundColor: BG_MODAL,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Keyboard style={{ width: 18, height: 18, color: ACCENT }} aria-hidden />
            <span style={{ fontSize: 15, fontWeight: 600, color: TEXT_PRIMARY }}>
              Keyboard Shortcuts
            </span>
          </div>
          <button
            onClick={() => setShowHelp(false)}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              color: TEXT_SECONDARY,
              display: "flex",
              padding: 4,
              borderRadius: 4,
            }}
            aria-label="Close keyboard shortcuts"
          >
            <X style={{ width: 16, height: 16 }} />
          </button>
        </div>

        <div style={{ padding: "16px 20px 20px" }}>
          {(["Navigation", "Patient & Worklist", "Review Actions", "General"] as ShortcutCategory[]).map(
            (cat, i) => (
              <div key={cat}>
                <SectionHeading label={cat} style={{ marginTop: i === 0 ? 0 : 18 }} />
                <div>
                  {SHORTCUT_CATALOG.filter((s) => s.category === cat).map((s) => (
                    <ShortcutRow key={s.key} shortcut={s} />
                  ))}
                </div>
              </div>
            ),
          )}
        </div>

        <div
          style={{
            padding: "10px 20px",
            borderTop: `1px solid ${BORDER}`,
            fontSize: 12,
            color: TEXT_CATEGORY,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <kbd style={kbdStyle}>?</kbd>
          <span>to show this panel &middot;</span>
          <kbd style={kbdStyle}>Esc</kbd>
          <span>to close</span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SectionHeading({ label, style }: { label: string; style?: CSSProperties }) {
  return (
    <div
      style={{
        fontSize: 11,
        fontWeight: 600,
        textTransform: "uppercase" as const,
        letterSpacing: "0.08em",
        color: TEXT_CATEGORY,
        marginBottom: 8,
        ...style,
      }}
    >
      {label}
    </div>
  );
}

function ShortcutRow({ shortcut }: { shortcut: { key: string; description: string } }) {
  const keys = shortcut.key.split(" ");
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
        padding: "6px 0",
        borderBottom: `1px solid ${BORDER}22`,
      }}
    >
      <span style={{ fontSize: 13, color: TEXT_SECONDARY, flex: 1 }}>
        {shortcut.description}
      </span>
      <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
        {keys.map((k, i) => (
          <kbd key={i} style={{ ...kbdStyle, color: ACCENT_GREEN, borderColor: "#334155" }}>
            {k}
          </kbd>
        ))}
      </div>
    </div>
  );
}

const kbdStyle: CSSProperties = {
  display: "inline-block",
  backgroundColor: BG_BADGE,
  border: `1px solid ${BORDER}`,
  borderRadius: 4,
  padding: "2px 6px",
  fontSize: 12,
  fontFamily: "inherit",
  fontWeight: 600,
  color: TEXT_SECONDARY,
  lineHeight: 1.5,
};
