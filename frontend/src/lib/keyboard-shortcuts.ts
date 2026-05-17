/**
 * keyboard-shortcuts.ts — Shared registry + helpers for global shortcuts.
 *
 * The legacy single-component implementation lived in
 * components/KeyboardShortcuts.tsx and only handled the `g <letter>`
 * navigation prefix + the `?` help modal.  This module extends that with:
 *
 *   * An imperative event-bus for *context-sensitive* shortcuts that
 *     individual pages register (e.g. "A = accept the currently-focused
 *     suspect on the patient detail page").  Pages call
 *     `registerContextShortcut("accept-focused-suspect", handler)` on mount
 *     and `unregisterContextShortcut` on unmount.
 *
 *   * A canonical SHORTCUT_CATALOG describing every shortcut surfaced in
 *     the `?` help overlay — kept here so both the help modal and the
 *     dispatch logic agree on what exists.
 *
 *   * A focus helper for the patient-search input (`focusPatientSearch()`)
 *     used by the `/` shortcut.
 *
 * The actual key-event listener still lives in components/KeyboardShortcuts.tsx
 * because it needs Next.js's `useRouter()` for navigation.  That file imports
 * SHORTCUT_CATALOG + the dispatch helpers below.
 */

// ---------------------------------------------------------------------------
// Catalog
// ---------------------------------------------------------------------------

export type ShortcutCategory = "Navigation" | "Patient & Worklist" | "Review Actions" | "General";

export interface ShortcutDescriptor {
  /** Display key sequence, e.g. "g p", "A", "←". */
  key: string;
  /** Lowercased token used for keyboard matching — see KeyboardShortcuts.tsx. */
  match?: string;
  description: string;
  category: ShortcutCategory;
  /** When true, the shortcut is dispatched even when no specific handler is
   *  registered — typical for navigation routes which the listener handles
   *  itself via useRouter().  Context-sensitive shortcuts are false. */
  global?: boolean;
}

export const SHORTCUT_CATALOG: ShortcutDescriptor[] = [
  // Navigation
  { key: "g h", description: "Go to Dashboard",           category: "Navigation", global: true },
  { key: "g p", description: "Go to Patients",            category: "Navigation", global: true },
  { key: "g w", description: "Go to Today's worklist",    category: "Navigation", global: true },
  { key: "g a", description: "Go to Clinical Analysis",   category: "Navigation", global: true },
  { key: "g s", description: "Go to Review Queue",        category: "Navigation", global: true },
  { key: "g r", description: "Go to Analytics",           category: "Navigation", global: true },
  { key: "g e", description: "Go to EMR Config",          category: "Navigation", global: true },

  // Patient & worklist navigation
  { key: "/",  description: "Focus patient search",       category: "Patient & Worklist", global: true },
  { key: "←",  match: "ArrowLeft",  description: "Previous patient in worklist", category: "Patient & Worklist" },
  { key: "→",  match: "ArrowRight", description: "Next patient in worklist",     category: "Patient & Worklist" },

  // Review actions (handled by the open page via context handlers)
  { key: "A", description: "Accept focused suspect",          category: "Review Actions" },
  { key: "D", description: "Dismiss focused suspect",         category: "Review Actions" },
  { key: "R", description: "Mark MEAT Reviewed (focused HCC)", category: "Review Actions" },

  // General
  { key: "?",   description: "Show keyboard shortcuts", category: "General", global: true },
  { key: "⌘ K", description: "Open command palette",   category: "General" },
  { key: "Esc", description: "Close modals / dialogs", category: "General", global: true },
];

// ---------------------------------------------------------------------------
// Context shortcut registry
// ---------------------------------------------------------------------------
//
// Pages register handlers for a small set of well-known shortcut IDs.  The
// global key listener calls into the registry by ID — if no handler is
// registered, the key is a no-op.  Multiple handlers stack as a LIFO so the
// most recently-mounted page wins (typical for modals / drilldowns).

export type ShortcutId =
  | "accept-focused-suspect"
  | "dismiss-focused-suspect"
  | "mark-meat-reviewed"
  | "next-patient"
  | "prev-patient"
  | "close-dialog";

type Handler = () => void | Promise<void>;

const _stacks: Map<ShortcutId, Handler[]> = new Map();

export function registerContextShortcut(id: ShortcutId, handler: Handler): () => void {
  const stack = _stacks.get(id) ?? [];
  stack.push(handler);
  _stacks.set(id, stack);
  return () => unregisterContextShortcut(id, handler);
}

export function unregisterContextShortcut(id: ShortcutId, handler: Handler): void {
  const stack = _stacks.get(id);
  if (!stack) return;
  const idx = stack.lastIndexOf(handler);
  if (idx >= 0) stack.splice(idx, 1);
  if (stack.length === 0) _stacks.delete(id);
}

export function dispatchContextShortcut(id: ShortcutId): boolean {
  const stack = _stacks.get(id);
  if (!stack || stack.length === 0) return false;
  const top = stack[stack.length - 1];
  try {
    void top();
  } catch (err) {
    // Don't let a broken handler block other shortcuts.
    // eslint-disable-next-line no-console
    console.warn(`[keyboard-shortcuts] handler "${id}" threw:`, err);
  }
  return true;
}

// ---------------------------------------------------------------------------
// Patient search focus helper
// ---------------------------------------------------------------------------
//
// The sidebar exposes a search input that listens for `raf-open-patient-search`
// events; if no such input is mounted (e.g. on login) we fall back to focusing
// the first `[data-patient-search]` element on the page.

export function focusPatientSearch(): void {
  try {
    window.dispatchEvent(new CustomEvent("raf-open-patient-search"));
  } catch {
    // ignore
  }
  // Brief delay so the event has a chance to mount/expand any inline search.
  setTimeout(() => {
    const el = document.querySelector<HTMLInputElement>("[data-patient-search]");
    if (el && typeof el.focus === "function") {
      el.focus();
      try { el.select(); } catch { /* ignore */ }
    }
  }, 50);
}

// ---------------------------------------------------------------------------
// Esc helper — closes any open dialog and unfocuses input fields.
// ---------------------------------------------------------------------------

export function dispatchEscape(): void {
  // Let any context-registered close handler run first.
  const handled = dispatchContextShortcut("close-dialog");
  if (handled) return;

  // Otherwise blur the currently focused element so the user is no longer
  // typing into a form field.
  const active = document.activeElement as HTMLElement | null;
  if (active && typeof active.blur === "function") {
    active.blur();
  }
}
