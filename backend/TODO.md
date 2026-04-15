# Technical TODO Tracker

This file tracks all TODO comments found in production code as of 2026-04-14.
Do not remove TODOs from source files; resolve them via tickets and mark as done here.

---

## Open TODOs

### backend/app/routers/meat.py — line 132
**Context:** MEAT batch processing is done synchronously in-request.
**TODO:** Replace this with an async Celery / cron batch job so the endpoint
is not blocked during heavy MEAT validation runs.
**Priority:** Medium
**Owner:** unassigned

---

### backend/app/routers/data_quality.py — line 22 (module docstring)
**Context:** Data quality router is a work-in-progress.
**TODO:** (Module-level TODO — see full file header for details)
**Priority:** Medium
**Owner:** unassigned

### backend/app/routers/data_quality.py — line 153
**Context:** `run_data_quality_check` returns rows but does not persist them.
**TODO:** Also persist the returned rows into a `data_quality_reports` table
so results are queryable over time and can surface in the BI export.
**Priority:** Low
**Owner:** unassigned

---

### backend/app/db.py — line 645 / 652
**Context:** Database abstraction currently only supports MySQL/MariaDB.
**TODO (multi-db):** Add psycopg2 (or psycopg3) support for PostgreSQL tenants.
**Priority:** Low (roadmap item)
**Owner:** unassigned

### backend/app/db.py — line 726
**Context:** `check_connections()` has no PostgreSQL connectivity test.
**TODO (multi-db):** Implement psycopg2-based connectivity test for PostgreSQL.
**Priority:** Low (depends on multi-db above)
**Owner:** unassigned

---

### backend/app/services/meat_validator.py — line 29
**Context:** MEAT validation uses keyword/rule-based matching.
**TODO:** Upgrade to an ML / LLM approach for higher accuracy and recall,
especially for complex clinical notes.
**Priority:** Medium (roadmap item)
**Owner:** unassigned

---

### backend/app/services/raf/calculator.py — line 170
**Context:** PY2026 Final Rule coefficients are not yet published by CMS.
**TODO:** Replace placeholder coefficients with official CMS values when the
PY2026 Final Rule is published.
**Priority:** High — must be done before PY2026 go-live
**Owner:** unassigned

---

## Resolved TODOs

_(Move entries here when the underlying issue is addressed and the TODO is removed from source.)_
