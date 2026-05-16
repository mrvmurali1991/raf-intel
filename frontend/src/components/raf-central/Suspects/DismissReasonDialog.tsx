"use client";

import { useEffect, useRef, useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { DISMISS_REASONS, type DismissReasonCode } from "../_shared";

interface DismissReasonDialogProps {
  open: boolean;
  suspectLabel: string;
  onCancel: () => void;
  onSubmit: (reason: string) => void;
}

function DismissReasonDialogInner({ suspectLabel, onCancel, onSubmit }: Omit<DismissReasonDialogProps, "open">) {
  // Default to NO selection so an accidental Enter-press cannot auto-dismiss
  // a valid suspect with the most destructive reason ("not clinically
  // supported"). Submit stays disabled until the clinician makes a positive
  // choice — UX/accessibility review #7 + patient-safety review #5.
  const [selected, setSelected] = useState<DismissReasonCode | null>(null);
  const [otherText, setOtherText] = useState("");
  const otherTextareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (selected === "other") {
      requestAnimationFrame(() => otherTextareaRef.current?.focus());
    }
  }, [selected]);

  const isValid = selected !== null && (selected !== "other" || otherText.trim().length > 0);

  const handleSubmit = () => {
    if (!isValid || selected === null) return;
    const reason =
      selected === "other"
        ? `other: ${otherText.trim()}`
        : `${selected}: ${DISMISS_REASONS[selected]}`;
    onSubmit(reason);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <DialogContent showCloseButton={false} className="sm:max-w-sm" onKeyDown={handleKeyDown}>
      <DialogHeader>
        <DialogTitle>Dismiss reason</DialogTitle>
      </DialogHeader>
      <div className="space-y-3 py-1">
        <p className="text-xs text-muted-foreground line-clamp-1">{suspectLabel}</p>
        <fieldset className="space-y-2">
          <legend className="sr-only">Select a dismiss reason</legend>
          {(Object.entries(DISMISS_REASONS) as [DismissReasonCode, string][]).map(([code, label]) => (
            <label
              key={code}
              className={cn(
                "flex items-center gap-2.5 rounded-md border px-3 py-2 text-sm cursor-pointer transition-colors",
                selected === code
                  ? "border-primary bg-primary/5"
                  : "border-border hover:bg-muted/50"
              )}
            >
              <input
                type="radio"
                name="dismiss-reason"
                value={code}
                checked={selected === code}
                onChange={() => setSelected(code as DismissReasonCode)}
                className="accent-primary"
              />
              {label}
            </label>
          ))}
        </fieldset>
        {selected === "other" && (
          <textarea
            ref={otherTextareaRef}
            value={otherText}
            onChange={(e) => setOtherText(e.target.value)}
            placeholder="Describe the reason..."
            rows={3}
            className="w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label="Other dismiss reason"
          />
        )}
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button variant="destructive" onClick={handleSubmit} disabled={!isValid}>
          Dismiss suspect
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

export function DismissReasonDialog({ open, suspectLabel, onCancel, onSubmit }: DismissReasonDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onCancel(); }}>
      {/* Remount inner component on each open to reset radio/text state cleanly */}
      {open && (
        <DismissReasonDialogInner
          suspectLabel={suspectLabel}
          onCancel={onCancel}
          onSubmit={onSubmit}
        />
      )}
    </Dialog>
  );
}
