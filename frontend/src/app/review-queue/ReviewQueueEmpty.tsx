"use client";

import { ClipboardList } from "lucide-react";

export function ReviewQueueEmpty() {
  return (
    <div
      className="flex flex-col items-center justify-center py-16 px-6 text-center"
      role="status"
    >
      <div className="w-14 h-14 rounded-xl bg-muted flex items-center justify-center mb-4 text-muted-foreground">
        <ClipboardList size={28} aria-hidden="true" />
      </div>
      <h3 className="text-[15px] font-semibold text-foreground mb-1">
        No items pending review
      </h3>
      <p className="text-[13px] text-muted-foreground max-w-xs leading-relaxed">
        All candidates have been reviewed. Check back later or switch tabs to see other categories.
      </p>
    </div>
  );
}
