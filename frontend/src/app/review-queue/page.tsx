"use client";

/**
 * /review-queue — shell page.
 *
 * perf(rsc): The full review queue (~661 lines) is extracted to ReviewQueueClient.tsx
 * and lazy-loaded with dynamic({ ssr: false }). This:
 *   - Eliminates SSR parse cost for the heavy interactive table
 *   - Prevents server-side execution of react-query / axios hooks
 *   - Shows a skeleton immediately while the client bundle hydrates
 *
 * TODO(rsc-server-shell): Convert this to a true Server Component that fetches
 * initial items server-side and passes them as `initialItems` prop to
 * ReviewQueueClient. Blocked by auth model: Bearer token lives in client memory.
 * Unblock by switching to HttpOnly cookie auth. See ReviewQueueClient.tsx for
 * the full TODO spec.
 */

import dynamic from "next/dynamic";
import { ClipboardList } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import {
  Table,
  TableHeader,
  TableRow,
  TableHead,
  TableBody,
  TableCell,
} from "@/components/ui/table";

/* ------------------------------------------------------------------ */
/* Skeleton shimmer row                                                 */
/* ------------------------------------------------------------------ */
function SkeletonRow({ delay }: { delay: string }) {
  const widths = ["w-40", "w-56", "w-20", "w-28", "w-20", "w-40"];
  return (
    <TableRow aria-hidden="true">
      {widths.map((w, j) => (
        <TableCell key={j}>
          <div
            className={`h-3.5 ${w} rounded bg-gradient-to-r from-slate-100 via-slate-200 to-slate-100 bg-[length:200%_100%] animate-[rq-shimmer_1.4s_infinite]`}
            style={{ animationDelay: delay }}
          />
        </TableCell>
      ))}
    </TableRow>
  );
}

/* ------------------------------------------------------------------ */
/* Loading skeleton — shown while the client bundle hydrates           */
/* ------------------------------------------------------------------ */
function ReviewQueueSkeleton() {
  return (
    <div className="min-h-screen bg-background p-6">
      <style>{`
        @keyframes rq-shimmer {
          0%   { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
      `}</style>

      <PageHeader
        title="Coder Review"
        subtitle="AI-generated work items pending coder review. Every decision is written to the audit log."
        icon={<ClipboardList size={20} />}
      />

      {/* Tab bar skeleton */}
      <div className="w-96 h-9 rounded-lg bg-slate-200 mb-4" />

      {/* Table skeleton */}
      <div
        className="rounded-xl border border-border overflow-hidden bg-card"
        aria-busy="true"
        aria-label="Loading review queue items"
      >
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/50">
              {["Patient", "Condition / Evidence", "HCC", "Confidence", "MEAT", "Actions"].map((h) => (
                <TableHead
                  key={h}
                  className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground"
                >
                  {h}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {Array.from({ length: 5 }).map((_, i) => (
              <SkeletonRow key={i} delay={`${i * 0.08}s`} />
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Empty state — exported so ReviewQueueClient can import it           */
/* ------------------------------------------------------------------ */
export function ReviewQueueEmpty() {
  return (
    <div
      className="flex flex-col items-center justify-center py-16 px-6 text-center"
      role="status"
    >
      <div className="w-14 h-14 rounded-xl bg-muted flex items-center justify-center mb-4 text-muted-foreground">
        <ClipboardList size={28} aria-hidden="true" />
      </div>
      <h3 className="text-[15px] font-semibold text-foreground mb-1">
        No items pending review
      </h3>
      <p className="text-[13px] text-muted-foreground max-w-xs leading-relaxed">
        All candidates have been reviewed. Check back later or switch tabs to see other categories.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Lazy-loaded interactive client                                       */
/* ------------------------------------------------------------------ */
const ReviewQueueClient = dynamic(
  () => import("./ReviewQueueClient"),
  { ssr: false, loading: ReviewQueueSkeleton },
);

/* ------------------------------------------------------------------ */
/* Page entry point                                                     */
/* ------------------------------------------------------------------ */
export default function ReviewQueuePage() {
  return <ReviewQueueClient />;
}
