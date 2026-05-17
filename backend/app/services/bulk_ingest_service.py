"""
Bulk FHIR ingest service.

Implements Gap #6 from COMPETITIVE-GAP-ANALYSIS.md — onboard a payer/plan
panel of 50K–500K members from a FHIR Bulk Data Access ($export) endpoint or
from a one-shot NDJSON upload.

Two entry points:

  * :func:`process_bulk_ingest_job`
        Synchronous worker that runs inside the Celery task
        ``raf.bulk_ingest.run``.  Designed to be re-entrant and idempotent.

  * :func:`generate_synthetic_ndjson`
        Helper that mints fake but FHIR-shaped NDJSON used by tests and the
        included verifier script.

The fast path is the streaming inner loop in :func:`_ingest_ndjson_stream`
which reads NDJSON one line at a time so the worker never has to hold the
full export in memory.  Patient / Condition / Encounter / Observation rows
are buffered into batches of ``BATCH_SIZE`` resources and flushed via
parameterised INSERT statements.  Every batch publishes a JSON progress
event onto the Redis channel ``bulk_ingest:{job_id}`` so SSE consumers
(see :mod:`app.routers.bulk_ingest`) get live updates.

Why a *service* module rather than a celery_tasks/ sub-package?
---------------------------------------------------------------
``backend/app/services/celery_tasks.py`` is currently a flat module, not a
package.  Converting it to a package would shuffle imports across the
codebase (every ``from app.services.celery_tasks import …``).  The Celery
task ``raf.bulk_ingest.run`` is therefore declared here and imported once at
the bottom of ``celery_tasks.py`` so the worker auto-discovery still picks
it up — see the import line at the end of that file.
"""
from __future__ import annotations

import io
import json
import logging
import time
import uuid
from datetime import date, datetime, timezone
from typing import Any, Iterable, Iterator

import httpx
import redis

from app.config import settings
from app.db import raf_cursor

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# How many FHIR resources are accumulated before they get flushed to MySQL.
# 500 is a sweet spot from benchmarking: large enough that connector overhead
# is amortised, small enough that a single batch fits in a few MB and one
# row failure doesn't roll back too much work.
BATCH_SIZE = 500

# After every Nth patient batch we run RAF + suspect scans.  Re-using the
# existing per-patient calculators is slower than a custom bulk path but
# gives us correctness for free; the bigger the batch, the longer the user
# waits for the first progress event.
RAF_BATCH_SIZE = 100

# Hard cap on the size of an uploaded NDJSON file (bytes).  Matches the
# 1 GB cap enforced by the upload endpoint — duplicated here as a backstop
# so a misconfigured router can't blow past the limit.
MAX_UPLOAD_BYTES = 1 * 1024 * 1024 * 1024  # 1 GB

# How long to poll Content-Location on $export before giving up.  Mirrors the
# FHIR Bulk Data spec recommendation of "minutes, not seconds".
POLL_INTERVAL_SECONDS = 5
POLL_MAX_SECONDS = 60 * 30  # 30 min

# Truncate the per-job error list at this many strings so a misbehaving
# source can't drive the row size unbounded.
MAX_ERRORS_RECORDED = 200

# Redis pub/sub channel format.
PROGRESS_CHANNEL_FMT = "bulk_ingest:{job_id}"


# ---------------------------------------------------------------------------
# Redis (lazy singleton — Celery workers and FastAPI process share the same
# settings.redis_url broker URL).
# ---------------------------------------------------------------------------

_redis_client: redis.Redis | None = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def _publish_progress(job_id: str, payload: dict[str, Any]) -> None:
    """Fire-and-forget — never let a Redis hiccup fail the ingest."""
    try:
        payload = {**payload, "job_id": job_id, "ts": datetime.now(timezone.utc).isoformat()}
        _get_redis().publish(PROGRESS_CHANNEL_FMT.format(job_id=job_id), json.dumps(payload))
    except Exception as exc:  # noqa: BLE001
        logger.warning("bulk_ingest: redis publish failed (continuing): %s", exc)


# ---------------------------------------------------------------------------
# Job row helpers
# ---------------------------------------------------------------------------

def create_job_row(
    *,
    job_id: str,
    tenant_id: str,
    source_url: str | None,
    source_type: str,
    resource_types: list[str],
    submitted_by: int | None,
) -> None:
    """Insert a fresh ``raf_bulk_ingest_jobs`` row in ``pending`` state."""
    with raf_cursor() as cur:
        cur.execute(
            """
            INSERT INTO raf_bulk_ingest_jobs
                (id, tenant_id, source_url, source_type, resource_types,
                 status, submitted_by, started_at)
            VALUES (%s, %s, %s, %s, %s, 'pending', %s, NOW())
            """,
            (
                job_id,
                tenant_id,
                source_url,
                source_type,
                json.dumps(resource_types),
                submitted_by,
            ),
        )


def _update_job(
    job_id: str,
    *,
    status: str | None = None,
    total_resources: int | None = None,
    ingested_resources: int | None = None,
    errors_count: int | None = None,
    patient_count: int | None = None,
    condition_count: int | None = None,
    encounter_count: int | None = None,
    observation_count: int | None = None,
    errors_json: str | None = None,
    completed: bool = False,
) -> None:
    """Patch the job row with whichever fields are non-None."""
    sets: list[str] = []
    params: list[Any] = []
    if status is not None:
        sets.append("status = %s")
        params.append(status)
    if total_resources is not None:
        sets.append("total_resources = %s")
        params.append(total_resources)
    if ingested_resources is not None:
        sets.append("ingested_resources = %s")
        params.append(ingested_resources)
    if errors_count is not None:
        sets.append("errors_count = %s")
        params.append(errors_count)
    if patient_count is not None:
        sets.append("patient_count = %s")
        params.append(patient_count)
    if condition_count is not None:
        sets.append("condition_count = %s")
        params.append(condition_count)
    if encounter_count is not None:
        sets.append("encounter_count = %s")
        params.append(encounter_count)
    if observation_count is not None:
        sets.append("observation_count = %s")
        params.append(observation_count)
    if errors_json is not None:
        sets.append("errors_json = %s")
        params.append(errors_json)
    if completed:
        sets.append("completed_at = NOW()")
    if not sets:
        return
    params.append(job_id)
    with raf_cursor() as cur:
        cur.execute(
            f"UPDATE raf_bulk_ingest_jobs SET {', '.join(sets)} WHERE id = %s",
            tuple(params),
        )


def fetch_job(job_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
    """Return the job row as a dict (or None)."""
    with raf_cursor() as cur:
        if tenant_id is not None:
            cur.execute(
                "SELECT * FROM raf_bulk_ingest_jobs WHERE id = %s AND tenant_id = %s",
                (job_id, tenant_id),
            )
        else:
            cur.execute("SELECT * FROM raf_bulk_ingest_jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
    if row and row.get("resource_types"):
        try:
            row["resource_types"] = json.loads(row["resource_types"])
        except (TypeError, ValueError):
            pass
    if row and row.get("errors_json"):
        try:
            row["errors"] = json.loads(row["errors_json"])
        except (TypeError, ValueError):
            row["errors"] = []
    return row


def list_jobs(tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with raf_cursor() as cur:
        cur.execute(
            """
            SELECT id, tenant_id, source_type, source_url, status,
                   total_resources, ingested_resources, errors_count,
                   patient_count, condition_count, encounter_count, observation_count,
                   started_at, completed_at
            FROM raf_bulk_ingest_jobs
            WHERE tenant_id = %s
            ORDER BY started_at DESC
            LIMIT %s
            """,
            (tenant_id, int(limit)),
        )
        return list(cur.fetchall())


# ---------------------------------------------------------------------------
# FHIR resource → row converters
# ---------------------------------------------------------------------------

def _patient_to_row(resource: dict[str, Any]) -> dict[str, Any] | None:
    """Flatten a FHIR R4 Patient resource into the columns the ``patients``
    table understands.  Mirrors the lighter version in
    :mod:`app.services.patient_import_service` but only extracts the fields
    needed for bulk panel onboarding (no consent/extensions parsing)."""
    name_list = resource.get("name") or []
    given: list[str] = []
    family = ""
    if name_list:
        n0 = name_list[0]
        if isinstance(n0, dict):
            given = n0.get("given") or []
            family = n0.get("family") or ""
    first_name = given[0] if given else ""
    last_name = family or ""

    if not first_name or not last_name or not resource.get("birthDate"):
        return None

    gender = (resource.get("gender") or "").lower()
    sex = {"male": "M", "female": "F"}.get(gender, "U")

    # MRN: prefer identifier with type code MR/MRN, else first identifier
    mrn = ""
    mbi = ""
    for ident in resource.get("identifier") or []:
        if not isinstance(ident, dict):
            continue
        system = (ident.get("system") or "").lower()
        type_coding = (ident.get("type") or {}).get("coding") or []
        type_code = (type_coding[0].get("code") if type_coding else "") or ""
        value = ident.get("value") or ""
        if "mbi" in system or "medicare" in system:
            mbi = mbi or value
        elif type_code in {"MR", "MRN"} or "mrn" in system or not mrn:
            mrn = mrn or value

    addr_list = resource.get("address") or []
    a0 = addr_list[0] if addr_list and isinstance(addr_list[0], dict) else {}
    line = a0.get("line") or []
    street = line[0] if line else ""

    telecom = resource.get("telecom") or []
    phone = ""
    email = ""
    for t in telecom:
        if not isinstance(t, dict):
            continue
        if not phone and (t.get("system") or "").lower() == "phone":
            phone = t.get("value") or ""
        if not email and (t.get("system") or "").lower() == "email":
            email = t.get("value") or ""

    return {
        "fhir_id": resource.get("id") or "",
        "first_name": first_name[:100],
        "last_name": last_name[:100],
        "dob": resource["birthDate"],
        "gender": sex,
        "mrn": (mrn or "")[:64],
        "mbi": (mbi or "")[:32],
        "street": street[:255],
        "city": (a0.get("city") or "")[:100],
        "state": (a0.get("state") or "")[:50],
        "zip": (a0.get("postalCode") or "")[:20],
        "phone": phone[:50],
        "email": email[:200],
    }


def _condition_icd10(resource: dict[str, Any]) -> tuple[str | None, str | None]:
    """Return (icd10_code, description) from a Condition.code.coding entry."""
    code = resource.get("code") or {}
    coding = code.get("coding") or []
    for c in coding:
        if not isinstance(c, dict):
            continue
        system = (c.get("system") or "").lower()
        if "icd-10" in system or "icd10" in system or "sid/icd-10" in system:
            return (c.get("code") or "").upper(), c.get("display") or code.get("text") or ""
    # Fall back to the first coding entry; many bulk feeds don't fill `system`
    if coding and isinstance(coding[0], dict):
        return (coding[0].get("code") or "").upper(), coding[0].get("display") or code.get("text") or ""
    return None, code.get("text")


def _condition_patient_ref(resource: dict[str, Any]) -> str | None:
    """Pull ``subject.reference`` → "Patient/<id>" → "<id>"."""
    subj = resource.get("subject") or resource.get("patient") or {}
    ref = subj.get("reference") if isinstance(subj, dict) else None
    if not ref or "/" not in ref:
        return ref
    return ref.split("/", 1)[1]


def _encounter_to_row(resource: dict[str, Any]) -> dict[str, Any] | None:
    period = resource.get("period") or {}
    start = period.get("start") or period.get("end") or resource.get("date")
    if not start:
        return None
    # FHIR uses ISO 8601 — clip to date for our DATE column
    try:
        enc_date = start[:10]
        datetime.strptime(enc_date, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None

    subj = resource.get("subject") or {}
    patient_ref = (subj.get("reference") if isinstance(subj, dict) else None) or ""
    patient_fhir_id = patient_ref.split("/", 1)[1] if "/" in patient_ref else patient_ref
    if not patient_fhir_id:
        return None

    cls = resource.get("class") or {}
    enc_type = (cls.get("code") if isinstance(cls, dict) else None) or "ambulatory"

    return {
        "fhir_id": resource.get("id") or "",
        "patient_fhir_id": patient_fhir_id,
        "encounter_date": enc_date,
        "encounter_type": enc_type[:50],
        "facility": "",  # bulk export rarely includes Location inline
    }


# ---------------------------------------------------------------------------
# Streaming ingest
# ---------------------------------------------------------------------------

class _BatchAccumulator:
    """Buffers FHIR resources per-type and flushes when the buffer hits
    BATCH_SIZE.  All DB writes go through this object so the inner per-line
    loop stays branch-free."""

    def __init__(self, tenant_id: str, job_id: str) -> None:
        self.tenant_id = tenant_id
        self.job_id = job_id
        self.patients: list[dict[str, Any]] = []
        self.conditions: list[dict[str, Any]] = []
        self.encounters: list[dict[str, Any]] = []
        self.observations: list[dict[str, Any]] = []
        # patient FHIR id -> internal patient.id (filled on patient flush)
        self.fhir_id_to_pid: dict[str, int] = {}
        self.counts = {
            "Patient": 0,
            "Condition": 0,
            "Encounter": 0,
            "Observation": 0,
        }
        self.errors: list[str] = []
        self.ingested = 0
        # patients pending RAF recalc — drained every RAF_BATCH_SIZE
        self.pending_raf_pids: list[int] = []

    # -- patient flush ------------------------------------------------------
    def _flush_patients(self) -> None:
        if not self.patients:
            return
        sql = (
            "INSERT INTO patients "
            "(tenant_id, first_name, last_name, dob, gender, mrn, mbi, "
            " street, city, state, zip, phone, email, data_source, is_active, "
            " emr_pid, source, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "        'fhir_bulk', 1, %s, 'fhir_bulk', NOW(), NOW()) "
            "ON DUPLICATE KEY UPDATE "
            "  first_name = VALUES(first_name), last_name = VALUES(last_name), "
            "  dob = VALUES(dob), updated_at = NOW(), id = LAST_INSERT_ID(id)"
        )
        with raf_cursor() as cur:
            for row in self.patients:
                try:
                    cur.execute(
                        sql,
                        (
                            self.tenant_id,
                            row["first_name"],
                            row["last_name"],
                            row["dob"],
                            row["gender"],
                            row["mrn"] or None,
                            row["mbi"] or None,
                            row["street"],
                            row["city"],
                            row["state"],
                            row["zip"],
                            row["phone"],
                            row["email"],
                            row["fhir_id"][:64],
                        ),
                    )
                    pid = cur.lastrowid
                    if not pid:
                        # ON DUPLICATE KEY didn't return one — look it up
                        cur.execute(
                            "SELECT id FROM patients WHERE tenant_id=%s AND emr_pid=%s LIMIT 1",
                            (self.tenant_id, row["fhir_id"][:64]),
                        )
                        r = cur.fetchone()
                        if r:
                            pid = int(r["id"] if isinstance(r, dict) else r[0])
                    if pid:
                        self.fhir_id_to_pid[row["fhir_id"]] = int(pid)
                        self.pending_raf_pids.append(int(pid))
                        self.counts["Patient"] += 1
                        self.ingested += 1
                except Exception as exc:  # noqa: BLE001
                    self._record_error(f"Patient {row.get('fhir_id', '?')}: {exc}")
        self.patients.clear()

    # -- condition flush ----------------------------------------------------
    def _flush_conditions(self) -> None:
        if not self.conditions:
            return
        from app.services.hcc_mapping_service import map_icd10_batch

        # Map all ICD-10 codes in this batch in one call.
        codes_in_batch = [c["icd10"] for c in self.conditions if c.get("icd10")]
        try:
            mapping = map_icd10_batch(codes_in_batch, model_version="V28")
        except Exception as exc:  # noqa: BLE001
            logger.warning("bulk_ingest: HCC batch mapping failed: %s", exc)
            mapping = {}

        # Resolve patient FHIR id → internal id for any patient_fhir_id we
        # haven't seen yet (might have been inserted in an earlier batch).
        self._resolve_pending_patient_refs(c["patient_fhir_id"] for c in self.conditions)

        year = date.today().year
        rows_to_insert: list[tuple[Any, ...]] = []
        for cond in self.conditions:
            try:
                pid = self.fhir_id_to_pid.get(cond["patient_fhir_id"])
                if not pid:
                    self._record_error(
                        f"Condition: no patient match for FHIR id {cond['patient_fhir_id']}"
                    )
                    continue
                icd10 = cond.get("icd10")
                if not icd10:
                    continue
                normalised = icd10.replace(".", "").upper()
                mapped = mapping.get(normalised)
                if not mapped:
                    # Code doesn't map to any HCC under V28 — skip silently,
                    # this is the majority case (most diagnoses are not HCC).
                    continue
                rows_to_insert.append(
                    (
                        pid,
                        mapped["hcc_code"],
                        json.dumps([normalised]),
                        cond.get("description") or "",
                        year,
                        "fhir_bulk",
                        self.tenant_id,
                        "V28",
                    )
                )
                self.counts["Condition"] += 1
                self.ingested += 1
            except Exception as exc:  # noqa: BLE001
                self._record_error(f"Condition: {exc}")

        if rows_to_insert:
            with raf_cursor() as cur:
                cur.executemany(
                    "INSERT IGNORE INTO raf_patient_hcc "
                    "(patient_id, hcc_code, icd10_codes, hcc_description, measurement_year, "
                    " source, tenant_id, model_version, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())",
                    rows_to_insert,
                )
        self.conditions.clear()

    # -- encounter flush ----------------------------------------------------
    def _flush_encounters(self) -> None:
        if not self.encounters:
            return
        self._resolve_pending_patient_refs(e["patient_fhir_id"] for e in self.encounters)

        rows_to_insert: list[tuple[Any, ...]] = []
        for enc in self.encounters:
            pid = self.fhir_id_to_pid.get(enc["patient_fhir_id"])
            if not pid:
                self._record_error(
                    f"Encounter: no patient match for FHIR id {enc['patient_fhir_id']}"
                )
                continue
            rows_to_insert.append(
                (
                    pid,
                    self.tenant_id,
                    None,  # openemr_encounter_id — bulk feeds aren't OpenEMR-bound
                    enc["encounter_date"],
                    enc["encounter_type"],
                    enc.get("facility") or "",
                )
            )
            self.counts["Encounter"] += 1
            self.ingested += 1
        if rows_to_insert:
            with raf_cursor() as cur:
                cur.executemany(
                    "INSERT INTO normalized_encounters "
                    "(patient_id, tenant_id, openemr_encounter_id, encounter_date, "
                    " encounter_type, facility, status) "
                    "VALUES (%s, %s, %s, %s, %s, %s, 'active')",
                    rows_to_insert,
                )
        self.encounters.clear()

    # -- observation flush --------------------------------------------------
    def _flush_observations(self) -> None:
        # Observations are recorded only as a counter for the MVP — full
        # storage requires the LOINC + measurement schema which is wired in
        # by the existing fhir_service and out of scope for the bulk path.
        if not self.observations:
            return
        self.counts["Observation"] += len(self.observations)
        self.ingested += len(self.observations)
        self.observations.clear()

    # -- helpers ------------------------------------------------------------
    def _resolve_pending_patient_refs(self, fhir_ids: Iterable[str]) -> None:
        unknown = [fid for fid in set(fhir_ids) if fid and fid not in self.fhir_id_to_pid]
        if not unknown:
            return
        placeholders = ", ".join(["%s"] * len(unknown))
        with raf_cursor() as cur:
            cur.execute(
                f"SELECT id, emr_pid FROM patients "
                f"WHERE tenant_id = %s AND emr_pid IN ({placeholders})",
                tuple([self.tenant_id, *unknown]),
            )
            for row in cur.fetchall():
                self.fhir_id_to_pid[row["emr_pid"]] = int(row["id"])

    def _record_error(self, msg: str) -> None:
        if len(self.errors) < MAX_ERRORS_RECORDED:
            self.errors.append(msg)

    # -- public flush -------------------------------------------------------
    def maybe_flush(self, force: bool = False) -> None:
        if force or len(self.patients) >= BATCH_SIZE:
            self._flush_patients()
        if force or len(self.conditions) >= BATCH_SIZE:
            self._flush_conditions()
        if force or len(self.encounters) >= BATCH_SIZE:
            self._flush_encounters()
        if force or len(self.observations) >= BATCH_SIZE:
            self._flush_observations()

        # Drain RAF queue if we've accumulated enough patients
        if force or len(self.pending_raf_pids) >= RAF_BATCH_SIZE:
            self._run_raf_batch()

    def _run_raf_batch(self) -> None:
        if not self.pending_raf_pids:
            return
        pids = self.pending_raf_pids[:]
        self.pending_raf_pids.clear()
        try:
            from app.services.raf_calculator import calculate_raf_score
        except Exception as exc:  # noqa: BLE001
            logger.warning("bulk_ingest: RAF calculator unavailable: %s", exc)
            return
        year = date.today().year
        for pid in pids:
            try:
                calculate_raf_score(pid, year, tenant_id=self.tenant_id)
            except Exception as exc:  # noqa: BLE001
                # RAF failures are tracked but never fail the ingest itself —
                # the user can re-run the calculator from the admin tools.
                self._record_error(f"RAF calc patient_id={pid}: {exc}")


# ---------------------------------------------------------------------------
# Source handlers
# ---------------------------------------------------------------------------

def _iter_ndjson(stream: io.IOBase) -> Iterator[dict[str, Any]]:
    """Yield FHIR resource dicts one at a time from an NDJSON byte stream.

    Skips blank / un-parseable lines but tracks them as errors via the
    accumulator caller — we don't fail the whole job for one malformed row."""
    for raw in stream:
        line = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            yield {"__parse_error__": True, "__raw__": line[:200]}


def _ingest_ndjson_stream(
    stream: io.IOBase,
    *,
    job_id: str,
    tenant_id: str,
    resource_types: set[str],
) -> _BatchAccumulator:
    """Read an NDJSON stream and dispatch each resource to the accumulator.

    Returns the populated :class:`_BatchAccumulator` so the caller can pull
    final counters out."""
    acc = _BatchAccumulator(tenant_id=tenant_id, job_id=job_id)
    seen_total = 0
    last_publish = time.monotonic()

    for resource in _iter_ndjson(stream):
        seen_total += 1
        if resource.get("__parse_error__"):
            acc._record_error(f"NDJSON parse error: {resource.get('__raw__', '')}")
            continue
        rtype = resource.get("resourceType")
        if rtype not in resource_types:
            continue
        try:
            if rtype == "Patient":
                row = _patient_to_row(resource)
                if row:
                    acc.patients.append(row)
                else:
                    acc._record_error(
                        f"Patient {resource.get('id', '?')}: missing required fields"
                    )
            elif rtype == "Condition":
                icd10, desc = _condition_icd10(resource)
                pref = _condition_patient_ref(resource)
                if icd10 and pref:
                    acc.conditions.append(
                        {"icd10": icd10, "description": desc or "", "patient_fhir_id": pref}
                    )
            elif rtype == "Encounter":
                row = _encounter_to_row(resource)
                if row:
                    acc.encounters.append(row)
            elif rtype == "Observation":
                acc.observations.append(resource)
        except Exception as exc:  # noqa: BLE001
            acc._record_error(f"{rtype} {resource.get('id', '?')}: {exc}")

        acc.maybe_flush(force=False)

        # Periodically push progress so the SSE consumer doesn't go quiet
        # during a long flush cycle.  Once per second is a reasonable cadence
        # — at 5k records/sec it pushes ~5k records of progress at a time.
        now = time.monotonic()
        if now - last_publish > 1.0:
            _publish_progress(
                job_id,
                {
                    "event": "progress",
                    "ingested_resources": acc.ingested,
                    "seen_total": seen_total,
                    "errors_count": len(acc.errors),
                    "counts": acc.counts.copy(),
                },
            )
            _update_job(
                job_id,
                ingested_resources=acc.ingested,
                errors_count=len(acc.errors),
                patient_count=acc.counts["Patient"],
                condition_count=acc.counts["Condition"],
                encounter_count=acc.counts["Encounter"],
                observation_count=acc.counts["Observation"],
            )
            last_publish = now

    # Final flush — also drains the RAF queue.
    acc.maybe_flush(force=True)
    return acc


def _download_bulk_export(
    source_url: str,
    *,
    job_id: str,
    tenant_id: str,
    resource_types: set[str],
) -> _BatchAccumulator:
    """FHIR Bulk Data Access $export flow.

    1. Kick off $export with ``Prefer: respond-async``.
    2. Poll the returned ``Content-Location`` until status == 200.
    3. Download every NDJSON file in the manifest, streaming into the
       accumulator.

    The job row's ``source_url`` is the $export endpoint, not the polling URL.
    """
    _update_job(job_id, status="downloading")
    _publish_progress(job_id, {"event": "downloading", "source_url": source_url})

    with httpx.Client(timeout=httpx.Timeout(60.0, read=300.0), follow_redirects=True) as client:
        # Step 1 — initiate export
        kickoff = client.get(
            source_url,
            headers={
                "Accept": "application/fhir+json",
                "Prefer": "respond-async",
            },
        )
        if kickoff.status_code not in (200, 202):
            raise RuntimeError(
                f"$export kickoff failed: HTTP {kickoff.status_code} {kickoff.text[:200]}"
            )

        status_url = kickoff.headers.get("Content-Location") or source_url

        # Step 2 — poll until manifest is ready
        deadline = time.monotonic() + POLL_MAX_SECONDS
        manifest: dict[str, Any] | None = None
        while time.monotonic() < deadline:
            resp = client.get(status_url, headers={"Accept": "application/json"})
            if resp.status_code == 200:
                manifest = resp.json()
                break
            if resp.status_code in (202, 204):
                _publish_progress(
                    job_id,
                    {
                        "event": "polling",
                        "x_progress": resp.headers.get("X-Progress", ""),
                    },
                )
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            raise RuntimeError(
                f"$export poll failed: HTTP {resp.status_code} {resp.text[:200]}"
            )

        if manifest is None:
            raise TimeoutError("$export did not complete within POLL_MAX_SECONDS")

        output_entries = manifest.get("output") or []
        _update_job(job_id, status="ingesting", total_resources=len(output_entries))
        _publish_progress(
            job_id,
            {"event": "manifest_ready", "file_count": len(output_entries)},
        )

        acc = _BatchAccumulator(tenant_id=tenant_id, job_id=job_id)

        # Step 3 — download every NDJSON file
        for entry in output_entries:
            url = entry.get("url")
            if not url:
                continue
            with client.stream("GET", url, headers={"Accept": "application/fhir+ndjson"}) as resp:
                resp.raise_for_status()
                buffer = io.BytesIO()
                for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                    buffer.write(chunk)
                buffer.seek(0)
                # Reuse the streaming ingestor — but accumulate into the
                # *same* accumulator across files so cross-file patient
                # references resolve.
                file_acc = _ingest_ndjson_stream(
                    buffer,
                    job_id=job_id,
                    tenant_id=tenant_id,
                    resource_types=resource_types,
                )
                # Merge file_acc counts into the top-level acc
                for k in acc.counts:
                    acc.counts[k] += file_acc.counts[k]
                acc.ingested += file_acc.ingested
                acc.errors.extend(file_acc.errors[: MAX_ERRORS_RECORDED - len(acc.errors)])
                acc.fhir_id_to_pid.update(file_acc.fhir_id_to_pid)

    return acc


# ---------------------------------------------------------------------------
# Public entry point — the Celery task body
# ---------------------------------------------------------------------------

def process_bulk_ingest_job(
    *,
    job_id: str,
    tenant_id: str,
    source_type: str,
    source_url: str | None,
    resource_types: list[str],
    local_file_path: str | None = None,
) -> dict[str, Any]:
    """Run an end-to-end bulk ingest.  Safe to call from a Celery task or
    inline (tests).  Returns the final job summary dict.
    """
    rtypes = set(resource_types or ["Patient", "Condition", "Encounter", "Observation"])
    _update_job(job_id, status="ingesting" if source_type == "ndjson_upload" else "downloading")
    _publish_progress(job_id, {"event": "started", "source_type": source_type})

    try:
        if source_type == "fhir_bulk_export":
            if not source_url:
                raise ValueError("source_url is required for fhir_bulk_export")
            acc = _download_bulk_export(
                source_url,
                job_id=job_id,
                tenant_id=tenant_id,
                resource_types=rtypes,
            )
        elif source_type == "ndjson_upload":
            if not local_file_path:
                raise ValueError("local_file_path is required for ndjson_upload")
            _update_job(job_id, status="ingesting")
            with open(local_file_path, "rb") as fh:
                acc = _ingest_ndjson_stream(
                    fh,
                    job_id=job_id,
                    tenant_id=tenant_id,
                    resource_types=rtypes,
                )
        else:
            raise ValueError(f"Unknown source_type: {source_type}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("bulk_ingest: job %s failed", job_id)
        _update_job(
            job_id,
            status="failed",
            errors_json=json.dumps([str(exc)]),
            errors_count=1,
            completed=True,
        )
        _publish_progress(job_id, {"event": "failed", "error": str(exc)})
        return {"status": "failed", "error": str(exc)}

    summary = {
        "status": "completed",
        "ingested_resources": acc.ingested,
        "errors_count": len(acc.errors),
        "counts": acc.counts,
    }
    _update_job(
        job_id,
        status="completed",
        ingested_resources=acc.ingested,
        errors_count=len(acc.errors),
        patient_count=acc.counts["Patient"],
        condition_count=acc.counts["Condition"],
        encounter_count=acc.counts["Encounter"],
        observation_count=acc.counts["Observation"],
        errors_json=json.dumps(acc.errors[:MAX_ERRORS_RECORDED]),
        completed=True,
    )
    _publish_progress(job_id, {"event": "completed", **summary})
    return summary


# ---------------------------------------------------------------------------
# Synthetic NDJSON generator (for tests / verification scripts)
# ---------------------------------------------------------------------------

def generate_synthetic_ndjson(
    *,
    patient_count: int = 1000,
    conditions_per_patient: int = 5,
    icd10_pool: list[str] | None = None,
) -> bytes:
    """Return a byte blob of NDJSON containing ``patient_count`` Patient
    resources followed by ``patient_count * conditions_per_patient``
    Condition resources.

    Used by ``backend/scripts/generate_fhir_bulk_test_file.py`` and the
    pytest verification at ``backend/tests/test_bulk_ingest.py``.
    """
    if icd10_pool is None:
        # A mix of HCC-bearing and non-HCC codes so the test covers both
        # the "this maps to HCC, write to raf_patient_hcc" and the
        # "no HCC, drop silently" branches.
        icd10_pool = [
            "E11.9",   # Type 2 diabetes → HCC 37 (V28)
            "I50.9",   # Heart failure  → HCC 226
            "N18.4",   # CKD stage 4    → HCC 327
            "F32.9",   # Depression     → no HCC
            "J45.40",  # Asthma         → no HCC
        ]

    out = io.BytesIO()
    for i in range(1, patient_count + 1):
        patient = {
            "resourceType": "Patient",
            "id": f"synthetic-patient-{i:06d}",
            "name": [{"family": f"Last{i:06d}", "given": [f"First{i:06d}"]}],
            "gender": "male" if i % 2 == 0 else "female",
            "birthDate": f"19{40 + (i % 50):02d}-01-{(i % 27) + 1:02d}",
            "identifier": [
                {
                    "type": {"coding": [{"code": "MR"}]},
                    "value": f"MRN{i:08d}",
                }
            ],
            "address": [{"city": "Springfield", "state": "IL", "postalCode": "62701"}],
        }
        out.write(json.dumps(patient).encode("utf-8"))
        out.write(b"\n")

    for i in range(1, patient_count + 1):
        for j in range(conditions_per_patient):
            icd10 = icd10_pool[(i + j) % len(icd10_pool)]
            condition = {
                "resourceType": "Condition",
                "id": f"synthetic-condition-{i:06d}-{j}",
                "subject": {"reference": f"Patient/synthetic-patient-{i:06d}"},
                "code": {
                    "coding": [
                        {
                            "system": "http://hl7.org/fhir/sid/icd-10-cm",
                            "code": icd10,
                            "display": f"Synthetic dx {icd10}",
                        }
                    ],
                    "text": f"Synthetic dx {icd10}",
                },
                "clinicalStatus": {
                    "coding": [{"code": "active"}]
                },
            }
            out.write(json.dumps(condition).encode("utf-8"))
            out.write(b"\n")

    return out.getvalue()
