"use client";

/**
 * ConfirmDialog
 * -------------
 * Generic accessible confirmation dialog for destructive / irreversible
 * actions. Replaces native `window.confirm` which is unstyled, blocks the
 * main thread, and provides no aria semantics.
 *
 * The confirm button is NOT autofocused — focus lands on Cancel so users
 * cannot accidentally destroy data by hitting Enter.
 */

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description?: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** When true, the confirm button uses destructive styling. */
  destructive?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  destructive = false,
  onConfirm,
  onClose,
}: ConfirmDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onClose(); }}>
      {open && (
        <DialogContent
          className="sm:max-w-md"
          aria-describedby={description ? "confirm-dialog-desc" : undefined}
        >
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
          </DialogHeader>
          {description && (
            <div
              id="confirm-dialog-desc"
              className="text-sm text-muted-foreground py-1"
            >
              {description}
            </div>
          )}
          <DialogFooter>
            {/* Cancel is autoFocused so Enter cannot accidentally trigger
                the destructive action. */}
            <Button
              variant="outline"
              onClick={onClose}
              autoFocus
              aria-label={`${cancelLabel} and dismiss dialog`}
            >
              {cancelLabel}
            </Button>
            <Button
              variant={destructive ? "destructive" : "default"}
              onClick={() => {
                onConfirm();
                onClose();
              }}
              className={cn(
                destructive &&
                  "bg-red-600 hover:bg-red-700 text-white dark:bg-red-600 dark:hover:bg-red-700",
              )}
            >
              {confirmLabel}
            </Button>
          </DialogFooter>
        </DialogContent>
      )}
    </Dialog>
  );
}

export default ConfirmDialog;
