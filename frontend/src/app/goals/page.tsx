"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { HelpButton } from "@/components/HelpPanel";
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
  if (metric === "revenue") return `$${value.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

// ---------------------------------------------------------------------------
// Progress bar
// ---------------------------------------------------------------------------

function GoalProgressBar({ pct, onTrack }: { pct: number; onTrack?: boolean }) {
  const color =
    pct >= 100
      ? "bg-green-500"
      : onTrack === false
      ? "bg-amber-400"
      : "bg-primary";
  return (
    <div className="w-full bg-slate-100 rounded-full h-2.5 overflow-hidden">
      <div
        className={`h-2.5 rounded-full transition-all duration-500 ${color}`}
        style={{ width: `${Math.min(pct, 100)}%` }}
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Goal card
// ---------------------------------------------------------------------------

function GoalCard({ goal }: { goal: RafGoal }) {
  const isComplete = goal.percent_complete >= 100;
  return (
    <div className="bg-card border border-border rounded-xl p-5 space-y-4 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 text-foreground font-medium">
          <span className="p-1.5 bg-primary/10 rounded-lg text-primary">
            {METRIC_ICONS[goal.metric]}
          </span>
          {METRIC_LABELS[goal.metric]}
        </div>
        <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-muted text-muted-foreground">
          {goal.period}
        </span>
      </div>

      <div className="space-y-1.5">
        <div className="flex justify-between text-sm">
          <span className="text-muted-foreground">Progress</span>
          <span className={`font-semibold ${isComplete ? "text-green-600" : "text-foreground"}`}>
            {goal.percent_complete}%
          </span>
        </div>
        <GoalProgressBar pct={goal.percent_complete} onTrack={goal.on_track} />
        <div className="flex justify-between text-xs text-muted-foreground">
          <span>{formatValue(goal.metric, goal.actual_value)} actual</span>
          <span>{formatValue(goal.metric, goal.target_value)} target</span>
        </div>
      </div>

      <div className="flex items-center justify-between text-xs text-muted-foreground pt-1 border-t border-border">
        <span className="flex items-center gap-1">
          <Calendar className="h-3.5 w-3.5" />
          {goal.days_remaining > 0 ? `${goal.days_remaining}d remaining` : "Quarter ended"}
        </span>
        {goal.on_track === false && !isComplete && (
          <span className="flex items-center gap-1 text-amber-600 font-medium">
            <AlertTriangle className="h-3.5 w-3.5" />
            Behind pace
          </span>
        )}
        {isComplete && (
          <span className="flex items-center gap-1 text-green-600 font-medium">
            <CheckCircle className="h-3.5 w-3.5" />
            Goal met
          </span>
        )}
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
        <div className="flex items-center justify-between">
          <h2 id="set-goal-title" className="text-lg font-semibold text-foreground flex items-center gap-2">
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
              className="w-full border border-border rounded-lg px-3 py-2 text-sm bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-primary"
            />
            <p className="text-xs text-muted-foreground">Format: YYYY-QN (e.g. 2026-Q2)</p>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="metric" className="text-sm font-medium text-foreground">
              Metric
            </label>
            <select
              id="metric"
              value={metric}
              onChange={(e) => setMetric(e.target.value as GoalMetric)}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary bg-background text-foreground"
            >
              {(Object.keys(METRIC_LABELS) as GoalMetric[]).map((m) => (
                <option key={m} value={m}>
                  {METRIC_LABELS[m]}
                </option>
              ))}
            </select>
          </div>

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
              className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary bg-background text-foreground"
            />
          </div>

          <div className="flex gap-3 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 px-4 py-2 text-sm font-medium border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex-1 px-4 py-2 text-sm font-medium bg-primary text-primary-foreground rounded-lg hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {saving ? "Saving..." : "Save Goal"}
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

  const { data: goals = [], isLoading, isError } = useQuery({
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

  return (
    <>
      {showModal && (
        <SetGoalModal
          onClose={() => setShowModal(false)}
          onSave={(p) => mutation.mutate(p)}
          saving={mutation.isPending}
        />
      )}

      <div className="container mx-auto p-6 space-y-8 max-w-5xl">
        <header className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 max-lg:pl-14">
          <div>
            <h1 className="text-2xl font-semibold text-foreground flex items-center gap-2">
              <Target className="h-6 w-6 text-primary" />
              Quarterly Goals
            </h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              Track RAF capture targets vs actuals for the current quarter.
            </p>
          </div>
          <div className="flex items-center gap-2 self-start sm:self-auto">
            <button
              onClick={() => setShowModal(true)}
              className="flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground text-sm font-medium rounded-lg hover:opacity-90 transition-opacity"
              aria-label="Set a new quarterly goal"
            >
              <Plus className="h-4 w-4" />
              Set Goal
            </button>
            <HelpButton />
          </div>
        </header>

        {isLoading && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-40 rounded-xl bg-muted animate-pulse" />
            ))}
          </div>
        )}

        {isError && (
          <div className="rounded-xl bg-red-50 border border-red-200 p-5 text-sm text-red-700 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            Failed to load goals. Please refresh.
          </div>
        )}

        {!isLoading && !isError && (
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
                    className="text-primary hover:underline font-medium"
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
