"""
Celery task wrapper for bulk FHIR ingest.

Lives next to :mod:`app.services.bulk_ingest_service` so the heavy lifting
stays in a plain-Python module that's easy to test inline without booting a
Celery worker.  This file only knows how to:

  1. Receive a Celery task invocation.
  2. Persist progress to ``raf_bulk_ingest_jobs``.
  3. Tear down the temp NDJSON file once the worker is done with it.

Task name: ``raf.bulk_ingest.run`` — routed to the ``heavy`` queue because
panel ingests can run for tens of minutes.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from celery.utils.log import get_task_logger

from app.services.bulk_ingest_service import process_bulk_ingest_job
from app.services.job_service import celery_app

logger = logging.getLogger(__name__)
task_logger = get_task_logger(__name__)


@celery_app.task(
    bind=True,
    name="raf.bulk_ingest.run",
    queue="heavy",
    # 6-hour ceiling for a single ingest — 500K patients × ~3K records/sec
    # comes in well under this on a single worker.
    time_limit=6 * 3600,
    soft_time_limit=int(5.5 * 3600),
    max_retries=2,
    default_retry_delay=120,
)
def task_run_bulk_ingest(
    self,
    *,
    job_id: str,
    tenant_id: str,
    source_type: str,
    source_url: str | None,
    resource_types: list[str],
    local_file_path: str | None = None,
) -> dict[str, Any]:
    """Run a bulk ingest job.  Returns the final summary dict."""
    task_logger.info(
        "bulk_ingest.run: job=%s tenant=%s source_type=%s",
        job_id, tenant_id, source_type,
    )
    try:
        result = process_bulk_ingest_job(
            job_id=job_id,
            tenant_id=tenant_id,
            source_type=source_type,
            source_url=source_url,
            resource_types=resource_types,
            local_file_path=local_file_path,
        )
        return result
    finally:
        # Clean up the uploaded NDJSON file regardless of outcome.  The
        # file lives in a tempfile-owned dir so a failure to remove is a
        # warning, not an error.
        if local_file_path and os.path.exists(local_file_path):
            try:
                os.remove(local_file_path)
            except OSError as exc:
                task_logger.warning(
                    "bulk_ingest: could not remove temp file %s: %s",
                    local_file_path, exc,
                )
