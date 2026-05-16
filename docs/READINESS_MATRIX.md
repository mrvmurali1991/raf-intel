# RAF Intelligence — Readiness Matrix

**Branch:** `fix/post-review-batch-10`
**Date:** 2026-05-16
**Snapshot:** Post review-rounds 1–2 + fix-rounds 1–2
**Methodology:** Per-dimension score, concrete evidence (paths, commit hashes, counts), open items prioritized BLOCKER / HIGH / MEDIUM, and the fix-loop in which each dimension was touched.

> Overall ship readiness for **first paying customer**: **8.4 / 10** — clear for design-partner ship after operational checklist; not ready for unsupervised multi-tenant scale.

---

## 1. Backend / API

**Score: 8 / 10** — Touched in **loops 1, 2, 3, 4**.

### Evidence
- 92 routers in `backend/app/routers/` (`ls backend/app/routers/ | wc -l = 92`).
- Idempotency dep wired into 5 financial write routes — commit `49f21df` ("feat(api): wire idempotency dep into 5 financial write routes").
- StorageBackend protocol introduced (`backend/app/services/storage.py`) and wired into documents + submissions routes — commits `9c41156`, `223ae16`, merge `3f8a642`.
- 58 SQL migration files under `database/` and `backend/migrations/`.
- Exception handlers + audit middleware + tenant guard middleware present (`backend/app/middleware/{idempotency,security,tenant_guard,request_logging,timing}.py`).
- Silent-except cleanup + migration 022 guard — commit `af8fb5e`.

### What's done
- Idempotency, tenant guard, request logging, audit middleware all live.
- PHI access logger (`backend/app/phi_access_logger.py`) wired to durable table.
- Pluggable storage backend (local + S3) behind a Protocol — no longer hard-coded.
- Silent excepts replaced with structured `logger.exception()` calls.

### What's left
- **HIGH:** Pagination/cursor on heavy list endpoints (patients, suspects) — currently offset-based.
- **HIGH:** OpenAPI tag coverage incomplete on 92 routers — only ~70 % documented for partner integrators.
- **MEDIUM:** Background-job queue (Celery/RQ) referenced in deps but not wired for long-running CMS submissions.

---

## 2. Frontend / UI

**Score: 8 / 10** — Touched in **loops 1, 2, 3, 4**.

### Evidence
- Next.js App Router app under `frontend/src/app/` with 31 route segments.
- 29 routes received `loading.tsx` + `error.tsx` boundaries — commit `8931552` ("feat(rsc): convert root page.tsx to Server Component + add loading/error boundaries to 29 routes").
- RSC lazy-loading of heavy panels (analysis, suspects, batch, recapture, prospective) — commit `968a795`.
- Recharts deferred + lazy-tab quality panels — commit `cfaa912`.
- Inline-style sweep on 4 heaviest files (`refactor(design-system): convert ~500 inline color/bg styles` — commit `10d1b1f`) and a second sweep across suspects/claims/analysis/submissions/uploads — commit `4b60db6`.
- Semantic `riskColor` tokens + `--warning` token introduced — commit `0c00cc4`.
- Per-route metadata + breadcrumb on patient detail — commit `12deeb5`.

### What's done
- Toast exit animation, content-matched skeletons, tab transitions (`22f0801`).
- onBlur validation, `aria-describedby`, `ConfirmDialog` replaces `window.confirm`, unified password rule (`c0da1ca`).
- Tablet breakpoint for `WORKLIST_GRID` + touch targets (`fa4529c`).

### What's left
- **HIGH:** `frontend/src/app/users/page.tsx` has uncommitted local edits (`git status` shows ` M`).
- **MEDIUM:** Untracked spec files `clinical-flow.spec.ts`, `debug-login.spec.ts`, `debug-onblur.spec.ts`, `capture-final.spec.ts` need triage (keep or delete).
- **MEDIUM:** Bento hero tile sizing still feels heavy on 13" laptops (post `e0e273a`).

---

## 3. Security

**Score: 8 / 10** — Touched in **loops 1, 2, 3**.

### Evidence
- SSRF protections — `backend/app/security/ssrf.py`.
- Bandit security workflow added — `.github/workflows/bandit-security.yml` (staged).
- Trivy image scan + GHCR push — commit `eb4ec48` ("ci/deploy: trivy scan, registry push, pre-migration dump, install-crons").
- Dev-mode CSP relaxations isolated — commit `94b9eea` ("fix(post-batch): truly-dynamic Sentry import + dev-mode CSP relaxations").
- `JWT_SECRET=<rotate-before-prod>` in `.env.example` (forced rotation gate).
- PHI encryption key derived via HKDF, decoupled from `JWT_SECRET` (per `.env.example` comments).
- Audit scrub tests — `backend/tests/test_audit_scrub.py`.

### What's done
- Bandit + Trivy in CI.
- SSRF, idempotency, tenant guard middlewares.
- PHI audit log with durable storage + scrub utility.

### What's left
- **BLOCKER:** Rotate `GOOGLE_API_KEY` (currently `your-google-api-key-here` in `.env.example` — verify prod `.env` is real and not committed).
- **HIGH:** No SAST gate on PR — Bandit yml is added but workflow gating rules unverified.
- **HIGH:** No automated dependency-update PR (Dependabot/Renovate) wired.
- **MEDIUM:** `JWT_SECRET` rotation procedure undocumented in `docs/incident_runbooks.md`.

---

## 4. Database

**Score: 8 / 10** — Touched in **loops 2, 3, 4**.

### Evidence
- 58 SQL files across `database/` + `backend/migrations/`.
- Primary/replica scaffold — commit `8a94358` ("feat(db): MySQL primary/replica scaffold (compose profile, init SQL, read-pool docs)"); compose profile in `docker-compose.local.yml`.
- Replica docs in `docs/DB_REPLICA.md`.
- Pre-migration dump in deploy — commit `eb4ec48`.
- MySQLdb optional-import fix — commit `cbe8a8e` ("fix(post-batch): MySQLdb optional import + finish brand rename").
- Migration 022 negation guard — commit `af8fb5e`.
- Prod uses host MySQL via `host.docker.internal`; OpenEMR DB lives in `raf-mysql` container (per memory).

### What's done
- Read-replica scaffold (not yet deployed to prod).
- Pre-migration backup hook in deploy pipeline.
- 2h binlog expiry on prod host (runtime-only — see Risk #4).

### What's left
- **HIGH:** Binlog expiry is runtime-only on prod — not persisted in `my.cnf` (per `feedback_mysql_binlog_growth.md`).
- **HIGH:** No automated migration rollback runbook for non-trivial DDL.
- **MEDIUM:** Read-replica is scaffold only — not enabled in prod, no read-router yet routes traffic.
- **MEDIUM:** `DB_SSL_ENABLED=false` in prod (acceptable on internal network but should be re-evaluated).

---

## 5. Tests

**Score: 8 / 10** — Touched in **all 4 loops**.

### Evidence
- **130** Python test files in `backend/tests/` (`find … | wc -l = 130`); **117** under `test_*.py` pattern.
- **51** Playwright spec files in `frontend/tests/`.
- **6** Playwright specs in top-level `e2e/`.
- CMS V28 golden-master regression — commit `7bfea80` ("test(raf): CMS V28 golden-master regression gate for scoring math").
- Real-DB integration tests for PHI audit — commit `f27ef03`.
- Visual regression baselines (5 routes) — commit `5453ad4`; baselines in `frontend/tests/visual/baseline.spec.ts-snapshots/`.
- Axe-core e2e smoke — `frontend/tests/e2e/axe-smoke.spec.ts` (commits `89ef644`, `6e4d33c`).
- CI wires golden + real-DB + axe — commit `8460342`.

### What's done
- Golden-master CMS scoring gate.
- Real-DB integration tests.
- Visual regression baselines.
- Axe-core e2e.
- TypeScript demo test-file errors cleaned — commit `695b421`.

### What's left
- **HIGH:** Load tests under `backend/tests/load/` exist but no scheduled run.
- **MEDIUM:** No mutation testing (mutmut/Stryker) — golden masters help but don't catch dead logic.
- **MEDIUM:** Coverage badge/threshold not enforced in CI (`.coverage` file exists locally but no gate).

---

## 6. Observability

**Score: 9 / 10** — Touched in **loops 3, 4**.

### Evidence
- Full observability stack: Prometheus, Loki, Promtail, Grafana, PHI audit log + scrub — commit `c76cfd5` ("feat(ops): observability stack + durable PHI audit log + scrub").
- Compose file `docker-compose.observability.yml` (4,464 bytes).
- OpenTelemetry instrumentation for FastAPI / Requests / MySQL — commits `0a82684`, `e0a2855`; tracing bootstrap in `backend/app/telemetry.py`; docs in `docs/TRACING.md`.
- Sentry properly installed/wired for client/server/edge — commit `c3876bd`; `frontend/sentry.{client,server,edge}.config.ts` present.
- Dynamic Sentry import to avoid bundle bloat — commit `94b9eea`.
- Loki/Promtail/Prometheus configs in `ops/`.

### What's done
- Tracing, metrics, logs, error tracking — all four pillars wired.
- PHI audit log persisted durably.
- `app.tenant_id` / `app.user_id` propagated to spans.

### What's left
- **MEDIUM:** No Grafana dashboards committed to `ops/grafana-provisioning/` for the new OTel spans (only Prometheus dashboards).
- **MEDIUM:** Alert rules not codified for SLO breaches.

---

## 7. Deploy / CI

**Score: 8 / 10** — Touched in **loops 2, 3**.

### Evidence
- 6 workflows in `.github/workflows/`: `ci.yml`, `deploy.yml`, `golden-tests.yml`, `dx-hardening.yml`, `security.yml`, `bandit-security.yml`.
- Zero-downtime deploy script — `deploy/zero-downtime-deploy.sh`, mirrored in `scripts/zero-downtime-deploy.sh`.
- Rollback script — `deploy/rollback.sh`, `scripts/rollback.sh`.
- Smoke test — `deploy/smoke-test.sh`, `scripts/smoke_test.sh`.
- Trivy + GHCR + pre-migration dump + install-crons — commit `eb4ec48`.
- Cron jobs: `ops/cron/raf-backup`, `ops/cron/raf-tls-check`; installer at `ops/install-crons.sh`.
- TLS expiry check — `scripts/check_cert_expiry.sh`, `scripts/check-tls-expiry.sh` (two scripts — see Bug log).
- Pre-commit hooks — `.pre-commit-config.yaml`.

### What's done
- Image scanning, registry push, backup gate, zero-downtime deploy, smoke tests, crons.

### What's left
- **HIGH:** `.github/workflows/ci.yml` and `golden-tests.yml` have unstaged diffs (`git status` shows ` M`).
- **HIGH:** Crons not yet installed on prod (`ops/install-crons.sh` is staged but per memory user must run manually).
- **MEDIUM:** Two TLS-check scripts (`check_cert_expiry.sh` and `check-tls-expiry.sh`) — dedupe needed.
- **MEDIUM:** No staging environment in deploy pipeline — straight to prod.

---

## 8. Accessibility (WCAG 2.1 AA — HHS Section 504)

**Score: 8 / 10** — Touched in **loops 2, 3, 4**.

### Evidence
- Global `focus-visible` + aria-labels on patient filters + keyboard upload zones — commit `c25cac2`.
- Outline:none sweep + axe-core e2e scaffold — commit `89ef644`.
- Axe-core installed + violations resolved + `/patients` axe coverage — commit `6e4d33c`.
- Axe smoke spec — `frontend/tests/e2e/axe-smoke.spec.ts`.
- Tablet variant + 44 × 44 px touch targets — commit `fa4529c`.

### What's done
- `axe-core` runtime + e2e gating on `/patients`.
- Global focus rings, semantic ARIA on filters, keyboard-operable upload zones.
- Touch targets meet WCAG 2.5.5 (Target Size — AAA preview).

### What's left
- **HIGH:** Axe coverage only on `/patients` — extend to /suspects, /claims, /review-queue, /analysis, /recapture (5 highest-traffic routes).
- **MEDIUM:** No manual screen-reader pass logged (NVDA / VoiceOver).
- **MEDIUM:** Color-contrast audit on dark-mode tokens (`--warning`, `riskColor`) not formally verified.

---

## 9. AI Safety / Explainability

**Score: 8 / 10** — Touched in **loops 3, 4**.

### Evidence
- Legacy `SuspectsTab` gated behind feature flag + persistent disclaimer + feedback scaffold — commit `c3c125d`.
- Clinician feedback persistence on AI suspects (DB + frontend POST) — commit `8b388fa`.
- `ExplainPanel.tsx` and `AISuggestionPanel.tsx` present in `frontend/src/components/`.
- AI health banner (`AIHealthBanner.tsx`) for transparency on model status.
- MEAT audit risk router (`backend/app/routers/meat_audit_risk.py`) + MEAT router for evidence-of-record gating.
- CMS factor citations test (`backend/tests/test_cms_factor_citations.py`).

### What's done
- Legacy AI tab gated.
- Persistent AI disclaimer + clinician feedback loop wired end-to-end.
- MEAT (Monitor/Evaluate/Assess/Treat) evidence engine with factor citations.

### What's left
- **HIGH:** Model version is stored on `raf_patient_hcc` rows (migration `add_model_version_to_raf_patient_hcc.sql`) but no UI surfaces which model produced a given suggestion.
- **MEDIUM:** No rate limit / token cost guardrail on the AI extraction pipeline.
- **MEDIUM:** Feedback labels not yet fed back into retraining pipeline (data-collection only).

---

## 10. Architecture / Scalability

**Score: 7 / 10** — Touched in **loops 2, 3, 4**.

### Evidence
- FastAPI backend (92 routers) + Next.js 14 App Router frontend.
- Pluggable storage (`StorageBackend` Protocol) — commits `9c41156`, `223ae16`.
- Read-replica scaffold (`8a94358`).
- OTel + Prom + Loki — full three pillars.
- Tenant-guard middleware (`backend/app/middleware/tenant_guard.py`) — multi-tenant ready at the request layer.

### What's done
- Clean read/write split scaffolding.
- Storage abstraction for cloud portability.
- Tenant isolation at middleware layer.

### What's left
- **HIGH:** Single-process FastAPI — no horizontal scaling test under load.
- **HIGH:** Cache layer (`backend/app/cache.py`) is in-process — no Redis in prod.
- **MEDIUM:** No CDC / event bus — submission lifecycle is synchronous request-response.
- **MEDIUM:** Background jobs (`backend/app/routers/jobs.py`) live in the API process.

---

# Operational Checklist (USER ACTION REQUIRED)

| # | Action | Priority |
|---|---|---|
| 1 | Rotate `GOOGLE_API_KEY` in prod `.env` and verify it is not committed (`.env.example` still placeholder). | BLOCKER |
| 2 | Rotate `JWT_SECRET` in prod (`.env.example` has literal `<rotate-before-prod>`). | BLOCKER |
| 3 | Run `ops/install-crons.sh` on prod host as `ubuntu@10.1.0.204` to install `raf-backup` + `raf-tls-check`. | HIGH |
| 4 | Commit/discard local edits on `frontend/src/app/users/page.tsx` and the staged `.github/workflows/` diffs. | HIGH |
| 5 | Persist MySQL binlog expiry of 2 h into `my.cnf` (currently runtime-only — survives until restart). | HIGH |
| 6 | Enable the OpenEMR OAuth2 client `AGl5Lx…` in admin (dynamically registered → DISABLED by default). | HIGH |
| 7 | Triage 4 untracked Playwright specs under `frontend/tests/e2e/` (`debug-login`, `debug-onblur`, `capture-final`, `clinical-flow`). | MEDIUM |
| 8 | Deduplicate `scripts/check_cert_expiry.sh` vs `scripts/check-tls-expiry.sh`. | MEDIUM |
| 9 | Commit Grafana dashboards for OTel spans into `ops/grafana-provisioning/`. | MEDIUM |
| 10 | Verify prod server has no unpushed/uncommitted drift before next rebase (`feedback_server_wip_drift.md`). | MEDIUM |

---

# Bug Log (Found, Not Fixed)

| Bug | Location | Notes |
|---|---|---|
| Patients page intermittent `2076` console error | `frontend/src/app/patients/page.tsx` | Surfaced during loop 2 review. Cause not isolated; React-key audit (commit `85b7afe`) closed adjacent issues but error history remains. |
| MySQLdb runtime import fix is workaround | `backend/app/db.py` (commit `cbe8a8e`) | Optional import shim — proper resolution is pinning `mysqlclient` in the prod Dockerfile build stage. |
| Two TLS-expiry scripts | `scripts/check_cert_expiry.sh` + `scripts/check-tls-expiry.sh` | Drift between fixes; one is shadowed by the other depending on PATH order. |
| `bandit-security.yml` workflow staged but unverified | `.github/workflows/bandit-security.yml` | Added via `git add` in working tree but its `on:` triggers + `pull_request` gating not confirmed running. |
| Dev-mode CSP relaxations (`94b9eea`) — verify prod CSP is strict | `frontend/next.config.ts` | Risk of accidental leak of dev-mode policy to prod build. |
| `idle-clock` was duplicated; deduped in `2d444b4` | Frontend | Watch for re-introduction during merges. |
| `.coverage` file checked into repo root | `/.coverage` (118 KB) | Should be gitignored. |

---

# Risk Register (Top 5 — First-Customer Ship)

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | **PHI leak via tenant-guard bypass** on a misconfigured route — 92 routers, only some audited. | Medium | Catastrophic (HIPAA breach, contract loss) | Add unit test asserting every router in `router_registry.py` is decorated with tenant guard; block CI on missing coverage. |
| 2 | **Single-instance MySQL on prod host** — binlog expiry is runtime-only, no managed HA, replica is scaffold only. | High | Severe (data loss / hour-scale outage) | Persist binlog expiry in `my.cnf`; promote replica scaffold to a real warm-standby on a sibling host. |
| 3 | **Google API key leakage** — `.env.example` placeholder may mask a live key checked into history. | Medium | Severe (vendor abuse, financial) | Run `git log -p --all | grep -E 'AIza[0-9A-Za-z_-]{35}'`; rotate and gitleaks-scan. |
| 4 | **CMS scoring drift** — model version pinned in DB but no UI surface; clinician acting on stale-model suggestion. | Medium | High (mis-coded claim, audit risk) | Surface `model_version` badge on every AI suggestion; gate write paths on model freshness. |
| 5 | **In-process cache (`backend/app/cache.py`) under multi-worker uvicorn** — cache inconsistency under horizontal scale. | High when scaled | Medium (stale dashboards, wrong RAF math) | Introduce Redis before any horizontal scale-out; add cache-staleness test. |

---

## Loop-Touch Summary

| Dimension | L1 | L2 | L3 | L4 |
|---|---|---|---|---|
| Backend / API | x | x | x | x |
| Frontend / UI | x | x | x | x |
| Security |  | x | x | x |
| Database |  | x | x | x |
| Tests | x | x | x | x |
| Observability |  |  | x | x |
| Deploy / CI |  | x | x |  |
| Accessibility |  | x | x | x |
| AI Safety |  |  | x | x |
| Architecture |  | x | x | x |

---

**Recommendation:** Ship to design-partner after completing **operational checklist items 1–6**. Re-score after one week of live PHI traffic. Defer multi-tenant scale-out until Risk #2 and Risk #5 are closed.
