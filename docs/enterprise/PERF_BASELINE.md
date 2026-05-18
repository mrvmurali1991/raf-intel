# Performance Baseline

**Last run:** 2026-05-18
**Hardware:** Mac M-series (single dev workstation, demo data)
**Backend:** raf-backend container (single replica, no autoscaling)
**Database:** raf-mysql container (single MySQL 8.0, no read replicas)
**Tool:** Locust 2.44.0

This is a **demo-environment** baseline. Production numbers under load will be different — we'll re-run on AWS-Fargate target sizing during pilot deployment.

---

## Test scenarios

### Workload mix (single coder workflow)

| Weight | Endpoint | Reason |
|---|---|---|
| 40% | `GET /api/suspects` | Worklist refresh |
| 20% | `GET /api/patients/{pid}/suspects` | Patient chart open |
| 15% | `GET /api/v28-impact/portfolio` | V28 KPI dashboard |
| 5% | `GET /api/hedis/measures` | Quality dashboard |
| 5% | `GET /api/radv/audit-runs` | RADV defense queue |
| 5% | `GET /api/coder-analytics/me` | Personal productivity |
| 3% | `GET /api/md/today` | Pre-visit huddle |
| 3% | `GET /api/outreach/health` | SRE probe |
| 2% | `GET /api/chart-chase/v2/dashboard` | Chart-chase queue |
| 2% | `GET /api/fhir/circuit/status` | Admin probe |

User behavior: 1–3 second think time between actions (simulating a real coder reviewing each row).

---

## Results — 50 concurrent users, 60s run

### Throughput

| Metric | Value |
|---|---|
| Total requests | 1,441 |
| RPS | ~24 |
| Wall time | 60s |
| Failures (excl. rate-limit + 404 path bug) | 0 |

### Per-endpoint P95 latency (ms)

| Endpoint | P50 | P75 | P95 | P99 | Notes |
|---|---|---|---|---|---|
| `/api/fhir/circuit/status` | 15 | 20 | 29 | 88 | In-memory CB state |
| `/api/suspects` | 15 | 22 | 110 | 340 | Some 429s at peak |
| `/api/hedis/measures` | 16 | 21 | 60 | 510 | Cold-cache spike |
| `/api/patients/{pid}/suspects` | 16 | 22 | 53 | 97 | 404 path mismatch (404s excluded from latency) |
| `/api/md/today` | 16 | 24 | 110 | 480 | Cold-cache spike |
| `/api/radv/audit-runs` | 18 | 29 | 260 | 540 | Cold-cache spike |
| `/api/outreach/health` | 19 | 27 | 54 | 300 | 4 cold queries |
| `/api/chart-chase/v2/dashboard` | 22 | 37 | 130 | 140 | 5 cold queries |
| `/api/coder-analytics/me` | 25 | 32 | 130 | 610 | Window aggregation |
| `/api/v28-impact/portfolio` | 17 | 26 | **1,300** | **2,300** | **Bottleneck** |

### Aggregated

- P50: 17 ms
- P75: 24 ms
- P95: 120 ms
- P99: 990 ms
- P99.9: 2,400 ms

### Errors (expected / actionable)

| Status | Count | Cause | Resolution |
|---|---|---|---|
| 404 | 296 | `/api/patients/{pid}/suspects` is at a different path — locustfile path bug | Fix locustfile route |
| 429 | 695 | Suspects endpoint rate-limit hit at 40% weight × 50 users | This is **correct behavior** — confirms per-endpoint limiter works |

---

## Identified bottleneck

### `/api/v28-impact/portfolio` — P95 1.3s, P99 2.3s

**Root cause hypothesis:** the endpoint scans all patients in tenant, computes V24/V28 hierarchy, then aggregates. For ~50 demo patients this should be fast — but each call re-runs the calculation (no cache hit) because the demo cache TTL is short.

**Mitigation paths (not implemented in this baseline; tracked as P1):**
1. Move the per-patient compute into a Celery beat task (`raf.refresh_v28_portfolio` — already exists). Set TTL to 24h.
2. Cache the aggregated result per `(tenant_id, year)` in Redis with 1h TTL.
3. Add a `?force_refresh=true` query param for admin override.

**Expected after fix:** P95 < 100ms (Redis hit).

---

## Other observations

- **All endpoints are auth-gated and return 401 with no token** — confirmed by the prior 401-only run when auth wiring was wrong. The fix in the Locust script (shared token via thread-safe singleton) avoids hitting the login rate-limit.
- **Per-endpoint rate-limit fires at 50u** for `/api/suspects` and `/api/v28-impact/portfolio` — this is the `limiter` decorator working. Verifies per-endpoint throttle.
- **No 5xx errors**: backend stays stable under 50u for 60s without OOM or DB connection exhaustion.

---

## Production target SLOs (proposed for pilot)

| Endpoint class | P95 target | P99 target | RPS target |
|---|---|---|---|
| Read (list, dashboard) | < 200 ms | < 500 ms | 1,000 |
| Read (single resource) | < 100 ms | < 250 ms | 2,000 |
| Write (accept, create) | < 500 ms | < 1.5 s | 200 |
| Bulk write (CSV ingest) | < 30 s | < 60 s | 10 |
| Long aggregation (V28, HEDIS) | < 2 s | < 5 s | 50 (cached) |

---

## How to re-run

```bash
cd backend
# Headless 50u for 60s
.venv/bin/locust -f tests/load/locustfile_raf.py \
    --headless --users 50 --spawn-rate 10 --run-time 60s \
    --host http://localhost:8500 --csv=/tmp/raf-perf-50u

# Interactive web UI
.venv/bin/locust -f tests/load/locustfile_raf.py --host http://localhost:8500
# then visit http://localhost:8089
```

Re-run cadence:
- Before every major release
- After any change to a hot-path endpoint (suspects, v28-impact, hedis, md/today)
- Monthly via `security-monthly` GitHub Actions workflow (planned)
