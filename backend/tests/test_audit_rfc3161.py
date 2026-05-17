"""Tests for RFC 3161 audit-chain timestamping.

Test matrix
-----------
1. get_timestamp_for_hash returns token bytes from a mocked TSA endpoint.
2. After 100 audit entries, the Celery task stores a token row covering the
   full range and the chain-head hash matches the last entry's hash_self.
3. The verify endpoint (tested directly via the service layer) returns
   valid=True for the just-created token.
4. When the TSA endpoint is unreachable, get_timestamp_for_hash returns b''
   and does not raise — the audit chain is unaffected.

All DB and HTTP calls are mocked; no live network or DB required.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — minimal in-memory audit chain simulator
# ---------------------------------------------------------------------------

_GENESIS = "0" * 64


def _make_entry(prev_hash: str, seq: int) -> dict:
    """Build a synthetic audit entry dict mirroring immutable_audit_log columns."""
    body = {
        "timestamp": f"2026-05-17T00:{seq:02d}:00+00:00",
        "event_type": "phi_access",
        "user_id": "1",
        "tenant_id": "t1",
        "resource_type": "patient",
        "resource_id": str(seq),
        "action": "view",
        "details": {"seq": seq},
        "previous_hash": prev_hash,
    }
    h = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
    body["current_hash"] = h
    return body


def _build_chain(n: int = 100) -> list[dict]:
    """Build a hash-linked chain of n entries."""
    entries = []
    prev = _GENESIS
    for i in range(1, n + 1):
        e = _make_entry(prev, i)
        e["id"] = i
        e["hash_prev"] = e["previous_hash"]
        e["hash_self"] = e["current_hash"]
        prev = e["current_hash"]
        entries.append(e)
    return entries


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_TSR = b"\x30\x82\x01\x00" + b"\xde\xad\xbe\xef" * 60  # plausible DER-ish blob


@pytest.fixture()
def tmp_audit_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def chain_100() -> list[dict]:
    return _build_chain(100)


# ---------------------------------------------------------------------------
# Test 1: get_timestamp_for_hash — happy path with mocked TSA
# ---------------------------------------------------------------------------

def test_get_timestamp_for_hash_returns_token(chain_100, tmp_audit_dir, monkeypatch):
    """get_timestamp_for_hash returns non-empty bytes when TSA is reachable."""
    monkeypatch.setenv("IMMUTABLE_AUDIT_DIR", str(tmp_audit_dir))
    monkeypatch.setenv("RFC3161_TSA_URL", "http://fake-tsa.test/tsr")

    # Provide a stub rfc3161ng with make_timestamp_request and related functions.
    fake_rfc3161ng = MagicMock()
    fake_rfc3161ng.make_timestamp_request.return_value = b"\x30\x00"  # minimal TSQ

    # Patch the lazy import inside audit_rfc3161.
    import sys
    # Remove cached module if present so monkeypatch takes effect.
    sys.modules.pop("rfc3161ng", None)
    sys.modules["rfc3161ng"] = fake_rfc3161ng

    # Mock urllib.request.urlopen to return FAKE_TSR.
    import urllib.request
    from io import BytesIO

    class _FakeResp:
        def read(self):
            return FAKE_TSR
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **kw: _FakeResp())

    # Re-import after patching so the module picks up sys.modules["rfc3161ng"].
    sys.modules.pop("app.services.audit_rfc3161", None)
    from app.services import audit_rfc3161

    head_hash = chain_100[-1]["hash_self"]
    token = audit_rfc3161.get_timestamp_for_hash(head_hash)

    assert token == FAKE_TSR, "Expected fake TSR bytes back from mocked TSA"
    assert len(token) > 0

    # Local .tsr file should have been created.
    tsr_files = list(tmp_audit_dir.glob("timestamps/**/*.tsr"))
    assert tsr_files, "Expected a .tsr file to be written locally"


# ---------------------------------------------------------------------------
# Test 2: Celery task stores token covering the full range
# ---------------------------------------------------------------------------

class _FakeTaskRequest:
    retries = 0
    id = "fake-task-id"


class _FakeSelf:
    """Minimal Celery task self mock."""
    request = _FakeTaskRequest()
    max_retries = 3

    def retry(self, exc=None, countdown=None):
        raise exc or RuntimeError("retry")


def _db_factory(entries: list[dict]):
    """Build a fake raf_cursor contextmanager backed by in-memory entries."""
    # Simulate two tables: immutable_audit_log and audit_timestamp_tokens.
    token_store: list[dict] = []
    next_token_id = [1]

    class FakeCursor:
        def __init__(self):
            self._result = []
            self.lastrowid = None

        def execute(self, sql: str, params=None):
            sql_stripped = " ".join(sql.split())
            # MAX(covers_entry_id_end) -> 0 (no prior tokens).
            if "COALESCE(MAX(covers_entry_id_end)" in sql:
                self._result = [{"COALESCE(MAX(covers_entry_id_end), 0)": 0}]
            # Range query: MIN/MAX id and head hash.
            elif "MIN(id) AS id_start" in sql:
                if entries:
                    self._result = [{
                        "id_start": entries[0]["id"],
                        "id_end": entries[-1]["id"],
                        "head_hash": entries[-1]["hash_self"],
                    }]
                else:
                    self._result = [{"id_start": None, "id_end": None, "head_hash": None}]
            # INSERT token.
            elif "INSERT INTO audit_timestamp_tokens" in sql:
                chain_head, id_start, id_end, tsa_url, token_bytes = params
                token_store.append({
                    "id": next_token_id[0],
                    "chain_head_hash": chain_head,
                    "covers_entry_id_start": id_start,
                    "covers_entry_id_end": id_end,
                    "tsa_url": tsa_url,
                    "token_bytes": token_bytes,
                })
                self.lastrowid = next_token_id[0]
                next_token_id[0] += 1
                self._result = []
            # SELECT token by id (verify endpoint path).
            elif "FROM audit_timestamp_tokens WHERE id" in sql:
                tid = params[0] if params else None
                self._result = [t for t in token_store if t["id"] == tid]
            # SELECT entries for chain walk.
            elif "FROM immutable_audit_log" in sql and "BETWEEN" in sql:
                lo, hi = params
                self._result = [e for e in entries if lo <= e["id"] <= hi]
            else:
                self._result = []

        def fetchone(self):
            return self._result[0] if self._result else None

        def fetchall(self):
            return list(self._result)

    @contextmanager
    def _fake_raf_cursor():
        c = FakeCursor()
        yield c

    return _fake_raf_cursor, token_store


def test_celery_task_stores_token_covering_full_range(chain_100, monkeypatch):
    """task_rfc3161_timestamp stores a token covering all 100 entries."""
    import sys
    sys.modules.pop("app.services.audit_rfc3161", None)

    fake_raf_cursor, token_store = _db_factory(chain_100)

    # Patch raf_cursor inside celery_tasks.
    import app.services.celery_tasks as ct
    monkeypatch.setattr(ct, "task_rfc3161_timestamp", ct.task_rfc3161_timestamp)

    # We call the underlying function body, bypassing Celery machinery.
    # Patch imports used inside the task body.
    with patch("app.services.audit_rfc3161.get_timestamp_for_hash", return_value=FAKE_TSR) as mock_ts, \
         patch("app.db.raf_cursor", fake_raf_cursor):

        # Import the module fresh so patches apply.
        sys.modules.pop("app.services.celery_tasks", None)
        import importlib, app.services.celery_tasks as celery_mod
        importlib.reload(celery_mod)

        # Directly invoke the task body via run() which skips Celery retry machinery.
        fake_self = _FakeSelf()

        # Patch db and audit_rfc3161 inside the reloaded module scope.
        with patch.dict("sys.modules", {"app.db": MagicMock(raf_cursor=fake_raf_cursor)}):
            # Reconstruct to call inner logic directly.
            import os
            os.environ.setdefault("RFC3161_TSA_URL", "https://freetsa.org/tsr")

            # --- Run the task body inline (no Celery broker needed) ---
            with patch("app.services.audit_rfc3161.get_timestamp_for_hash", return_value=FAKE_TSR):
                import app.db as db_mod
                monkeypatch.setattr(db_mod, "raf_cursor", fake_raf_cursor)

                result = celery_mod.task_rfc3161_timestamp.run()

    # Assertions.
    assert result.get("token_id") is not None, f"Expected token_id in result: {result}"
    assert result["covers_entry_id_start"] == 1
    assert result["covers_entry_id_end"] == 100
    assert result["chain_head_hash"] == chain_100[-1]["hash_self"]
    assert len(token_store) == 1
    stored = token_store[0]
    assert stored["token_bytes"] == FAKE_TSR
    assert stored["covers_entry_id_start"] == 1
    assert stored["covers_entry_id_end"] == 100


# ---------------------------------------------------------------------------
# Test 3: verify endpoint logic returns valid=True for a good token
# ---------------------------------------------------------------------------

def test_verify_endpoint_returns_valid_true(chain_100, monkeypatch):
    """Service-layer verify logic returns valid=True for a correct token."""
    import sys
    sys.modules.pop("app.services.audit_rfc3161", None)

    fake_raf_cursor, token_store = _db_factory(chain_100)
    # Pre-seed one token row covering all 100 entries.
    head_hash = chain_100[-1]["hash_self"]
    token_store.append({
        "id": 1,
        "chain_head_hash": head_hash,
        "covers_entry_id_start": 1,
        "covers_entry_id_end": 100,
        "tsa_url": "https://freetsa.org/tsr",
        "token_bytes": FAKE_TSR,
        "token_generated_at": __import__("datetime").datetime(2026, 5, 17, 0, 0),
    })

    import app.db as db_mod
    monkeypatch.setattr(db_mod, "raf_cursor", fake_raf_cursor)

    # verify_timestamp_token should return True for our fake TSR.
    with patch("app.services.audit_rfc3161.verify_timestamp_token", return_value=True):
        # Simulate the endpoint logic directly (avoids full FastAPI stack).
        import app.routers.audit as audit_router
        monkeypatch.setattr(audit_router, "raf_cursor", fake_raf_cursor)

        # Build a fake current_user with admin role.
        fake_user = {"id": 1, "email": "admin@raf.health", "role": "admin", "tenant_id": "t1"}

        # Temporarily make require_role a no-op.
        monkeypatch.setattr(audit_router, "require_role", lambda user, role: None)

        response = audit_router.verify_timestamp_token_endpoint(
            token_id=1,
            current_user=fake_user,
        )

    assert response["valid"] is True, f"Expected valid=True, got: {response}"
    assert response["covers_entries"] == [1, 100]
    assert response["chain_head"] == head_hash
    assert response["chain_ok"] is True
    assert response["token_crypto_ok"] is True


# ---------------------------------------------------------------------------
# Test 4: Unreachable TSA returns b'' without corrupting the chain
# ---------------------------------------------------------------------------

def test_unreachable_tsa_returns_empty_bytes(chain_100, tmp_audit_dir, monkeypatch):
    """When the TSA is unreachable, get_timestamp_for_hash returns b'' safely."""
    import sys
    sys.modules.pop("app.services.audit_rfc3161", None)

    monkeypatch.setenv("IMMUTABLE_AUDIT_DIR", str(tmp_audit_dir))
    monkeypatch.setenv("RFC3161_TSA_URL", "http://unreachable.tsa.test/tsr")

    fake_rfc3161ng = MagicMock()
    fake_rfc3161ng.make_timestamp_request.return_value = b"\x30\x00"
    sys.modules["rfc3161ng"] = fake_rfc3161ng

    import urllib.request

    def _raise_timeout(*a, **kw):
        raise TimeoutError("connection timed out")

    monkeypatch.setattr(urllib.request, "urlopen", _raise_timeout)

    from app.services import audit_rfc3161

    head_hash = chain_100[-1]["hash_self"]
    token = audit_rfc3161.get_timestamp_for_hash(head_hash)

    assert token == b"", f"Expected b'' on TSA failure, got {token!r}"

    # Verify no .tsr files were written (nothing to persist).
    tsr_files = list(tmp_audit_dir.glob("timestamps/**/*.tsr"))
    assert not tsr_files, "No .tsr file should be written when TSA fails"
