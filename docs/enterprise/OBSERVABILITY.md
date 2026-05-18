# Observability — Distributed Tracing with OpenTelemetry

## Overview

RAF Intelligence exports OpenTelemetry traces to any OTLP-compatible backend
(Jaeger, Tempo, Honeycomb, Datadog, Dynatrace, etc.).  All instrumentation is
optional and non-blocking: a missing collector or unset endpoint never stalls
startup or degrades the application.

---

## Quick-Start: Local Dev Traces with Jaeger

### 1. Start the observability stack (includes Jaeger)

```bash
docker compose -f docker-compose.observability.yml up -d jaeger
```

Jaeger UI is at http://localhost:16686.

### 2. Configure the backend

Add to your `.env` (or export in the shell):

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318/v1/traces
OTEL_SERVICE_NAME=raf-intelligence-backend
GIT_SHA=$(git rev-parse --short HEAD)
APP_ENV=development
```

Restart the backend:

```bash
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8500 --reload
```

### 3. Generate traffic and view traces

Hit any endpoint, then open http://localhost:16686, select service
`raf-intelligence-backend`, and click **Find Traces**.

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | No | (none) | OTLP HTTP URL, e.g. `http://jaeger:4318/v1/traces` |
| `OTEL_SERVICE_NAME` | No | `raf-intelligence-backend` | Service name in traces |
| `GIT_SHA` | No | `unknown` | Git short SHA, injected by CI at build time |
| `APP_ENV` | No | `production` | Set to `development` for console exporter fallback |

When `OTEL_EXPORTER_OTLP_ENDPOINT` is not set:

- `APP_ENV=development` — spans are printed to stdout via `ConsoleSpanExporter`.
- Production — tracing is a no-op (zero overhead).

---

## Instrumented Libraries

Auto-instrumented at startup:

| Library | Instrumentor |
|---|---|
| FastAPI / ASGI | `opentelemetry-instrumentation-fastapi` |
| httpx (FHIR calls) | `opentelemetry-instrumentation-httpx` |
| MySQL connector | `opentelemetry-instrumentation-mysql` |
| Redis | `opentelemetry-instrumentation-redis` |
| Celery | `opentelemetry-instrumentation-celery` |

---

## Custom High-Leverage Spans

| Span Name | File | Key Attributes |
|---|---|---|
| `accept_suspect` | `services/suspect_engine.py` | `tenant_id`, `patient_id`, `suspect_id`, `source` |
| `extract_hcc_suspects_from_note` | `services/nlp_suspect_extractor.py` | `tenant_id`, `model_name`, `note_length`, `suspects_returned` |
| `push_problem_list_condition` | `services/fhir_problem_list.py` | `tenant_id`, `ehr_base_url`, `circuit_state`, `attempt_number` |
| `compute_extrapolated_exposure` | `services/radv_audit_run_service.py` | `tenant_id`, `sample_size`, `lcb_dollars`, `point_exposure` |

---

## PHI Safety

The helper `_safe_attrs(d)` in `app/telemetry.py` strips keys that contain
PHI tokens (`note_text`, `patient_name`, `mbi`, `dob`, `ssn`, `hicn`, etc.)
before any dict is used as span attributes.  All custom spans use this helper
or set only non-PHI scalar attributes directly.

---

## Observability Status Endpoint

Requires admin role:

```
GET /api/admin/observability/status
Authorization: Bearer <admin-token>
```

Returns:

```json
{
  "tracer_provider": "TracerProvider(service=raf-intelligence-backend, version=abc1234)",
  "exporter": "otlp_http",
  "endpoint_set": true,
  "sample_rate": 1.0
}
```

---

## Production Collector Configuration

Point `OTEL_EXPORTER_OTLP_ENDPOINT` to your collector:

```
# Datadog
OTEL_EXPORTER_OTLP_ENDPOINT=https://trace.agent.datadoghq.com

# Honeycomb
OTEL_EXPORTER_OTLP_ENDPOINT=https://api.honeycomb.io/v1/traces

# Self-hosted OpenTelemetry Collector
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318/v1/traces
```

The exporter uses HTTP/protobuf (port 4318).  It falls back to gRPC (port 4317)
if the HTTP exporter package is absent.

---

## SOC 2 Evidence Notes

- Tracing is enabled per-environment via env var — no code changes needed.
- No PHI flows into spans: `_safe_attrs` enforces this at the helper level.
- The admin status endpoint provides machine-readable evidence that tracing is active.
- Span retention in your collector/backend constitutes the operational log trail
  required for CC7.2 (monitoring of system components).
