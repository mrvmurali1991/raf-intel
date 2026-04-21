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

interface MEATAttestationDialogProps {
  open: boolean;
  hcc: string;
  label: string;
  missingLabel: string;
  placeholder?: string;
  onCancel: () => void;
  onSubmit: (note: string) => void;
}

function MEATAttestationDialogInner({
  hcc,
  label,
  missingLabel,
  placeholder,
  onCancel,
  onSubmit,
}: Omit<MEATAttestationDialogProps, "open">) {
  const [note, setNote] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Autofocus textarea on mount (this inner component is only mounted when open=true)
  useEffect(() => {
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      const trimmed = note.trim();
      if (trimmed) onSubmit(trimmed);
    }
  };

  const handleSubmit = () => {
    const trimmed = note.trim();
    if (trimmed) onSubmit(trimmed);
  };

  const defaultPlaceholder =
    placeholder ||
    `e.g., Patient on medication for HCC ${hcc}, condition monitored quarterly, no acute complications.`;

  return (
    <DialogContent showCloseButton={false} className="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>MEAT Attestation — HCC {hcc}</DialogTitle>
      </DialogHeader>
      <div className="space-y-2 py-1">
        <p className="text-xs text-muted-foreground">
          <span className="font-semibold">{label}</span>
          {missingLabel && (
            <> — missing: <span className="font-medium">{missingLabel}</span></>
          )}
        </p>
        <textarea
          ref={textareaRef}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={defaultPlaceholder}
          rows={4}
          className="w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Clinician attestation note"
        />
        <p className="text-[10px] text-muted-foreground">
          Cmd+Enter / Ctrl+Enter to submit. Already-documented MEAT letters will not be overwritten.
        </p>
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        <Button onClick={handleSubmit} disabled={!note.trim()}>
          Submit attestation
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

export function MEATAttestationDialog({
  open,
  hcc,
  label,
  missingLabel,
  placeholder,
  onCancel,
  onSubmit,
}: MEATAttestationDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) onCancel(); }}>
      {/* Remount inner component on each open to reset note state cleanly */}
      {open && (
        <MEATAttestationDialogInner
          hcc={hcc}
          label={label}
          missingLabel={missingLabel}
          placeholder={placeholder}
          onCancel={onCancel}
          onSubmit={onSubmit}
        />
      )}
    </Dialog>
  );
}
