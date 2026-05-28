"use client";

// PageLoading — full-page skeleton with configurable variants
//
// Usage:
//   import { PageLoading } from "@/components/ui/page-loading";
//
//   // Table page:
//   <PageLoading variant="table" rows={8} />
//
//   // Cards grid:
//   <PageLoading variant="cards" cards={6} />
//
//   // Dashboard with KPIs + chart + table:
//   <PageLoading variant="dashboard" />
//
//   // Detail/profile page:
//   <PageLoading variant="detail" />

import React from "react";

export interface PageLoadingProps {
  /** Layout variant — drives which skeleton sections are rendered */
  variant?: "table" | "cards" | "dashboard" | "detail";
  /** Number of skeleton rows (table variant only, default 6) */
  rows?: number;
  /** Number of skeleton cards (cards variant only, default 6) */
  cards?: number;
}

// ---------------------------------------------------------------------------
// Primitive pulse blocks
// ---------------------------------------------------------------------------

function Pulse({ className }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded-md bg-muted ${className ?? ""}`}
      aria-hidden="true"
    />
  );
}

// ---------------------------------------------------------------------------
// Shared sub-skeletons
// ---------------------------------------------------------------------------

/** Mimics PageHeader: icon square + title bar + subtitle bar + action button */
function PageHeaderSkeleton() {
  return (
    <div className="flex items-start justify-between mb-6 pb-5 border-b border-border gap-4 flex-wrap">
      <div className="flex items-center gap-3">
        {/* icon */}
        <Pulse className="w-11 h-11 rounded-xl flex-shrink-0" />
        <div className="space-y-2">
          {/* title */}
          <Pulse className="h-[22px] w-48 rounded" />
          {/* subtitle */}
          <Pulse className="h-3.5 w-32 rounded" />
        </div>
      </div>
      {/* action button */}
      <Pulse className="h-8 w-28 rounded-lg" />
    </div>
  );
}

/** Breadcrumb row: two short pill segments joined by a separator */
function BreadcrumbSkeleton() {
  return (
    <div className="flex items-center gap-2 mb-4" aria-hidden="true">
      <Pulse className="h-4 w-16 rounded" />
      <Pulse className="h-4 w-1 rounded" />
      <Pulse className="h-4 w-24 rounded" />
    </div>
  );
}

/** Single table skeleton row */
function TableRowSkeleton({ cols = 5 }: { cols?: number }) {
  const widths = ["w-32", "w-24", "w-20", "w-28", "w-16"];
  return (
    <div className="flex items-center gap-4 px-4 py-3 border-b border-border last:border-0">
      {Array.from({ length: cols }).map((_, i) => (
        <Pulse
          key={i}
          className={`h-4 flex-1 rounded ${widths[i % widths.length]}`}
        />
      ))}
    </div>
  );
}

/** Table header row (darker shade) */
function TableHeaderSkeleton({ cols = 5 }: { cols?: number }) {
  return (
    <div className="flex items-center gap-4 px-4 py-2.5 border-b border-border bg-muted/40">
      {Array.from({ length: cols }).map((_, i) => (
        <Pulse key={i} className="h-3.5 flex-1 rounded opacity-70" />
      ))}
    </div>
  );
}

/** KPI metric card skeleton */
function KpiCardSkeleton() {
  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      {/* label */}
      <Pulse className="h-3 w-24 rounded" />
      {/* big number */}
      <Pulse className="h-7 w-16 rounded" />
      {/* trend chip */}
      <Pulse className="h-3 w-20 rounded" />
    </div>
  );
}

/** Chart area skeleton */
function ChartSkeleton() {
  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      {/* chart header */}
      <div className="flex items-center justify-between mb-2">
        <Pulse className="h-4 w-36 rounded" />
        <Pulse className="h-6 w-24 rounded-lg" />
      </div>
      {/* chart body — simulated bars */}
      <div className="flex items-end gap-2 h-40 px-2 pt-2">
        {[60, 80, 45, 90, 55, 75, 65, 85, 50, 70, 40, 95].map((h, i) => (
          <div
            key={i}
            className="animate-pulse flex-1 rounded-t bg-muted"
            style={{ height: `${h}%` }}
            aria-hidden="true"
          />
        ))}
      </div>
    </div>
  );
}

/** Generic card skeleton */
function CardSkeleton() {
  return (
    <div className="rounded-xl border border-border bg-card p-4 space-y-3">
      {/* card header row */}
      <div className="flex items-center gap-2">
        <Pulse className="w-8 h-8 rounded-lg flex-shrink-0" />
        <Pulse className="h-4 flex-1 rounded" />
      </div>
      {/* body lines */}
      <Pulse className="h-3 w-full rounded" />
      <Pulse className="h-3 w-4/5 rounded" />
      <Pulse className="h-3 w-3/5 rounded" />
      {/* footer chip */}
      <Pulse className="h-5 w-20 rounded-full mt-1" />
    </div>
  );
}

/** Tab bar skeleton */
function TabBarSkeleton({ tabs = 4 }: { tabs?: number }) {
  const widths = ["w-20", "w-24", "w-16", "w-20"];
  return (
    <div className="flex gap-1 border-b border-border pb-px mb-6">
      {Array.from({ length: tabs }).map((_, i) => (
        <Pulse
          key={i}
          className={`h-8 rounded-t-md ${widths[i % widths.length]}`}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Variant compositions
// ---------------------------------------------------------------------------

function TableVariant({ rows }: { rows: number }) {
  return (
    <div role="status" aria-label="Loading table data" aria-live="polite">
      <span className="sr-only">Loading…</span>
      <PageHeaderSkeleton />
      <div className="rounded-xl border border-border overflow-hidden">
        <TableHeaderSkeleton />
        {Array.from({ length: rows }).map((_, i) => (
          <TableRowSkeleton key={i} />
        ))}
      </div>
    </div>
  );
}

function CardsVariant({ cards }: { cards: number }) {
  return (
    <div role="status" aria-label="Loading cards" aria-live="polite">
      <span className="sr-only">Loading…</span>
      <PageHeaderSkeleton />
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {Array.from({ length: cards }).map((_, i) => (
          <CardSkeleton key={i} />
        ))}
      </div>
    </div>
  );
}

function DashboardVariant() {
  return (
    <div role="status" aria-label="Loading dashboard" aria-live="polite">
      <span className="sr-only">Loading…</span>
      <PageHeaderSkeleton />
      {/* KPI bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
        {Array.from({ length: 4 }).map((_, i) => (
          <KpiCardSkeleton key={i} />
        ))}
      </div>
      {/* Chart row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        <div className="lg:col-span-2">
          <ChartSkeleton />
        </div>
        <ChartSkeleton />
      </div>
      {/* Summary table */}
      <div className="rounded-xl border border-border overflow-hidden">
        <TableHeaderSkeleton cols={4} />
        {Array.from({ length: 4 }).map((_, i) => (
          <TableRowSkeleton key={i} cols={4} />
        ))}
      </div>
    </div>
  );
}

function DetailVariant() {
  return (
    <div role="status" aria-label="Loading detail page" aria-live="polite">
      <span className="sr-only">Loading…</span>
      <BreadcrumbSkeleton />
      <PageHeaderSkeleton />
      <TabBarSkeleton />
      {/* Content body */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <div className="rounded-xl border border-border bg-card p-5 space-y-3">
            <Pulse className="h-5 w-40 rounded" />
            <Pulse className="h-3.5 w-full rounded" />
            <Pulse className="h-3.5 w-5/6 rounded" />
            <Pulse className="h-3.5 w-4/6 rounded" />
          </div>
          <div className="rounded-xl border border-border overflow-hidden">
            <TableHeaderSkeleton cols={3} />
            {Array.from({ length: 5 }).map((_, i) => (
              <TableRowSkeleton key={i} cols={3} />
            ))}
          </div>
        </div>
        <div className="space-y-4">
          <KpiCardSkeleton />
          <KpiCardSkeleton />
          <CardSkeleton />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------

export function PageLoading({
  variant = "table",
  rows = 6,
  cards = 6,
}: PageLoadingProps) {
  switch (variant) {
    case "cards":
      return <CardsVariant cards={cards} />;
    case "dashboard":
      return <DashboardVariant />;
    case "detail":
      return <DetailVariant />;
    case "table":
    default:
      return <TableVariant rows={rows} />;
  }
}
