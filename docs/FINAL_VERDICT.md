# RAF Intelligence — Final Independent Verdict

**Branch reviewed:** `fix/post-review-batch-10` (tip `a4c8f1b`)
**Baseline:** `docs/READINESS_MATRIX.md` @ `82539a1` (claimed 8.4 / 10)
**Date:** 2026-05-16
**Reviewer:** Independent verifier, no participation in fix loops.

## Methodology

Re-counted artefacts from `a4c8f1b` git tree directly. Did not trust prior summary.

## Verified counts (from `a4c8f1b`)

- Routers under `backend/app/routers/`: **91** (matrix claimed 92 — off by 1, immaterial).
- Python tests `backend/tests/test_*.py`: **118** (matrix claimed 117 — verified).
- Playwright specs under `frontend/tests/`: **54** (matrix claimed 51 — undercount in matrix; current is higher).
- SQL files in `database/` + `backend/migrations/`: **58 + 4 = 62** (matrix said 58 total; matrix mis-aggregated).
- CI workflows in `.github/workflows/`: **7** (`ci`, `deploy`, `golden-tests`, `dx-hardening`, `security`, `bandit-security`, `bundle-size`). Matrix claimed 6.
- Commits in window `0b4b8f8..a4c8f1b`: **114**. The fix loops are real.
- `docs/FINAL_TEST_REPORT.md`: **does not exist**. Prompt referenced a file that was never produced.

## CI gate status (verified by reading `ci.yml`)

- Golden / integration / axe: `continue-on-error: true` was REMOVED in `c92d485`. These ARE blocking — confirmed.
- `pip-audit` step stays non-blocking by intent — single remaining soft gate.
- Bandit workflow exists, runs on push + PR, fails on HIGH severity — verified in `bandit-security.yml`.

## Re-scored 10 dimensions

| # | Dimension | Matrix | My score | Why my score differs |
|---|---|---:|---:|---|
| 1 | Backend / API | 8 | **8** | Pagination + 92-router OpenAPI tagging still incomplete. |
| 2 | Frontend / UI | 8 | **7** | Two known intermittent React errors, uncommitted local edits, untracked debug specs. |
| 3 | Security | 8 | **7** | GOOGLE_API_KEY rotation + JWT_SECRET rotation are user-action gates; pip-audit non-blocking; no Dependabot. |
| 4 | Database | 8 | **7** | Replica scaffold only, binlog expiry runtime-only on prod, no rollback runbook. |
| 5 | Tests | 8 | **8** | 118 + 54 specs strong; no mutation testing, no coverage gate. |
| 6 | Observability | 9 | **8** | Four pillars wired, but zero Grafana dashboards for OTel and no SLO alerts. |
| 7 | Deploy / CI | 8 | **7** | No staging env; two TLS-check scripts; crons not yet installed on prod; bundle-size gate brand new. |
| 8 | Accessibility | 8 | **7** | Axe e2e covers only `/patients`; 4 high-traffic routes untested; no manual SR pass. |
| 9 | AI Safety | 8 | **7** | Model-version surfaced in DB but no UI badge; no token-cost guardrail; feedback loop not wired to retrain. |
| 10 | Architecture | 7 | **7** | Redis fallback exists (matrix mis-claimed in-process only), but single-instance MySQL + sync submission lifecycle remain. |

**Weighted overall (equal weights):** **7.3 / 10**. Matrix's 8.4 was generous by ~1 point — primarily by treating "scaffold present" as "in production" for replica, HA app server, and observability dashboards.

## Realistic ceiling from code alone

**Code-only ceiling: ~8.5 / 10.** The remaining gap to 10 is structurally not closeable by writing more code in this repo.

### Code-level gaps still closeable (do these first)

- `frontend/src/app/users/page.tsx` — discard or commit the dangling local edits.
- `.github/workflows/{ci,golden-tests}.yml` — flush the unstaged diffs noted in matrix §7.
- Extend `frontend/tests/e2e/axe-smoke.spec.ts` to `/suspects`, `/claims`, `/review-queue`, `/analysis`, `/recapture`.
- Add model-version badge consumer of `raf_patient_hcc.model_version` in `frontend/src/components/AISuggestionPanel.tsx`.
- Remove `/.coverage` and add to `.gitignore`.
- Dedupe `scripts/check_cert_expiry.sh` vs `scripts/check-tls-expiry.sh`.
- Add tenant-guard coverage test against `backend/app/router_registry.py` — closes Risk #1.
- Flip `pip-audit` step in `ci.yml` to blocking with a curated ignore-list.
- Commit Grafana dashboards under `ops/grafana-provisioning/dashboards/` for the OTel spans introduced in `0a82684`.

### Operational gaps requiring user action (no runbook covers all)

- Rotate `GOOGLE_API_KEY` and `JWT_SECRET` in prod `.env`. No runbook documents the procedure — write one in `docs/incident_runbooks.md`.
- Run `ops/install-crons.sh` on `ubuntu@10.1.0.204`.
- Persist binlog expiry into `my.cnf` (currently runtime-only per `feedback_mysql_binlog_growth.md`).
- Enable OpenEMR OAuth2 client `AGl5Lx…` in admin (per `feedback_openemr_client_enable.md`).
- Promote MySQL replica scaffold to a real warm-standby on a sibling host.

### Genuine "needs real customers" gaps (cannot be closed in-repo)

- HIPAA / SOC 2 audit signoff — requires external auditor, 6-12 weeks.
- Multi-tenant PHI isolation under real concurrent load — only chaos with paying tenants will expose subtle bypasses.
- Model drift detection — requires production label feedback at volume (months).
- Customer-load performance — load tests exist (`backend/tests/load/locustfile.py`) but no scheduled run; real ceiling unknown until first paying tenant.

## Verdict

**Honest current score: 7.3 / 10.** Code-only realistic ceiling: **8.5 / 10** after closing the nine code gaps above. **10 / 10 is not reachable from code alone** because the residual 1.5 points are auditor signoff, real-PHI battle-testing, and customer-load chaos — none of which a fix-loop agent can manufacture.

Ship to a design partner under the matrix's operational checklist. Do not call this 10/10; do not call it 8.4 either. It is a credible first-customer build with documented blockers — that is what 7.3 means in this rubric, and that is a healthy place to be.
