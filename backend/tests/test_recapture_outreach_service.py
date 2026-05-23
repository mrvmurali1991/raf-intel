"""tests/test_recapture_outreach_service.py — outreach automation tracker.

Covers:
- Template create / list / seed-defaults
- Event lifecycle (queue -> sent -> delivered -> responded)
- Conversion / closure metric math (closures × $3,000)
- Channel breakdown rates (response_rate, visit_rate, closure_rate)
- Per-gap history retrieval
- Validation of channels and statuses

All DB calls are mocked via unittest.mock — no database required.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from app.services.recapture_outreach_service import (
    _REVENUE_PER_CLOSURE,
    VALID_CHANNELS,
    VALID_STATUSES,
    create_template,
    get_outreach_history,
    list_templates,
    mark_delivered,
    mark_event,
    mark_opted_out,
    mark_response,
    mark_sent,
    outreach_summary,
    queue_outreach,
    seed_default_templates,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scripted_cursor(script: list):
    """Build a cursor whose fetchall/fetchone/lastrowid follow ``script``.

    Each script entry is a dict::
        {"fetchall": [...], "fetchone": {...}, "lastrowid": 1, "rowcount": 1}

    The cursor walks the script in order on each ``execute`` call.  Any keys
    omitted on an entry default to "no change" — that is, fetchall returns
    [], fetchone returns None, lastrowid stays 0, rowcount stays 1.
    """
    state = {"i": 0}
    cur = MagicMock()

    def _execute(*args, **kwargs):
        i = state["i"]
        if i < len(script):
            step = script[i]
            cur.fetchall.return_value = step.get("fetchall", [])
            cur.fetchone.return_value = step.get("fetchone", None)
            cur.lastrowid = step.get("lastrowid", 0)
            cur.rowcount = step.get("rowcount", 1)
        state["i"] += 1

    cur.execute.side_effect = _execute
    cur.executemany.side_effect = _execute

    @contextmanager
    def _cm(*args, **kwargs):
        # Reset the script cursor each "with raf_cursor()" entry only when
        # the caller hasn't started yet — keeps multi-step ops working.
        yield cur

    return _cm, cur


def _now() -> datetime:
    return datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 1. Templates
# ---------------------------------------------------------------------------

class TestTemplates:
    def test_create_template_basic(self) -> None:
        # INSERT lastrowid=1, then SELECT returns persisted row
        row = {
            "id": 1, "tenant_id": "1", "channel": "sms", "name": "Test SMS",
            "subject": None, "message_text": "Hi {first_name}",
            "trigger_rules": '{"min_days_open": 30}', "is_active": 1,
            "created_at": _now(), "updated_at": _now(),
        }
        cm, _ = _scripted_cursor([
            {"lastrowid": 1, "rowcount": 1},
            {"fetchone": row},
        ])
        with patch("app.services.recapture_outreach_service.raf_cursor", cm):
            tpl = create_template(
                tenant_id="1", channel="sms", name="Test SMS",
                message_text="Hi {first_name}",
                trigger_rules={"min_days_open": 30},
            )
        assert tpl["id"] == 1
        assert tpl["channel"] == "sms"
        assert tpl["is_active"] is True
        # JSON should be deserialised back to dict for the API
        assert tpl["trigger_rules"] == {"min_days_open": 30}

    def test_create_template_invalid_channel(self) -> None:
        with pytest.raises(ValueError, match="Invalid channel"):
            create_template(
                tenant_id="1", channel="carrier_pigeon",
                name="Nope", message_text="hi",
            )

    def test_create_template_requires_name_and_message(self) -> None:
        with pytest.raises(ValueError, match="name"):
            create_template(tenant_id="1", channel="sms", name="", message_text="hi")
        with pytest.raises(ValueError, match="message_text"):
            create_template(tenant_id="1", channel="sms", name="A", message_text="")

    def test_list_templates(self) -> None:
        rows = [
            {"id": 1, "tenant_id": "1", "channel": "sms", "name": "A",
             "subject": None, "message_text": "x", "trigger_rules": None,
             "is_active": 1, "created_at": _now(), "updated_at": _now()},
            {"id": 2, "tenant_id": "1", "channel": "portal", "name": "B",
             "subject": "S", "message_text": "y", "trigger_rules": None,
             "is_active": 0, "created_at": _now(), "updated_at": _now()},
        ]
        cm, _ = _scripted_cursor([{"fetchall": rows}])
        with patch("app.services.recapture_outreach_service.raf_cursor", cm):
            out = list_templates(tenant_id="1")
        assert len(out) == 2
        assert out[0]["is_active"] is True
        assert out[1]["is_active"] is False

    def test_list_templates_invalid_channel_filter(self) -> None:
        with pytest.raises(ValueError, match="Invalid channel"):
            list_templates(tenant_id="1", channel="bogus")

    def test_seed_defaults_inserts_three_when_none_exist(self) -> None:
        # First call from seed_default_templates -> list_templates -> empty
        # Then for each of the 3 defaults: 1) create insert, 2) select back.
        # Plus seed_default_templates calls list_templates ONCE up front.
        # We use a callable cm that returns a fresh cursor each `with` so
        # internal calls don't share state with the outer one.
        sql_calls: list = []

        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            local_state = {"i": 0}
            # Each sub-`with` block has its own state. We rely on the order:
            #   1st with: list_templates -> fetchall=[]
            #   2nd with: create_template insert + select back row
            #   ...
            def _execute(sql, params=None):
                idx = len(sql_calls)
                sql_calls.append((sql, params))
                # Deterministic by *order across the seed flow*
                if idx == 0:
                    # list_templates SELECT
                    cur.fetchall.return_value = []
                else:
                    # create_template: pairs of (INSERT, SELECT)
                    if "INSERT" in sql:
                        cur.lastrowid = idx
                        cur.rowcount = 1
                    else:  # SELECT
                        cur.fetchone.return_value = {
                            "id": idx, "tenant_id": "t1",
                            "channel": "sms", "name": "x",
                            "subject": None, "message_text": "x",
                            "trigger_rules": None, "is_active": 1,
                            "created_at": _now(), "updated_at": _now(),
                        }
            cur.execute.side_effect = _execute
            yield cur

        with patch("app.services.recapture_outreach_service.raf_cursor", _cm):
            created = seed_default_templates(tenant_id="t1")
        assert len(created) == 3

    def test_seed_defaults_idempotent_when_already_present(self) -> None:
        # list_templates returns the 3 default names already
        existing = [
            {"id": 1, "tenant_id": "t1", "channel": "sms",
             "name": "Annual wellness reminder (SMS)",
             "subject": None, "message_text": "x", "trigger_rules": None,
             "is_active": 1, "created_at": _now(), "updated_at": _now()},
            {"id": 2, "tenant_id": "t1", "channel": "portal",
             "name": "Portal nudge — overdue chronic care visit",
             "subject": None, "message_text": "x", "trigger_rules": None,
             "is_active": 1, "created_at": _now(), "updated_at": _now()},
            {"id": 3, "tenant_id": "t1", "channel": "phone",
             "name": "Phone callback request",
             "subject": None, "message_text": "x", "trigger_rules": None,
             "is_active": 1, "created_at": _now(), "updated_at": _now()},
        ]

        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            cur.fetchall.return_value = existing
            yield cur

        with patch("app.services.recapture_outreach_service.raf_cursor", _cm):
            created = seed_default_templates(tenant_id="t1")
        assert created == []


# ---------------------------------------------------------------------------
# 2. queue_outreach
# ---------------------------------------------------------------------------

class TestQueueOutreach:
    def _new_event_row(self, **overrides):
        base = {
            "id": 7, "tenant_id": "1", "gap_id": 100, "patient_id": "P1",
            "template_id": 1, "channel": "sms", "status": "queued",
            "scheduled_for": None, "sent_at": None, "delivered_at": None,
            "responded_at": None, "response_text": None,
            "resulted_in_visit": 0, "resulted_in_closure": 0,
            "metadata": None, "created_at": _now(), "updated_at": _now(),
        }
        base.update(overrides)
        return base

    def test_queue_with_template_inherits_channel(self) -> None:
        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            calls = {"i": 0}

            def _exec(sql, params=None):
                i = calls["i"]
                calls["i"] += 1
                if i == 0:  # gap lookup
                    cur.fetchone.return_value = {"id": 100, "patient_id": "P1"}
                elif i == 1:  # template lookup
                    cur.fetchone.return_value = {"id": 1, "channel": "sms"}
                elif i == 2:  # insert event
                    cur.lastrowid = 7
                    cur.rowcount = 1
                else:  # select event
                    cur.fetchone.return_value = self._new_event_row()
            cur.execute.side_effect = _exec
            yield cur

        with patch("app.services.recapture_outreach_service.raf_cursor", _cm):
            evt = queue_outreach(tenant_id="1", gap_id=100, template_id=1)

        assert evt["status"] == "queued"
        assert evt["channel"] == "sms"
        assert evt["gap_id"] == 100

    def test_queue_with_channel_only(self) -> None:
        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            calls = {"i": 0}

            def _exec(sql, params=None):
                i = calls["i"]
                calls["i"] += 1
                if i == 0:
                    cur.fetchone.return_value = {"id": 100, "patient_id": "P1"}
                elif i == 1:
                    cur.lastrowid = 8
                    cur.rowcount = 1
                else:
                    cur.fetchone.return_value = self._new_event_row(
                        id=8, channel="phone", template_id=None,
                    )
            cur.execute.side_effect = _exec
            yield cur

        with patch("app.services.recapture_outreach_service.raf_cursor", _cm):
            evt = queue_outreach(tenant_id="1", gap_id=100, channel="phone")
        assert evt["channel"] == "phone"
        assert evt["template_id"] is None

    def test_queue_requires_gap_to_exist_for_tenant(self) -> None:
        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            cur.fetchone.return_value = None
            yield cur

        with patch("app.services.recapture_outreach_service.raf_cursor", _cm):
            with pytest.raises(ValueError, match="not found"):
                queue_outreach(tenant_id="1", gap_id=999, channel="sms")

    def test_queue_requires_either_template_or_channel(self) -> None:
        with pytest.raises(ValueError, match="template_id or channel"):
            queue_outreach(tenant_id="1", gap_id=100)


# ---------------------------------------------------------------------------
# 3. Event lifecycle transitions
# ---------------------------------------------------------------------------

class TestEventLifecycle:
    def _row_after(self, status: str, **extras):
        base = {
            "id": 7, "tenant_id": "1", "gap_id": 100, "patient_id": "P1",
            "template_id": 1, "channel": "sms", "status": status,
            "scheduled_for": None, "sent_at": _now() if status != "queued" else None,
            "delivered_at": _now() if status in ("delivered", "responded") else None,
            "responded_at": _now() if status == "responded" else None,
            "response_text": extras.get("response_text"),
            "resulted_in_visit": int(bool(extras.get("resulted_in_visit", 0))),
            "resulted_in_closure": int(bool(extras.get("resulted_in_closure", 0))),
            "metadata": None, "created_at": _now(), "updated_at": _now(),
        }
        return base

    def _make_cm(self, target_row):
        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            calls = {"i": 0}

            def _exec(sql, params=None):
                i = calls["i"]
                calls["i"] += 1
                if i == 0:  # UPDATE
                    cur.rowcount = 1
                else:  # SELECT
                    cur.fetchone.return_value = target_row
            cur.execute.side_effect = _exec
            yield cur
        return _cm

    def test_mark_sent_sets_sent_at(self) -> None:
        with patch(
            "app.services.recapture_outreach_service.raf_cursor",
            self._make_cm(self._row_after("sent")),
        ):
            evt = mark_sent(7)
        assert evt["status"] == "sent"
        assert evt["sent_at"] is not None

    def test_mark_delivered_sets_delivered_at(self) -> None:
        with patch(
            "app.services.recapture_outreach_service.raf_cursor",
            self._make_cm(self._row_after("delivered")),
        ):
            evt = mark_delivered(7)
        assert evt["status"] == "delivered"
        assert evt["delivered_at"] is not None

    def test_mark_response_records_outcome_and_closes_gap(self) -> None:
        target = self._row_after(
            "responded", response_text="Thanks", resulted_in_closure=1,
        )

        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            calls = {"i": 0}

            def _exec(sql, params=None):
                i = calls["i"]
                calls["i"] += 1
                if i == 0:
                    cur.rowcount = 1
                else:
                    cur.fetchone.return_value = target
            cur.execute.side_effect = _exec
            yield cur

        with patch(
            "app.services.recapture_outreach_service.raf_cursor", _cm,
        ), patch(
            "app.services.recapture_gap_service.close_gap"
        ) as mock_close:
            evt = mark_response(
                7, response_text="Thanks",
                resulted_in_visit=True, resulted_in_closure=True,
            )

        assert evt["status"] == "responded"
        assert evt["resulted_in_closure"] is True
        # Closure cascades to recapture_gap_service.close_gap
        mock_close.assert_called_once_with(gap_id=100, tenant_id="1")

    def test_mark_response_without_closure_does_not_close_gap(self) -> None:
        target = self._row_after("responded", resulted_in_visit=1)

        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            calls = {"i": 0}

            def _exec(sql, params=None):
                i = calls["i"]
                calls["i"] += 1
                if i == 0:
                    cur.rowcount = 1
                else:
                    cur.fetchone.return_value = target
            cur.execute.side_effect = _exec
            yield cur

        with patch(
            "app.services.recapture_outreach_service.raf_cursor", _cm,
        ), patch(
            "app.services.recapture_gap_service.close_gap"
        ) as mock_close:
            mark_response(7, resulted_in_visit=True, resulted_in_closure=False)
        mock_close.assert_not_called()

    def test_mark_opted_out_terminal(self) -> None:
        with patch(
            "app.services.recapture_outreach_service.raf_cursor",
            self._make_cm(self._row_after("opted_out")),
        ):
            evt = mark_opted_out(7)
        assert evt["status"] == "opted_out"

    def test_mark_invalid_status_raises(self) -> None:
        with pytest.raises(ValueError, match="not transitionable"):
            mark_event(event_id=7, status="exploded")

    def test_mark_event_dispatches_to_correct_handler(self) -> None:
        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            calls = {"i": 0}

            def _exec(sql, params=None):
                i = calls["i"]
                calls["i"] += 1
                if i == 0:
                    cur.rowcount = 1
                else:
                    cur.fetchone.return_value = self._row_after("sent")
            cur.execute.side_effect = _exec
            yield cur

        with patch("app.services.recapture_outreach_service.raf_cursor", _cm):
            evt = mark_event(event_id=7, status="sent")
        assert evt["status"] == "sent"

    def test_mark_event_rejects_queued(self) -> None:
        # 'queued' is the initial state — not transitionable via mark_event.
        with pytest.raises(ValueError, match="not transitionable"):
            mark_event(event_id=7, status="queued")

    def test_mark_event_not_found_raises(self) -> None:
        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            cur.rowcount = 0
            yield cur

        with patch("app.services.recapture_outreach_service.raf_cursor", _cm):
            with pytest.raises(ValueError, match="not found"):
                mark_event(event_id=999, status="sent")


# ---------------------------------------------------------------------------
# 4. outreach_summary — conversion math + channel breakdown
# ---------------------------------------------------------------------------

class TestOutreachSummary:
    def test_revenue_constant_matches_recapture_service(self) -> None:
        from app.services.recapture_gap_service import _REVENUE_IMPACT_PER_GAP
        assert _REVENUE_PER_CLOSURE == _REVENUE_IMPACT_PER_GAP

    def test_summary_aggregates_correctly(self) -> None:
        channel_rows = [
            {
                "channel": "sms", "total": 100,
                "queued": 10, "sent_or_later": 90, "delivered": 80,
                "responded": 30, "visits": 18, "closed": 12,
            },
            {
                "channel": "portal", "total": 40,
                "queued": 5, "sent_or_later": 35, "delivered": 35,
                "responded": 10, "visits": 5, "closed": 3,
            },
        ]
        overall_row = {
            "total": 140,
            "sent_or_later": 125,   # 90 + 35
            "responded": 40,        # 30 + 10
            "closed": 15,           # 12 + 3
            "avg_days_to_response": 4.25,
        }

        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            calls = {"i": 0}

            def _exec(sql, params=None):
                i = calls["i"]
                calls["i"] += 1
                if i == 0:  # channel breakdown
                    cur.fetchall.return_value = channel_rows
                else:  # overall
                    cur.fetchone.return_value = overall_row
            cur.execute.side_effect = _exec
            yield cur

        with patch("app.services.recapture_outreach_service.raf_cursor", _cm):
            out = outreach_summary(tenant_id="1", year=2026)

        assert out["year"] == 2026
        assert out["total_sent"] == 125
        assert out["total_responded"] == 40
        assert out["total_closed"] == 15
        # Conversion = closed / sent
        assert out["conversion_rate"] == pytest.approx(15 / 125)
        # Revenue = closures × $3,000
        assert out["estimated_revenue"] == pytest.approx(15 * 3000.0)
        assert out["avg_days_to_response"] == pytest.approx(4.25)

        sms = out["by_channel"]["sms"]
        assert sms["sent"] == 90
        assert sms["responded"] == 30
        assert sms["closed"] == 12
        assert sms["response_rate"] == pytest.approx(30 / 90)
        assert sms["visit_rate"] == pytest.approx(18 / 90)
        assert sms["closure_rate"] == pytest.approx(12 / 90)

        portal = out["by_channel"]["portal"]
        assert portal["closure_rate"] == pytest.approx(3 / 35)

    def test_summary_handles_empty_dataset(self) -> None:
        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            calls = {"i": 0}

            def _exec(sql, params=None):
                i = calls["i"]
                calls["i"] += 1
                if i == 0:
                    cur.fetchall.return_value = []
                else:
                    cur.fetchone.return_value = {
                        "total": 0, "sent_or_later": 0, "responded": 0,
                        "closed": 0, "avg_days_to_response": None,
                    }
            cur.execute.side_effect = _exec
            yield cur

        with patch("app.services.recapture_outreach_service.raf_cursor", _cm):
            out = outreach_summary(tenant_id="1")

        assert out["total_sent"] == 0
        assert out["conversion_rate"] == 0.0
        assert out["estimated_revenue"] == 0.0
        assert out["avg_days_to_response"] is None
        assert out["by_channel"] == {}

    def test_summary_no_zero_division_when_channel_has_only_queued(self) -> None:
        channel_rows = [{
            "channel": "sms", "total": 5,
            "queued": 5, "sent_or_later": 0, "delivered": 0,
            "responded": 0, "visits": 0, "closed": 0,
        }]
        overall_row = {
            "total": 5, "sent_or_later": 0, "responded": 0, "closed": 0,
            "avg_days_to_response": None,
        }

        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            calls = {"i": 0}

            def _exec(sql, params=None):
                i = calls["i"]
                calls["i"] += 1
                if i == 0:
                    cur.fetchall.return_value = channel_rows
                else:
                    cur.fetchone.return_value = overall_row
            cur.execute.side_effect = _exec
            yield cur

        with patch("app.services.recapture_outreach_service.raf_cursor", _cm):
            out = outreach_summary(tenant_id="1")

        assert out["by_channel"]["sms"]["closure_rate"] == 0.0
        assert out["by_channel"]["sms"]["response_rate"] == 0.0
        assert out["conversion_rate"] == 0.0


# ---------------------------------------------------------------------------
# 5. get_outreach_history
# ---------------------------------------------------------------------------

class TestOutreachHistory:
    def test_returns_chronological_events(self) -> None:
        rows = [
            {
                "id": 1, "tenant_id": "1", "gap_id": 100, "patient_id": "P1",
                "template_id": 1, "channel": "sms", "status": "sent",
                "scheduled_for": None, "sent_at": _now(),
                "delivered_at": None, "responded_at": None,
                "response_text": None, "resulted_in_visit": 0,
                "resulted_in_closure": 0, "metadata": None,
                "created_at": _now(), "updated_at": _now(),
                "template_name": "SMS Reminder",
            },
            {
                "id": 2, "tenant_id": "1", "gap_id": 100, "patient_id": "P1",
                "template_id": 2, "channel": "phone", "status": "responded",
                "scheduled_for": None, "sent_at": _now(),
                "delivered_at": _now(), "responded_at": _now(),
                "response_text": "Booked appt", "resulted_in_visit": 1,
                "resulted_in_closure": 1, "metadata": None,
                "created_at": _now(), "updated_at": _now(),
                "template_name": "Phone Callback",
            },
        ]

        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            cur.fetchall.return_value = rows
            yield cur

        with patch("app.services.recapture_outreach_service.raf_cursor", _cm):
            events = get_outreach_history(gap_id=100, tenant_id="1")

        assert len(events) == 2
        assert events[0]["channel"] == "sms"
        assert events[1]["resulted_in_visit"] is True
        assert events[1]["resulted_in_closure"] is True

    def test_empty_history(self) -> None:
        @contextmanager
        def _cm(*args, **kwargs):
            cur = MagicMock()
            cur.fetchall.return_value = []
            yield cur

        with patch("app.services.recapture_outreach_service.raf_cursor", _cm):
            events = get_outreach_history(gap_id=999)
        assert events == []


# ---------------------------------------------------------------------------
# 6. Constants surface
# ---------------------------------------------------------------------------

class TestConstants:
    def test_valid_channels(self) -> None:
        assert VALID_CHANNELS == {"sms", "portal", "phone", "email", "letter"}

    def test_valid_statuses(self) -> None:
        assert VALID_STATUSES == {
            "queued", "sent", "delivered", "responded", "failed", "opted_out",
        }

    def test_revenue_per_closure_is_3000(self) -> None:
        assert _REVENUE_PER_CLOSURE == 3000.00
