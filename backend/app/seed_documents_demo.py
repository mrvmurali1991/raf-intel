"""
Seed demo documents — idempotent wrapper.

Called at startup from main.py lifespan. Runs the seed_documents.py
script only if the documents table has fewer than 18 rows.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def seed_documents_demo() -> None:
    """Run seed_documents.py if documents table is not already populated."""
    from app.db import raf_cursor

    try:
        with raf_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM documents")
            cnt = cur.fetchone()["cnt"]
            if cnt >= 18:
                logger.info("Demo documents already seeded (%d docs) — skipping.", cnt)
                return
    except Exception as exc:
        logger.warning("Cannot check documents table: %s", exc)
        return

    script = Path(__file__).resolve().parent.parent / "seed_documents.py"
    if not script.exists():
        logger.warning("seed_documents.py not found at %s — skipping.", script)
        return

    logger.info("Seeding demo documents via %s …", script.name)
    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            check=False, capture_output=True,
            text=True,
            timeout=60,
            cwd=str(script.parent),
        )
        if result.returncode == 0:
            logger.info("Demo documents seeded successfully.")
        else:
            logger.error("seed_documents.py failed (rc=%d): %s", result.returncode, result.stderr[:500])
    except Exception as exc:
        logger.error("Failed to run seed_documents.py: %s", exc)
