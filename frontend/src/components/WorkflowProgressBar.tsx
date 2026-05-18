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
import { ClipboardList, ClipboardCheck, ShieldCheck, FileText, ChevronRight } from "lucide-react";

export type WorkflowStage = "suspects" | "attestations" | "pre-submission" | "edi-generation";

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

        return (
          <React.Fragment key={stage.id}>
            <Link
              href={stage.href}
              aria-current={isCurrent ? "page" : undefined}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                padding: "5px 12px",
                borderRadius: 7,
                fontSize: 12,
                fontWeight: isCurrent ? 700 : 500,
                textDecoration: "none",
                whiteSpace: "nowrap",
                transition: "background 0.15s, color 0.15s",
                background: isCurrent
                  ? "#0F766E"
                  : isPast
                  ? "#D1FAE5"
                  : "transparent",
                color: isCurrent
                  ? "#FFFFFF"
                  : isPast
                  ? "#065F46"
                  : isFuture
                  ? "#94A3B8"
                  : "#374151",
                cursor: isFuture ? "pointer" : "pointer",
                opacity: isFuture ? 0.6 : 1,
              }}
            >
              {stage.icon}
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
