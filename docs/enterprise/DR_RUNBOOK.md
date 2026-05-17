# Disaster Recovery Runbook — RAF Intelligence

**Owner:** Platform/SRE (kriya@raf.health)
**Last reviewed:** 2026-05-18
**Review cadence:** quarterly

## 1. Objectives

| Target | Value |
|---|---|
| RTO (Recovery Time Objective) | **2 hours** for region-level failure |
| RPO (Recovery Point Objective) | **15 minutes** (MySQL binlog shipped continuously) |
| Audit-chain RPO | **0** (synchronous DB + JSONL, hourly WORM archive) |
| MTTR (median, single-instance failure) | **15 minutes** |

## 2. Components & dependencies

| Component | Tier | Region | Stateful |
|---|---|---|---|
| `raf-backend` (FastAPI) | T1 | OVH-NA (primary), AWS-US-West (DR) | No |
| `raf-mysql` (RAF + OpenEMR dbs) | T0 | OVH-NA | **Yes** |
| `raf-redis` (Celery broker + cache) | T1 | OVH-NA | Ephemeral OK |
| `celery-worker`, `celery-beat` | T1 | OVH-NA | No |
| **Audit log** (JSONL + DB + S3 WORM) | T0 | dual-write | **Yes** |
| External: OpenEMR FHIR | T2 | per-tenant | n/a |
| External: Gemini API | T2 | google | n/a |
| External: Twilio, SendGrid | T2 | provider | n/a |

## 3. Backup strategy

### 3.1 MySQL

- **Full dump**: nightly 02:00 UTC, retained 30 days, encrypted at rest, off-site to S3 (`s3://raf-backups-prod/mysql/full/`).
- **Binlog shipping**: continuous, 15-min batch flush to S3 (`s3://raf-backups-prod/mysql/binlog/`).
- **Verified**: monthly automated restore-test to staging environment via Celery beat task `raf.backup_verify.run`.

### 3.2 Audit log

- **Tier 1 (hot)**: local JSONL `logs/immutable_audit.jsonl`, fsynced after every write.
- **Tier 2 (warm)**: MySQL `immutable_audit_log` row per event, hash-chained.
- **Tier 3 (cold/WORM)**: S3 Object Lock COMPLIANCE mode, retention 7 years (2555 days), hourly via Celery `raf.archive_audit_log_hourly`.
- **Boot-time integrity check**: `verify_chain_on_boot()` refuses to start if DB has a last_hash but JSONL is missing.

### 3.3 Uploaded documents (chart-chase, CCDAs)

- Volume mount `/uploads/` is rsynced to S3 every 5 minutes via cron.

## 4. Failure scenarios + recovery

### 4.1 Backend container crash (single instance)

**Detection:** Container healthcheck → Docker restart policy `unless-stopped`. PagerDuty alert if 3 restarts in 5 min.

**Recovery (automatic):** Docker restarts. No data loss (backend is stateless).

**MTTR:** < 60 seconds.

### 4.2 MySQL instance failure

**Detection:** Backend `/health` returns 503 within 10s of MySQL outage.

**Recovery:**
1. PagerDuty pages SRE.
2. SRE checks if MySQL container can restart: `docker logs raf-mysql --tail 100`.
3. If disk-full: free space + restart. RTO < 15 min.
4. If data corruption: failover to DR — apply last full dump + binlogs from S3 to `raf-mysql-dr` in AWS-US-West. RTO 1–2 hours.

**Runbook commands:**
```bash
# On DR host
docker run -d --name raf-mysql-dr -v /data/mysql:/var/lib/mysql mysql:8.0
aws s3 cp s3://raf-backups-prod/mysql/full/$(date +%Y-%m-%d).sql.gz - | gunzip | \
  docker exec -i raf-mysql-dr mysql -uroot -p$PASS
# Replay binlogs newer than dump timestamp
aws s3 cp s3://raf-backups-prod/mysql/binlog/ ./binlog/ --recursive \
  --exclude "* before $DUMP_TS"
for f in ./binlog/*.bin; do
  docker exec -i raf-mysql-dr mysqlbinlog $f | mysql -uroot -p$PASS
done
# Repoint backend DNS
aws route53 change-resource-record-sets --hosted-zone-id ... --change-batch ...
```

### 4.3 Region-level OVH outage

**Detection:** External Pingdom check fails for 5 min.

**Recovery:**
1. Promote DR (AWS-US-West) per §4.2.
2. Update Route 53 weighted record `raf.health` to 100% AWS-US-West.
3. Confirm `verify_chain_on_boot()` passes on DR backend.
4. Public status page update.

**RTO:** 2 hours. **RPO:** 15 minutes.

### 4.4 Audit chain divergence

**Detection:** Boot fails with `RuntimeError: FATAL: audit chain tampered`. OR `append_audit_entry` raises `AuditChainTamperError` at runtime.

**Recovery:** **DO NOT** delete the JSONL. **DO NOT** truncate the DB table.

1. Page SRE + legal (this is a compliance event).
2. Snapshot both JSONL and DB rows.
3. Compute hash from S3 WORM archive `s3://raf-audit-worm-prod/$(date +%Y/%m/%d)/`.
4. Open incident ticket with full timeline.
5. Reconcile from WORM tier if forensically clean.

### 4.5 OpenEMR FHIR endpoint outage

**Detection:** FHIR circuit breaker opens (per-tenant, `GET /api/fhir/circuit/status`).

**Recovery:**
1. **No customer-facing outage** — circuit fails fast in <50ms instead of blocking.
2. SUSPECT accepts still succeed; `raf_suspect_conditions.fhir_writeback_status='failed'`.
3. After 60s the circuit transitions to half-open and probes.
4. On EHR recovery, run replay job: `POST /api/admin/fhir/replay-failed-writes` (admin endpoint, to be added).

### 4.6 Twilio / SendGrid outage

**Detection:** `GET /api/outreach/health` shows `failed_other_24h` rising.

**Recovery:**
1. Messages auto-fall to status=`failed` with vendor error.
2. After vendor recovers: `POST /api/outreach/replay-batch` with list of failed message_ids.

## 5. Communication

| Severity | Notify | SLA |
|---|---|---|
| SEV-1 (outage, PHI risk) | PagerDuty primary + secondary + legal + customer success | < 15 min |
| SEV-2 (degraded, no PHI risk) | PagerDuty primary | < 30 min |
| SEV-3 (single-tenant issue) | Slack #raf-ops | < 2 hours |

**Public status page:** https://status.raf.health (Statuspage.io)
**Customer notification:** automated for SEV-1, manual for SEV-2 via Customer Success.

## 6. Post-incident

Within 72 hours of any SEV-1/SEV-2:

1. Blameless post-mortem in Notion.
2. Add regression test (if applicable).
3. File JIRA ticket for any deferred remediation.
4. Update this runbook if the scenario was novel.

## 7. Quarterly drill

Every quarter, SRE runs a tabletop exercise simulating one of §4.1–4.6 plus a randomly-chosen multi-failure (e.g. MySQL + region). Drill output is logged in `docs/enterprise/dr-drills/`.

## 8. References

- `/Users/murali/Desktop/raf-intelligence/backend/app/services/immutable_audit.py:311` — `verify_chain_on_boot()`
- `/Users/murali/Desktop/raf-intelligence/backend/app/services/celery_tasks.py` — `raf.archive_audit_log_hourly`
- `/Users/murali/Desktop/raf-intelligence/backend/app/services/circuit_breaker.py` — per-tenant FHIR breakers
