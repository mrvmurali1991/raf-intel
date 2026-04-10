"use client";

import { useState, useEffect, useCallback } from "react";
import api from "@/lib/api";
import {
  Code,
  Plus,
  Trash2,
  Pencil,
  Play,
  Copy,
  CheckCircle2,
  AlertCircle,
  Clock,
  ChevronDown,
  ChevronUp,
  Eye,
  EyeOff,
  RefreshCw,
  Loader2,
  Webhook,
  BookOpen,
  KeyRound,
  Zap,
  X,
  ExternalLink,
  Terminal,
  ShieldCheck,
  AlertTriangle,
  CheckCheck,
} from "lucide-react";
import { PageHeader, StatCard } from "@/components/healthcare-ui";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------


function generateSecret(): string {
  const bytes = new Uint8Array(30);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(36).padStart(2, "0")).join("").slice(0, 40);
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type WebhookStatus = "active" | "inactive";
type HttpMethod = "GET" | "POST" | "PUT" | "DELETE" | "PATCH";

interface WebhookDelivery {
  id: string;
  event: string;
  timestamp: string;
  status_code: number;
  response_time_ms: number;
  attempts: number;
  request_payload?: string;
  response_body?: string;
}

interface WebhookEndpoint {
  id: string;
  url: string;
  secret: string;
  events: string[];
  status: WebhookStatus;
  last_delivery?: string;
  success_rate: number;
  deliveries?: WebhookDelivery[];
}

interface TestResult {
  status_code: number;
  response_time_ms: number;
  success: boolean;
  error?: string;
}

// ---------------------------------------------------------------------------
// Webhook event catalog
// ---------------------------------------------------------------------------

const EVENT_GROUPS = [
  {
    category: "RAF Events",
    events: [
      { id: "score.calculated", label: "score.calculated", desc: "RAF score computed for a patient" },
      { id: "score.changed", label: "score.changed", desc: "RAF score changed significantly" },
    ],
  },
  {
    category: "Clinical",
    events: [
      { id: "suspect.created", label: "suspect.created", desc: "New HCC suspect identified" },
      { id: "suspect.accepted", label: "suspect.accepted", desc: "Suspect diagnosis accepted" },
      { id: "suspect.dismissed", label: "suspect.dismissed", desc: "Suspect diagnosis dismissed" },
    ],
  },
  {
    category: "Documents",
    events: [
      { id: "document.uploaded", label: "document.uploaded", desc: "Clinical document uploaded" },
      { id: "document.analyzed", label: "document.analyzed", desc: "Document AI analysis complete" },
    ],
  },
  {
    category: "Claims",
    events: [
      { id: "claims.batch.processed", label: "claims.batch.processed", desc: "Claims batch processing finished" },
    ],
  },
  {
    category: "FHIR",
    events: [
      { id: "fhir.sync.completed", label: "fhir.sync.completed", desc: "FHIR sync operation completed" },
    ],
  },
  {
    category: "Submissions",
    events: [
      { id: "submission.generated", label: "submission.generated", desc: "RAF submission file generated" },
      { id: "submission.validated", label: "submission.validated", desc: "Submission passed validation" },
    ],
  },
  {
    category: "Providers",
    events: [
      { id: "provider.scorecard.updated", label: "provider.scorecard.updated", desc: "Provider scorecard refreshed" },
    ],
  },
];

// ---------------------------------------------------------------------------
// API endpoint catalog for documentation tab
// ---------------------------------------------------------------------------

const API_CATEGORIES = [
  {
    category: "Patients",
    tag: "patients",
    endpoints: [
      { method: "GET" as HttpMethod, path: "/api/patients", desc: "List all patients with RAF scores and risk stratification", params: ["search", "limit", "offset", "sort_by"] },
      { method: "GET" as HttpMethod, path: "/api/patients/{id}", desc: "Get full patient profile including HCC history and RAF trend", params: ["id"] },
      { method: "POST" as HttpMethod, path: "/api/patients/{id}/raf-score", desc: "Trigger RAF score recalculation for a patient", params: ["id"] },
    ],
  },
  {
    category: "HCC Suspects",
    tag: "suspects",
    endpoints: [
      { method: "GET" as HttpMethod, path: "/api/suspects", desc: "List unreviewed HCC suspects across the patient population", params: ["patient_id", "status", "hcc_code", "limit"] },
      { method: "PUT" as HttpMethod, path: "/api/suspects/{id}/accept", desc: "Accept a suspected HCC diagnosis", params: ["id"] },
      { method: "PUT" as HttpMethod, path: "/api/suspects/{id}/dismiss", desc: "Dismiss a suspected HCC diagnosis with reason", params: ["id"] },
    ],
  },
  {
    category: "Documents",
    tag: "documents",
    endpoints: [
      { method: "POST" as HttpMethod, path: "/api/documents/upload", desc: "Upload a clinical document for AI analysis (PDF, DOCX, HL7 CCD)", params: ["patient_id", "document_type"] },
      { method: "GET" as HttpMethod, path: "/api/documents/{id}", desc: "Get document details and extracted HCC findings", params: ["id"] },
      { method: "GET" as HttpMethod, path: "/api/documents/{id}/analysis", desc: "Retrieve full AI analysis with confidence scores", params: ["id"] },
    ],
  },
  {
    category: "Claims",
    tag: "claims",
    endpoints: [
      { method: "POST" as HttpMethod, path: "/api/claims/batch", desc: "Submit a batch of claims for RAF analysis", params: [] },
      { method: "GET" as HttpMethod, path: "/api/claims/batch/{job_id}", desc: "Poll batch processing status and results", params: ["job_id"] },
    ],
  },
  {
    category: "FHIR",
    tag: "fhir",
    endpoints: [
      { method: "GET" as HttpMethod, path: "/api/fhir/connections", desc: "List FHIR EHR connections and their sync status", params: [] },
      { method: "POST" as HttpMethod, path: "/api/fhir/sync/{connection_id}", desc: "Trigger a manual FHIR data sync for a connection", params: ["connection_id"] },
    ],
  },
  {
    category: "Submissions",
    tag: "submissions",
    endpoints: [
      { method: "POST" as HttpMethod, path: "/api/submissions/generate", desc: "Generate a CMS-compliant RAF submission file", params: ["plan_id", "submission_year"] },
      { method: "GET" as HttpMethod, path: "/api/submissions/{id}/validate", desc: "Run validation rules against a submission", params: ["id"] },
    ],
  },
  {
    category: "Webhooks",
    tag: "webhooks",
    endpoints: [
      { method: "GET" as HttpMethod, path: "/api/webhooks", desc: "List all configured webhook endpoints", params: [] },
      { method: "POST" as HttpMethod, path: "/api/webhooks", desc: "Register a new webhook endpoint", params: [] },
      { method: "DELETE" as HttpMethod, path: "/api/webhooks/{id}", desc: "Remove a webhook endpoint", params: ["id"] },
      { method: "POST" as HttpMethod, path: "/api/webhooks/{id}/test", desc: "Send a test event to the webhook endpoint", params: ["id"] },
    ],
  },
];

// ---------------------------------------------------------------------------
// Code snippets
// ---------------------------------------------------------------------------

const CODE_SNIPPETS = {
  auth: {
    python: `import requests

# Obtain a JWT token
resp = requests.post(
    "https://api.raf-intelligence.io/api/auth/login",
    json={"username": "your@email.com", "password": "your_password"}
)
token = resp.json()["access_token"]

# Use in subsequent requests
headers = {"Authorization": f"Bearer {token}"}
`,
    javascript: `const resp = await fetch(
  "https://api.raf-intelligence.io/api/auth/login",
  {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      username: "your@email.com",
      password: "your_password"
    })
  }
);
const { access_token } = await resp.json();

// Use in subsequent requests
const headers = { Authorization: \`Bearer \${access_token}\` };
`,
    curl: `# Get a token
curl -X POST https://api.raf-intelligence.io/api/auth/login \\
  -H "Content-Type: application/json" \\
  -d '{"username":"your@email.com","password":"your_password"}'

# Use the token
export TOKEN="<access_token from response>"
curl -H "Authorization: Bearer $TOKEN" \\
  https://api.raf-intelligence.io/api/patients
`,
  },
  raf: {
    python: `# Calculate RAF score for a patient
resp = requests.post(
    "https://api.raf-intelligence.io/api/patients/P-1001/raf-score",
    headers=headers
)
score = resp.json()
print(f"RAF Score: {score['raf_score']}")
print(f"HCC Count: {len(score['hcc_codes'])}")
`,
    javascript: `// Calculate RAF score for a patient
const resp = await fetch(
  "https://api.raf-intelligence.io/api/patients/P-1001/raf-score",
  { method: "POST", headers }
);
const score = await resp.json();
console.log(\`RAF Score: \${score.raf_score}\`);
`,
    curl: `curl -X POST \\
  https://api.raf-intelligence.io/api/patients/P-1001/raf-score \\
  -H "Authorization: Bearer $TOKEN"
`,
  },
  upload: {
    python: `import os

with open("clinical_note.pdf", "rb") as f:
    resp = requests.post(
        "https://api.raf-intelligence.io/api/documents/upload",
        headers=headers,
        data={"patient_id": "P-1001", "document_type": "clinical_note"},
        files={"file": ("clinical_note.pdf", f, "application/pdf")}
    )
doc = resp.json()
print(f"Document ID: {doc['id']}, Status: {doc['status']}")
`,
    javascript: `const form = new FormData();
form.append("patient_id", "P-1001");
form.append("document_type", "clinical_note");
form.append("file", fileBlob, "clinical_note.pdf");

const resp = await fetch(
  "https://api.raf-intelligence.io/api/documents/upload",
  { method: "POST", headers: { Authorization: headers.Authorization }, body: form }
);
const doc = await resp.json();
`,
    curl: `curl -X POST \\
  https://api.raf-intelligence.io/api/documents/upload \\
  -H "Authorization: Bearer $TOKEN" \\
  -F "patient_id=P-1001" \\
  -F "document_type=clinical_note" \\
  -F "file=@clinical_note.pdf"
`,
  },
  webhook: {
    python: `# Register a webhook endpoint
resp = requests.post(
    "https://api.raf-intelligence.io/api/webhooks",
    headers={**headers, "Content-Type": "application/json"},
    json={
        "url": "https://your-app.com/webhooks/raf",
        "secret": "your_signing_secret",
        "events": ["score.calculated", "suspect.created"]
    }
)
webhook = resp.json()
print(f"Webhook ID: {webhook['id']}")
`,
    javascript: `const resp = await fetch(
  "https://api.raf-intelligence.io/api/webhooks",
  {
    method: "POST",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({
      url: "https://your-app.com/webhooks/raf",
      secret: "your_signing_secret",
      events: ["score.calculated", "suspect.created"]
    })
  }
);
`,
    curl: `curl -X POST \\
  https://api.raf-intelligence.io/api/webhooks \\
  -H "Authorization: Bearer $TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "url": "https://your-app.com/webhooks/raf",
    "secret": "your_signing_secret",
    "events": ["score.calculated", "suspect.created"]
  }'
`,
  },
};

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function formatRelative(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60000) return "just now";
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return `${Math.floor(diff / 86400000)}d ago`;
}

function statusCodeColor(code: number) {
  if (code >= 200 && code < 300) return "text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40 border-emerald-200 dark:border-emerald-800/60";
  if (code >= 400 && code < 500) return "text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40 border-amber-200 dark:border-amber-700/60";
  if (code >= 500) return "text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/40 border-red-200 dark:border-red-800/60";
  return "text-slate-500 bg-slate-100 dark:bg-slate-800 border-slate-200 dark:border-slate-700";
}

function methodColor(method: HttpMethod) {
  const map: Record<HttpMethod, string> = {
    GET: "bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/60",
    POST: "bg-blue-100 dark:bg-blue-950/60 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-800/60",
    PUT: "bg-amber-100 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-700/60",
    PATCH: "bg-orange-100 dark:bg-orange-950/60 text-orange-700 dark:text-orange-300 border-orange-200 dark:border-orange-700/60",
    DELETE: "bg-red-100 dark:bg-red-950/60 text-red-700 dark:text-red-300 border-red-200 dark:border-red-800/60",
  };
  return map[method];
}

// ---------------------------------------------------------------------------
// CopyButton
// ---------------------------------------------------------------------------

function CopyButton({ text, className = "" }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  function copy() {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }
  return (
    <button
      onClick={copy}
      className={`flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors
        border-slate-200 dark:border-slate-700 text-muted-foreground hover:text-foreground hover:bg-slate-50 dark:hover:bg-slate-800 ${className}`}
      aria-label="Copy to clipboard"
    >
      {copied ? <CheckCheck className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}
      {copied ? "Copied!" : "Copy"}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Tab bar
// ---------------------------------------------------------------------------

type Tab = "webhooks" | "docs" | "keys";

function TabBar({ active, onChange }: { active: Tab; onChange: (t: Tab) => void }) {
  const tabs: { id: Tab; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
    { id: "webhooks", label: "Webhooks", icon: Webhook },
    { id: "docs", label: "API Documentation", icon: BookOpen },
    { id: "keys", label: "API Keys", icon: KeyRound },
  ];
  return (
    <div className="flex gap-1 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/50 p-1 w-fit">
      {tabs.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          onClick={() => onChange(id)}
          className={`flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all btn-press ${
            active === id
              ? "bg-white dark:bg-slate-800 text-foreground shadow-md border border-slate-200 dark:border-slate-700"
              : "text-muted-foreground hover:text-foreground hover:bg-white/50 dark:hover:bg-slate-800/50"
          }`}
          aria-current={active === id ? "page" : undefined}
        >
          <Icon className="h-4 w-4" />
          {label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Add Webhook Dialog
// ---------------------------------------------------------------------------

function AddWebhookDialog({
  open,
  onClose,
  onAdd,
  editWebhook,
}: {
  open: boolean;
  onClose: () => void;
  onAdd: (wh: Omit<WebhookEndpoint, "id" | "success_rate" | "last_delivery">) => void;
  editWebhook?: WebhookEndpoint | null;
}) {
  const [url, setUrl] = useState(editWebhook?.url ?? "");
  const [secret, setSecret] = useState(() => editWebhook?.secret ?? generateSecret());
  const [secretVisible, setSecretVisible] = useState(false);
  const [selectedEvents, setSelectedEvents] = useState<Set<string>>(
    new Set(editWebhook?.events ?? [])
  );
  const [urlError, setUrlError] = useState("");

  function validateUrl(val: string) {
    if (!val.startsWith("https://")) {
      setUrlError("URL must start with https://");
    } else {
      setUrlError("");
    }
  }

  function toggleEvent(id: string) {
    setSelectedEvents((prev) => {
      const next = new Set(prev);
      if (next.has(id)) { next.delete(id); } else { next.add(id); }
      return next;
    });
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!url.startsWith("https://")) {
      setUrlError("URL must start with https://");
      return;
    }
    onAdd({
      url,
      secret,
      events: Array.from(selectedEvents),
      status: "active",
    });
    onClose();
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 animate-fade-in">
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      <div className="relative z-10 w-full max-w-xl rounded-2xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-2xl flex flex-col max-h-[90vh] animate-scale-in">
        <div className="flex items-center justify-between px-6 py-5 border-b border-slate-100 dark:border-slate-800 flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-500/10 border border-blue-500/20">
              <Webhook className="h-4 w-4 text-blue-400" />
            </div>
            <h2 className="text-base font-semibold text-foreground">
              {editWebhook ? "Edit Webhook" : "Add Webhook"}
            </h2>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-muted-foreground hover:text-foreground hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            aria-label="Close dialog"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col min-h-0 flex-1">
          <div className="overflow-y-auto flex-1 px-6 py-5 space-y-5">
            {/* URL */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-foreground">
                Endpoint URL <span className="text-red-500">*</span>
              </label>
              <Input
                value={url}
                onChange={(e) => { setUrl(e.target.value); validateUrl(e.target.value); }}
                placeholder="https://your-app.com/webhooks/raf"
                className={`h-10 rounded-xl font-mono text-sm transition-all duration-200 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 ${urlError ? "border-red-400" : ""}`}
                required
              />
              {urlError && (
                <p className="text-xs text-red-500 flex items-center gap-1">
                  <AlertCircle className="h-3.5 w-3.5" />
                  {urlError}
                </p>
              )}
              <p className="text-[11px] text-muted-foreground">Must be HTTPS. We will POST JSON payloads to this URL.</p>
            </div>

            {/* Secret */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-foreground">Signing Secret</label>
              <div className="flex gap-2">
                <div className="relative flex-1">
                  <Input
                    value={secret}
                    readOnly
                    type={secretVisible ? "text" : "password"}
                    className="h-10 rounded-xl pr-10 font-mono text-sm focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 transition-all duration-200"
                  />
                  <button
                    type="button"
                    onClick={() => setSecretVisible((v) => !v)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    aria-label={secretVisible ? "Hide secret" : "Show secret"}
                  >
                    {secretVisible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
                <CopyButton text={secret} />
                <button
                  type="button"
                  onClick={() => setSecret(generateSecret())}
                  className="flex items-center gap-1.5 rounded-xl border border-slate-200 dark:border-slate-700 px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
                  title="Regenerate secret"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  Regen
                </button>
              </div>
              <p className="text-[11px] text-muted-foreground">
                Used to verify webhook payloads via HMAC-SHA256 signature in the <code className="font-mono">X-RAF-Signature</code> header.
              </p>
            </div>

            {/* Events */}
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground">
                Events <span className="text-red-500">*</span>
              </label>
              <p className="text-[11px] text-muted-foreground">Select which events will trigger this webhook.</p>
              <div className="space-y-4 mt-1">
                {EVENT_GROUPS.map((group) => (
                  <div key={group.category}>
                    <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-1.5">
                      {group.category}
                    </p>
                    <div className="space-y-1">
                      {group.events.map((ev) => (
                        <label
                          key={ev.id}
                          className="flex items-start gap-3 rounded-lg p-2.5 hover:bg-slate-50 dark:hover:bg-slate-800/50 cursor-pointer transition-colors"
                        >
                          <input
                            type="checkbox"
                            checked={selectedEvents.has(ev.id)}
                            onChange={() => toggleEvent(ev.id)}
                            className="mt-0.5 h-4 w-4 rounded border-slate-300 accent-blue-600"
                          />
                          <div>
                            <p className="text-sm font-medium font-mono text-foreground">{ev.label}</p>
                            <p className="text-xs text-muted-foreground">{ev.desc}</p>
                          </div>
                        </label>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="flex justify-end gap-3 px-6 py-4 border-t border-slate-100 dark:border-slate-800 flex-shrink-0">
            <Button type="button" variant="outline" onClick={onClose} className="h-10 rounded-xl">
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={!url || selectedEvents.size === 0}
              className="h-10 rounded-xl font-semibold bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-700 hover:to-blue-600 shadow-lg shadow-blue-500/20 btn-press"
            >
              {editWebhook ? "Save Changes" : "Add Webhook"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Delivery History Row
// ---------------------------------------------------------------------------

function DeliveryRow({ delivery }: { delivery: WebhookDelivery }) {
  const [expanded, setExpanded] = useState(false);
  const colorClass = statusCodeColor(delivery.status_code);
  const isTimeout = delivery.response_time_ms >= 5000;

  return (
    <>
      <tr
        className="border-b border-slate-50 dark:border-slate-800/50 hover:bg-slate-50 dark:hover:bg-slate-800/30 cursor-pointer transition-colors"
        onClick={() => setExpanded((v) => !v)}
      >
        <td className="py-2.5 pr-4 font-mono text-xs text-foreground">{delivery.event}</td>
        <td className="py-2.5 pr-4 text-xs text-muted-foreground whitespace-nowrap">
          {formatRelative(delivery.timestamp)}
        </td>
        <td className="py-2.5 pr-4">
          <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-mono font-semibold ${colorClass}`}>
            {isTimeout ? "timeout" : delivery.status_code}
          </span>
        </td>
        <td className="py-2.5 pr-4 text-xs text-muted-foreground tabular-nums">
          {isTimeout ? "5000+ ms" : `${delivery.response_time_ms} ms`}
        </td>
        <td className="py-2.5 pr-4 text-xs text-muted-foreground tabular-nums">{delivery.attempts}</td>
        <td className="py-2.5 text-right">
          {expanded ? <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" /> : <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />}
        </td>
      </tr>
      {expanded && (delivery.request_payload || delivery.response_body) && (
        <tr className="bg-slate-50 dark:bg-slate-900/50">
          <td colSpan={6} className="px-4 pb-3 pt-0">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mt-2">
              {delivery.request_payload && (
                <div>
                  <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Request Payload</p>
                  <pre className="text-xs font-mono bg-slate-900 text-slate-100 rounded-xl p-3 overflow-x-auto">
                    {JSON.stringify((() => { try { return JSON.parse(delivery.request_payload); } catch { return delivery.request_payload; } })(), null, 2)}
                  </pre>
                </div>
              )}
              {delivery.response_body && (
                <div>
                  <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Response Body</p>
                  <pre className="text-xs font-mono bg-slate-900 text-slate-100 rounded-xl p-3 overflow-x-auto">
                    {JSON.stringify((() => { try { return JSON.parse(delivery.response_body); } catch { return delivery.response_body; } })(), null, 2)}
                  </pre>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Webhook Row
// ---------------------------------------------------------------------------

function WebhookRow({
  webhook,
  onTest,
  onEdit,
  onToggle,
  onDelete,
}: {
  webhook: WebhookEndpoint;
  onTest: (id: string) => void;
  onEdit: (wh: WebhookEndpoint) => void;
  onToggle: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  const [deliveriesOpen, setDeliveriesOpen] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);
  const [testing, setTesting] = useState(false);

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const start = Date.now();
      await api.post(`/api/webhooks/${webhook.id}/test`);
      setTestResult({ status_code: 200, response_time_ms: Date.now() - start, success: true });
    } catch (err: unknown) {
      const code = (err as { response?: { status?: number } })?.response?.status ?? 0;
      setTestResult({
        status_code: code,
        response_time_ms: 0,
        success: false,
        error: code === 0 ? "Connection refused or timeout" : `HTTP ${code}`,
      });
    } finally {
      setTesting(false);
      onTest(webhook.id);
    }
  }

  const successRateColor =
    webhook.success_rate >= 95
      ? "text-emerald-600 dark:text-emerald-400"
      : webhook.success_rate >= 80
      ? "text-amber-600 dark:text-amber-400"
      : "text-red-600 dark:text-red-400";

  return (
    <>
      <tr className="border-b border-slate-100 dark:border-slate-800/50 hover:bg-blue-50/40 dark:hover:bg-slate-800/30 transition-colors duration-150 odd:bg-slate-50/30">
        {/* URL */}
        <td className="py-3.5 pr-4 max-w-[220px]">
          <p className="font-mono text-xs text-foreground truncate" title={webhook.url}>
            {webhook.url}
          </p>
          {testResult && (
            <div className={`flex items-center gap-1.5 mt-1 text-xs ${testResult.success ? "text-emerald-600" : "text-red-500"}`}>
              {testResult.success ? <CheckCircle2 className="h-3 w-3" /> : <AlertCircle className="h-3 w-3" />}
              {testResult.success
                ? `${testResult.status_code} — ${testResult.response_time_ms}ms`
                : testResult.error}
            </div>
          )}
        </td>
        {/* Events */}
        <td className="py-3.5 pr-4">
          <span className="inline-flex items-center rounded-full bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-800/60 px-2 py-0.5 text-xs font-semibold text-blue-600 dark:text-blue-400">
            {webhook.events.length} event{webhook.events.length !== 1 ? "s" : ""}
          </span>
        </td>
        {/* Status */}
        <td className="py-3.5 pr-4">
          <span
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold border ${
              webhook.status === "active"
                ? "bg-emerald-50 dark:bg-emerald-950/40 border-emerald-200 dark:border-emerald-800/60 text-emerald-600 dark:text-emerald-400"
                : "bg-slate-100 dark:bg-slate-800 border-slate-200 dark:border-slate-700 text-slate-500"
            }`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${webhook.status === "active" ? "bg-emerald-500" : "bg-slate-400"}`} />
            {webhook.status}
          </span>
        </td>
        {/* Last delivery */}
        <td className="py-3.5 pr-4 text-xs text-muted-foreground whitespace-nowrap">
          {webhook.last_delivery ? formatRelative(webhook.last_delivery) : "—"}
        </td>
        {/* Success rate */}
        <td className={`py-3.5 pr-4 text-xs font-semibold tabular-nums ${successRateColor}`}>
          {(webhook.success_rate ?? 0).toFixed(1)}%
        </td>
        {/* Actions */}
        <td className="py-3.5">
          <div className="flex items-center gap-1">
            <button
              onClick={handleTest}
              disabled={testing}
              title="Send test event"
              className="flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-xs font-medium text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-950/40 border border-transparent hover:border-blue-200 dark:hover:border-blue-800/60 transition-all disabled:opacity-50 btn-press"
            >
              {testing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
              Test
            </button>
            <button
              onClick={() => onEdit(webhook)}
              title="Edit webhook"
              className="rounded-lg p-1.5 text-muted-foreground hover:text-foreground hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            >
              <Pencil className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={() => onToggle(webhook.id)}
              title={webhook.status === "active" ? "Disable" : "Enable"}
              className="rounded-lg p-1.5 text-muted-foreground hover:text-foreground hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            >
              {webhook.status === "active" ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            </button>
            <button
              onClick={() => onDelete(webhook.id)}
              title="Delete webhook"
              className="rounded-lg p-1.5 text-muted-foreground hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40 transition-colors"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={() => setDeliveriesOpen((v) => !v)}
              title="View delivery history"
              className="rounded-lg p-1.5 text-muted-foreground hover:text-foreground hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            >
              {deliveriesOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </button>
          </div>
        </td>
      </tr>
      {/* Delivery history sub-table */}
      {deliveriesOpen && (
        <tr>
          <td colSpan={6} className="p-0">
            <div className="bg-slate-50 dark:bg-slate-900/60 border-b border-slate-100 dark:border-slate-800 px-4 pb-4 pt-3">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                Recent Deliveries
              </p>
              {webhook.deliveries && webhook.deliveries.length > 0 ? (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b-2 border-slate-200 dark:border-slate-700">
                      {["Event", "When", "Status", "Response Time", "Attempts", ""].map((h) => (
                        <th key={h} className="text-left text-[11px] font-bold uppercase tracking-wider text-muted-foreground pb-2 pr-4">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {webhook.deliveries.map((d) => (
                      <DeliveryRow key={d.id} delivery={d} />
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="text-xs text-muted-foreground py-2">No delivery history available.</p>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Webhooks Tab
// ---------------------------------------------------------------------------

function WebhooksTab() {
  const [webhooks, setWebhooks] = useState<WebhookEndpoint[]>([]);
  const [, setIsLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<WebhookEndpoint | null>(null);

  // Fetch webhooks from API on mount
  const loadWebhooks = useCallback(async () => {
    setIsLoading(true);
    try {
      const { data } = await api.get("/api/webhooks");
      const mapped = (Array.isArray(data) ? data : data?.webhooks ?? []).map((wh: Record<string, unknown>) => ({
        id: wh.id?.toString() ?? `wh_${Date.now()}`,
        url: wh.url ?? wh.endpoint_url ?? "",
        secret: wh.secret ?? wh.signing_secret ?? "",
        events: wh.events ?? [],
        status: wh.is_active === false ? "inactive" as const : "active" as const,
        last_delivery: wh.last_triggered_at ?? wh.last_delivery,
        success_rate: wh.success_rate ?? 100,
        deliveries: wh.deliveries ?? [],
      }));
      setWebhooks(mapped);
    } catch {
      // API not available — start with empty state
      setWebhooks([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => { loadWebhooks(); }, [loadWebhooks]);

  const activeCount = webhooks.filter((w) => w.status === "active").length;
  const totalDeliveries = webhooks.reduce(
    (sum, w) => sum + (w.deliveries?.length ?? 0), 0
  );
  const failedDeliveries = webhooks.reduce(
    (sum, w) => sum + (w.deliveries?.filter((d) => d.status_code >= 400).length ?? 0), 0
  );
  const allDeliveries = webhooks.flatMap((w) => w.deliveries ?? []);
  const avgResponseTime = allDeliveries.length > 0
    ? `${Math.round(allDeliveries.reduce((s, d) => s + d.response_time_ms, 0) / allDeliveries.length)} ms`
    : "— ms";

  function handleAdd(data: Omit<WebhookEndpoint, "id" | "success_rate" | "last_delivery">) {
    if (editTarget) {
      setWebhooks((prev) =>
        prev.map((w) => (w.id === editTarget.id ? { ...editTarget, ...data } : w))
      );
      setEditTarget(null);
    } else {
      setWebhooks((prev) => [
        ...prev,
        { ...data, id: `wh_${Date.now()}`, success_rate: 100 },
      ]);
    }
  }

  function handleToggle(id: string) {
    setWebhooks((prev) =>
      prev.map((w) =>
        w.id === id ? { ...w, status: w.status === "active" ? "inactive" : "active" } : w
      )
    );
  }

  function handleDelete(id: string) {
    setWebhooks((prev) => prev.filter((w) => w.id !== id));
  }

  function handleEdit(wh: WebhookEndpoint) {
    setEditTarget(wh);
    setDialogOpen(true);
  }

  return (
    <div className="space-y-6">
      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="animate-fade-in stagger-1 hover-lift">
          <StatCard label="Active Webhooks" value={activeCount} icon={<Webhook size={18} />} />
        </div>
        <div className="animate-fade-in stagger-2 hover-lift">
          <StatCard label="Events Delivered (24h)" value={totalDeliveries.toLocaleString()} icon={<Zap size={18} />} />
        </div>
        <div className="animate-fade-in stagger-3 hover-lift">
          <StatCard label="Failed Deliveries" value={failedDeliveries} icon={<AlertTriangle size={18} />} color="#DC2626" />
        </div>
        <div className="animate-fade-in stagger-4 hover-lift">
          <StatCard label="Avg Response Time" value={avgResponseTime} icon={<Clock size={18} />} />
        </div>
      </div>

      {/* Table card */}
      <div className="premium-card rounded-2xl bg-white dark:bg-slate-900/50 overflow-hidden animate-fade-in stagger-5">
        <div className="flex items-center justify-between px-6 py-5 border-b border-slate-100 dark:border-slate-800">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-500/10 border border-blue-500/20">
              <Webhook className="h-4 w-4 text-blue-400" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-foreground">Webhook Endpoints</h2>
              <p className="text-xs text-muted-foreground mt-0.5">
                {webhooks.length} endpoint{webhooks.length !== 1 ? "s" : ""} configured
              </p>
            </div>
          </div>
          <Button
            onClick={() => { setEditTarget(null); setDialogOpen(true); }}
            className="h-9 rounded-xl text-sm font-semibold bg-gradient-to-r from-blue-600 to-blue-500 hover:from-blue-700 hover:to-blue-600 shadow-lg shadow-blue-500/20 btn-press"
          >
            <Plus className="mr-2 h-4 w-4" />
            Add Webhook
          </Button>
        </div>

        {webhooks.length === 0 ? (
          <div className="flex flex-col items-center py-16 gap-3 text-center px-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-100 dark:bg-slate-800 border border-slate-200 dark:border-slate-700">
              <Webhook className="h-6 w-6 text-muted-foreground" />
            </div>
            <p className="text-sm font-semibold text-foreground">No webhooks configured</p>
            <p className="text-xs text-muted-foreground max-w-xs">
              Add a webhook endpoint to receive real-time events when RAF scores change or new suspects are identified.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b-2 border-slate-200 dark:border-slate-700 bg-gradient-to-r from-slate-50 to-slate-100 dark:from-slate-900 dark:to-slate-800/80">
                  {["URL", "Events", "Status", "Last Delivery", "Success Rate", "Actions"].map((h) => (
                    <th key={h} className="text-left text-[11px] font-bold uppercase tracking-wider text-muted-foreground px-4 py-3.5 first:pl-6 last:pr-6">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {webhooks.map((wh) => (
                  <WebhookRow
                    key={wh.id}
                    webhook={wh}
                    onTest={() => {}}
                    onEdit={handleEdit}
                    onToggle={handleToggle}
                    onDelete={handleDelete}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <AddWebhookDialog
        open={dialogOpen}
        onClose={() => { setDialogOpen(false); setEditTarget(null); }}
        onAdd={handleAdd}
        editWebhook={editTarget}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// API endpoint expandable row
// ---------------------------------------------------------------------------

function EndpointRow({ method, path, desc, params }: {
  method: HttpMethod;
  path: string;
  desc: string;
  params: string[];
}) {
  const [open, setOpen] = useState(false);
  const slug = path.replace(/\//g, "-").replace(/[{}]/g, "").replace(/^-/, "");

  return (
    <div className="border-b border-slate-100 dark:border-slate-800 last:border-0">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-5 py-3.5 hover:bg-blue-50/40 dark:hover:bg-slate-800/40 transition-colors duration-150 text-left"
      >
        <span className={`shrink-0 inline-flex items-center rounded border px-2 py-0.5 text-[11px] font-bold font-mono w-[56px] justify-center ${methodColor(method)}`}>
          {method}
        </span>
        <span className="flex-1 font-mono text-sm text-foreground">{path}</span>
        <span className="text-xs text-muted-foreground hidden md:block mr-4">{desc}</span>
        {open ? <ChevronUp className="h-4 w-4 text-muted-foreground shrink-0" /> : <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />}
      </button>
      {open && (
        <div className="bg-slate-50 dark:bg-slate-900/60 px-5 pb-4 pt-1 space-y-3">
          <p className="text-sm text-muted-foreground">{desc}</p>
          {params.length > 0 && (
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground mb-2">Parameters</p>
              <div className="flex flex-wrap gap-2">
                {params.map((p) => (
                  <code key={p} className="rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2.5 py-1 text-xs font-mono text-foreground">
                    {p}
                  </code>
                ))}
              </div>
            </div>
          )}
          <div className="flex gap-2 pt-1">
            <a
              href={`/docs#/${slug}`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1.5 rounded-lg border border-blue-200 dark:border-blue-800/60 bg-blue-50 dark:bg-blue-950/40 px-3 py-1.5 text-xs font-medium text-blue-600 dark:text-blue-400 hover:bg-blue-100 dark:hover:bg-blue-950/60 transition-colors btn-press"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              Try it in Swagger
            </a>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Code snippet block with language toggle
// ---------------------------------------------------------------------------

type Lang = "python" | "javascript" | "curl";

function CodeBlock({
  title,
  snippets,
}: {
  title: string;
  snippets: Record<Lang, string>;
}) {
  const [lang, setLang] = useState<Lang>("python");
  const langs: Lang[] = ["python", "javascript", "curl"];
  const langLabels: Record<Lang, string> = { python: "Python", javascript: "JavaScript", curl: "cURL" };

  return (
    <div className="rounded-xl border border-slate-200 dark:border-slate-800 overflow-hidden hover-lift transition-all duration-200">
      <div className="flex items-center justify-between px-4 py-2.5 bg-gradient-to-r from-slate-100 to-slate-50 dark:from-slate-800 dark:to-slate-800/80 border-b border-slate-200 dark:border-slate-700">
        <div className="flex items-center gap-2">
          <Terminal className="h-3.5 w-3.5 text-muted-foreground" />
          <span className="text-xs font-semibold text-foreground">{title}</span>
        </div>
        <div className="flex items-center gap-1">
          {langs.map((l) => (
            <button
              key={l}
              onClick={() => setLang(l)}
              className={`rounded px-2 py-0.5 text-xs font-medium transition-colors ${
                lang === l
                  ? "bg-white dark:bg-slate-700 text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {langLabels[l]}
            </button>
          ))}
          <CopyButton text={snippets[lang]} className="ml-2" />
        </div>
      </div>
      <pre className="bg-slate-900 text-slate-100 text-xs font-mono p-4 overflow-x-auto leading-relaxed">
        {snippets[lang]}
      </pre>
    </div>
  );
}

// ---------------------------------------------------------------------------
// API Documentation Tab
// ---------------------------------------------------------------------------

function DocsTab() {
  return (
    <div className="space-y-8">
      {/* Quick start */}
      <div className="premium-card rounded-2xl bg-white dark:bg-slate-900/50 overflow-hidden animate-fade-in stagger-1">
        <div className="px-6 py-5 border-b border-slate-100 dark:border-slate-800 flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-500/10 border border-blue-500/20">
            <Zap className="h-4 w-4 text-blue-400" />
          </div>
          <div>
            <h2 className="text-sm font-semibold text-foreground">Quick Start</h2>
            <p className="text-xs text-muted-foreground mt-0.5">Authentication and common operations</p>
          </div>
        </div>
        <div className="px-6 py-5 space-y-5">
          <div className="flex items-start gap-3 rounded-xl border border-blue-200 dark:border-blue-800/60 bg-blue-50 dark:bg-blue-950/30 p-4">
            <ShieldCheck className="h-4 w-4 text-blue-500 dark:text-blue-400 shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-medium text-blue-700 dark:text-blue-300">JWT Bearer Authentication</p>
              <p className="text-xs text-blue-600/80 dark:text-blue-400/70 mt-0.5">
                All API endpoints require a valid JWT token obtained from <code className="font-mono bg-blue-100 dark:bg-blue-900/60 px-1 rounded">/api/auth/login</code>. Tokens expire after 24 hours.
              </p>
            </div>
          </div>
          <CodeBlock title="1. Authentication" snippets={CODE_SNIPPETS.auth} />
          <CodeBlock title="2. Calculate RAF Score for a Patient" snippets={CODE_SNIPPETS.raf} />
          <CodeBlock title="3. Upload a Document for Analysis" snippets={CODE_SNIPPETS.upload} />
          <CodeBlock title="4. Subscribe to Webhook Events" snippets={CODE_SNIPPETS.webhook} />
        </div>
      </div>

      {/* Endpoint reference */}
      <div className="premium-card rounded-2xl bg-white dark:bg-slate-900/50 overflow-hidden animate-fade-in stagger-3">
        <div className="px-6 py-5 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-500/10 border border-blue-500/20">
              <BookOpen className="h-4 w-4 text-blue-400" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-foreground">API Reference</h2>
              <p className="text-xs text-muted-foreground mt-0.5">All available endpoints grouped by category</p>
            </div>
          </div>
          <a
            href="/docs"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 rounded-xl border border-slate-200 dark:border-slate-700 px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            Open Swagger UI
          </a>
        </div>

        <div className="divide-y divide-slate-100 dark:divide-slate-800">
          {API_CATEGORIES.map((cat) => (
            <div key={cat.category}>
              <div className="flex items-center gap-2 px-5 py-3 bg-slate-50 dark:bg-slate-900/60">
                <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground">{cat.category}</span>
                <span className="rounded-full bg-slate-200 dark:bg-slate-700 px-1.5 py-0.5 text-[10px] font-semibold text-muted-foreground">
                  {cat.endpoints.length}
                </span>
              </div>
              {cat.endpoints.map((ep) => (
                <EndpointRow key={`${ep.method}${ep.path}`} {...ep} />
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// API Keys Tab (placeholder)
// ---------------------------------------------------------------------------

function KeysTab() {
  const [keys, setKeys] = useState([
    { id: "1", name: "Production Internal Sync", prefix: "raf_live_9f8d", created: new Date(Date.now() - 86400000 * 90).toISOString().slice(0, 10), lastUsed: "2 mins ago" },
    { id: "2", name: "CI/CD Pipeline Analysis", prefix: "raf_test_1c2b", created: new Date(Date.now() - 86400000 * 7).toISOString().slice(0, 10), lastUsed: "Yesterday" }
  ]);
  const [showGenerate, setShowGenerate] = useState(false);
  const [newKeyName, setNewKeyName] = useState("");

  const handleGenerate = () => {
    if (!newKeyName.trim()) return;
    const prefix = `raf_${Math.random().toString(36).substring(2, 6)}_${Math.random().toString(36).substring(2, 6)}`;
    setKeys([{ id: Date.now().toString(), name: newKeyName, prefix, created: "Just now", lastUsed: "Never" }, ...keys]);
    setNewKeyName("");
    setShowGenerate(false);
  };

  const handleRevoke = (id: string) => {
    setKeys(keys.filter(k => k.id !== id));
  };

  return (
    <div className="space-y-6">
      <div className="premium-card rounded-2xl bg-white dark:bg-slate-900/50 overflow-hidden animate-fade-in stagger-1">
        <div className="px-6 py-5 border-b border-slate-100 dark:border-slate-800 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-blue-500/10 border border-blue-500/20">
              <KeyRound className="h-4 w-4 text-blue-400" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-foreground">API Keys</h2>
              <p className="text-xs text-muted-foreground mt-0.5">Manage token integration lifecycle natively</p>
            </div>
          </div>
          <button onClick={() => setShowGenerate(!showGenerate)} className="flex items-center gap-2 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded-lg">
            Generate New Key
          </button>
        </div>

        {showGenerate && (
          <div className="px-6 py-4 bg-slate-50 dark:bg-slate-900/40 border-b border-slate-100 dark:border-slate-800 flex gap-3">
            <input 
              type="text" 
              value={newKeyName}
              onChange={(e) => setNewKeyName(e.target.value)}
              placeholder="e.g. Jenkins Runner" 
              className="px-3 py-1.5 text-sm rounded border border-slate-200"
            />
            <button onClick={handleGenerate} className="px-3 py-1.5 bg-emerald-600 text-white text-xs font-semibold rounded">
              Create
            </button>
          </div>
        )}

        <div className="px-6 py-4">
          {keys.map(k => (
            <div key={k.id} className="flex justify-between items-center py-2 border-b border-slate-100 last:border-0">
              <div className="flex flex-col">
                <span className="font-semibold text-sm">{k.name}</span>
                <span className="text-xs text-slate-500 font-mono mt-1">{k.prefix}...</span>
              </div>
              <button onClick={() => handleRevoke(k.id)} className="text-red-500 text-xs font-semibold hover:underline">
                Revoke
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DeveloperPage() {
  const [tab, setTab] = useState<Tab>("webhooks");

  return (
    <div className="max-w-5xl space-y-6 animate-fade-in">
      <PageHeader
        title="Developer Settings"
        subtitle="Manage webhooks, explore the API, and configure integrations"
        icon={<Code size={20} />}
      />

      <div className="animate-fade-in stagger-1">
        <TabBar active={tab} onChange={setTab} />
      </div>

      <div className="animate-fade-in stagger-2">
        {tab === "webhooks" && <WebhooksTab />}
        {tab === "docs" && <DocsTab />}
        {tab === "keys" && <KeysTab />}
      </div>
    </div>
  );
}
