"use client";

/**
 * CommandPalette — Global search / command palette triggered by Cmd+K.
 *
 * Usage (already wired in auth-layout.tsx):
 *   <CommandPalette open={open} onClose={() => setOpen(false)} />
 *
 * Trigger from anywhere:
 *   window.dispatchEvent(new CustomEvent("open-command-palette"))
 */

import { useEffect, useRef, useState, useCallback, CSSProperties } from "react";
import { useRouter } from "next/navigation";
import {
  Search,
  X,
  User,
  FileText,
  Zap,
  ArrowRight,
  Clock,
  LayoutDashboard,
  Users,
  ClipboardCheck,
  CalendarClock,
  Target,
  Microscope,
  Layers,
  FileImage,
  Workflow,
  BarChart3,
  UserCheck,
  Star,
  Send,
  Calculator,
  ShieldCheck,
  UsersRound,
  Code,
  Database,
  Settings,
} from "lucide-react";
import { searchPatients } from "@/lib/api";
import type { Patient } from "@/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ResultCategory = "patients" | "navigate" | "actions";

interface BaseResult {
  id: string;
  label: string;
  category: ResultCategory;
  description?: string;
}

interface PageResult extends BaseResult {
  category: "navigate";
  href: string;
  icon: React.ComponentType<{ style?: CSSProperties }>;
  shortcut?: string; // e.g. "g h"
}

interface PatientResult extends BaseResult {
  category: "patients";
  pid: string;
  dob?: string;
}

interface ActionResult extends BaseResult {
  category: "actions";
  href?: string;
  action?: () => void;
}

type SearchResult = PageResult | PatientResult | ActionResult;

// ---------------------------------------------------------------------------
// Static data
// ---------------------------------------------------------------------------

const PAGE_RESULTS: PageResult[] = [
  { id: "p-dash",    category: "navigate", label: "Dashboard",           href: "/",            icon: LayoutDashboard, description: "Overview & KPIs",           shortcut: "g h" },
  { id: "p-pat",     category: "navigate", label: "Patients",            href: "/patients",    icon: Users,           description: "Patient roster",            shortcut: "g p" },
  { id: "p-sus",     category: "navigate", label: "Review Queue",        href: "/review-queue",icon: ClipboardCheck,  description: "HCC suspects",              shortcut: "g s" },
  { id: "p-rec",     category: "navigate", label: "Recapture Gaps",      href: "/recapture",   icon: CalendarClock,   description: "Gap closure" },
  { id: "p-pro",     category: "navigate", label: "Prospective",         href: "/prospective", icon: Target,          description: "Prospective HCC" },
  { id: "p-ana",     category: "navigate", label: "Clinical Analysis",   href: "/analysis",    icon: Microscope,      description: "AI-powered HCC coding",     shortcut: "g a" },
  { id: "p-bat",     category: "navigate", label: "Batch Analysis",      href: "/batch",       icon: Layers,          description: "Bulk processing" },
  { id: "p-doc",     category: "navigate", label: "Documents",           href: "/documents",   icon: FileImage,       description: "Document uploads" },
  { id: "p-cla",     category: "navigate", label: "Claims",              href: "/claims",      icon: FileText,        description: "Claims data" },
  { id: "p-dem",     category: "navigate", label: "Pipeline Demo",       href: "/demo",        icon: Workflow,        description: "Demo pipeline" },
  { id: "p-rep",     category: "navigate", label: "Analytics",           href: "/reports",     icon: BarChart3,       description: "Reports & analytics",       shortcut: "g r" },
  { id: "p-prov",    category: "navigate", label: "Provider Performance", href: "/providers",  icon: UserCheck,       description: "Provider metrics" },
  { id: "p-qual",    category: "navigate", label: "Quality & STARS",     href: "/quality",     icon: Star,            description: "STARS measures" },
  { id: "p-sub",     category: "navigate", label: "CMS Submissions",     href: "/submissions", icon: Send,            description: "CMS data submissions" },
  { id: "p-roi",     category: "navigate", label: "ROI Calculator",      href: "/roi",         icon: Calculator,      description: "ROI estimates" },
  { id: "p-aud",     category: "navigate", label: "Compliance & Audit",  href: "/audit",       icon: ShieldCheck,     description: "Audit tools" },
  { id: "p-usr",     category: "navigate", label: "Users",               href: "/users",       icon: UsersRound,      description: "User management" },
  { id: "p-dev",     category: "navigate", label: "Developer",           href: "/developer",   icon: Code,            description: "Developer tools" },
  { id: "p-emr",     category: "navigate", label: "EMR Config",          href: "/emr-config",  icon: Database,        description: "EMR connections",           shortcut: "g e" },
  { id: "p-set",     category: "navigate", label: "Settings",            href: "/settings",    icon: Settings,        description: "Account settings" },
];

const ACTION_RESULTS: ActionResult[] = [
  {
    id: "a-accept-suspects",
    category: "actions",
    label: "Accept all suspects",
    description: "Bulk-accept every open HCC suspect in Review Queue",
    action: () => {
      window.dispatchEvent(new CustomEvent("cmd:accept-all-suspects"));
    },
  },
  {
    id: "a-pre-submission",
    category: "actions",
    label: "Run pre-submission validation",
    href: "/pre-submission",
    description: "Validate RAF data before CMS submission",
  },
  {
    id: "a-export-gaps",
    category: "actions",
    label: "Export gaps to CSV",
    description: "Download all open care gaps as a CSV file",
    action: () => {
      window.dispatchEvent(new CustomEvent("cmd:export-gaps-csv"));
    },
  },
  { id: "a-analysis",   category: "actions", label: "Run Analysis",        href: "/analysis",   description: "Open Clinical Analysis" },
  { id: "a-batch",      category: "actions", label: "Run Batch Analysis",  href: "/batch",      description: "Open Batch Analysis" },
  { id: "a-audit",      category: "actions", label: "Generate Audit",      href: "/audit",      description: "Open Compliance & Audit" },
  { id: "a-emr",        category: "actions", label: "Add EMR Connection",  href: "/emr-config", description: "Configure EMR" },
  { id: "a-settings",   category: "actions", label: "Open Settings",       href: "/settings",   description: "Account & preferences" },
];

// Category display config
const CATEGORY_LABELS: Record<ResultCategory, string> = {
  patients: "Patients",
  navigate: "Navigate",
  actions: "Actions",
};

const CATEGORY_ORDER: ResultCategory[] = ["patients", "navigate", "actions"];

const RECENT_KEY = "raf_command_recent";
const MAX_RECENT = 5;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function loadRecent(): SearchResult[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function saveRecent(item: SearchResult) {
  try {
    const prev = loadRecent().filter((r) => r.id !== item.id);
    localStorage.setItem(RECENT_KEY, JSON.stringify([item, ...prev].slice(0, MAX_RECENT)));
  } catch {
    // ignore
  }
}

function matchesQuery(label: string, description: string | undefined, q: string): boolean {
  const lq = q.toLowerCase();
  return label.toLowerCase().includes(lq) || (description ?? "").toLowerCase().includes(lq);
}

// ---------------------------------------------------------------------------
// Design tokens (matching Sidebar)
// ---------------------------------------------------------------------------
const BG_MODAL = "#0F172A";
const BG_OVERLAY = "rgba(0,0,0,0.7)";
const BG_INPUT = "#1E293B";
const BG_ITEM_HOVER = "#1E293B";
const BG_ITEM_ACTIVE = "#2563EB";
const BORDER = "#334155";
const TEXT_PRIMARY = "#F1F5F9";
const TEXT_SECONDARY = "#94A3B8";
const TEXT_CATEGORY = "#64748B";
const ACCENT = "#60A5FA";

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [recentSearches, setRecentSearches] = useState<SearchResult[]>(() => loadRecent());
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [prevOpen, setPrevOpen] = useState(open);

  // Reset state when opened (synchronous during render)
  if (open && !prevOpen) {
    setPrevOpen(open);
    setQuery("");
    setResults([...PAGE_RESULTS, ...ACTION_RESULTS]);
    setActiveIndex(0);
  }
  if (open !== prevOpen) {
    setPrevOpen(open);
  }

  // Focus input when opened
  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [open]);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape" && open) {
        onClose();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  // Search logic
  const runSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      // Show all pages + actions by default when query is empty
      setResults([...PAGE_RESULTS, ...ACTION_RESULTS]);
      setLoading(false);
      return;
    }

    setLoading(true);

    const pageMatches: PageResult[] = PAGE_RESULTS.filter((p) =>
      matchesQuery(p.label, p.description, q) ||
      (p.shortcut && p.shortcut.toLowerCase().includes(q.toLowerCase()))
    );

    const actionMatches: ActionResult[] = ACTION_RESULTS.filter((a) =>
      matchesQuery(a.label, a.description, q)
    );

    let patientMatches: PatientResult[] = [];
    try {
      const res = await searchPatients({ search: q, limit: 5 });
      const patients: Patient[] = Array.isArray(res) ? res : (res as { patients?: Patient[] }).patients ?? [];
      patientMatches = patients.map((p: Patient) => ({
        id: `patient-${p.pid}`,
        category: "patients" as const,
        label: `${p.fname ?? ""} ${p.lname ?? ""}`.trim() || `PID ${p.pid}`,
        pid: String(p.pid),
        description: `PID: ${p.pid}${p.DOB ? ` · DOB: ${p.DOB}` : ""}`,
        dob: p.DOB,
      }));
    } catch {
      // Patient search fails silently — still show page/action results
    }

    setResults([...patientMatches, ...pageMatches, ...actionMatches]);
    setActiveIndex(0);
    setLoading(false);
  }, []);

  // Debounced query handler
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => runSearch(query), 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, runSearch]);

  // Keyboard navigation
  const handleKeyDown = (e: React.KeyboardEvent) => {
    const list = results;
    if (!list.length) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(i + 1, list.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      selectResult(list[activeIndex]);
    }
  };

  // Scroll active item into view
  useEffect(() => {
    const active = listRef.current?.querySelector("[data-active='true']");
    active?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);

  function selectResult(result: SearchResult) {
    saveRecent(result);
    setRecentSearches(loadRecent());

    if (result.category === "patients") {
      router.push(`/patients/${(result as PatientResult).pid}`);
    } else if (result.category === "navigate") {
      router.push((result as PageResult).href);
    } else {
      const action = result as ActionResult;
      if (action.action) {
        action.action();
      } else if (action.href) {
        router.push(action.href);
      }
    }
    onClose();
  }

  if (!open) return null;

  const displayList = results;
  const showRecent = !query.trim() && recentSearches.length > 0;
  const isEmpty = !loading && query.trim().length > 0 && results.length === 0;

  // Group results by category
  const grouped: Partial<Record<ResultCategory, SearchResult[]>> = {};
  for (const result of displayList) {
    if (!grouped[result.category]) grouped[result.category] = [];
    grouped[result.category]!.push(result);
  }

  // Build flat indexed list for keyboard nav
  const flatList: SearchResult[] = CATEGORY_ORDER.flatMap(
    (cat) => grouped[cat] ?? []
  );

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 9999,
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        paddingTop: "clamp(60px, 10vh, 120px)",
        backgroundColor: BG_OVERLAY,
        backdropFilter: "blur(4px)",
      }}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label="Command palette"
    >
      <div
        className="backdrop-blur-card animate-scale-in"
        style={{
          width: "100%",
          maxWidth: 600,
          margin: "0 16px",
          backgroundColor: BG_MODAL,
          border: `1px solid ${BORDER}`,
          borderRadius: 10,
          overflow: "hidden",
          boxShadow: "0 25px 60px rgba(0,0,0,0.6), 0 0 80px rgba(37,99,235,0.08)",
          fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search input */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "14px 16px",
            borderBottom: `1px solid ${BORDER}`,
          }}
        >
          <Search style={{ width: 18, height: 18, color: TEXT_SECONDARY, flexShrink: 0 }} aria-hidden />
          <input
            ref={inputRef}
            type="text"
            placeholder="Search patients, pages, actions..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            className="command-palette-input"
            style={{
              flex: 1,
              background: "none",
              border: "none",
              fontSize: 15,
              color: TEXT_PRIMARY,
              caretColor: ACCENT,
            }}
            aria-label="Search"
            aria-autocomplete="list"
            aria-controls="command-results"
            role="combobox"
            aria-expanded={displayList.length > 0}
            aria-activedescendant={
              flatList[activeIndex] ? `cmd-item-${flatList[activeIndex].id}` : undefined
            }
          />
          {loading && (
            <div
              style={{
                width: 16,
                height: 16,
                border: `2px solid ${BORDER}`,
                borderTopColor: ACCENT,
                borderRadius: "50%",
                animation: "spin 0.6s linear infinite",
                flexShrink: 0,
              }}
              aria-label="Searching..."
            />
          )}
          <button
            onClick={onClose}
            style={{
              background: "none",
              border: `1px solid ${BORDER}`,
              borderRadius: 4,
              padding: "2px 6px",
              cursor: "pointer",
              color: TEXT_SECONDARY,
              fontSize: 11,
              flexShrink: 0,
            }}
            aria-label="Close command palette"
          >
            Esc
          </button>
        </div>

        {/* Results */}
        <div
          id="command-results"
          ref={listRef}
          role="listbox"
          aria-label="Search results"
          style={{
            maxHeight: 420,
            overflowY: "auto",
            padding: "8px 0",
          }}
        >
          {showRecent && (
            <div
              style={{
                padding: "6px 16px 4px",
                fontSize: 11,
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                color: TEXT_CATEGORY,
                display: "flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              <Clock style={{ width: 12, height: 12 }} aria-hidden />
              Recent
            </div>
          )}

          {isEmpty && (
            <div
              style={{
                padding: "32px 16px",
                textAlign: "center",
                color: TEXT_SECONDARY,
                fontSize: 14,
              }}
            >
              No results for &quot;{query}&quot;
            </div>
          )}

          {CATEGORY_ORDER.map((cat) => {
            const items = grouped[cat];
            if (!items || items.length === 0) return null;

            return (
              <div key={cat}>
                {!showRecent && (
                  <div
                    style={{
                      padding: "8px 16px 4px",
                      fontSize: 11,
                      fontWeight: 600,
                      textTransform: "uppercase",
                      letterSpacing: "0.08em",
                      color: TEXT_CATEGORY,
                    }}
                  >
                    {CATEGORY_LABELS[cat]}
                  </div>
                )}
                {items.map((result) => {
                  const flatIdx = flatList.findIndex((r) => r.id === result.id);
                  const isActive = flatIdx === activeIndex;

                  return (
                    <button
                      key={result.id}
                      id={`cmd-item-${result.id}`}
                      role="option"
                      aria-selected={isActive}
                      data-active={isActive}
                      onClick={() => selectResult(result)}
                      onMouseEnter={() => setActiveIndex(flatIdx)}
                      className={isActive ? "" : "hover-lift"}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        width: "100%",
                        padding: "8px 16px",
                        background: isActive ? BG_ITEM_ACTIVE : "transparent",
                        border: "none",
                        cursor: "pointer",
                        textAlign: "left",
                        borderRadius: 6,
                        transition: "background 100ms, transform 150ms, box-shadow 150ms",
                      }}
                    >
                      {/* Icon */}
                      <div
                        style={{
                          width: 32,
                          height: 32,
                          borderRadius: 6,
                          backgroundColor: isActive ? "rgba(255,255,255,0.15)" : BG_INPUT,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          flexShrink: 0,
                        }}
                      >
                        {result.category === "patients" ? (
                          <User style={{ width: 15, height: 15, color: isActive ? "#fff" : ACCENT }} aria-hidden />
                        ) : result.category === "actions" ? (
                          <Zap style={{ width: 15, height: 15, color: isActive ? "#fff" : "#A78BFA" }} aria-hidden />
                        ) : (
                          (() => {
                            const PageIcon = (result as PageResult).icon;
                            return <PageIcon style={{ width: 15, height: 15, color: isActive ? "#fff" : TEXT_SECONDARY }} aria-hidden />;
                          })()
                        )}

                      </div>

                      {/* Text */}
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div
                          style={{
                            fontSize: 14,
                            fontWeight: 500,
                            color: isActive ? "#fff" : TEXT_PRIMARY,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {result.label}
                        </div>
                        {result.description && (
                          <div
                            style={{
                              fontSize: 12,
                              color: isActive ? "rgba(255,255,255,0.7)" : TEXT_SECONDARY,
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                              whiteSpace: "nowrap",
                            }}
                          >
                            {result.description}
                          </div>
                        )}
                      </div>

                      {/* Keyboard shortcut hint */}
                      {result.category === "navigate" && (result as PageResult).shortcut && (
                        <span
                          style={{
                            display: "flex",
                            gap: 3,
                            flexShrink: 0,
                            marginLeft: "auto",
                          }}
                          aria-label={`Shortcut: ${(result as PageResult).shortcut}`}
                        >
                          {((result as PageResult).shortcut as string).split(" ").map((k) => (
                            <kbd
                              key={k}
                              style={{
                                backgroundColor: isActive ? "rgba(255,255,255,0.15)" : BG_INPUT,
                                border: `1px solid ${isActive ? "rgba(255,255,255,0.3)" : BORDER}`,
                                borderRadius: 3,
                                padding: "1px 5px",
                                fontSize: 10,
                                fontFamily: "inherit",
                                color: isActive ? "rgba(255,255,255,0.85)" : TEXT_SECONDARY,
                                lineHeight: "16px",
                              }}
                            >
                              {k}
                            </kbd>
                          ))}
                        </span>
                      )}

                      {/* Arrow indicator */}
                      {isActive && (
                        <ArrowRight
                          style={{ width: 14, height: 14, color: "rgba(255,255,255,0.7)", flexShrink: 0 }}
                          aria-hidden
                        />
                      )}
                    </button>
                  );
                })}
              </div>
            );
          })}

          {!loading && results.length === 0 && !query.trim() && (
            <div
              style={{
                padding: "24px 16px",
                textAlign: "center",
                color: TEXT_SECONDARY,
                fontSize: 13,
              }}
            >
              Start typing to search patients, pages, or actions.
            </div>
          )}
        </div>

        {/* Footer hint */}
        <div
          style={{
            display: "flex",
            gap: 16,
            padding: "8px 16px",
            borderTop: `1px solid ${BORDER}`,
            fontSize: 11,
            color: TEXT_CATEGORY,
          }}
        >
          {[
            { keys: ["↑", "↓"], label: "navigate" },
            { keys: ["↵"], label: "select" },
            { keys: ["Esc"], label: "close" },
          ].map(({ keys, label }) => (
            <span key={label} style={{ display: "flex", alignItems: "center", gap: 4 }}>
              {keys.map((k) => (
                <kbd
                  key={k}
                  style={{
                    backgroundColor: BG_INPUT,
                    border: `1px solid ${BORDER}`,
                    borderRadius: 3,
                    padding: "1px 5px",
                    fontSize: 11,
                    fontFamily: "inherit",
                    color: TEXT_SECONDARY,
                  }}
                >
                  {k}
                </kbd>
              ))}
              <span>{label}</span>
            </span>
          ))}
        </div>
      </div>

      {/* Spin animation + input focus gradient */}
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        .command-palette-input:focus {
          background: linear-gradient(90deg, rgba(37,99,235,0.06) 0%, transparent 100%) !important;
        }
      `}</style>
    </div>
  );
}
