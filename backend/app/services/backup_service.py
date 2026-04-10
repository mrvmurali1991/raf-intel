"""
Backup service for RAF Intelligence.

Provides status reporting for existing backup files, schedule info,
and the ability to trigger a new backup via backup.sh as a subprocess.

All paths are resolved relative to the project root (three levels above
this file: backend/app/services/ -> project root).
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

# backend/app/services/backup_service.py  ->  project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

_BACKUP_SCRIPT = _PROJECT_ROOT / "scripts" / "backup.sh"

_DEFAULT_BACKUP_DIR = _PROJECT_ROOT / "data" / "backups"

# ---------------------------------------------------------------------------
# In-memory job registry (survives only for the lifetime of the process)
# ---------------------------------------------------------------------------

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def _backup_dir() -> Path:
    """Return the configured backup directory as an absolute Path."""
    raw = os.getenv("BACKUP_DIR", str(_DEFAULT_BACKUP_DIR))
    # Allow relative paths in BACKUP_DIR (resolved from project root)
    p = Path(raw)
    if not p.is_absolute():
        p = _PROJECT_ROOT / p
    return p


def _parse_timestamp_from_filename(name: str) -> datetime | None:
    """Extract the embedded timestamp from a backup filename.

    Expected pattern: <prefix>_YYYY-MM-DD_HHMMSS.sql.gz
    Returns None when the filename does not match.
    """
    # Strip .sql.gz suffix
    stem = name.removesuffix(".sql.gz")
    parts = stem.rsplit("_", 2)
    if len(parts) < 3:
        return None
    date_part = parts[-2]   # YYYY-MM-DD
    time_part = parts[-1]   # HHMMSS
    try:
        return datetime.strptime(f"{date_part}_{time_part}", "%Y-%m-%d_%H%M%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def get_backup_status() -> dict[str, Any]:
    """Return metadata for all backup files found in BACKUP_DIR.

    Each entry in ``backups`` contains:
    - ``filename``   — bare filename
    - ``size_bytes`` — file size in bytes
    - ``size_human`` — human-readable size (e.g. "12.3 MB")
    - ``created_at`` — ISO-8601 timestamp parsed from filename, or file mtime
    - ``db_target``  — "raf_intelligence", "openemr", or "unknown"
    """
    backup_dir = _backup_dir()
    backups: list[dict[str, Any]] = []

    if not backup_dir.exists():
        return {
            "backup_dir": str(backup_dir),
            "backup_dir_exists": False,
            "count": 0,
            "backups": [],
        }

    for entry in sorted(backup_dir.glob("*.sql.gz"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            stat = entry.stat()
        except OSError:
            continue

        size_bytes = stat.st_size
        size_human = _human_size(size_bytes)

        ts = _parse_timestamp_from_filename(entry.name)
        if ts is None:
            ts = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

        if entry.name.startswith("raf_intelligence"):
            db_target = "raf_intelligence"
        elif entry.name.startswith("openemr"):
            db_target = "openemr"
        else:
            db_target = "unknown"

        backups.append(
            {
                "filename": entry.name,
                "size_bytes": size_bytes,
                "size_human": size_human,
                "created_at": ts.isoformat(),
                "db_target": db_target,
            }
        )

    return {
        "backup_dir": str(backup_dir),
        "backup_dir_exists": True,
        "count": len(backups),
        "backups": backups,
    }


def get_backup_schedule() -> dict[str, Any]:
    """Return the configured backup schedule information.

    In the current implementation backups are run manually (via Makefile or
    cron).  This endpoint surfaces the relevant configuration so that an ops
    dashboard can show what has been configured.
    """
    return {
        "mode": "manual",
        "description": (
            "Backups are triggered manually via 'make backup' or via the "
            "POST /api/admin/backups endpoint. For automated scheduling, "
            "add a cron job that calls ./scripts/backup.sh --full."
        ),
        "retention_days": int(os.getenv("BACKUP_RETENTION_DAYS", "30")),
        "backup_dir": str(_backup_dir()),
        "backup_script": str(_BACKUP_SCRIPT),
    }


def trigger_backup(backup_type: str = "full") -> dict[str, Any]:
    """Launch backup.sh in a background subprocess and return a job record.

    Args:
        backup_type: One of ``"full"``, ``"raf"``, or ``"openemr"``.
                     Maps to the ``--full``, ``--raf-only``, and
                     ``--openemr-only`` flags of backup.sh.

    Returns:
        A dict with ``job_id``, ``status``, ``backup_type``, and
        ``started_at``.  The caller can poll ``get_job_status(job_id)``
        to track completion.

    Raises:
        ValueError: When *backup_type* is not recognised.
        FileNotFoundError: When backup.sh cannot be found.
        RuntimeError: When the subprocess cannot be launched.
    """
    flag_map = {
        "full": "--full",
        "raf": "--raf-only",
        "openemr": "--openemr-only",
    }
    if backup_type not in flag_map:
        raise ValueError(
            f"Invalid backup_type {backup_type!r}. "
            f"Expected one of: {', '.join(flag_map)}"
        )

    if not _BACKUP_SCRIPT.exists():
        raise FileNotFoundError(
            f"backup.sh not found at {_BACKUP_SCRIPT}. "
            "Ensure the scripts directory is present and backup.sh is executable."
        )

    job_id = str(uuid.uuid4())
    started_at = datetime.now(timezone.utc).isoformat()

    job: dict[str, Any] = {
        "job_id": job_id,
        "backup_type": backup_type,
        "flag": flag_map[backup_type],
        "status": "running",
        "started_at": started_at,
        "finished_at": None,
        "exit_code": None,
        "stdout": "",
        "stderr": "",
    }

    with _jobs_lock:
        _jobs[job_id] = job

    # Build an environment that inherits the parent process environment so all
    # DB_* and BACKUP_* variables are available to the shell script.
    env = os.environ.copy()

    def _run() -> None:
        try:
            result = subprocess.run(
                [str(_BACKUP_SCRIPT), flag_map[backup_type]],
                capture_output=True,
                text=True,
                env=env,
                timeout=1800,  # 30-minute hard timeout
            )
            with _jobs_lock:
                _jobs[job_id].update(
                    {
                        "status": "success" if result.returncode == 0 else "failed",
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "exit_code": result.returncode,
                        "stdout": result.stdout[-8000:],   # keep last 8 KB
                        "stderr": result.stderr[-4000:],
                    }
                )
            if result.returncode == 0:
                logger.info("Backup job %s (%s) completed successfully.", job_id, backup_type)
            else:
                logger.error(
                    "Backup job %s (%s) failed (exit %d): %s",
                    job_id,
                    backup_type,
                    result.returncode,
                    result.stderr[-500:],
                )
        except subprocess.TimeoutExpired:
            logger.error("Backup job %s timed out after 30 minutes.", job_id)
            with _jobs_lock:
                _jobs[job_id].update(
                    {
                        "status": "failed",
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "exit_code": -1,
                        "stderr": "Backup process timed out after 30 minutes.",
                    }
                )
        except Exception as exc:
            logger.exception("Unexpected error in backup job %s: %s", job_id, exc)
            with _jobs_lock:
                _jobs[job_id].update(
                    {
                        "status": "failed",
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "exit_code": -1,
                        "stderr": str(exc),
                    }
                )

    thread = threading.Thread(target=_run, name=f"backup-{job_id[:8]}", daemon=True)
    thread.start()

    logger.info(
        "Launched backup job %s (type=%s, flag=%s)",
        job_id,
        backup_type,
        flag_map[backup_type],
    )

    return {
        "job_id": job_id,
        "status": "running",
        "backup_type": backup_type,
        "started_at": started_at,
    }


def get_job_status(job_id: str) -> dict[str, Any] | None:
    """Return the current state of a previously triggered backup job.

    Returns ``None`` when *job_id* is not known.
    """
    with _jobs_lock:
        job = _jobs.get(job_id)
    return dict(job) if job else None


def list_jobs(limit: int = 20) -> list[dict[str, Any]]:
    """Return the most recent backup jobs, newest first."""
    with _jobs_lock:
        jobs = list(_jobs.values())
    jobs.sort(key=lambda j: j["started_at"], reverse=True)
    return [dict(j) for j in jobs[:limit]]


# ---------------------------------------------------------------------------
# Private utilities
# ---------------------------------------------------------------------------


def _human_size(size_bytes: int) -> str:
    """Return a human-readable file size string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0  # type: ignore[assignment]
    return f"{size_bytes:.1f} PB"
