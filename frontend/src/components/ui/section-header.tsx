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
    <div className="flex items-center justify-between mb-4">
      <div className="flex items-center gap-2">
        {icon && <span className="text-primary flex">{icon}</span>}
        <div className="flex flex-col">
          <h3 className="m-0 text-base font-bold text-foreground">{title}</h3>
          <div className="w-8 h-[3px] rounded-sm bg-primary mt-1 opacity-70" />
        </div>
        {count !== undefined && (
          <span className="text-[11px] font-semibold text-primary bg-primary/10 px-2 py-0.5 rounded-full">
            {count}
          </span>
        )}
      </div>
      {action && <div>{action}</div>}
    </div>
  );
}
