"use client";

/**
 * AppDialog & ConfirmDialog
 * ─────────────────────────
 * AppDialog wraps the existing shadcn/base-ui Dialog primitives with:
 *   - Consistent 24 px padding
 *   - Four max-width tiers: sm (400), md (560), lg (720), xl (960)
 *   - Sticky header (title + optional description + close button)
 *   - Independently scrollable content area
 *   - Muted footer rail with cancel/confirm slot
 *   - Backdrop blur on the overlay
 *   - Escape-to-close and body-scroll-lock (handled by base-ui DialogPrimitive)
 *
 * ConfirmDialog is a thin shortcut built on AppDialog for the common
 * "are you sure?" pattern — including a loading state on the confirm button.
 *
 * Usage – AppDialog:
 * ──────────────────
 *   <AppDialog
 *     open={open}
 *     onClose={() => setOpen(false)}
 *     title="Edit patient"
 *     description="Changes are saved immediately."
 *     size="md"
 *     footer={
 *       <>
 *         <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
 *         <Button onClick={handleSave}>Save</Button>
 *       </>
 *     }
 *   >
 *     <PatientForm />
 *   </AppDialog>
 *
 * Usage – ConfirmDialog:
 * ──────────────────────
 *   <ConfirmDialog
 *     open={open}
 *     onClose={() => setOpen(false)}
 *     onConfirm={handleDelete}
 *     title="Delete campaign"
 *     message="This action cannot be undone."
 *     confirmLabel="Delete"
 *     destructive
 *     loading={deleting}
 *   />
 */

import React, { useCallback, useEffect } from "react";
import { XIcon, Loader2Icon } from "lucide-react";
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

// ─── Size map ────────────────────────────────────────────────────────────────

const SIZE_CLASSES = {
  sm: "max-w-[400px]",
  md: "max-w-[560px]",
  lg: "max-w-[720px]",
  xl: "max-w-[960px]",
} as const;

// ─── AppDialog ───────────────────────────────────────────────────────────────

export interface AppDialogProps {
  /** Whether the dialog is visible. */
  open: boolean;
  /** Called when the dialog requests to close (Escape, backdrop click, or X). */
  onClose: () => void;
  /** Bold title rendered in the sticky header. */
  title: string;
  /** Optional muted subtitle rendered below the title. */
  description?: string;
  /** Controls the maximum width of the dialog panel. Defaults to "md". */
  size?: keyof typeof SIZE_CLASSES;
  /** Scrollable body content. */
  children: React.ReactNode;
  /**
   * Optional footer content. Render your own <Button> elements here.
   * When omitted, the footer rail is not rendered at all.
   */
  footer?: React.ReactNode;
  /**
   * When true, styles any "confirm" Button in the footer with the destructive
   * colour. You must still pass the destructive prop to your own buttons —
   * this flag exists primarily so consumers can derive styling from a single
   * prop at call-site without threading it into a custom footer.
   *
   * Used directly by ConfirmDialog.
   */
  destructive?: boolean;
}

export function AppDialog({
  open,
  onClose,
  title,
  description,
  size = "md",
  children,
  footer,
}: AppDialogProps) {
  // base-ui DialogPrimitive.Root manages Escape and aria-modal.
  // We forward the open/close state via onOpenChange.
  const handleOpenChange = useCallback(
    (isOpen: boolean) => {
      if (!isOpen) onClose();
    },
    [onClose],
  );

  // Prevent body scroll while dialog is open. base-ui does NOT automatically
  // lock scroll on Popup (unlike Radix), so we add our own lock.
  useEffect(() => {
    if (!open) return;
    const original = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = original;
    };
  }, [open]);

  return (
    <DialogPrimitive.Root open={open} onOpenChange={handleOpenChange}>
      <DialogPrimitive.Portal>
        {/* ── Backdrop ─────────────────────────────────────────────────────── */}
        <DialogPrimitive.Backdrop
          className={cn(
            "fixed inset-0 isolate z-50 bg-black/60 backdrop-blur-sm",
            "duration-150 data-open:animate-in data-open:fade-in-0",
            "data-closed:animate-out data-closed:fade-out-0",
          )}
        />

        {/* ── Panel ────────────────────────────────────────────────────────── */}
        <DialogPrimitive.Popup
          className={cn(
            // Positioning
            "fixed top-1/2 left-1/2 z-50 -translate-x-1/2 -translate-y-1/2",
            // Sizing — full-width on mobile, capped on larger screens
            "w-[calc(100%-2rem)]",
            SIZE_CLASSES[size],
            // Structure
            "flex max-h-[min(90dvh,800px)] flex-col",
            "overflow-hidden rounded-2xl",
            // Surface
            "bg-popover text-popover-foreground",
            "ring-1 ring-foreground/10 shadow-2xl",
            // Animation
            "duration-150 outline-none",
            "data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95",
            "data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95",
          )}
          // Allows clicking the backdrop to close via the root onOpenChange
          aria-labelledby="app-dialog-title"
          aria-describedby={description ? "app-dialog-description" : undefined}
        >
          {/* ── Header ───────────────────────────────────────────────────── */}
          <header className="flex shrink-0 items-start justify-between gap-4 border-b border-border px-6 py-5">
            <div className="flex flex-col gap-1">
              <DialogPrimitive.Title
                id="app-dialog-title"
                className="font-heading text-base font-semibold leading-snug text-foreground"
              >
                {title}
              </DialogPrimitive.Title>
              {description && (
                <DialogPrimitive.Description
                  id="app-dialog-description"
                  className="text-sm text-muted-foreground"
                >
                  {description}
                </DialogPrimitive.Description>
              )}
            </div>

            {/* Close button */}
            <DialogPrimitive.Close
              render={
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="Close dialog"
                  className="shrink-0 -mt-0.5"
                />
              }
            >
              <XIcon className="size-4" />
            </DialogPrimitive.Close>
          </header>

          {/* ── Scrollable body ──────────────────────────────────────────── */}
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-6 py-6">
            {children}
          </div>

          {/* ── Footer (only rendered when the caller provides content) ──── */}
          {footer && (
            <footer
              className={cn(
                "flex shrink-0 flex-col-reverse items-center gap-2",
                "border-t border-border bg-muted/40 px-6 py-4",
                "sm:flex-row sm:justify-end",
              )}
            >
              {footer}
            </footer>
          )}
        </DialogPrimitive.Popup>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

// ─── ConfirmDialog ───────────────────────────────────────────────────────────

export interface ConfirmDialogProps {
  /** Whether the dialog is visible. */
  open: boolean;
  /** Called when the user cancels or closes the dialog. */
  onClose: () => void;
  /** Called when the user clicks the confirm button. Does NOT auto-close — caller is responsible. */
  onConfirm: () => void;
  /** Bold title rendered in the header. */
  title: string;
  /** Body message. Accepts a string or any React node for rich copy. */
  message: React.ReactNode;
  /** Label for the confirm button. Defaults to "Confirm". */
  confirmLabel?: string;
  /** Label for the cancel button. Defaults to "Cancel". */
  cancelLabel?: string;
  /** When true, the confirm button uses red/destructive styling. */
  destructive?: boolean;
  /** When true, the confirm button shows a spinner and is disabled. */
  loading?: boolean;
}

export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  destructive = false,
  loading = false,
}: ConfirmDialogProps) {
  return (
    <AppDialog
      open={open}
      onClose={onClose}
      title={title}
      size="sm"
      destructive={destructive}
      footer={
        <>
          {/* Cancel is autoFocused so Enter cannot accidentally fire the
              destructive action. */}
          <Button
            variant="outline"
            onClick={onClose}
            disabled={loading}
            autoFocus
            aria-label={`${cancelLabel} and close dialog`}
          >
            {cancelLabel}
          </Button>

          <Button
            variant={destructive ? "destructive" : "default"}
            onClick={onConfirm}
            disabled={loading}
            aria-busy={loading}
            className={cn(
              destructive &&
                "bg-red-600 text-white hover:bg-red-700 dark:bg-red-600 dark:hover:bg-red-700",
            )}
          >
            {loading && (
              <Loader2Icon
                className="size-3.5 animate-spin"
                aria-hidden="true"
              />
            )}
            {loading ? "Please wait…" : confirmLabel}
          </Button>
        </>
      }
    >
      {/* Message body */}
      <div
        id="confirm-dialog-description"
        className="text-sm text-muted-foreground"
        role="note"
      >
        {message}
      </div>
    </AppDialog>
  );
}

export default AppDialog;
