# Threat Model — RAF Intelligence

**Framework:** STRIDE per surface
**Last reviewed:** 2026-05-18
**Review cadence:** before each major release; full re-walk annually
**Owner:** Security Engineering (security@raf.health)

---

## 1. Trust boundaries

```
                  ┌─────────────────────────────┐
                  │  Internet                    │
                  └──────────────┬───────────────┘
                                 │  TLS 1.2+ + HSTS
                ┌────────────────▼─────────────────┐
                │  ALB (TB1)  WAF + rate limit     │
                └────────────────┬─────────────────┘
                                 │  internal TLS
        ┌────────────────────────▼──────────────────────────┐
        │  raf-backend (TB2)   FastAPI + auth middleware    │
        │   - JWT verification                              │
        │   - Tenant isolation enforcement                  │
        │   - PHI scrubbing                                 │
        └──┬──────────────┬──────────────┬────────────┬─────┘
           │              │              │            │
   ┌───────▼──────┐ ┌─────▼─────┐ ┌──────▼──────┐ ┌──▼──────────────┐
   │ MySQL (TB3)  │ │ Redis(TB4)│ │ S3 WORM(TB5)│ │ External APIs   │
   │ RAF + EMR    │ │ Celery    │ │ Audit log   │ │ Gemini/Twilio/  │
   │ tenant_id    │ │ broker    │ │ Object Lock │ │ SendGrid/EHR(TB6)│
   └──────────────┘ └───────────┘ └─────────────┘ └─────────────────┘
```

---

## 2. STRIDE by surface

### Surface A — Public HTTPS endpoint (TB1 → TB2)

| Threat | Vector | Mitigation | Residual |
|---|---|---|---|
| **S**poofing | Forged JWT | RS256 signature + 32-byte secret; `iat`/`exp` checked; revocation via `users.password_changed_at` | LOW |
| **T**ampering | Modified body | TLS + Pydantic validation per route | LOW |
| **R**epudiation | User denies action | Hash-chained immutable audit log + RFC 3161 timestamps; force-accept reason + MRN re-entry | LOW |
| **I**nformation Disclosure | Endpoint without auth gate | In-router `Depends(get_current_user)` on every router constructor + global middleware (belt-and-suspenders) | LOW |
| **D**enial of Service | High-volume traffic | AWS WAF rate limit 1000/5min per IP + per-endpoint rate limit via `limiter` | MEDIUM |
| **E**levation of Privilege | Role injection in token | Role read from JWT `claims.role` only — never from request body; admin endpoints check `current_user.role` explicitly | LOW |

### Surface B — Application logic (TB2)

| Threat | Vector | Mitigation | Residual |
|---|---|---|---|
| Spoofing | Tenant header injection | Tenant from JWT claim, not X-Active-Tenant on protected routes; admin role downrank | LOW |
| Tampering | SQL injection | Parameterized queries everywhere; `safe_ident()` for dynamic identifiers — `services/sql_safety.py` | LOW |
| Tampering | Stored XSS in clinical notes | Frontend uses React text rendering (no `dangerouslySetInnerHTML` on PHI); CSP `Content-Security-Policy: default-src 'self'` | LOW |
| Repudiation | Bulk override via API | EDI override requires `len(patient_ids) == 1` + 4-eyes co-signer + 30-char reason | LOW |
| Info Disclosure | PHI in logs / Sentry | `_scrub_phi()` middleware redacts before any external log emit | LOW |
| Info Disclosure | PHI in span attributes | Documented PHI key blacklist in `OBSERVABILITY.md`; `safe_span_attrs()` helper | MEDIUM (review needed for OTel) |
| DoS | NLP / FHIR slow paths | Per-tenant FHIR circuit breaker + 5s timeout; Celery hand-off for async write-back | LOW |
| EoP | NLP hallucinated suspect → write-back | Verbatim-substring guard + 0.85 write-back floor + clinician MEAT signature required | LOW |

### Surface C — Database (TB3)

| Threat | Vector | Mitigation | Residual |
|---|---|---|---|
| Spoofing | Tenant cross-read | Every query in `services/*` filters `WHERE tenant_id=%s`; periodic audit via `tests/integration/test_tenant_isolation.py` | LOW |
| Tampering | Direct DB write bypassing audit | DB in private subnet; no DBA access in prod without ticket + audit; immutable audit chain detects unbounded inserts | MEDIUM |
| Tampering | Schema drift via untested migration | Alembic upgrade gated on staging; integrity check `verify_chain_on_boot()` on each backend start | LOW |
| Info Disclosure | At-rest encryption key compromise | CMK/BYOK in customer KMS for single-tenant; AWS RDS encryption at rest with rotation | LOW |
| Info Disclosure | Backup leak | S3 KMS encryption; bucket policy denies non-TLS + foreign principals; IAM-controlled access | LOW |
| DoS | Unbounded query | Query timeout 30s; pagination required on every list endpoint | LOW |
| EoP | SQL identifier injection (table name) | `safe_ident()` rejects anything outside `[a-zA-Z_][a-zA-Z0-9_]{0,63}` | LOW |

### Surface D — Audit log (TB5)

| Threat | Vector | Mitigation | Residual |
|---|---|---|---|
| Tampering | rm of JSONL | DB cross-check on every append (`AuditChainTamperError`); `verify_chain_on_boot()` refuses to start with divergent state | LOW |
| Tampering | DB row delete | S3 Object Lock COMPLIANCE 7-year retention — even root cannot delete | LOW |
| Tampering | Hash chain forgery | SHA-256 chain + RFC 3161 timestamps from external TSA every 15 min — independent verification | LOW |
| Repudiation | Disputed chain validity | TSA token verifiable cryptographically via `/api/admin/audit/timestamp/{id}/verify` | LOW |

### Surface E — External APIs (TB6)

| Threat | Vector | Mitigation | Residual |
|---|---|---|---|
| Spoofing | Forged webhook | Twilio HMAC-SHA1, SendGrid ECDSA signature verification — `routers/outreach_v2.py` | LOW |
| Tampering | MITM on FHIR push | TLS 1.2+ + cert pinning option per tenant | LOW |
| Info Disclosure | PHI in template | SMS/voice templates contain NO diagnosis names — `template_is_phi_safe()` enforced + tested | LOW |
| Info Disclosure | Gemini retains note | Google BAA mandates zero retention for API customers; logged for compliance review | MEDIUM |
| DoS | EHR rate limit | Per-tenant circuit breaker + retry with exponential back-off | LOW |
| EoP | Compromised vendor key | Lazy-import; key in AWS Secrets Manager; rotated quarterly; outreach falls back to letter channel | LOW |

### Surface F — Coder / Operator (people)

| Threat | Vector | Mitigation | Residual |
|---|---|---|---|
| Spoofing | Phishing → password | Mandatory MFA on admin; HIBP breach-corpus check on password set; 90-day rotation | MEDIUM |
| Repudiation | Coder denies acceptance | Force-Accept requires MRN re-entry + 20-char reason + immutable audit | LOW |
| Info Disclosure | Screen scraping | Session timeout + screen-lock advisory; PHI watermarking planned | MEDIUM |
| EoP | Insider abuse | Quarterly access review + role-based perms + dual-control for sensitive admin (e.g. retention policy changes) | MEDIUM |

---

## 3. Top 10 risks (current)

| # | Risk | Likelihood | Impact | Score | Mitigation |
|---|---|---|---|---|---|
| 1 | Phishing of admin account | M | H | 9 | MFA mandatory; HIBP check; quarterly training |
| 2 | Insider downloads bulk PHI | L | H | 6 | Per-export audit + size cap (10k rows); quarterly access review |
| 3 | DDoS at ALB | M | M | 6 | AWS Shield Standard + WAF; auto-scale |
| 4 | Compromised third-party vendor (Twilio/SendGrid) | L | M | 4 | BAA + sub-processor list; rotation; tenant isolation in templates |
| 5 | Gemini retains a clinical note | L | H | 6 | BAA mandates zero retention; quarterly verification |
| 6 | Audit chain tamper attempt | L | H | 6 | Hash chain + RFC 3161 + S3 WORM |
| 7 | Schema migration corrupts data | L | H | 6 | Alembic test on staging; PITR backup |
| 8 | SQL injection via unsanitized identifier | L | H | 6 | `safe_ident()` + Bandit B608 scan in CI |
| 9 | Stored XSS in coder UI | L | M | 4 | React + CSP; no `dangerouslySetInnerHTML` on PHI |
| 10 | OTel span leaks PHI | M | M | 6 | Documented PHI key blacklist; `safe_span_attrs()` helper |

---

## 4. Risk treatment

Risks at score ≥ 9 require a documented mitigation plan; ≥ 6 are tracked in the security backlog; < 6 accepted and re-reviewed annually.

This document is reviewed:
- before every major release (semver minor or major bump)
- annually as a full re-walk
- after any security incident

## 5. References

- `docs/enterprise/NIST_800_53_CONTROL_MATRIX.md` — control implementation evidence
- `docs/enterprise/DR_RUNBOOK.md` — incident response
- `docs/enterprise/SECURITY_SCAN_BASELINE.md` — Bandit/Trivy findings
- `SECURITY.md` — disclosure policy
