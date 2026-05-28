"use client";

// Usage:
// import { WelcomeGuide } from "@/components/ui/welcome-guide";
//
// Place near the top of a layout or page that runs after login:
//   const [showWelcome, setShowWelcome] = React.useState(false);
//   React.useEffect(() => {
//     const dismissed = localStorage.getItem("raf-welcome-dismissed");
//     if (!dismissed) setShowWelcome(true);
//   }, []);
//   {showWelcome && (
//     <WelcomeGuide
//       userName="Dr. Patel"
//       role="provider"
//       onDismiss={() => setShowWelcome(false)}
//     />
//   )}

import React, { useEffect, useRef } from "react";
import Link from "next/link";
import {
  LayoutDashboard,
  Stethoscope,
  RefreshCw,
  ClipboardList,
  BadgeCheck,
  CalendarCheck,
  Users,
  BarChart3,
  X,
  ArrowRight,
} from "lucide-react";
import { cn } from "@/lib/utils";

export interface WelcomeGuideProps {
  userName?: string;
  role?: "admin" | "coder" | "provider" | string;
  onDismiss: () => void;
}

interface GuideCard {
  icon: React.ReactNode;
  title: string;
  description: string;
  href: string;
}

const STORAGE_KEY = "raf-welcome-dismissed";
const AUTO_DISMISS_MS = 30_000;

const ROLE_CARDS: Record<string, GuideCard[]> = {
  admin: [
    {
      icon: <LayoutDashboard size={18} />,
      title: "Dashboard",
      description: "Your command center for RAF performance",
      href: "/dashboard",
    },
    {
      icon: <Stethoscope size={18} />,
      title: "Suspects",
      description: "AI-found HCC gaps to review and capture",
      href: "/suspects",
    },
    {
      icon: <RefreshCw size={18} />,
      title: "Recapture",
      description: "Protect last year's confirmed revenue",
      href: "/recapture",
    },
    {
      icon: <BarChart3 size={18} />,
      title: "Reports",
      description: "Analytics and exportable insights",
      href: "/reports",
    },
  ],
  coder: [
    {
      icon: <Stethoscope size={18} />,
      title: "Suspects",
      description: "AI-found HCC gaps ready for coding",
      href: "/suspects",
    },
    {
      icon: <ClipboardList size={18} />,
      title: "Review Queue",
      description: "Charts pending your clinical review",
      href: "/review-queue",
    },
    {
      icon: <BadgeCheck size={18} />,
      title: "Attestations",
      description: "Track provider sign-offs and approvals",
      href: "/attestations",
    },
    {
      icon: <RefreshCw size={18} />,
      title: "Recapture",
      description: "Protect last year's confirmed revenue",
      href: "/recapture",
    },
  ],
  provider: [
    {
      icon: <CalendarCheck size={18} />,
      title: "Huddle",
      description: "Pre-visit briefings for today's patients",
      href: "/suspects",
    },
    {
      icon: <ClipboardList size={18} />,
      title: "Worklist",
      description: "Your prioritised patient action list",
      href: "/worklist",
    },
    {
      icon: <Users size={18} />,
      title: "Patients",
      description: "Full panel with RAF scores and gaps",
      href: "/patients",
    },
    {
      icon: <BadgeCheck size={18} />,
      title: "Attestations",
      description: "Diagnoses awaiting your sign-off",
      href: "/attestations",
    },
  ],
};

function resolveCards(role?: string): GuideCard[] {
  if (!role) return ROLE_CARDS.admin;
  const key = role.toLowerCase();
  return ROLE_CARDS[key] ?? ROLE_CARDS.admin;
}

function resolveGreeting(userName?: string): string {
  if (!userName) return "Welcome to RAF Intelligence!";
  return `Welcome, ${userName}!`;
}

export function WelcomeGuide({ userName, role, onDismiss }: WelcomeGuideProps) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [visible, setVisible] = React.useState(false);

  // Slide-in on mount
  useEffect(() => {
    const raf = requestAnimationFrame(() => setVisible(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  // Auto-dismiss after 30 s
  useEffect(() => {
    timerRef.current = setTimeout(() => handleDismiss(), AUTO_DISMISS_MS);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleDismiss() {
    if (timerRef.current) clearTimeout(timerRef.current);
    // Persist dismissal immediately; animate out
    try {
      localStorage.setItem(STORAGE_KEY, "1");
    } catch {
      // storage unavailable — still dismiss visually
    }
    setVisible(false);
    // Wait for exit transition before removing from DOM
    setTimeout(() => onDismiss(), 350);
  }

  const cards = resolveCards(role);
  const greeting = resolveGreeting(userName);

  return (
    <div
      role="banner"
      aria-label="Welcome guide"
      className={cn(
        "w-full z-50 transition-transform duration-350 ease-out will-change-transform",
        visible ? "translate-y-0" : "-translate-y-full"
      )}
    >
      <div className="mx-4 mt-3 mb-0 rounded-xl border border-blue-100 dark:border-blue-900/60 bg-white dark:bg-slate-900 shadow-md shadow-blue-900/5 overflow-hidden">
        {/* Top accent bar */}
        <div className="h-0.5 w-full bg-gradient-to-r from-blue-500 via-indigo-500 to-violet-500" />

        <div className="px-5 py-4">
          {/* Header row */}
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-2 min-w-0">
              {/* Friendly wave using a text span so no emoji dependency on icon libs */}
              <span
                aria-hidden="true"
                className="text-xl leading-none select-none"
                style={{ display: "inline-block" }}
              >
                👋
              </span>
              <div className="min-w-0">
                <p className="text-sm font-semibold text-foreground dark:text-slate-100 truncate">
                  {greeting}{" "}
                  <span className="font-normal text-muted-foreground dark:text-slate-400">
                    Here&apos;s your quick-start guide.
                  </span>
                </p>
              </div>
            </div>

            {/* Close X — always available */}
            <button
              type="button"
              aria-label="Close welcome guide"
              onClick={handleDismiss}
              className="flex-shrink-0 rounded-md p-1 text-muted-foreground hover:text-foreground hover:bg-muted dark:hover:bg-slate-800 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <X size={16} />
            </button>
          </div>

          {/* Guide cards */}
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {cards.map((card) => (
              <Link
                key={card.href}
                href={card.href}
                onClick={handleDismiss}
                className={cn(
                  "group flex flex-col gap-1.5 rounded-lg border border-border dark:border-slate-700/60",
                  "bg-muted/40 dark:bg-slate-800/50 hover:bg-blue-50 dark:hover:bg-blue-950/40",
                  "hover:border-blue-200 dark:hover:border-blue-800/60",
                  "px-3 py-2.5 transition-colors duration-150 no-underline focus-visible:outline-none",
                  "focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
                )}
                aria-label={`Go to ${card.title} — ${card.description}`}
              >
                <span className="flex items-center gap-1.5 text-blue-600 dark:text-blue-400 group-hover:text-blue-700 dark:group-hover:text-blue-300 transition-colors">
                  {card.icon}
                  <span className="text-xs font-semibold text-foreground dark:text-slate-100 group-hover:text-blue-700 dark:group-hover:text-blue-300 transition-colors">
                    {card.title}
                  </span>
                </span>
                <span className="text-xs text-muted-foreground dark:text-slate-400 leading-snug">
                  {card.description}
                </span>
              </Link>
            ))}
          </div>

          {/* Footer action row */}
          <div className="mt-3 flex items-center justify-end">
            <button
              type="button"
              onClick={handleDismiss}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-xs font-medium",
                "bg-blue-600 text-white hover:bg-blue-700 active:bg-blue-800",
                "transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2",
                "focus-visible:ring-blue-500 focus-visible:ring-offset-1"
              )}
            >
              Got it, let&apos;s go
              <ArrowRight size={13} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
