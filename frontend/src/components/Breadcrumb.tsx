"use client";

/**
 * Breadcrumb — lightweight auto-generating breadcrumb nav.
 *
 * Usage:
 *   <Breadcrumb items={[
 *     { label: "Patients", href: "/patients" },
 *     { label: "Jane Doe" },          // last item — no href, rendered bold
 *   ]} />
 *
 * Rules:
 *   - Last item is always the current page: no link, font-medium, text-foreground
 *   - All prior items with an href render as links (text-muted-foreground, hover underline)
 *   - Prior items without an href render as plain muted text (e.g. a static label)
 *   - Separator: ChevronRight, small and muted
 *   - Compact: text-sm throughout
 *   - Fully accessible: nav[aria-label], aria-current="page" on last item
 */

import Link from "next/link";
import { ChevronRight } from "lucide-react";

export interface BreadcrumbItem {
  label: string;
  href?: string;
}

interface BreadcrumbProps {
  items: BreadcrumbItem[];
  className?: string;
}

export function Breadcrumb({ items, className = "" }: BreadcrumbProps) {
  if (!items || items.length === 0) return null;

  return (
    <nav
      aria-label="Breadcrumb"
      className={`flex items-center flex-wrap gap-0.5 text-sm mb-4 ${className}`}
    >
      <ol className="flex items-center flex-wrap gap-0.5 list-none m-0 p-0">
        {items.map((item, i) => {
          const isLast = i === items.length - 1;

          return (
            <li key={`${item.label}-${i}`} className="flex items-center gap-0.5">
              {/* Separator — not shown before the very first item */}
              {i > 0 && (
                <ChevronRight
                  className="h-3 w-3 text-muted-foreground/40 mx-0.5 flex-shrink-0"
                  aria-hidden="true"
                />
              )}

              {isLast ? (
                // Current page: no link, bold, full foreground color
                <span
                  className="font-medium text-foreground px-0.5"
                  aria-current="page"
                >
                  {item.label}
                </span>
              ) : item.href ? (
                // Ancestor with href: link, muted, hover underline
                <Link
                  href={item.href}
                  className="text-muted-foreground hover:text-foreground hover:underline underline-offset-2 transition-colors px-0.5 rounded"
                >
                  {item.label}
                </Link>
              ) : (
                // Ancestor without href: plain muted text (static label)
                <span className="text-muted-foreground px-0.5">
                  {item.label}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
