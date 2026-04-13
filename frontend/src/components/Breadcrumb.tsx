"use client";

import Link from "next/link";
import { ChevronRight, Home } from "lucide-react";
import { cn } from "@/lib/utils";

interface BreadcrumbItem {
  label: string;
  href?: string;
}

export function Breadcrumb({ items }: { items: BreadcrumbItem[] }) {
  return (
    <nav
      aria-label="Breadcrumb"
      className="flex items-center gap-1.5 text-sm text-muted-foreground mb-4"
    >
      <Link
        href="/"
        className="flex items-center gap-1 hover:text-foreground transition-colors rounded-md px-1.5 py-0.5 hover:bg-muted"
        aria-label="Home"
      >
        <Home className="h-3.5 w-3.5" />
      </Link>
      {items.map((item, i) => {
        const isLast = i === items.length - 1;
        return (
          <span key={item.label || item.href || i} className="flex items-center gap-1.5">
            <ChevronRight className="h-3 w-3 text-muted-foreground/50" />
            {item.href && !isLast ? (
              <Link
                href={item.href}
                className="hover:text-foreground transition-colors rounded-md px-1.5 py-0.5 hover:bg-muted"
              >
                {item.label}
              </Link>
            ) : (
              <span
                className={cn(
                  "px-1.5 py-0.5",
                  isLast && "text-foreground font-medium"
                )}
                aria-current={isLast ? "page" : undefined}
              >
                {item.label}
              </span>
            )}
          </span>
        );
      })}
    </nav>
  );
}
