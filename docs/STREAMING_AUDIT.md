# LLM Streaming Audit — RAF Intelligence

**Date:** 2026-05-16
**Branch:** `fix/post-review-batch-10`
**Reviewer:** AI-UX post-review batch 10
**Question:** Do any LLM-driven endpoints return a full response after a 30s spinner, when they could stream token-by-token (2026 clinical AI standard)?

## TL;DR

**No conversion performed. No applicable endpoint.** RAF Intelligence has no
user-facing chat/completion endpoint. All Gemini (Vertex AI) calls live inside
batch pipelines that:

1. Run server-side as Celery / `BackgroundTasks` jobs (already non-blocking).
2. Produce **structured JSON** that is schema-validated *atomically* before
   anything is returned (`output_schema` path in
   `backend/app/services/llm/vertex_client.py:547`).
3. Are consumed by the frontend via **job-ID polling** (`/analysis/jobs/{job_id}`),
   not by reading a request body.

Token streaming would provide zero UX benefit and would *break* the schema
validation/retry contract that keeps clinical extraction safe.

## LLM endpoint inventory

| Caller | File | Returns to frontend? | Streamable? |
|---|---|---|---|
| `llm_generate` (text + schema) | `backend/app/services/llm/vertex_client.py:455` | No — internal | n/a |
| `llm_generate_content` (raw payload) | `backend/app/services/llm/vertex_client.py:340` | No — internal | n/a |
| Document analysis | `backend/app/services/document_service.py:545` | Indirect via job poll | No (JSON contract) |
| AI suspect pipeline | `backend/app/services/ai_pipeline/suspect_engine.py` | Indirect via job poll | No (JSON contract) |
| MEAT evidence extractor | `backend/app/services/ai_pipeline/meat_extractor.py` | Indirect via job poll | No (JSON contract) |
| Provider-query / extractor | `backend/app/services/ai_pipeline/extractor.py` | Indirect via job poll | No (JSON contract) |
| Skill pipeline | `backend/app/services/skill_pipeline.py` | Indirect via job poll | No (JSON contract) |
| Health ping | `backend/app/routers/health.py:743` | Yes (smoke test only) | Not worth wiring |

### Routers that *do* return analysis to the user

- `POST /analysis/encounter/{id}` → `backend/app/routers/analysis.py:226`
  → enqueues Celery job, returns `{ job_id }`.
- `POST /analysis/note` → `backend/app/routers/analysis.py:549` → same pattern.
- `POST /documents/{id}/analyze` → `backend/app/routers/documents.py:791` →
  `BackgroundTasks` + polling at `GET /documents/{id}/analysis`.

All three are **already** async-via-jobs. The frontend (`frontend/src/app/analysis/page.tsx:380`)
calls `analyzeNote` / `analyzeEncounter` and shows the result in one shot when
the job completes — there is no spinner-on-LLM situation to optimise.

## Why token streaming would be wrong here

1. **JSON-only outputs.** Every pipeline call passes `output_schema=` to
   `llm_generate`, which validates the *complete* document and silently retries
   with a strict-JSON reminder on parse failure (vertex_client.py:547-585).
   Streaming partial tokens would either (a) require speculative parsing of
   half-formed JSON, or (b) buffer everything anyway — defeating the point.
2. **PHI guardrails are post-hoc.** `sanitize_note_for_llm` and
   `validate_llm_output` run on the full string. Streaming partial tokens to
   the browser would leak PHI past the validator.
3. **Background-job architecture already exists.** Job IDs + polling give the
   user a deterministic progress signal (`status: queued|running|complete`)
   without the SSE/keep-alive complexity. This is the right abstraction for
   30-90s batch extraction; SSE is the right abstraction for chat.
4. **BAA constraint.** The only sanctioned transport is
   `aiplatform.googleapis.com:generateContent`. Switching to
   `:streamGenerateContent` is supported but adds reconnection/audit complexity
   for a code path with no user-visible benefit.

## Where progress UX *could* be improved (separate work)

These are long-running endpoints whose users do see a spinner. They would
benefit from **progress events** (SSE or websocket), not token streaming:

| Endpoint | Typical duration | Suggested upgrade |
|---|---|---|
| `POST /raf/recalc` (batch RAF score) | 10-60s | SSE `event: progress` with `{patients_done, total}` |
| `POST /openemr/sync` (FHIR pull) | 5-120s | SSE `event: patient` per record (already partially done via the auto-sync toast) |
| `POST /analysis/batch/{pid}` | 30-180s per encounter | SSE `event: encounter` with per-encounter status |
| `POST /documents/{id}/analyze` | 5-30s | Progress phase (`uploading → parsing → llm → validating → done`) over SSE |

The auto-sync flow on `frontend/src/components/dashboards/AdminDashboard.tsx`
already uses SSE successfully (`/openemr/sync/stream`) — that's the template
to extend to the four endpoints above.

## Decision

**No code change in this branch.** The audit doc above is the deliverable.
The "AI is thinking…" cursor in the original ask doesn't map to any current
user surface — there is no chat. If a clinical-AI chat surface is added
later, that's the right place to introduce token streaming; the existing
`llm_generate_content` would need a sibling `llm_stream_content` that
proxies `:streamGenerateContent` SSE chunks through a `StreamingResponse`.

## Verification

```bash
$ docker compose -f docker-compose.local.yml exec backend \
    python -c "from app.main import app; print('ok')"
# ok  — no imports added/removed; backend boots clean.
```
