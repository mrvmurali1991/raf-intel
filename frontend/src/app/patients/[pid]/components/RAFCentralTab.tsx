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
    <div className="w-full">
      <RAFCentralPanel patientId={Number(pid)} year={year} layout="dashboard" />
    </div>
  );
}

export default RAFCentralTab;
