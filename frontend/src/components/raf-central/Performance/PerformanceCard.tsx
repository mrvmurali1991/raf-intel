"use client";

import type { AuditReadiness } from "../_shared";
import { AuditDonut } from "./AuditDonut";

/**
 * AuditSection (PerformanceCard) — MEAT compliance donut used in the panel accordion.
 */
export function AuditSection({ audit }: { audit: AuditReadiness }) {
  return (
    <div className="pt-1">
      <AuditDonut
        compliant={audit.hccs_compliant}
        total={audit.hccs_total}
        riskLevel={audit.risk_level}
      />
    </div>
  );
}
