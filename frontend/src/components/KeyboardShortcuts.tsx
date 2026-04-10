"use client";

/**
 * KeyboardShortcuts — Global sequential keyboard shortcuts + help modal.
 *
 * Shortcuts:
 *   g h  → Dashboard
 *   g p  → Patients
 *   g a  → Clinical Analysis
 *   g s  → Review Queue (Suspects)
 *   g r  → Analytics (Reports)
 *   g e  → EMR Config
 *   ?    → Show this help modal
 *
 * Usage (already wired in auth-layout.tsx):
 *   <KeyboardShortcuts />
 *
 * Other components can check whether the user has ever used a shortcut via:
 *   localStorage.getItem("raf_kb_used") === "1"
 */

import { useEffect, useState, useRef, CSSProperties } from "react";
import { useRouter } from "next/navigation";
import { X, Keyboard } from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Shortcut {
  key: string;       // e.g. "g h"
  description: string;
  action: () => void;
}

// localStorage flag set once the user fires any shortcut
const KB_USED_KEY = "raf_kb_used";

export function markKeyboardShortcutUsed() {
  try {
    const alreadySet = localStorage.getItem(KB_USED_KEY) === "1";
    localStorage.setItem(KB_USED_KEY, "1");
    if (!alreadySet) {
      // Notify same-tab listeners (e.g. Sidebar) immediately
      window.dispatchEvent(new CustomEvent("raf-kb-used"));
    }
  } catch {
    // ignore
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
// Design tokens (matching CommandPalette / Sidebar dark-first palette)
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
  // Stores the first key of a pending sequence, e.g. "g"
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const pendingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const SHORTCUTS: Shortcut[] = [
    { key: "g h", description: "Go to Dashboard",       action: () => router.push("/") },
    { key: "g p", description: "Go to Patients",        action: () => router.push("/patients") },
    { key: "g a", description: "Go to Clinical Analysis", action: () => router.push("/analysis") },
    { key: "g s", description: "Go to Review Queue",    action: () => router.push("/suspects") },
    { key: "g r", description: "Go to Analytics",       action: () => router.push("/reports") },
    { key: "g e", description: "Go to EMR Config",      action: () => router.push("/emr-config") },
    { key: "?",   description: "Show keyboard shortcuts", action: () => setShowHelp(true) },
  ];

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // Never fire when typing in a focusable input element
      const tag = (e.target as HTMLElement).tagName;
      const isEditable = (e.target as HTMLElement).isContentEditable;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || isEditable) return;

      // Ignore modifier-key combos (e.g. Cmd+K is handled elsewhere)
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      const key = e.key;

      setPendingKey((currentPendingKey) => {
        if (currentPendingKey) {
          // We have a first key — check if "pendingKey + ' ' + key" matches a shortcut
          const sequence = `${currentPendingKey} ${key}`;
          const match = SHORTCUTS.find((s) => s.key === sequence);
          if (pendingTimerRef.current) clearTimeout(pendingTimerRef.current);

          if (match) {
            e.preventDefault();
            markKeyboardShortcutUsed();
            match.action();
          }
          return null;
        }

        // Single-key shortcut (e.g. "?")
        const singleMatch = SHORTCUTS.find(
          (s) => s.key === key && !s.key.includes(" ")
        );
        if (singleMatch) {
          e.preventDefault();
          markKeyboardShortcutUsed();
          singleMatch.action();
          return null;
        }

        // Check if this key is a valid first key of any sequence shortcut
        const isSequenceStart = SHORTCUTS.some(
          (s) => s.key.includes(" ") && s.key.split(" ")[0] === key
        );
        if (isSequenceStart) {
          // Clear pending state after 500 ms if no second key arrives
          if (pendingTimerRef.current) clearTimeout(pendingTimerRef.current);
          pendingTimerRef.current = setTimeout(() => setPendingKey(null), 500);
          return key;
        }

        return null;
      });
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  });

  // Close modal on Escape
  useEffect(() => {
    if (!showHelp) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") setShowHelp(false);
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [showHelp]);

  if (!showHelp) return null;

  return (
    <div
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
          maxWidth: 520,
          backgroundColor: BG_MODAL,
          border: `1px solid ${BORDER}`,
          borderRadius: 14,
          overflow: "hidden",
          boxShadow: "0 25px 60px rgba(0,0,0,0.6)",
          fontFamily:
            '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "16px 20px",
            borderBottom: `1px solid ${BORDER}`,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <Keyboard style={{ width: 18, height: 18, color: ACCENT }} aria-hidden />
            <span
              style={{ fontSize: 15, fontWeight: 600, color: TEXT_PRIMARY }}
            >
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

        {/* Shortcut grid */}
        <div style={{ padding: "16px 20px 20px" }}>
          {/* Navigation section */}
          <SectionHeading label="Navigation" />
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "4px 16px" }}>
            {SHORTCUTS.filter((s) => s.key !== "?").map((s) => (
              <ShortcutRow key={s.key} shortcut={s} />
            ))}
          </div>

          {/* General section */}
          <SectionHeading label="General" style={{ marginTop: 20 }} />
          <div>
            {SHORTCUTS.filter((s) => s.key === "?").map((s) => (
              <ShortcutRow key={s.key} shortcut={s} />
            ))}
            <ShortcutRow
              shortcut={{ key: "⌘ K", description: "Open command palette", action: () => {} }}
            />
            <ShortcutRow
              shortcut={{ key: "Esc", description: "Close modals / dialogs", action: () => {} }}
            />
          </div>
        </div>

        {/* Footer */}
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

function SectionHeading({
  label,
  style,
}: {
  label: string;
  style?: CSSProperties;
}) {
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

function ShortcutRow({ shortcut }: { shortcut: Omit<Shortcut, "action"> & { action?: () => void } }) {
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
