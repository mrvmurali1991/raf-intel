# Scripts — RAF Intelligence

Utility scripts for local development, database management, and demo operations.

## predemo.sh — Pre-Demo Preflight

Run this **5 minutes before a sales demo** to verify the local stack is healthy
and the demo data is fully seeded.

### Quick start

```bash
# Full preflight: health check + migrations + seeds + smoke probes
bash scripts/predemo.sh

# Dry-run: smoke probes only, no data mutations (safe on live data)
bash scripts/predemo.sh --dry-run

# Hard reset: purge all tagged demo rows, then re-seed from scratch
bash scripts/predemo.sh --reset
bash scripts/predemo.sh
```

### What it does (in order)

| Step | Action |
|------|--------|
| 1 | Assert `raf-backend`, `raf-frontend`, `raf-mysql` are up and healthy. Starts the stack via `docker compose -f docker-compose.local.yml up -d` if any are down. |
| 2 | Copy `database/migrations/` into the backend container and run `apply_migrations.py`. |
| 3 | Run `run_all_seeds.sh` inside the backend container (KG ontology seeds). |
| 4 | Run `seed_irr_demo.py` to populate inter-rater reliability demo rows. |
| 5 | Copy and run `seed_demo_panel.py` to seed 12 demo patients, HCCs, recapture gaps, suspects, and the EMR connection row. |
| 6 | Unlock the admin account: reset `failed_login_attempts` and clear `locked_until`. |
| 7 | Run smoke probes (login, dashboard stats, EMR status, frontend pages, IRR kappa). |
| 8 | Print a color-coded summary — green check per pass, red X per fail with a one-line remediation hint. |

### Smoke probes

| Probe | Endpoint | Pass condition |
|-------|----------|---------------|
| Login | `POST /api/auth/login` | `access_token` in response |
| Dashboard data | `GET /api/dashboard/stats` | `total_patients > 0` |
| EMR connected | `GET /api/emr/status` | `connected: true` |
| Frontend pages | `/`, `/worklist`, `/patients`, `/recapture`, `/suspects` | HTTP 200 (or 30x redirect) |
| Mobile UA | `/` with iPhone user-agent | HTTP 200 (or 30x redirect) |
| IRR kappa | `GET /api/recapture/audit-readiness` | `inter_rater_reliability.kappa > 0` |

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | All P0 checks passed (demo is ready) |
| `1` | One or more P0 failures (do not start the demo) |

P0 failures: login, frontend pages, dashboard total_patients.
Non-P0 failures (EMR status, IRR kappa): script exits 0 with a warning.

### Demo credentials

```
URL:      http://localhost:3444
Email:    admin@raf.health
Password: Admin@123
```

### Flags

| Flag | Effect |
|------|--------|
| `--dry-run` | Skips all seed steps; runs smoke probes only. Use when you want to verify without mutating any data. |
| `--reset` | Deletes all rows tagged `DEMO_PANEL` / `IRR_DEMO` before re-seeding. Use when demo data is stale or corrupted. |

### Troubleshooting

**"Container raf-backend is not healthy"**
```bash
docker compose -f docker-compose.local.yml logs raf-backend --tail 50
```

**"Login: no access_token"**
```bash
# Manually unlock the account
docker exec raf-mysql mysql -uroot -proot raf_intelligence \
  -e "UPDATE users SET failed_login_attempts=0, locked_until=NULL WHERE email='admin@raf.health';"
```

**"total_patients is 0"**
```bash
# Re-run full seed (without --dry-run)
bash scripts/predemo.sh --reset
bash scripts/predemo.sh
```

**"kappa not > 0"**
```bash
docker exec raf-backend python /app/scripts/seed_irr_demo.py
```

---

## Other scripts

| Script | Purpose |
|--------|---------|
| `backup.sh` | Database backup |
| `restore.sh` | Database restore |
| `smoke_test.sh` | Pre-deploy image smoke test (CI usage) |
| `validate-env.sh` | Validate `.env` file completeness |
| `seed_sample_patients.py` | Seed a small set of sample patients (dev) |
| `seed_demo_environment.py` | Broader demo environment seed (legacy) |
| `import_raf_coefficients.py` | Load CMS RAF coefficients from CSV |
| `import_icd10_hcc_crosswalk.py` | Load ICD-10 → HCC crosswalk |
| `import_full_crosswalk.py` | Full crosswalk import |
| `integration_test.py` | End-to-end API integration tests |
