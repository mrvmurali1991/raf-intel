"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { HelpButton } from "@/components/HelpPanel";
import { PageHeader } from "@/components/ui/page-header";
import {
  Target,
  Plus,
  TrendingUp,
  DollarSign,
  CheckCircle,
  X,
  Calendar,
  AlertTriangle,
} from "lucide-react";
import {
  listGoals,
  createGoal,
  type RafGoal,
  type GoalMetric,
  type GoalCreatePayload,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const METRIC_LABELS: Record<GoalMetric, string> = {
  raf_capture_count: "RAF Captures",
  revenue: "Revenue ($)",
  gaps_closed: "Gaps Closed",
};

const METRIC_ICONS: Record<GoalMetric, React.ReactNode> = {
  raf_capture_count: <TrendingUp className="h-4 w-4" />,
  revenue: <DollarSign className="h-4 w-4" />,
  gaps_closed: <CheckCircle className="h-4 w-4" />,
};

function currentQuarter(): string {
  const d = new Date();
  const q = Math.floor(d.getMonth() / 3) + 1;
  return `${d.getFullYear()}-Q${q}`;
}

function formatValue(metric: GoalMetric, value: number): string {
  if (metric === "revenue")
    return `$${value.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

// ---------------------------------------------------------------------------
// Progress bar
// ---------------------------------------------------------------------------

/**
 * Color thresholds (relative to expected pace):
 *   >= 80% of pace → teal (on track)
 *   50–79% of pace → amber (slight lag)
 *   < 50% of pace  → red (at risk)
 *   >= 100% complete → teal regardless
 */
function paceColor(pct: number, pace: number): "teal" | "amber" | "red" {
  if (pct >= 100) return "teal";
  if (pace === 0) return "teal";
  const ratio = pct / pace;
  if (ratio >= 0.8) return "teal";
  if (ratio >= 0.5) return "amber";
  return "red";
}

const FILL_CLASS: Record<"teal" | "amber" | "red", string> = {
  teal: "bg-teal-500",
  amber: "bg-amber-400",
  red: "bg-red-500",
};

const TEXT_CLASS: Record<"teal" | "amber" | "red", string> = {
  teal: "text-teal-600",
  amber: "text-amber-600",
  red: "text-red-600",
};

function GoalProgressBar({ pct, pace }: { pct: number; pace: number }) {
  const color = paceColor(pct, pace);
  const clampedWidth = Math.min(Math.max(pct, 0), 100);
  return (
    <div className="w-full bg-slate-100 dark:bg-slate-800 rounded-full h-2.5 overflow-hidden">
      <div
        className={`h-2.5 rounded-full transition-all duration-500 ${FILL_CLASS[color]}`}
        style={{ width: `${clampedWidth}%` }}
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Goal progress: ${pct}%`}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Loading skeleton
// ---------------------------------------------------------------------------

function GoalCardSkeleton() {
  return (
    <div className="bg-card border border-border rounded-xl p-5 space-y-4 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-muted animate-pulse" />
          <div className="h-4 w-28 rounded bg-muted animate-pulse" />
        </div>
        <div className="h-5 w-16 rounded-full bg-muted animate-pulse" />
      </div>
      <div className="space-y-2">
        <div className="flex justify-between">
          <div className="h-3.5 w-20 rounded bg-muted animate-pulse" />
          <div className="h-3.5 w-16 rounded bg-muted animate-pulse" />
        </div>
        <div className="w-full bg-muted rounded-full h-2.5 animate-pulse" />
        <div className="flex justify-between">
          <div className="h-3 w-20 rounded bg-muted animate-pulse" />
          <div className="h-3 w-20 rounded bg-muted animate-pulse" />
        </div>
      </div>
      <div className="pt-2 border-t border-border flex justify-between">
        <div className="h-5 w-24 rounded-full bg-muted animate-pulse" />
        <div className="h-5 w-20 rounded-full bg-muted animate-pulse" />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Goal card
// ---------------------------------------------------------------------------

function GoalCard({ goal }: { goal: RafGoal }) {
  const isComplete = goal.percent_complete >= 100;
  const pace = goal.pace_expected ?? 0;
  const color = paceColor(goal.percent_complete, pace);

  const statusLabel = isComplete
    ? "Goal met"
    : color === "red"
    ? "At risk"
    : color === "amber"
    ? "Behind pace"
    : "On track";

  const StatusIcon = isComplete || color === "teal" ? CheckCircle : AlertTriangle;

  return (
    <div
      tabIndex={0}
      role="article"
      aria-label={`${METRIC_LABELS[goal.metric]} goal for ${goal.period}: ${goal.percent_complete}% complete, ${statusLabel}`}
      className="bg-card border border-border rounded-xl p-5 space-y-4 shadow-sm hover:shadow-md transition-shadow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2"
    >
      {/* Header row: metric name + period badge */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="p-1.5 bg-primary/10 rounded-lg text-primary shrink-0">
            {METRIC_ICONS[goal.metric]}
          </span>
          <span className="text-sm font-bold text-foreground leading-tight">
            {METRIC_LABELS[goal.metric]}
          </span>
        </div>
        <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-muted text-muted-foreground whitespace-nowrap">
          {goal.period}
        </span>
      </div>

      {/* Progress section */}
      <div className="space-y-2">
        {/* Percent + target row */}
        <div className="flex items-baseline justify-between gap-2">
          <span className={`text-xl font-bold ${TEXT_CLASS[color]}`}>
            {goal.percent_complete}%{" "}
            <span className="text-xs font-normal text-muted-foreground">
              complete
            </span>
          </span>
          <span className="text-xs text-muted-foreground">
            Target:{" "}
            <span className="font-semibold text-foreground">
              {formatValue(goal.metric, goal.target_value)}
            </span>
          </span>
        </div>

        {/* Full-width teal-fill progress bar */}
        <GoalProgressBar pct={goal.percent_complete} pace={pace} />

        {/* Actual vs target sub-labels */}
        <div className="flex justify-between text-xs text-muted-foreground">
          <span>{formatValue(goal.metric, goal.actual_value)} actual</span>
          <span>{formatValue(goal.metric, goal.target_value)} target</span>
        </div>
      </div>

      {/* Footer row: days badge + on-track indicator */}
      <div className="flex items-center justify-between pt-2 border-t border-border gap-2">
        {/* Days remaining badge */}
        <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
          <Calendar className="h-3 w-3 shrink-0" />
          {goal.days_remaining > 0
            ? `${goal.days_remaining}d remaining`
            : "Quarter ended"}
        </span>

        {/* On-track / status indicator */}
        <span
          className={`inline-flex items-center gap-1 text-xs font-semibold ${TEXT_CLASS[color]}`}
        >
          <StatusIcon className="h-3.5 w-3.5 shrink-0" />
          {statusLabel}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Set Goal modal
// ---------------------------------------------------------------------------

interface SetGoalModalProps {
  onClose: () => void;
  onSave: (payload: GoalCreatePayload) => void;
  saving: boolean;
}

const INPUT_CLASS =
  "w-full border border-border rounded-lg px-3 py-2.5 sm:py-2 text-sm bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary min-h-[44px] sm:min-h-0 transition-shadow";

function SetGoalModal({ onClose, onSave, saving }: SetGoalModalProps) {
  const [period, setPeriod] = useState(currentQuarter());
  const [metric, setMetric] = useState<GoalMetric>("raf_capture_count");
  const [target, setTarget] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const val = parseFloat(target);
    if (isNaN(val) || val <= 0) return;
    onSave({ period, metric, target_value: val });
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="set-goal-title"
    >
      <div className="bg-card rounded-2xl shadow-2xl w-full max-w-md p-6 space-y-5 mx-4">
        {/* Modal header */}
        <div className="flex items-center justify-between">
          <h2
            id="set-goal-title"
            className="text-lg font-semibold text-foreground flex items-center gap-2"
          >
            <Target className="h-5 w-5 text-primary" />
            Set Quarterly Goal
          </h2>
          <button
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
            aria-label="Close modal"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Quarter field */}
          <div className="space-y-1.5">
            <label htmlFor="period" className="text-sm font-medium text-foreground">
              Quarter
            </label>
            <input
              id="period"
              type="text"
              value={period}
              onChange={(e) => setPeriod(e.target.value)}
              placeholder="2026-Q2"
              pattern="\d{4}-Q[1-4]"
              required
              className={INPUT_CLASS}
            />
            <p className="text-xs text-muted-foreground">
              Format: YYYY-QN (e.g. 2026-Q2)
            </p>
          </div>

          {/* Metric field */}
          <div className="space-y-1.5">
            <label htmlFor="metric" className="text-sm font-medium text-foreground">
              Metric
            </label>
            <select
              id="metric"
              value={metric}
              onChange={(e) => setMetric(e.target.value as GoalMetric)}
              className={INPUT_CLASS}
            >
              {(Object.keys(METRIC_LABELS) as GoalMetric[]).map((m) => (
                <option key={m} value={m}>
                  {METRIC_LABELS[m]}
                </option>
              ))}
            </select>
          </div>

          {/* Target value field */}
          <div className="space-y-1.5">
            <label htmlFor="target" className="text-sm font-medium text-foreground">
              Target Value
            </label>
            <input
              id="target"
              type="number"
              min="1"
              step="any"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              placeholder={metric === "revenue" ? "500000" : "200"}
              required
              className={INPUT_CLASS}
            />
          </div>

          {/* Action buttons: Cancel (outline) + Create (teal solid) */}
          <div className="flex flex-col-reverse sm:flex-row gap-3 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2.5 sm:py-2 text-sm font-medium border border-border rounded-lg text-foreground hover:bg-muted transition-colors min-h-[44px] sm:min-h-0"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex-1 px-4 py-2.5 sm:py-2 text-sm font-medium bg-teal-600 text-white rounded-lg hover:bg-teal-700 disabled:opacity-50 transition-colors min-h-[44px] sm:min-h-0"
            >
              {saving ? "Creating..." : "Create"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function GoalsPage() {
  const [showModal, setShowModal] = useState(false);
  const qc = useQueryClient();

  const {
    data: goals = [],
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["goals"],
    queryFn: () => listGoals(),
    staleTime: 60_000,
  });

  const mutation = useMutation({
    mutationFn: createGoal,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["goals"] });
      setShowModal(false);
    },
  });

  const currentPeriod = currentQuarter();
  const activeGoals = goals.filter((g) => g.period === currentPeriod);
  const pastGoals = goals.filter((g) => g.period !== currentPeriod);

  const headerActions = (
    <>
      <button
        onClick={() => setShowModal(true)}
        className="flex items-center gap-2 px-4 py-2 min-h-[44px] sm:min-h-0 bg-teal-600 text-white text-sm font-medium rounded-lg hover:bg-teal-700 transition-colors"
        aria-label="Set a new quarterly goal"
      >
        <Plus className="h-4 w-4" />
        Set Goal
      </button>
      <HelpButton />
    </>
  );

  return (
    <>
      {showModal && (
        <SetGoalModal
          onClose={() => setShowModal(false)}
          onSave={(p) => mutation.mutate(p)}
          saving={mutation.isPending}
        />
      )}

      <div className="container mx-auto p-4 sm:p-6 space-y-8 max-w-5xl">
        <PageHeader
          title="Quarterly Goals"
          subtitle="Track RAF capture targets vs actuals for the current quarter."
          icon={<Target className="h-5 w-5" />}
          actions={headerActions}
        />

        {/* Loading state */}
        {isLoading && (
          <div className="space-y-8">
            <section className="space-y-3">
              <div className="h-4 w-32 rounded bg-muted animate-pulse" />
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {[1, 2, 3].map((i) => (
                  <GoalCardSkeleton key={i} />
                ))}
              </div>
            </section>
          </div>
        )}

        {/* Error state */}
        {isError && (
          <div className="rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-5 text-sm text-red-700 dark:text-red-400 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            Failed to load goals. Please refresh.
          </div>
        )}

        {/* Empty state — no goals at all */}
        {!isLoading && !isError && goals.length === 0 && (
          <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-border py-20 px-6 text-center gap-4">
            <div className="w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center text-primary">
              <Target className="h-7 w-7" />
            </div>
            <div className="space-y-1">
              <p className="text-base font-semibold text-foreground">
                No quarterly goals set
              </p>
              <p className="text-sm text-muted-foreground max-w-xs">
                Define targets for RAF captures, revenue, or gaps closed to
                track your team&apos;s progress each quarter.
              </p>
            </div>
            <button
              onClick={() => setShowModal(true)}
              className="flex items-center gap-2 px-5 py-2.5 bg-teal-600 text-white text-sm font-medium rounded-lg hover:bg-teal-700 transition-colors"
            >
              <Plus className="h-4 w-4" />
              Create your first goal
            </button>
          </div>
        )}

        {/* Goals list */}
        {!isLoading && !isError && goals.length > 0 && (
          <>
            <section className="space-y-3">
              <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
                {currentPeriod} — Active
              </h2>
              {activeGoals.length === 0 ? (
                <div className="rounded-xl border-2 border-dashed border-border p-8 text-center text-muted-foreground text-sm">
                  No goals set for {currentPeriod}.{" "}
                  <button
                    onClick={() => setShowModal(true)}
                    className="text-teal-600 hover:underline font-medium"
                  >
                    Set one now.
                  </button>
                </div>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {activeGoals.map((g) => (
                    <GoalCard key={g.id} goal={g} />
                  ))}
                </div>
              )}
            </section>

            {pastGoals.length > 0 && (
              <section className="space-y-3">
                <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
                  Previous Quarters
                </h2>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                  {pastGoals.map((g) => (
                    <GoalCard key={g.id} goal={g} />
                  ))}
                </div>
              </section>
            )}
          </>
        )}
      </div>
    </>
  );
}
