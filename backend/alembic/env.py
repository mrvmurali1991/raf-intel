"""
Alembic migration environment for RAF Intelligence.

This env.py is intentionally thin — it delegates all database connection
configuration to ``app.config.settings`` so that the same .env file used
by the FastAPI app also drives migrations.  No credentials are hardcoded
here or in alembic.ini.

Supported invocation modes
--------------------------
Online mode  (default):
    alembic upgrade head

Offline mode (generates SQL without connecting — useful for review / CI):
    alembic upgrade head --sql

MySQL dialect
-------------
Alembic requires a SQLAlchemy-compatible URL.  The app's connection pools
use ``mysql-connector-python`` directly, so we build a separate
``mysql+pymysql://`` URL here purely for Alembic.  PyMySQL is a pure-Python
driver that SQLAlchemy supports natively and requires no C extensions.

The RAF database (``raf_intelligence``) is the target for all Alembic-managed
migrations.  The OpenEMR schema is managed externally by OpenEMR itself and
is never modified by these migrations.
"""
from __future__ import annotations

import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

# ---------------------------------------------------------------------------
# Alembic Config object — gives access to values in alembic.ini
# ---------------------------------------------------------------------------

config = context.config

# Attach Python logging configuration from alembic.ini (the [loggers] section).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")

# ---------------------------------------------------------------------------
# SQLAlchemy MetaData for autogenerate support
#
# If you later add SQLAlchemy ORM models, import their Base here so that
# `alembic revision --autogenerate` can diff them against the live schema.
#
# Example:
#   from app.models.base import Base
#   target_metadata = Base.metadata
#
# For now we set it to None because the existing tables are managed by
# app/migrations.py and Alembic is being introduced alongside that system.
# ---------------------------------------------------------------------------

target_metadata = None


# ---------------------------------------------------------------------------
# Build the database URL from app config
# ---------------------------------------------------------------------------

def _get_database_url() -> str:
    """Construct a SQLAlchemy-compatible MySQL URL from app settings.

    Uses the ``mysql+pymysql`` dialect so that SQLAlchemy can connect without
    needing the C extension that ``mysql-connector-python`` requires.  PyMySQL
    is a pure-Python drop-in that works identically for DDL operations.

    The URL is percent-encoded by SQLAlchemy's ``URL.create`` helper, so
    special characters in passwords are handled correctly.
    """
    from sqlalchemy.engine import URL

    # Import inside the function so that config.py (and its _get_required_credential
    # calls) run only when alembic actually needs the URL, not at module import
    # time.  This avoids confusing errors when alembic --help is run without
    # a .env file present.
    from app.config import settings

    url = URL.create(
        drivername="mysql+pymysql",
        username=settings.raf_db_user,
        password=settings.raf_db_password,
        host=settings.raf_db_host,
        port=settings.raf_db_port,
        database=settings.raf_db_name,
        query={"charset": "utf8mb4"},
    )
    return url


# ---------------------------------------------------------------------------
# Offline migration — emit SQL to stdout without connecting to the database
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    In this mode Alembic emits the migration SQL to stdout (or a file) rather
    than executing it against a live database.  Useful for:
    - Reviewing what a migration will do before applying it
    - Generating SQL for a DBA to apply manually
    - CI pipelines that do not have database access

    Usage:
        alembic upgrade head --sql > migration.sql
    """
    url = _get_database_url()

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # MySQL-specific: include IF EXISTS / IF NOT EXISTS clauses where possible
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migration — connect to the database and execute migrations directly
# ---------------------------------------------------------------------------

def run_migrations_online() -> None:
    """Run migrations in 'online' mode (default).

    Creates a SQLAlchemy engine from the app config URL, acquires a connection,
    and runs all pending migrations.  Uses ``NullPool`` to avoid holding
    connections open after the migration completes — important for short-lived
    CLI invocations.

    Usage:
        alembic upgrade head
        alembic downgrade -1
    """
    url = _get_database_url()

    connectable = create_engine(
        url,
        # NullPool: do not pool connections.  Alembic runs as a CLI tool, not
        # a long-lived server, so connection pooling adds no benefit and can
        # leave idle connections open if the process is killed mid-migration.
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()

    logger.info("Alembic online migration complete.")


# ---------------------------------------------------------------------------
# Entry point — Alembic calls this module directly
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    logger.info("Running Alembic migrations in offline mode.")
    run_migrations_offline()
else:
    logger.info("Running Alembic migrations in online mode.")
    run_migrations_online()
