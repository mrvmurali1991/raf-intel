"use client";

/**
 * HelpPanel — contextual help drawer that slides in from the right.
 *
 * Usage:
 *   import { HelpPanel } from "@/components/HelpPanel";
 *   <HelpPanel open={open} onClose={() => setOpen(false)} help={help} />
 *
 * The companion HelpButton renders the `?` icon and wires open/close state.
 *
 *   import { HelpButton } from "@/components/HelpPanel";
 *   <HelpButton />  // resolves help content from usePathname() automatically
 *
 * Keyboard: pressing `?` on any page fires the "raf-open-help-panel" window
 * event; HelpButton listens for it so the panel opens without prop threading.
 */

import { useState, useEffect, useRef } from "react";
import { usePathname } from "next/navigation";
import { HelpCircle, X, BookOpen, ChevronDown } from "lucide-react";
import { getPageHelp, type PageHelp, type HelpSection } from "@/data/page-help";

// ---------------------------------------------------------------------------
// HelpPanel
// ---------------------------------------------------------------------------

interface HelpPanelProps {
  open: boolean;
  onClose: () => void;
  help: PageHelp;
}

export function HelpPanel({ open, onClose, help }: HelpPanelProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  // Close on Escape
  useEffect(() => {
    if (!open) return;
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKey);
    panelRef.current?.focus();
    return () => document.removeEventListener("keydown", handleKey);
  }, [open, onClose]);

  // Lock body scroll while open
  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => { document.body.style.overflow = ""; };
  }, [open]);

  if (!open) return null;

  return (
    <>
      {/* Backdrop */}
      <div
        aria-hidden="true"
        data-testid="help-panel-backdrop"
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          zIndex: 9990,
          background: "rgba(0,0,0,0.35)",
          backdropFilter: "blur(2px)",
        }}
      />

      {/* Drawer */}
      <div
        ref={panelRef}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={`Help: ${help.title}`}
        data-testid="help-panel"
        style={{
          position: "fixed",
          top: 0,
          right: 0,
          bottom: 0,
          zIndex: 9991,
          width: "min(480px, 95vw)",
          background: "#fff",
          boxShadow: "-4px 0 32px rgba(0,0,0,0.18)",
          display: "flex",
          flexDirection: "column",
          outline: "none",
          animation: "helpPanelSlideIn 0.22s cubic-bezier(0.16,1,0.3,1)",
        }}
      >
        <style>{`
          @keyframes helpPanelSlideIn {
            from { transform: translateX(100%); opacity: 0; }
            to   { transform: translateX(0);    opacity: 1; }
          }
          .help-section-item {
            border-radius: 10px;
            border: 1px solid #E2E8F0;
            overflow: hidden;
            margin-bottom: 10px;
          }
          .help-section-item > summary {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 16px;
            font-size: 13px;
            font-weight: 600;
            color: #1E293B;
            background: #F8FAFC;
            cursor: pointer;
            list-style: none;
            gap: 8px;
          }
          .help-section-item > summary::-webkit-details-marker { display: none; }
          .help-section-item > summary:hover { background: #F1F5F9; }
          .help-section-item > summary:focus-visible { outline: 2px solid #2563EB; outline-offset: -2px; }
          .help-section-content {
            padding: 14px 16px;
            font-size: 13px;
            color: #475569;
            border-top: 1px solid #E2E8F0;
            background: #fff;
            white-space: pre-line;
            line-height: 1.7;
          }
        `}</style>

        {/* Header */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "18px 20px 14px",
            borderBottom: "1px solid #E2E8F0",
            flexShrink: 0,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span
              aria-hidden="true"
              style={{
                width: 32,
                height: 32,
                borderRadius: 8,
                background: "linear-gradient(135deg,#2563EB,#7C3AED)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              <BookOpen size={16} color="#fff" />
            </span>
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, color: "#0F172A", lineHeight: 1.2 }}>
                {help.title}
              </div>
              <div style={{ fontSize: 11, color: "#94A3B8", marginTop: 1 }}>Page Guide</div>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close help panel"
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: 6,
              borderRadius: 6,
              color: "#64748B",
              display: "flex",
              alignItems: "center",
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Purpose banner */}
        <div
          style={{
            padding: "14px 20px",
            background: "linear-gradient(135deg,rgba(37,99,235,0.06),rgba(124,58,237,0.06))",
            borderBottom: "1px solid #E2E8F0",
            fontSize: 13,
            color: "#1E293B",
            lineHeight: 1.6,
            flexShrink: 0,
          }}
        >
          {help.purpose}
        </div>

        {/* Sections — scrollable */}
        <div
          style={{ overflowY: "auto", flex: 1, padding: "16px 20px 24px" }}
          role="list"
          aria-label="Help sections"
        >
          {help.sections.map((section) => (
            <SectionAccordion key={section.heading} section={section} />
          ))}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: "10px 20px",
            borderTop: "1px solid #E2E8F0",
            fontSize: 11,
            color: "#94A3B8",
            flexShrink: 0,
          }}
        >
          Press{" "}
          <kbd
            style={{
              background: "#F1F5F9",
              border: "1px solid #E2E8F0",
              borderRadius: 3,
              padding: "1px 5px",
              fontSize: 11,
              fontWeight: 600,
              color: "#475569",
            }}
          >
            ?
          </kbd>{" "}
          to open &middot;{" "}
          <kbd
            style={{
              background: "#F1F5F9",
              border: "1px solid #E2E8F0",
              borderRadius: 3,
              padding: "1px 5px",
              fontSize: 11,
              fontWeight: 600,
              color: "#475569",
            }}
          >
            Esc
          </kbd>{" "}
          to close
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// SectionAccordion
// ---------------------------------------------------------------------------

function SectionAccordion({ section }: { section: HelpSection }) {
  return (
    <details className="help-section-item" open>
      <summary>
        <span>{section.heading}</span>
        <ChevronDown size={14} style={{ flexShrink: 0, opacity: 0.5 }} aria-hidden="true" />
      </summary>
      <div className="help-section-content">{section.body}</div>
    </details>
  );
}

// ---------------------------------------------------------------------------
// openHelpPanel — event-based imperative trigger (used by keyboard shortcut)
// ---------------------------------------------------------------------------

/** Fire this to open the help panel for the currently active HelpButton. */
export function openHelpPanel(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("raf-open-help-panel"));
  }
}

// ---------------------------------------------------------------------------
// HelpButton — `?` icon that opens the panel; reads route from usePathname()
// ---------------------------------------------------------------------------

interface HelpButtonProps {
  /** Override the route key (e.g. for pages rendered under a dynamic segment). */
  routeOverride?: string;
  /** Extra class names applied to the button element. */
  className?: string;
}

export function HelpButton({ routeOverride, className }: HelpButtonProps) {
  const pathname = usePathname();
  const route = routeOverride ?? pathname ?? "/";
  const help = getPageHelp(route);
  const [open, setOpen] = useState(false);

  // Listen for the global keyboard-shortcut event
  useEffect(() => {
    const handler = () => setOpen(true);
    window.addEventListener("raf-open-help-panel", handler);
    return () => window.removeEventListener("raf-open-help-panel", handler);
  }, []);

  if (!help) return null;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        data-testid="help-button"
        data-route={route}
        aria-label={`Help: ${help.title}`}
        aria-haspopup="dialog"
        className={className}
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: 34,
          height: 34,
          borderRadius: 8,
          border: "1px solid #E2E8F0",
          background: "#fff",
          cursor: "pointer",
          color: "#64748B",
          flexShrink: 0,
          transition: "border-color 0.15s, color 0.15s, background 0.15s",
        }}
        onMouseEnter={(e) => {
          const btn = e.currentTarget;
          btn.style.borderColor = "#2563EB";
          btn.style.color = "#2563EB";
          btn.style.background = "#EFF6FF";
        }}
        onMouseLeave={(e) => {
          const btn = e.currentTarget;
          btn.style.borderColor = "#E2E8F0";
          btn.style.color = "#64748B";
          btn.style.background = "#fff";
        }}
      >
        <HelpCircle size={17} aria-hidden="true" />
        <span className="sr-only">Help</span>
      </button>

      <HelpPanel open={open} onClose={() => setOpen(false)} help={help} />
    </>
  );
}
