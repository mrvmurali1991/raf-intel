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
      style={{
        display: "flex",
        alignItems: "center",
        gap: 0,
        background: "#F8FAFC",
        border: "1px solid #E2E8F0",
        borderRadius: 10,
        padding: "6px 8px",
        marginBottom: 20,
        overflowX: "auto",
        flexWrap: "nowrap",
      }}
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
                "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs whitespace-nowrap transition-colors",
                isCurrent
                  ? "font-bold opacity-100"
                  : isPast
                  ? "font-medium opacity-100"
                  : "font-medium opacity-60",
              ]
                .filter(Boolean)
                .join(" ")}
              style={{
                textDecoration: "none",
                background: isCurrent
                  ? "#0F766E"
                  : isPast
                  ? "#D1FAE5"
                  : "transparent",
                color: isCurrent
                  ? "#FFFFFF"
                  : isPast
                  ? "#065F46"
                  : "#94A3B8",
              }}
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
                style={{
                  color: "#CBD5E1",
                  flexShrink: 0,
                  margin: "0 2px",
                }}
              />
            )}
          </React.Fragment>
        );
      })}
    </nav>
  );
}
