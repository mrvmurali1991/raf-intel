# RAF Recompute Inbox

## Overview

Previously, every pipeline run that touched patient data — EMR sync, encounter analysis, suspect decisions — triggered a synchronous `calculate_raf_score` call inline. This caused two problems: operators had to click "Calculate RAF" manually after certain workflows, and batch operations (syncing 50 patients at once) would fire 50 sequential recalculations, blocking the pipeline.

The inbox replaces that pattern with a dirty-marker queue. Any code path that changes data affecting a RAF score writes a row to `raf_recompute_pending` instead of calling the scorer directly. A Celery Beat worker drains that queue every 15 seconds, deduplicating entries so a patient that was marked dirty five times only gets recalculated once per drain cycle. The feature is guarded by `RAF_INBOX_ENABLED`; set it to `false` to fall back to the old synchronous path.

## Architecture

```
Mutation source
  (EMR sync, encounter analysis,
   suspect accept/dismiss,
   pipeline_chain handlers,
   admin manual endpoint)
        |
        v
  mark_dirty() / mark_many_dirty()
  [backend/app/services/raf_inbox.py]
        |
        v
  raf_recompute_pending table
  [alembic migration 018]
        |
        v
  drain_raf_inbox (Celery Beat, every 15s)
  [task: raf.drain_raf_inbox]
        |
        v
  calculate_raf_score()
        |
        +---> raf_scores (DB write)
        |
        +---> SSE publish: raf_updated event
                |
                v
          Frontend NotificationCenter
          invalidates React Query caches
```

## Call sites that mark patients dirty

- `backend/app/services/emr_sync.py` (and normalization helpers) — `reason="sync"`
- `backend/app/api/encounters.py`, per-encounter analysis endpoint — `reason="analysis"`
- `backend/app/tasks/encounter_tasks.py`, batch encounter analysis — `reason="analysis"`
- `backend/app/api/suspects.py`, accept and dismiss handlers — `reason="suspect"`
- `backend/app/tasks/pipeline_chain.py`, `normalization_completed` handler — `reason="sync"`
- `backend/app/tasks/pipeline_chain.py`, `analysis_completed` handler — `reason="analysis"`
- `POST /api/admin/raf-inbox/mark-dirty` admin endpoint — `reason="manual"`

## Operating

**Check inbox depth**

```bash
curl -s -H "Authorization: Bearer <token>" \
  https://<host>/api/admin/raf-inbox/status | jq .
```

Response fields: `pending`, `processing`, `done`, `failed`, `oldest_pending_age_seconds`.

**Requeue failed rows**

```bash
curl -s -X POST -H "Authorization: Bearer <token>" \
  https://<host>/api/admin/raf-inbox/requeue | jq .
```

Moves all `failed` rows back to `pending`. The worker will pick them up on the next drain cycle.

**Verify the worker is running**

```bash
docker logs raf-worker 2>&1 | grep drain_raf_inbox | tail -20
```

You should see periodic `Task raf.drain_raf_inbox succeeded` lines spaced roughly 15 seconds apart.

**Watch a drain happen live**

```bash
docker logs -f raf-worker 2>&1 | grep -E "drain_raf_inbox|raf_score"
```

## Rollback

If you need to disable the inbox and revert to synchronous in-process recalculation:

1. Open the Docker Compose file at `/home/ubuntu/raf-intelligence/docker-compose.yml` (or the relevant `.env` file that sets environment variables for the `backend` and `worker` services).

2. Set `RAF_INBOX_ENABLED=false` for both the `backend` and `worker` services.

3. Restart both services:

   ```bash
   docker compose restart backend worker
   ```

4. With `RAF_INBOX_ENABLED=false`, `pipeline_chain.py` skips writing to `raf_recompute_pending` and instead calls `calculate_raf_for_all_patients()` synchronously before completing. The `raf_recompute_pending` table is left in place but no new rows are written.

Note: any rows already in the table will not be processed while the flag is false. If you re-enable later, the worker will drain whatever is still pending.

## Tuning

**Beat frequency** — default is 15 seconds. Change the `beat_schedule` entry for `drain-raf-inbox` in `backend/app/celery_app.py` (the `schedule` value is in seconds).

**Per-drain row cap** — the worker claims at most 200 rows per cycle. Change the `limit` argument to `claim_next()` in the drain task at `backend/app/tasks/raf_tasks.py`.

**Done row retention** — there is no retention sweep. Rows with `status='done'` accumulate indefinitely. If the table grows large, truncate manually or add a scheduled DELETE. This is a known gap with no automated solution yet.

## Known limitations

**Stuck processing rows** — if the worker crashes mid-calculation, the affected row stays in `status='processing'` forever. There is no auto-reaper. To recover manually:

```sql
UPDATE raf_recompute_pending
SET status = 'pending', claimed_at = NULL
WHERE status = 'processing'
  AND claimed_at < NOW() - INTERVAL 10 MINUTE;
```

Run this in a psql session or via the admin SQL interface. The worker will then pick up the row on the next drain cycle.

**Done rows never purged** — see Tuning above. Monitor table size if you run high-volume syncs.

**SSE delivery is best-effort** — `raf_updated` events are only delivered to browser sessions that are connected at the moment the score is written. A user who is not connected will not see a live notification. They will see the updated RAF score on their next page load, which re-fetches from the database.
