"use client";

/**
 * AttributeOrphansBanner
 * ----------------------
 * Yellow banner shown when there are recapture gaps with no attributed
 * provider (NULL provider_npi). Clicking the action button calls
 * ``POST /api/recapture/orphan-gaps/attribute`` and re-queries the orphan
 * count.
 */

import { useMemo, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Wand2, Loader2, CheckCircle2 } from "lucide-react";
import {
  attributeOrphanGaps,
  listRecaptureGaps,
  type AttributeOrphansResult,
} from "@/lib/api";

export default function AttributeOrphansBanner() {
  const qc = useQueryClient();
  const [lastResult, setLastResult] = useState<AttributeOrphansResult | null>(null);

  // Fetch a sample of open gaps to count orphans (NULL provider_npi).
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["recapture-gaps", "orphan-scan"],
    queryFn: () => listRecaptureGaps({ status: "open", limit: 500 }),
  });

  const orphanCount = useMemo(() => {
    return (data ?? []).filter((g) => !g.provider_npi).length;
  }, [data]);

  const mutation = useMutation({
    mutationFn: () => attributeOrphanGaps(),
    onSuccess: async (result) => {
      setLastResult(result);
      // Invalidate gap-related queries so the table re-fetches.
      await qc.invalidateQueries({ queryKey: ["recapture-gaps"] });
      await refetch();
    },
  });

  if (isLoading) return null;
  if (orphanCount === 0 && !lastResult) return null;

  return (
    <div
      role="status"
      style={{
        margin: "0 0 16px",
        padding: "12px 16px",
        borderRadius: 10,
        background: "#FEF3C7",
        border: "1px solid #FCD34D",
        color: "#78350F",
        display: "flex", alignItems: "center", gap: 12,
      }}
    >
      {lastResult ? (
        <CheckCircle2 size={18} style={{ flexShrink: 0, color: "#047857" }} />
      ) : (
        <AlertTriangle size={18} style={{ flexShrink: 0 }} />
      )}

      <div style={{ flex: 1, fontSize: 13, lineHeight: 1.4 }}>
        {lastResult ? (
          <span style={{ color: "#065F46" }}>
            Attribution complete — checked <strong>{lastResult.checked}</strong>,
            updated <strong>{lastResult.updated}</strong>,
            still orphan <strong>{lastResult.still_orphan}</strong>.
          </span>
        ) : (
          <span>
            <strong>{orphanCount}</strong> recapture{" "}
            {orphanCount === 1 ? "gap has" : "gaps have"} no attributed provider.
            Run attribution to backfill them from the patient panel.
          </span>
        )}
      </div>

      <button
        type="button"
        onClick={() => {
          setLastResult(null);
          mutation.mutate();
        }}
        disabled={mutation.isPending}
        style={{
          display: "inline-flex", alignItems: "center", gap: 6,
          padding: "8px 14px", borderRadius: 8, border: "none",
          background: mutation.isPending ? "#FCD34D" : "#F59E0B",
          color: "#fff", fontSize: 13, fontWeight: 600,
          cursor: mutation.isPending ? "not-allowed" : "pointer",
        }}
      >
        {mutation.isPending ? <Loader2 size={14} className="animate-spin" /> : <Wand2 size={14} />}
        {mutation.isPending ? "Running…" : "Run attribution"}
      </button>
    </div>
  );
}
