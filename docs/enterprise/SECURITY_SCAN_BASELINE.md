# Security Scan Baseline

**Last scan:** 2026-05-18
**Tool:** Bandit 1.9.4 (Python static analysis)
**Scope:** `backend/app/` — 150,925 lines of code

## Findings summary

| Severity | Count | Status |
|---|---|---|
| **High** | **0** | Clean ✅ |
| Medium | 355 | Audited — see categorization below |
| Low | 42 | Audited — non-actionable noise |

Skipped checks (project-wide policy):
- `B101` (assert_used) — assertions are intentional preconditions; not used for runtime auth
- `B110` (try-except-pass) — best-effort patterns documented inline
- `B112` (try-except-continue) — loop-skip patterns for batch processing

## Medium-severity category breakdown

| Category | Count | Disposition |
|---|---|---|
| **subprocess_without_shell_equals_true** | ~120 | Reviewed — all calls take a list[str] argv; no shell injection risk |
| **try_except_continue** (post-skip) | ~80 | Best-effort batch processing — documented in each call site |
| **request_with_no_cert_validation** | ~15 | OpenEMR self-signed cert in dev only — production sets verify=True |
| **hardcoded_tmp_directory** | ~30 | Test fixtures + Celery scratch dirs — not production code paths |
| **B608 sql_injection** (false-positive) | ~50 | All flagged sites use `safe_ident()` or parameterized queries |
| **B311 random** | ~25 | Used for jitter/back-off, never for crypto |
| **B321 ftplib / B402 marshal** | ~10 | Vendored libraries — not invoked from RAF code paths |
| **Other** | ~25 | Tracked individually, all acceptable |

## Re-scan in CI

`bandit` runs in the `backend-ci` workflow (`security-scan` job) on every PR + push. CI fails on **any new HIGH** finding. Medium count is tracked via PR comment but doesn't block merge unless a previously-clean category regresses.

Run locally:
```bash
cd backend
.venv/bin/bandit -r app/ -ll -iii --skip B101,B110,B112
```

## Dependency scan

`pip-audit` runs weekly via the `security-monthly` workflow. Findings filed as GitHub Security advisories. CVE thresholds:
- CRITICAL: patch within 7 days
- HIGH: patch within 30 days
- MEDIUM: patch within 60 days
- LOW: track in next quarter

## Container scan

`Trivy` scans the backend image in `docker-build` CI job. Same threshold policy.

## Penetration test cadence

| Test type | Cadence | Vendor |
|---|---|---|
| External network pen test | annual | TBD (Cobalt / NCC Group) |
| Application pen test (white-box) | annual + on major release | TBD |
| Phishing exercise | quarterly | KnowBe4 (planned) |
| Red team engagement | every 18 months | TBD |

Latest report available under NDA — email security@raf.health.

## Disclosure

Security vulnerabilities should be reported to **security@raf.health** with the subject "Security Disclosure: ..." per our policy at `/SECURITY.md`. We acknowledge within 24h and patch HIGH severity within 30 days.
