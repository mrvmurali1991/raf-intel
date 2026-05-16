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
import { tokens } from "@/styles/tokens";

function ReviewQueueSkeleton() {
  return (
    <div style={{
      minHeight: "100vh",
      padding: "32px 40px 48px",
      background: tokens.slate50,
    }}>
      {/* Header skeleton */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 24 }}>
        <div style={{ width: 48, height: 48, borderRadius: 14, background: tokens.slate200 }} />
        <div>
          <div style={{ width: 160, height: 24, borderRadius: 6, background: tokens.slate200, marginBottom: 8 }} />
          <div style={{ width: 280, height: 14, borderRadius: 6, background: tokens.slate100 }} />
        </div>
      </div>
      {/* Tab bar skeleton */}
      <div style={{ width: 380, height: 38, borderRadius: 10, background: tokens.slate200, marginBottom: 16 }} />
      {/* Table skeleton */}
      <div style={{ border: `1px solid ${tokens.slate200}`, borderRadius: 14, overflow: "hidden" }}>
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} style={{
            display: "grid",
            gridTemplateColumns: "1.4fr 2fr 110px 140px 120px 200px",
            gap: 14,
            padding: "14px 22px",
            borderBottom: i < 4 ? `1px solid ${tokens.slate100}` : "none",
            alignItems: "center",
          }}>
            {[160, 220, 80, 110, 80, 160].map((w, j) => (
              <div key={j} style={{
                height: 14, width: w, borderRadius: 6,
                background: `linear-gradient(90deg, ${tokens.slate100} 25%, ${tokens.slate200} 50%, ${tokens.slate100} 75%)`,
                backgroundSize: "200% 100%",
                animation: "rq-ske-shimmer 1.4s infinite",
                animationDelay: `${i * 0.08}s`,
              }} />
            ))}
          </div>
        ))}
      </div>
      <style>{`@keyframes rq-ske-shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }`}</style>
    </div>
  );
}

const ReviewQueueClient = dynamic(
  () => import("./ReviewQueueClient"),
  { ssr: false, loading: ReviewQueueSkeleton },
);

export default function ReviewQueuePage() {
  return <ReviewQueueClient />;
}
