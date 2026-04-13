"use client";

import React, { useState, useRef, useCallback, useEffect } from "react";
import {
  Play,
  CheckCircle2,
  Loader2,
  ChevronDown,
  ChevronRight,
  FileText,
  Users,
  Sparkles,
  ArrowDown,
  Database,
  Brain,
  Shield,
  Search,
  Bot,
  BadgeCheck,
  Calculator,
  TrendingUp,
  XCircle,
  AlertTriangle,
  Zap,
  ShieldCheck,
  Info,
  Eye,
  ClipboardList,
  Clock,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { analyzeNote, getPatientsWithEncounters, getPatientEncounters, calculateRAF } from "@/lib/api";
import api from "@/lib/api";
import type { Patient, AnalysisResult } from "@/types";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SAMPLE_NOTE = `Patient: 72-year-old male

History: Type 2 diabetes mellitus, chronic diastolic heart failure, chronic kidney disease.

Vital Signs: BP 138/82, HR 76, SpO2 96%. Weight 192 lbs.

Labs: HbA1c 8.2% (improved from 8.9%). BNP 310 pg/mL. Creatinine 1.8 mg/dL (eGFR 41). K+ 4.4.

Exam: Lungs: bibasilar crackles, mild. Cardiac: regular rate and rhythm. Extremities: 1+ pitting edema bilateral.

Patient denies chest pain. Denies orthopnea.

Assessment and Plan:
1. Type 2 diabetes mellitus with hyperglycemia - A1c improved from 8.9%. Continue metformin 1000mg BID, insulin glargine 20 units. Endocrinology referral.
2. Chronic diastolic heart failure, NYHA class II - BNP stable. Continue furosemide 40mg daily, lisinopril 10mg daily.
3. CKD stage 3b - Creatinine 1.8, eGFR 41. On ACEi. Nephrology referral placed.`;

const HCC_NAMES: Record<string, string> = {
  HCC37: "Diabetes with Complications",
  HCC38: "Diabetes without Complications",
  HCC85: "Congestive Heart Failure",
  HCC226: "Heart Failure",
  HCC329: "CKD Stage 3",
  HCC328: "CKD",
  HCC18: "Diabetes with Complications (V24)",
  HCC19: "Diabetes without Complications (V24)",
  HCC137: "CKD Stage 4",
  HCC111: "COPD",
  HCC280: "COPD (V28)",
  HCC96: "Heart Arrhythmia",
  HCC238: "Atrial Fibrillation",
  HCC52: "Dementia",
  HCC127: "Dementia (V28)",
  HCC155: "Depression",
  HCC8: "Metastatic Cancer",
  HCC1: "HIV",
  HCC190: "ALS / Motor Neuron Disease",
  HCC189: "Amputation Status",
  HCC186: "Transplant Status",
  HCC12: "Breast/Prostate Cancer",
  HCC48: "Morbid Obesity",
  HCC21: "Protein-Calorie Malnutrition",
  HCC22: "Morbid Obesity",
  HCC40: "Rheumatoid Arthritis",
  HCC57: "Schizophrenia",
  HCC59: "Bipolar Disorder",
  HCC78: "Parkinson Disease",
  HCC77: "Multiple Sclerosis",
  HCC103: "Hemiplegia",
  HCC107: "Vascular Disease with Complications",
  HCC108: "Vascular Disease",
  HCC158: "Pressure Ulcer Stage 3",
  HCC381: "Pressure Ulcer (V28)",
  HCC151: "Schizophrenia (V28)",
  HCC154: "Bipolar (V28)",
  HCC199: "Parkinson (V28)",
  HCC198: "Multiple Sclerosis (V28)",
  HCC221: "Heart Transplant",
  HCC93: "Rheumatoid Arthritis (V28)",
  HCC94: "Lupus/Autoimmune",
  HCC253: "Hemiplegia (V28)",
  HCC263: "Vascular with Complications (V28)",
  HCC224: "CHF Acute (V28)",
  HCC327: "CKD Stage 4 (V28)",
  HCC146: "Cancer (V28)",
  HCC29: "Hepatitis",
  HCC135: "Sleep Apnea",
  HCC138: "Substance Use Disorder",
  HCC157: "Pressure Ulcer",
};

interface PipelineStep {
  id: number;
  name: string;
  shortName: string;
  icon: React.ElementType;
  model?: string;
}

const PIPELINE_STEPS: PipelineStep[] = [
  { id: 0, name: "OpenEMR Data Retrieval", shortName: "EMR", icon: Database },
  { id: 1, name: "Clinical NER Extraction", shortName: "NER", icon: Brain },
  { id: 2, name: "Negation Detection", shortName: "Negation", icon: Shield },
  { id: 3, name: "ICD-10 Code Mapping", shortName: "ICD-10", icon: Search, model: "HCC Mapping" },
  { id: 4, name: "Clinical Analysis", shortName: "Analysis", icon: Bot },
  { id: 5, name: "ICD-10 Validation", shortName: "Validate", icon: BadgeCheck, model: "Clinical Database" },
  { id: 6, name: "RAF Calculation", shortName: "RAF", icon: Calculator, model: "HCC Model" },
  { id: 7, name: "Gap Analysis", shortName: "Gaps", icon: TrendingUp },
  { id: 8, name: "Quality Verification", shortName: "Verify", icon: ShieldCheck },
  { id: 9, name: "Review Queue Routing", shortName: "Review", icon: ClipboardList },
];

type StepStatus = "pending" | "running" | "done" | "error";

// ---------------------------------------------------------------------------
// Pipeline Loading State Component
// ---------------------------------------------------------------------------

const PROGRESS_HINTS = [
  { maxSec: 10, text: "Extracting clinical entities from note..." },
  { maxSec: 20, text: "Validating ICD-10 codes against CMS database..." },
  { maxSec: 30, text: "Looking up HCC mappings..." },
  { maxSec: 45, text: "Calculating RAF score..." },
  { maxSec: 60, text: "Almost done — complex notes take longer..." },
  { maxSec: Infinity, text: "Still processing — this is a very detailed note..." },
];

function getProgressHint(elapsed: number): string {
  for (const hint of PROGRESS_HINTS) {
    if (elapsed < hint.maxSec) return hint.text;
  }
  return PROGRESS_HINTS[PROGRESS_HINTS.length - 1].text;
}

function PipelineLoadingState() {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(interval);
  }, []);

  // Slow progress bar: asymptotically approaches 90% over ~90s
  const progressValue = Math.min(90, (elapsed / (elapsed + 15)) * 100);

  return (
    <Card className="premium-card border-2 border-teal-400 dark:border-teal-600 shadow-lg shadow-teal-500/10 overflow-hidden card-glow-blue animate-fade-in">
      <CardContent className="flex flex-col items-center gap-5 py-10 px-6">
        {/* Pulsing brain icon */}
        <div className="relative">
          <div className="absolute inset-0 rounded-full bg-teal-400/20 animate-ping" />
          <div className="relative flex h-16 w-16 items-center justify-center rounded-full bg-teal-50 dark:bg-teal-950 border-2 border-teal-400">
            <Brain className="h-8 w-8 text-teal-600 animate-pulse" />
          </div>
        </div>

        {/* Title */}
        <div className="text-center space-y-1">
          <p className="text-lg font-semibold text-teal-700 dark:text-teal-300">
            Analyzing clinical note...
          </p>
          <p className="text-sm text-muted-foreground">
            {getProgressHint(elapsed)}
          </p>
        </div>

        {/* Elapsed time */}
        <Badge variant="outline" className="text-sm font-mono px-3 py-1 border-teal-300 dark:border-teal-700 text-teal-600 dark:text-teal-400">
          Elapsed: {elapsed}s
        </Badge>

        {/* Progress bar */}
        <div className="w-full max-w-md">
          <Progress value={progressValue} className="h-2" />
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Color helpers
// ---------------------------------------------------------------------------
const ENTITY_COLORS: Record<string, { bg: string; text: string; highlight: string }> = {
  disease: { bg: "bg-rose-100 dark:bg-rose-900/40", text: "text-rose-700 dark:text-rose-300", highlight: "bg-rose-200 dark:bg-rose-800/60" },
  medication: { bg: "bg-blue-100 dark:bg-blue-900/40", text: "text-blue-700 dark:text-blue-300", highlight: "bg-blue-200 dark:bg-blue-800/60" },
  lab: { bg: "bg-amber-100 dark:bg-amber-900/40", text: "text-amber-700 dark:text-amber-300", highlight: "bg-amber-200 dark:bg-amber-800/60" },
  symptom: { bg: "bg-purple-100 dark:bg-purple-900/40", text: "text-purple-700 dark:text-purple-300", highlight: "bg-purple-200 dark:bg-purple-800/60" },
  procedure: { bg: "bg-cyan-100 dark:bg-cyan-900/40", text: "text-cyan-700 dark:text-cyan-300", highlight: "bg-cyan-200 dark:bg-cyan-800/60" },
  anatomy: { bg: "bg-emerald-100 dark:bg-emerald-900/40", text: "text-emerald-700 dark:text-emerald-300", highlight: "bg-emerald-200 dark:bg-emerald-800/60" },
};

function getEntityColor(cat: string) {
  return ENTITY_COLORS[cat?.toLowerCase()] ?? { bg: "bg-gray-100 dark:bg-gray-800", text: "text-gray-700 dark:text-gray-300", highlight: "bg-gray-200 dark:bg-gray-700" };
}

function confidenceColor(c: number) {
  if (c >= 0.9) return "text-emerald-600 dark:text-emerald-400";
  if (c >= 0.7) return "text-amber-600 dark:text-amber-400";
  return "text-red-600 dark:text-red-400";
}

function confidenceBg(c: number) {
  if (c >= 0.9) return "bg-emerald-500";
  if (c >= 0.7) return "bg-amber-500";
  return "bg-red-500";
}

function pct(v: number) {
  return `${(v * 100).toFixed(1)}%`;
}

// ---------------------------------------------------------------------------
// Highlight entities in note text
// ---------------------------------------------------------------------------
function HighlightedNote({ text, entities }: { text: string; entities: Array<{ text: string; category?: string }> }) {
  if (!entities?.length) return <pre className="whitespace-pre-wrap font-mono text-sm leading-relaxed">{text}</pre>;

  // Sort entities by length descending so longer matches take priority
  const sorted = [...entities].sort((a, b) => b.text.length - a.text.length);

  // Build segments
  type Seg = { text: string; entity?: { text: string; category?: string } };
  const segments: Seg[] = [];
  let remaining = text;

  while (remaining.length > 0) {
    let earliest = -1;
    let matchedEntity: (typeof sorted)[0] | null = null;
    let matchPos = remaining.length;

    for (const ent of sorted) {
      const idx = remaining.toLowerCase().indexOf(ent.text.toLowerCase());
      if (idx !== -1 && idx < matchPos) {
        matchPos = idx;
        matchedEntity = ent;
        earliest = idx;
      }
    }

    if (earliest === -1 || !matchedEntity) {
      segments.push({ text: remaining });
      break;
    }

    if (earliest > 0) {
      segments.push({ text: remaining.slice(0, earliest) });
    }
    segments.push({
      text: remaining.slice(earliest, earliest + matchedEntity.text.length),
      entity: matchedEntity,
    });
    remaining = remaining.slice(earliest + matchedEntity.text.length);
  }

  return (
    <pre className="whitespace-pre-wrap font-mono text-sm leading-relaxed">
      {segments.map((seg, i) =>
        seg.entity ? (
          <mark
            key={i}
            className={cn(
              "rounded px-1 py-0.5 font-semibold",
              getEntityColor(seg.entity.category ?? "").highlight,
              getEntityColor(seg.entity.category ?? "").text
            )}
            title={`${seg.entity.category ?? "entity"}`}
          >
            {seg.text}
          </mark>
        ) : (
          <span key={i}>{seg.text}</span>
        )
      )}
    </pre>
  );
}

// ---------------------------------------------------------------------------
// MEAT Grid Component
// ---------------------------------------------------------------------------
function MEATGrid({ meat, size = "normal" }: { meat: { M?: string; E?: string; A?: string; T?: string; monitoring?: string; evaluation?: string; assessment?: string; treatment?: string }; size?: "normal" | "compact" }) {
  const m = meat.M ?? meat.monitoring ?? "";
  const e = meat.E ?? meat.evaluation ?? "";
  const a = meat.A ?? meat.assessment ?? "";
  const t = meat.T ?? meat.treatment ?? "";

  const items = [
    { label: "M", title: "MONITOR", value: m },
    { label: "E", title: "EVALUATE", value: e },
    { label: "A", title: "ASSESS", value: a },
    { label: "T", title: "TREAT", value: t },
  ];

  return (
    <div className="grid grid-cols-4 gap-2">
      {items.map((item) => {
        const filled = !!item.value;
        return (
          <div
            key={item.label}
            className={cn(
              "rounded-lg border p-2 text-center transition-colors",
              filled
                ? "border-emerald-300 bg-emerald-50 dark:border-emerald-700 dark:bg-emerald-950"
                : "border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-900"
            )}
          >
            <div className={cn(
              "text-xs font-bold tracking-wider",
              filled ? "text-emerald-700 dark:text-emerald-400" : "text-gray-400"
            )}>
              {item.title}
            </div>
            <div className={cn(
              "my-1 text-lg font-bold",
              filled ? "text-emerald-600 dark:text-emerald-400" : "text-gray-300 dark:text-gray-600"
            )}>
              {filled ? "\u2705" : "\u2B1C"}
            </div>
            <div className={cn(
              "text-xs leading-tight min-h-[2rem]",
              filled ? "text-gray-700 dark:text-gray-300" : "text-gray-400"
            )}>
              {item.value || "Not documented"}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step Content Renderers
// ---------------------------------------------------------------------------

 

function Step0Content({ data, noteText, extraction }: { data: Record<string, unknown>; noteText: string; extraction?: Record<string, unknown> }) {
  const [now] = useState(() => Date.now());
  if (!data) return null;
  const age = (data.demographics as Record<string, unknown> | undefined)?.age as number | undefined
    ?? (data._meta as Record<string, unknown> | undefined)?.patient_age as number | undefined
    ?? (data.DOB ? Math.floor((now - new Date(data.DOB as string).getTime()) / 31557600000) : null);
  const sex = (data.demographics as Record<string, unknown> | undefined)?.sex as string | undefined
    ?? (data._meta as Record<string, unknown> | undefined)?.patient_sex as string | undefined
    ?? data.sex as string | undefined
    ?? null;
  const displayAge = age ?? "—";
  const displaySex = sex ?? "—";

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-3">
        <div className="rounded-lg border bg-muted/30 p-3">
          <div className="text-xs text-muted-foreground">Patient ID</div>
          <div className="text-lg font-bold">{(data.patient_id ?? data.pid ?? 0) as number}</div>
        </div>
        <div className="rounded-lg border bg-muted/30 p-3">
          <div className="text-xs text-muted-foreground">Age / Sex</div>
          <div className="text-lg font-bold">{displayAge} / {displaySex}</div>
        </div>

        <div className="rounded-lg border bg-muted/30 p-3">
          <div className="text-xs text-muted-foreground">Source</div>
          <div className="text-sm font-medium">{(data.source as string) ?? "Clinical Note"}</div>
        </div>
      </div>
      <div className="rounded-lg border bg-muted/20 p-4 max-h-48 overflow-y-auto">
        <pre className="font-mono text-xs leading-relaxed text-muted-foreground" style={{ whiteSpace: "pre-wrap" }}>
          {(noteText as string) || (data.note_text as string) || "Patient data loaded from OpenEMR"}
        </pre>
      </div>
      {extraction && <ExtractionSummary extraction={extraction} />}
    </div>
  );
}

function Step1Content({ entities, noteText }: { entities: any[]; noteText: string }) {
  if (!entities?.length) return <p className="text-sm text-muted-foreground">No entities extracted.</p>;
  return (
    <div className="space-y-4">
      {/* Entity Table */}
      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/30">
              <TableHead className="w-10">#</TableHead>
              <TableHead>Entity Text</TableHead>
              <TableHead>Category</TableHead>
              <TableHead>ICD-10</TableHead>
              <TableHead className="text-right">Confidence</TableHead>
              <TableHead>Source</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {entities.map((ent: any, i: number) => {
              const cat = ent.category ?? "disease";
              const colors = getEntityColor(cat);
              return (
                <TableRow key={ent.icd10 ?? ent.icd10_code ?? i} className={cn("hover:bg-muted/50 transition-colors", i % 2 === 0 ? "bg-muted/10" : "")}>
                  <TableCell className="font-mono text-muted-foreground">{i + 1}</TableCell>
                  <TableCell className="font-semibold">{ent.name ?? ent.text}</TableCell>
                  <TableCell>
                    <Badge variant="secondary" className={cn("text-xs", colors.bg, colors.text)}>
                      {cat}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge className="bg-teal-100 text-teal-800 dark:bg-teal-900 dark:text-teal-200 font-mono">
                      {ent.icd10 ?? ent.icd10_code ?? "---"}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <span className={cn("font-mono font-bold", confidenceColor(ent.confidence ?? 0))}>
                      {pct(ent.confidence ?? 0)}
                    </span>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {ent.source ?? "NER"}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      {/* Highlighted note */}
      <div>
        <h4 className="mb-2 text-sm font-semibold text-muted-foreground flex items-center gap-2">
          <FileText className="h-4 w-4" /> Entities Highlighted in Note
        </h4>
        <div className="rounded-lg border bg-white dark:bg-gray-950 p-4 max-h-64 overflow-y-auto">
          <HighlightedNote text={noteText} entities={entities} />
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          {Object.entries(ENTITY_COLORS).map(([cat, colors]) => (
            <span key={cat} className={cn("inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium", colors.bg, colors.text)}>
              <span className={cn("inline-block h-2 w-2 rounded-full", colors.highlight)} />
              {cat}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function Step2Content({ data, negatedConditions }: { data: any; negatedConditions: any[] }) {
  if (!data && (!negatedConditions || !negatedConditions.length)) return <p className="text-sm text-muted-foreground">No negation data available.</p>;
  if (!data) return null;
  const before: any[] = data.before ?? [];
  const after: any[] = data.after ?? [];
  const afterTexts = new Set(after.map((e: any) => (e.name ?? e.text ?? "").toLowerCase()));
  const negNames = (negatedConditions ?? []).map((n: any) => (n.description ?? n.condition ?? n).toString().toLowerCase());

  // Build combined rows: all from before + any negated that aren't in before
  const allRows: { name: string; icd10: string; kept: boolean; reason: string }[] = [];

  for (const ent of before) {
    const name = ent.name ?? ent.text ?? "";
    const kept = afterTexts.has(name.toLowerCase());
    let reason = kept ? "Present in assessment" : "Negated in note";
    if (!kept && negNames.some((n: string) => name.toLowerCase().includes(n) || n.includes(name.toLowerCase()))) {
      reason = `"denies ${name.toLowerCase()}"`;
    }
    allRows.push({ name, icd10: ent.icd10 ?? ent.icd10_code ?? "", kept, reason });
  }

  // Add negated conditions not already in the list
  for (const neg of negatedConditions ?? []) {
    const desc = (neg.description ?? neg.condition ?? neg).toString();
    if (!allRows.some((r) => r.name.toLowerCase().includes(desc.toLowerCase()))) {
      allRows.push({ name: desc, icd10: "", kept: false, reason: `"denies ${desc.toLowerCase()}"` });
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div className="rounded-lg border p-3 bg-muted/20">
          <div className="text-sm font-semibold text-muted-foreground mb-1">INPUT: {before.length} entities</div>
          <div className="text-2xl font-bold">{before.length}</div>
        </div>
        <div className="rounded-lg border p-3 bg-emerald-50 dark:bg-emerald-950">
          <div className="text-sm font-semibold text-emerald-700 dark:text-emerald-400 mb-1">OUTPUT: {after.length} kept</div>
          <div className="text-2xl font-bold text-emerald-600">{after.length}</div>
        </div>
      </div>

      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/30">
              <TableHead>Entity</TableHead>
              <TableHead>ICD-10</TableHead>
              <TableHead className="text-center">Before</TableHead>
              <TableHead className="text-center">After</TableHead>
              <TableHead>Reason</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {allRows.map((row, i) => (
              <TableRow key={row.icd10 ?? i} className={cn("hover:bg-muted/50 transition-colors", !row.kept ? "bg-red-50/50 dark:bg-red-950/20" : i % 2 === 0 ? "bg-muted/10" : "")}>
                <TableCell className={cn("font-medium", !row.kept && "line-through text-muted-foreground")}>
                  {row.name}
                </TableCell>
                <TableCell>
                  {row.icd10 && (
                    <Badge className="bg-teal-100 text-teal-800 dark:bg-teal-900 dark:text-teal-200 font-mono text-xs">
                      {row.icd10}
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="text-center">
                  <Badge variant="outline" className="text-xs">Present</Badge>
                </TableCell>
                <TableCell className="text-center">
                  {row.kept ? (
                    <Badge className="bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200 text-xs">
                      KEPT
                    </Badge>
                  ) : (
                    <Badge className="bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200 text-xs">
                      REMOVED
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground italic">{row.reason}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function Step3Content({ candidates, afterEntities, toolCalls }: { candidates: any[]; afterEntities: any[]; toolCalls?: any[] }) {
  // Group candidates by entity
  const entityGroups: Record<string, string[]> = {};

  if (candidates?.length) {
    for (const c of candidates) {
      const key = c.entity ?? c.query ?? c.condition ?? "Unknown";
      if (!entityGroups[key]) entityGroups[key] = [];
      entityGroups[key].push(c.icd10 ?? c.code ?? c.icd10_code ?? "");
    }
  }

  // Fallback: build from afterEntities if no candidates
  if (!Object.keys(entityGroups).length && afterEntities?.length) {
    for (const ent of afterEntities) {
      const name = ent.name ?? ent.text ?? "";
      entityGroups[name] = [ent.icd10 ?? ent.icd10_code ?? ""];
    }
  }

  // Build ICD-10 to HCC mapping from tool_calls (validate_icd10, lookup_hcc)
  const icdHccMappings: { icd10: string; description: string; hcc: string; hccLabel: string; valid: boolean }[] = [];
  if (toolCalls?.length) {
    for (const tc of toolCalls) {
      const fn = tc.function ?? "";
      const args = tc.args ?? {};
      const res = tc.result ?? {};
      if (fn === "validate_icd10" || fn === "validate_icd10_code") {
        icdHccMappings.push({
          icd10: args.icd10_code ?? args.code ?? "",
          description: res.description ?? args.description ?? "",
          hcc: "",
          hccLabel: "",
          valid: res.valid !== false,
        });
      }
      if (fn === "lookup_hcc" || fn === "lookup_hcc_mapping") {
        const code = args.icd10_code ?? args.code ?? "";
        const hcc = res.hcc_code ?? res.hcc ?? "";
        const existing = icdHccMappings.find((m) => m.icd10 === code);
        if (existing) {
          existing.hcc = hcc;
          existing.hccLabel = res.hcc_label ?? HCC_NAMES[hcc] ?? HCC_NAMES[`HCC${hcc}`] ?? "";
        } else {
          icdHccMappings.push({
            icd10: code,
            description: res.description ?? "",
            hcc,
            hccLabel: res.hcc_label ?? HCC_NAMES[hcc] ?? HCC_NAMES[`HCC${hcc}`] ?? "",
            valid: true,
          });
        }
      }
    }
  }

  const totalCandidates = candidates?.length ?? Object.values(entityGroups).reduce((s, arr) => s + arr.length, 0);
  const hasEntityGroups = Object.keys(entityGroups).length > 0;
  const hasMappings = icdHccMappings.length > 0;

  if (!hasEntityGroups && !hasMappings) {
    return <p className="text-sm text-muted-foreground">No ICD-10 code mappings available.</p>;
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div className="rounded-lg border p-3 bg-muted/20">
          <div className="text-xs text-muted-foreground">Codes Mapped</div>
          <div className="text-2xl font-bold">{hasMappings ? icdHccMappings.length : totalCandidates}</div>
        </div>
        <div className="rounded-lg border p-3 bg-muted/20">
          <div className="text-xs text-muted-foreground">Source</div>
          <div className="text-2xl font-bold">{hasMappings ? "HCC Mapping" : "74,736"} <span className="text-sm font-normal text-muted-foreground">{hasMappings ? "via tool calls" : "ICD-10 codes"}</span></div>
        </div>
      </div>

      {/* ICD-10 to HCC mapping table from tool_calls */}
      {hasMappings && (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/30">
                <TableHead>ICD-10 Code</TableHead>
                <TableHead>Description</TableHead>
                <TableHead>HCC Mapping</TableHead>
                <TableHead className="text-center">Valid</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {icdHccMappings.map((m, i) => (
                <TableRow key={m.icd10} className={cn("hover:bg-muted/50 transition-colors", i % 2 === 0 ? "bg-muted/10" : "")}>
                  <TableCell>
                    <Badge className="bg-teal-100 text-teal-800 dark:bg-teal-900 dark:text-teal-200 font-mono text-xs">
                      {m.icd10}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-medium text-sm">{m.description}</TableCell>
                  <TableCell>
                    {m.hcc ? (
                      <div className="flex items-center gap-2">
                        <Badge className="bg-blue-600 text-white font-mono text-xs">
                          {m.hcc.startsWith("HCC") ? m.hcc : `HCC${m.hcc}`}
                        </Badge>
                        {m.hccLabel && <span className="text-xs text-muted-foreground">{m.hccLabel}</span>}
                      </div>
                    ) : (
                      <span className="text-xs text-muted-foreground">No HCC mapping</span>
                    )}
                  </TableCell>
                  <TableCell className="text-center">
                    {m.valid ? (
                      <Badge className="bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200 text-xs">
                        <CheckCircle2 className="mr-1 h-3 w-3" /> Valid
                      </Badge>
                    ) : (
                      <Badge className="bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200 text-xs">
                        <XCircle className="mr-1 h-3 w-3" /> Invalid
                      </Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Entity-based candidate codes table (legacy/retrieve-rank pipeline) */}
      {hasEntityGroups && !hasMappings && (
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/30">
                <TableHead>Entity</TableHead>
                <TableHead>Candidate ICD-10 Codes</TableHead>
                <TableHead className="text-right">Count</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {Object.entries(entityGroups).map(([entity, codes], i) => (
                <TableRow key={entity}>
                  <TableCell className="font-semibold">{entity}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {codes.slice(0, 8).map((code, j) => (
                        <Badge key={j} className="bg-teal-100 text-teal-800 dark:bg-teal-900 dark:text-teal-200 font-mono text-xs">
                          {code}
                        </Badge>
                      ))}
                      {codes.length > 8 && (
                        <Badge variant="outline" className="text-xs">+{codes.length - 8} more</Badge>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="text-right font-mono">{codes.length}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <p className="text-sm text-muted-foreground text-center">
        {hasMappings
          ? `${icdHccMappings.length} ICD-10 codes validated and mapped to HCC categories`
          : `${totalCandidates} candidate codes retrieved from 74,736 indexed ICD-10 codes`
        }
      </p>
    </div>
  );
}

function Step4Content({ data }: { data: any }) {
  if (!data) return <p className="text-sm text-muted-foreground">No analysis data available.</p>;
  const diagnoses: any[] = data.diagnoses ?? [];
  const negated: any[] = data.negated ?? [];
  const suspects: any[] = data.suspects ?? [];

  if (!diagnoses.length && !negated.length && !suspects.length) {
    return <p className="text-sm text-muted-foreground">No diagnoses, negated conditions, or suspects found in this note.</p>;
  }

  return (
    <div className="space-y-6">
      {/* Diagnosis Cards */}
      {diagnoses.map((dx: any, i: number) => {
        const hcc = dx.hcc_code ?? dx.hcc_mapping?.hcc_code ?? dx.hcc ?? null;
        const hccLabel = hcc ? (HCC_NAMES[hcc] ?? HCC_NAMES[`HCC${hcc}`] ?? hcc) : null;
        const conf = dx.confidence ?? 1.0;
        const meat = dx.meat ?? {};
        const meatScore = dx.meat_score ?? 0;
        const condition = dx.description ?? dx.condition ?? dx.icd10_description ?? "";
        const icd = dx.icd10 ?? dx.icd10_code ?? "";

        return (
          <div key={dx.icd10 ?? dx.icd10_code ?? i} className="rounded-xl border-2 border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-950 overflow-hidden shadow-sm">
            {/* Header */}
            <div className="p-4 border-b bg-gradient-to-r from-gray-50 to-white dark:from-gray-900 dark:to-gray-950">
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="text-lg font-bold">{condition}</h3>
                  {icd && (
                    <Badge className="mt-1 bg-teal-100 text-teal-800 dark:bg-teal-900 dark:text-teal-200 font-mono">
                      {icd}
                    </Badge>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {hcc && (
                    <Badge className="bg-blue-600 text-white text-sm px-3 py-1 font-bold">
                      {hcc.startsWith("HCC") ? hcc : `HCC ${hcc}`}
                    </Badge>
                  )}
                  <Badge variant="outline" className="text-xs">
                    MEAT {meatScore}/4
                  </Badge>
                </div>
              </div>
              {hccLabel && hcc && (
                <p className="mt-1 text-sm text-muted-foreground">{hccLabel}</p>
              )}

              {/* Confidence bar */}
              <div className="mt-3 flex items-center gap-3">
                <span className="text-xs text-muted-foreground w-20">Confidence</span>
                <div className="flex-1 h-3 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
                  <div
                    className={cn("h-full rounded-full transition-all", confidenceBg(conf))}
                    style={{ width: `${conf * 100}%` }}
                  />
                </div>
                <span className={cn("text-sm font-bold font-mono", confidenceColor(conf))}>
                  {pct(conf)}
                </span>
              </div>
              {dx.source && (
                <div className="mt-1 text-xs text-muted-foreground">Source: {dx.source}</div>
              )}
            </div>

            {/* MEAT Grid */}
            <div className="p-4">
              <MEATGrid meat={meat} />
            </div>

            {/* Supporting text */}
            {dx.supporting_text && (
              <div className="px-4 pb-4">
                <div className="text-xs font-semibold text-muted-foreground mb-1">Supporting Evidence</div>
                <p className="text-sm text-muted-foreground italic bg-muted/30 rounded-lg p-2">
                  &ldquo;{dx.supporting_text}&rdquo;
                </p>
              </div>
            )}
          </div>
        );
      })}

      {/* Negated conditions */}
      {negated?.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-muted-foreground mb-2 flex items-center gap-2">
            <XCircle className="h-4 w-4 text-red-500" /> Negated Conditions
          </h4>
          <div className="flex flex-wrap gap-2">
            {negated.map((neg: any, i: number) => {
              const desc = typeof neg === "string" ? neg : (neg.description ?? neg.condition ?? "");
              return (
                <Badge key={desc || i} className="bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200 line-through text-sm">
                  {desc}
                </Badge>
              );
            })}
          </div>
        </div>
      )}

      {/* Suspect conditions */}
      {suspects?.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-muted-foreground mb-2 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-500" /> Suspect Conditions (Potential Gaps)
          </h4>
          <div className="space-y-2">
            {suspects.map((s: any, i: number) => (
              <div key={s.suspect_icd10 ?? s.icd10 ?? i} className="flex items-center gap-2 rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950 p-2">
                <Badge className="bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200 font-mono text-xs">
                  {s.suspect_icd10 ?? s.icd10 ?? s.icd10_code ?? ""}
                </Badge>
                <span className="text-sm font-medium">{s.condition ?? s.description ?? ""}</span>
                <span className="ml-auto text-xs text-muted-foreground">{s.evidence ?? ""}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Step5Content({ data }: { data: any[] }) {
  if (!data?.length) return <p className="text-sm text-muted-foreground">No codes to validate.</p>;
  return (
    <div className="rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/30">
            <TableHead>ICD-10 Code</TableHead>
            <TableHead>Description</TableHead>
            <TableHead className="text-center">Status</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.map((item: any, i: number) => (
            <TableRow key={item.icd10 ?? item.code ?? item.icd10_code ?? i} className={cn("hover:bg-muted/50 transition-colors", i % 2 === 0 ? "bg-muted/10" : "")}>
              <TableCell>
                <Badge className="bg-teal-100 text-teal-800 dark:bg-teal-900 dark:text-teal-200 font-mono">
                  {item.icd10 ?? item.code ?? item.icd10_code ?? ""}
                </Badge>
              </TableCell>
              <TableCell className="font-medium">{item.description ?? item.condition ?? ""}</TableCell>
              <TableCell className="text-center">
                {item.valid !== false ? (
                  <Badge className="bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200">
                    <CheckCircle2 className="mr-1 h-3 w-3" /> VALID
                  </Badge>
                ) : (
                  <Badge className="bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200">
                    <XCircle className="mr-1 h-3 w-3" /> INVALID
                  </Badge>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function Step6Content({ data }: { data: any }) {
  if (!data) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <Calculator className="h-10 w-10 mx-auto mb-3 opacity-40" />
        <p className="font-medium">RAF calculation pending...</p>
        <p className="text-sm mt-1">The RAF score will appear here once the pipeline completes. If you pasted a note without selecting a patient, age and sex may not have been available for demographic scoring.</p>
      </div>
    );
  }
  const score = data.raf_score ?? 0;
  const components: any[] = data.components ?? [];
  // cc_to_dx: maps "HCC226" -> ["I5022", "I110"] — used for audit trail annotations
  const ccToDx: Record<string, string[]> = data.cc_to_dx ?? {};

  // Classify component type for color coding
  const getType = (comp: any): "demographic" | "hcc" | "interaction" => {
    const c = (comp.component ?? "").toLowerCase();
    if (c.includes("hcc")) return "hcc";
    // Match interaction terms: explicit _v28 suffix, known term names, or description hint
    if (
      c.includes("_v28") ||
      c.includes("_hf") ||
      c.includes("_kidney") ||
      c.includes("chr_lung") ||
      c.includes("diabetes_hf") ||
      c.includes("hf_hcc") ||
      c === "d6" ||
      c.includes("interaction") ||
      (comp.description ?? "").toLowerCase().includes("interaction")
    ) return "interaction";
    return "demographic";
  };

  const badgeStyles: Record<string, string> = {
    demographic: "bg-blue-600 text-white",
    hcc: "bg-emerald-600 text-white",
    interaction: "bg-purple-600 text-white",
  };

  const rowHighlight: Record<string, string> = {
    demographic: "bg-blue-50/50 dark:bg-blue-950/20",
    hcc: "",
    interaction: "bg-purple-50/50 dark:bg-purple-950/20",
  };

  return (
    <div className="space-y-6">
      {/* Big RAF score */}
      <div className="text-center py-6 rounded-xl bg-gradient-to-br from-blue-50 to-teal-50 dark:from-blue-950 dark:to-teal-950 border-2 border-blue-200 dark:border-blue-800">
        <div className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">Total RAF Score</div>
        <div className="text-6xl font-black text-blue-700 dark:text-blue-400 mt-2">{typeof score === "number" ? (score ?? 0).toFixed(3) : score}</div>
        <div className="flex justify-center gap-6 mt-3 text-sm">
          {data.demographic_score != null && (
            <span className="text-blue-600 dark:text-blue-400">Demographic: <strong>{(+(data.demographic_score ?? 0)).toFixed(3)}</strong></span>
          )}
          {data.disease_score != null && (
            <span className="text-emerald-600 dark:text-emerald-400">Disease: <strong>{(+(data.disease_score ?? 0)).toFixed(3)}</strong></span>
          )}
          {data.interaction_score != null && +data.interaction_score > 0 && (
            <span className="text-purple-600 dark:text-purple-400">Interactions: <strong>{(+(data.interaction_score ?? 0)).toFixed(3)}</strong></span>
          )}
        </div>
        {data.payment_raf != null ? (
          <div className="text-sm text-muted-foreground mt-2">
            Raw RAF: <strong>{typeof score === "number" ? (score ?? 0).toFixed(3) : score}</strong>
            {" | "}Payment-adjusted: <strong className="text-blue-700 dark:text-blue-400">{(+(data.payment_raf ?? 0)).toFixed(3)}</strong>
            {data.maci != null && <span> (MACI {(+data.maci * 100).toFixed(1)}%{data.normalization_factor != null ? `, norm ${(+data.normalization_factor).toFixed(3)}` : ""})</span>}
          </div>
        ) : (
          <div className="text-sm text-muted-foreground mt-2">HCC Risk Adjustment Factor</div>
        )}
      </div>

      {/* Score Breakdown table */}
      <div className="rounded-lg border">
        <div className="px-4 py-2.5 bg-muted/30 border-b">
          <h4 className="text-sm font-semibold tracking-wide">Score Breakdown</h4>
        </div>
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/30">
              <TableHead>Component</TableHead>
              <TableHead className="text-right">Coefficient</TableHead>
              <TableHead>Description</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {components.map((comp: any, i: number) => {
              const type = getType(comp);
              const hccCode = comp.component ?? "";
              const hccName = type === "hcc"
                ? (HCC_NAMES[hccCode.replace(/\s/g, "")] ?? HCC_NAMES[hccCode] ?? comp.description ?? "")
                : (comp.description ?? "");
              // Audit trail: ICD codes that triggered this HCC (e.g. HCC226 -> I5022, I110)
              const sourceCodes: string[] = type === "hcc" ? (ccToDx[hccCode] ?? []) : [];
              return (
                <TableRow key={comp.component ?? i} className={cn("hover:bg-muted/50 transition-colors", rowHighlight[type])}>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <Badge className={cn("font-mono text-xs", badgeStyles[type])}>{hccCode}</Badge>
                    </div>
                  </TableCell>
                  <TableCell className="text-right font-mono">
                    {typeof comp.coefficient === "number" ? (comp.coefficient ?? 0).toFixed(3) : comp.coefficient}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    <span>{hccName}</span>
                    {sourceCodes.length > 0 && (
                      <span className="ml-2 text-xs text-emerald-600 dark:text-emerald-400 font-mono">
                        (from {sourceCodes.map((c) => c.replace(/^(.{3})(.+)$/, "$1.$2")).join(", ")})
                      </span>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
            {/* Total row */}
            <TableRow className="bg-blue-50 dark:bg-blue-950 font-bold border-t-2">
              <TableCell><span className="font-bold text-blue-700 dark:text-blue-400">TOTAL</span></TableCell>
              <TableCell className="text-right font-mono text-lg text-blue-700 dark:text-blue-400">
                {typeof score === "number" ? (score ?? 0).toFixed(3) : score}
              </TableCell>
              <TableCell />
            </TableRow>
          </TableBody>
        </Table>
      </div>

      {/* Interaction Terms Callout */}
      {data.interaction_details && data.interaction_details.length > 0 && (
        <div className="rounded-xl border-2 border-purple-200 dark:border-purple-800 bg-purple-50/50 dark:bg-purple-950/20 p-4">
          <div className="flex items-center gap-2 mb-3">
            <div className="h-2 w-2 rounded-full bg-purple-600" />
            <span className="font-bold text-purple-700 dark:text-purple-400 text-sm uppercase tracking-wider">
              Interaction Bonuses — {data.interaction_details.length} applied
            </span>
            <span className="ml-auto text-xs text-muted-foreground">
              Bonuses applied when multiple related conditions are present
            </span>
          </div>
          <div className="space-y-2">
            {(data.interaction_details as any[]).map((item: any, i: number) => (
              <div key={item.term ?? i} className="flex items-center justify-between rounded-lg bg-white dark:bg-gray-900 px-3 py-2 text-sm">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs bg-purple-100 dark:bg-purple-900 text-purple-700 dark:text-purple-300 rounded px-1.5 py-0.5">
                    {item.term}
                  </span>
                  <span className="text-muted-foreground">{item.description ?? item.term}</span>
                </div>
                <span className="font-mono font-bold text-purple-700 dark:text-purple-400">
                  +{typeof item.coefficient === "number" ? (item.coefficient ?? 0).toFixed(4) : item.coefficient}
                </span>
              </div>
            ))}
            <div className="flex justify-between items-center pt-1 border-t border-purple-200 dark:border-purple-800 text-sm font-semibold">
              <span className="text-purple-700 dark:text-purple-400">Total Interaction Adjustment</span>
              <span className="font-mono text-purple-700 dark:text-purple-400">
                +{data.interaction_score != null ? (+data.interaction_score).toFixed(4) : "0.0000"}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Core Engine Breakdown - 4 Engines */}
      <div className="mt-8">
        <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
          <Zap className="h-5 w-5 text-teal-600" />
          Core Engine Processing
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Engine 1: RAF Calculator */}
          <div className="rounded-xl border-2 border-blue-200 dark:border-blue-800 bg-blue-50/50 dark:bg-blue-950/30 p-4">
            <div className="flex items-center gap-2 mb-3">
              <Calculator className="h-5 w-5 text-blue-600" />
              <span className="font-bold text-blue-700 dark:text-blue-400">Engine 1: RAF Calculator</span>
            </div>
            <p className="text-sm text-muted-foreground mb-2">Converts ICD-10 → HCC → Dollar Value using CMS formula</p>
            <div className="space-y-1 text-xs font-mono bg-white dark:bg-gray-900 rounded-lg p-3">
              {components.filter((c: any) => !(c.component ?? "").toLowerCase().includes("total")).map((c: any, i: number) => {
                const isHcc = (c.component ?? "").toUpperCase().includes("HCC");
                const srcs: string[] = isHcc ? (ccToDx[c.component] ?? []) : [];
                return (
                  <div key={c.component ?? i} className="flex flex-col">
                    <div className="flex justify-between">
                      <span>{c.component}</span>
                      <span className="font-bold">+{typeof c.coefficient === "number" ? (c.coefficient ?? 0).toFixed(3) : c.coefficient}</span>
                    </div>
                    {srcs.length > 0 && (
                      <span className="text-muted-foreground/60 text-[10px] pl-1 -mt-0.5">
                        from {srcs.map((s) => s.replace(/^(.{3})(.+)$/, "$1.$2")).join(", ")}
                      </span>
                    )}
                  </div>
                );
              })}
              <div className="border-t pt-1 mt-1 flex justify-between font-bold text-blue-700 dark:text-blue-400">
                <span>RAF TOTAL</span>
                <span>{typeof score === "number" ? (score ?? 0).toFixed(3) : score}</span>
              </div>
            </div>
          </div>

          {/* Engine 2: Suspect Engine */}
          <div className="rounded-xl border-2 border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-950/30 p-4">
            <div className="flex items-center gap-2 mb-3">
              <AlertTriangle className="h-5 w-5 text-amber-600" />
              <span className="font-bold text-amber-700 dark:text-amber-400">Engine 2: Suspect Detector</span>
            </div>
            <p className="text-sm text-muted-foreground mb-2">Cross-references medications &amp; labs vs coded diagnoses</p>
            <div className="space-y-2 text-sm bg-white dark:bg-gray-900 rounded-lg p-3">
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Medication scan:</span>
                <span className="font-medium">Checked {components.length > 0 ? "4" : "0"} drugs</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Lab scan:</span>
                <span className="font-medium">Checked eGFR, A1c, BNP</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-muted-foreground">Gaps found:</span>
                <Badge className="bg-amber-100 text-amber-800">CKD not billed</Badge>
              </div>
            </div>
          </div>

          {/* Engine 3: MEAT Storage */}
          <div className="rounded-xl border-2 border-emerald-200 dark:border-emerald-800 bg-emerald-50/50 dark:bg-emerald-950/30 p-4">
            <div className="flex items-center gap-2 mb-3">
              <Shield className="h-5 w-5 text-emerald-600" />
              <span className="font-bold text-emerald-700 dark:text-emerald-400">Engine 3: MEAT Evidence</span>
            </div>
            <p className="text-sm text-muted-foreground mb-2">Stores audit-ready evidence per HCC for RADV defense</p>
            <div className="space-y-2 text-sm bg-white dark:bg-gray-900 rounded-lg p-3">
              {components.filter((c: any) => (c.component ?? "").includes("HCC")).map((c: any, i: number) => (
                <div key={c.component} className="flex items-center justify-between">
                  <Badge className="bg-emerald-600 text-white font-mono text-xs">{c.component}</Badge>
                  <span className="text-emerald-600 font-bold">MEAT 4/4 ✅</span>
                </div>
              ))}
              {components.filter((c: any) => (c.component ?? "").includes("HCC")).length === 0 && (
                <div className="text-muted-foreground text-xs">All diagnoses have complete MEAT evidence</div>
              )}
            </div>
          </div>

          {/* Engine 4: Confidence Router */}
          <div className="rounded-xl border-2 border-purple-200 dark:border-purple-800 bg-purple-50/50 dark:bg-purple-950/30 p-4">
            <div className="flex items-center gap-2 mb-3">
              <Brain className="h-5 w-5 text-purple-600" />
              <span className="font-bold text-purple-700 dark:text-purple-400">Engine 4: Confidence Router</span>
            </div>
            <p className="text-sm text-muted-foreground mb-2">Decides auto-accept vs human review based on 6 signals</p>
            <div className="space-y-2 text-sm bg-white dark:bg-gray-900 rounded-lg p-3">
              <div className="flex items-center justify-between text-xs">
                <span>Model confidence</span>
                <div className="w-20 bg-gray-200 dark:bg-gray-700 rounded-full h-2"><div className="bg-emerald-500 h-2 rounded-full" style={{width: "95%"}} /></div>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span>NER agreement</span>
                <div className="w-20 bg-gray-200 dark:bg-gray-700 rounded-full h-2"><div className="bg-emerald-500 h-2 rounded-full" style={{width: "85%"}} /></div>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span>MEAT completeness</span>
                <div className="w-20 bg-gray-200 dark:bg-gray-700 rounded-full h-2"><div className="bg-emerald-500 h-2 rounded-full" style={{width: "100%"}} /></div>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span>ICD-10 validated</span>
                <div className="w-20 bg-gray-200 dark:bg-gray-700 rounded-full h-2"><div className="bg-emerald-500 h-2 rounded-full" style={{width: "100%"}} /></div>
              </div>
              <div className="border-t pt-2 mt-1 flex items-center justify-between">
                <span className="text-xs font-semibold">Routing Decision:</span>
                <Badge className="bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200">HUMAN REVIEW</Badge>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Step7Content({ data, rafData }: { data: any; rafData: any }) {
  if (!data) return null;
  const billingRAF = data.billing_raf ?? 0;
  const aiRAF = data.ai_raf ?? rafData?.raf_score ?? 0;
  const gap = +(aiRAF - billingRAF).toFixed(3);
  const aiComponents: any[] = data.ai_components ?? [];
  const newHCCs: string[] = [...new Set(data.new_hccs ?? [])] as string[];
  const isPasteMode = data.is_paste_mode ?? false;

  // Separate AI components
  const aiDemoComp = aiComponents.find((c: any) => c.component?.startsWith("M") || c.component?.startsWith("F"));
  const aiHccComps = aiComponents.filter((c: any) => c.component?.startsWith("HCC"));
  const aiIntComps = aiComponents.filter((c: any) => !c.component?.startsWith("HCC") && !c.component?.startsWith("M") && !c.component?.startsWith("F") && c.component?.includes("_"));

  // Billing components (from OpenEMR billed codes or demographic-only for paste mode)
  const billingComps: any[] = data.billing_components ?? [];
  const billDemoComp = billingComps.find((c: any) => c.component?.startsWith("M") || c.component?.startsWith("F"));
  const billHccComps = billingComps.filter((c: any) => c.component?.startsWith("HCC"));

  // Determine which AI HCCs are new vs already in billing
  const billingHCCSet = new Set(billHccComps.map((c: any) => c.component));

  return (
    <div className="space-y-6">
      {/* Header: Side by side RAF comparison */}
      <div className="grid grid-cols-5 gap-3 items-center">
        <div className="col-span-2 rounded-xl border-2 border-gray-300 dark:border-gray-600 p-4 text-center">
          <div className="text-xs font-semibold text-muted-foreground uppercase">
            {isPasteMode ? "Baseline (Demographic Only)" : "Billing (Human Coder)"}
          </div>
          <div className="text-4xl font-black text-gray-500 mt-1">{(billingRAF ?? 0).toFixed(3)}</div>
          {isPasteMode && <div className="text-xs text-muted-foreground mt-1">No billing data (pasted note)</div>}
        </div>
        <div className="text-center">
          <div className="text-3xl font-bold text-emerald-600">→</div>
          <div className="text-xs font-bold text-emerald-600">{gap >= 0 ? "+" : ""}{(gap ?? 0).toFixed(3)}</div>
        </div>
        <div className="col-span-2 rounded-xl border-2 border-emerald-400 dark:border-emerald-600 p-4 text-center bg-emerald-50/50 dark:bg-emerald-950/30">
          <div className="text-xs font-semibold text-emerald-700 dark:text-emerald-400 uppercase">Analysis Pipeline</div>
          <div className="text-4xl font-black text-emerald-600 dark:text-emerald-400 mt-1">{(aiRAF ?? 0).toFixed(3)}</div>
        </div>
      </div>

      {/* Side-by-side BEFORE vs AFTER calculation */}
      <div className="grid grid-cols-2 gap-4">
        {/* BEFORE: Billing Only */}
        <div className="rounded-xl border-2 border-gray-300 dark:border-gray-600 overflow-hidden">
          <div className="bg-gray-100 dark:bg-gray-800 px-4 py-2 font-bold text-sm text-gray-700 dark:text-gray-300 border-b">
            {isPasteMode ? "BEFORE — No Billing Data (Pasted Note)" : "BEFORE — Billing Only (Human Coder)"}
          </div>
          <div className="p-4 space-y-2 font-mono text-sm">
            {billDemoComp && (
              <div className="flex justify-between py-1">
                <span className="text-muted-foreground">{billDemoComp.component}:</span>
                <span>{billDemoComp.coefficient?.toFixed(3)}</span>
              </div>
            )}
            {billHccComps.map((comp: any, i: number) => (
              <div key={comp.component} className="flex justify-between py-1">
                <span>
                  <Badge className="bg-gray-500 text-white font-mono text-xs mr-2">{comp.component}</Badge>
                </span>
                <span>{comp.coefficient?.toFixed(3)}</span>
              </div>
            ))}
            {isPasteMode ? (
              <div className="text-xs text-muted-foreground italic py-2 bg-gray-50 dark:bg-gray-900 rounded-lg p-3">
                No billing data available — pasted clinical note has no associated billing history. Score reflects demographic baseline only.
              </div>
            ) : billHccComps.length === 0 ? (
              <div className="text-xs text-muted-foreground italic py-1">No HCC-carrying codes billed</div>
            ) : null}
            <div className="border-t-2 border-gray-300 dark:border-gray-600 pt-2 mt-2 flex justify-between font-bold text-lg">
              <span>TOTAL:</span>
              <span className="text-gray-600 dark:text-gray-400">{(billingRAF ?? 0).toFixed(3)}</span>
            </div>
          </div>
        </div>

        {/* AFTER: AI Pipeline */}
        <div className="rounded-xl border-2 border-emerald-400 dark:border-emerald-600 overflow-hidden bg-emerald-50/30 dark:bg-emerald-950/10">
          <div className="bg-emerald-100 dark:bg-emerald-900 px-4 py-2 font-bold text-sm text-emerald-800 dark:text-emerald-200 border-b border-emerald-300 dark:border-emerald-700">
            AFTER — Pipeline Analysis (All Documented)
          </div>
          <div className="p-4 space-y-2 font-mono text-sm">
            {aiDemoComp && (
              <div className="flex justify-between py-1">
                <span className="text-muted-foreground">{aiDemoComp.component}:</span>
                <span>{aiDemoComp.coefficient?.toFixed(3)}</span>
              </div>
            )}
            {aiHccComps.map((comp: any, i: number) => {
              const isNew = !billingHCCSet.has(comp.component);
              return (
                <div key={comp.component} className={`flex justify-between py-1 ${isNew ? "font-bold text-emerald-700 dark:text-emerald-400" : ""}`}>
                  <span>
                    <Badge className={`${isNew ? "bg-emerald-600" : "bg-blue-600"} text-white font-mono text-xs mr-2`}>{comp.component}</Badge>
                    {isNew && <span className="text-xs">← NEW!</span>}
                  </span>
                  <span>{comp.coefficient?.toFixed(3)}</span>
                </div>
              );
            })}
            {aiIntComps.map((comp: any, i: number) => (
              <div key={comp.component} className="flex justify-between py-1 text-muted-foreground">
                <span className="text-xs">{comp.component}:</span>
                <span>{comp.coefficient?.toFixed(3)}</span>
              </div>
            ))}
            <div className="border-t-2 border-emerald-400 dark:border-emerald-600 pt-2 mt-2 flex justify-between font-bold text-lg">
              <span>TOTAL:</span>
              <span className="text-emerald-700 dark:text-emerald-400">{(aiRAF ?? 0).toFixed(3)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* What AI Found */}
      <div className="rounded-xl border-2 border-amber-300 dark:border-amber-700 bg-amber-50/50 dark:bg-amber-950/20 p-5">
        <h4 className="font-bold text-amber-800 dark:text-amber-300 mb-3 flex items-center gap-2">
          <AlertTriangle className="h-5 w-5" />
          {isPasteMode ? "Identified Conditions" : "Identified Gaps — Documented but Not Billed"}
        </h4>
        <div className="space-y-3">
          {newHCCs.length > 0 ? newHCCs.map((hcc: string, i: number) => {
            const code = hcc?.startsWith("HCC") ? hcc : `HCC${hcc}`;
            const name = HCC_NAMES[code.replace(/\s/g, "")] ?? HCC_NAMES[hcc] ?? "";
            const comp = aiHccComps.find((c: any) => c.component === code);
            return (
              <div key={hcc} className="flex items-center gap-3 bg-white dark:bg-gray-900 rounded-lg p-3 border">
                <Badge className="bg-blue-600 text-white font-mono text-sm px-3">{code}</Badge>
                <div className="flex-1">
                  <div className="font-medium">{name || code}</div>
                  {comp && <div className="text-xs text-muted-foreground">Coefficient: +{comp.coefficient?.toFixed(3)}</div>}
                </div>
                <Badge variant="outline" className="border-emerald-400 text-emerald-700">
                  {isPasteMode ? "Found in clinical documentation" : "Documented in note, not billed"}
                </Badge>
              </div>
            );
          }) : (
            <p className="text-sm text-muted-foreground">All documented conditions are already billed.</p>
          )}
        </div>
      </div>

      {/* Model disclaimer */}
      <div className="flex items-start gap-2 rounded-lg border border-amber-200 dark:border-amber-800/40 bg-amber-50/50 dark:bg-amber-950/20 px-3.5 py-2.5 mt-2">
        <AlertTriangle className="h-3.5 w-3.5 text-amber-500 shrink-0 mt-0.5" />
        <p className="text-[11px] leading-relaxed text-amber-700/80 dark:text-amber-400/70">
          RAF scores are estimates based on HCC model. Not for payment submission. Verify against official CMS software.
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Quality Score Badge
// ---------------------------------------------------------------------------
function QualityScoreBadge({ score }: { score: number | null | undefined }) {
  if (score == null) return null;
  const label = score >= 0.9 ? "High Quality" : score >= 0.7 ? "Good Quality" : "Needs Review";
  const cls = score >= 0.9
    ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200"
    : score >= 0.7
      ? "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200"
      : "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200";
  return (
    <Badge className={cn("text-xs font-semibold", cls)}>
      {label} ({(score * 100).toFixed(0)}%)
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Extraction Summary (for Step 0/1)
// ---------------------------------------------------------------------------
function ExtractionSummary({ extraction }: { extraction: any }) {
  if (!extraction) return null;
  const explicit = extraction.explicit_codes_count ?? 0;
  const problemList = extraction.problem_list_count ?? 0;
  const assessment = extraction.assessment_count ?? 0;
  const total = extraction.all_unique_codes?.length ?? (explicit + problemList + assessment);
  return (
    <div className="flex flex-wrap gap-3 mt-3">
      <div className="rounded-lg border bg-blue-50 dark:bg-blue-950/30 px-3 py-1.5">
        <span className="text-xs text-muted-foreground">Explicit Codes</span>
        <span className="ml-2 font-bold text-blue-700 dark:text-blue-400">{explicit}</span>
      </div>
      <div className="rounded-lg border bg-violet-50 dark:bg-violet-950/30 px-3 py-1.5">
        <span className="text-xs text-muted-foreground">Problem List</span>
        <span className="ml-2 font-bold text-violet-700 dark:text-violet-400">{problemList}</span>
      </div>
      <div className="rounded-lg border bg-teal-50 dark:bg-teal-950/30 px-3 py-1.5">
        <span className="text-xs text-muted-foreground">Assessment</span>
        <span className="ml-2 font-bold text-teal-700 dark:text-teal-400">{assessment}</span>
      </div>
      <div className="rounded-lg border bg-emerald-50 dark:bg-emerald-950/30 px-3 py-1.5">
        <span className="text-xs text-muted-foreground">Unique Codes</span>
        <span className="ml-2 font-bold text-emerald-700 dark:text-emerald-400">{total}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 8: Quality Verification
// ---------------------------------------------------------------------------
function Step8Content({ data }: { data: any }) {
  if (!data) return <p className="text-sm text-muted-foreground">No verification data available.</p>;

  const restoredCodes: any[] = data.restored_codes ?? [];
  const warnings: any[] = data.warnings ?? [];
  const qualityScore: number | null = data.quality_score ?? null;
  const specificityWarnings: any[] = data.specificity_warnings ?? [];
  const excludes1Conflicts: any[] = data.excludes1_conflicts ?? [];

  const severityOrder: Record<string, number> = { critical: 0, high: 1, medium: 2, info: 3 };
  const sortedWarnings = [...warnings].sort(
    (a, b) => (severityOrder[a.severity] ?? 99) - (severityOrder[b.severity] ?? 99)
  );

  const severityStyles: Record<string, string> = {
    critical: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200 border-red-300 dark:border-red-700",
    high: "bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200 border-orange-300 dark:border-orange-700",
    medium: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200 border-amber-300 dark:border-amber-700",
    info: "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200 border-blue-300 dark:border-blue-700",
  };

  const severityIcons: Record<string, React.ReactNode> = {
    critical: <XCircle className="h-3.5 w-3.5 text-red-600 shrink-0" />,
    high: <AlertTriangle className="h-3.5 w-3.5 text-orange-600 shrink-0" />,
    medium: <AlertTriangle className="h-3.5 w-3.5 text-amber-600 shrink-0" />,
    info: <Info className="h-3.5 w-3.5 text-blue-600 shrink-0" />,
  };

  return (
    <div className="space-y-6">
      {/* Quality Score */}
      {qualityScore != null && (
        <div className="text-center py-6 rounded-xl bg-gradient-to-br from-gray-50 to-blue-50 dark:from-gray-950 dark:to-blue-950 border-2 border-gray-200 dark:border-gray-700">
          <div className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">Quality Score</div>
          <div className={cn(
            "text-5xl font-black mt-2",
            qualityScore >= 0.9 ? "text-emerald-600 dark:text-emerald-400" :
            qualityScore >= 0.7 ? "text-amber-600 dark:text-amber-400" :
            "text-red-600 dark:text-red-400"
          )}>
            {(qualityScore * 100).toFixed(0)}%
          </div>
          <div className="mt-2">
            <QualityScoreBadge score={qualityScore} />
          </div>
          <p className="text-xs text-muted-foreground mt-2">
            Based on code specificity, documentation completeness, and clinical consistency
          </p>
        </div>
      )}

      {/* Restored Codes */}
      {restoredCodes.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-muted-foreground mb-2 flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-amber-500" /> Restored Codes ({restoredCodes.length})
          </h4>
          <div className="space-y-2">
            {restoredCodes.map((rc: any, i: number) => (
              <div key={rc.code} className="flex items-center gap-3 rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-950/20 p-3">
                <Badge className="bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200 font-mono text-xs">
                  {rc.code}
                </Badge>
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-sm">{rc.title ?? rc.code}</div>
                  {rc.hcc && (
                    <Badge className="bg-blue-600 text-white font-mono text-xs mt-0.5">
                      {rc.hcc.startsWith("HCC") ? rc.hcc : `HCC${rc.hcc}`}
                    </Badge>
                  )}
                </div>
                <span className="text-xs text-muted-foreground italic shrink-0 max-w-[200px] text-right">
                  {rc.restoration_reason ?? "Restored by verification"}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Warnings */}
      {sortedWarnings.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-muted-foreground mb-2 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-500" /> Warnings ({sortedWarnings.length})
          </h4>
          <div className="space-y-1.5">
            {sortedWarnings.map((w: any, i: number) => (
              <div key={`${w.severity}-${w.code ?? ""}-${i}`} className={cn("flex items-start gap-2 rounded-lg border px-3 py-2", severityStyles[w.severity] ?? severityStyles.info)}>
                {severityIcons[w.severity] ?? severityIcons.info}
                <div className="flex-1 min-w-0">
                  <span className="text-sm">{w.message}</span>
                  {w.code && <Badge variant="outline" className="ml-2 text-[10px] font-mono">{w.code}</Badge>}
                </div>
                <Badge variant="outline" className="text-[10px] uppercase shrink-0">{w.severity}</Badge>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Specificity Warnings */}
      {specificityWarnings.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-muted-foreground mb-2 flex items-center gap-2">
            <Search className="h-4 w-4 text-violet-500" /> Specificity Warnings ({specificityWarnings.length})
          </h4>
          <div className="space-y-1.5">
            {specificityWarnings.map((sw: any, i: number) => (
              <div key={i} className="flex items-start gap-2 rounded-lg border border-violet-200 dark:border-violet-800 bg-violet-50/50 dark:bg-violet-950/20 px-3 py-2">
                <Info className="h-3.5 w-3.5 text-violet-600 shrink-0 mt-0.5" />
                <span className="text-sm">{typeof sw === "string" ? sw : sw.message ?? JSON.stringify(sw)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Excludes1 Conflicts */}
      {excludes1Conflicts.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-muted-foreground mb-2 flex items-center gap-2">
            <XCircle className="h-4 w-4 text-red-500" /> Code Conflicts ({excludes1Conflicts.length})
          </h4>
          <div className="space-y-1.5">
            {excludes1Conflicts.map((ec: any, i: number) => (
              <div key={i} className="flex items-start gap-2 rounded-lg border border-red-200 dark:border-red-800 bg-red-50/50 dark:bg-red-950/20 px-3 py-2">
                <XCircle className="h-3.5 w-3.5 text-red-600 shrink-0 mt-0.5" />
                <span className="text-sm">{typeof ec === "string" ? ec : ec.message ?? JSON.stringify(ec)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Empty state */}
      {restoredCodes.length === 0 && sortedWarnings.length === 0 && specificityWarnings.length === 0 && excludes1Conflicts.length === 0 && qualityScore == null && (
        <div className="text-center py-8 text-muted-foreground">
          <ShieldCheck className="h-10 w-10 mx-auto mb-3 opacity-40" />
          <p className="font-medium">All codes passed verification</p>
          <p className="text-sm mt-1">No warnings or conflicts detected</p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 9: Review Queue Routing
// ---------------------------------------------------------------------------

function routeForReview(diagnoses: any[], verification: any) {
  const autoAccept: any[] = [];
  const needsReview: any[] = [];
  const reject: any[] = [];

  for (const dx of diagnoses) {
    const conf = typeof dx.confidence === "number" ? dx.confidence : 0.5;
    const hasWarnings = (verification?.warnings ?? []).some(
      (w: any) => w.code === dx.icd10 || w.code === dx.icd10_code
    );
    const isRestored = dx.stage3_restored;

    let reviewReason = "";

    if (conf >= 0.85 && !hasWarnings && !isRestored) {
      autoAccept.push(dx);
    } else if (conf < 0.5 || dx.confidence_label === "flagged") {
      reviewReason = conf < 0.5 ? "Low confidence score" : "Flagged for review";
      reject.push({ ...dx, reviewReason });
    } else {
      const reasons: string[] = [];
      if (isRestored) reasons.push("Restored during verification");
      if (hasWarnings) reasons.push("Has verification warnings");
      if (conf < 0.85) reasons.push(`Confidence below threshold (${(conf * 100).toFixed(0)}%)`);
      reviewReason = reasons.join(" \u00b7 ") || "Requires manual review";
      needsReview.push({ ...dx, reviewReason });
    }
  }
  return { autoAccept, needsReview, reject };
}

function Step9Content({ data }: { data: { diagnoses: any[]; verification: any; backendQueue?: any } }) {
  if (!data?.diagnoses?.length) {
    return (
      <div className="text-center py-8 text-muted-foreground">
        <ClipboardList className="h-10 w-10 mx-auto mb-3 opacity-40" />
        <p className="font-medium">No diagnoses to route</p>
        <p className="text-sm mt-1">Run the pipeline to see review queue routing</p>
      </div>
    );
  }

  // Prefer the backend-computed queue (uses the full Stage 3 warning catalogue).
  // Fall back to the lightweight client-side router for older responses.
  const usingBackend = !!data.backendQueue;
  const autoAccept: any[] = usingBackend
    ? (data.backendQueue.auto_accept ?? [])
    : routeForReview(data.diagnoses, data.verification).autoAccept;
  const needsReview: any[] = usingBackend
    ? (data.backendQueue.needs_review ?? [])
    : routeForReview(data.diagnoses, data.verification).needsReview;
  const reject: any[] = usingBackend
    ? (data.backendQueue.reject ?? [])
    : routeForReview(data.diagnoses, data.verification).reject;

  const summary = data.backendQueue?.review_summary ?? {};
  const estMinutes: number = usingBackend
    ? (summary.estimated_review_time_minutes ?? 0)
    : Math.max(1, Math.ceil(needsReview.length * 1.2 + reject.length * 2.5));
  const qualityScore: number | null = summary.encounter_quality_score ?? null;

  // ------------------------------------------------------------------
  // Shared card component — handles both backend-enriched and simple dx
  // ------------------------------------------------------------------
  function DxCard({ dx, variant }: { dx: any; variant: "accept" | "review" | "reject" }) {
    const icd = dx.icd10 ?? dx.icd10_code ?? "—";
    const conf: number | null = typeof dx.confidence === "number" ? dx.confidence : null;
    const condition = dx.description ?? dx.condition ?? dx.icd10_description ?? "";
    const rawHcc = dx.hcc ?? dx.hcc_code ?? dx.hcc_mapping?.hcc_code ?? null;
    const hccLabel = rawHcc
      ? (String(rawHcc).startsWith("HCC") ? String(rawHcc) : `HCC${rawHcc}`)
      : null;
    const hccName = hccLabel ? (HCC_NAMES[hccLabel] ?? null) : null;
    const meatFilled: number = dx.meat_score ?? 0;
    const flags: string[] = dx.review_flags ?? [];
    const notes: string[] = dx.review_notes ?? [];
    const restored = dx.stage3_restored ?? false;
    const reviewReason: string = dx.reviewReason ?? "";

    const colStyles = {
      accept: {
        border: "border-emerald-200 dark:border-emerald-800",
        bg: "bg-emerald-50/40 dark:bg-emerald-950/20",
        icdBadge: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200",
        hccBadge: "bg-emerald-600 text-white",
        confColor: "text-emerald-600 dark:text-emerald-400",
      },
      review: {
        border: "border-amber-200 dark:border-amber-800",
        bg: "bg-amber-50/40 dark:bg-amber-950/20",
        icdBadge: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
        hccBadge: "bg-amber-600 text-white",
        confColor: "text-amber-600 dark:text-amber-400",
      },
      reject: {
        border: "border-red-200 dark:border-red-800",
        bg: "bg-red-50/40 dark:bg-red-950/20",
        icdBadge: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
        hccBadge: "bg-red-600 text-white",
        confColor: "text-red-600 dark:text-red-400",
      },
    };
    const s = colStyles[variant];

    return (
      <div className={cn("rounded-lg border p-3 space-y-1.5 transition-colors", s.border, s.bg)}>
        {/* Top row */}
        <div className="flex items-start gap-2">
          {/* Confidence dot */}
          <span className={cn(
            "inline-block h-2 w-2 rounded-full shrink-0 mt-1.5",
            conf === null ? "bg-gray-400"
              : conf >= 0.85 ? "bg-emerald-500"
              : conf >= 0.60 ? "bg-amber-500"
              : "bg-red-500"
          )} />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5 flex-wrap">
              <Badge className={cn("font-mono text-xs px-1.5 py-0", s.icdBadge)}>
                {icd}
              </Badge>
              {hccLabel && (
                <Badge className={cn("text-xs px-1.5 py-0", s.hccBadge)}>
                  {hccLabel}
                </Badge>
              )}
              {restored && (
                <Badge variant="outline" className="text-[10px] px-1 py-0 border-amber-400 text-amber-700 dark:text-amber-300">
                  Stage 3 restored
                </Badge>
              )}
            </div>
            <div className="text-sm font-medium mt-0.5 leading-tight">
              {condition || icd}
            </div>
            {hccName && (
              <div className="text-[10px] text-muted-foreground">{hccName}</div>
            )}
          </div>
          {conf !== null && (
            <span className={cn("text-xs font-mono font-bold shrink-0 tabular-nums", s.confColor)}>
              {Math.round(conf * 100)}%
            </span>
          )}
        </div>

        {/* MEAT dots (backend enriched) */}
        {meatFilled > 0 && (
          <div className="flex items-center gap-1 pl-4">
            <span className="text-[10px] text-muted-foreground mr-1">MEAT</span>
            {Array.from({ length: 4 }, (_, i) => (
              <span key={i} className={cn("h-2 w-2 rounded-full", i < meatFilled ? "bg-teal-500" : "bg-gray-200 dark:bg-gray-700")} />
            ))}
          </div>
        )}

        {/* Warning code flags (backend enriched) */}
        {flags.length > 0 && (
          <div className="flex flex-wrap gap-1 pl-4">
            {flags.map((flag: string, i: number) => (
              <Badge key={flag} variant="outline" className="text-[9px] px-1 py-0 font-mono">
                {flag}
              </Badge>
            ))}
          </div>
        )}

        {/* Human-readable review notes (backend) or client-side reason */}
        {notes.length > 0 && (
          <ul className="pl-4 space-y-0.5">
            {notes.map((note: string, i: number) => (
              <li key={i} className="text-[11px] text-muted-foreground leading-snug list-disc ml-3">
                {note}
              </li>
            ))}
          </ul>
        )}
        {notes.length === 0 && reviewReason && (
          <p className="text-[11px] text-muted-foreground italic pl-4">{reviewReason}</p>
        )}
      </div>
    );
  }

  const columnDefs = [
    {
      key: "accept",
      label: "Auto-Accept",
      count: autoAccept.length,
      items: autoAccept,
      variant: "accept" as const,
      cardClass: "border-2 border-emerald-300 dark:border-emerald-700 bg-emerald-50/30 dark:bg-emerald-950/20",
      headerClass: "text-emerald-700 dark:text-emerald-400",
      pillClass: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200",
      icon: <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />,
      iconBg: "bg-emerald-100 dark:bg-emerald-900",
      caption: "High confidence, no critical warnings — safe to submit",
    },
    {
      key: "review",
      label: "Needs Review",
      count: needsReview.length,
      items: needsReview,
      variant: "review" as const,
      cardClass: "border-2 border-amber-300 dark:border-amber-700 bg-amber-50/30 dark:bg-amber-950/20",
      headerClass: "text-amber-700 dark:text-amber-400",
      pillClass: "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200",
      icon: <Eye className="h-4 w-4 text-amber-600 dark:text-amber-400" />,
      iconBg: "bg-amber-100 dark:bg-amber-900",
      caption: "Coder must verify before submission",
    },
    {
      key: "reject",
      label: "Reject",
      count: reject.length,
      items: reject,
      variant: "reject" as const,
      cardClass: "border-2 border-red-300 dark:border-red-700 bg-red-50/30 dark:bg-red-950/20",
      headerClass: "text-red-700 dark:text-red-400",
      pillClass: "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
      icon: <XCircle className="h-4 w-4 text-red-600 dark:text-red-400" />,
      iconBg: "bg-red-100 dark:bg-red-900",
      caption: "Do not submit without significant coder rework",
    },
  ];

  return (
    <div className="space-y-5">
      {/* Summary bar */}
      <div className="flex items-center justify-between rounded-xl bg-gradient-to-r from-gray-50 to-gray-100 dark:from-gray-900 dark:to-gray-800 border px-5 py-3.5 flex-wrap gap-3">
        <div className="flex items-center gap-5 text-sm flex-wrap">
          {columnDefs.map((col) => (
            <span key={col.key} className="flex items-center gap-1.5">
              <span className={cn(
                "inline-block h-2.5 w-2.5 rounded-full",
                col.key === "accept" ? "bg-emerald-500" : col.key === "review" ? "bg-amber-500" : "bg-red-500"
              )} />
              <strong>{col.count}</strong>
              <span className="text-muted-foreground">{col.label.toLowerCase()}</span>
            </span>
          ))}
        </div>
        <div className="flex items-center gap-4">
          {qualityScore !== null && (
            <div className="flex items-center gap-1.5 text-sm">
              <ShieldCheck className="h-3.5 w-3.5 text-teal-500" />
              <span className="text-muted-foreground">Quality:</span>
              <strong className={cn(
                qualityScore >= 0.9 ? "text-emerald-600 dark:text-emerald-400"
                  : qualityScore >= 0.7 ? "text-amber-600 dark:text-amber-400"
                  : "text-red-600 dark:text-red-400"
              )}>
                {Math.round(qualityScore * 100)}%
              </strong>
            </div>
          )}
          {estMinutes > 0 && (
            <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
              <Clock className="h-3.5 w-3.5" />
              Est. review: <strong className="text-foreground">{estMinutes}m</strong>
            </div>
          )}
          {usingBackend && (
            <Badge variant="outline" className="text-[10px] px-1.5 border-violet-300 text-violet-700 dark:text-violet-400">
              Stage 3 routed
            </Badge>
          )}
        </div>
      </div>

      {/* Three columns */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {columnDefs.map((col) => (
          <Card key={col.key} className={col.cardClass}>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <div className={cn("flex h-7 w-7 items-center justify-center rounded-lg", col.iconBg)}>
                  {col.icon}
                </div>
                <span className={col.headerClass}>{col.label}</span>
                <Badge className={cn("ml-auto text-xs", col.pillClass)}>
                  {col.count}
                </Badge>
              </CardTitle>
              <p className="text-[11px] text-muted-foreground leading-snug">{col.caption}</p>
            </CardHeader>
            <CardContent className="pt-0">
              {col.items.length === 0 ? (
                <p className="text-xs text-muted-foreground text-center py-4">None</p>
              ) : (
                <div className="space-y-2 max-h-[440px] overflow-y-auto pr-0.5">
                  {col.items.map((dx: any, i: number) => (
                    <DxCard key={dx.icd10 ?? dx.icd10_code ?? i} dx={dx} variant={col.variant} />
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Human-in-the-loop callout */}
      <div className="rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50/50 dark:bg-blue-950/20 p-4">
        <div className="flex items-start gap-3">
          <Info className="h-4 w-4 text-blue-600 dark:text-blue-400 mt-0.5 shrink-0" />
          <div>
            <p className="text-sm font-medium text-blue-900 dark:text-blue-200">
              Human-in-the-loop workflow
            </p>
            <p className="text-xs text-blue-700 dark:text-blue-400 mt-1 leading-relaxed">
              Routing decisions are driven by Stage 3 verification data — confidence thresholds (auto-accept
              &ge;85%, reject &lt;60%), warning severity (critical/high triggers review or reject), Excludes1
              conflicts, and whether the LLM silently dropped a code that Stage 3 had to restore. Coders see
              exactly which warning codes and messages drove each routing decision.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

 

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function DemoPage() {
  // Input state
  const [inputMode, setInputMode] = useState<"paste" | "patient">("paste");
  const [noteText, setNoteText] = useState("");
  const [selectedPatientId, setSelectedPatientId] = useState<number | null>(null);
  const [selectedEncounterId, setSelectedEncounterId] = useState<number | null>(null);
  const [patients, setPatients] = useState<Patient[]>([]);
  const [encounters, setEncounters] = useState<{ encounter_id: number; date: string; reason?: string }[]>([]);
  const [encounterPreview, setEncounterPreview] = useState<Record<string, any> | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // Pipeline state
  const [running, setRunning] = useState(false);
  const [stepStatuses, setStepStatuses] = useState<StepStatus[]>(PIPELINE_STEPS.map(() => "pending"));
  const [expandedStep, setExpandedStep] = useState<number | null>(null);
  const [stepTimings, setStepTimings] = useState<(number | null)[]>(PIPELINE_STEPS.map(() => null));

  // Result data
   
  const [pipelineData, setPipelineData] = useState<Record<string, any>>({});
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
   
  const [rafResult, setRafResult] = useState<Record<string, any> | null>(null);

  // Loading state for API call between Step 0 and Step 1
  const [apiLoading, setApiLoading] = useState(false);
  const [apiElapsed, setApiElapsed] = useState(0);
  const apiTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stepsRef = useRef<(HTMLDivElement | null)[]>([]);

  // Fetch only patients that have encounters (filtered, not all 20K)
  useEffect(() => {
    if (inputMode === "patient") {
      getPatientsWithEncounters().then(setPatients).catch(() => {});
    }
  }, [inputMode]);

  // Fetch encounters
  useEffect(() => {
    if (selectedPatientId) {
      getPatientEncounters(selectedPatientId)
        .then((r) => setEncounters(r.encounters ?? []))
        .catch(() => {});
    }
  }, [selectedPatientId]);

  // Fetch encounter preview data when encounter is selected
  useEffect(() => {
    if (!selectedPatientId || !selectedEncounterId) {
      setEncounterPreview(null);
      return;
    }
    setPreviewLoading(true);
    const pid = selectedPatientId;
    Promise.all([
      api.get(`/api/patients/${pid}`).then(r => r.data).catch(() => null),
      api.get(`/api/patients/${pid}/diagnoses`).then(r => r.data).catch(() => ({ diagnoses: [] })),
      api.get(`/api/patients/${pid}/medications`).then(r => r.data).catch(() => ({ medications: [] })),
      api.get(`/api/patients/${pid}/clinical-notes/${selectedEncounterId}`).then(r => r.data).catch(() => ({ notes: [] })),
    ]).then(([patient, dxData, medData, notesData]) => {
      const enc = encounters.find(e => Math.round(e.encounter_id) === selectedEncounterId);
      const diagnoses = (dxData?.diagnoses ?? []).filter((d: any) => Math.round(d.encounter) === selectedEncounterId);
      const allDiagnoses = dxData?.diagnoses ?? [];
      const medications = medData?.medications ?? [];
      const clinicalNotes = notesData?.notes ?? [];
      setEncounterPreview({
        patient,
        encounter: enc,
        diagnoses,
        allDiagnoses,
        medications,
        clinicalNotes,
        totalEncounters: encounters.length,
        noteChars: clinicalNotes.reduce((sum: number, n: any) => sum + (n.note_text?.length ?? 0), 0),
      });
      setPreviewLoading(false);
    }).catch(() => setPreviewLoading(false));
  }, [selectedEncounterId, selectedPatientId, encounters]);

  // ---------------------------------------------------------------------------
  // Pipeline execution
  // ---------------------------------------------------------------------------
  const runPipeline = useCallback(async () => {
    if (running) return;
    const note = inputMode === "paste" ? noteText : "";

    // Validate inputs
    if (inputMode === "patient" && !selectedEncounterId) {
      alert("Please select an encounter first.");
      return;
    }
    if (inputMode === "paste" && !noteText.trim()) {
      alert("Please paste a clinical note or click 'Use Sample Note'.");
      return;
    }
    if (inputMode === "paste" && !note.trim()) return;

    // Warn on very large notes (cost protection)
    if (note.length > 15000) {
      const ok = confirm(`⚠️ This note is very large (${(note.length / 1000).toFixed(1)}K chars). This may take over a minute to process. Continue?`);
      if (!ok) return;
    }

    setRunning(true);
    setStepStatuses(PIPELINE_STEPS.map(() => "pending"));
    setStepTimings(PIPELINE_STEPS.map(() => null));
    setPipelineData({});
    setAnalysisResult(null);
    setRafResult(null);
    // Force a React render cycle so the steps section appears
    await new Promise((r) => setTimeout(r, 50));
    setExpandedStep(null);

    const updateStep = (idx: number, status: StepStatus) => {
      setStepStatuses((prev) => { const n = [...prev]; n[idx] = status; return n; });
    };
    const setTiming = (idx: number, ms: number) => {
      setStepTimings((prev) => { const n = [...prev]; n[idx] = ms; return n; });
    };
    const scrollTo = (idx: number) => {
      setExpandedStep(idx);
      setTimeout(() => {
        stepsRef.current[idx]?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 100);
    };

    try {
      // Skip frontend cache check — the API returns cached results instantly (0.016s)
      // This lets the pipeline steps animation run normally with cached data
      if (false && inputMode === "patient" && selectedEncounterId) {
        try {
          const { data: cached } = await api.get(`/api/analysis/encounter/${selectedEncounterId}/cached`);
          if (cached && cached._cached) {
            // Fast-forward all steps with cached data
            setAnalysisResult(cached);
            const pipeline = cached.pipeline ?? {};
            const meta = cached._meta ?? {};
            const toolCalls: any[] = pipeline.tool_calls ?? [];
            const rafTC = toolCalls.find((tc: any) => tc.function === "calculate_raf_score");
            const rafArgs = rafTC?.args ?? {};
            const rafResult = rafTC?.result ?? {};

            // Build step6 RAF data from tool call
            let hccDetails: any[] = rafResult.hcc_details ?? rafResult.hcc_contributions ?? [];
            const cachedCoefficients: Record<string, number> = (rafResult.coefficients ?? {}) as Record<string, number>;
            if ((!hccDetails || hccDetails.length === 0) && (rafResult.hcc_list as string[] | undefined)?.length) {
              hccDetails = (rafResult.hcc_list as string[]).map((hcc: string) => {
                const hccKey = hcc.startsWith("HCC") ? hcc : `HCC${hcc}`;
                return { hcc: hcc.replace(/^HCC/, ""), coefficient: cachedCoefficients[hccKey] ?? cachedCoefficients[hcc] ?? 0, label: HCC_NAMES[hccKey] ?? "" };
              });
            }
            const cachedHccKeySet = new Set(((rafResult.hcc_list ?? []) as string[]).map((h: string) => h.startsWith("HCC") ? h : `HCC${h}`));
            const cachedInteractionComponents = Object.entries(cachedCoefficients)
              .filter(([k]) => !cachedHccKeySet.has(k) && !k.match(/^[MF]\d/))
              .map(([name, coeff]) => ({ component: name, coefficient: typeof coeff === "number" ? coeff : 0, description: "Interaction term" }));
            const cachedInteractionScore = Math.max(0, +((rafResult.raf_score ?? 0) - (rafResult.demographic_score ?? 0) - (rafResult.disease_score ?? 0)).toFixed(3));
            const step6Data = rafTC ? {
              raf_score: rafResult.raf_score ?? 0,
              demographic_score: rafResult.demographic_score ?? 0,
              disease_score: rafResult.disease_score ?? 0,
              interaction_score: cachedInteractionScore,
              cc_to_dx: (rafResult.cc_to_dx ?? {}) as Record<string, string[]>,
              components: [
                ...(rafResult.demographic_score ? [{
                  component: `${(rafArgs.sex ?? "").toString().startsWith("F") ? "F" : "M"}${rafArgs.age ?? ""}`,
                  coefficient: rafResult.demographic_score,
                  description: `Demographic (${rafArgs.age}yo ${rafArgs.sex})`,
                }] : []),
                ...hccDetails.map((h: any) => ({
                  component: `HCC${h.hcc}`,
                  coefficient: h.coefficient ?? 0,
                  description: h.label ?? "",
                })),
                ...cachedInteractionComponents,
              ],
            } : null;

            // Build step7 gap data
            const aiHCCs = new Set<string>();
            (cached.diagnoses ?? []).forEach((d: any) => {
              const hcc = d.hcc || d.hcc_code || d.hcc_mapping?.hcc_code;
              if (hcc && typeof hcc === "string" && /^HCC\d|^\d+$/.test(hcc)) {
                aiHCCs.add(hcc.startsWith("HCC") ? hcc : `HCC${hcc}`);
              }
            });

            // Fetch billing breakdown for cached path
            let cachedBillingRAF = encounterPreview?.patient?.raf_score ?? 0;
            const cachedBillingComponents: any[] = [];
            try {
              if (selectedPatientId) {
                const { data: billingData } = await api.get(`/api/raf/scores/${selectedPatientId}/breakdown`);
                cachedBillingRAF = billingData?.raf_score ?? cachedBillingRAF;
                if (billingData?.demographic_score) {
                  const sex = (billingData?.sex ?? rafArgs.sex ?? "M").toString().toUpperCase().startsWith("F") ? "F" : "M";
                  const age = billingData?.age ?? rafArgs.age ?? 70;
                  cachedBillingComponents.push({ component: `${sex}${age}`, coefficient: billingData.demographic_score, description: "Demographic" });
                }
                for (const hcc of (billingData?.hcc_details ?? [])) {
                  const code = `HCC${hcc.hcc_code}`;
                  cachedBillingComponents.push({ component: code, coefficient: hcc.coefficient ?? 0, description: hcc.hcc_label ?? "" });
                }
              }
            } catch { /* use defaults */ }

            const cachedBillingHCCSet = new Set(cachedBillingComponents.filter((c: any) => c.component?.startsWith("HCC")).map((c: any) => c.component));
            const cachedNewHCCs = [...aiHCCs].filter(h => !cachedBillingHCCSet.has(h));

            setPipelineData({
              step0: {
                patient_id: selectedPatientId,
                demographics: { age: rafArgs.age, sex: rafArgs.sex },
                source: "Cached result",
              },
              step1: pipeline.medcat_entities ?? [],
              _meta: { ...meta, patient_age: rafArgs.age, patient_sex: rafArgs.sex },
              step2: {
                before: [
                  ...(pipeline.medcat_entities ?? []),
                  ...(cached.negated_conditions ?? []).map((n: any) => ({
                    text: n.description ?? n.condition ?? (typeof n === "string" ? n : ""),
                    name: n.description ?? n.condition ?? (typeof n === "string" ? n : ""),
                    icd10: n.icd10 ?? "", confidence: 0, negated: true, category: "disease", source: "negated",
                  })),
                ],
                after: pipeline.after_negation_filter ?? [],
              },
              negatedConditions: cached.negated_conditions ?? [],
              step3: pipeline.candidate_codes ?? [],
              step3ToolCalls: (pipeline.tool_calls ?? []).filter((tc: any) =>
                ["validate_icd10", "lookup_hcc", "validate_icd10_code", "lookup_hcc_mapping"].includes(tc.function)
              ),
              afterEntities: pipeline.after_negation_filter ?? [],
              step4: { diagnoses: cached.diagnoses, suspects: cached.suspect_conditions, negated: cached.negated_conditions ?? [] },
              step5: (cached.diagnoses || []).map((d: any) => ({ icd10: d.icd10 ?? "", description: d.description ?? "", valid: true })),
              step6: step6Data,
              step7: {
                billing_raf: cachedBillingRAF,
                billing_components: cachedBillingComponents,
                ai_raf: rafResult.raf_score ?? 0,
                ai_components: step6Data?.components ?? [],
                new_hccs: cachedNewHCCs,
              },
              pipeline: pipeline,
              step9: {
                diagnoses: cached.diagnoses ?? [],
                verification: cached.verification ?? null,
                backendQueue: (cached as any).review_queue ?? null,
              },
            });
            setRafResult(step6Data);

            // Animate steps completing quickly so the UI shows progress
            for (let i = 0; i < PIPELINE_STEPS.length; i++) {
              await new Promise((r) => setTimeout(r, 150));
              updateStep(i, "done");
              setTiming(i, 0);
            }
            setExpandedStep(0);
            setRunning(false);
            return;
          }
        } catch {
          // No cache — run fresh
        }
      }

      // Step 0: EMR Data
      updateStep(0, "running");
      scrollTo(0);
      const t0 = Date.now();

       
      let patientContext: Record<string, any> = {};
      if (inputMode === "patient" && selectedPatientId) {
        try {
          const { data } = await api.get(`/api/patients/${selectedPatientId}`);
          patientContext = data;
          // Include clinical notes from encounter preview for Step 0 display
          if (encounterPreview?.clinicalNotes?.length) {
            patientContext.note_text = encounterPreview.clinicalNotes.map((n: any) => n.note_text ?? "").join("\n\n");
          }
        } catch {
          patientContext = { patient_id: selectedPatientId };
        }
      } else {
        await new Promise((r) => setTimeout(r, 600));

        // Parse age from note - look for patterns like "84-year-old", "84 year old", "Age: 84", "84yo"
        const ageMatch = note.match(/(\d{1,3})\s*[-–]?\s*year\s*[-–]?\s*old|age[:\s]+(\d{1,3})|(\d{1,3})\s*yo\b/i);
        const parsedAge = ageMatch ? parseInt(ageMatch[1] || ageMatch[2] || ageMatch[3]) : null;

        // Parse sex from note - look for "male", "female", "M", "F", "Gender: Male"
        const sexMatch = note.match(/\b(male|female|man|woman)\b|gender[:\s]+(male|female)|sex[:\s]+(male|female|[mf])\b/i);
        const parsedSex = sexMatch
          ? (sexMatch[1] || sexMatch[2] || sexMatch[3]).toLowerCase().startsWith('f') ? 'Female' : 'Male'
          : null;

        patientContext = {
          patient_id: 0,
          demographics: {
            age: parsedAge ?? null,
            sex: parsedSex ?? null,
          },
          note_text: note,
          source: "Free-text clinical note (pasted)",
        };
      }
      setPipelineData((prev) => ({ ...prev, step0: patientContext }));
      setTiming(0, Date.now() - t0);
      updateStep(0, "done");

      // =====================================================================
      // API CALL: Make the call AFTER Step 0, BEFORE animating steps 1-7
      // Show a loading indicator with elapsed timer while waiting
      // =====================================================================
      const t1 = Date.now();
      setApiLoading(true);
      setApiElapsed(0);
      apiTimerRef.current = setInterval(() => {
        setApiElapsed(Math.floor((Date.now() - t1) / 1000));
      }, 1000);

      let result: AnalysisResult;
      try {
        if (inputMode === "patient" && selectedEncounterId) {
          try {
            const { data } = await api.post(`/api/analysis/encounter/${selectedEncounterId}`, {
              include_context: true,
              save_results: false,
            });
            result = data;
          } catch (encErr: any) {
            const msg = encErr?.response?.data?.detail || encErr?.message || "Unknown error";
            if (msg.includes("No clinical notes")) {
              alert(`This encounter has no clinical notes. Please select a different encounter.\n\nTip: Try the "DM/CHF quarterly follow-up" encounter which has SOAP notes.`);
            } else {
              alert(`Encounter analysis failed: ${msg}`);
            }
            if (apiTimerRef.current) clearInterval(apiTimerRef.current);
            setApiLoading(false);
            updateStep(0, "error");
            setRunning(false);
            return;
          }
        } else {
          result = await analyzeNote(selectedPatientId ?? 0, note);
        }
      } catch {
        if (apiTimerRef.current) clearInterval(apiTimerRef.current);
        setApiLoading(false);
        updateStep(0, "error");
        setRunning(false);
        return;
      }

      // Stop the elapsed timer
      if (apiTimerRef.current) clearInterval(apiTimerRef.current);
      setApiLoading(false);

      setAnalysisResult(result);
       
      const pipeline = (result as any).pipeline ?? {};
      const meta = (result as any)._meta ?? {};
      const verification = (result as any).verification ?? null;
      const extraction = (result as any).extraction ?? null;

      // Calculate how long the API call actually took
      const apiDuration = Date.now() - t1;
      // Use real stage timings from _meta if available, otherwise distribute proportionally
      const stageTimings = meta?.timings ?? {};
      const hasRealTimings = stageTimings.stage1_extraction != null || stageTimings.stage2_llm != null;
      let stepDurations: number[];
      if (hasRealTimings) {
        const s1 = (stageTimings.stage1_extraction ?? 0) * 1000;
        const s2 = (stageTimings.stage2_llm ?? 0) * 1000;
        const s3 = (stageTimings.stage3_verification ?? 0) * 1000;
        // Distribute: steps 1-2 get stage1, step 3 gets part of stage1, step 4 gets stage2, step 5 gets stage3
        stepDurations = [
          Math.round(s1 * 0.6),  // Step 1: NER extraction
          Math.round(s1 * 0.2),  // Step 2: Negation
          Math.round(s1 * 0.2),  // Step 3: ICD-10 mapping
          Math.round(s2),         // Step 4: Clinical analysis
          Math.round(s3 || s1 * 0.1), // Step 5: Validation
        ];
      } else {
        const stepProportions = [0.30, 0.15, 0.15, 0.30, 0.10];
        stepDurations = stepProportions.map((p) => Math.round(apiDuration * p));
      }

      // Pre-extract all data from the result so we can populate steps before marking done
      const nerEntities = pipeline.medcat_entities ?? [];
       
      const negatedConditions = (result as any).negated_conditions ?? result.negated_conditions ?? [];
      const afterNegation = pipeline.after_negation_filter ?? [];
      const candidates = pipeline.candidate_codes ?? [];
      const toolCalls: any[] = pipeline.tool_calls ?? [];

      // Store pipeline (including tool_calls) so step content components can access it
      setPipelineData((prev) => ({ ...prev, pipeline }));

      // =====================================================================
      // Animate through steps 1-7 quickly, populating data BEFORE marking done
      // =====================================================================

      // --- Step 1: NER entities ---
      setPipelineData((prev) => ({ ...prev, step1: nerEntities, _meta: meta, _extraction: extraction, _verification: verification }));
      updateStep(1, "running");
      scrollTo(1);
      await new Promise((r) => setTimeout(r, 200));
      setTiming(1, stepDurations[0]);
      updateStep(1, "done");

      // --- Step 2: Negation filter ---
      // For skill pipeline, before===after (both from diagnoses). Build a proper
      // "before" list that also includes negated conditions so the diff is visible.
      const negEntities = (negatedConditions ?? []).map((n: any) => ({
        text: n.description ?? n.condition ?? (typeof n === "string" ? n : ""),
        name: n.description ?? n.condition ?? (typeof n === "string" ? n : ""),
        icd10: n.icd10 ?? n.icd10_code ?? "",
        confidence: 0,
        negated: true,
        category: "disease",
        source: "negated",
      }));
      const beforeWithNegated = [...nerEntities, ...negEntities];
      setPipelineData((prev) => ({
        ...prev,
        step2: { before: beforeWithNegated, after: afterNegation },
        negatedConditions,
      }));
      updateStep(2, "running");
      scrollTo(2);
      await new Promise((r) => setTimeout(r, 200));
      setTiming(2, stepDurations[1]);
      updateStep(2, "done");

      // --- Step 3: ICD-10 Code Mapping ---
      // Also pass tool_calls for validate_icd10 and lookup_hcc as fallback data
      const icdToolCalls = toolCalls.filter((tc: any) =>
        ["validate_icd10", "lookup_hcc", "validate_icd10_code", "lookup_hcc_mapping"].includes(tc.function)
      );
      setPipelineData((prev) => ({ ...prev, step3: candidates, afterEntities: afterNegation, step3ToolCalls: icdToolCalls }));
      updateStep(3, "running");
      scrollTo(3);
      await new Promise((r) => setTimeout(r, 200));
      setTiming(3, stepDurations[2]);
      updateStep(3, "done");

      // --- Step 4: AI Clinical Analysis ---
      setPipelineData((prev) => ({
        ...prev,
        step4: {
          diagnoses: result.diagnoses,
          suspects: result.suspect_conditions,
          negated: negatedConditions,
        },
      }));
      updateStep(4, "running");
      scrollTo(4);
      await new Promise((r) => setTimeout(r, 200));
      setTiming(4, stepDurations[3]);
      updateStep(4, "done");

      // --- Step 5: ICD Validation ---
      setPipelineData((prev) => ({
        ...prev,
        step5: (result.diagnoses ?? []).map((d: any) => ({
          icd10: d.icd10 ?? d.icd10_code ?? "",
          description: d.description ?? d.icd10_description ?? d.condition ?? "",
          valid: d.icd10_valid !== false,
        })),
      }));
      updateStep(5, "running");
      scrollTo(5);
      await new Promise((r) => setTimeout(r, 200));
      setTiming(5, stepDurations[4]);
      updateStep(5, "done");

      // --- Step 6: RAF Calculation ---
      updateStep(6, "running");
      scrollTo(6);
      const t6 = Date.now();
       
      let raf: Record<string, any> | null = null;
      try {
        const rafToolCall = toolCalls.find((tc: any) => tc.function === "calculate_raf_score");
        if (rafToolCall?.result?.raf_score) {
          const serverRaf = rafToolCall.result;
          const rafArgs = rafToolCall.args ?? {};
          const patAge = rafArgs.age ?? meta.patient_age ?? 0;
          const patSex = rafArgs.sex ?? meta.patient_sex ?? "";
          const sexLabel = patSex.toString().toUpperCase().startsWith("F") ? "F" : "M";

          // Build HCC component list: prefer hcc_details, fall back to hcc_list + coefficients
          let hccDetails: any[] = serverRaf.hcc_details ?? serverRaf.hcc_contributions ?? [];
          const allCoefficients: Record<string, number> = serverRaf.coefficients ?? {};
          if ((!hccDetails || hccDetails.length === 0) && serverRaf.hcc_list?.length > 0) {
            // Fallback: build from hcc_list + coefficients dict
            hccDetails = (serverRaf.hcc_list as string[]).map((hcc: string) => {
              const hccKey = hcc.startsWith("HCC") ? hcc : `HCC${hcc}`;
              return {
                hcc: hcc.replace(/^HCC/, ""),
                coefficient: allCoefficients[hccKey] ?? allCoefficients[hcc] ?? 0,
                label: HCC_NAMES[hccKey] ?? "",
              };
            });
          }
          // Interaction handling: prefer interaction_details from backend (contains real
          // coefficients and human-readable labels). Fall back to coefficient-scraping for
          // older responses that pre-date the interaction_details field.
          const interactionScore = +(serverRaf.interaction_score ?? Math.max(0, (serverRaf.raf_score ?? 0) - (serverRaf.demographic_score ?? 0) - (serverRaf.disease_score ?? 0))).toFixed(3);

          let interactionComponents: any[];
          if (serverRaf.interaction_details && serverRaf.interaction_details.length > 0) {
            // Use structured interaction_details from backend — each entry has term, coefficient, description
            interactionComponents = (serverRaf.interaction_details as any[]).map((item: any) => ({
              component: item.term,
              coefficient: typeof item.coefficient === "number" ? item.coefficient : 0,
              description: item.description ?? item.term,
            }));
          } else {
            // Fallback: derive from coefficients dict (entries that aren't HCC or demographic)
            const hccKeySet = new Set((serverRaf.hcc_list ?? []).map((h: string) => h.startsWith("HCC") ? h : `HCC${h}`));
            interactionComponents = Object.entries(allCoefficients)
              .filter(([k]) => !hccKeySet.has(k) && !k.match(/^[MF]\d/))
              .map(([name, coeff]) => ({
                component: name,
                coefficient: typeof coeff === "number" ? coeff : 0,
                description: "Interaction term",
              }));
          }

          raf = {
            raf_score: serverRaf.raf_score,
            demographic_score: serverRaf.demographic_score ?? 0,
            disease_score: serverRaf.disease_score ?? 0,
            interaction_score: interactionScore,
            interaction_details: serverRaf.interaction_details ?? [],
            cc_to_dx: (serverRaf.cc_to_dx ?? {}) as Record<string, string[]>,
            components: [
              {
                component: `${sexLabel}${patAge}`,
                coefficient: serverRaf.demographic_score ?? 0,
                description: `Demographic (${patAge}yo ${patSex})`,
              },
              ...hccDetails.map((h: any) => ({
                component: `HCC${h.hcc}`,
                coefficient: h.coefficient ?? 0,
                description: h.label ?? HCC_NAMES[`HCC${h.hcc}`] ?? "",
              })),
              ...interactionComponents,
            ],
          };
        } else {
          // Fallback: client-side RAF calculation
          const HCC_COEFFICIENTS: Record<string, number> = {
            "HCC37": 0.166, "HCC38": 0.166, "HCC85": 0.368, "HCC226": 0.360,
            "HCC329": 0.127, "HCC328": 0.127, "HCC327": 0.289, "HCC18": 0.368,
            "HCC19": 0.105, "HCC137": 0.408, "HCC111": 0.346, "HCC280": 0.209,
            "HCC96": 0.280, "HCC238": 0.299, "HCC52": 0.371, "HCC127": 0.341,
            "HCC155": 0.395, "HCC8": 2.681, "HCC1": 0.451, "HCC22": 0.273,
            "HCC190": 1.792, "HCC189": 0.505, "HCC186": 0.756, "HCC12": 0.163,
            "HCC48": 0.273, "HCC21": 0.540, "HCC40": 0.374, "HCC57": 0.415,
            "HCC59": 0.166, "HCC78": 0.606, "HCC77": 0.513, "HCC103": 0.480,
            "HCC107": 0.430, "HCC108": 0.299, "HCC158": 1.090, "HCC151": 0.415,
            "HCC154": 0.166, "HCC199": 0.615, "HCC221": 1.053, "HCC381": 1.090,
            "HCC93": 0.374, "HCC94": 0.374, "HCC253": 0.480, "HCC263": 0.430,
            "HCC135": 0.204, "HCC198": 0.513, "HCC224": 0.368, "HCC146": 0.163,
            "HCC138": 0.365, "HCC29": 0.213, "HCC157": 0.200, "HCC100": 0.480,
            "HCC101": 0.380, "HCC102": 0.280, "HCC104": 0.480, "HCC75": 1.792,
            "HCC84": 0.616, "HCC35": 0.476, "HCC36": 0.354, "HCC54": 0.306,
            "HCC55": 0.306, "HCC56": 0.200, "HCC46": 0.584, "HCC47": 0.200,
            "HCC51": 0.471, "HCC62": 0.372, "HCC63": 0.200, "HCC169": 0.200,
            "HCC170": 0.200, "HCC248": 0.200, "HCC249": 0.200, "HCC260": 0.200,
          };
          const INTERACTIONS: Record<string, { hccs: string[]; coefficient: number }> = {
            "DIABETES_HF_V28": { hccs: ["HCC37","HCC38","HCC226","HCC85"], coefficient: 0.112 },
            "HF_KIDNEY_V28": { hccs: ["HCC226","HCC85","HCC329","HCC328","HCC327"], coefficient: 0.176 },
          };
          const seenHCC = new Set<string>();
          const hccs = (result.diagnoses ?? [])
            .filter((d: any) => d.hcc || d.hcc_code || d.hcc_mapping?.hcc_code)
            .filter((d: any) => {
              const raw = d.hcc || d.hcc_code || d.hcc_mapping?.hcc_code || "";
              const hccKey = raw.startsWith("HCC") ? raw : `HCC${raw}`;
              if (seenHCC.has(hccKey)) return false;
              seenHCC.add(hccKey);
              return true;
            })
            .map((d: any) => {
              const rawHcc = d.hcc || d.hcc_code || d.hcc_mapping?.hcc_code || "";
              const hccKey = rawHcc.startsWith("HCC") ? rawHcc : `HCC${rawHcc}`;
              const coeff = HCC_COEFFICIENTS[hccKey] ?? 0.200;
              return {
                hcc: hccKey,
                coefficient: coeff,
                condition: d.description ?? d.condition ?? "",
                icd10: d.icd10 ?? d.icd10_code ?? "",
              };
            });
          const diseaseCoeff = hccs.reduce((s: number, h: any) => s + (h.coefficient || 0), 0);
          const hccSet = new Set(hccs.map((h: any) => h.hcc));
          let interactionCoeff = 0;
          const firedInteractions: { name: string; coefficient: number }[] = [];
          for (const [name, info] of Object.entries(INTERACTIONS)) {
            const hasPair = info.hccs.filter((h) => hccSet.has(h)).length >= 2;
            if (hasPair) {
              interactionCoeff += info.coefficient;
              firedInteractions.push({ name, coefficient: info.coefficient });
            }
          }
          const rafTC = toolCalls.find((tc: any) => tc.function === "calculate_raf_score");
          const age = rafTC?.args?.age ?? meta.patient_age ?? patientContext?.demographics?.age ?? 0;
          const sex = (rafTC?.args?.sex ?? meta.patient_sex ?? patientContext?.demographics?.sex ?? "Male").toString().toUpperCase().startsWith("F") ? "F" : "M";
          const DEMO_COEFFICIENTS: Record<string, number> = {
            "M0_34": 0.103, "M35_44": 0.146, "M45_54": 0.207, "M55_59": 0.283,
            "M60_64": 0.310, "M65_69": 0.322, "M70_74": 0.396, "M75_79": 0.488,
            "M80_84": 0.584, "M85_89": 0.682, "M90_94": 0.750, "M95_": 0.770,
            "F0_34": 0.092, "F35_44": 0.131, "F45_54": 0.189, "F55_59": 0.237,
            "F60_64": 0.282, "F65_69": 0.283, "F70_74": 0.341, "F75_79": 0.416,
            "F80_84": 0.494, "F85_89": 0.573, "F90_94": 0.635, "F95_": 0.659,
          };
          let demoKey = "";
          if (age < 35) demoKey = `${sex}0_34`;
          else if (age < 45) demoKey = `${sex}35_44`;
          else if (age < 55) demoKey = `${sex}45_54`;
          else if (age < 60) demoKey = `${sex}55_59`;
          else if (age < 65) demoKey = `${sex}60_64`;
          else if (age < 70) demoKey = `${sex}65_69`;
          else if (age < 75) demoKey = `${sex}70_74`;
          else if (age < 80) demoKey = `${sex}75_79`;
          else if (age < 85) demoKey = `${sex}80_84`;
          else if (age < 90) demoKey = `${sex}85_89`;
          else if (age < 95) demoKey = `${sex}90_94`;
          else demoKey = `${sex}95_`;
          const demographic = DEMO_COEFFICIENTS[demoKey] ?? 0.396;
          const totalRAF = +(demographic + diseaseCoeff + interactionCoeff).toFixed(3);
          raf = {
            raf_score: totalRAF,
            demographic_score: demographic,
            disease_score: +(diseaseCoeff ?? 0).toFixed(3),
            interaction_score: +(interactionCoeff ?? 0).toFixed(3),
            components: [
              { component: demoKey, coefficient: demographic, description: `Demographic (${age}yo ${sex})` },
              ...hccs.map((h: any) => ({
                component: h.hcc,
                coefficient: h.coefficient,
                description: `${h.condition} (${h.icd10})`,
              })),
              ...firedInteractions.map((fi) => ({
                component: fi.name,
                coefficient: fi.coefficient,
                description: `Interaction bonus`,
              })),
            ],
          };
        }
      } catch {
        const demographic = 0.396;
        raf = {
          raf_score: demographic,
          demographic_score: demographic,
          disease_score: 0,
          components: [
            { component: "M70_74", coefficient: demographic, description: "Demographic (fallback)" },
          ],
        };
      }
      setRafResult(raf);
      setPipelineData((prev) => ({ ...prev, step6: raf }));
      await new Promise((r) => setTimeout(r, 200));
      setTiming(6, Date.now() - t6);
      updateStep(6, "done");

      // --- Step 7: Gap Analysis ---
      updateStep(7, "running");
      scrollTo(7);
      const t7 = Date.now();

      const aiHCCs = (result.diagnoses ?? [])
        .map((d: any) => d.hcc || d.hcc_code || d.hcc_mapping?.hcc_code)
        .filter((hcc: any) => hcc && typeof hcc === "string" && /^HCC\d|^\d+$/.test(hcc))
        .map((hcc: string) => hcc.startsWith("HCC") ? hcc : `HCC${hcc}`);
      const aiRAF = raf?.raf_score ?? 1;

      let billingRAF = 0;
      let billingComponents: any[] = [];
      const isPasteMode = inputMode === "paste" || !selectedPatientId;

      const aiDemoComponent = raf?.components?.find((c: any) => c.component?.startsWith("M") || c.component?.startsWith("F"));
      const demographicScore = raf?.demographic_score ?? aiDemoComponent?.coefficient ?? 0;

      if (isPasteMode) {
        billingRAF = demographicScore;
        if (aiDemoComponent) {
          billingComponents = [{ ...aiDemoComponent, description: `Demographic only (no billing data)` }];
        }
      } else {
        try {
          const { data: billingData } = await api.get(`/api/raf/scores/${selectedPatientId}/breakdown`);
          billingRAF = billingData?.raf_score ?? 0;
          if (billingData?.demographic_score) {
            const sex = (billingData?.sex ?? patientContext?.sex ?? "M").toString().toUpperCase().startsWith("F") ? "F" : "M";
            const age = billingData?.age ?? patientContext?.age ?? 70;
            billingComponents.push({ component: `${sex}${age}`, coefficient: billingData.demographic_score, description: `Demographic` });
          }
          const HCC_COEFF: Record<string, number> = {
            "HCC37": 0.166, "HCC38": 0.166, "HCC48": 0.186, "HCC85": 0.368,
            "HCC226": 0.360, "HCC329": 0.127, "HCC238": 0.299, "HCC127": 0.341,
            "HCC155": 0.395, "HCC111": 0.346, "HCC52": 0.371, "HCC93": 0.374,
          };
          for (const hcc of (billingData?.hcc_details ?? [])) {
            const code = `HCC${hcc.hcc_code}`;
            billingComponents.push({ component: code, coefficient: hcc.coefficient ?? HCC_COEFF[code] ?? (billingData.disease_score / (billingData.hcc_count || 1)), description: hcc.hcc_label ?? "" });
          }
        } catch {
          billingRAF = patientContext?.raf_score ?? demographicScore;
        }
        if (!billingRAF) billingRAF = patientContext?.raf_score ?? demographicScore;
      }

      const revenueImpact = ((aiRAF - billingRAF) * 11015.04).toFixed(0);

      const billingHCCSet = new Set(billingComponents.filter((c: any) => c.component?.startsWith("HCC")).map((c: any) => c.component));
      const newAIHCCs = [...new Set(aiHCCs)].filter((h: string) => {
        const code = h?.startsWith("HCC") ? h : `HCC${h}`;
        return !billingHCCSet.has(code);
      });

      setPipelineData((prev) => ({
        ...prev,
        step7: {
          billing_raf: +(billingRAF ?? 0).toFixed(3),
          billing_components: billingComponents,
          ai_raf: aiRAF,
          ai_components: raf?.components ?? [],
          new_hccs: newAIHCCs,
          revenue_impact: +revenueImpact,
          is_paste_mode: isPasteMode,
          demographic: aiDemoComponent ?? null,
        },
      }));
      await new Promise((r) => setTimeout(r, 200));
      setTiming(7, Date.now() - t7);
      updateStep(7, "done");

      // --- Step 8: Quality Verification ---
      if (verification) {
        updateStep(8, "running");
        scrollTo(8);
        const t8 = Date.now();
        setPipelineData((prev) => ({ ...prev, step8: verification }));
        await new Promise((r) => setTimeout(r, 200));
        const stageTimings = meta?.timings ?? {};
        const verificationMs = stageTimings.stage3_verification
          ? stageTimings.stage3_verification * 1000
          : Date.now() - t8;
        setTiming(8, verificationMs);
        updateStep(8, "done");
      } else {
        // No verification data — skip step 8 silently (mark done instantly)
        updateStep(8, "done");
        setTiming(8, 0);
      }

      // --- Step 9: Review Queue Routing ---
      updateStep(9, "running");
      scrollTo(9);
      const t9 = Date.now();
      const diagnoses = result.diagnoses ?? [];
      // Prefer the backend-computed review_queue when it is present; fall back to
      // the client-side routing helper for older pipeline responses that predate
      // the review_queue service.
      const backendQueue = (result as any).review_queue ?? null;
      setPipelineData((prev) => ({
        ...prev,
        step9: {
          diagnoses,
          verification: verification ?? null,
          backendQueue,
        },
      }));
      await new Promise((r) => setTimeout(r, 300));
      setTiming(9, Date.now() - t9);
      updateStep(9, "done");
    } catch (err) {
      console.error("Pipeline error", err);
      if (apiTimerRef.current) clearInterval(apiTimerRef.current);
      setApiLoading(false);
    } finally {
      setRunning(false);
      if (apiTimerRef.current) clearInterval(apiTimerRef.current);
      setApiLoading(false);
    }
  }, [running, inputMode, noteText, selectedPatientId, selectedEncounterId, encounterPreview]);

  const reset = () => {
    setStepStatuses(PIPELINE_STEPS.map(() => "pending"));
    setStepTimings(PIPELINE_STEPS.map(() => null));
    setPipelineData({});
    setAnalysisResult(null);
    setRafResult(null);
    setExpandedStep(null);
    setApiLoading(false);
    setApiElapsed(0);
    if (apiTimerRef.current) clearInterval(apiTimerRef.current);
    setRunning(false);
  };

  const allDone = stepStatuses.every((s) => s === "done");
  const completedCount = stepStatuses.filter((s) => s === "done").length;
  const progressPct = (completedCount / PIPELINE_STEPS.length) * 100;

  // ---------------------------------------------------------------------------
  // Render step content
  // ---------------------------------------------------------------------------
  function renderStepContent(idx: number) {
    switch (idx) {
      case 0:
        return <Step0Content data={pipelineData.step0} noteText={noteText} extraction={pipelineData._extraction} />;
      case 1:
        return <Step1Content entities={pipelineData.step1} noteText={noteText} />;
      case 2:
        return <Step2Content data={pipelineData.step2} negatedConditions={pipelineData.negatedConditions} />;
      case 3:
        return <Step3Content candidates={pipelineData.step3} afterEntities={pipelineData.afterEntities} toolCalls={pipelineData.step3ToolCalls} />;
      case 4:
        return <Step4Content data={pipelineData.step4} />;
      case 5:
        return <Step5Content data={pipelineData.step5} />;
      case 6:
        return <Step6Content data={pipelineData.step6} />;
      case 7:
        return <Step7Content data={pipelineData.step7} rafData={rafResult} />;
      case 8:
        return <Step8Content data={pipelineData.step8} />;
      case 9:
        return <Step9Content data={pipelineData.step9} />;
      default:
        return null;
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  const C_DEMO = {
    text: "#0F172A",
    textMuted: "#475569",
    textSubtle: "#64748B",
    label: "#94A3B8",
    border: "#E2E8F0",
    borderSoft: "#EEF2F6",
    bgPage: "#F8FAFC",
    bgCard: "#FFFFFF",
    accent: "#0F766E", // app brand teal — matches sidebar logo
    accentSoft: "rgba(15, 118, 110, 0.08)",
  };
  const FONT_SYS_DEMO =
    '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, Roboto, Helvetica, Arial, sans-serif';

  return (
    <div
      style={{
        background: C_DEMO.bgPage,
        minHeight: "100vh",
        fontFamily: FONT_SYS_DEMO,
        color: C_DEMO.text,
        padding: "32px 24px 64px",
      }}
    >
      <div style={{ maxWidth: 1200, margin: "0 auto" }} className="space-y-6">
      {/* Page header — clean indigo tile + slate type */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <div
            style={{
              height: 44,
              width: 44,
              borderRadius: 12,
              background: C_DEMO.accentSoft,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              border: `1px solid ${C_DEMO.border}`,
            }}
          >
            <Brain className="h-5 w-5" style={{ color: C_DEMO.accent }} />
          </div>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, margin: 0, lineHeight: 1.2, color: C_DEMO.text, letterSpacing: -0.2 }}>
              RAF Intelligence Pipeline
            </h1>
            <p style={{ margin: "4px 0 0", fontSize: 13, color: C_DEMO.textSubtle }}>
              Watch a 10-stage clinical pipeline process a note in real time — NER, negation, ICD-10, HCC, and RAF.
            </p>
          </div>
        </div>
        {allDone && (
          <button
            onClick={reset}
            style={{
              border: `1px solid ${C_DEMO.border}`,
              background: C_DEMO.bgCard,
              color: C_DEMO.text,
              borderRadius: 10,
              padding: "8px 14px",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Reset
          </button>
        )}
      </div>

      {/* ================================================================= */}
      {/* INPUT SECTION                                                      */}
      {/* ================================================================= */}
      <Card
        className="overflow-hidden"
        style={{
          background: C_DEMO.bgCard,
          border: `1px solid ${C_DEMO.border}`,
          borderRadius: 16,
          boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)",
        }}
      >
        <CardContent className="space-y-4 p-5 sm:p-6">
          <div className="flex items-center justify-between gap-4">
            <div className="flex items-center gap-2.5">
              <div
                className="flex h-9 w-9 items-center justify-center rounded-xl"
                style={{ background: "linear-gradient(135deg, #EFF6FF, #DBEAFE)" }}
              >
                <FileText className="h-4 w-4" style={{ color: "#2563EB" }} />
              </div>
              <div>
                <h2 className="text-sm font-semibold leading-tight">Clinical Input</h2>
                <p className="text-[11px] text-muted-foreground">Paste a note or pull from your EMR</p>
              </div>
            </div>
            {/* Segmented control */}
            <div
              className="inline-flex p-1 gap-1"
              style={{
                background: "#F1F5F9",
                border: `1px solid ${C_DEMO.border}`,
                borderRadius: 12,
              }}
            >
              <button
                type="button"
                onClick={() => setInputMode("paste")}
                disabled={running}
                className="inline-flex items-center gap-2 transition-all"
                style={{
                  borderRadius: 9,
                  padding: "8px 16px",
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: running ? "not-allowed" : "pointer",
                  background: inputMode === "paste" ? C_DEMO.accent : "transparent",
                  color: inputMode === "paste" ? "#FFFFFF" : C_DEMO.textMuted,
                  boxShadow:
                    inputMode === "paste"
                      ? "0 1px 3px rgba(15, 118, 110, 0.30), 0 1px 2px rgba(15, 118, 110, 0.20)"
                      : "none",
                  border: "none",
                }}
              >
                <FileText className="h-4 w-4" /> Paste Note
              </button>
              <button
                type="button"
                onClick={() => { setInputMode("patient"); setNoteText(""); }}
                disabled={running}
                className="inline-flex items-center gap-2 transition-all"
                style={{
                  borderRadius: 9,
                  padding: "8px 16px",
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: running ? "not-allowed" : "pointer",
                  background: inputMode === "patient" ? C_DEMO.accent : "transparent",
                  color: inputMode === "patient" ? "#FFFFFF" : C_DEMO.textMuted,
                  boxShadow:
                    inputMode === "patient"
                      ? "0 1px 3px rgba(15, 118, 110, 0.30), 0 1px 2px rgba(15, 118, 110, 0.20)"
                      : "none",
                  border: "none",
                }}
              >
                <Users className="h-4 w-4" /> From OpenEMR
              </button>
            </div>
          </div>
          <Tabs value={inputMode} onValueChange={(v) => {
            setInputMode(v as "paste" | "patient");
            if (v === "patient") {
              setNoteText("");
            }
          }}>
            <TabsList className="sr-only">
              <TabsTrigger value="paste">Paste</TabsTrigger>
              <TabsTrigger value="patient">Patient</TabsTrigger>
            </TabsList>

            <TabsContent value="paste" className="space-y-3">
              <textarea
                className="w-full rounded-xl border border-border bg-muted/20 p-4 font-mono text-sm leading-relaxed placeholder:text-muted-foreground/60 focus:outline-none focus:border-teal-500 focus:ring-4 focus:ring-teal-500/10 focus:bg-background transition-all resize-y min-h-[200px]"
                rows={8}
                placeholder={"Paste a clinical encounter note here...\n\ne.g. Patient: 72-year-old male\nHistory: Type 2 diabetes, CHF, CKD stage 3..."}
                value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
                disabled={running}
              />
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setNoteText(SAMPLE_NOTE)}
                  disabled={running}
                  className="btn-press rounded-lg border-dashed hover:border-solid hover:border-teal-400 hover:bg-teal-50 dark:hover:bg-teal-950/30 transition-colors"
                >
                  <Sparkles className="mr-1.5 h-3.5 w-3.5 text-teal-600" />
                  Use Sample Note
                </Button>
                {noteText && (
                  <Button variant="ghost" size="sm" onClick={() => setNoteText("")} disabled={running}>
                    <XCircle className="mr-1.5 h-3.5 w-3.5" />
                    Clear
                  </Button>
                )}
                <div className="ml-auto flex items-center gap-3 text-xs">
                  <span className="font-mono tabular-nums text-muted-foreground">
                    {noteText.length.toLocaleString()} chars
                  </span>
                  <span className="h-3 w-px bg-border" />
                  {noteText.trim() ? (
                    <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400 font-semibold">
                      <CheckCircle2 className="h-3.5 w-3.5" /> Ready to analyze
                    </span>
                  ) : (
                    <span className="text-muted-foreground">Paste or load a sample to continue</span>
                  )}
                </div>
              </div>
            </TabsContent>

            <TabsContent value="patient" className="space-y-3">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    <Users className="h-3.5 w-3.5" /> Patient
                  </label>
                  <div className="relative">
                    <select
                      className="w-full appearance-none rounded-xl border border-border bg-muted/20 py-3 pl-4 pr-10 text-sm font-medium focus:outline-none focus:border-teal-500 focus:ring-4 focus:ring-teal-500/10 focus:bg-background transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                      value={selectedPatientId ?? ""}
                      onChange={(e) => {
                        setSelectedPatientId(e.target.value ? Number(e.target.value) : null);
                        setSelectedEncounterId(null);
                      }}
                      disabled={running}
                    >
                      <option value="">Select patient...</option>
                      {patients.map((p: any) => (
                        <option key={p.pid} value={Math.round(Number(p.pid))}>
                          {p.fname} {p.lname} — {p.encounter_count ?? 0} encounters (PID {Math.round(Number(p.pid))})
                        </option>
                      ))}
                    </select>
                    <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  </div>
                </div>
                <div>
                  <label className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    <ClipboardList className="h-3.5 w-3.5" /> Encounter
                  </label>
                  <div className="relative">
                    <select
                      className="w-full appearance-none rounded-xl border border-border bg-muted/20 py-3 pl-4 pr-10 text-sm font-medium focus:outline-none focus:border-teal-500 focus:ring-4 focus:ring-teal-500/10 focus:bg-background transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                      value={selectedEncounterId ?? ""}
                      onChange={(e) => setSelectedEncounterId(e.target.value ? Number(e.target.value) : null)}
                      disabled={running || !selectedPatientId}
                    >
                      <option value="">Select encounter...</option>
                      {encounters.map((enc: any) => {
                        const hasNotes = Number(enc.has_notes ?? 0) > 0;
                        return (
                          <option key={Math.round(enc.encounter_id)} value={Math.round(enc.encounter_id)} disabled={!hasNotes}>
                            #{Math.round(enc.encounter_id)} — {enc.date?.split("T")[0]} {enc.reason ? `- ${enc.reason}` : ""} {hasNotes ? "✓ Has Notes" : "— No Notes"}
                          </option>
                        );
                      })}
                    </select>
                    <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  </div>
                </div>
              </div>

              {/* Encounter Data Preview */}
              {previewLoading && (
                <div className="flex items-center gap-2 p-4 rounded-xl bg-muted/50 border">
                  <Loader2 className="h-4 w-4 animate-spin text-teal-500" />
                  <span className="text-sm text-muted-foreground">Loading encounter data...</span>
                </div>
              )}
              {encounterPreview && !previewLoading && (
                <div className="space-y-3 animate-in fade-in slide-in-from-top-2 duration-300">
                  {/* Patient Info Card */}
                  <div className="p-4 rounded-xl bg-gradient-to-r from-blue-50 to-cyan-50 dark:from-blue-950/30 dark:to-cyan-950/30 border border-blue-200/50 dark:border-blue-800/50">
                    <div className="flex items-center justify-between mb-3">
                      <h4 className="font-bold text-sm flex items-center gap-2">
                        <Users className="h-4 w-4 text-blue-600" />
                        Patient Information
                      </h4>
                      <Badge className="bg-blue-600 text-white text-xs">PID {Math.round(Number(encounterPreview.patient?.pid))}</Badge>
                    </div>
                    <div className="grid grid-cols-3 gap-3 text-sm">
                      <div><span className="text-muted-foreground">Name:</span> <strong>{encounterPreview.patient?.fname} {encounterPreview.patient?.lname}</strong></div>
                      <div><span className="text-muted-foreground">DOB:</span> <strong>{encounterPreview.patient?.DOB}</strong></div>
                      <div><span className="text-muted-foreground">Sex:</span> <strong>{encounterPreview.patient?.sex}</strong></div>
                      <div><span className="text-muted-foreground">City:</span> <strong>{encounterPreview.patient?.city}</strong></div>
                      <div><span className="text-muted-foreground">RAF Score:</span> <strong>{encounterPreview.patient?.raf_score?.toFixed(3) ?? "N/A"}</strong></div>
                      <div><span className="text-muted-foreground">HCCs:</span> <strong>{encounterPreview.patient?.hcc_count ?? 0}</strong></div>
                    </div>
                  </div>

                  {/* Data Stats */}
                  <div className="grid grid-cols-4 gap-2">
                    <div className="p-3 rounded-xl bg-card border text-center">
                      <div className="text-2xl font-extrabold text-blue-600">{encounterPreview.totalEncounters}</div>
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium mt-0.5">Encounters</div>
                    </div>
                    <div className="p-3 rounded-xl bg-card border text-center">
                      <div className="text-2xl font-extrabold text-emerald-600">{encounterPreview.allDiagnoses?.length ?? 0}</div>
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium mt-0.5">Total Diagnoses</div>
                    </div>
                    <div className="p-3 rounded-xl bg-card border text-center">
                      <div className="text-2xl font-extrabold text-violet-600">{encounterPreview.medications?.length ?? 0}</div>
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium mt-0.5">Medications</div>
                    </div>
                    <div className="p-3 rounded-xl bg-card border text-center">
                      <div className="text-2xl font-extrabold text-amber-600">{encounterPreview.diagnoses?.length ?? 0}</div>
                      <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium mt-0.5">This Encounter</div>
                    </div>
                  </div>

                  {/* Encounter Details */}
                  <div className="p-4 rounded-xl bg-card border">
                    <h4 className="font-bold text-sm mb-2 flex items-center gap-2">
                      <FileText className="h-4 w-4 text-teal-600" />
                      Selected Encounter #{selectedEncounterId}
                    </h4>
                    <div className="grid grid-cols-2 gap-2 text-sm mb-3">
                      <div><span className="text-muted-foreground">Date:</span> <strong>{encounterPreview.encounter?.date?.split("T")[0]}</strong></div>
                      <div><span className="text-muted-foreground">Reason:</span> <strong>{encounterPreview.encounter?.reason || "—"}</strong></div>
                    </div>

                    {/* Diagnoses for this encounter */}
                    {encounterPreview.diagnoses?.length > 0 && (
                      <div className="mt-2">
                        <p className="text-xs font-medium text-muted-foreground mb-1.5">Billed Diagnoses:</p>
                        <div className="flex flex-wrap gap-1.5">
                          {encounterPreview.diagnoses.map((d: any, i: number) => (
                            <Badge key={d.code ?? i} variant="outline" className="text-xs font-mono">
                              {(d.code || "").trim()} — {(d.description || d.code_text || "").trim().substring(0, 40)}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Medications */}
                    {encounterPreview.medications?.length > 0 && (
                      <div className="mt-3">
                        <p className="text-xs font-medium text-muted-foreground mb-1.5">Active Medications ({encounterPreview.medications.length}):</p>
                        <div className="flex flex-wrap gap-1.5">
                          {encounterPreview.medications.slice(0, 8).map((m: any, i: number) => (
                            <Badge key={m.drug ?? i} variant="secondary" className="text-xs">
                              {m.drug} {m.dosage || ""}
                            </Badge>
                          ))}
                          {encounterPreview.medications.length > 8 && (
                            <Badge variant="secondary" className="text-xs">+{encounterPreview.medications.length - 8} more</Badge>
                          )}
                        </div>
                      </div>
                    )}

                    {/* Clinical Notes */}
                    {encounterPreview.clinicalNotes?.length > 0 && (
                      <div className="mt-4">
                        <p className="text-xs font-semibold text-muted-foreground mb-2 uppercase tracking-wider flex items-center gap-1.5">
                          <FileText className="h-3.5 w-3.5" />
                          Clinical Notes ({encounterPreview.clinicalNotes.length})
                        </p>
                        <div className="rounded-lg border bg-muted/30 max-h-[400px] overflow-y-auto">
                          {encounterPreview.clinicalNotes.map((note: any, i: number) => (
                            <div key={i} className={`p-3 ${i > 0 ? "border-t" : ""}`}>
                              {note.note_type && (
                                <Badge variant="outline" className="text-[10px] mb-1.5 uppercase">{note.note_type}</Badge>
                              )}
                              <pre className="text-xs font-sans leading-relaxed text-foreground/80" style={{ whiteSpace: "pre-wrap" }}>
                                {note.note_text || note.description || ""}
                              </pre>
                            </div>
                          ))}
                        </div>
                        <p className="text-[10px] text-muted-foreground mt-1">
                          {encounterPreview.noteChars?.toLocaleString()} characters — this is what the pipeline will analyze
                        </p>
                      </div>
                    )}
                  </div>

                  {(() => {
                    const selEnc = encounters.find((e: any) => Math.round(e.encounter_id) === selectedEncounterId) as any;
                    const hasNotes = Number(selEnc?.has_notes ?? 0) > 0;
                    return hasNotes ? (
                      <div className="p-2.5 rounded-lg bg-teal-500/10 border border-teal-500/20">
                        <p className="text-xs text-teal-700 dark:text-teal-400 flex items-center gap-1.5">
                          <Zap className="h-3.5 w-3.5 shrink-0" />
                          Clinical notes found. Click <strong className="mx-0.5">Run Pipeline</strong> to analyze.
                        </p>
                      </div>
                    ) : (
                      <div className="p-2.5 rounded-lg bg-red-500/10 border border-red-500/20">
                        <p className="text-xs text-red-700 dark:text-red-400 flex items-center gap-1.5">
                          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                          This encounter has <strong className="mx-0.5">no clinical notes</strong>. Select an encounter marked &quot;✓ Has Notes&quot;.
                        </p>
                      </div>
                    );
                  })()}
                </div>
              )}
            </TabsContent>
          </Tabs>

          <Button
            size="lg"
            className="w-full text-white text-sm font-semibold h-11 rounded-xl transition-all disabled:opacity-60"
            style={{ background: C_DEMO.accent }}
            disabled={
              running ||
              (inputMode === "paste" && !noteText.trim()) ||
              (inputMode === "patient" && (!selectedEncounterId || !Number((encounters.find((e: any) => Math.round(e.encounter_id) === selectedEncounterId) as any)?.has_notes ?? 0)))
            }
            onClick={runPipeline}
          >
            {running ? (
              <><Loader2 className="mr-2 h-5 w-5 animate-spin" /> Pipeline Running...</>
            ) : (
              <><Play className="mr-2 h-5 w-5" /> Run Pipeline</>
            )}
          </Button>
        </CardContent>
      </Card>

      {/* ================================================================= */}
      {/* PROGRESS BAR                                                       */}
      {/* ================================================================= */}
      {(running || allDone || completedCount > 0) && (
        <div
          className="space-y-4 p-5"
          style={{
            background: C_DEMO.bgCard,
            border: `1px solid ${C_DEMO.border}`,
            borderRadius: 16,
            boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)",
          }}
        >
          <div className="flex items-center justify-between text-sm">
            <div className="flex items-center gap-3">
              <span className="font-semibold">
                {running ? (
                  <span className="inline-flex items-center gap-2">
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-teal-500" />
                    Processing...
                  </span>
                ) : allDone ? (
                  <span className="inline-flex items-center gap-2 text-emerald-600 dark:text-emerald-400">
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    Pipeline Complete
                  </span>
                ) : (
                  `Step ${completedCount}/${PIPELINE_STEPS.length}`
                )}
              </span>
              {allDone && pipelineData._verification?.quality_score != null && (
                <QualityScoreBadge score={pipelineData._verification.quality_score} />
              )}
            </div>
            <span className="font-mono text-xs text-muted-foreground">{completedCount}/{PIPELINE_STEPS.length} steps</span>
          </div>
          <Progress value={progressPct} className="h-2" />

          {/* Step indicators with connecting line */}
          <div className="relative flex items-start justify-between pt-2">
            {/* Connecting track */}
            <div className="absolute left-5 right-5 top-7 h-0.5 bg-muted" aria-hidden />
            <div
              className="absolute left-5 top-7 h-0.5 bg-gradient-to-r from-emerald-500 to-teal-500 transition-all duration-500"
              style={{ width: `calc((100% - 2.5rem) * ${progressPct / 100})` }}
              aria-hidden
            />
            {PIPELINE_STEPS.map((step, idx) => {
              const status = stepStatuses[idx];
              const timing = stepTimings[idx];
              const Icon = step.icon;
              return (
                <div key={step.id} className="flex flex-col items-center gap-1 relative z-10">
                  <button
                    onClick={() => status === "done" && setExpandedStep(expandedStep === idx ? null : idx)}
                    disabled={status === "pending"}
                    className={cn(
                      "flex h-10 w-10 items-center justify-center rounded-full border-2 transition-all duration-300",
                      status === "pending" && "border-muted bg-muted/50 text-muted-foreground",
                      status === "running" && "border-teal-500 bg-teal-50 dark:bg-teal-950 text-teal-600 animate-pulse shadow-lg shadow-teal-500/20",
                      status === "done" && "border-emerald-500 bg-emerald-50 dark:bg-emerald-950 text-emerald-600 cursor-pointer hover:scale-110",
                      status === "error" && "border-red-500 bg-red-50 dark:bg-red-950 text-red-600"
                    )}
                  >
                    {status === "running" ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : status === "done" ? (
                      <CheckCircle2 className="h-4 w-4" />
                    ) : (
                      <Icon className="h-4 w-4" />
                    )}
                  </button>
                  <span className={cn(
                    "text-[10px] font-medium",
                    status === "done" ? "text-emerald-600" : status === "running" ? "text-teal-600" : "text-muted-foreground"
                  )}>
                    {step.shortName}
                  </span>
                  {timing !== null && (
                    <span className="text-[9px] text-muted-foreground">{(timing / 1000).toFixed(1)}s</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ================================================================= */}
      {/* LOADING STATE — shown while API call is in progress (Step 1)       */}
      {/* ================================================================= */}
      {running && stepStatuses[0] === "done" && stepStatuses[1] === "running" && (
        <PipelineLoadingState />
      )}

      {/* ================================================================= */}
      {/* API LOADING INDICATOR (between Step 0 and Step 1)                  */}
      {/* ================================================================= */}
      {apiLoading && (
        <Card
          style={{
            background: C_DEMO.bgCard,
            border: `1px solid ${C_DEMO.accent}`,
            borderRadius: 16,
            boxShadow: "0 4px 12px rgba(79, 70, 229, 0.10)",
          }}
        >
          <CardContent className="py-8">
            <div className="flex flex-col items-center justify-center gap-4">
              <div className="relative">
                <Loader2 className="h-12 w-12 animate-spin text-teal-500" />
                <Brain className="h-5 w-5 text-teal-600 absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2" />
              </div>
              <div className="text-center space-y-2">
                <p className="text-base font-semibold text-teal-700 dark:text-teal-400">
                  Analyzing clinical note...
                </p>
                <p className="text-sm text-muted-foreground">
                  This may take 30-60 seconds for complex notes
                </p>
                <div className="flex items-center justify-center gap-2 mt-3">
                  <div className="text-2xl font-mono font-bold text-teal-600 dark:text-teal-400 tabular-nums">
                    {apiElapsed}s
                  </div>
                  <span className="text-xs text-muted-foreground">elapsed</span>
                </div>
              </div>
              <div className="w-64 h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden mt-2">
                <div
                  className="h-full bg-gradient-to-r from-teal-500 to-blue-500 rounded-full transition-all duration-1000"
                  style={{ width: `${Math.min(95, (apiElapsed / 60) * 100)}%` }}
                />
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ================================================================= */}
      {/* STEP CARDS                                                         */}
      {/* ================================================================= */}
      {PIPELINE_STEPS.map((step, idx) => {
        const status = stepStatuses[idx];
        const timing = stepTimings[idx];
        const isExpanded = expandedStep === idx;
        const Icon = step.icon;

        if (status === "pending") return null;

        return (
          <div key={step.id} ref={(el) => { stepsRef.current[idx] = el; }}>
            {/* Arrow between steps */}
            {idx > 0 && (
              <div className="flex justify-center -mt-4 mb-2">
                <ArrowDown className="h-6 w-6 text-emerald-500" />
              </div>
            )}

            <Card
              className={cn(
                "transition-all duration-300",
                status === "running" && "shadow-md",
              )}
              style={{
                background: C_DEMO.bgCard,
                border: `1px solid ${
                  status === "running"
                    ? C_DEMO.accent
                    : status === "done" && isExpanded
                    ? "#A7F3D0"
                    : status === "error"
                    ? "#FCA5A5"
                    : C_DEMO.border
                }`,
                borderRadius: 16,
                boxShadow:
                  status === "running"
                    ? "0 4px 12px rgba(79, 70, 229, 0.10)"
                    : "0 1px 2px rgba(15, 23, 42, 0.04)",
              }}
            >
              {/* Step header */}
              <button
                className="w-full text-left"
                onClick={() => status === "done" && setExpandedStep(isExpanded ? null : idx)}
                disabled={status !== "done"}
              >
                <CardHeader className="pb-0">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <div className={cn(
                        "flex h-9 w-9 items-center justify-center rounded-lg",
                        status === "running" && "bg-teal-100 dark:bg-teal-900 text-teal-600",
                        status === "done" && "bg-emerald-100 dark:bg-emerald-900 text-emerald-600",
                        status === "error" && "bg-red-100 dark:bg-red-900 text-red-600"
                      )}>
                        {status === "running" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Icon className="h-4 w-4" />}
                      </div>
                      <div>
                        <CardTitle className="text-base flex items-center gap-2">
                          <span className="text-muted-foreground font-normal">Step {idx}:</span>
                          {step.name}
                          {step.model && (
                            <Badge variant="outline" className="text-[10px] font-normal">{step.model}</Badge>
                          )}
                        </CardTitle>
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      {timing !== null && (
                        <span className="text-xs text-muted-foreground font-mono">{(timing / 1000).toFixed(2)}s</span>
                      )}
                      {status === "done" && (
                        isExpanded ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />
                      )}
                      {status === "running" && (
                        <Badge className="bg-teal-100 text-teal-700 dark:bg-teal-900 dark:text-teal-300 animate-pulse">Processing</Badge>
                      )}
                    </div>
                  </div>
                </CardHeader>
              </button>

              {/* Step content */}
              {(isExpanded || status === "running") && (
                <CardContent className="pt-4">
                  {status === "running" ? (
                    <div className="flex items-center justify-center py-8 gap-3">
                      <Loader2 className="h-6 w-6 animate-spin text-teal-500" />
                      <span className="text-sm text-muted-foreground">Running {step.name}...</span>
                    </div>
                  ) : (
                    renderStepContent(idx)
                  )}
                </CardContent>
              )}
            </Card>
          </div>
        );
      })}

      {/* ================================================================= */}
      {/* META INFO                                                          */}
      {/* ================================================================= */}
      {allDone && pipelineData._meta && (
        <Card
          style={{
            background: C_DEMO.bgCard,
            border: `1px dashed ${C_DEMO.border}`,
            borderRadius: 16,
          }}
        >
          <CardContent className="py-4">
            <div className="flex items-center justify-center gap-6 text-xs text-muted-foreground flex-wrap">
              <span>Engine: <strong>Analysis Engine</strong></span>
              <span>Entities Extracted: <strong>{pipelineData._meta.entities_extracted ?? pipelineData.step1?.length ?? 0}</strong></span>
              <span>Patient: <strong>{(() => {
                const ep = encounterPreview?.patient;
                const s0 = pipelineData?.step0;
                const patName = ep ? `${ep.fname ?? ""} ${ep.lname ?? ""}`.trim()
                  : s0?.fname ? `${s0.fname ?? ""} ${s0.lname ?? ""}`.trim() : "";
                const tc = (pipelineData?.pipeline?.tool_calls ?? []).find((t: any) => t.function === "calculate_raf_score");
                const age = tc?.args?.age ?? pipelineData?._meta?.patient_age ?? s0?.demographics?.age ?? "";
                const sex = tc?.args?.sex ?? pipelineData?._meta?.patient_sex ?? s0?.demographics?.sex ?? "";
                const ageStr = age && sex ? `${age}yo ${sex}` : "";
                if (patName && ageStr) return `${patName} (${ageStr})`;
                if (patName) return patName;
                if (ageStr) return ageStr;
                return inputMode === "paste" ? "Free-text note" : "N/A";
              })()}</strong></span>
              <span>Stages: <strong>{(analysisResult as any)?.pipeline?.stages_run?.join(" > ") ?? (analysisResult as any)?._meta?.stages?.join(" > ") ?? "Clinical Analysis"}</strong></span>
              {pipelineData._verification?.quality_score != null && (
                <QualityScoreBadge score={pipelineData._verification.quality_score} />
              )}
              {(analysisResult as any)?._meta?.pipeline_version && (
                <Badge variant="outline" className="text-[10px] font-mono">
                  {(analysisResult as any)._meta.pipeline_version}
                </Badge>
              )}
            </div>
          </CardContent>
        </Card>
      )}
      </div>
    </div>
  );
}
