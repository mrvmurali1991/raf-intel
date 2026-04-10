# RAF Intelligence — Incident Runbooks
**Version**: 1.0.0
**Target Environment**: Production

This document serves as the primary technical runbook for Tier-1 and Tier-2 on-call engineers.

## Table of Contents
1. [Migration Rollback Procedures](#1-migration-rollback-procedures)
2. [Authentication Service Outage](#2-authentication-service-outage)
3. [Database Connection Saturation](#3-database-connection-saturation)
4. [AI / Gemini API Degradation](#4-ai--gemini-api-degradation)

---

## 1. Migration Rollback Procedures
**Trigger**: A bad migration was flushed to production, causing startup failures or SQL constraint errors across the backend.

### Standard Rollback
1. SSH into the primary application server or target the Kubernetes `backend` deployment.
2. Confirm current head of migrations by scanning the `run_all.sql` sequence.
3. Identify the schema breaking change. 
   - Note: Because we use idempotent `IF NOT EXISTS` raw SQL (e.g., `023_service_tables.sql`) instead of declarative down-migrations, you must execute explicit `DROP TABLE` or `ALTER TABLE ... DROP COLUMN` mapped to the bad commit.
4. Open the MySQL console:
   ```bash
   mysql -h ${RAF_DB_HOST} -P ${RAF_DB_PORT} -u ${RAF_DB_USER} -p ${RAF_DB_NAME}
   ```
5. Apply the rollback SQL.
6. Restart the backend service (`kubectl rollout restart deployment backend`).

---

## 2. Authentication Service Outage
**Trigger**: Users report HTTP 401/403s rapidly increasing; token verification failing.

### Triage Path
1. **Did `JWT_SECRET` change?**
   - Verify `env` variables on the hosting platform. If `JWT_SECRET` changed dynamically, all existing client tokens are voided. They must sign in again. This is transient but impacts UX heavily.
2. **Is it the Redis connection?**
   - Check if `redis_url` timed out. Token expiration checking might be stalled. 
   - Check readiness probe logs: `GET /health/ready` ensures Redis connectivity.
3. **Emergency Override (Break Glass)**:
   - To unblock operations, revert the `JWT_SECRET` environment variable to its previous hash in AWS Secrets Manager / Azure KeyVault until the system stabilizes.

---

## 3. Database Connection Saturation
**Trigger**: Uvicorn workers raise `TimeoutError: MySQL server has gone away` or `/health` returns "degraded" due to DB pool exhaustion.

### Triage Path
1. Verify the max connection limits on AWS RDS / Azure MySQL.
2. Check if a newly scheduled Celery job (e.g., population-wide RAF sync) has monopolized connections without releasing resources (cursor leak).
3. **Immediate Mitigation**: 
   - Increase the SQLAlchemy/Database pool `max_overflow`.
   - Scale *down* backend replicas to throttle incoming SQL load until the bottleneck is clear.
   - Run `SHOW PROCESSLIST;` on the MySQL DB to kill hanging analytical queries holding locks on `patient_data`.

---

## 4. AI / Gemini API Degradation
**Trigger**: NER clinical note processing starts failing, generating high traces in Sentry, or timing out.

### Triage Path
1. Check Google Cloud Platform status for Vertex AI / Gemini availability.
2. Validate the `GOOGLE_API_KEY` hasn't expired or breached rate limits.
3. **Graceful Fallback**: 
   - The application supports async processing. The Celery worker will drop the NER extraction job into a retry queue with exponential backoff if a `429 Too Many Requests` is struck from the AI provider.
   - No data is lost, it is just delayed. Monitor the `raf_jobs` table to ensure the `status` flips to `RETRY` successfully.
