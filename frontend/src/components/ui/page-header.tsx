"use client";

import React from "react";
import { ChevronLeft } from "lucide-react";
import Link from "next/link";

// Usage:
// import { PageHeader } from "@/components/ui/page-header";
// <PageHeader title="Patients" subtitle="All enrolled" icon={<Users size={20} />} backHref="/dashboard" />

export interface PageHeaderProps {
  title: React.ReactNode;
  subtitle?: string;
  icon?: React.ReactNode;
  actions?: React.ReactNode;
  backHref?: string;
}

export function PageHeader({ title, subtitle, icon, actions, backHref }: PageHeaderProps) {
  return (
    <div className="flex items-start justify-between mb-6 pb-5 border-b border-border dark:border-slate-700 gap-4 flex-wrap">
      <div className="flex items-center gap-3 min-w-0">
        {backHref && (
          <Link
            href={backHref}
            className="hover-lift w-9 h-9 rounded-lg border border-border dark:border-slate-700 flex items-center justify-center text-muted-foreground dark:text-slate-400 no-underline flex-shrink-0"
          >
            <ChevronLeft size={18} />
          </Link>
        )}
        {icon && (
          <div className="w-11 h-11 rounded-xl bg-primary/10 flex items-center justify-center text-primary flex-shrink-0 shadow-sm">
            {icon}
          </div>
        )}
        <div className="min-w-0">
          <h1 className="m-0 text-2xl font-bold text-foreground dark:text-white leading-tight">{title}</h1>
          {subtitle && <p className="mt-1 mb-0 text-sm text-muted-foreground dark:text-slate-400">{subtitle}</p>}
        </div>
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
