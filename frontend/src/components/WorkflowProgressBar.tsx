"use client";

/**
 * WorkflowProgressBar
 *
 * Renders a 4-stage HCC workflow funnel at the top of each workflow page.
 * Highlights the current stage and provides navigation to adjacent stages.
 *
 * Usage:
 *   <WorkflowProgressBar currentStage="suspects" />
 *   <WorkflowProgressBar currentStage="attestations" />
 *   <WorkflowProgressBar currentStage="pre-submission" />
 *   <WorkflowProgressBar currentStage="edi-generation" />
 */

import React from "react";
import Link from "next/link";
import {
  ClipboardList,
  ClipboardCheck,
  ShieldCheck,
  FileText,
  ChevronRight,
  CheckCircle2,
} from "lucide-react";

export type WorkflowStage =
  | "suspects"
  | "attestations"
  | "pre-submission"
  | "edi-generation";

interface StageConfig {
  id: WorkflowStage;
  label: string;
  shortLabel: string;
  href: string;
  icon: React.ReactNode;
}

const STAGES: StageConfig[] = [
  {
    id: "suspects",
    label: "Suspects",
    shortLabel: "Suspects",
    href: "/suspects",
    icon: <ClipboardList size={14} aria-hidden />,
  },
  {
    id: "attestations",
    label: "Attestations",
    shortLabel: "Attestations",
    href: "/attestations",
    icon: <ClipboardCheck size={14} aria-hidden />,
  },
  {
    id: "pre-submission",
    label: "Pre-submission",
    shortLabel: "Pre-sub",
    href: "/pre-submission",
    icon: <ShieldCheck size={14} aria-hidden />,
  },
  {
    id: "edi-generation",
    label: "EDI Generation",
    shortLabel: "EDI",
    href: "/edi-generation",
    icon: <FileText size={14} aria-hidden />,
  },
];

interface Props {
  currentStage: WorkflowStage;
}

export default function WorkflowProgressBar({ currentStage }: Props) {
  const currentIdx = STAGES.findIndex((s) => s.id === currentStage);

  return (
    <nav
      aria-label="HCC workflow stages"
      className="flex items-center gap-0 bg-muted/40 border border-border rounded-[10px] px-2 py-1.5 mb-5 overflow-x-auto flex-nowrap"
    >
      {STAGES.map((stage, idx) => {
        const isCurrent = stage.id === currentStage;
        const isPast = idx < currentIdx;
        const isFuture = idx > currentIdx;

        const stateAttr: "past" | "current" | "future" = isCurrent
          ? "current"
          : isPast
          ? "past"
          : "future";

        return (
          <React.Fragment key={stage.id}>
            <Link
              href={stage.href}
              aria-current={isCurrent ? "step" : undefined}
              data-stage={stage.id}
              data-state={stateAttr}
              className={[
                "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs whitespace-nowrap transition-colors no-underline",
                isCurrent
                  ? "bg-primary text-primary-foreground font-bold"
                  : isPast
                  ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300 font-medium"
                  : "text-[hsl(var(--muted-future))] font-medium",
              ]
                .filter(Boolean)
                .join(" ")}
            >
              {isPast ? (
                <CheckCircle2 size={14} aria-hidden className="text-emerald-600" />
              ) : (
                stage.icon
              )}
              <span className="hidden sm:inline">{stage.label}</span>
              <span className="sm:hidden">{stage.shortLabel}</span>
            </Link>
            {idx < STAGES.length - 1 && (
              <ChevronRight
                size={14}
                aria-hidden
                className="text-muted-foreground/50 shrink-0 mx-0.5"
              />
            )}
          </React.Fragment>
        );
      })}
    </nav>
  );
}
