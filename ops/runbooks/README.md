# Production Readiness Runbooks — 5 BLOCKER Ops Items

These runbooks bring RAF Intelligence prod from **8.4 / 10** to **10 / 10** by closing the five operational BLOCKER / HIGH items listed in `docs/READINESS_MATRIX.md` § "Operational Checklist".

Each runbook is a single, self-contained, copy-pasteable artifact you (the operator) run **once**. All `.sh` files are idempotent — re-running them on an already-fixed box is safe.

---

## Execution order

Run in this order. The ordering is chosen by **blast radius** (cut the bleeding first) and **deadline** (TLS expires on a calendar — the cron is preventative, but the cert itself is reactive).

| # | Runbook | Type | Why this order | Time |
|---|---|---|---|---|
| 1 | `02-rotate-jwt-secret.sh` | executable | Fastest blast-radius cut. A leaked JWT secret invalidates **all** active sessions and signed tokens — rotate it before any other change touches prod. | ~15 min |
| 2 | `01-rotate-google-api-key.md` | manual (GCP console) | Per the earlier secret-audit the key may have been exposed in `.env.example`. Burn it next so attackers cannot run up a vendor bill while you finish hardening. | ~20 min |
| 3 | `03-renew-tls-cert.sh` | executable | TLS expiry deadline ≤ 9 days from today. Renew the cert and verify before installing the **preventative** cron in step 4. | ~15 min |
| 4 | `04-install-prod-crons.sh` | executable | Installs `raf-backup` (nightly) + `raf-tls-check` (weekly). These are the long-term safety nets — install only after #3 has bought you breathing room. | ~10 min |
| 5 | `05-wire-sentry.md` | manual (Sentry console) | Observability — non-urgent but required for 10/10. Do this within the same week so the first paying customer's errors hit a real on-call inbox, not stdout. | ~30 min |

---

## Conventions

- All commands assume your local shell is `bash` or `zsh` on macOS, and the prod host is `ubuntu@10.1.0.204` reached via jump host `15.204.73.232:2222` with key `~/.ssh/openvpn-key-v2.pem` (per `reference_server.md`).
- Prod `.env` lives at `/opt/raf-intelligence/.env` on the prod host.
- Docker compose project on prod is `raf-intelligence` under `/opt/raf-intelligence`.
- Every runbook has five sections: **Prerequisites**, **Steps**, **Verification**, **Rollback**, **Time estimate**.

---

## Quick start

```bash
# From your laptop, in the repo root:
cd ops/runbooks

# 1. JWT secret
bash 02-rotate-jwt-secret.sh

# 2. Google API key — follow the markdown
open 01-rotate-google-api-key.md      # or `code .` / cat

# 3. TLS cert
bash 03-renew-tls-cert.sh

# 4. Install crons
bash 04-install-prod-crons.sh

# 5. Sentry — follow the markdown
open 05-wire-sentry.md
```

---

## After all five are done

Re-run the readiness audit:

```bash
# From repo root
git pull origin fix/post-review-batch-10
grep -E "BLOCKER" docs/READINESS_MATRIX.md
# Expected: zero matches
```

Then re-score per `docs/READINESS_MATRIX.md` methodology and confirm overall ship readiness = **10 / 10**.
