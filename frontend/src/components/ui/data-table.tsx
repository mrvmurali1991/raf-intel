"use client";

/**
 * DataTable — shared, reusable table component for RAF Intelligence.
 *
 * Replaces all one-off CSS-Grid table implementations across the app.
 *
 * Usage:
 * ```tsx
 * import { DataTable, type ColumnDef } from "@/components/ui/data-table";
 *
 * const columns: ColumnDef<Patient>[] = [
 *   { key: "name", header: "Patient", width: "minmax(200px, 2fr)", sortable: true },
 *   { key: "raf_score", header: "RAF Score", width: "100px", align: "right", sortable: true,
 *     render: (v) => <span className="font-mono">{v?.toFixed(3)}</span> },
 *   { key: "risk_level", header: "Risk", width: "120px",
 *     render: (_, row) => <RiskBadge level={row.risk_level} /> },
 * ];
 *
 * <DataTable
 *   data={patients}
 *   columns={columns}
 *   loading={isLoading}
 *   totalCount={total}
 *   currentPage={page}
 *   pageSize={25}
 *   onPageChange={setPage}
 *   sortColumn="raf_score"
 *   sortDirection="desc"
 *   onSort={(col, dir) => setSort({ col, dir })}
 *   onRowClick={(row) => router.push(`/patients/${row.id}`)}
 *   searchable
 *   onSearch={setQuery}
 *   filterSlot={<RiskFilterChips ... />}
 *   actionSlot={<BulkActionsBar ... />}
 *   stickyHeader
 * />
 * ```
 */

import React, { useCallback, useId, useMemo } from "react";
import { ChevronUp, ChevronDown, ChevronLeft, ChevronRight, Search } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface ColumnDef<T> {
  /** Dot-notation key into T, or a unique identifier for render-only columns */
  key: string;
  header: string;
  /** CSS width token — e.g. "200px", "1fr", "minmax(120px, 1fr)". Defaults to "1fr". */
  width?: string;
  /** Custom cell renderer. `value` is the raw field value; `row` is the full record. */
  render?: (value: unknown, row: T) => React.ReactNode;
  sortable?: boolean;
  align?: "left" | "center" | "right";
  /** Extra className applied to every cell (header + body) in this column */
  className?: string;
}

export interface DataTableProps<T> {
  data: T[];
  columns: ColumnDef<T>[];
  // ---- Loading / empty ----
  loading?: boolean;
  emptyMessage?: string;
  emptyIcon?: React.ReactNode;
  // ---- Pagination ----
  pageSize?: number;
  totalCount?: number;
  currentPage?: number;
  onPageChange?: (page: number) => void;
  // ---- Sorting ----
  onSort?: (column: string, direction: "asc" | "desc") => void;
  sortColumn?: string;
  sortDirection?: "asc" | "desc";
  // ---- Row interaction ----
  onRowClick?: (row: T) => void;
  rowClassName?: (row: T) => string;
  // ---- Search ----
  searchable?: boolean;
  searchPlaceholder?: string;
  onSearch?: (query: string) => void;
  // ---- Slots ----
  filterSlot?: React.ReactNode;
  actionSlot?: React.ReactNode;
  // ---- Layout ----
  stickyHeader?: boolean;
  compact?: boolean;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** Resolve a dot-notation key like "address.city" against an object */
function resolvePath(obj: unknown, key: string): unknown {
  return key.split(".").reduce<unknown>((cur, part) => {
    if (cur !== null && cur !== undefined && typeof cur === "object") {
      return (cur as Record<string, unknown>)[part];
    }
    return undefined;
  }, obj);
}

/** Build the CSS grid-template-columns string from column defs */
function buildGridTemplate<T>(columns: ColumnDef<T>[]): string {
  return columns.map((c) => c.width ?? "1fr").join(" ");
}

/** Clamp a value between min and max */
function clamp(val: number, min: number, max: number): number {
  return Math.min(Math.max(val, min), max);
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Shimmer skeleton row — mirrors the column widths of the real grid */
function SkeletonRow({
  columns,
  compact,
  gridTemplate,
}: {
  columns: ColumnDef<unknown>[];
  compact: boolean;
  gridTemplate: string;
}) {
  return (
    <div
      role="row"
      aria-hidden="true"
      className="grid items-center border-b border-border last:border-b-0"
      style={{ gridTemplateColumns: gridTemplate }}
    >
      {columns.map((col, i) => (
        <div
          key={col.key + i}
          className={cn("px-4", compact ? "py-2.5" : "py-3.5")}
          style={{ textAlign: col.align ?? "left" }}
        >
          {/* Vary skeleton widths to look natural */}
          <div
            className={cn(
              "skeleton h-3 rounded",
              i === 0 ? "w-3/4" : i % 3 === 0 ? "w-1/2" : "w-2/3",
              col.align === "right" && "ml-auto",
              col.align === "center" && "mx-auto"
            )}
          />
        </div>
      ))}
    </div>
  );
}

/** Single sort chevron indicator */
function SortIndicator({
  active,
  direction,
}: {
  active: boolean;
  direction?: "asc" | "desc";
}) {
  if (!active) {
    return (
      <span className="ml-1 inline-flex flex-col gap-[1px] opacity-30" aria-hidden="true">
        <ChevronUp size={9} />
        <ChevronDown size={9} />
      </span>
    );
  }
  return (
    <span className="ml-1 inline-flex text-primary" aria-hidden="true">
      {direction === "asc" ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
    </span>
  );
}

/** Page number button used in pagination bar */
function PageButton({
  page,
  active,
  onClick,
  disabled,
  children,
}: {
  page?: number;
  active?: boolean;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-current={active ? "page" : undefined}
      aria-label={page !== undefined ? `Page ${page}` : undefined}
      className={cn(
        "inline-flex h-7 min-w-[28px] items-center justify-center rounded-md px-2 text-[12px] font-medium transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
        "disabled:pointer-events-none disabled:opacity-40",
        active
          ? "bg-primary text-primary-foreground shadow-sm"
          : "text-muted-foreground hover:bg-muted hover:text-foreground"
      )}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// PaginationBar
// ---------------------------------------------------------------------------

function PaginationBar({
  currentPage,
  totalPages,
  totalCount,
  pageSize,
  onPageChange,
}: {
  currentPage: number;
  totalPages: number;
  totalCount: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}) {
  const firstItem = (currentPage - 1) * pageSize + 1;
  const lastItem = Math.min(currentPage * pageSize, totalCount);

  // Build visible page numbers with ellipsis: [1] ... [4] [5*] [6] ... [12]
  const pageNumbers = useMemo(() => {
    if (totalPages <= 7) {
      return Array.from({ length: totalPages }, (_, i) => i + 1);
    }
    const pages: (number | "ellipsis-start" | "ellipsis-end")[] = [];
    pages.push(1);
    if (currentPage > 3) pages.push("ellipsis-start");
    const start = clamp(currentPage - 1, 2, totalPages - 1);
    const end = clamp(currentPage + 1, 2, totalPages - 1);
    for (let p = start; p <= end; p++) pages.push(p);
    if (currentPage < totalPages - 2) pages.push("ellipsis-end");
    pages.push(totalPages);
    return pages;
  }, [currentPage, totalPages]);

  return (
    <div
      className="flex items-center justify-between gap-3 border-t border-border px-4 py-2.5 flex-wrap"
      role="navigation"
      aria-label="Table pagination"
    >
      {/* Showing N–M of X */}
      <p className="text-[12px] text-muted-foreground tabular-nums shrink-0">
        Showing{" "}
        <span className="font-medium text-foreground">
          {totalCount === 0 ? 0 : firstItem}–{lastItem}
        </span>{" "}
        of{" "}
        <span className="font-medium text-foreground">{totalCount.toLocaleString()}</span>
      </p>

      {/* Page buttons */}
      <div className="flex items-center gap-1">
        <PageButton
          onClick={() => onPageChange(currentPage - 1)}
          disabled={currentPage <= 1}
          aria-label="Previous page"
        >
          <ChevronLeft size={13} />
        </PageButton>

        {pageNumbers.map((p, i) =>
          typeof p === "string" ? (
            <span
              key={p + i}
              className="inline-flex h-7 w-7 items-center justify-center text-[12px] text-muted-foreground select-none"
              aria-hidden="true"
            >
              &hellip;
            </span>
          ) : (
            <PageButton
              key={p}
              page={p}
              active={p === currentPage}
              onClick={() => onPageChange(p)}
            >
              {p}
            </PageButton>
          )
        )}

        <PageButton
          onClick={() => onPageChange(currentPage + 1)}
          disabled={currentPage >= totalPages}
          aria-label="Next page"
        >
          <ChevronRight size={13} />
        </PageButton>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// DataTable
// ---------------------------------------------------------------------------

export function DataTable<T extends Record<string, unknown>>({
  data,
  columns,
  loading = false,
  emptyMessage = "No data found",
  emptyIcon,
  pageSize = 25,
  totalCount,
  currentPage = 1,
  onPageChange,
  onSort,
  sortColumn,
  sortDirection = "asc",
  onRowClick,
  rowClassName,
  searchable = false,
  searchPlaceholder = "Search…",
  onSearch,
  filterSlot,
  actionSlot,
  stickyHeader = false,
  compact = false,
}: DataTableProps<T>) {
  const tableId = useId();
  const headerId = `${tableId}-header`;

  const gridTemplate = buildGridTemplate(columns);

  // Derived pagination
  const effectiveTotal = totalCount ?? data.length;
  const totalPages = Math.max(1, Math.ceil(effectiveTotal / pageSize));
  const hasPagination = !!onPageChange && effectiveTotal > 0;

  // ---- Sort handler ----
  const handleSort = useCallback(
    (col: ColumnDef<T>) => {
      if (!col.sortable || !onSort) return;
      const nextDir =
        sortColumn === col.key && sortDirection === "asc" ? "desc" : "asc";
      onSort(col.key, nextDir);
    },
    [onSort, sortColumn, sortDirection]
  );

  // ---- Search handler ----
  const handleSearch = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      onSearch?.(e.target.value);
    },
    [onSearch]
  );

  // ---- Skeleton count — show pageSize rows while loading ----
  const skeletonCount = Math.min(pageSize, 10);

  // ---- Align class helper ----
  const alignClass = (align?: "left" | "center" | "right") =>
    align === "right"
      ? "text-right"
      : align === "center"
      ? "text-center"
      : "text-left";

  // ---- Row height class ----
  const rowHeightClass = compact ? "min-h-[40px]" : "min-h-[56px]";
  const cellPaddingClass = compact ? "py-2.5" : "py-3.5";
  const headerHeightClass = compact ? "h-10" : "h-12";

  const hasToolbar = searchable || filterSlot || actionSlot;

  return (
    <div
      className="flex flex-col rounded-xl border border-border bg-card overflow-hidden w-full animate-fade-in"
      role="region"
      aria-label="Data table"
      aria-busy={loading}
    >
      {/* ================================================================
          Toolbar: search + filter slot + action slot
          ================================================================ */}
      {hasToolbar && (
        <div className="flex items-center gap-2 px-4 py-3 border-b border-border flex-wrap">
          {searchable && (
            <div className="relative flex-1 min-w-[160px] max-w-[320px]">
              <Search
                size={14}
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
                aria-hidden="true"
              />
              <input
                type="search"
                placeholder={searchPlaceholder}
                onChange={handleSearch}
                aria-label={searchPlaceholder}
                className={cn(
                  "h-8 w-full rounded-lg border border-input bg-transparent",
                  "pl-8 pr-3 text-sm text-foreground placeholder:text-muted-foreground",
                  "transition-colors outline-none",
                  "focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/50",
                  "dark:bg-input/30"
                )}
              />
            </div>
          )}
          {filterSlot && (
            <div className="flex items-center gap-2 flex-wrap">{filterSlot}</div>
          )}
          {actionSlot && (
            <div className="flex items-center gap-2 ml-auto">{actionSlot}</div>
          )}
        </div>
      )}

      {/* ================================================================
          Scrollable table area
          ================================================================ */}
      <div className="overflow-x-auto w-full">
        <div
          className="min-w-max w-full"
          role="table"
          aria-rowcount={loading ? undefined : effectiveTotal}
          aria-labelledby={headerId}
        >
          {/* ---- Header row ---- */}
          <div
            id={headerId}
            role="row"
            aria-rowindex={1}
            className={cn(
              "grid items-center border-b border-border bg-muted/40",
              headerHeightClass,
              stickyHeader && [
                "sticky top-0 z-10",
                // Glass effect matching the worklist-header-row pattern in globals.css
                "bg-[rgba(255,255,255,0.9)] backdrop-blur-[8px]",
                "[box-shadow:0_1px_0_rgba(0,0,0,0.06)]",
                "dark:bg-[rgba(13,17,23,0.9)] dark:[box-shadow:0_1px_0_rgba(0,0,0,0.2)]",
              ]
            )}
            style={{ gridTemplateColumns: gridTemplate }}
          >
            {columns.map((col) => {
              const isActive = sortColumn === col.key;
              return (
                <div
                  key={col.key}
                  role="columnheader"
                  aria-sort={
                    col.sortable
                      ? isActive
                        ? sortDirection === "asc"
                          ? "ascending"
                          : "descending"
                        : "none"
                      : undefined
                  }
                  className={cn(
                    "px-4 flex items-center",
                    alignClass(col.align),
                    col.align === "right" && "justify-end",
                    col.align === "center" && "justify-center",
                    col.className
                  )}
                >
                  {col.sortable && onSort ? (
                    <button
                      type="button"
                      onClick={() => handleSort(col)}
                      aria-label={`Sort by ${col.header}${
                        isActive
                          ? sortDirection === "asc"
                            ? ", sorted ascending"
                            : ", sorted descending"
                          : ""
                      }`}
                      className={cn(
                        "inline-flex items-center gap-0.5 bg-transparent border-none p-0 cursor-pointer",
                        "text-[11px] font-bold uppercase tracking-[0.08em] whitespace-nowrap",
                        "transition-colors duration-150 focus-visible:outline-none focus-visible:underline",
                        isActive
                          ? "text-foreground"
                          : "text-muted-foreground hover:text-foreground"
                      )}
                    >
                      {col.header}
                      <SortIndicator
                        active={isActive}
                        direction={isActive ? sortDirection : undefined}
                      />
                    </button>
                  ) : (
                    <span className="text-[11px] font-bold uppercase tracking-[0.08em] whitespace-nowrap text-muted-foreground">
                      {col.header}
                    </span>
                  )}
                </div>
              );
            })}
          </div>

          {/* ================================================================
              Body: loading skeletons / empty state / data rows
              ================================================================ */}
          <div role="rowgroup">
            {/* ---- Loading skeletons ---- */}
            {loading &&
              Array.from({ length: skeletonCount }).map((_, i) => (
                <SkeletonRow
                  key={`skeleton-${i}`}
                  columns={columns as ColumnDef<unknown>[]}
                  compact={compact}
                  gridTemplate={gridTemplate}
                />
              ))}

            {/* ---- Empty state ---- */}
            {!loading && data.length === 0 && (
              <div role="row" aria-rowindex={2}>
                <div
                  role="cell"
                  className="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center"
                >
                  {emptyIcon && (
                    <div className="w-12 h-12 rounded-xl bg-muted flex items-center justify-center text-muted-foreground">
                      {emptyIcon}
                    </div>
                  )}
                  <p className="text-[14px] font-semibold text-foreground leading-snug">
                    {emptyMessage}
                  </p>
                </div>
              </div>
            )}

            {/* ---- Data rows ---- */}
            {!loading &&
              data.map((row, rowIndex) => {
                const isClickable = !!onRowClick;
                const extraClass = rowClassName?.(row) ?? "";

                return (
                  <div
                    key={rowIndex}
                    role="row"
                    aria-rowindex={rowIndex + 2}
                    tabIndex={isClickable ? 0 : undefined}
                    onClick={isClickable ? () => onRowClick(row) : undefined}
                    onKeyDown={
                      isClickable
                        ? (e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              onRowClick(row);
                            }
                          }
                        : undefined
                    }
                    className={cn(
                      "grid items-center border-b border-border last:border-b-0",
                      "transition-colors duration-100",
                      rowHeightClass,
                      isClickable && [
                        "cursor-pointer",
                        "hover:bg-muted/50",
                        "focus-visible:outline-none",
                        "focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/60",
                      ],
                      !isClickable && "hover:bg-muted/30",
                      extraClass
                    )}
                    style={{ gridTemplateColumns: gridTemplate }}
                  >
                    {columns.map((col) => {
                      const rawValue = resolvePath(row, col.key);
                      const rendered = col.render
                        ? col.render(rawValue, row)
                        : (rawValue as React.ReactNode) ?? null;

                      return (
                        <div
                          key={col.key}
                          role="cell"
                          className={cn(
                            "px-4 truncate",
                            cellPaddingClass,
                            alignClass(col.align),
                            col.className
                          )}
                        >
                          {rendered}
                        </div>
                      );
                    })}
                  </div>
                );
              })}
          </div>
        </div>
      </div>

      {/* ================================================================
          Pagination bar
          ================================================================ */}
      {hasPagination && (
        <PaginationBar
          currentPage={currentPage}
          totalPages={totalPages}
          totalCount={effectiveTotal}
          pageSize={pageSize}
          onPageChange={onPageChange!}
        />
      )}
    </div>
  );
}
