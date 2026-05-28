"use client";

// PageEmpty — centered empty-state for full page sections
//
// Usage:
//   import { PageEmpty } from "@/components/ui/page-empty";
//   import { FileSearch } from "lucide-react";
//
//   // Icon + title only:
//   <PageEmpty icon={<FileSearch size={48} />} title="No suspects found" />
//
//   // With description:
//   <PageEmpty
//     icon={<FileSearch size={48} />}
//     title="No suspects found"
//     description="Try adjusting your filters or run a new analysis."
//   />
//
//   // With primary action:
//   <PageEmpty
//     icon={<Users size={48} />}
//     title="No patients imported"
//     description="Connect an EMR or upload a CSV to get started."
//     action={{ label: "Connect EMR", onClick: () => router.push("/connect") }}
//   />

import React from "react";

export interface PageEmptyProps {
  /** Lucide icon element — render at 48px, e.g. <Users size={48} /> */
  icon?: React.ReactNode;
  /** Primary empty-state headline (required) */
  title: string;
  /** Supporting copy shown beneath the title */
  description?: string;
  /** Optional single call-to-action button */
  action?: {
    label: string;
    onClick: () => void;
  };
}

export function PageEmpty({ icon, title, description, action }: PageEmptyProps) {
  return (
    <div
      className="flex flex-col items-center justify-center min-h-[40vh] px-6 py-12 text-center"
      role="status"
      aria-label={title}
    >
      {icon && (
        <div
          className="mb-5 flex items-center justify-center text-muted-foreground/60"
          aria-hidden="true"
        >
          {icon}
        </div>
      )}

      <h2 className="text-lg font-medium text-foreground m-0">{title}</h2>

      {description && (
        <p className="mt-2 text-sm text-muted-foreground max-w-sm leading-relaxed">
          {description}
        </p>
      )}

      {action && (
        <button
          type="button"
          onClick={action.onClick}
          className="mt-5 inline-flex items-center justify-center rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition-all duration-150 hover:brightness-105 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50"
        >
          {action.label}
        </button>
      )}
    </div>
  );
}
