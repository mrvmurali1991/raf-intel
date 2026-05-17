"""
Visual Cohort Builder (v2) router.

Companion API for the drag-and-drop cohort builder UI
(``frontend/src/app/cohorts/builder``).  Intentionally separate from the
legacy ``cohorts.py`` router so the existing cohort UI and stored procedures
are unaffected.

Endpoints
---------
POST /api/cohorts/v2/preview   – live count + sample patient ids for a
                                  given definition (debounced from UI).
POST /api/cohorts/v2            – persist a definition to ``raf_cohorts``.
GET  /api/cohorts/v2            – list the tenant's saved v2 cohorts.

Definition shape
----------------
``{"operator": "AND" | "OR", "clauses": [{"field": ..., "op": ..., "value": ...}, ...]}``

Supported fields:
    - age        (op: gte | lte | eq, value: int)         → patients.dob
    - sex        (op: eq,              value: "M"/"F")     → patients.sex
    - raf_score  (op: gte | lte | eq, value: float)       → raf_scores.final_raf
    - has_hcc    (op: eq,              value: int|str)     → raf_patient_hcc.hcc_code

All endpoints are tenant-scoped and permission-gated (``cohorts``).
"""

# Do NOT use ``from __future__ import annotations`` — breaks FastAPI schema gen.

import json
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.auth import get_current_user, get_tenant_id, require_permission
from app.db import raf_cursor, raf_read_cursor
from app.rate_limit import limiter
from app.services.emr_manager import active_patients_subquery

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cohorts/v2", tags=["cohorts"])

# ---------------------------------------------------------------------------
# Allow-lists — never interpolate user input directly into SQL.
# ---------------------------------------------------------------------------

_ALLOWED_FIELDS: frozenset[str] = frozenset({"age", "raf_score", "has_hcc", "sex"})
_ALLOWED_OPS: frozenset[str] = frozenset({"gte", "lte", "eq"})
_OP_TO_SQL: dict[str, str] = {"gte": ">=", "lte": "<=", "eq": "="}

_MAX_CLAUSES = 20
_SAMPLE_LIMIT = 20


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class Clause(BaseModel):
    field: Literal["age", "raf_score", "has_hcc", "sex"]
    op: Literal["gte", "lte", "eq"]
    value: Any = Field(..., description="Comparison value; type validated per field")

    @field_validator("value")
    @classmethod
    def _check_value_not_none(cls, v: Any) -> Any:  # noqa: D401
        if v is None or (isinstance(v, str) and not v.strip()):
            raise ValueError("clause value must not be empty")
        return v


class Definition(BaseModel):
    operator: Literal["AND", "OR"] = "AND"
    clauses: list[Clause] = Field(default_factory=list)

    @field_validator("clauses")
    @classmethod
    def _check_clause_count(cls, v: list[Clause]) -> list[Clause]:
        if len(v) > _MAX_CLAUSES:
            raise ValueError(f"at most {_MAX_CLAUSES} clauses allowed")
        return v


class PreviewRequest(BaseModel):
    definition: Definition


class SaveRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    definition: Definition


# ---------------------------------------------------------------------------
# Compilation helpers — turn one clause into (sql_fragment, params).
#
# Some clauses reference auxiliary tables (raf_scores, raf_patient_hcc); for
# those we emit a sub-select that resolves back to a patient_id list and join
# it against the patients table outside.  This keeps clause compilation simple
# and uniform regardless of the field source.
# ---------------------------------------------------------------------------

def _compile_clause(clause: Clause, tenant_id: str) -> tuple[str, list[Any]]:
    """Return (sql_fragment_referring_to_p.id, params) for a single clause.

    The fragment is a self-contained boolean expression suitable for ANDing or
    ORing with other clause fragments in a WHERE clause on ``patients p``.
    Sub-queries are tenant-scoped via the standard active_patients_subquery
    helper (HIPAA isolation).
    """
    field = clause.field
    op = clause.op
    if field not in _ALLOWED_FIELDS:
        raise ValueError(f"unsupported field: {field}")
    if op not in _ALLOWED_OPS:
        raise ValueError(f"unsupported op: {op}")
    sql_op = _OP_TO_SQL[op]

    if field == "age":
        try:
            ival = int(clause.value)
        except (TypeError, ValueError) as exc:
            raise ValueError("age clause requires an integer value") from exc
        # TIMESTAMPDIFF on dob — note inverse comparator semantics for >=/<=
        # would flip if computed against (CURDATE() - dob); we keep direct year
        # diff which behaves intuitively (age >= 65 → at least 65 years old).
        return (f"TIMESTAMPDIFF(YEAR, p.dob, CURDATE()) {sql_op} %s", [ival])

    if field == "sex":
        if op != "eq":
            raise ValueError("sex clause only supports op=eq")
        sval = str(clause.value).strip().upper()
        if sval not in {"M", "F", "MALE", "FEMALE", "OTHER", "U", "UNKNOWN"}:
            raise ValueError(f"sex value must be M/F/Male/Female, got {sval!r}")
        # Normalize Male/Female to M/F to match common stored shape, but the
        # DB has both forms in different installs — match either.
        canonical = "M" if sval in {"M", "MALE"} else "F" if sval in {"F", "FEMALE"} else sval
        return ("UPPER(p.sex) IN (%s, %s)", [canonical, sval])

    if field == "raf_score":
        try:
            fval = float(clause.value)
        except (TypeError, ValueError) as exc:
            raise ValueError("raf_score clause requires a numeric value") from exc
        active_frag, active_params = active_patients_subquery(tenant_id)
        sub = (
            f"p.id IN (SELECT patient_id FROM raf_scores "
            f"WHERE final_raf {sql_op} %s AND {active_frag})"
        )
        return (sub, [fval, *active_params])

    if field == "has_hcc":
        # value can be a number (89) or string ("89") referring to hcc_code.
        try:
            hval = int(clause.value)
        except (TypeError, ValueError) as exc:
            raise ValueError("has_hcc clause requires an integer hcc code") from exc
        if op != "eq":
            raise ValueError("has_hcc clause only supports op=eq")
        active_frag, active_params = active_patients_subquery(tenant_id)
        sub = (
            f"p.id IN (SELECT patient_id FROM raf_patient_hcc "
            f"WHERE hcc_code = %s AND {active_frag})"
        )
        return (sub, [hval, *active_params])

    raise ValueError(f"unhandled field: {field}")


def _compile_definition(
    definition: Definition,
    tenant_id: str,
) -> tuple[str, list[Any]]:
    """Compile the full definition to a WHERE clause body and bound params.

    Empty clause list compiles to ``1=1`` (matches all active tenant patients).
    """
    if not definition.clauses:
        return ("1=1", [])
    parts: list[str] = []
    params: list[Any] = []
    for clause in definition.clauses:
        frag, p = _compile_clause(clause, tenant_id)
        parts.append(f"({frag})")
        params.extend(p)
    joiner = " AND " if definition.operator == "AND" else " OR "
    return (joiner.join(parts), params)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/preview", summary="Preview matching patients for a cohort definition")
@limiter.limit("60/minute")
def preview(
    request: Request,
    body: PreviewRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("cohorts", "read")),
) -> dict[str, Any]:
    """Compile the definition to SQL, return matched count + sample patients.

    Sample is limited to the first ``_SAMPLE_LIMIT`` rows ordered by patient
    id for stable previews.  The sample includes ``id``, ``first_name``,
    ``last_name``, and ``mrn`` so the UI can render a recognisable list.
    """
    try:
        where_body, where_params = _compile_definition(body.definition, tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Always tenant-scope the outer query so a definition with zero clauses
    # still respects HIPAA isolation.
    base_where = "p.is_active = 1 AND p.tenant_id = %s"
    full_where = f"{base_where} AND ({where_body})"
    count_sql = f"SELECT COUNT(*) AS cnt FROM patients p WHERE {full_where}"
    sample_sql = (
        f"SELECT p.id, p.first_name, p.last_name, p.mrn "
        f"FROM patients p WHERE {full_where} ORDER BY p.id LIMIT %s"
    )
    params_count = [tenant_id, *where_params]
    params_sample = [tenant_id, *where_params, _SAMPLE_LIMIT]

    try:
        with raf_read_cursor() as cur:
            cur.execute(count_sql, params_count)
            row = cur.fetchone() or {}
            matched = int(row.get("cnt") or 0)
            cur.execute(sample_sql, params_sample)
            rows = cur.fetchall() or []
    except Exception as exc:
        logger.error("cohorts_v2.preview failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="preview failed")

    samples = [
        {
            "id": int(r["id"]),
            "first_name": r.get("first_name") or "",
            "last_name": r.get("last_name") or "",
            "mrn": r.get("mrn") or "",
        }
        for r in rows
    ]
    return {
        "matched_count": matched,
        "sample_patient_ids": [s["id"] for s in samples],
        "sample_patients": samples,
    }


@router.post("", summary="Save a v2 cohort definition", status_code=201)
@limiter.limit("30/minute")
def save_cohort(
    request: Request,
    body: SaveRequest,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("cohorts", "write")),
) -> dict[str, Any]:
    """Persist the definition into ``raf_cohorts`` for the current tenant."""
    # Validate compilability before persisting — surface bad clauses early.
    try:
        _compile_definition(body.definition, tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    user_id = int(current_user.get("id") or current_user.get("user_id") or 0)
    definition_payload = json.dumps(body.definition.model_dump())
    try:
        with raf_cursor() as cur:
            cur.execute(
                """
                INSERT INTO raf_cohorts
                    (tenant_id, name, definition_json, created_by_user_id)
                VALUES (%s, %s, %s, %s)
                """,
                (tenant_id, body.name, definition_payload, user_id),
            )
            new_id = cur.lastrowid
    except Exception as exc:
        logger.error("cohorts_v2.save failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="save failed")
    return {
        "id": int(new_id),
        "name": body.name,
        "tenant_id": tenant_id,
        "definition": body.definition.model_dump(),
        "created_by_user_id": user_id,
    }


@router.get("", summary="List saved v2 cohorts for the current tenant")
@limiter.limit("60/minute")
def list_cohorts(
    request: Request,
    current_user: dict = Depends(get_current_user),
    tenant_id: str = Depends(get_tenant_id),
    _perm: None = Depends(require_permission("cohorts", "read")),
) -> dict[str, Any]:
    """Return up to 200 saved cohorts ordered by most recently updated."""
    try:
        with raf_read_cursor() as cur:
            cur.execute(
                """
                SELECT id, tenant_id, name, definition_json,
                       created_by_user_id, created_at, updated_at
                FROM raf_cohorts
                WHERE tenant_id = %s
                ORDER BY updated_at DESC, id DESC
                LIMIT 200
                """,
                (tenant_id,),
            )
            rows = cur.fetchall() or []
    except Exception as exc:
        logger.error("cohorts_v2.list failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="list failed")

    cohorts: list[dict[str, Any]] = []
    for r in rows:
        raw = r.get("definition_json")
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="replace")
        try:
            definition = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except json.JSONDecodeError:
            definition = {"operator": "AND", "clauses": []}
        cohorts.append(
            {
                "id": int(r["id"]),
                "tenant_id": r["tenant_id"],
                "name": r["name"],
                "definition": definition,
                "created_by_user_id": r["created_by_user_id"],
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                "updated_at": r["updated_at"].isoformat() if r.get("updated_at") else None,
            }
        )
    return {"count": len(cohorts), "cohorts": cohorts}
