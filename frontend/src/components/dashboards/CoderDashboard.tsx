"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { CheckCircle, AlertTriangle, FileText, Activity, Clock, XCircle } from "lucide-react";
import { PageHeader, SectionHeader, StatCard } from "@/components/healthcare-ui";
import { getDashboardStats } from "@/lib/api";

/* ---------- Types ---------- */

interface CoderDashboardStats {
  total_suspects_open?: number | string;
  patients_analyzed?: number | string;
  [key: string]: unknown;
}

export interface RecentAction {
  id: string;
  suspectId: number;
  action: "accepted" | "dismissed";
  label: string;
  timestamp: string; // ISO string
}

/* ---------- Local-storage backed recent activity ---------- */

const RECENT_KEY = "coder_recent_activity";
const MAX_RECENT = 5;

/** Call this from the suspects page when a suspect is accepted or dismissed. */
export function pushRecentAction(action: Omit<RecentAction, "id">) {
  try {
    const prev: RecentAction[] = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
    const entry: RecentAction = { ...action, id: crypto.randomUUID() };
    const next = [entry, ...prev].slice(0, MAX_RECENT);
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
    window.dispatchEvent(new Event("recent-activity-updated"));
  } catch {
    /* noop */
  }
}

function useRecentActivity(): RecentAction[] {
  const [items, setItems] = useState<RecentAction[]>([]);

  useEffect(() => {
    const load = () => {
      try {
        setItems(JSON.parse(localStorage.getItem(RECENT_KEY) || "[]"));
      } catch {
        setItems([]);
      }
    };
    load();
    window.addEventListener("recent-activity-updated", load);
    window.addEventListener("storage", load);
    return () => {
      window.removeEventListener("recent-activity-updated", load);
      window.removeEventListener("storage", load);
    };
  }, []);

  return items;
}

/* ---------- Urgency badge ---------- */

function UrgencyBadge({ count }: { count: number }) {
  if (count <= 10) return null;
  const isRed = count > 50;
  return (
    <span
      className={`ml-2 inline-flex items-center px-2 py-0.5 rounded-full text-xs font-bold ${
        isRed
          ? "bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-200"
          : "bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-200"
      }`}
      aria-label={
        isRed
          ? "Critical: more than 50 pending suspects"
          : "Warning: more than 10 pending suspects"
      }
    >
      {isRed ? "Critical" : "High"}
    </span>
  );
}

/* ---------- Skeleton ---------- */
import { Pulse, SkeletonCard } from "@/components/ui/loading";

function CoderSkeleton() {
  return (
    <>
      <SkeletonCard columns={3} />
      {/* 2 quick link cards skeleton */}
      <div className="mt-8">
        <Pulse w={160} h={20} />
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 mt-4">
          {[1, 2].map((i) => (
            <div
              key={i}
              className="bg-white border border-border/40 rounded-2xl p-6 shadow-sm"
            >
              <Pulse w={180} h={18} />
              <div style={{ height: 8 }} />
              <Pulse w="100%" h={14} />
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

/* ---------- Relative time helper ---------- */

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

/* ---------- Main component ---------- */

export function CoderDashboard() {
  const { data: stats, isLoading } = useQuery<CoderDashboardStats>({
    queryKey: ["dashboard-stats"],
    queryFn: () => getDashboardStats() as unknown as CoderDashboardStats,
  });

  const recentActions = useRecentActivity();
  const pendingCount = Number(stats?.total_suspects_open ?? 0);

  return (
    <div className="fade-in-up">
      <PageHeader
        title="Coder Worklist Dashboard"
        subtitle="Review suspected conditions, missing documentation, and active queue."
      />

      <div style={{ paddingBottom: 24 }} />

      {isLoading ? (
        <CoderSkeleton />
      ) : (
        <>
          {/* KPI cards — responsive 3 → 2 → 1 */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5 mb-8">
            <StatCard
              label={
                <span className="inline-flex items-center">
                  Pending Suspects
                  <UrgencyBadge count={pendingCount} />
                </span>
              }
              value={stats?.total_suspects_open ?? "0"}
              subtitle="Requires Validation"
              icon={<AlertTriangle size={20} />}
              color="#F59E0B"
              href="/suspects"
              aria-label={`Pending suspects: ${stats?.total_suspects_open ?? 0}`}
            />
            <StatCard
              label="Missing Documents"
              value={"0"}
              subtitle="Follow-up needed"
              icon={<FileText size={20} />}
              color="#3B82F6"
              aria-label="Missing documents: 0"
            />
            <StatCard
              label="Analyzed Patients"
              value={stats?.patients_analyzed ?? "0"}
              subtitle="Total NLP Scanned"
              icon={<Activity size={20} />}
              color="#10B981"
              href="/patients"
              aria-label={`Analyzed patients: ${stats?.patients_analyzed ?? 0}`}
            />
          </div>

          {/* Quick Links */}
          <SectionHeader title="Active Quick Links" />
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 mt-4">
            <Link
              href="/suspects"
              className="block p-6 bg-white border border-border/40 rounded-2xl shadow-sm hover:shadow-md transition"
              aria-label="Go to suspects queue"
            >
              <div className="flex items-center gap-3 text-amber-600 mb-2">
                <AlertTriangle size={24} />
                <span className="font-semibold text-lg text-foreground">
                  Suspects Queue
                </span>
              </div>
              <p className="text-muted-foreground text-sm">
                Validations are waiting. Accept suspects to push them directly
                to OpenEMR.
              </p>
            </Link>
            <Link
              href="/documents"
              className="block p-6 bg-white border border-border/40 rounded-2xl shadow-sm hover:shadow-md transition"
              aria-label="Go to document analysis"
            >
              <div className="flex items-center gap-3 text-blue-600 mb-2">
                <FileText size={24} />
                <span className="font-semibold text-lg text-foreground">
                  Document Analysis
                </span>
              </div>
              <p className="text-muted-foreground text-sm">
                Upload C-CDA or PDF files for NLP extraction and validation.
              </p>
            </Link>
          </div>

          {/* Recent Activity */}
          {recentActions.length > 0 && (
            <div className="mt-8">
              <SectionHeader title="Recent Activity" />
              <div className="mt-4 bg-white border border-border/40 rounded-2xl shadow-sm divide-y divide-border/30 overflow-hidden">
                {recentActions.map((a) => (
                  <div
                    key={a.id}
                    className="flex items-center gap-3 px-5 py-3"
                  >
                    {a.action === "accepted" ? (
                      <CheckCircle
                        size={16}
                        className="text-emerald-500 shrink-0"
                        aria-hidden="true"
                      />
                    ) : (
                      <XCircle
                        size={16}
                        className="text-red-400 shrink-0"
                        aria-hidden="true"
                      />
                    )}
                    <span className="text-sm text-foreground flex-1 min-w-0 truncate">
                      <span className="font-medium capitalize">
                        {a.action}
                      </span>{" "}
                      {a.label}
                    </span>
                    <span className="text-xs text-muted-foreground flex items-center gap-1 shrink-0">
                      <Clock size={12} aria-hidden="true" />
                      <time dateTime={a.timestamp}>
                        {relativeTime(a.timestamp)}
                      </time>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
