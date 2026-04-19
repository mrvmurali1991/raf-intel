"use client";

/**
 * RAFCentralTab
 * -------------
 * Thin wrapper around RAFCentralPanel so the unified RAF intelligence panel
 * is viewable inside the main app (not just the OpenEMR embed iframe).
 */

import { RAFCentralPanel } from "@/components/RAFCentralPanel";

export function RAFCentralTab({
  pid,
  year,
}: {
  pid: string;
  year: number;
}) {
  return (
    <div className="mx-auto max-w-4xl overflow-hidden rounded-lg border bg-background shadow-sm">
      <RAFCentralPanel patientId={Number(pid)} year={year} />
    </div>
  );
}

export default RAFCentralTab;
