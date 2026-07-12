#!/usr/bin/env python3
"""
RAF Intelligence — FHIR Connection Demo Script
===============================================
Run this while screen-recording to demonstrate OpenEMR FHIR integration.

Usage:
    python3 scripts/demo_fhir_connect.py

What it does (step by step, with pauses for video):
1. Registers an OAuth2 API client on OpenEMR
2. Authenticates via password grant
3. Authorizes FHIR scopes (opens browser automatically)
4. Pulls patients, conditions, encounters via FHIR R4
5. Displays results in a clean table
"""

import json
import sys
import time
import webbrowser
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OPENEMR_URL = "https://openemr.ehrservicedesk.com"
OAUTH2_BASE = f"{OPENEMR_URL}/oauth2/default"
FHIR_BASE = f"{OPENEMR_URL}/apis/default/fhir"
REDIRECT_URI = "http://127.0.0.1:9999/callback"

USERNAME = os.getenv("OPENEMR_ADMIN_USER", "admin")
PASSWORD = os.getenv("OPENEMR_ADMIN_PASSWORD", "")

# ---------------------------------------------------------------------------
# Pretty printing helpers
# ---------------------------------------------------------------------------

GREEN = "\033[92m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def step(num, text):
    print(f"\n{BOLD}{CYAN}━━━ Step {num}: {text} ━━━{RESET}\n")
    time.sleep(1)


def success(text):
    print(f"  {GREEN}✓ {text}{RESET}")


def info(text):
    print(f"  {DIM}{text}{RESET}")


def warn(text):
    print(f"  {YELLOW}⚠ {text}{RESET}")


def error(text):
    print(f"  {RED}✗ {text}{RESET}")


def print_table(headers, rows):
    """Print a nicely formatted table."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    header_line = "  │ ".join(f"{BOLD}{h:<{widths[i]}}{RESET}" for i, h in enumerate(headers))
    sep_line = "──┼─".join("─" * w for w in widths)
    print(f"  {header_line}")
    print(f"  {DIM}{sep_line}{RESET}")
    for row in rows:
        line = "  │ ".join(f"{str(c):<{widths[i]}}" for i, c in enumerate(row))
        print(f"  {line}")


# ---------------------------------------------------------------------------
# OAuth2 callback server (captures authorization code from browser redirect)
# ---------------------------------------------------------------------------

auth_code = None


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        auth_code = params.get("code", [None])[0]

        # Show success page in browser
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        html = """
        <html><body style="font-family: Inter, sans-serif; display:flex; align-items:center;
        justify-content:center; height:100vh; background:#0F172A; color:white; text-align:center;">
        <div>
            <div style="font-size:64px; margin-bottom:20px;">✅</div>
            <h1 style="font-size:28px; margin:0 0 8px;">Authorization Successful!</h1>
            <p style="color:#94A3B8; font-size:16px;">
                RAF Intelligence is now connected to OpenEMR via FHIR R4.<br>
                You can close this tab.
            </p>
        </div>
        </body></html>
        """
        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        pass  # Suppress noisy HTTP logs


# ---------------------------------------------------------------------------
# Main demo flow
# ---------------------------------------------------------------------------

def main():
    global auth_code

    print(f"\n{BOLD}{CYAN}╔══════════════════════════════════════════════════════╗{RESET}")
    print(f"{BOLD}{CYAN}║   RAF Intelligence — FHIR R4 Connection Demo        ║{RESET}")
    print(f"{BOLD}{CYAN}║   OpenEMR: {OPENEMR_URL:<40} ║{RESET}")
    print(f"{BOLD}{CYAN}╚══════════════════════════════════════════════════════╝{RESET}")

    # ── Step 1: Register OAuth2 Client ──────────────────────────────────
    step(1, "Register OAuth2 API Client")

    info(f"Endpoint: {OAUTH2_BASE}/registration")

    SCOPES = (
        "openid api:fhir api:oemr "
        "user/Patient.read user/Encounter.read user/Condition.read "
        "user/Observation.read user/Procedure.read "
        "user/AllergyIntolerance.read user/MedicationRequest.read "
        "user/Coverage.read user/Immunization.read"
    )

    reg_resp = requests.post(f"{OAUTH2_BASE}/registration", json={
        "application_type": "private",
        "client_name": "RAF Intelligence FHIR Demo",
        "token_endpoint_auth_method": "client_secret_post",
        "grant_types": ["authorization_code", "password"],
        "redirect_uris": [REDIRECT_URI],
        "contacts": ["admin@rafintelligence.com"],
        "scope": SCOPES,
    })

    if reg_resp.status_code != 200 and reg_resp.status_code != 201:
        error(f"Registration failed: {reg_resp.text}")
        sys.exit(1)

    reg = reg_resp.json()
    client_id = reg["client_id"]
    client_secret = reg["client_secret"]

    success("API Client registered successfully")
    info(f"Client ID:     {client_id[:30]}...")
    info(f"Client Secret: {client_secret[:15]}...")
    info(f"Scopes:        {SCOPES[:60]}...")

    # ── Step 2: Authorize via Browser ───────────────────────────────────
    step(2, "Authorize FHIR Access (Browser)")

    # Start local callback server
    server = HTTPServer(("127.0.0.1", 9999), CallbackHandler)

    # Build authorize URL
    auth_url = (
        f"{OAUTH2_BASE}/authorize?"
        f"response_type=code&"
        f"client_id={urllib.parse.quote(client_id)}&"
        f"redirect_uri={urllib.parse.quote(REDIRECT_URI)}&"
        f"scope={urllib.parse.quote(SCOPES)}&"
        f"state=raf-demo"
    )

    info("Opening browser for OAuth2 authorization...")
    info("Login with your OpenEMR admin credentials and click 'Authorize'")
    print()
    webbrowser.open(auth_url)

    # Wait for callback — keep serving until we get the code
    print(f"  {YELLOW}Waiting for authorization (click Authorize in browser)...{RESET}", end="", flush=True)
    server.timeout = 180
    while auth_code is None:
        server.handle_request()

    server.server_close()

    if not auth_code:
        error("Authorization timed out (2 minutes). Please try again.")
        sys.exit(1)

    print(f"\r  {GREEN}✓ Authorization code received!{' ' * 30}{RESET}")

    # ── Step 3: Exchange Code for Token ─────────────────────────────────
    step(3, "Exchange Authorization Code for Access Token")

    token_resp = requests.post(f"{OAUTH2_BASE}/token", data={
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": auth_code,
        "redirect_uri": REDIRECT_URI,
    })

    if token_resp.status_code != 200:
        # Fallback: try password grant
        warn("Auth code exchange failed, trying password grant...")
        token_resp = requests.post(f"{OAUTH2_BASE}/token", data={
            "grant_type": "password",
            "client_id": client_id,
            "client_secret": client_secret,
            "user_role": "users",
            "username": USERNAME,
            "password": PASSWORD,
            "scope": SCOPES,
        })

    if token_resp.status_code != 200:
        error(f"Token exchange failed: {token_resp.text}")
        sys.exit(1)

    token_data = token_resp.json()
    access_token = token_data["access_token"]
    granted_scopes = token_data.get("scope", "")

    success("Access token obtained!")
    info(f"Token type:     {token_data.get('token_type', 'Bearer')}")
    info(f"Expires in:     {token_data.get('expires_in', '?')} seconds")
    info(f"Scopes granted: {granted_scopes or '(check JWT claims)'}")

    headers = {"Authorization": f"Bearer {access_token}"}

    # ── Step 4: Pull Patients ───────────────────────────────────────────
    step(4, "Pull Patients via FHIR R4")

    info(f"GET {FHIR_BASE}/Patient?_count=10")
    pat_resp = requests.get(f"{FHIR_BASE}/Patient?_count=10", headers=headers)

    if pat_resp.status_code != 200:
        # Try alternate FHIR path
        pat_resp = requests.get(f"{OPENEMR_URL}/apis/default/fhir/R4/Patient?_count=10", headers=headers)

    if pat_resp.status_code == 200:
        bundle = pat_resp.json()
        entries = bundle.get("entry", [])
        total = bundle.get("total", len(entries))
        success(f"Retrieved {total} patients")

        rows = []
        patient_ids = []
        for e in entries[:10]:
            r = e.get("resource", {})
            pid = r.get("id", "?")
            patient_ids.append(pid)
            names = r.get("name", [{}])
            name = "Unknown"
            if names:
                given = " ".join(names[0].get("given", []))
                family = names[0].get("family", "")
                name = f"{given} {family}".strip()
            dob = r.get("birthDate", "?")
            gender = r.get("gender", "?")
            rows.append((pid, name, dob, gender))

        print()
        print_table(["ID", "Name", "DOB", "Gender"], rows)
    else:
        error(f"Failed to pull patients: {pat_resp.status_code}")
        warn(pat_resp.text[:200])
        patient_ids = []

    # ── Step 5: Pull Conditions (Diagnoses) ─────────────────────────────
    step(5, "Pull Conditions / ICD-10 Codes via FHIR R4")

    if patient_ids:
        pid = patient_ids[0]
        info(f"GET {FHIR_BASE}/Condition?patient={pid}")
        cond_resp = requests.get(f"{FHIR_BASE}/Condition?patient={pid}&_count=10", headers=headers)

        if cond_resp.status_code == 200:
            bundle = cond_resp.json()
            entries = bundle.get("entry", [])
            success(f"Retrieved {len(entries)} conditions for patient {pid}")

            rows = []
            for e in entries[:10]:
                r = e.get("resource", {})
                code_obj = r.get("code", {})
                codings = code_obj.get("coding", [{}])
                code = codings[0].get("code", "?") if codings else "?"
                display = codings[0].get("display", code_obj.get("text", "?")) if codings else "?"
                system = codings[0].get("system", "?") if codings else "?"
                status = r.get("clinicalStatus", {})
                status_text = status.get("coding", [{}])[0].get("code", "?") if isinstance(status, dict) else "?"
                rows.append((code, display[:45], status_text, system.split("/")[-1][:15]))

            if rows:
                print()
                print_table(["Code", "Description", "Status", "System"], rows)
            else:
                info("No conditions found for this patient")
        else:
            warn(f"Conditions: {cond_resp.status_code}")

    # ── Step 6: Pull Encounters ─────────────────────────────────────────
    step(6, "Pull Encounters via FHIR R4")

    if patient_ids:
        pid = patient_ids[0]
        info(f"GET {FHIR_BASE}/Encounter?patient={pid}")
        enc_resp = requests.get(f"{FHIR_BASE}/Encounter?patient={pid}&_count=10", headers=headers)

        if enc_resp.status_code == 200:
            bundle = enc_resp.json()
            entries = bundle.get("entry", [])
            success(f"Retrieved {len(entries)} encounters for patient {pid}")

            rows = []
            for e in entries[:10]:
                r = e.get("resource", {})
                eid = r.get("id", "?")
                period = r.get("period", {})
                start = period.get("start", "?")[:10]
                enc_class = r.get("class", {})
                class_code = enc_class.get("code", "?") if isinstance(enc_class, dict) else "?"
                status = r.get("status", "?")
                rows.append((eid, start, class_code, status))

            if rows:
                print()
                print_table(["Encounter ID", "Date", "Class", "Status"], rows)
        else:
            warn(f"Encounters: {enc_resp.status_code}")

    # ── Done ────────────────────────────────────────────────────────────
    print(f"\n{BOLD}{GREEN}━━━ Connection Successful! ━━━{RESET}\n")
    print(f"  {BOLD}FHIR Base URL:{RESET}  {FHIR_BASE}")
    print(f"  {BOLD}Token URL:{RESET}      {OAUTH2_BASE}/token")
    print(f"  {BOLD}Client ID:{RESET}      {client_id}")
    print(f"  {BOLD}Auth Method:{RESET}    OAuth2 (SMART on FHIR)")
    print()
    print(f"  {DIM}No database credentials or IP addresses required.{RESET}")
    print(f"  {DIM}All data flows through standard FHIR R4 API.{RESET}")
    print()


if __name__ == "__main__":
    main()
