"""
sync_demographics.py
--------------------
One-shot script to sync phone and preferred_language from OpenEMR into the
RAF Intelligence `patients` table.

For each RAF patient that has an `emr_pid` set, the script:
  1. Strips the emr_pid to an integer (stored as e.g. '35.0' in some rows).
  2. Looks up the matching row in OpenEMR's `patient_data` table.
  3. Updates the RAF patient's `phone` and `preferred_language` columns.

Usage (from the backend/ directory with the app virtualenv active):
    python sync_demographics.py [--dry-run] [--tenant-id TENANT_ID]

Flags:
    --dry-run      Print what would be updated without writing to the DB.
    --tenant-id    RAF tenant_id to filter on (default: "1").
"""

from __future__ import annotations

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync phone/language from OpenEMR → RAF patients.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned updates without writing to the database.",
    )
    parser.add_argument(
        "--tenant-id",
        default="1",
        help="RAF tenant_id to restrict the sync to (default: 1).",
    )
    return parser.parse_args()


def _to_int_pid(raw: str | float | int | None) -> int | None:
    """Convert emr_pid values like '35.0', 35.0, or '35' to integer 35.

    Returns None if the value is missing or cannot be parsed.
    """
    if raw is None:
        return None
    try:
        return int(float(raw))
    except (ValueError, TypeError):
        log.warning("Cannot parse emr_pid %r — skipping.", raw)
        return None


def main() -> int:
    args = parse_args()
    tenant_id: str = args.tenant_id
    dry_run: bool = args.dry_run

    if dry_run:
        log.info("DRY-RUN mode — no changes will be written.")

    # Import here so the module can be parsed without the app context.
    from app.db import openemr_cursor, raf_cursor

    # ------------------------------------------------------------------
    # 1. Fetch all RAF patients that have an emr_pid set.
    # ------------------------------------------------------------------
    with raf_cursor() as raf_cur:
        raf_cur.execute(
            """
            SELECT id, emr_pid, phone, preferred_language
            FROM   patients
            WHERE  tenant_id = %s
              AND  emr_pid IS NOT NULL
              AND  emr_pid <> ''
            ORDER  BY id
            """,
            (tenant_id,),
        )
        raf_patients: list[dict] = raf_cur.fetchall()

    if not raf_patients:
        log.info("No RAF patients with emr_pid found for tenant_id=%s.  Nothing to do.", tenant_id)
        return 0

    log.info("Found %d RAF patient(s) with emr_pid for tenant_id=%s.", len(raf_patients), tenant_id)

    # Build a mapping: integer pid → RAF patient row
    pid_to_raf: dict[int, dict] = {}
    for row in raf_patients:
        pid = _to_int_pid(row["emr_pid"])
        if pid is not None:
            pid_to_raf[pid] = row
        else:
            log.warning("RAF patient id=%s has unparseable emr_pid=%r — skipping.", row["id"], row["emr_pid"])

    if not pid_to_raf:
        log.warning("No valid integer pids could be derived.  Nothing to sync.")
        return 0

    openemr_pids = list(pid_to_raf.keys())

    # ------------------------------------------------------------------
    # 2. Fetch matching rows from OpenEMR patient_data.
    # ------------------------------------------------------------------
    placeholders = ", ".join(["%s"] * len(openemr_pids))
    with openemr_cursor(tenant_id=tenant_id) as emr_cur:
        emr_cur.execute(
            f"""
            SELECT pid, phone_cell, language
            FROM   patient_data
            WHERE  pid IN ({placeholders})
            """,
            tuple(openemr_pids),
        )
        emr_rows: list[dict] = emr_cur.fetchall()

    if not emr_rows:
        log.warning("No matching rows found in OpenEMR patient_data.  Nothing to sync.")
        return 0

    log.info("Retrieved %d OpenEMR patient_data row(s).", len(emr_rows))

    # ------------------------------------------------------------------
    # 3. Reconcile and build update list.
    # ------------------------------------------------------------------
    updates: list[dict] = []
    for emr_row in emr_rows:
        pid = int(emr_row["pid"])
        raf_row = pid_to_raf.get(pid)
        if raf_row is None:
            log.debug("OpenEMR pid=%d has no matching RAF patient — skipping.", pid)
            continue

        new_phone = (emr_row.get("phone_cell") or "").strip() or None
        new_language = (emr_row.get("language") or "").strip() or None

        current_phone = raf_row.get("phone")
        current_language = raf_row.get("preferred_language")

        if new_phone == current_phone and new_language == current_language:
            log.info(
                "RAF id=%s (emr_pid=%s): no change needed (phone=%r, language=%r).",
                raf_row["id"], pid, current_phone, current_language,
            )
            continue

        updates.append(
            {
                "raf_id": raf_row["id"],
                "emr_pid": pid,
                "phone": new_phone,
                "preferred_language": new_language,
                "prev_phone": current_phone,
                "prev_language": current_language,
            }
        )

    if not updates:
        log.info("All patients are already up-to-date.  Nothing to write.")
        return 0

    log.info("%d patient(s) require an update.", len(updates))

    # ------------------------------------------------------------------
    # 4. Apply updates to the RAF patients table.
    # ------------------------------------------------------------------
    for upd in updates:
        log.info(
            "RAF id=%-4s  emr_pid=%-4s  phone: %r → %r  language: %r → %r",
            upd["raf_id"],
            upd["emr_pid"],
            upd["prev_phone"],
            upd["phone"],
            upd["prev_language"],
            upd["preferred_language"],
        )

        if dry_run:
            continue

        with raf_cursor() as raf_cur:
            raf_cur.execute(
                """
                UPDATE patients
                SET    phone              = %s,
                       preferred_language = %s
                WHERE  id                = %s
                  AND  tenant_id         = %s
                """,
                (upd["phone"], upd["preferred_language"], upd["raf_id"], tenant_id),
            )
            if raf_cur.rowcount != 1:
                log.error(
                    "UPDATE affected %d rows for RAF id=%s — expected 1.  Check tenant_id.",
                    raf_cur.rowcount,
                    upd["raf_id"],
                )

    if dry_run:
        log.info("DRY-RUN complete — %d update(s) would have been applied.", len(updates))
    else:
        log.info("Sync complete — %d patient(s) updated.", len(updates))

    return 0


if __name__ == "__main__":
    sys.exit(main())
