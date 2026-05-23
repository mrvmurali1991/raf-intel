"""Outreach DLQ + FHIR per-tenant circuit-breaker — unit tests.

These tests use the actual SQL helpers + the circuit-breaker registry. The
DLQ tests rely on the live MySQL via raf_cursor; mark them `integration`
so they're excluded from `pytest -m "not integration"` fast runs.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# FHIR circuit-breaker tests — pure-Python, no DB
# ---------------------------------------------------------------------------

class TestPerTenantCircuitBreaker:
    def setup_method(self) -> None:
        # Reset the keyed registry between tests
        from app.services import circuit_breaker as cb_mod
        cb_mod._keyed_breakers.clear()

    def test_separate_breakers_per_tenant_isolated(self) -> None:
        from app.services.circuit_breaker import get_breaker
        cb_a = get_breaker("fhir:tenant_a:url", failure_threshold=3)
        cb_b = get_breaker("fhir:tenant_b:url", failure_threshold=3)
        for _ in range(3):
            cb_a.record_failure()
        assert cb_a.state.value == "open"
        assert cb_b.state.value == "closed"

    def test_5_consecutive_failures_opens_circuit(self) -> None:
        from app.services.circuit_breaker import (
            CircuitBreakerError,
            get_breaker,
        )
        cb = get_breaker("fhir:t1:url", failure_threshold=5, recovery_timeout=60.0)

        def boom():
            raise RuntimeError("502")

        wrapped = cb(boom)
        for _ in range(5):
            with pytest.raises(RuntimeError):
                wrapped()
        assert cb.state.value == "open"
        with pytest.raises(CircuitBreakerError):
            wrapped()  # 6th attempt fails fast

    def test_circuit_half_open_after_recovery_timeout(self) -> None:
        from app.services.circuit_breaker import (
            CircuitState,
            get_breaker,
        )
        cb = get_breaker("fhir:t2:url", failure_threshold=2, recovery_timeout=0.1)
        for _ in range(2):
            cb.record_failure()
        assert cb._state == CircuitState.OPEN
        time.sleep(0.15)
        # Reading state property transitions to HALF_OPEN once timeout elapses
        assert cb.state == CircuitState.HALF_OPEN

    def test_record_success_closes_circuit(self) -> None:
        from app.services.circuit_breaker import (
            CircuitState,
            get_breaker,
        )
        cb = get_breaker("fhir:t3:url", failure_threshold=2)
        cb.record_failure()
        cb.record_failure()
        assert cb._state == CircuitState.OPEN
        cb.record_success()
        assert cb._state == CircuitState.CLOSED
        assert cb._failure_count == 0

    def test_all_breakers_status_snapshot(self) -> None:
        from app.services.circuit_breaker import all_breakers_status, get_breaker
        get_breaker("fhir:t_aa:url", failure_threshold=2).record_failure()
        get_breaker("fhir:t_bb:url", failure_threshold=2)
        snap = all_breakers_status()
        keys = {s["key"] for s in snap}
        assert "fhir:t_aa:url" in keys
        assert "fhir:t_bb:url" in keys
        aa = next(s for s in snap if s["key"] == "fhir:t_aa:url")
        assert aa["consecutive_failures"] == 1


# ---------------------------------------------------------------------------
# Outreach template PHI-safety — pure-Python, no DB
# ---------------------------------------------------------------------------

class TestOutreachTemplatePhiSafety:
    def test_sms_templates_have_no_diagnosis_terms(self) -> None:
        from app.services.outreach.templates import (
            template_is_phi_safe,
        )
        for measure in ("AWV", "BCS", "CCS", "HBD", "CBP", "FUM"):
            assert template_is_phi_safe(measure, "sms"), (
                f"SMS template for {measure} contains a banned diagnosis term"
            )

    def test_voice_templates_have_no_diagnosis_terms(self) -> None:
        from app.services.outreach.templates import template_is_phi_safe
        for measure in ("AWV", "BCS", "CCS", "HBD", "CBP", "FUM"):
            assert template_is_phi_safe(measure, "voice"), (
                f"Voice template for {measure} contains a banned diagnosis term"
            )

    def test_sms_template_includes_opt_out_footer(self) -> None:
        from app.services.outreach.templates import get_template
        body = get_template("AWV", "sms")
        assert "STOP" in body.upper()

    def test_email_template_has_unsubscribe_token(self) -> None:
        from app.services.outreach.templates import get_template
        html = get_template("AWV", "email")
        assert "{unsubscribe_url}" in html


# ---------------------------------------------------------------------------
# Outreach orchestrator DLQ — requires raf_cursor (live DB)
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestOutreachDLQ:
    def setup_method(self) -> None:
        from app.db import raf_cursor
        with raf_cursor() as cur:
            cur.execute(
                "DELETE FROM outreach_messages WHERE patient_id BETWEEN 90001 AND 90099"
            )
            cur.execute(
                "DELETE FROM outreach_consents WHERE patient_id BETWEEN 90001 AND 90099"
            )

    def teardown_method(self) -> None:
        self.setup_method()

    def test_enqueue_sms_without_twilio_creds_marks_failed(self) -> None:
        from app.services.outreach.orchestrator import enqueue_outreach
        with patch.dict("os.environ", {}, clear=False) as env:
            env.pop("TWILIO_ACCOUNT_SID", None)
            env.pop("TWILIO_AUTH_TOKEN", None)
            r = enqueue_outreach(
                tenant_id="1",
                patient_id=90001,
                measure_id="AWV",
                channel="sms",
                to_address="+15551234567",
                first_name="DLQ",
            )
        assert r["status"] == "failed"

    def test_enqueue_email_without_sendgrid_marks_failed(self) -> None:
        from app.services.outreach.orchestrator import enqueue_outreach
        with patch.dict("os.environ", {}, clear=False) as env:
            env.pop("SENDGRID_API_KEY", None)
            r = enqueue_outreach(
                tenant_id="1",
                patient_id=90002,
                measure_id="BCS",
                channel="email",
                to_address="test@example.com",
                first_name="DLQ",
            )
        assert r["status"] == "failed"

    def test_replay_failed_message_creates_new_attempt(self) -> None:
        from app.services.outreach.orchestrator import (
            enqueue_outreach,
            replay_message,
        )
        r1 = enqueue_outreach(
            tenant_id="1",
            patient_id=90003,
            measure_id="CCS",
            channel="sms",
            to_address="+15551234567",
            first_name="DLQ",
        )
        assert r1["status"] == "failed"
        r2 = replay_message("1", int(r1["message_id"]), actor_user_id=1)
        assert r2.get("replayed_message_id") and \
               r2["replayed_message_id"] != r1["message_id"]

    def test_replay_respects_opt_out(self) -> None:
        from app.services.outreach.orchestrator import (
            enqueue_outreach,
            record_opt_out,
            replay_message,
        )
        r1 = enqueue_outreach(
            tenant_id="1",
            patient_id=90004,
            measure_id="FUM",
            channel="sms",
            to_address="+15551234567",
            first_name="DLQ",
        )
        record_opt_out("1", 90004, "sms", reason="test")
        r2 = replay_message("1", int(r1["message_id"]), actor_user_id=1)
        assert r2["status"] == "opted_out"

    def test_health_probe_shows_unconfigured_when_creds_missing(self) -> None:
        from app.services.outreach.orchestrator import (
            enqueue_outreach,
            outreach_health,
        )
        with patch.dict("os.environ", {}, clear=False) as env:
            env.pop("TWILIO_ACCOUNT_SID", None)
            env.pop("TWILIO_AUTH_TOKEN", None)
            env.pop("SENDGRID_API_KEY", None)
            enqueue_outreach(
                tenant_id="1",
                patient_id=90005,
                measure_id="HBD",
                channel="sms",
                to_address="+15551234567",
                first_name="Health",
            )
            h = outreach_health("1")
        assert h["twilio_configured"] is False
        assert h["sendgrid_configured"] is False
        assert h["failed_provider_unconfigured_24h"] >= 1
