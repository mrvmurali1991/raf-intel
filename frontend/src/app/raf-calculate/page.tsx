"use client";

import { useState, useCallback, useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { AdvancedRAFPanel } from "@/components/AdvancedRAFPanel";
import type { AdvancedRAFOptions } from "@/components/AdvancedRAFPanel";
import { tokens } from "@/styles/tokens";
import {
  Calculator,
  ChevronRight,
  AlertTriangle,
  CheckCircle,
  Info,
  Activity,
  TrendingUp,
  Users,
  Clock,
} from "lucide-react";

// ─── Types ────────────────────────────────────────────────────────────────────

interface RAFResult {
  patient_id: number;
  measurement_year: number;
  raf_score: number;
  v24_score?: number;
  v28_score?: number;
  blend_weights?: { v24: number; v28: number };
  model_segment: string;
  model_version: string;
  hcc_count: number;
  demographic_score: number;
  disease_score: number;
  interaction_score: number;
  hcc_list: number[];
  new_enrollee?: boolean;
  frailty_addend?: number;
  frailty_is_frail?: boolean;
  frailty_adl_count?: number;
  sweep_period?: string;
  esrd_segment?: string;
  calculated_at: string;
  error?: string;
}

interface PatientBasics {
  fname: string;
  lname: string;
  pid: number;
  DOB?: string;
  sex?: string;
}

// ─── Debounce Hook ────────────────────────────────────────────────────────────

function useDebouncedValue<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(t);
  }, [value, delay]);
  return debounced;
}

// ─── Patient Selector ─────────────────────────────────────────────────────────

function PatientSearchBox({
  selectedPid: _selectedPid,
  onSelect,
}: {
  selectedPid: number | null;
  onSelect: (pid: number, name: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const debouncedQuery = useDebouncedValue(query, 300);

  const { data, isFetching, isError, error } = useQuery({
    queryKey: ["patient-search-raf", debouncedQuery],
    queryFn: async () => {
      const r = await api.get("/api/patients", {
        params: { search: debouncedQuery, limit: 8 },
      });
      return r.data;
    },
    enabled: debouncedQuery.length > 1,
  });

  const patients: PatientBasics[] = data?.patients ?? [];
  const errorMessage =
    (error as { response?: { data?: { detail?: string } }; message?: string } | null)
      ?.response?.data?.detail ??
    (error as { message?: string } | null)?.message ??
    "Search failed.";

  return (
    <div style={{ position: "relative" }}>
      <input
        id="patient-search-input"
        type="text"
        placeholder="Search patient by name or PID…"
        value={query}
        onChange={(e) => { setQuery(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        style={ps.input}
      />
      {open && debouncedQuery.length > 1 && isFetching && (
        <div style={ps.statusRow}>Searching…</div>
      )}
      {open && debouncedQuery.length > 1 && !isFetching && isError && (
        <div style={{ ...ps.statusRow, color: tokens.riskHigh }}>{errorMessage}</div>
      )}
      {open && patients.length > 0 && (
        <div style={ps.dropdown}>
          {patients.map((p) => (
            <button
              key={p.pid}
              id={`patient-opt-${p.pid}`}
              onClick={() => {
                onSelect(p.pid, `${p.fname} ${p.lname}`);
                setQuery(`${p.fname} ${p.lname}`);
                setOpen(false);
              }}
              style={ps.option}
            >
              <div style={ps.optionAvatar}>
                {((p.fname || "").trim()[0] || (p.lname || "").trim()[0] || "\u2022").toUpperCase()}{(p.fname && p.lname ? (p.lname || "").trim()[0] : "").toUpperCase()}
              </div>
              <div>
                <div style={ps.optionName}>{p.fname} {p.lname}</div>
                <div style={ps.optionSub}>PID {p.pid} · {p.DOB ?? "—"} · {p.sex ?? "—"}</div>
              </div>
              <ChevronRight size={14} style={{ marginLeft: "auto", color: tokens.slate400 }} />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

const ps: Record<string, React.CSSProperties> = {
  input: {
    width: "100%", height: 44, borderRadius: 10,
    border: `1.5px solid ${tokens.slate200}`, padding: "0 16px",
    fontSize: 14, color: tokens.slate900,
    background: tokens.white, boxSizing: "border-box",
  },
  dropdown: {
    position: "absolute", top: "calc(100% + 4px)", left: 0, right: 0,
    background: tokens.white, border: `1px solid ${tokens.slate200}`, borderRadius: 10,
    boxShadow: "0 8px 24px rgba(0,0,0,0.12)", zIndex: 100,
    overflow: "hidden",
  },
  option: {
    display: "flex", alignItems: "center", gap: 10,
    width: "100%", padding: "10px 14px",
    border: "none", background: "none", cursor: "pointer",
    textAlign: "left" as const,
    borderBottom: `1px solid ${tokens.slate100}`,
    transition: "background .1s",
  },
  optionAvatar: {
    width: 32, height: 32, borderRadius: "50%",
    background: `linear-gradient(135deg, ${tokens.primaryDark}, ${tokens.accentPurple})`,
    color: tokens.white, fontWeight: 700, fontSize: 12,
    display: "flex", alignItems: "center", justifyContent: "center",
    flexShrink: 0,
  },
  optionName: { fontSize: 13, fontWeight: 600, color: tokens.slate900 },
  optionSub:  { fontSize: 11, color: tokens.slate500 },
  statusRow: {
    position: "absolute", top: "calc(100% + 4px)", left: 0, right: 0,
    background: tokens.white, border: `1px solid ${tokens.slate200}`, borderRadius: 10,
    padding: "10px 14px", fontSize: 12, color: tokens.slate500, zIndex: 100,
    boxShadow: "0 8px 24px rgba(0,0,0,0.08)",
  },
};

// ─── Result Card ──────────────────────────────────────────────────────────────

function ResultCard({ result }: { result: RAFResult }) {
  const risk = result.raf_score >= 2.0 ? "High" : result.raf_score >= 1.0 ? "Medium" : "Low";
  const riskColor = result.raf_score >= 2.0 ? tokens.riskHigh : result.raf_score >= 1.0 ? tokens.riskMedium : tokens.riskLow;
  const riskBg    = result.raf_score >= 2.0 ? tokens.riskHighSoft : result.raf_score >= 1.0 ? tokens.warningSoft : tokens.successSoft;

  return (
    <div style={rc.wrapper}>
      {/* Score Hero */}
      <div style={{ ...rc.hero, background: `linear-gradient(135deg, ${tokens.slate900}, ${tokens.primaryDark})` }}>
        <div>
          <div style={rc.heroLabel}>Final RAF Score</div>
          <div style={rc.heroScore}>{(result.raf_score ?? 0).toFixed(4)}</div>
          <div style={{ ...rc.riskBadge, background: riskBg, color: riskColor }}>
            {risk} Risk · Segment: {result.model_segment}
          </div>
        </div>
        <div style={rc.heroRight}>
          {result.new_enrollee && (
            <div style={rc.tag}>NE Model</div>
          )}
          {result.frailty_is_frail && (
            <div style={{ ...rc.tag, background: tokens.emerald100, color: tokens.riskLow }}>
              Frailty +{result.frailty_addend?.toFixed(4)}
            </div>
          )}
          {result.sweep_period && (
            <div style={{ ...rc.tag, background: tokens.primarySoft, color: tokens.accentPurple }}>
              {result.sweep_period} sweep
            </div>
          )}
          {result.esrd_segment && (
            <div style={{ ...rc.tag, background: tokens.warningSoft, color: tokens.riskMedium }}>
              ESRD: {result.esrd_segment}
            </div>
          )}
        </div>
      </div>

      {/* Score Breakdown */}
      <div style={rc.grid4}>
        <ScoreStat label="Demographic" value={(result.demographic_score ?? 0).toFixed(4)} icon="👤" />
        <ScoreStat label="Disease HCCs" value={(result.disease_score ?? 0).toFixed(4)} icon="🏥" />
        <ScoreStat label="Interactions" value={(result.interaction_score ?? 0).toFixed(4)} icon="🔗" />
        <ScoreStat label="HCC Count" value={String(result.hcc_count)} icon="📊" />
      </div>

      {/* Blend Weights */}
      {result.blend_weights && (
        <div style={rc.blendRow}>
          <div style={rc.blendItem}>
            <span style={rc.blendLabel}>V24 Score</span>
            <span style={rc.blendVal}>{result.v24_score?.toFixed(4) ?? "—"}</span>
            <span style={rc.blendWeight}>({((result.blend_weights.v24 ?? 0) * 100).toFixed(0)}% weight)</span>
          </div>
          <div style={rc.blendSep}>+</div>
          <div style={rc.blendItem}>
            <span style={rc.blendLabel}>V28 Score</span>
            <span style={rc.blendVal}>{result.v28_score?.toFixed(4) ?? "—"}</span>
            <span style={rc.blendWeight}>({((result.blend_weights.v28 ?? 0) * 100).toFixed(0)}% weight)</span>
          </div>
          <div style={rc.blendSep}>=</div>
          <div style={rc.blendItem}>
            <span style={rc.blendLabel}>Blended RAF</span>
            <span style={{ ...rc.blendVal, color: tokens.primaryDark, fontWeight: 800 }}>{(result.raf_score ?? 0).toFixed(4)}</span>
          </div>
        </div>
      )}

      {/* HCC List */}
      {result.hcc_list?.length > 0 && (
        <div style={rc.hccSection}>
          <div style={rc.hccTitle}>HCC Conditions ({result.hcc_list.length})</div>
          <div style={rc.hccWrap}>
            {result.hcc_list.map((hcc) => (
              <span key={hcc} style={rc.hccChip}>HCC {hcc}</span>
            ))}
          </div>
        </div>
      )}

      {/* Frailty Detail */}
      {result.frailty_is_frail && (
        <div style={rc.frailtyBox}>
          <CheckCircle size={16} color={tokens.riskLow} />
          <div>
            <strong>Frailty Adjustment Applied</strong> — {result.frailty_adl_count} of 6 ADL impairments.
            Addend: <strong>+{result.frailty_addend?.toFixed(4)}</strong> applied to payment RAF.
          </div>
        </div>
      )}

      {/* New Enrollee Note */}
      {result.new_enrollee && (
        <div style={{ ...rc.frailtyBox, borderColor: tokens.slate300, background: tokens.primarySoft }}>
          <Info size={16} color={tokens.accentPurple} />
          <div style={{ color: tokens.primaryDark }}>
            <strong>New Enrollee (NE) Model Applied</strong> — Patient has &lt;12 months Part B coverage.
            HCC codes excluded; demographic-only score used per CMS NE methodology.
          </div>
        </div>
      )}

      <div style={rc.footer}>
        Calculated at {new Date(result.calculated_at).toLocaleString()} ·{" "}
        Model: {result.model_version}
      </div>
    </div>
  );
}

function ScoreStat({ label, value, icon }: { label: string; value: string; icon: string }) {
  return (
    <div style={rc.statCard}>
      <div style={rc.statIcon}>{icon}</div>
      <div style={rc.statVal}>{value}</div>
      <div style={rc.statLabel}>{label}</div>
    </div>
  );
}

const rc: Record<string, React.CSSProperties> = {
  wrapper: {
    border: `1.5px solid ${tokens.slate200}`, borderRadius: 14,
    overflow: "hidden", background: tokens.white,
  },
  hero: {
    padding: "20px 24px", color: tokens.white,
    display: "flex", justifyContent: "space-between", alignItems: "flex-start",
  },
  heroLabel: { fontSize: 12, opacity: 0.75, fontWeight: 600, textTransform: "uppercase", letterSpacing: ".05em" },
  heroScore: { fontSize: 44, fontWeight: 800, lineHeight: 1.1, marginTop: 4 },
  riskBadge: {
    display: "inline-block", marginTop: 8,
    padding: "3px 12px", borderRadius: 99,
    fontSize: 12, fontWeight: 700,
  },
  heroRight: { display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end" },
  tag: {
    padding: "3px 10px", borderRadius: 99,
    fontSize: 11, fontWeight: 700,
    background: tokens.primarySoft, color: tokens.primaryDark,
  },
  grid4: {
    display: "grid", gridTemplateColumns: "repeat(4, 1fr)",
    borderBottom: `1px solid ${tokens.slate100}`,
  },
  statCard: {
    padding: "14px 18px", textAlign: "center",
    borderRight: `1px solid ${tokens.slate100}`,
  },
  statIcon:  { fontSize: 18, marginBottom: 4 },
  statVal:   { fontSize: 20, fontWeight: 700, color: tokens.slate900 },
  statLabel: { fontSize: 11, color: tokens.slate500, marginTop: 2, textTransform: "uppercase", letterSpacing: ".04em" },
  blendRow: {
    display: "flex", alignItems: "center", gap: 4,
    padding: "12px 20px", background: tokens.slate50,
    borderBottom: `1px solid ${tokens.slate100}`,
  },
  blendItem:   { flex: 1, textAlign: "center" as const },
  blendLabel:  { display: "block", fontSize: 11, color: tokens.slate500 },
  blendVal:    { display: "block", fontSize: 16, fontWeight: 700, color: tokens.slate900 },
  blendWeight: { display: "block", fontSize: 10, color: tokens.slate400 },
  blendSep:    { fontSize: 20, fontWeight: 700, color: tokens.slate400, padding: "0 6px" },
  hccSection:  { padding: "14px 20px", borderBottom: `1px solid ${tokens.slate100}` },
  hccTitle:    { fontSize: 12, fontWeight: 700, color: tokens.slate700, marginBottom: 8, textTransform: "uppercase", letterSpacing: ".04em" },
  hccWrap:     { display: "flex", flexWrap: "wrap", gap: 6 },
  hccChip: {
    padding: "2px 10px", borderRadius: 99, fontSize: 12, fontWeight: 600,
    background: tokens.primarySoft, color: tokens.primaryDark, border: `1px solid ${tokens.slate200}`,
  },
  frailtyBox: {
    display: "flex", gap: 10, alignItems: "flex-start",
    padding: "12px 20px", background: tokens.successSoft,
    borderTop: `1px solid ${tokens.emerald100}`, fontSize: 13, color: tokens.successDark,
    borderBottom: `1px solid ${tokens.emerald100}`,
  },
  footer: {
    padding: "10px 20px", fontSize: 11, color: tokens.slate400,
    textAlign: "right" as const, background: tokens.slate50,
  },
};

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function RAFCalculatePage() {
  const searchParams = useSearchParams();
  const initPid = searchParams.get("pid") ? Number(searchParams.get("pid")) : null;

  const [selectedPid, setSelectedPid] = useState<number | null>(initPid);
  const [selectedName, setSelectedName] = useState("");
  const [isCalculating, setIsCalculating] = useState(false);
  const [rafResult, setRafResult] = useState<RAFResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [, setOptions] = useState<AdvancedRAFOptions | null>(null);

  const handleCalculate = useCallback(async (opts: AdvancedRAFOptions) => {
    if (!selectedPid) {
      setError("Please select a patient first.");
      return;
    }
    setIsCalculating(true);
    setError(null);
    setRafResult(null);

    try {
      const payload: any = {
        model_version: "auto",
        enrollment_months: opts.enrollmentMonths,
        sweep_period: opts.sweepPeriod ?? "none",
        plan_type: opts.planType,
        enrollment_info: {
          orec: opts.orec,
          dual_status: "non_dual",
          institutional: false,
        },
      };

      if (opts.adlData) {
        payload.adl_data = opts.adlData;
      }

      const resp = await api.post<RAFResult>(`/api/raf/calculate/${selectedPid}`, payload);
      setRafResult(resp.data);
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } }; message?: string };
      setError(e?.response?.data?.detail ?? e?.message ?? "Calculation failed.");
    } finally {
      setIsCalculating(false);
    }
  }, [selectedPid]);

  return (
    <div className="rci-page-pad-desktop" style={page.wrapper}>
      {/* ── Page Header ──────────────────────────────────────────────────────── */}
      <div style={page.header}>
        <div style={page.headerLeft}>
          <div style={page.headerIcon}>
            <Calculator size={22} color={tokens.white} />
          </div>
          <div>
            <h1 style={page.title}>RAF Score Calculator</h1>
            <p style={page.subtitle}>
              CMS-HCC V24/V28 blended · ESRD routing · New Enrollee · Frailty · Sweep Period
            </p>
          </div>
        </div>
        <div style={page.headerStats}>
          <HeaderStat icon={<Activity size={14} />} label="CMS-HCC V28" />
          <HeaderStat icon={<TrendingUp size={14} />} label="Frailty Adj." />
          <HeaderStat icon={<Clock size={14} />} label="3 Sweep Windows" />
          <HeaderStat icon={<Users size={14} />} label="ESRD + NE" />
        </div>
      </div>

      <div style={page.body}>
        {/* ── Left Column: Patient + Options ───────────────────────────────── */}
        <div style={page.leftCol}>
          {/* Patient Selector */}
          <div style={page.card}>
            <div style={page.cardTitle}>
              <Users size={14} /> Select Patient
            </div>
            <PatientSearchBox
              selectedPid={selectedPid}
              onSelect={(pid, name) => {
                setSelectedPid(pid);
                setSelectedName(name);
                setRafResult(null);
                setError(null);
              }}
            />
            {selectedPid && (
              <div style={page.selectedBadge}>
                <CheckCircle size={14} color={tokens.riskLow} />
                <span><strong>{selectedName}</strong> (PID {selectedPid}) selected</span>
              </div>
            )}
          </div>

          {/* Advanced Options Panel */}
          <AdvancedRAFPanel
            onChange={setOptions}
            onCalculate={handleCalculate}
            isCalculating={isCalculating}
            rafResult={rafResult ? {
              raf_score:       rafResult.raf_score,
              frailty_addend:  rafResult.frailty_addend,
              is_new_enrollee: rafResult.new_enrollee,
              model_segment:   rafResult.model_segment,
              sweep_period:    rafResult.sweep_period,
              v24_score:       rafResult.v24_score,
              v28_score:       rafResult.v28_score,
              hcc_count:       rafResult.hcc_count,
            } : null}
          />
        </div>

        {/* ── Right Column: Results ─────────────────────────────────────────── */}
        <div style={page.rightCol}>
          {error && (
            <div style={page.errorBox}>
              <AlertTriangle size={16} color={tokens.riskHigh} />
              <span>{error}</span>
            </div>
          )}

          {!rafResult && !isCalculating && !error && (
            <div style={page.emptyState}>
              <div style={page.emptyIcon}>
                <Calculator size={36} color={tokens.slate400} />
              </div>
              <div style={page.emptyTitle}>Ready to Calculate</div>
              <div style={page.emptyDesc}>
                Select a patient, configure the options on the left,
                and press <strong>Calculate RAF Score</strong> to run the
                CMS-HCC calculation.
              </div>
              <div style={page.featureList}>
                {[
                  "✦ V24/V28 blended per CMS transition schedule",
                  "✦ ESRD routing: DLY · FG · NE segments",
                  "✦ New Enrollee demographic-only model",
                  "✦ CMS Initial / Midyear / Final sweep windows",
                  "✦ PACE & FIDE-SNP frailty addend (≥3 ADLs)",
                ].map((f) => (
                  <div key={f} style={page.featureItem}>{f}</div>
                ))}
              </div>
            </div>
          )}

          {isCalculating && (
            <div style={page.loadingState}>
              <div style={page.loadingSpinner} />
              <div style={page.loadingText}>Running CMS-HCC calculation…</div>
              <div style={page.loadingDesc}>
                Applying V24/V28 blending, ESRD routing, and interaction terms
              </div>
            </div>
          )}

          {rafResult && !isCalculating && (
            <ResultCard result={rafResult} />
          )}
        </div>
      </div>
    </div>
  );
}

function HeaderStat({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div style={page.headerStat}>
      {icon}
      <span style={{ fontSize: 12, fontWeight: 600 }}>{label}</span>
    </div>
  );
}

const page: Record<string, React.CSSProperties> = {
  wrapper: {
    minHeight: "100vh", background: tokens.slate50,
    padding: "20px 16px",
    fontFamily: "'Inter', -apple-system, sans-serif",
  },
  header: {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    background: `linear-gradient(135deg, ${tokens.slate900}, ${tokens.primaryDark})`,
    borderRadius: 16, padding: "24px 28px", marginBottom: 24, color: tokens.white,
    flexWrap: "wrap", gap: 16,
  },
  headerLeft: { display: "flex", alignItems: "center", gap: 14 },
  headerIcon: {
    width: 48, height: 48, borderRadius: 12,
    background: "rgba(255,255,255,0.15)",
    display: "flex", alignItems: "center", justifyContent: "center",
    flexShrink: 0,
  },
  title:    { margin: 0, fontSize: 22, fontWeight: 800 },
  subtitle: { margin: "4px 0 0", fontSize: 13, opacity: 0.75 },
  headerStats: { display: "flex", gap: 8, flexWrap: "wrap" },
  headerStat: {
    display: "flex", alignItems: "center", gap: 6,
    padding: "6px 12px", borderRadius: 99,
    background: "rgba(255,255,255,0.12)",
    color: tokens.white,
  },

  body: {
    display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
    gap: 20, alignItems: "flex-start",
  },
  leftCol:  { display: "flex", flexDirection: "column", gap: 16 },
  rightCol: { position: "sticky" as const, top: 24 },

  card: {
    background: tokens.white, border: `1px solid ${tokens.slate200}`,
    borderRadius: 12, padding: "16px 18px",
  },
  cardTitle: {
    display: "flex", alignItems: "center", gap: 6,
    fontSize: 12, fontWeight: 700, color: tokens.slate700,
    textTransform: "uppercase", letterSpacing: ".04em",
    marginBottom: 12,
  },
  selectedBadge: {
    display: "flex", alignItems: "center", gap: 6,
    marginTop: 10, padding: "8px 12px",
    background: tokens.successSoft, borderRadius: 8,
    fontSize: 13, color: tokens.successDark,
  },

  errorBox: {
    display: "flex", alignItems: "center", gap: 10,
    padding: "12px 16px", borderRadius: 10,
    background: tokens.riskHighSoft, border: `1px solid ${tokens.dangerBorder}`,
    color: tokens.riskHigh, fontSize: 13, marginBottom: 16,
  },

  emptyState: {
    padding: "48px 32px", textAlign: "center",
    background: tokens.white, border: `1.5px dashed ${tokens.slate200}`,
    borderRadius: 16,
  },
  emptyIcon: {
    width: 72, height: 72, borderRadius: 18,
    background: tokens.slate100,
    display: "flex", alignItems: "center", justifyContent: "center",
    margin: "0 auto 16px",
  },
  emptyTitle: { fontSize: 18, fontWeight: 700, color: tokens.slate900, marginBottom: 8 },
  emptyDesc:  { fontSize: 14, color: tokens.slate500, lineHeight: 1.6, maxWidth: 380, margin: "0 auto 24px" },
  featureList: { display: "flex", flexDirection: "column", gap: 8, textAlign: "left", maxWidth: 320, margin: "0 auto" },
  featureItem: { fontSize: 13, color: tokens.slate600 },

  loadingState: {
    padding: "60px 32px", textAlign: "center",
    background: tokens.white, border: `1.5px solid ${tokens.slate200}`,
    borderRadius: 16,
  },
  loadingSpinner: {
    width: 40, height: 40,
    border: `3px solid ${tokens.primarySoft}`,
    borderTopColor: tokens.primary,
    borderRadius: "50%",
    animation: "spin 0.8s linear infinite",
    margin: "0 auto 16px",
    display: "inline-block",
  },
  loadingText: { fontSize: 16, fontWeight: 700, color: tokens.primaryDark, marginBottom: 6 },
  loadingDesc: { fontSize: 13, color: tokens.slate500 },
};
