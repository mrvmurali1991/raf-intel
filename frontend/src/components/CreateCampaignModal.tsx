"use client";

/**
 * CreateCampaignModal — multi-step wizard for bulk recapture campaigns.
 *
 *   Step 1 — Name + description + target close date
 *   Step 2 — Filter (HCC codes multiselect, min revenue, days_open)
 *   Step 3 — Preview match count + per-HCC breakdown
 *   Step 4 — Pick coders + distribution strategy
 *   Step 5 — Confirm: creates the campaign and bulk-assigns
 *
 * Emits a ``recapture-campaigns:changed`` window event after a successful
 * assign so RecaptureCampaignList re-fetches.
 */

import React, { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X, ChevronLeft, ChevronRight, CheckCircle2 } from "lucide-react";

import {
  assignRecaptureCampaign,
  createRecaptureCampaign,
  listEligibleCoders,
  previewRecaptureFilter,
  type EligibleCoder,
  type RecaptureFilterCriteria,
} from "@/lib/api";

interface Props {
  open: boolean;
  onClose: () => void;
}

type Step = 1 | 2 | 3 | 4 | 5;

const COMMON_HCC_CODES: Array<{ code: string; label: string }> = [
  { code: "18",  label: "HCC 18 — Diabetes w/ chronic complications" },
  { code: "19",  label: "HCC 19 — Diabetes without complications" },
  { code: "85",  label: "HCC 85 — Congestive Heart Failure" },
  { code: "108", label: "HCC 108 — Vascular Disease" },
  { code: "111", label: "HCC 111 — COPD" },
  { code: "138", label: "HCC 138 — CKD Stage 3" },
];

function formatCurrency(n: number): string {
  return "$" + Math.round(n).toLocaleString("en-US");
}

export default function CreateCampaignModal({ open, onClose }: Props) {
  const [step, setStep] = useState<Step>(1);

  // Step 1
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [targetDate, setTargetDate] = useState("");

  // Step 2 — filter
  const [hccCodes, setHccCodes] = useState<string[]>([]);
  const [hccCustom, setHccCustom] = useState("");
  const [minRevenue, setMinRevenue] = useState<string>("");
  const [maxAgeDays, setMaxAgeDays] = useState<string>("");

  // Step 4
  const [selectedCoders, setSelectedCoders] = useState<number[]>([]);
  const [distribution, setDistribution] = useState<"round_robin" | "by_specialty">(
    "round_robin"
  );

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{
    campaign_id: number;
    assigned: number;
  } | null>(null);

  // Reset on open
  useEffect(() => {
    if (open) {
      setStep(1);
      setName("");
      setDescription("");
      setTargetDate("");
      setHccCodes([]);
      setHccCustom("");
      setMinRevenue("");
      setMaxAgeDays("");
      setSelectedCoders([]);
      setDistribution("round_robin");
      setSubmitting(false);
      setError(null);
      setDone(null);
    }
  }, [open]);

  const filterCriteria: RecaptureFilterCriteria = useMemo(() => {
    const out: RecaptureFilterCriteria = {};
    if (hccCodes.length) out.hcc_codes = hccCodes;
    const minR = Number(minRevenue);
    if (minRevenue !== "" && Number.isFinite(minR)) out.min_revenue = minR;
    const days = Number(maxAgeDays);
    if (maxAgeDays !== "" && Number.isFinite(days) && days >= 0) {
      out.max_age_days = days;
    }
    return out;
  }, [hccCodes, minRevenue, maxAgeDays]);

  // Preview is fetched when entering step 3
  const preview = useQuery({
    queryKey: ["recapture-preview", filterCriteria],
    queryFn: () => previewRecaptureFilter(filterCriteria),
    enabled: open && step === 3,
    staleTime: 10_000,
  });

  // Coder list fetched once per modal open
  const coders = useQuery({
    queryKey: ["recapture-coders"],
    queryFn: listEligibleCoders,
    enabled: open && (step === 4 || step === 5),
    staleTime: 60_000,
  });

  if (!open) return null;

  const canAdvance = (() => {
    if (step === 1) return name.trim().length > 0;
    if (step === 2) return true;
    if (step === 3) return (preview.data?.matched_gaps ?? 0) > 0;
    if (step === 4) return selectedCoders.length > 0;
    return true;
  })();

  function toggleHcc(code: string) {
    setHccCodes((prev) =>
      prev.includes(code) ? prev.filter((c) => c !== code) : [...prev, code]
    );
  }

  function addCustomHcc() {
    const v = hccCustom.trim();
    if (!v) return;
    if (!hccCodes.includes(v)) setHccCodes((prev) => [...prev, v]);
    setHccCustom("");
  }

  function toggleCoder(id: number) {
    setSelectedCoders((prev) =>
      prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]
    );
  }

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      const c = await createRecaptureCampaign({
        name: name.trim(),
        description: description.trim() || null,
        filter_criteria: filterCriteria,
        target_close_date: targetDate || null,
        status: "draft",
      });
      const result = await assignRecaptureCampaign(c.id, {
        coder_ids: selectedCoders,
        distribution,
      });
      setDone({ campaign_id: c.id, assigned: result.assigned });
      // Notify the list view
      window.dispatchEvent(new CustomEvent("recapture-campaigns:changed"));
    } catch (err) {
      const msg =
        (err as { response?: { data?: { detail?: string } }; message?: string })
          .response?.data?.detail ||
        (err as Error).message ||
        "Failed to create campaign";
      setError(String(msg));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4">
      <div className="w-full max-w-2xl overflow-hidden rounded-xl bg-white shadow-2xl">
        <header className="flex items-center justify-between border-b border-slate-100 p-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">
              {done ? "Campaign created" : "New recapture campaign"}
            </h2>
            <p className="text-sm text-slate-500">
              {done ? "Coder assignments are ready." : `Step ${step} of 5`}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-500 hover:bg-slate-100"
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </header>

        <div className="max-h-[60vh] overflow-y-auto p-5">
          {done ? (
            <div className="flex flex-col items-center gap-3 py-8 text-center">
              <CheckCircle2 size={48} className="text-emerald-500" />
              <p className="text-base font-semibold text-slate-900">
                Campaign #{done.campaign_id} is live.
              </p>
              <p className="text-sm text-slate-500">
                {done.assigned} gap{done.assigned === 1 ? "" : "s"} assigned to{" "}
                {selectedCoders.length} coder
                {selectedCoders.length === 1 ? "" : "s"}.
              </p>
            </div>
          ) : null}

          {!done && step === 1 ? (
            <div className="space-y-4">
              <label className="block">
                <span className="text-sm font-medium text-slate-700">Name</span>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Q3 Diabetes Recapture"
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </label>
              <label className="block">
                <span className="text-sm font-medium text-slate-700">
                  Description (optional)
                </span>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={3}
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </label>
              <label className="block">
                <span className="text-sm font-medium text-slate-700">
                  Target close date (optional)
                </span>
                <input
                  type="date"
                  value={targetDate}
                  onChange={(e) => setTargetDate(e.target.value)}
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </label>
            </div>
          ) : null}

          {!done && step === 2 ? (
            <div className="space-y-4">
              <div>
                <span className="text-sm font-medium text-slate-700">
                  HCC codes
                </span>
                <p className="mt-0.5 text-xs text-slate-500">
                  Pick one or more — gaps with these HCC codes will be included.
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {COMMON_HCC_CODES.map((h) => {
                    const active = hccCodes.includes(h.code);
                    return (
                      <button
                        key={h.code}
                        type="button"
                        onClick={() => toggleHcc(h.code)}
                        className={`rounded-full border px-3 py-1 text-xs font-medium ${
                          active
                            ? "border-blue-500 bg-blue-50 text-blue-700"
                            : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                        }`}
                      >
                        {h.label}
                      </button>
                    );
                  })}
                </div>
                <div className="mt-2 flex gap-2">
                  <input
                    value={hccCustom}
                    onChange={(e) => setHccCustom(e.target.value)}
                    placeholder="Other HCC code"
                    className="flex-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm"
                  />
                  <button
                    type="button"
                    onClick={addCustomHcc}
                    className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
                  >
                    Add
                  </button>
                </div>
                {hccCodes.length ? (
                  <p className="mt-2 text-xs text-slate-500">
                    Selected: {hccCodes.join(", ")}
                  </p>
                ) : null}
              </div>

              <label className="block">
                <span className="text-sm font-medium text-slate-700">
                  Minimum revenue per gap ($)
                </span>
                <input
                  type="number"
                  value={minRevenue}
                  onChange={(e) => setMinRevenue(e.target.value)}
                  min={0}
                  step={500}
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                />
              </label>

              <label className="block">
                <span className="text-sm font-medium text-slate-700">
                  Maximum gap age (days open)
                </span>
                <input
                  type="number"
                  value={maxAgeDays}
                  onChange={(e) => setMaxAgeDays(e.target.value)}
                  min={0}
                  className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                />
              </label>
            </div>
          ) : null}

          {!done && step === 3 ? (
            <div>
              <p className="text-sm text-slate-600">
                Preview — these gaps will be eligible for assignment:
              </p>
              {preview.isLoading ? (
                <div className="mt-4 text-sm text-slate-500">Counting…</div>
              ) : preview.isError ? (
                <div className="mt-4 text-sm text-rose-600">
                  Failed to preview filter.
                </div>
              ) : preview.data ? (
                <div className="mt-4 space-y-3">
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
                    <p className="text-3xl font-bold text-slate-900">
                      {preview.data.matched_gaps}
                    </p>
                    <p className="text-sm text-slate-500">
                      open recapture gaps
                    </p>
                    <p className="mt-1 text-sm font-medium text-emerald-700">
                      {formatCurrency(preview.data.total_revenue_at_risk)} at risk
                    </p>
                  </div>
                  {preview.data.by_hcc.length ? (
                    <div className="rounded-lg border border-slate-200">
                      <div className="border-b border-slate-100 p-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
                        Top HCCs
                      </div>
                      <ul className="divide-y divide-slate-100">
                        {preview.data.by_hcc.slice(0, 8).map((row) => (
                          <li
                            key={row.hcc_code}
                            className="flex items-center justify-between p-3 text-sm"
                          >
                            <span className="font-medium text-slate-700">
                              HCC {row.hcc_code}
                            </span>
                            <span className="text-slate-500">
                              {row.count} gaps · {formatCurrency(row.revenue)}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}

          {!done && step === 4 ? (
            <div className="space-y-4">
              <div>
                <span className="text-sm font-medium text-slate-700">
                  Distribution
                </span>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  {(["round_robin", "by_specialty"] as const).map((d) => (
                    <button
                      key={d}
                      type="button"
                      onClick={() => setDistribution(d)}
                      className={`rounded-lg border p-3 text-left text-sm ${
                        distribution === d
                          ? "border-blue-500 bg-blue-50"
                          : "border-slate-200 bg-white hover:bg-slate-50"
                      }`}
                    >
                      <div className="font-medium text-slate-900">
                        {d === "round_robin" ? "Round robin" : "By specialty"}
                      </div>
                      <div className="text-xs text-slate-500">
                        {d === "round_robin"
                          ? "Even split, one gap at a time"
                          : "Match coder NPI to gap provider, fall back to round-robin"}
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <span className="text-sm font-medium text-slate-700">
                  Select coders
                </span>
                {coders.isLoading ? (
                  <div className="mt-2 text-sm text-slate-500">Loading…</div>
                ) : (coders.data?.length ?? 0) > 0 ? (
                  <ul className="mt-2 max-h-64 overflow-y-auto rounded-md border border-slate-200">
                    {(coders.data ?? []).map((c: EligibleCoder) => {
                      const checked = selectedCoders.includes(c.id);
                      return (
                        <li
                          key={c.id}
                          className="flex items-center justify-between border-b border-slate-100 p-3 last:border-b-0"
                        >
                          <label className="flex flex-1 cursor-pointer items-center gap-3">
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => toggleCoder(c.id)}
                              className="h-4 w-4 rounded border-slate-300"
                            />
                            <div>
                              <div className="text-sm font-medium text-slate-800">
                                {c.full_name}
                              </div>
                              <div className="text-xs text-slate-500">
                                {c.email} · {c.role}
                              </div>
                            </div>
                          </label>
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <p className="mt-2 text-sm text-slate-500">
                    No eligible coders found.
                  </p>
                )}
              </div>
            </div>
          ) : null}

          {!done && step === 5 ? (
            <div className="space-y-3 text-sm text-slate-600">
              <p>
                Ready to create <strong>{name.trim()}</strong> with{" "}
                <strong>{preview.data?.matched_gaps ?? 0}</strong> matching gaps,
                assigned to <strong>{selectedCoders.length}</strong> coder
                {selectedCoders.length === 1 ? "" : "s"} via{" "}
                <strong>{distribution.replace("_", " ")}</strong>.
              </p>
              {error ? (
                <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
                  {error}
                </div>
              ) : null}
            </div>
          ) : null}
        </div>

        <footer className="flex items-center justify-between border-t border-slate-100 p-4">
          <button
            type="button"
            onClick={done ? onClose : () => setStep((s) => Math.max(1, s - 1) as Step)}
            disabled={!done && step === 1}
            className="inline-flex items-center gap-1 rounded-md border border-slate-200 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40"
          >
            {done ? "Close" : (
              <>
                <ChevronLeft size={14} /> Back
              </>
            )}
          </button>

          {!done ? (
            step < 5 ? (
              <button
                type="button"
                onClick={() => setStep((s) => Math.min(5, s + 1) as Step)}
                disabled={!canAdvance}
                className="inline-flex items-center gap-1 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40"
              >
                Next <ChevronRight size={14} />
              </button>
            ) : (
              <button
                type="button"
                onClick={submit}
                disabled={submitting || selectedCoders.length === 0}
                className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
              >
                {submitting ? "Creating…" : "Create + assign"}
              </button>
            )
          ) : null}
        </footer>
      </div>
    </div>
  );
}
