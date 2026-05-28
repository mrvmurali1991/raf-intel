"use client";

/**
 * SearchFilterBar — unified search + filter bar for RAF Intelligence.
 *
 * Replaces ad-hoc search inputs scattered across patients, suspects,
 * recapture, and other list pages with a single consistent component.
 *
 * Usage:
 * ```tsx
 * import { SearchFilterBar } from "@/components/ui/search-filter-bar";
 *
 * const filters: FilterOption[] = [
 *   {
 *     key: "status",
 *     label: "Status",
 *     options: [
 *       { value: "active", label: "Active" },
 *       { value: "inactive", label: "Inactive" },
 *     ],
 *   },
 *   {
 *     key: "risk",
 *     label: "Risk",
 *     options: [
 *       { value: "high", label: "High" },
 *       { value: "medium", label: "Medium" },
 *       { value: "low", label: "Low" },
 *     ],
 *   },
 * ];
 *
 * const [search, setSearch] = useState("");
 * const [filterValues, setFilterValues] = useState<Record<string, string>>({});
 *
 * <SearchFilterBar
 *   searchValue={search}
 *   onSearchChange={setSearch}
 *   searchPlaceholder="Search patients..."
 *   filters={filters}
 *   filterValues={filterValues}
 *   onFilterChange={(key, value) =>
 *     setFilterValues((prev) => ({ ...prev, [key]: value }))
 *   }
 *   onClearAll={() => { setSearch(""); setFilterValues({}); }}
 *   actionSlot={<ExportCSVButton />}
 * />
 * ```
 */

import React, { useCallback, useEffect, useId, useRef, useState } from "react";
import { Search, X, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

export interface FilterOption {
  /** Unique key used in filterValues map */
  key: string;
  /** Human-readable label rendered in the dropdown trigger */
  label: string;
  /** Selectable options — "All" is prepended automatically */
  options: { value: string; label: string }[];
  /** Value treated as "unset" — defaults to empty string "" */
  defaultValue?: string;
}

export interface SearchFilterBarProps {
  /** Controlled search text */
  searchValue?: string;
  /** Fired after 300 ms debounce */
  onSearchChange?: (value: string) => void;
  searchPlaceholder?: string;

  /** Filter definitions */
  filters?: FilterOption[];
  /** Controlled filter state: { [key]: selectedValue } */
  filterValues?: Record<string, string>;
  /** Fired immediately (no debounce) */
  onFilterChange?: (key: string, value: string) => void;

  /**
   * Called when the "Clear all" button is clicked.
   * The parent is responsible for resetting both searchValue and filterValues.
   */
  onClearAll?: () => void;

  /**
   * Override the computed active-filter count badge.
   * Omit to let the component compute it automatically.
   */
  activeFilterCount?: number;

  /** Flexible right-side slot — Export CSV, Bulk Actions, etc. */
  actionSlot?: React.ReactNode;

  className?: string;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

const SENTINEL = "" as const; // value that means "All / unset"

function useDebounce<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState<T>(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);
  return debounced;
}

// ---------------------------------------------------------------------------
// FilterDropdown — native <select> styled to match the design system
// ---------------------------------------------------------------------------

interface FilterDropdownProps {
  filter: FilterOption;
  value: string;
  onChange: (value: string) => void;
  id: string;
}

function FilterDropdown({ filter, value, onChange, id }: FilterDropdownProps) {
  const isActive = value !== SENTINEL && value !== (filter.defaultValue ?? SENTINEL);

  return (
    <div className="relative flex-shrink-0">
      {/* Visually-hidden label for screen readers */}
      <label htmlFor={id} className="sr-only">
        {filter.label}
      </label>

      {/* The native select provides full keyboard and screen-reader support. */}
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-label={filter.label}
        className={cn(
          // base layout
          "h-8 appearance-none cursor-pointer rounded-lg border bg-transparent",
          "pl-2.5 pr-7 text-sm font-medium",
          "transition-colors outline-none",
          // focus ring matches design system ring token
          "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
          // idle state
          "border-border text-foreground",
          "dark:border-slate-700 dark:bg-slate-800 dark:text-slate-100",
          // active (filtering) state — teal accent border
          isActive && [
            "border-teal-600 bg-teal-50 text-teal-800",
            "dark:border-teal-500 dark:bg-teal-950/40 dark:text-teal-200",
          ]
        )}
      >
        <option value={SENTINEL}>All {filter.label}</option>
        {filter.options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      {/* Decorative chevron — pointer-events:none so clicks pass through */}
      <ChevronDown
        aria-hidden="true"
        className={cn(
          "pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 size-3.5",
          isActive ? "text-teal-700 dark:text-teal-300" : "text-muted-foreground"
        )}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// ActiveFilterBadge
// ---------------------------------------------------------------------------

function ActiveFilterBadge({ count }: { count: number }) {
  if (count === 0) return null;
  return (
    <span
      aria-label={`${count} active filter${count === 1 ? "" : "s"}`}
      className={cn(
        "inline-flex items-center justify-center",
        "size-5 rounded-full text-xs font-semibold leading-none",
        "bg-teal-600 text-white",
        "dark:bg-teal-500 dark:text-white",
        "flex-shrink-0"
      )}
    >
      {count > 9 ? "9+" : count}
    </span>
  );
}

// ---------------------------------------------------------------------------
// SearchFilterBar — main export
// ---------------------------------------------------------------------------

export function SearchFilterBar({
  searchValue = "",
  onSearchChange,
  searchPlaceholder = "Search...",
  filters = [],
  filterValues = {},
  onFilterChange,
  onClearAll,
  activeFilterCount,
  actionSlot,
  className,
}: SearchFilterBarProps) {
  // Internal "draft" search value so we can debounce without losing keystroke
  // responsiveness in the input itself.
  const [localSearch, setLocalSearch] = useState(searchValue);
  const inputRef = useRef<HTMLInputElement>(null);
  const baseId = useId();

  // Sync controlled prop → local state when parent resets (e.g. clear-all)
  useEffect(() => {
    setLocalSearch(searchValue);
  }, [searchValue]);

  const debouncedSearch = useDebounce(localSearch, 300);

  // Fire onChange only when the debounced value actually changes
  const prevDebounced = useRef(debouncedSearch);
  useEffect(() => {
    if (debouncedSearch !== prevDebounced.current) {
      prevDebounced.current = debouncedSearch;
      onSearchChange?.(debouncedSearch);
    }
  }, [debouncedSearch, onSearchChange]);

  const handleSearchInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setLocalSearch(e.target.value);
    },
    []
  );

  const handleClearSearch = useCallback(() => {
    setLocalSearch("");
    // Flush immediately — no debounce needed for an explicit clear
    onSearchChange?.("");
    inputRef.current?.focus();
  }, [onSearchChange]);

  const handleClearAll = useCallback(() => {
    setLocalSearch("");
    onClearAll?.();
    inputRef.current?.focus();
  }, [onClearAll]);

  // Compute active filter count when not overridden by prop
  const computedActiveCount = React.useMemo(() => {
    if (activeFilterCount !== undefined) return activeFilterCount;
    let n = localSearch.trim().length > 0 ? 1 : 0;
    if (filters.length > 0) {
      for (const f of filters) {
        const v = filterValues[f.key] ?? SENTINEL;
        if (v !== SENTINEL && v !== (f.defaultValue ?? SENTINEL)) n++;
      }
    }
    return n;
  }, [activeFilterCount, localSearch, filters, filterValues]);

  const hasAnything = computedActiveCount > 0;

  return (
    <div
      role="search"
      aria-label="Search and filter"
      className={cn(
        // Container: flex-wrap so it naturally stacks on small screens
        "flex flex-wrap items-center gap-2",
        "rounded-xl border border-border bg-background p-2",
        "dark:border-slate-700 dark:bg-slate-900/60",
        className
      )}
    >
      {/* ── Search input ─────────────────────────────────────────────── */}
      <div
        className={cn(
          // Full width on mobile, flex-grow on desktop
          "relative flex items-center",
          "min-w-0 w-full sm:w-auto sm:flex-1 sm:min-w-[180px]"
        )}
      >
        <Search
          aria-hidden="true"
          className="pointer-events-none absolute left-2.5 size-3.5 flex-shrink-0 text-muted-foreground"
        />

        <input
          ref={inputRef}
          type="search"
          role="searchbox"
          aria-label={searchPlaceholder}
          value={localSearch}
          onChange={handleSearchInput}
          placeholder={searchPlaceholder}
          autoComplete="off"
          spellCheck={false}
          className={cn(
            "h-8 w-full rounded-lg border border-input bg-transparent",
            "pl-8 pr-8 text-sm",
            "placeholder:text-muted-foreground",
            "transition-colors outline-none",
            "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
            "dark:border-slate-700 dark:bg-slate-800 dark:text-white",
            "dark:placeholder:text-slate-500",
            // hide default browser clear button — we render our own
            "[&::-webkit-search-cancel-button]:hidden [&::-webkit-search-decoration]:hidden"
          )}
        />

        {/* Clear search button — only shown when input has text */}
        {localSearch.length > 0 && (
          <button
            type="button"
            onClick={handleClearSearch}
            aria-label="Clear search"
            tabIndex={0}
            className={cn(
              "absolute right-2 flex items-center justify-center",
              "size-4 rounded-full",
              "text-muted-foreground hover:text-foreground",
              "hover:bg-muted",
              "transition-colors outline-none",
              "focus-visible:ring-2 focus-visible:ring-ring/50"
            )}
          >
            <X aria-hidden="true" className="size-3" />
          </button>
        )}
      </div>

      {/* ── Filter dropdowns ─────────────────────────────────────────── */}
      {filters.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          {filters.map((filter, i) => (
            <FilterDropdown
              key={filter.key}
              id={`${baseId}-filter-${i}`}
              filter={filter}
              value={filterValues[filter.key] ?? SENTINEL}
              onChange={(v) => onFilterChange?.(filter.key, v)}
            />
          ))}

          {/* Active filter count badge — floats after the last dropdown */}
          <ActiveFilterBadge count={computedActiveCount} />
        </div>
      )}

      {/* ── Clear all ────────────────────────────────────────────────── */}
      {hasAnything && (
        <button
          type="button"
          onClick={handleClearAll}
          aria-label="Clear all filters and search"
          className={cn(
            "inline-flex items-center gap-1",
            "h-8 rounded-lg px-2.5 text-sm font-medium",
            "text-muted-foreground hover:text-foreground",
            "hover:bg-muted",
            "transition-colors outline-none",
            "focus-visible:ring-2 focus-visible:ring-ring/50",
            "flex-shrink-0",
            "dark:text-slate-400 dark:hover:text-slate-200 dark:hover:bg-slate-800"
          )}
        >
          <X aria-hidden="true" className="size-3.5" />
          <span>Clear all</span>
        </button>
      )}

      {/* ── Action slot ──────────────────────────────────────────────── */}
      {actionSlot && (
        <div className="ml-auto flex items-center gap-2 flex-shrink-0">
          {actionSlot}
        </div>
      )}
    </div>
  );
}

export default SearchFilterBar;
