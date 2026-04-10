"use client";

/**
 * SessionTimeoutWarning
 *
 * Tracks user activity independently of the auth-context idle timer.
 * After 12 minutes of inactivity (3 min before the 15-min token expiry)
 * it renders a modal with a live countdown.  The user can either
 * "Stay Logged In" (calls refreshToken) or "Log Out".  If the countdown
 * reaches zero the component calls logout automatically.
 *
 * Activity events are throttled to fire at most once every 10 seconds so
 * we never saturate the event loop on heavy-mouse pages.
 *
 * Usage:
 *   <SessionTimeoutWarning />   // mount inside the authenticated shell
 */

import {
  useEffect,
  useRef,
  useState,
  useCallback,
  useId,
} from "react";
import { useAuth } from "@/contexts/auth-context";

// ---------------------------------------------------------------------------
// Timing constants
// ---------------------------------------------------------------------------

/** Show the warning this many ms after the last activity event. */
const WARN_AFTER_MS = 12 * 60 * 1_000; // 12 minutes

/** How long the countdown runs before auto-logout (must equal 15min - WARN_AFTER_MS). */
const COUNTDOWN_MS = 3 * 60 * 1_000; // 3 minutes

/** Minimum gap between activity-reset calls (throttle). */
const THROTTLE_MS = 10_000; // 10 seconds

// ---------------------------------------------------------------------------
// Design tokens — match the dark-glass aesthetic used in WelcomeWizard
// ---------------------------------------------------------------------------

const BG_OVERLAY = "rgba(0,0,0,0.55)";
const BG_MODAL = "#111827"; // slate-900
const BORDER = "rgba(255,255,255,0.08)";
const TEXT_PRIMARY = "#F9FAFB";
const TEXT_SUBTLE = "#9CA3AF";
const ACCENT = "#3B82F6"; // blue-500
const ACCENT_HOVER = "#2563EB"; // blue-600
const DANGER = "#EF4444"; // red-500
const DANGER_HOVER = "#DC2626"; // red-600
const FONT_STACK =
  '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatCountdown(ms: number): string {
  const totalSec = Math.max(0, Math.ceil(ms / 1_000));
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function SessionTimeoutWarning() {
  const { refreshToken, logout, isAuthenticated } = useAuth();

  const [showModal, setShowModal] = useState(false);
  const [remainingMs, setRemainingMs] = useState(COUNTDOWN_MS);
  const [stayLoading, setStayLoading] = useState(false);

  // Timestamp of the last recorded activity
  const lastActivityRef = useRef(Date.now());
  // The last time we actually ran the throttled reset
  const lastThrottleRef = useRef(Date.now());
  // Whether we are currently showing the modal (avoids stale closure in timers)
  const showModalRef = useRef(false);
  // Interval handle for the countdown ticker
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // When the warning started (used to compute remaining time precisely)
  const warnStartRef = useRef<number | null>(null);

  // Keep ref in sync with state
  useEffect(() => {
    showModalRef.current = showModal;
  }, [showModal]);

  // -------------------------------------------------------------------------
  // Countdown — starts when modal becomes visible, clears when it hides
  // -------------------------------------------------------------------------

  const startCountdown = useCallback(() => {
    if (countdownRef.current) clearInterval(countdownRef.current);
    warnStartRef.current = Date.now();
    setRemainingMs(COUNTDOWN_MS);

    countdownRef.current = setInterval(() => {
      const elapsed = Date.now() - (warnStartRef.current ?? Date.now());
      const left = COUNTDOWN_MS - elapsed;

      if (left <= 0) {
        // Time's up — auto-logout
        if (countdownRef.current) clearInterval(countdownRef.current);
        setShowModal(false);
        logout();
      } else {
        setRemainingMs(left);
      }
    }, 500);
  }, [logout]);

  const stopCountdown = useCallback(() => {
    if (countdownRef.current) {
      clearInterval(countdownRef.current);
      countdownRef.current = null;
    }
    warnStartRef.current = null;
  }, []);

  // -------------------------------------------------------------------------
  // Activity tracking + idle-check interval
  // -------------------------------------------------------------------------

  useEffect(() => {
    if (!isAuthenticated) return;

    const ACTIVITY_EVENTS = ["mousemove", "mousedown", "keydown", "touchstart", "scroll"] as const;

    const resetActivity = () => {
      const now = Date.now();
      // Throttle: only update lastActivityRef at most once per THROTTLE_MS
      if (now - lastThrottleRef.current >= THROTTLE_MS) {
        lastActivityRef.current = now;
        lastThrottleRef.current = now;
        // If modal is showing and user moved, dismiss it gracefully
        // (they'll get a fresh 12 min window — no need to call refreshToken here;
        //  the auth-context's own 401 interceptor handles silent refresh)
        if (showModalRef.current) {
          stopCountdown();
          setShowModal(false);
        }
      }
    };

    ACTIVITY_EVENTS.forEach((e) =>
      window.addEventListener(e, resetActivity, { passive: true })
    );

    // Poll every 30 s to check whether 12 min of inactivity has passed
    const idleCheck = setInterval(() => {
      if (showModalRef.current) return; // already showing — let countdown handle it
      if (Date.now() - lastActivityRef.current >= WARN_AFTER_MS) {
        setShowModal(true);
        startCountdown();
      }
    }, 30_000);

    return () => {
      ACTIVITY_EVENTS.forEach((e) => window.removeEventListener(e, resetActivity));
      clearInterval(idleCheck);
      stopCountdown();
    };
  }, [isAuthenticated, startCountdown, stopCountdown]);

  // Cleanup countdown on unmount
  useEffect(() => () => stopCountdown(), [stopCountdown]);

  // -------------------------------------------------------------------------
  // Focus trap
  // -------------------------------------------------------------------------

  const modalRef = useRef<HTMLDivElement>(null);
  const firstFocusRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!showModal) return;

    // Focus the primary action button when the modal opens
    firstFocusRef.current?.focus();

    const trapFocus = (e: KeyboardEvent) => {
      if (e.key !== "Tab" || !modalRef.current) return;
      const focusable = modalRef.current.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };

    document.addEventListener("keydown", trapFocus);
    return () => document.removeEventListener("keydown", trapFocus);
  }, [showModal]);

  // -------------------------------------------------------------------------
  // Action handlers
  // -------------------------------------------------------------------------

  const handleStayLoggedIn = useCallback(async () => {
    setStayLoading(true);
    try {
      await refreshToken();
      // Reset our own idle clock so the 12-min window restarts cleanly
      lastActivityRef.current = Date.now();
      lastThrottleRef.current = Date.now();
    } catch {
      // If refresh fails the 401 interceptor will handle logout — just close
    } finally {
      stopCountdown();
      setShowModal(false);
      setStayLoading(false);
    }
  }, [refreshToken, stopCountdown]);

  const handleLogOut = useCallback(async () => {
    stopCountdown();
    setShowModal(false);
    await logout();
  }, [logout, stopCountdown]);

  // -------------------------------------------------------------------------
  // IDs for aria relationships
  // -------------------------------------------------------------------------

  const titleId = useId();
  const descId = useId();

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  if (!showModal) return null;

  const countdownLabel = formatCountdown(remainingMs);
  const isUrgent = remainingMs <= 60_000; // last 60 s — turn countdown red

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: BG_OVERLAY,
        backdropFilter: "blur(6px)",
        padding: 16,
        fontFamily: FONT_STACK,
      }}
      // Clicking the overlay does nothing intentionally — user must choose
      aria-hidden="false"
    >
      <div
        ref={modalRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descId}
        style={{
          width: "100%",
          maxWidth: 420,
          backgroundColor: BG_MODAL,
          border: `1px solid ${BORDER}`,
          borderRadius: 16,
          overflow: "hidden",
          boxShadow: "0 30px 70px rgba(0,0,0,0.6)",
          outline: "none",
        }}
        tabIndex={-1}
      >
        {/* ---------------------------------------------------------------- */}
        {/* Header                                                            */}
        {/* ---------------------------------------------------------------- */}
        <div
          style={{
            padding: "24px 24px 0",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            textAlign: "center",
            gap: 12,
          }}
        >
          {/* Icon */}
          <div
            aria-hidden="true"
            style={{
              width: 56,
              height: 56,
              borderRadius: "50%",
              backgroundColor: "rgba(234,179,8,0.12)",
              border: "1px solid rgba(234,179,8,0.25)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 26,
            }}
          >
            {/* Clock emoji — purely decorative */}
            &#9200;
          </div>

          <h2
            id={titleId}
            style={{
              margin: 0,
              fontSize: 18,
              fontWeight: 600,
              color: TEXT_PRIMARY,
              letterSpacing: "-0.01em",
            }}
          >
            Your session is about to expire
          </h2>
        </div>

        {/* ---------------------------------------------------------------- */}
        {/* Body                                                              */}
        {/* ---------------------------------------------------------------- */}
        <div
          id={descId}
          style={{
            padding: "16px 24px 24px",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 20,
            textAlign: "center",
          }}
        >
          <p
            style={{
              margin: 0,
              fontSize: 14,
              color: TEXT_SUBTLE,
              lineHeight: 1.6,
            }}
          >
            You have been inactive for a while. For your security, you will be
            logged out automatically.
          </p>

          {/* Countdown */}
          <div
            aria-live="polite"
            aria-atomic="true"
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 4,
            }}
          >
            <span
              style={{
                fontSize: 13,
                color: TEXT_SUBTLE,
                textTransform: "uppercase",
                letterSpacing: "0.08em",
              }}
            >
              Logging out in
            </span>
            <span
              style={{
                fontSize: 44,
                fontWeight: 700,
                fontVariantNumeric: "tabular-nums",
                letterSpacing: "-0.02em",
                color: isUrgent ? DANGER : TEXT_PRIMARY,
                transition: "color 0.3s",
                // Screen readers will read the live region text naturally;
                // we use aria-label on this span so VoiceOver reads it once
                // rather than letter by letter.
              }}
              aria-label={`${countdownLabel} remaining`}
            >
              {countdownLabel}
            </span>
          </div>

          {/* Action buttons */}
          <div
            style={{
              display: "flex",
              gap: 12,
              width: "100%",
            }}
          >
            <button
              ref={firstFocusRef}
              onClick={handleStayLoggedIn}
              disabled={stayLoading}
              style={{
                flex: 1,
                padding: "10px 0",
                borderRadius: 8,
                border: "none",
                cursor: stayLoading ? "not-allowed" : "pointer",
                fontSize: 14,
                fontWeight: 600,
                fontFamily: FONT_STACK,
                backgroundColor: stayLoading ? ACCENT_HOVER : ACCENT,
                color: "#fff",
                opacity: stayLoading ? 0.75 : 1,
                transition: "background-color 0.15s, opacity 0.15s",
              }}
              onMouseEnter={(e) => {
                if (!stayLoading)
                  (e.currentTarget as HTMLButtonElement).style.backgroundColor = ACCENT_HOVER;
              }}
              onMouseLeave={(e) => {
                if (!stayLoading)
                  (e.currentTarget as HTMLButtonElement).style.backgroundColor = ACCENT;
              }}
              aria-label="Stay logged in and refresh session"
            >
              {stayLoading ? "Refreshing…" : "Stay Logged In"}
            </button>

            <button
              onClick={handleLogOut}
              disabled={stayLoading}
              style={{
                flex: 1,
                padding: "10px 0",
                borderRadius: 8,
                border: `1px solid rgba(239,68,68,0.35)`,
                cursor: stayLoading ? "not-allowed" : "pointer",
                fontSize: 14,
                fontWeight: 600,
                fontFamily: FONT_STACK,
                backgroundColor: "transparent",
                color: DANGER,
                opacity: stayLoading ? 0.5 : 1,
                transition: "background-color 0.15s, opacity 0.15s",
              }}
              onMouseEnter={(e) => {
                if (!stayLoading) {
                  const btn = e.currentTarget as HTMLButtonElement;
                  btn.style.backgroundColor = "rgba(239,68,68,0.1)";
                  btn.style.color = DANGER_HOVER;
                }
              }}
              onMouseLeave={(e) => {
                if (!stayLoading) {
                  const btn = e.currentTarget as HTMLButtonElement;
                  btn.style.backgroundColor = "transparent";
                  btn.style.color = DANGER;
                }
              }}
              aria-label="Log out now"
            >
              Log Out
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
