"""Locust load test — realistic coder workflow mix.

Run:
    cd backend
    .venv/bin/locust -f tests/load/locustfile_raf.py \
        --headless --users 50 --spawn-rate 5 --run-time 90s \
        --host http://localhost:8500 --csv=/tmp/raf-perf
"""
from __future__ import annotations

import os
import random

import threading

import requests
from locust import HttpUser, between, task

ADMIN_EMAIL = os.getenv("LOCUST_EMAIL", "admin@raf.health")
ADMIN_PASSWORD = os.getenv("LOCUST_PASSWORD", "Admin@123")

_TOKEN_LOCK = threading.Lock()
_TOKEN: str = ""


def _get_token(host: str) -> str:
    global _TOKEN
    with _TOKEN_LOCK:
        if _TOKEN:
            return _TOKEN
        r = requests.post(
            f"{host}/api/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            timeout=10,
        )
        r.raise_for_status()
        _TOKEN = (r.json() or {}).get("access_token", "")
        return _TOKEN


class CoderWorkflow(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        host = self.host or "http://localhost:8500"
        token = _get_token(host)
        self.client.headers.update({"Authorization": f"Bearer {token}"})

    # 40% — suspect worklist
    @task(40)
    def get_suspects_worklist(self):
        self.client.get("/api/suspects?limit=25", name="GET /api/suspects")

    # 15% — accept a suspect (simulated; doesn't actually mutate prod)
    @task(15)
    def get_v28_impact(self):
        self.client.get(
            "/api/v28-impact/portfolio",
            name="GET /api/v28-impact/portfolio",
        )

    # 20% — patient detail
    @task(20)
    def get_patient_suspects(self):
        pid = random.randint(20, 30)
        self.client.get(
            f"/api/patients/{pid}/suspects",
            name="GET /api/patients/{pid}/suspects",
        )

    @task(5)
    def get_hedis_measures(self):
        self.client.get(
            "/api/hedis/measures", name="GET /api/hedis/measures",
        )

    @task(5)
    def get_radv_runs(self):
        self.client.get(
            "/api/radv/audit-runs", name="GET /api/radv/audit-runs",
        )

    @task(5)
    def get_coder_analytics(self):
        self.client.get(
            "/api/coder-analytics/me", name="GET /api/coder-analytics/me",
        )

    @task(3)
    def get_md_today(self):
        self.client.get(
            "/api/md/today?provider_id=1", name="GET /api/md/today",
        )

    @task(3)
    def get_outreach_health(self):
        self.client.get(
            "/api/outreach/health", name="GET /api/outreach/health",
        )

    @task(2)
    def get_chart_chase_dashboard(self):
        self.client.get(
            "/api/chart-chase/v2/dashboard",
            name="GET /api/chart-chase/v2/dashboard",
        )

    @task(2)
    def get_circuit_status(self):
        self.client.get(
            "/api/fhir/circuit/status",
            name="GET /api/fhir/circuit/status",
        )
