-- =============================================================================
-- RAF Intelligence — Migration 025: Normalize emr_connections.db_host
-- =============================================================================
-- Fixes a worker failure seen in logs:
--   sync_encounters FAILED ... Can't connect to MySQL server on 'localhost:3306'
--
-- Root cause: some rows in `emr_connections` have `db_host` set to 'localhost'
-- or '127.0.0.1'. Inside the worker container, those names resolve to the
-- container itself rather than the OpenEMR MySQL service. The canonical Docker
-- Compose service name for OpenEMR's MySQL (see docker-compose.yml:165 and
-- backend env OPENEMR_DB_HOST default on lines 54/101) is `mysql`.
--
-- This migration rewrites loopback-style hosts to the canonical service name,
-- but only for direct-DB connection rows. FHIR / REST rows are untouched.
--
-- Idempotent; safe to re-run. If every affected row is already normalized,
-- the UPDATE simply matches zero rows.
-- =============================================================================

UPDATE emr_connections
SET db_host = 'mysql'
WHERE db_host IN ('localhost', '127.0.0.1', '0.0.0.0')
  AND db_type IN ('direct_db', 'mariadb', 'mysql');

-- -----------------------------------------------------------------------------
-- ROLLBACK (for operator reference — do NOT uncomment in normal deploys):
-- -----------------------------------------------------------------------------
-- UPDATE emr_connections
-- SET db_host = 'localhost'
-- WHERE db_host = 'mysql'
--   AND db_type IN ('direct_db', 'mariadb', 'mysql');
-- =============================================================================
