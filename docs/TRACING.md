# Distributed Tracing (OpenTelemetry)

RAF Intelligence emits OpenTelemetry traces from the FastAPI backend. Bootstrap
lives in `backend/app/telemetry.py` and is wired into the app from
`backend/app/main.py` via `init_telemetry(app)` and `instrument_app(app)`.

## Enabling

Tracing is **disabled by default**. To turn it on, set the OTLP endpoint in the
backend environment (typically the project root `.env` consumed by
`app/config.py`):

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
OTEL_SERVICE_NAME=raf-intelligence-backend   # optional, default shown
```

When the variable is empty, both `init_telemetry` and `instrument_app`
short-circuit and return without touching the runtime. In `APP_ENV=development`
without an endpoint, spans are written to the console via `ConsoleSpanExporter`
for local inspection.

## Spans Included

The auto-instrumentation covers:

- **FastAPI routes** — every HTTP request produces a server span tagged with
  route template, method, status code, and (when present) `app.tenant_id` /
  `app.user_id` attributes from `request.state`.
- **Outbound HTTP via `requests`** — every call made through the `requests`
  library (FHIR clients, webhook senders) is captured as a client span.
- **MySQL queries** — every query issued through `mysql-connector-python`
  records a span with the SQL statement template (parameters stripped).
- **Celery tasks** and **Redis** commands — instrumented when those packages
  are installed.

`/health` and `/metrics` are excluded to avoid burying real traffic in
liveness-probe noise (`excluded_urls="health.*,metrics"`).

## Sampling

Default sampler is `parent_based_traceidratio` with ratio `1.0` — i.e. all
traces are sampled. For production set:

```bash
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=0.1   # keep 10% of traces
```

## Viewing Traces

Bring up the observability stack and open Jaeger:

```bash
docker-compose -f docker-compose.observability.yml up -d
open http://localhost:16686
```

Pick service `raf-intelligence-backend` in the Jaeger UI to drill into per-route
latency, downstream MySQL/HTTP fan-out, and error spans.

## PHI Safety

Spans must **never** carry patient names, MRNs, DOBs, or other PHI in their
attributes. The default instrumentations only record request paths, SQL
templates, and HTTP metadata — none of which include PHI in this codebase. When
adding custom spans (`tracer.start_as_current_span(...)`), pass only IDs and
synthetic surrogates; scrub any free-text fields before setting them as
attributes. The existing `server_request_hook` in `telemetry.py` deliberately
records only `app.tenant_id` and `app.user_id`, which are non-PHI internal IDs.
