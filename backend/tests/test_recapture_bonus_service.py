"""
tests/test_recapture_bonus_service.py — Coder bonus / incentive tracker.

Covers:
- Default config seeded when none exists (all 12 month multipliers populated).
- Multiplier curve correctly applied to per-month closure counts.
- Leaderboard ordering by closures DESC, dollars DESC.
- Edge case: zero closures returns empty leaderboard / zeroed earnings.
- bonus_for_closing_now: open gap, already closed gap, missing gap.
- current_month_multiplier returns next-month delta.
- update_config rejects negative bonus and ignores unknown fields.

All DB calls are mocked via unittest.mock — no database required.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.services import recapture_bonus_service as svc
from app.services.recapture_bonus_service import (
    DEFAULT_BONUS_PER_CLOSURE,
    DEFAULT_MONTH_MULTIPLIERS,
    bonus_for_closing_now,
    compute_coder_earnings,
    compute_leaderboard,
    current_month_multiplier,
    get_or_create_config,
    update_config,
)


# ---------------------------------------------------------------------------
# Cursor helpers
# ---------------------------------------------------------------------------


def _config_row(
    *,
    bonus: float = DEFAULT_BONUS_PER_CLOSURE,
    multipliers: dict[int, float] | None = None,
    active: int = 1,
    tenant_id: str = "1",
) -> dict:
    mults = multipliers if multipliers is not None else DEFAULT_MONTH_MULTIPLIERS
    return {
        "id": 1,
        "tenant_id": tenant_id,
        "bonus_per_closure_default": bonus,
        "month_multipliers": json.dumps({str(k): v for k, v in mults.items()}),
        "active": active,
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 1),
    }


@contextmanager
def _cursor_returning(*, fetchone_seq=None, fetchall_seq=None):
    """
    Context manager that yields a MagicMock cursor whose fetchone / fetchall
    iterate through the given sequences as the service code calls them.
    """
    cur = MagicMock()
    fetchone_iter = iter(fetchone_seq or [])
    fetchall_iter = iter(fetchall_seq or [])

    cur.fetchone.side_effect = lambda: next(fetchone_iter, None)
    cur.fetchall.side_effect = lambda: next(fetchall_iter, [])
    yield cur


def _make_cursor_factory(fetchone_seq=None, fetchall_seq=None):
    """
    Build a fresh raf_cursor() context manager that re-yields a cursor with
    the supplied sequences each time. Each new ``with`` block starts at the
    beginning of the iterator — this matches services that open one block.
    """
    def _factory(*args, **kwargs):
        return _cursor_returning(
            fetchone_seq=list(fetchone_seq or []),
            fetchall_seq=list(fetchall_seq or []),
        )
    return _factory


def _stateful_cursor_factory(fetchone_seq=None, fetchall_seq=None):
    """
    Same as _make_cursor_factory but the iterators persist across multiple
    ``with raf_cursor() as cur:`` blocks within a single service call.
    """
    fetchone_iter = iter(fetchone_seq or [])
    fetchall_iter = iter(fetchall_seq or [])

    @contextmanager
    def _cm(*args, **kwargs):
        cur = MagicMock()
        cur.fetchone.side_effect = lambda: next(fetchone_iter, None)
        cur.fetchall.side_effect = lambda: next(fetchall_iter, [])
        yield cur

    return _cm


# ---------------------------------------------------------------------------
# get_or_create_config
# ---------------------------------------------------------------------------


class TestGetOrCreateConfig:
    def test_returns_existing_row_with_all_12_months(self):
        # First select returns the row
        cm = _stateful_cursor_factory(fetchone_seq=[_config_row()])
        with patch.object(svc, "raf_cursor", cm):
            cfg = get_or_create_config("1")

        assert cfg["bonus_per_closure_default"] == DEFAULT_BONUS_PER_CLOSURE
        assert set(cfg["month_multipliers"].keys()) == set(range(1, 13))
        # spot-check: January is heavily bonused, December heavily discounted
        assert cfg["month_multipliers"][1] == 2.0
        assert cfg["month_multipliers"][12] == 0.3

    def test_seeds_default_when_missing(self):
        # First fetchone returns None (no row), insert then second fetchone
        # returns a freshly-seeded row.
        cm = _stateful_cursor_factory(fetchone_seq=[None, _config_row()])
        with patch.object(svc, "raf_cursor", cm):
            cfg = get_or_create_config("99")

        assert cfg["active"] is True
        assert cfg["month_multipliers"][1] == 2.0

    def test_corrupt_multipliers_falls_back_to_defaults(self):
        row = _config_row()
        row["month_multipliers"] = "not-json{{"
        cm = _stateful_cursor_factory(fetchone_seq=[row])
        with patch.object(svc, "raf_cursor", cm):
            cfg = get_or_create_config("1")
        assert cfg["month_multipliers"] == DEFAULT_MONTH_MULTIPLIERS


# ---------------------------------------------------------------------------
# current_month_multiplier
# ---------------------------------------------------------------------------


class TestCurrentMonthMultiplier:
    def test_may_returns_next_drop_to_september(self):
        cm = _stateful_cursor_factory(fetchone_seq=[_config_row()])
        with patch.object(svc, "raf_cursor", cm):
            out = current_month_multiplier("1", today=date(2026, 5, 15))
        assert out["month"] == 5
        assert out["multiplier"] == 1.0
        assert out["next_month"] == 6
        assert out["next_multiplier"] == 1.0
        assert out["delta"] == 0.0
        assert out["days_until_next_month"] == 17  # May 15 -> June 1

    def test_december_wraps_to_january(self):
        cm = _stateful_cursor_factory(fetchone_seq=[_config_row()])
        with patch.object(svc, "raf_cursor", cm):
            out = current_month_multiplier("1", today=date(2026, 12, 20))
        assert out["month"] == 12
        assert out["next_month"] == 1
        assert out["multiplier"] == 0.3
        assert out["next_multiplier"] == 2.0
        assert out["delta"] == pytest.approx(1.7, rel=1e-3)


# ---------------------------------------------------------------------------
# bonus_for_closing_now
# ---------------------------------------------------------------------------


class TestBonusForClosingNow:
    def test_open_gap_in_may_yields_25_dollars(self):
        # bonus_for_closing_now calls:
        #   1. get_or_create_config (config row)
        #   2. current_month_multiplier -> get_or_create_config (config row again)
        #   3. SELECT recapture_gaps where id... (gap row)
        cm = _stateful_cursor_factory(fetchone_seq=[
            _config_row(),
            _config_row(),
            {"id": 7, "status": "open", "tenant_id": "1"},
        ])
        # Force "today" to May by patching datetime.now used inside the service.
        real_dt = datetime
        with patch.object(svc, "raf_cursor", cm), \
             patch.object(svc, "datetime") as dt_mock:
            dt_mock.now.return_value = real_dt(2026, 5, 15, tzinfo=None)
            dt_mock.side_effect = lambda *a, **kw: real_dt(*a, **kw)
            out = bonus_for_closing_now("1", 7)

        assert out["eligible"] is True
        assert out["base_bonus"] == 25.00
        # May = 1.0x → 25 * 1.0 = 25
        assert out["bonus"] == 25.00

    def test_already_closed_gap_returns_zero_with_reason(self):
        cm = _stateful_cursor_factory(fetchone_seq=[
            _config_row(),
            _config_row(),
            {"id": 7, "status": "recaptured", "tenant_id": "1"},
        ])
        with patch.object(svc, "raf_cursor", cm):
            out = bonus_for_closing_now("1", 7)
        assert out["eligible"] is False
        assert "recaptured" in out["reason"]
        assert out["bonus"] == 0.0

    def test_missing_gap_returns_zero(self):
        cm = _stateful_cursor_factory(fetchone_seq=[
            _config_row(),
            _config_row(),
            None,
        ])
        with patch.object(svc, "raf_cursor", cm):
            out = bonus_for_closing_now("1", 999)
        assert out["eligible"] is False
        assert out["reason"] == "gap not found for this tenant"


# ---------------------------------------------------------------------------
# compute_coder_earnings
# ---------------------------------------------------------------------------


class TestComputeCoderEarnings:
    def test_three_may_closures_yield_75_dollars(self):
        # Sequence inside compute_coder_earnings:
        #   - get_or_create_config:   fetchone (config row)
        #   - current_month_multiplier -> get_or_create_config: fetchone (config row)
        #   - users select:            fetchone (user)
        #   - closures group-by:       fetchall (3 in May)
        #   - open count:              fetchone (open row)
        cm = _stateful_cursor_factory(
            fetchone_seq=[
                _config_row(),          # get_or_create_config
                _config_row(),          # current_month_multiplier
                {"id": 42, "email": "coder@x.com", "full_name": "Cody Coder", "role": "coder"},
                {"open_count": 4},      # open count
            ],
            fetchall_seq=[
                [{"month": 5, "closures": 3, "dollars_recaptured": 9000.0}],
            ],
        )
        with patch.object(svc, "raf_cursor", cm):
            with patch.object(svc, "datetime") as dt_mock:
                dt_mock.now.return_value = datetime(2026, 5, 15)
                out = compute_coder_earnings("1", 42, 2026, today=date(2026, 5, 15))

        assert out["ytd_closures"] == 3
        assert out["ytd_dollars_recaptured"] == 9000.0
        # 3 * $25 * 1.0 (May)
        assert out["bonus_earned"] == 75.00
        # 4 open * $25 * 1.0 (May)
        assert out["bonus_at_risk"] == 100.00
        assert out["current_multiplier"] == 1.0
        # 12 monthly buckets returned
        assert len(out["monthly_breakdown"]) == 12

    def test_zero_closures_returns_zeros(self):
        cm = _stateful_cursor_factory(
            fetchone_seq=[
                _config_row(),
                _config_row(),
                {"id": 42, "email": "c@x.com", "full_name": "C", "role": "coder"},
                {"open_count": 0},
            ],
            fetchall_seq=[[]],
        )
        with patch.object(svc, "raf_cursor", cm):
            out = compute_coder_earnings("1", 42, 2026, today=date(2026, 5, 15))

        assert out["ytd_closures"] == 0
        assert out["bonus_earned"] == 0.0
        assert out["bonus_at_risk"] == 0.0

    def test_january_closures_get_2x_multiplier(self):
        # 2 closures in January → 2 * $25 * 2.0 = $100
        cm = _stateful_cursor_factory(
            fetchone_seq=[
                _config_row(),
                _config_row(),
                {"id": 42, "email": "c@x.com", "full_name": "C", "role": "coder"},
                {"open_count": 0},
            ],
            fetchall_seq=[
                [{"month": 1, "closures": 2, "dollars_recaptured": 6000.0}],
            ],
        )
        with patch.object(svc, "raf_cursor", cm):
            out = compute_coder_earnings("1", 42, 2026, today=date(2026, 5, 15))
        assert out["bonus_earned"] == 100.00


# ---------------------------------------------------------------------------
# compute_leaderboard
# ---------------------------------------------------------------------------


class TestComputeLeaderboard:
    def test_ordering_by_closures_then_dollars(self):
        # Coders A and B; A has more closures, B has more dollars.
        cm = _stateful_cursor_factory(
            fetchone_seq=[_config_row()],
            fetchall_seq=[
                # closed_rows
                [
                    {"resolved_by": "1", "month": 5, "closures": 5, "dollars": 12000.0},
                    {"resolved_by": "2", "month": 5, "closures": 3, "dollars": 50000.0},
                ],
                # open_rows
                [
                    {"resolved_by": "1", "open_count": 2},
                    {"resolved_by": "2", "open_count": 7},
                ],
                # users_rows
                [
                    {"id": 1, "email": "alice@x.com", "full_name": "Alice"},
                    {"id": 2, "email": "bob@x.com", "full_name": "Bob"},
                ],
            ],
        )
        with patch.object(svc, "raf_cursor", cm):
            board = compute_leaderboard("1", 2026, limit=10)

        assert len(board) == 2
        assert board[0]["rank"] == 1
        assert board[0]["name"] == "Alice"
        assert board[0]["ytd_closures"] == 5
        assert board[1]["rank"] == 2
        assert board[1]["name"] == "Bob"
        # Win rate = closures / (closures + open). Alice 5/(5+2)=0.7142; Bob 3/(3+7)=0.3
        assert board[0]["win_rate"] == pytest.approx(0.7143, abs=1e-3)
        assert board[1]["win_rate"] == 0.3

    def test_zero_closures_returns_empty(self):
        cm = _stateful_cursor_factory(
            fetchone_seq=[_config_row()],
            fetchall_seq=[[], [], []],
        )
        with patch.object(svc, "raf_cursor", cm):
            board = compute_leaderboard("1", 2026, limit=10)
        assert board == []

    def test_filters_out_system_resolved(self):
        # The SQL excludes 'system' — we mimic that here by NOT returning
        # any row with resolved_by='system'. This is a contract test that
        # the leaderboard never surfaces auto-closures.
        cm = _stateful_cursor_factory(
            fetchone_seq=[_config_row()],
            fetchall_seq=[
                # closed_rows: only 1 human coder
                [{"resolved_by": "1", "month": 5, "closures": 2, "dollars": 6000.0}],
                # open_rows
                [],
                # users_rows
                [{"id": 1, "email": "a@x.com", "full_name": "Alice"}],
            ],
        )
        with patch.object(svc, "raf_cursor", cm):
            board = compute_leaderboard("1", 2026)
        assert len(board) == 1
        assert board[0]["name"] == "Alice"


# ---------------------------------------------------------------------------
# update_config validation
# ---------------------------------------------------------------------------


class TestUpdateConfig:
    def test_rejects_negative_bonus(self):
        cm = _stateful_cursor_factory(fetchone_seq=[_config_row()])
        with patch.object(svc, "raf_cursor", cm):
            with pytest.raises(ValueError, match=">= 0"):
                update_config("1", bonus_per_closure_default=-5)

    def test_ignores_unknown_fields(self):
        # Two get_or_create_config calls (start + final return) plus one UPDATE.
        cm = _stateful_cursor_factory(fetchone_seq=[
            _config_row(),  # initial get_or_create_config
            _config_row(bonus=30.0),  # post-update reselect
        ])
        with patch.object(svc, "raf_cursor", cm):
            cfg = update_config("1", unknown_field="ignored", bonus_per_closure_default=30.0)
        assert cfg["bonus_per_closure_default"] == 30.0


# ---------------------------------------------------------------------------
# Acceptance test from the spec:
#   "Close 3 gaps in May → coder earnings = 3 × $25 × 1.0 = $75"
# ---------------------------------------------------------------------------


def test_acceptance_three_may_closures_equal_seventy_five_dollars():
    cm = _stateful_cursor_factory(
        fetchone_seq=[
            _config_row(),
            _config_row(),
            {"id": 1, "email": "x@y.com", "full_name": "X", "role": "coder"},
            {"open_count": 0},
        ],
        fetchall_seq=[
            [{"month": 5, "closures": 3, "dollars_recaptured": 9000.0}],
        ],
    )
    with patch.object(svc, "raf_cursor", cm):
        result = compute_coder_earnings("1", 1, 2026, today=date(2026, 5, 15))
    assert result["bonus_earned"] == 75.00
