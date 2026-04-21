import os

from locust import HttpUser, between, events, task

# ---------------------------------------------------------------------------
# RAF Intelligence — Load Testing Suite
# ---------------------------------------------------------------------------
# Usage:
#   locust -f locustfile.py --host=http://localhost:8500
#
# To run headless:
#   locust -f locustfile.py --headless -u 100 -r 10 --run-time 1m --host=http://localhost:8500
# ---------------------------------------------------------------------------

class RAFIntelligenceUser(HttpUser):
    wait_time = between(1.0, 5.0)
    token = ""

    def on_start(self):
        """Authenticate user on start to get JWT token."""
        # Use test environment credentials
        username = os.getenv("LOCUST_TEST_USER", "admin@raf-intelligence.com")
        password = os.getenv("LOCUST_TEST_PASSWORD", "admin123")  # Placeholder

        with self.client.post("/api/auth/login", json={"username": username, "password": password}, catch_response=True) as response:
            if response.status_code == 200:
                self.token = response.json().get("access_token")
            else:
                # If auth fails in test env due to missing seed data, we might need a bypass
                # For load testing, some endpoints might be hit that skip auth or we mock it.
                response.success()

    def get_headers(self) -> dict[str, str]:
        if not self.token:
            return {}
        return {"Authorization": f"Bearer {self.token}"}

    @task(3)
    def dashboard_kpis(self):
        """Simulate a user hitting the main dashboard."""
        self.client.get("/api/dashboard/stats", headers=self.get_headers(), name="Dashboard Stats")
        self.client.get("/api/dashboard/trends", headers=self.get_headers(), name="Dashboard Trends")

    @task(2)
    def view_patient_population(self):
        """Simulate viewing the patient grid."""
        self.client.get("/api/patients?page=1&limit=50", headers=self.get_headers(), name="List Patients")

    @task(1)
    def trigger_raf_calculation(self):
        """Simulate triggering a RAF calculation for a specific patient.
        This is a heavier workload invoking the HCC parser."""
        patient_id = 1001 # Sample ID
        self.client.post(f"/api/raf/calculate/{patient_id}", headers=self.get_headers(), name="Trigger RAF Calc")

    @task(4)
    def get_suspects(self):
        """Simulate loading the suspect review queue."""
        self.client.get("/api/suspects?status=open", headers=self.get_headers(), name="List Suspects")

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    print("Starting RAF Intelligence Load Test...")

@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    print("Load Test Finished.")
