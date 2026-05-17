"use client";

/**
 * Pre-Submission Validation Dashboard.
 *
 * Mirrors the Edifecs RAEM workflow: surface coding-rule violations
 * BEFORE the 837/EDPS file is generated so the coding team can fix
 * issues that would otherwise be rejected (or, worse, paid then clawed
 * back at RADV).
 *
 * Data: GET /api/pre-submission/validate?year=<int>
 *
 *   { year, tenant_id, total,
 *     rule_counts: {R1, R2, R3, R4, R5},
 *     severity_counts: {HIGH, MEDIUM, LOW},
 *     rule_descriptions: { R1: "Missing MEAT — ...", ... },
 *     items: [{ rule_id, severity, hcc_id, hcc_code, icd10, patient_id, message }, ...]
 *   }
 *
 * The page is read-only; backend never mutates raf_patient_hcc.
 */

import React, { useMemo, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, AlertCircle, Info, ShieldCheck, ExternalLink } from "lucide-react";

import api from "@/lib/api";
import { PageHeader, StatCard, EmptyState } from "@/components/healthcare-ui";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Finding {
  rule_id: string;
  severity: "HIGH" | "MEDIUM" | "LOW";
  hcc_id: number;
  hcc_code: number | null;
  icd10: string | null;
  patient_id: number;
  message: string;
}

interface ValidateResponse {
  year: number;
  tenant_id: number;
  total: number;
  rule_counts: Record<string, number>;
  severity_counts: Record<"HIGH" | "MEDIUM" | "LOW", number>;
  rule_descriptions: Record<string, string>;
  items: Finding[];
}

// ---------------------------------------------------------------------------
// Year options — current year + 3 back, + 1 forward (covers all open sweeps).
// ---------------------------------------------------------------------------

function buildYearOptions(currentYear: number): number[] {
  const out: number[] = [];
  for (let y = currentYear + 1; y >= currentYear - 3; y--) out.push(y);
  return out;
}

// ---------------------------------------------------------------------------
// Severity chip
// ---------------------------------------------------------------------------

function SeverityChip({ severity }: { severity: Finding["severity"] }) {
  // Use semantic tokens; the Tailwind utility palette already has destructive
  // (red) / warning-like (amber) / muted (slate) covered. We map by severity.
  const styles: Record<Finding["severity"], { cls: string; label: string }> = {
    HIGH:   { cls: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-200 border border-red-200 dark:border-red-800",                label: "HIGH"   },
    MEDIUM: { cls: "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-200 border border-amber-200 dark:border-amber-800",     label: "MEDIUM" },
    LOW:    { cls: "bg-slate-100 text-slate-700 dark:bg-slate-800/60 dark:text-slate-200 border border-slate-200 dark:border-slate-700",      label: "LOW"    },
  };
  const s = styles[severity];
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${s.cls}`}
      aria-label={`Severity: ${s.label}`}
    >
      {s.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function PreSubmissionPage() {
  const currentYear = new Date().getFullYear();
  const [year, setYear] = useState<number>(currentYear);

  const { data, isLoading, isError, error, refetch, isFetching } = useQuery<ValidateResponse>({
    queryKey: ["pre-submission-validate", year],
    queryFn: async () => {
      const res = await api.get<ValidateResponse>(
        `/api/pre-submission/validate`,
        { params: { year } }
      );
      return res.data;
    },
    staleTime: 30_000,
  });

  const yearOptions = useMemo(() => buildYearOptions(currentYear), [currentYear]);

  const high = data?.severity_counts?.HIGH ?? 0;
  const medium = data?.severity_counts?.MEDIUM ?? 0;
  const low = data?.severity_counts?.LOW ?? 0;
  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <main id="main-content" className="p-6 space-y-6">
      <PageHeader
        title="Pre-submission validation"
        subtitle="Catch coding-rule violations before the 837/EDPS file ships — Edifecs-RAEM-style."
        icon={<ShieldCheck size={22} />}
        actions={
          <div className="flex items-center gap-2">
            <label htmlFor="presub-year" className="text-sm text-muted-foreground">
              Measurement year
            </label>
            <select
              id="presub-year"
              value={year}
              onChange={(e) => setYear(Number(e.target.value))}
              className="rounded-md border border-border bg-background px-3 py-1.5 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-primary"
              aria-label="Measurement year"
            >
              {yearOptions.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          </div>
        }
      />

      {/* KPI tiles */}
      <section
        className="grid grid-cols-1 md:grid-cols-3 gap-4"
        aria-label="Severity totals"
      >
        <StatCard
          label="High severity"
          value={high}
          subtitle="Will be rejected by CMS"
          icon={<AlertCircle size={20} />}
          accentClassName="text-red-700 bg-red-100 dark:text-red-200 dark:bg-red-900/30"
          loading={isLoading}
        />
        <StatCard
          label="Medium severity"
          value={medium}
          subtitle="Risk of RADV reversal"
          icon={<AlertTriangle size={20} />}
          accentClassName="text-amber-700 bg-amber-100 dark:text-amber-200 dark:bg-amber-900/30"
          loading={isLoading}
        />
        <StatCard
          label="Low severity"
          value={low}
          subtitle="Advisory — review when possible"
          icon={<Info size={20} />}
          accentClassName="text-slate-700 bg-slate-100 dark:text-slate-200 dark:bg-slate-800/60"
          loading={isLoading}
        />
      </section>

      {/* Rule descriptions strip — small static reference so the table is self-explanatory */}
      {data?.rule_descriptions && (
        <section
          aria-label="Rule reference"
          className="rounded-lg border border-border bg-card p-4 text-xs text-muted-foreground"
        >
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
            {Object.entries(data.rule_descriptions).map(([rid, desc]) => (
              <div key={rid} className="flex gap-2">
                <span className="font-mono font-semibold text-foreground">{rid}</span>
                <span>{desc}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Findings table */}
      <section aria-label="Findings" className="rounded-lg border border-border bg-card">
        <header className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">
            Findings
            {!isLoading && (
              <span className="ml-2 text-muted-foreground font-normal">
                {total === 0
                  ? "(0)"
                  : items.length < total
                    ? `(showing top ${items.length} of ${total})`
                    : `(${total})`}
              </span>
            )}
          </h2>
          <button
            type="button"
            onClick={() => refetch()}
            disabled={isFetching}
            className="rounded-md border border-border bg-background px-3 py-1 text-xs font-medium hover:bg-muted disabled:opacity-50"
            aria-label="Re-run validation"
          >
            {isFetching ? "Re-running…" : "Re-run"}
          </button>
        </header>

        {isError ? (
          <div className="p-6">
            <EmptyState
              icon={<AlertCircle size={32} />}
              title="Could not load findings"
              description={(error as Error)?.message || "Please retry in a moment."}
            />
          </div>
        ) : isLoading ? (
          <div className="p-4 space-y-2" aria-busy="true">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-10 rounded-md bg-muted animate-pulse" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={<ShieldCheck size={32} />}
              title="All clear — ready to submit"
              description={`No coding-rule violations found for measurement year ${year}. Generate the 837/EDPS file with confidence.`}
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-muted-foreground bg-muted/40">
                <tr>
                  <th scope="col" className="px-4 py-2 font-medium">Rule</th>
                  <th scope="col" className="px-4 py-2 font-medium">Severity</th>
                  <th scope="col" className="px-4 py-2 font-medium">HCC</th>
                  <th scope="col" className="px-4 py-2 font-medium">ICD-10</th>
                  <th scope="col" className="px-4 py-2 font-medium">Patient</th>
                  <th scope="col" className="px-4 py-2 font-medium">Message</th>
                </tr>
              </thead>
              <tbody>
                {items.map((f) => (
                  <tr
                    key={f.hcc_id + ":" + f.rule_id + ":" + (f.icd10 ?? "")}
                    className="border-t border-border align-top hover:bg-muted/30"
                  >
                    <td className="px-4 py-2 font-mono text-xs">
                      <div className="font-semibold">{f.rule_id}</div>
                      <div className="text-muted-foreground text-[11px]">
                        {data?.rule_descriptions?.[f.rule_id]?.split("—")[0]?.trim()}
                      </div>
                    </td>
                    <td className="px-4 py-2">
                      <SeverityChip severity={f.severity} />
                    </td>
                    <td className="px-4 py-2 font-mono text-xs">
                      {f.hcc_code ?? <span className="text-muted-foreground italic">unmapped</span>}
                    </td>
                    <td className="px-4 py-2 font-mono text-xs">
                      {f.icd10 ?? <span className="text-muted-foreground">—</span>}
                    </td>
                    <td className="px-4 py-2">
                      <Link
                        href={`/patients/${f.patient_id}`}
                        className="inline-flex items-center gap-1 text-primary hover:underline"
                      >
                        #{f.patient_id}
                        <ExternalLink size={12} aria-hidden />
                      </Link>
                    </td>
                    <td className="px-4 py-2 text-muted-foreground">
                      {f.message}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
