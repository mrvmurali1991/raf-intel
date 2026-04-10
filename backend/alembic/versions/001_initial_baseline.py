"""Initial baseline — marks existing schema as Alembic revision 001.

This migration intentionally performs NO DDL operations (no CREATE TABLE,
no ALTER TABLE, no DROP TABLE).

Background
----------
All tables that existed before Alembic was introduced were created by
``app/migrations.py`` using ``CREATE TABLE IF NOT EXISTS`` statements.
Those tables are considered the baseline schema.  This revision simply
declares "the database is already at this state" so that subsequent
Alembic-managed migrations have a clean starting point.

How to stamp an existing database
----------------------------------
If the RAF Intelligence database already has tables (created by migrations.py)
and you are running Alembic for the first time, stamp the database to this
revision without running any SQL:

    alembic stamp 001_initial_baseline

After stamping, future `alembic upgrade head` calls will only apply migrations
added after this baseline.

If you are provisioning a brand-new database, run migrations.py first
(which happens automatically on app startup) and then stamp:

    # 1. Start the app once to create tables via migrations.py
    # 2. alembic stamp 001_initial_baseline
    # 3. From this point forward use: alembic upgrade head

Tables managed by app/migrations.py (pre-Alembic baseline)
-----------------------------------------------------------
The following tables were in scope when this baseline was established.
New tables added after this revision must be created via Alembic migrations,
not by modifying migrations.py.

    - users
    - refresh_tokens
    - audit_log
    - raf_scores
    - analysis_results
    - suspect_conditions
    - provider_attestations
    - documents
    - chart_chase_requests
    - emr_connections
    - emr_patient_matches
    - fhir_resources
    - claims
    - submission_batches
    - prospective_conditions
    - awv_visits
    - quality_measures
    - care_gaps
    - cohorts
    - cohort_members
    - cohort_snapshots
    - adt_messages
    - webhook_subscriptions
    - webhook_deliveries
    - notification_configs
    - direct_messages
    - background_jobs
    - sync_logs
    - phi_access_log
    - benchmarks
    - provider_scorecard_cache
    - coder_worklist
    - realtime_alerts
    - dashboard_configs

Revision ID: 001_initial_baseline
Revises:
Create Date: 2026-04-06 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "001_initial_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No-op: all tables in the baseline schema were created by app/migrations.py.
    # This revision exists solely to give Alembic a starting point.
    pass


def downgrade() -> None:
    # Downgrading below the baseline is not supported.
    # Dropping all tables would destroy production data; use a database backup
    # and restore procedure instead.
    pass
