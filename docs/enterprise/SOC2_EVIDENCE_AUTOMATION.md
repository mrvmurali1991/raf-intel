# SOC 2 Type II Evidence Automation

**Goal:** Reduce auditor evidence-request fatigue by collecting deterministic, time-stamped artifacts automatically. Daily snapshots feed Vanta/Drata/A-LIGN ingestion.

**Status:** Operational for 5 high-priority controls. Coverage expands as we close additional audit findings.

---

## Architecture

```
                        Celery beat (raf.soc2.daily_evidence)
                                       │  03:00 UTC daily
                                       ▼
                    ┌──────────────────────────────────┐
                    │  collect_all() in soc2_evidence  │
                    │  - CC6.1  Logical access         │
                    │  - CC6.7  Transmission encryption│
                    │  - CC7.2  Anomaly detection      │
                    │  - CC8.1  Change management      │
                    │  - A1.2   Availability + backup  │
                    └──────────────────┬───────────────┘
                                       │
                  ┌────────────────────┴────────────────────┐
                  ▼                                         ▼
        ┌──────────────────┐                    ┌────────────────────┐
        │ soc2_evidence    │                    │ S3: evidence/      │
        │ (MySQL, append   │                    │ {ctrl}/{date}.json │
        │  -only by RBAC)  │                    │ (long-term archive)│
        └────────┬─────────┘                    └────────────────────┘
                 │
                 ▼
        ┌──────────────────────────┐
        │ GET /api/admin/soc2/...  │
        │ - /controls (list)       │
        │ - /collect (run now)     │
        │ - /latest/{ctrl}         │
        └──────────────────────────┘
                 │
                 ▼
            Vanta / Drata
            (auditor portal)
```

---

## Controls in scope

| Control | Description | Frequency | Evidence type |
|---|---|---|---|
| **CC6.1** | Logical access controls (active users, MFA %, lockouts) | daily | counter snapshot |
| **CC6.7** | Transmission encryption (TLS version, HSTS) | daily | config attestation |
| **CC7.2** | Anomaly detection (failed logins, audit chain integrity) | daily | counter + chain hash |
| **CC8.1** | Change management (alembic head, CI workflows present) | daily | repo snapshot |
| **A1.2** | Availability + backup posture (RTO, RPO, drill cadence) | daily | config attestation |

Trust Services Criteria covered: Security (CC), Availability (A1).

## Controls planned (not yet automated)

| Control | Description | Source |
|---|---|---|
| CC2.1 | Communication of security responsibilities | HR LMS |
| CC3.1 | Risk identification | Risk register |
| CC5.1 | Control activities | Manual evidence |
| C1.1 | Confidentiality commitments | BAA + contract corpus |
| P1.1 (Privacy) | Privacy notice + consent | Frontend + DB |

---

## How auditors use this

1. The auditor (Vanta/Drata/A-LIGN) is granted a read-only API token with role `auditor`.
2. Their integration polls `/api/admin/soc2/controls` to discover what's automated.
3. For each control they pull `/api/admin/soc2/latest/{control_id}` daily and ingest into their evidence corpus.
4. If they want historical: `SELECT evidence_json FROM soc2_evidence WHERE control_id=? ORDER BY collected_at DESC` — we expose this via a paginated endpoint on request.

## Example evidence payload (CC6.1)

```json
{
  "control": "CC6.1",
  "description": "Logical access controls — user/MFA/lockout state",
  "as_of": "2026-05-18T04:21:17.351009",
  "active_users": 142,
  "mfa_enabled": 142,
  "mfa_enrollment_pct": 100.0,
  "locked_accounts": 0,
  "stale_passwords_over_90d": 3
}
```

The auditor flags **stale_passwords_over_90d > 0** as a finding under IA-5 / CC6.1 rotation policy. RAF responds with a remediation plan (force rotation on the 3 users + flag in HR).

---

## Auditor read-only role

Create the auditor account:

```bash
# Admin UI: /admin/users → "Add user"
# email: auditor@vanta.example.com
# role: auditor
# permissions: read-only on soc2_evidence + audit_log
```

The `auditor` role has:
- `Depends(require_permission("soc2", "read"))` access to `/api/admin/soc2/latest/{ctrl}`
- `Depends(require_permission("audit_log", "read"))` for chain verification
- **No** write access anywhere
- **No** PHI access

## Retention

- MySQL row retained 13 months (one full SOC 2 period plus margin).
- S3 archive retained 7 years per HIPAA + most state laws.
- Customer can request deletion of their tenant's evidence rows on contract termination (within the auditor's evidence window).

## How to add a new control

```python
# backend/app/services/soc2_evidence.py

def cc4_1_monitoring(tenant_id: str = "*") -> dict[str, Any]:
    """CC4.1 — Monitoring activities."""
    return {
        "control": "CC4.1",
        "description": "Continuous monitoring evidence",
        "as_of": datetime.utcnow().isoformat(),
        # ... your counters here ...
    }

COLLECTORS["CC4.1"] = cc4_1_monitoring
```

Add a unit test in `tests/test_soc2_evidence.py` that validates the dict shape + smoke-tests the row insert.

## Re-running locally

```bash
TOKEN=$(curl -s -X POST http://localhost:8500/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@raf.health","password":"Admin@123"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Run all collectors now
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8500/api/admin/soc2/collect

# Fetch a single control's latest evidence
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8500/api/admin/soc2/latest/CC6.1 | jq .
```

## References

- `backend/app/services/soc2_evidence.py` — collectors
- `backend/app/routers/soc2_evidence.py` — admin endpoints
- `docs/enterprise/NIST_800_53_CONTROL_MATRIX.md` — broader NIST mapping
- AICPA TSP Section 100 — Trust Services Criteria 2022
