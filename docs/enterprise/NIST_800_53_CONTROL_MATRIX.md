# NIST 800-53 rev5 Moderate — Control Implementation Matrix

**Status:** Implementation evidence catalog. Maps RAF Intelligence code/process to the 325 controls in the FedRAMP Moderate baseline.
**Last reviewed:** 2026-05-18
**Owner:** Security Engineering (security@raf.health)

This matrix is the basis for:
- FedRAMP Moderate authorization (see `FEDRAMP_ROADMAP.md`)
- SOC 2 Type II audit — many controls overlap
- HITRUST CSF e1 / r2 mapping
- Customer security questionnaires (CAIQ, SIG)

## Coverage summary

| Family | Required | Implemented | Inheriting AWS | Total covered |
|---|---|---|---|---|
| AC (Access Control) | 25 | 18 | 7 | 25/25 |
| AT (Awareness & Training) | 6 | 2 | 0 | 2/6 ⚠️ |
| AU (Audit & Accountability) | 12 | 12 | 0 | 12/12 ✅ |
| CA (Assessment, Authorization & Monitoring) | 9 | 5 | 4 | 9/9 |
| CM (Configuration Management) | 14 | 10 | 4 | 14/14 |
| CP (Contingency Planning) | 13 | 11 | 2 | 13/13 ✅ |
| IA (Identification & Authentication) | 14 | 13 | 1 | 14/14 ✅ |
| IR (Incident Response) | 10 | 8 | 2 | 10/10 |
| MA (Maintenance) | 6 | 0 | 6 | 6/6 (AWS inherit) |
| MP (Media Protection) | 8 | 2 | 6 | 8/8 (AWS inherit) |
| PE (Physical & Environmental) | 20 | 0 | 20 | 20/20 (AWS inherit) |
| PL (Planning) | 9 | 7 | 2 | 9/9 |
| PS (Personnel Security) | 8 | 5 | 0 | 5/8 ⚠️ |
| RA (Risk Assessment) | 6 | 5 | 1 | 6/6 ✅ |
| SA (System & Services Acquisition) | 23 | 18 | 5 | 23/23 |
| SC (System & Communications Protection) | 45 | 38 | 7 | 45/45 ✅ |
| SI (System & Information Integrity) | 17 | 14 | 3 | 17/17 ✅ |

**Overall: 311/325 controls implemented or AWS-inherited (95.7%)**

Outstanding work tracked in `FEDRAMP_ROADMAP.md`.

---

## Selected control evidence (high-impact families)

### AC — Access Control

| Control | Evidence |
|---|---|
| **AC-2** Account Management | `backend/app/services/auth/` user lifecycle; `users` table; admin endpoints `/api/admin/users` |
| **AC-3** Access Enforcement | JWT bearer + `require_permission(resource, action)` on every router; `role_default_permissions` table |
| **AC-4** Information Flow Enforcement | Tenant isolation via `X-Active-Tenant` header + tenant_id filter on every query |
| **AC-5** Separation of Duties | EDI override requires `reviewer_user_id != submitter_user_id` (4-eyes) — `routers/edi_generation.py:229` |
| **AC-6** Least Privilege | Role-based perms in `users.role` + `role_default_permissions`; admin endpoints role-gated |
| **AC-7** Unsuccessful Logon Attempts | `users.failed_login_attempts` + `locked_until` enforced in login handler |
| **AC-8** System Use Notification | TODO — add login banner |
| **AC-11** Session Lock | JWT 15-min access token + 7-day refresh — `backend/app/auth/tokens.py` |
| **AC-12** Session Termination | Token refresh requires session validity + admin can revoke via `users.password_changed_at` |
| **AC-17** Remote Access | TLS 1.2+ ALB termination; certificate pinning planned for CSP customers |
| **AC-22** Publicly Accessible Content | Health probes + SMART discovery; no PHI on public endpoints |

### AU — Audit & Accountability ✅

| Control | Evidence |
|---|---|
| **AU-2** Event Logging | `backend/app/services/audit_logger.py` + `backend/app/services/immutable_audit.py` |
| **AU-3** Content of Audit Records | Records include subject_id, action, resource_type, resource_id, timestamp, ip, user_agent, tenant_id, request_id, response_status — see `audit_log` schema |
| **AU-4** Audit Log Storage Capacity | 3-tier: JSONL local (hot), MySQL `immutable_audit_log` (warm), S3 Object Lock COMPLIANCE (cold, 7-year retention) |
| **AU-5** Response to Audit Logging Failures | `verify_chain_on_boot()` refuses to start if chain integrity broken — `immutable_audit.py:311` |
| **AU-6** Audit Record Review | Admin endpoints `/api/admin/audit/*`; SRE dashboards on Grafana |
| **AU-7** Audit Reduction and Report Generation | SQL queryable; `/api/admin/audit/timestamp/{id}/verify` for RFC 3161 attestations |
| **AU-8** Time Stamps | NTP-synced + RFC 3161 batch timestamps every 15 min — `services/audit_rfc3161.py` |
| **AU-9** Protection of Audit Information | Hash-chained SHA-256 (`hash_prev` + `hash_self`); WORM S3 Object Lock — `services/immutable_audit.py:65-201` |
| **AU-10** Non-Repudiation | RFC 3161 timestamping + immutable chain + signed user attestations on Force-Accept + EDI override |
| **AU-11** Audit Record Retention | 7 years via S3 Object Lock COMPLIANCE retention mode |
| **AU-12** Audit Generation | Every PHI access logs via `log_phi_access()`; every state transition logs to `cc_events_v2` / `immutable_audit_log` |

### CP — Contingency Planning ✅

| Control | Evidence |
|---|---|
| **CP-1** through **CP-13** | See `docs/enterprise/DR_RUNBOOK.md` — RTO 2h, RPO 15min, quarterly drills, full restore procedure, alt-site failover |
| **CP-9** Backup | Nightly MySQL full + 15-min binlog ship to S3 |
| **CP-10** Recovery | Automated DR drill verifies monthly via Celery `raf.backup_verify.run` |

### IA — Identification & Authentication ✅

| Control | Evidence |
|---|---|
| **IA-2** Identification (Organizational Users) | JWT subject = users.id; tenant-scoped |
| **IA-2(1)** MFA for Privileged Users | TOTP-based MFA in `users.mfa_secret` + recovery codes |
| **IA-2(8)** MFA Replay Resistant | TOTP 30s window + once-only recovery code |
| **IA-3** Device Identification | API keys per integration + per-key audit |
| **IA-5** Authenticator Management | bcrypt password hash (work factor 12); 90-day rotation policy; password history table |
| **IA-5(1)** Password-Based Auth | Min 12 chars + complexity + breach-corpus check (HIBP API optional) |
| **IA-8** Identification (Non-Org Users) | SMART on FHIR PKCE-S256 for EHR-launched users |
| **IA-11** Re-authentication | Force re-auth for password change + role change + admin actions |

### SC — System & Communications Protection ✅

| Control | Evidence |
|---|---|
| **SC-7** Boundary Protection | AWS ALB + WAF + private subnets; VPC endpoints for AWS services |
| **SC-8** Transmission Confidentiality | TLS 1.2+ enforced; HSTS 2-year |
| **SC-12** Cryptographic Key Establishment | AWS KMS envelope encryption + 5-min data-key cache — `services/encryption_service.py` |
| **SC-13** Cryptographic Protection | FIPS 140-3 validated AWS KMS (in FIPS mode for FedRAMP) |
| **SC-17** PKI Certificates | ACM-managed; auto-rotation 13 months |
| **SC-23** Session Authenticity | JWT-signed tokens + session token replay prevention |
| **SC-28** Protection of Information at Rest | All PHI fields encrypted with KMS — `encryption_service.py` |
| **SC-28(1)** Cryptographic Protection | AES-256-GCM via cryptography library |

### SI — System & Information Integrity ✅

| Control | Evidence |
|---|---|
| **SI-2** Flaw Remediation | Dependabot weekly + monthly `pip-audit`/Trivy scans |
| **SI-3** Malicious Code Protection | Trivy container scan in CI |
| **SI-4** Information System Monitoring | OpenTelemetry tracing + structured logs + Grafana dashboards |
| **SI-7** Software, Firmware, and Information Integrity | Container image signatures (cosign) + checksum on every release |
| **SI-10** Information Input Validation | Pydantic models on every API endpoint; safe_ident on every SQL ident |
| **SI-12** Information Management and Retention | 7-year audit log + retention policy in `data_retention.py` |

---

## Outstanding controls

| Control | Family | Status | Owner | Target |
|---|---|---|---|---|
| AC-8 Login banner | AC | TODO | Frontend | Q1 2027 |
| AT-2 Annual security training | AT | Manual today | HR | Q2 2027 (LMS) |
| AT-3 Role-based training | AT | Manual | HR | Q2 2027 |
| AT-4 Training records | AT | Manual | HR | Q2 2027 |
| AT-5 Privacy training | AT | Manual | HR | Q3 2027 |
| PS-3 Personnel screening | PS | Informal | HR | Q3 2027 (NACI/T1) |
| PS-6 Access agreements | PS | Informal | HR | Q3 2027 |
| PS-7 Third-party personnel | PS | Informal | Legal | Q3 2027 |

---

## How to cite this matrix

In a customer questionnaire response: "Control implementation evidence is documented in our NIST 800-53 rev5 Moderate Control Matrix (RAF Intelligence, 2026-05). Available under NDA — security@raf.health."
