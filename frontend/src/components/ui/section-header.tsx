"use client";

import React from "react";

// Usage:
// import { SectionHeader } from "@/components/ui/section-header";
// <SectionHeader title="Active Gaps" icon={<AlertCircle size={16} />} count={12} action={<Button>Export</Button>} />

export interface SectionHeaderProps {
  title: string;
  icon?: React.ReactNode;
  count?: number;
  action?: React.ReactNode;
}

export function SectionHeader({ title, icon, count, action }: SectionHeaderProps) {
  return (
    <div className="flex items-center justify-between pb-4 mb-4 border-b border-border">
      <div className="flex items-center gap-2">
        {icon && <span className="text-muted-foreground flex">{icon}</span>}
        <h3 className="m-0 text-sm font-semibold text-foreground">{title}</h3>
        {count !== undefined && (
          <span className="text-[11px] font-semibold text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
            {count}
          </span>
        )}
      </div>
      {action && <div>{action}</div>}
    </div>
  );
}
