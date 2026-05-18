"use client";

import React from "react";

// Usage:
// import { EmptyState } from "@/components/ui/empty-state";
// <EmptyState icon={<Search size={24} />} title="No results" description="Try adjusting your filters." />

export interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
}

export function EmptyState({ icon, title, description }: EmptyStateProps) {
  return (
    <div
      className="animate-fade-in flex flex-col items-center justify-center px-6 py-12 text-center border-2 border-dashed border-border rounded-2xl"
      role="status"
    >
      {icon && (
        <div className="animate-gentle-bounce w-14 h-14 rounded-2xl bg-muted flex items-center justify-center text-muted-foreground mb-4">
          {icon}
        </div>
      )}
      <h4 className="m-0 text-[15px] font-semibold text-foreground">{title}</h4>
      {description && (
        <p className="mt-2 text-[13px] text-muted-foreground max-w-[320px] leading-relaxed">
          {description}
        </p>
      )}
    </div>
  );
}
