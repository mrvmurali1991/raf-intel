# Testing Guide — RAF Intelligence Backend

## Two-Speed Test Strategy

The test suite runs in two modes:

| Mode | Command | Time | What runs |
|------|---------|------|-----------|
| Fast (unit) | `bash backend/scripts/test-fast.sh` or `make ci-fast` | <60 s | All tests NOT marked `integration` |
| Full (integration) | `bash backend/scripts/test-all.sh` | ~10 min | Everything, requires live DB + services |

CI gates on `ci-fast` for every PR. Full integration runs are reserved for pre-merge on `server`.

---

## When to use `@pytest.mark.integration`

Mark a test (or an entire file via `pytestmark`) as `integration` when it:

- Calls `raf_cursor()` or `openemr_cursor()` against a **live database** (not mocked)
- Sends real HTTP requests with `requests.Session` or `httpx.Client` to a running backend
- Connects to a real `redis.Redis` instance
- Calls `celery_app.send_task()` or `.apply_async()` on a real broker
- Calls the **Gemini / Vertex AI API** without mocking
- Calls **Twilio**, **SendGrid**, **FHIR endpoints**, or any other external network service

### Quick checklist

```python
# NEEDS @pytest.mark.integration
from app.db import raf_cursor          # live DB
import redis; r = redis.Redis(...)     # live Redis
import httpx; httpx.get("https://...") # real network
from app.tasks import celery_app       # real Celery
```

```python
# Does NOT need the marker — pure unit test
from unittest.mock import patch, MagicMock
# All external calls replaced with mocks
```

### File-level marking

For test files where every test is an integration test, add at the top:

```python
import pytest
pytestmark = pytest.mark.integration
```

For a mix of unit + integration tests within one file, mark individual classes or functions:

```python
@pytest.mark.integration
class TestRealDBPath:
    ...
```

---

## Adding a test that touches Gemini / FHIR / Twilio

Always mark integration:

```python
import pytest
from unittest.mock import patch

pytestmark = pytest.mark.integration  # file-level OR per-class/function


class TestFHIRWriteback:
    def test_pushes_condition(self):
        # real httpx call to FHIR server goes here
        ...
```

If you want the test runnable in fast mode by mocking the external dep:

```python
def test_condition_body_shape():
    # No I/O — pure dict construction test — NO marker needed
    from app.services.fhir_problem_list import build_condition_body
    body = build_condition_body(icd10="E11.22", patient_id=1)
    assert body["resourceType"] == "Condition"
```

---

## Auto-mocks applied in fast mode

The `conftest.py` applies these auto-use fixtures automatically for every test that is **not** marked `integration`:

| Dep | What is mocked | Where |
|-----|---------------|-------|
| Gemini/Vertex | `llm_generate_content` returns `{"candidates": []}` | `app.services.llm.vertex_client`, `gemini_client` |
| Redis | `get_redis_client()` returns a `MagicMock` | `app.cache`, `app.services.cache_service` |
| EMR gate | `list_connections()` returns `[{"is_active": 1}]` | `app.services.emr_manager` |

These mocks are **transparent** — they fire only when the real module exists. Missing modules are silently skipped.

---

## Running the fast suite locally

```bash
# From repo root
make ci-fast

# From backend/ directory directly
bash backend/scripts/test-fast.sh

# With extra verbosity
bash backend/scripts/test-fast.sh -v

# Run a single file in fast mode
cd backend
.venv/bin/pytest tests/test_raf_calculator.py -m "not integration" --no-cov --tb=short
```

Expected output ends with:
```
=== test-fast.sh complete in Ns ===
Result: PASSED
```

---

## How CI gates on `test-fast`

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs `make ci-fast` as an early gate:

```yaml
- name: Fast unit tests
  run: make ci-fast
```

A non-zero exit code blocks the PR. Integration tests run in a separate job that requires a MySQL service container and is only enforced on the `server` branch.

---

## Timeout policy

- Default per-test timeout: **20 seconds** (hard kill via `pytest-timeout`).
- Tests that legitimately need more time (e.g., multi-page PDF OCR in unit mode) should be marked `@pytest.mark.slow` and are excluded from `test-fast.sh`.
- The `--timeout-method=thread` flag is used so even blocking C-extensions are killed.

---

## Slow-test marker

```python
@pytest.mark.slow
def test_large_ccda_parse():
    # Takes 30-60s — excluded from fast run
    ...
```

To run slow tests explicitly:
```bash
cd backend && .venv/bin/pytest tests/ -m "slow" --no-cov
```
