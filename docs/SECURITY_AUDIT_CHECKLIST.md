# RAF Intelligence -- Security Audit Checklist & HIPAA Compliance Assessment

**Application:** RAF Intelligence (HCC/RAF Coding Platform)
**Classification:** Healthcare SaaS handling ePHI
**Tech Stack:** FastAPI (Python) + MySQL + Gemini AI / Next.js + React / Docker on Ubuntu
**Date Created:** 2026-04-01
**Review Cycle:** Quarterly (minimum) or after any significant architecture change

---

## Table of Contents

1. [Authentication Security](#1-authentication-security)
2. [Authorization & Access Control](#2-authorization--access-control)
3. [Data Protection](#3-data-protection)
4. [HIPAA Technical Safeguards (45 CFR 164.312)](#4-hipaa-technical-safeguards)
5. [Application Security (OWASP)](#5-application-security-owasp)
6. [Infrastructure Security](#6-infrastructure-security)
7. [AI/ML Security (Gemini Integration)](#7-aiml-security-gemini-integration)
8. [Compliance Checklist](#8-compliance-checklist)
9. [Incident Response](#9-incident-response)
10. [Findings from Current Codebase](#10-findings-from-current-codebase)

---

## 1. Authentication Security

### 1.1 JWT Implementation

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 1.1.1 | - [ ] Use RS256 (asymmetric) instead of HS256 for JWT signing | Critical | Not Started | Generate RSA-2048+ keypair. Store private key in secrets manager, distribute public key to services for verification. Asymmetric signing prevents any service with the verification key from forging tokens. |
| 1.1.2 | - [ ] Set short access token expiry (15 minutes max) | Critical | Not Started | In `python-jose` or `PyJWT`: `exp = datetime.utcnow() + timedelta(minutes=15)`. Use refresh tokens (longer-lived, stored server-side) for session continuity. |
| 1.1.3 | - [ ] Implement refresh token rotation | Critical | Not Started | Store refresh tokens in the `raf_intelligence` MySQL DB with a `token_family` column. On each refresh, invalidate the old token and issue a new one. If a revoked token is reused, invalidate the entire family (replay detection). |
| 1.1.4 | - [ ] Implement JWT secret/key rotation without downtime | High | Not Started | Support multiple signing keys via a JWKS endpoint. Include `kid` (Key ID) in the JWT header. During rotation, accept tokens signed by both the old and new key for a grace period equal to the longest token lifetime. |
| 1.1.5 | - [ ] Store access tokens in memory only (never localStorage) | Critical | Not Started | In the Next.js frontend, store the access token in a JavaScript variable or React context -- never in localStorage or sessionStorage. Use httpOnly, Secure, SameSite=Strict cookies for refresh tokens. |
| 1.1.6 | - [ ] Validate all JWT claims on every request | Critical | Not Started | In a FastAPI dependency, verify: `exp`, `iat`, `iss`, `aud`, `sub`, `jti`. Reject tokens missing any required claim. Use `python-jose` with `options={"verify_exp": True, "verify_aud": True}`. |
| 1.1.7 | - [ ] Implement a token blocklist/revocation mechanism | High | Not Started | Use Redis (already in stack for Celery) to maintain a set of revoked `jti` values. Check the blocklist in the FastAPI auth dependency before processing any request. TTL entries to match token expiry. |
| 1.1.8 | - [ ] Set explicit `alg` in JWT header and reject `none` algorithm | Critical | Not Started | Hardcode accepted algorithms: `algorithms=["RS256"]` in verification. Never pass user-supplied algorithm values. |

### 1.2 Password Policy (NIST 800-63B for Healthcare)

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 1.2.1 | - [ ] Minimum 12 characters (NIST 800-63B recommends 8 minimum; healthcare orgs should exceed this) | Critical | Not Started | Validate in both the Next.js frontend (UX) and FastAPI backend (enforcement). Backend is the authority. |
| 1.2.2 | - [ ] Maximum 128 characters (do not truncate silently) | Medium | Not Started | Set `max_length=128` on the Pydantic model. Return a clear validation error if exceeded. |
| 1.2.3 | - [ ] Check passwords against breach databases (HIBP k-Anonymity API) | High | Not Started | Use the HaveIBeenPwned Passwords API with k-Anonymity (send only the first 5 chars of the SHA-1 hash). Block any password found in known breaches. |
| 1.2.4 | - [ ] Use bcrypt or Argon2id for password hashing | Critical | Not Started | Use `passlib[bcrypt]` with `CryptContext(schemes=["bcrypt"], deprecated="auto")` or preferably `argon2-cffi` with Argon2id. Never use MD5, SHA-256, or PBKDF2 with low iterations. |
| 1.2.5 | - [ ] Do NOT enforce composition rules (uppercase + special char) | Medium | Not Started | Per NIST 800-63B, composition rules reduce usability without improving security. Check length and breach status instead. |
| 1.2.6 | - [ ] Block context-specific passwords (username, "raf", "hcc", company name) | Medium | Not Started | Maintain a blocklist of application-specific terms. Check password does not contain the user's email prefix, name, or common application terms. |

### 1.3 Multi-Factor Authentication

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 1.3.1 | - [ ] Implement TOTP-based MFA (Google Authenticator, Authy) | Critical | Not Started | Use `pyotp` library. Store the encrypted TOTP secret per user in MySQL. Generate QR codes with `qrcode` library during enrollment. This is a HIPAA addressable requirement that is effectively required for ePHI access. |
| 1.3.2 | - [ ] Provide backup/recovery codes (one-time use, 8 codes minimum) | High | Not Started | Generate 8-10 single-use codes at MFA enrollment. Store as bcrypt hashes. Mark each as used after consumption. |
| 1.3.3 | - [ ] Enforce MFA for all users with PHI access | Critical | Not Started | In the FastAPI auth middleware, check `user.mfa_verified` claim in JWT. Redirect to MFA challenge if the session has not completed MFA. |
| 1.3.4 | - [ ] Support WebAuthn/FIDO2 as a second factor option | Medium | Not Started | Use `py_webauthn` library. This provides phishing-resistant MFA. Prioritize TOTP first, add WebAuthn as an enhancement. |
| 1.3.5 | - [ ] Rate-limit MFA code attempts (5 attempts, then lockout) | High | Not Started | Track failed TOTP attempts in Redis with a 15-minute sliding window. Lock the account for 30 minutes after 5 failures. |

### 1.4 Session Management

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 1.4.1 | - [ ] Automatic session timeout after 15 minutes of inactivity | Critical | Not Started | HIPAA requires automatic logoff. Implement in both frontend (redirect to login) and backend (reject stale refresh tokens). Track `last_activity` timestamp per session. |
| 1.4.2 | - [ ] Absolute session timeout of 8 hours | High | Not Started | Regardless of activity, force re-authentication after 8 hours. Set `max_session_age` in the refresh token logic. |
| 1.4.3 | - [ ] Limit concurrent sessions per user (max 2-3) | High | Not Started | Track active sessions in a MySQL `user_sessions` table. On new login, if the limit is reached, either deny or invalidate the oldest session. |
| 1.4.4 | - [ ] Invalidate all sessions on password change | Critical | Not Started | When a password is changed, delete all refresh tokens and add all active access token `jti` values to the Redis blocklist. |
| 1.4.5 | - [ ] Admin ability to terminate any user session | High | Not Started | Provide an admin API endpoint that revokes all tokens for a given `user_id`. Required for HIPAA workforce termination procedures. |
| 1.4.6 | - [ ] Log all session lifecycle events | High | Not Started | Record login, logout, timeout, forced termination in an audit log table with timestamp, user_id, IP, and user_agent. |

### 1.5 Brute Force Protection

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 1.5.1 | - [ ] Progressive account lockout (5 failures = 15 min lock, 10 = 1 hour) | Critical | Not Started | Track in Redis: key = `login_failures:{username}`, increment on failure, reset on success. Use exponential backoff. |
| 1.5.2 | - [ ] IP-based rate limiting on auth endpoints | Critical | Not Started | Use `slowapi` (FastAPI rate limiting library): `@limiter.limit("5/minute")` on `/auth/login`, `/auth/token/refresh`, `/auth/mfa/verify`. |
| 1.5.3 | - [ ] Return generic error messages ("Invalid credentials") | Critical | Not Started | Never reveal whether the username or password was wrong. Never reveal whether an account exists via login or password reset flows. |
| 1.5.4 | - [ ] CAPTCHA after 3 failed attempts | Medium | Not Started | Integrate hCaptcha or Cloudflare Turnstile. Trigger after 3 consecutive failures for the same username or IP. |
| 1.5.5 | - [ ] Alert on suspicious login patterns | High | Not Started | Trigger alerts for: login from new geography, multiple failed attempts across accounts from same IP, successful login after multiple failures. |

---

## 2. Authorization & Access Control

### 2.1 RBAC Implementation

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 2.1.1 | - [ ] Define role hierarchy: Super Admin, Org Admin, Coder, Auditor, Read-Only | Critical | Not Started | Create MySQL tables: `roles`, `permissions`, `role_permissions`, `user_roles`. Include `organization_id` for multi-tenant isolation. |
| 2.1.2 | - [ ] Implement permission-based access control (not just role checks) | High | Not Started | Check granular permissions (e.g., `phi:read`, `phi:write`, `reports:export`, `users:manage`) in FastAPI dependencies. Roles are groups of permissions. |
| 2.1.3 | - [ ] Enforce multi-tenant data isolation | Critical | Not Started | Every database query that returns PHI must include a `WHERE organization_id = :org_id` clause. Never rely on frontend filtering alone. Use a FastAPI dependency that injects the current user's `org_id` from the JWT. |
| 2.1.4 | - [ ] Implement row-level security for patient data | Critical | Not Started | Restrict coders to patients assigned to them. Use a `coder_patient_assignments` table and enforce in queries. |
| 2.1.5 | - [ ] Deny by default -- explicitly grant access | Critical | Not Started | FastAPI route dependencies should deny access unless the user has a matching permission. Use `Depends(require_permission("phi:read"))` pattern. |

### 2.2 PHI Access Controls (Minimum Necessary Standard)

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 2.2.1 | - [ ] Implement minimum necessary access -- only return PHI fields the role requires | Critical | Not Started | Coders see diagnosis codes and clinical notes. Billing sees financial data. Admins see audit logs. Define field-level access per role. Use Pydantic response models that exclude fields the caller should not see. |
| 2.2.2 | - [ ] Log every PHI access with user, timestamp, patient, and fields accessed | Critical | Not Started | Create an `audit_phi_access` table. Insert a row on every endpoint that returns or modifies PHI. Include: `user_id`, `patient_id`, `action` (view/edit/export), `fields_accessed`, `timestamp`, `ip_address`. |
| 2.2.3 | - [ ] Implement data segmentation for sensitive diagnoses | High | Not Started | Mental health, substance abuse, HIV, and reproductive health records may have additional state-level protections (42 CFR Part 2 for substance abuse). Flag sensitive HCC codes and apply additional access restrictions. |

### 2.3 Emergency Access (Break-the-Glass)

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 2.3.1 | - [ ] Implement break-the-glass access procedure | High | Not Started | Allow authorized users to access records outside their normal scope with: mandatory reason entry, immediate supervisor notification, enhanced audit logging, automatic review trigger. |
| 2.3.2 | - [ ] Require documented justification for emergency access | High | Not Started | Store `emergency_access_log` with `user_id`, `patient_id`, `reason`, `timestamp`. Queue for compliance officer review within 24 hours. |
| 2.3.3 | - [ ] Auto-expire emergency access after a defined period (4 hours) | High | Not Started | Temporary permission grant with automatic revocation. |

---

## 3. Data Protection

### 3.1 Encryption at Rest

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 3.1.1 | - [ ] Enable MySQL Transparent Data Encryption (TDE) for PHI tables | Critical | Not Started | Use InnoDB tablespace encryption: `ALTER TABLE patients ENCRYPTION='Y'`. Requires `keyring_file` or `keyring_okv` plugin. Store the keyring on a separate volume from the data. |
| 3.1.2 | - [ ] **FINDING:** Move encryption keys out of filesystem into a secrets manager | Critical | Not Started | Current code stores keys at `.phi_key` and `.phi_aes256_key` as files on disk (see `phi_encryption.py`). Migrate to HashiCorp Vault, AWS KMS, or GCP Cloud KMS. Keys on disk are vulnerable to container escape, backup exposure, and lack rotation support. |
| 3.1.3 | - [ ] Implement envelope encryption for PHI fields | High | Not Started | Use a Key Encryption Key (KEK) in Vault/KMS to wrap per-record Data Encryption Keys (DEKs). This enables key rotation without re-encrypting all data. |
| 3.1.4 | - [ ] **FINDING:** Add Associated Authenticated Data (AAD) to AES-GCM encryption | High | Not Started | Current `encrypt_note_excerpt` passes `None` as AAD. Pass the `patient_id` and `field_name` as AAD to bind ciphertext to its intended context and prevent ciphertext substitution attacks. |
| 3.1.5 | - [ ] Encrypt full-disk on the Docker host | High | Not Started | Enable LUKS on Ubuntu for the data volume. This provides defense-in-depth if MySQL TDE keys are compromised. |
| 3.1.6 | - [ ] Encrypt MySQL backups | Critical | Not Started | Use `mysqldump` piped through `gpg` or `age` encryption, or use Percona XtraBackup with `--encrypt=AES256`. Store backup encryption keys separately from backup files. |

### 3.2 Encryption in Transit

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 3.2.1 | - [ ] Enforce TLS 1.2+ on all external connections | Critical | Not Started | Configure the reverse proxy (Nginx/Caddy) with `ssl_protocols TLSv1.2 TLSv1.3`. Disable TLS 1.0 and 1.1. |
| 3.2.2 | - [ ] Configure strong cipher suites (disable CBC, prefer AEAD) | High | Not Started | Use: `TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:ECDHE-RSA-AES256-GCM-SHA384`. Test with `testssl.sh`. |
| 3.2.3 | - [ ] Enable HSTS with min 1-year max-age | High | Not Started | `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload` |
| 3.2.4 | - [ ] Enable TLS on MySQL connections | Critical | Not Started | Current `db.py` does not specify `ssl_ca`, `ssl_cert`, `ssl_key` in connection pool config. Add `ssl_ca=/path/to/ca.pem` to `_build_openemr_pool()` and `_build_raf_pool()`. Set `require_secure_transport=ON` in MySQL. |
| 3.2.5 | - [ ] TLS for Redis connections | High | Not Started | Current `redis_url` uses `redis://` (plaintext). Switch to `rediss://` with certificate verification for any deployment where Redis is on a separate host. |
| 3.2.6 | - [ ] TLS for Gemini AI API calls | Critical | Not Started | Verify the Google AI SDK enforces TLS by default. Ensure no proxy or middleware downgrades the connection. Pin the Google API root CA certificate if possible. |

### 3.3 PHI in Non-Production Environments

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 3.3.1 | - [ ] Never use real PHI in development or testing | Critical | Not Started | Use synthetic data generators (e.g., `Faker` with medical profiles or Synthea). Create a `scripts/generate_test_data.py` that produces realistic but fictional patient records. |
| 3.3.2 | - [ ] Implement data masking for any prod-to-dev data copies | Critical | Not Started | If production data must be used for debugging, apply: name randomization, DOB shifting (+/- random days), MRN replacement, address generalization (ZIP to first 3 digits). |
| 3.3.3 | - [ ] **FINDING:** Ensure no PHI appears in application logs | Critical | Not Started | Audit all `logger.*` calls in the codebase. The current `phi_encryption.py` correctly avoids logging plaintext, but verify all routers and services. Use a structured logging library (`structlog`) with a PHI scrubbing processor. |
| 3.3.4 | - [ ] Exclude PHI from error responses | Critical | Not Started | FastAPI exception handlers must strip patient identifiers from 4xx/5xx responses. Never include patient_name, dob, ssn, or mrn in error detail messages. |
| 3.3.5 | - [ ] Exclude PHI from URL parameters | High | Not Started | Never pass patient identifiers as query parameters (they appear in access logs, browser history, and referrer headers). Use POST bodies or path parameters with opaque IDs. |

---

## 4. HIPAA Technical Safeguards (45 CFR 164.312)

### 4.1 Access Control (164.312(a)(1))

| # | Requirement | Priority | Status | Implementation |
|---|-------------|----------|--------|----------------|
| 4.1.1 | - [ ] **Unique User Identification (R):** Assign a unique identifier to each user | Critical | Not Started | Every user gets a UUID `user_id` in the `users` table. No shared accounts. No generic "admin" or "coder" accounts. Log all actions against the individual user_id. |
| 4.1.2 | - [ ] **Emergency Access Procedure (R):** Establish procedures for obtaining ePHI during emergencies | Critical | Not Started | See Section 2.3 (break-the-glass). Document the procedure in the organization's HIPAA policies. |
| 4.1.3 | - [ ] **Automatic Logoff (A):** Implement electronic procedures that terminate sessions after inactivity | Critical | Not Started | See Section 1.4.1. 15-minute inactivity timeout. This is "addressable" under HIPAA but effectively required for a system handling ePHI. |
| 4.1.4 | - [ ] **Encryption and Decryption (A):** Implement mechanism to encrypt/decrypt ePHI | Critical | Not Started | Already partially implemented via `phi_encryption.py` (AES-256-GCM). Extend to cover all PHI fields, not just clinical notes. Move key management to a proper KMS. |

### 4.2 Audit Controls (164.312(b))

| # | Requirement | Priority | Status | Implementation |
|---|-------------|----------|--------|----------------|
| 4.2.1 | - [ ] Implement comprehensive audit logging for all ePHI access | Critical | Not Started | Create `audit_log` table: `id`, `timestamp`, `user_id`, `action`, `resource_type`, `resource_id`, `ip_address`, `user_agent`, `request_id`, `outcome` (success/failure). |
| 4.2.2 | - [ ] Log authentication events (login, logout, failure, lockout) | Critical | Not Started | Separate `auth_audit_log` or tagged entries in the main audit log. |
| 4.2.3 | - [ ] Log administrative actions (user creation, role changes, config changes) | Critical | Not Started | Track who changed what, when, and the before/after values. |
| 4.2.4 | - [ ] Make audit logs tamper-evident (append-only, hash chain or external SIEM) | High | Not Started | Write audit logs to an append-only store. Options: ship to a SIEM (Splunk, Elastic), use a separate write-only database user, or implement hash chaining (each entry includes SHA-256 of the previous entry). |
| 4.2.5 | - [ ] Retain audit logs for minimum 6 years (HIPAA retention) | Critical | Not Started | Configure log rotation to archive, not delete. Use lifecycle policies on object storage (S3/GCS) with legal hold. |
| 4.2.6 | - [ ] Regular audit log review process (weekly minimum) | High | Not Started | Automate anomaly detection (unusual access patterns, after-hours access, bulk data exports). Generate weekly summary reports for the compliance officer. |

### 4.3 Integrity Controls (164.312(c)(1))

| # | Requirement | Priority | Status | Implementation |
|---|-------------|----------|--------|----------------|
| 4.3.1 | - [ ] **Mechanism to Authenticate ePHI (A):** Verify ePHI has not been altered or destroyed improperly | Critical | Not Started | AES-GCM authentication tags already provide integrity verification for encrypted fields. Add checksums (HMAC-SHA256) for non-encrypted PHI records. Track data modification history with a `record_versions` table. |
| 4.3.2 | - [ ] Database integrity checks | High | Not Started | Run `CHECK TABLE` regularly. Enable MySQL binary logging for point-in-time recovery. Implement application-level optimistic locking (`version` column) on PHI records. |

### 4.4 Transmission Security (164.312(e)(1))

| # | Requirement | Priority | Status | Implementation |
|---|-------------|----------|--------|----------------|
| 4.4.1 | - [ ] **Integrity Controls (A):** Protect ePHI from improper modification during transmission | Critical | Not Started | TLS provides this. Additionally, for API responses containing PHI, include a response body hash in a custom header for client-side verification. |
| 4.4.2 | - [ ] **Encryption (A):** Encrypt ePHI whenever transmitted over networks | Critical | Not Started | See Section 3.2. Enforce TLS everywhere: client-to-server, server-to-database, server-to-Gemini API, server-to-Redis. |

### 4.5 Person or Entity Authentication (164.312(d))

| # | Requirement | Priority | Status | Implementation |
|---|-------------|----------|--------|----------------|
| 4.5.1 | - [ ] Verify identity of persons seeking access to ePHI | Critical | Not Started | Multi-factor authentication (Section 1.3). Identity verification during account provisioning (admin-approved, email-verified). |
| 4.5.2 | - [ ] API authentication for all system-to-system communication | Critical | Not Started | Use API keys or mutual TLS for the Gemini AI integration and any EHR/OpenEMR API calls. Never send PHI to external APIs without authenticated channels. |

---

## 5. Application Security (OWASP Top 10)

### 5.1 Injection Prevention (A03:2021)

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 5.1.1 | - [ ] **FINDING:** Verify all MySQL queries use parameterized queries | Critical | Not Started | Audit every `cursor.execute()` call in the codebase. The current `db.py` provides cursors but does not enforce parameterization. Search for string formatting in SQL: `f"SELECT`, `"SELECT" +`, `% (`. Every instance is a potential SQL injection. |
| 5.1.2 | - [ ] Use an ORM (SQLAlchemy) for complex queries | High | Not Started | Consider migrating from raw `mysql-connector-python` to SQLAlchemy with the MySQL dialect. ORM queries are parameterized by default. |
| 5.1.3 | - [ ] Validate and sanitize all Gemini AI prompt inputs | Critical | Not Started | Patient data sent to Gemini for HCC code suggestions must be sanitized to prevent prompt injection. Validate that user-supplied text does not contain instruction-like patterns. Implement output validation on AI responses. |
| 5.1.4 | - [ ] Implement input validation on all API endpoints using Pydantic models | High | Not Started | Every FastAPI route should use typed Pydantic request models with strict validation: `constr(max_length=...)`, `conint(ge=0)`, regex patterns for ICD-10 codes. |

### 5.2 Broken Access Control (A01:2021)

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 5.2.1 | - [ ] Enforce authorization checks on every endpoint | Critical | Not Started | Use FastAPI `Depends()` with permission-checking functions. Never rely on frontend-only access control. |
| 5.2.2 | - [ ] Prevent IDOR (Insecure Direct Object Reference) | Critical | Not Started | When a user requests `/patients/{patient_id}`, verify the user's organization owns that patient record. Use UUIDs instead of sequential integers for externally-exposed IDs. |
| 5.2.3 | - [ ] Disable directory listing and unnecessary HTTP methods | Medium | Not Started | In Nginx/reverse proxy: `autoindex off;`. Only allow GET, POST, PUT, PATCH, DELETE, OPTIONS as needed per endpoint. |
| 5.2.4 | - [ ] Implement CORS properly | High | Not Started | In FastAPI `CORSMiddleware`, set `allow_origins` to the exact frontend domain (e.g., `https://raf.comercioit.com`). Never use `allow_origins=["*"]` in production. |

### 5.3 Cryptographic Failures (A02:2021)

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 5.3.1 | - [ ] **FINDING:** Classify all data fields as PHI/PII/Public | Critical | Not Started | Create a data classification matrix. PHI fields: patient name, DOB, MRN, SSN, diagnosis codes linked to patient identity, clinical notes. Ensure every PHI field is encrypted at rest. |
| 5.3.2 | - [ ] **FINDING:** Default DB credentials in config.py | Critical | Not Started | `config.py` defaults to `user="root"`, `password="root"` for both databases. While these are fallback defaults overridden by `.env`, they should be removed entirely. The application should fail to start if DB credentials are not provided via environment variables. |
| 5.3.3 | - [ ] Never hardcode secrets in source code | Critical | Not Started | Scan the repository with `trufflehog` or `gitleaks` to detect any committed secrets. Add these tools to the CI pipeline. |

### 5.4 XSS Prevention (A03:2021 -- Injection)

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 5.4.1 | - [ ] Set Content Security Policy headers | High | Not Started | Configure a strict CSP: `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' https://raf-api.comercioit.com` |
| 5.4.2 | - [ ] Ensure React's built-in XSS protection is not bypassed | Critical | Not Started | Audit the Next.js frontend for any use of unsafe HTML rendering patterns. If rendering AI-generated content (HCC code suggestions), sanitize with DOMPurify first. |
| 5.4.3 | - [ ] Set security headers on all responses | High | Not Started | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: camera=(), microphone=(), geolocation=()`. Add via FastAPI middleware or reverse proxy. |

### 5.5 CSRF Protection

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 5.5.1 | - [ ] Implement CSRF tokens for cookie-based auth flows | High | Not Started | If using httpOnly cookies for refresh tokens, implement double-submit cookie pattern or synchronizer token pattern. Use `fastapi-csrf-protect` library. |
| 5.5.2 | - [ ] Set SameSite=Strict on all cookies | High | Not Started | In the Set-Cookie header: `SameSite=Strict; Secure; HttpOnly; Path=/api/auth`. |

### 5.6 API Security

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 5.6.1 | - [ ] Implement rate limiting on all API endpoints | High | Not Started | Use `slowapi`: general endpoints at 100 req/min, auth endpoints at 5 req/min, PHI export endpoints at 10 req/hour. Return `429 Too Many Requests` with `Retry-After` header. |
| 5.6.2 | - [ ] Limit request body size | Medium | Not Started | Set `max_request_size` in Uvicorn/Nginx. 10MB for file uploads, 1MB for API requests. |
| 5.6.3 | - [ ] Implement request/response logging (without PHI) | High | Not Started | Log: method, path, status code, response time, user_id, request_id. Never log request/response bodies that may contain PHI. Use middleware with a PHI field exclusion list. |
| 5.6.4 | - [ ] Validate Content-Type headers | Medium | Not Started | Reject requests with unexpected Content-Type. API endpoints should only accept `application/json`. |
| 5.6.5 | - [ ] Implement API versioning | Medium | Not Started | Use URL path versioning: `/api/v1/...`. This enables safe deprecation of endpoints with security issues. |

### 5.7 Error Handling

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 5.7.1 | - [ ] Implement global exception handler that strips sensitive data | Critical | Not Started | FastAPI `@app.exception_handler(Exception)` that returns generic error messages to clients. Log full stack traces server-side only. Never include PHI, SQL queries, or internal paths in responses. |
| 5.7.2 | - [ ] Disable debug mode and stack traces in production | Critical | Not Started | Ensure `debug=False` in FastAPI/Uvicorn production config. Do not use `--reload` in production. |
| 5.7.3 | - [ ] Return consistent error response format | Medium | Not Started | Use a standard schema: `{"error": {"code": "AUTH_FAILED", "message": "...", "request_id": "..."}}`. Include `request_id` for support correlation without exposing internals. |

---

## 6. Infrastructure Security

### 6.1 Docker Container Hardening

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 6.1.1 | - [ ] Run containers as non-root user | Critical | Not Started | In each Dockerfile: `RUN adduser --disabled-password --no-create-home appuser` then `USER appuser`. Verify with `docker exec raf-backend whoami`. |
| 6.1.2 | - [ ] Use minimal base images (python:3.11-slim, node:20-alpine) | High | Not Started | Smaller images = smaller attack surface. Rebuild images from slim/alpine bases. |
| 6.1.3 | - [ ] Set filesystem to read-only where possible | High | Not Started | In `docker-compose.yml`: `read_only: true` with explicit `tmpfs` mounts for `/tmp`. Current config mounts `./models:/app/models:ro` which is good. |
| 6.1.4 | - [ ] Drop all Linux capabilities and add only needed ones | High | Not Started | `cap_drop: [ALL]` in docker-compose. Add back only what is needed (usually none for web apps). |
| 6.1.5 | - [ ] Scan Docker images for vulnerabilities | High | Not Started | Use `trivy image raf-backend:latest` in CI. Block deployment on Critical/High CVEs. |
| 6.1.6 | - [ ] Set resource limits (CPU, memory) | Medium | Not Started | In docker-compose: `deploy: resources: limits: memory: 2G, cpus: '1.0'`. Prevents resource exhaustion attacks. |
| 6.1.7 | - [ ] Do not expose unnecessary ports | Critical | Not Started | Current config exposes port 8500 (backend) and 3000 (frontend). In production, only the reverse proxy port (443) should be exposed to the internet. Backend and frontend should be on an internal Docker network only. |
| 6.1.8 | - [ ] Use Docker secrets instead of env_file for sensitive values | High | Not Started | Current config uses `env_file: .env` which passes all secrets as environment variables visible via `docker inspect`. Migrate to Docker secrets or a runtime secrets manager. |
| 6.1.9 | - [ ] **FINDING:** Pin image versions in Dockerfiles | High | Not Started | Use `python:3.11.9-slim-bookworm` not `python:3.11-slim`. Pin all base images to specific digests for reproducibility and supply chain security. |

### 6.2 Network Security

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 6.2.1 | - [ ] Implement network segmentation (DMZ, application tier, database tier) | Critical | Not Started | Create separate Docker networks: `frontend-net` (frontend + reverse proxy), `backend-net` (backend + Redis), `data-net` (backend + MySQL). Frontend should not have direct database access. |
| 6.2.2 | - [ ] Configure host firewall (ufw/iptables) | Critical | Not Started | Allow inbound: 443 (HTTPS), 22 (SSH from jump host only). Deny all other inbound. The jump host at 15.204.73.232 should be the only allowed SSH source. |
| 6.2.3 | - [ ] **FINDING:** Restrict database to localhost/container network only | Critical | Not Started | MySQL ports (3306/3309) must not be accessible from the internet. Verify with `ss -tlnp` on the host. Bind MySQL to `127.0.0.1` or the Docker internal network only. |
| 6.2.4 | - [ ] Place a WAF in front of the application | High | Not Started | Use Cloudflare WAF, AWS WAF, or ModSecurity with Nginx. Enable OWASP Core Rule Set. Protects against SQL injection, XSS, and common attack patterns at the network edge. |
| 6.2.5 | - [ ] Implement DDoS protection | High | Not Started | Use Cloudflare or cloud-provider DDoS protection. Configure rate limiting at the edge. |

### 6.3 SSH Hardening

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 6.3.1 | - [ ] Disable password authentication (key-only) | Critical | Not Started | In `/etc/ssh/sshd_config`: `PasswordAuthentication no`, `PubkeyAuthentication yes`. |
| 6.3.2 | - [ ] Disable root SSH login | Critical | Not Started | `PermitRootLogin no` in sshd_config. |
| 6.3.3 | - [ ] Restrict SSH to jump host IP only | Critical | Not Started | Firewall rule: allow SSH (22) only from 15.204.73.232. |
| 6.3.4 | - [ ] Use SSH key passphrase and ed25519 keys | High | Not Started | `ssh-keygen -t ed25519`. Enforce passphrase-protected keys. |
| 6.3.5 | - [ ] Enable SSH audit logging | High | Not Started | Ensure `LogLevel VERBOSE` in sshd_config. Forward SSH logs to SIEM. |

### 6.4 Secrets Management

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 6.4.1 | - [ ] **FINDING:** Migrate from .env file to a secrets manager | Critical | Not Started | Current architecture uses `.env` file with database passwords, API keys. Migrate to HashiCorp Vault (self-hosted) or cloud KMS. At minimum, use Docker secrets for the Docker Compose deployment. |
| 6.4.2 | - [ ] Implement secret rotation policy | High | Not Started | Database passwords: rotate every 90 days. API keys: rotate every 180 days. Encryption keys: rotate annually with re-encryption migration. JWT signing keys: rotate every 90 days. |
| 6.4.3 | - [ ] Ensure .env is in .gitignore | Critical | Not Started | Verify `.env`, `.phi_key`, `.phi_aes256_key`, and any key files are in `.gitignore`. Run `git log --all --full-history -- .env` to check if secrets were ever committed. |
| 6.4.4 | - [ ] Scan git history for leaked secrets | Critical | Not Started | Run `gitleaks detect --source=. --log-opts="--all"` or `trufflehog git file://.`. Remediate any findings by rotating the exposed credentials immediately. |

---

## 7. AI/ML Security (Gemini Integration)

| # | Item | Priority | Status | Guidance |
|---|------|----------|--------|----------|
| 7.1 | - [ ] Minimize PHI sent to Gemini API | Critical | Not Started | Send de-identified clinical text when possible. Strip patient names, DOBs, MRNs before sending to Gemini. Only send the minimum clinical context needed for HCC code prediction. |
| 7.2 | - [ ] Verify Google's BAA covers Gemini API usage for PHI | Critical | Not Started | Google Cloud has a BAA for certain services. Verify Gemini API (not just Vertex AI) is covered. If not covered under BAA, PHI must not be sent to Gemini. Use de-identified data only. |
| 7.3 | - [ ] Implement prompt injection defenses | High | Not Started | Validate and sanitize all user-supplied text before including in Gemini prompts. Use system prompts to constrain model behavior. Validate AI output against expected formats (valid ICD-10 codes, valid HCC categories). |
| 7.4 | - [ ] Log all AI API interactions (without PHI) | High | Not Started | Log: timestamp, user_id, prompt_type (not content), response_type, model_version, token_count. Never log the prompt or response content if it may contain PHI. |
| 7.5 | - [ ] Implement AI output validation | High | Not Started | Validate that Gemini-suggested HCC codes are valid ICD-10-CM codes. Check against CMS-published code sets. Flag anomalous outputs for human review. |
| 7.6 | - [ ] Rate-limit AI API calls per user | Medium | Not Started | Prevent abuse and control costs. Limit to N Gemini calls per user per hour. |
| 7.7 | - [ ] Implement human-in-the-loop for AI-generated coding suggestions | High | Not Started | AI suggestions must be reviewed and confirmed by a certified coder before submission. Never auto-submit AI-generated HCC codes to CMS. This is both a security and compliance requirement. |

---

## 8. Compliance Checklist

### 8.1 HIPAA Security Rule (45 CFR Part 164, Subpart C)

| # | Requirement | Section | Priority | Status |
|---|-------------|---------|----------|--------|
| 8.1.1 | - [ ] Conduct a formal Risk Analysis | 164.308(a)(1)(ii)(A) | Critical | Not Started |
| 8.1.2 | - [ ] Implement Risk Management program | 164.308(a)(1)(ii)(B) | Critical | Not Started |
| 8.1.3 | - [ ] Assign a Security Officer | 164.308(a)(2) | Critical | Not Started |
| 8.1.4 | - [ ] Implement workforce access management procedures | 164.308(a)(3) | Critical | Not Started |
| 8.1.5 | - [ ] Implement security awareness training program | 164.308(a)(5) | Critical | Not Started |
| 8.1.6 | - [ ] Implement security incident procedures | 164.308(a)(6) | Critical | Not Started |
| 8.1.7 | - [ ] Establish contingency plan (backup, disaster recovery, emergency mode) | 164.308(a)(7) | Critical | Not Started |
| 8.1.8 | - [ ] Perform periodic evaluations of security policies | 164.308(a)(8) | High | Not Started |
| 8.1.9 | - [ ] Implement BAA management for all subcontractors | 164.308(b)(1) | Critical | Not Started |
| 8.1.10 | - [ ] Facility access controls | 164.310(a)(1) | High | Not Started |
| 8.1.11 | - [ ] Workstation use and security policies | 164.310(b)/(c) | High | Not Started |
| 8.1.12 | - [ ] Device and media controls (disposal, re-use) | 164.310(d)(1) | High | Not Started |
| 8.1.13 | - [ ] All Technical Safeguards (Section 4 above) | 164.312 | Critical | Not Started |

### 8.2 HIPAA Privacy Rule (Relevant Technical Items)

| # | Requirement | Priority | Status |
|---|-------------|----------|--------|
| 8.2.1 | - [ ] Implement minimum necessary access in the application | Critical | Not Started |
| 8.2.2 | - [ ] Support individual right of access (patient data export) | High | Not Started |
| 8.2.3 | - [ ] Implement PHI disclosure tracking (accounting of disclosures) | High | Not Started |
| 8.2.4 | - [ ] Support data amendment requests | Medium | Not Started |

### 8.3 Business Associate Agreement (BAA) Requirements

| # | Item | Priority | Status |
|---|------|----------|--------|
| 8.3.1 | - [ ] Execute BAA with all cloud/infrastructure providers | Critical | Not Started |
| 8.3.2 | - [ ] Execute BAA with Google (for Gemini AI if processing PHI) | Critical | Not Started |
| 8.3.3 | - [ ] Execute BAA with any third-party SaaS tools accessing PHI | Critical | Not Started |
| 8.3.4 | - [ ] Maintain BAA register with renewal dates | High | Not Started |
| 8.3.5 | - [ ] Include breach notification obligations in all BAAs | Critical | Not Started |
| 8.3.6 | - [ ] BAA between RAF Intelligence and each customer (health plan/provider group) | Critical | Not Started |

### 8.4 SOC 2 Type II Readiness

| # | Item | Priority | Status |
|---|------|----------|--------|
| 8.4.1 | - [ ] Document all security policies and procedures | High | Not Started |
| 8.4.2 | - [ ] Implement change management process | High | Not Started |
| 8.4.3 | - [ ] Implement vulnerability management program | High | Not Started |
| 8.4.4 | - [ ] Implement vendor management program | High | Not Started |
| 8.4.5 | - [ ] Implement monitoring and alerting | High | Not Started |
| 8.4.6 | - [ ] Conduct annual penetration testing | High | Not Started |
| 8.4.7 | - [ ] Background checks for workforce with PHI access | High | Not Started |
| 8.4.8 | - [ ] Implement data retention and disposal policies | High | Not Started |

### 8.5 HITRUST CSF Alignment

| # | Item | Priority | Status |
|---|------|----------|--------|
| 8.5.1 | - [ ] Map controls to HITRUST CSF categories | Medium | Not Started |
| 8.5.2 | - [ ] Implement HITRUST r2 assessment readiness | Medium | Not Started |
| 8.5.3 | - [ ] Establish control maturity documentation | Medium | Not Started |

---

## 9. Incident Response

### 9.1 Breach Notification (HIPAA Breach Notification Rule, 45 CFR Part 164, Subpart D)

| # | Item | Priority | Status |
|---|------|----------|--------|
| 9.1.1 | - [ ] Individual notification within 60 days of breach discovery | Critical | Not Started |
| 9.1.2 | - [ ] HHS notification within 60 days (if 500+ individuals affected, notify without unreasonable delay) | Critical | Not Started |
| 9.1.3 | - [ ] Media notification for breaches affecting 500+ individuals in a state | Critical | Not Started |
| 9.1.4 | - [ ] Business associate notification to covered entity without unreasonable delay | Critical | Not Started |
| 9.1.5 | - [ ] Annual HHS notification for breaches affecting fewer than 500 individuals | High | Not Started |

### 9.2 Breach Assessment (4-Factor Test per 45 CFR 164.402)

Document and assess every potential breach using these four factors:

1. **Nature and extent of PHI involved** -- What identifiers? How sensitive?
2. **Unauthorized person who used/accessed the PHI** -- Who? Internal or external?
3. **Whether PHI was actually acquired or viewed** -- Was it accessed or just exposed?
4. **Extent of risk mitigation** -- What was done to reduce harm?

If the assessment does not demonstrate a low probability that PHI was compromised, it must be treated as a breach.

### 9.3 Incident Response Plan Template

| Phase | Actions | Owner |
|-------|---------|-------|
| **1. Preparation** | Maintain IR plan, train team, test plan annually, maintain contact list | Security Officer |
| **2. Detection** | Monitor alerts, triage events, classify severity (Critical/High/Medium/Low) | On-call engineer |
| **3. Containment** | Isolate affected systems, preserve evidence, activate IR team | IR Team Lead |
| **4. Eradication** | Remove threat, patch vulnerabilities, reset compromised credentials | Engineering |
| **5. Recovery** | Restore systems from known-good backups, verify integrity, monitor closely | Engineering |
| **6. Post-Incident** | Root cause analysis, update controls, update IR plan, breach notification if applicable | Security Officer |

### 9.4 Contact List Template

| Role | Name | Phone | Email | Escalation Tier |
|------|------|-------|-------|-----------------|
| Security Officer | _______ | _______ | _______ | Tier 1 |
| Privacy Officer | _______ | _______ | _______ | Tier 1 |
| CTO / Engineering Lead | _______ | _______ | _______ | Tier 1 |
| Legal Counsel (HIPAA) | _______ | _______ | _______ | Tier 2 |
| Cyber Insurance Carrier | _______ | _______ | _______ | Tier 2 |
| HHS OCR Breach Portal | N/A | N/A | https://ocrportal.hhs.gov/ocr/breach/wizard_breach.jsf | As required |
| FBI Cyber Division (IC3) | N/A | N/A | https://www.ic3.gov | Major incidents |
| Forensics Vendor | _______ | _______ | _______ | Tier 3 |

---

## 10. Findings from Current Codebase

The following issues were identified during review of the existing code. These should be prioritized for immediate remediation.

### Critical Findings

| # | Finding | File | Risk | Remediation |
|---|---------|------|------|-------------|
| F1 | Encryption keys stored as files on disk (`.phi_key`, `.phi_aes256_key`) | `backend/app/services/_legacy/phi_encryption.py` | Key compromise via container escape, backup exposure, or unauthorized filesystem access | Migrate to HashiCorp Vault or cloud KMS. At minimum, restrict file permissions to `0400` and ensure keys are excluded from Docker image builds and backups. |
| F2 | Default database credentials in source code (`root`/`root`) | `backend/app/config.py` | If `.env` is missing, application connects with root/root defaults | Remove default values. Raise an error if environment variables are not set: `os.environ["RAF_DB_PASSWORD"]` (no default). |
| F3 | No TLS configured for MySQL connections | `backend/app/db.py` | Database traffic between application and MySQL is unencrypted. PHI transmitted in plaintext on the network. | Add `ssl_ca`, `ssl_cert`, `ssl_key` parameters to connection pool configuration. Set `require_secure_transport=ON` in MySQL server config. |
| F4 | No TLS configured for Redis connection | `backend/app/config.py` | Redis URL uses `redis://` (plaintext). Celery task data and any cached PHI transmitted unencrypted. | Change to `rediss://` with certificate verification. |
| F5 | AES-GCM encryption uses no Associated Authenticated Data (AAD) | `backend/app/services/_legacy/phi_encryption.py` | Encrypted values can be swapped between records/fields without detection (ciphertext substitution) | Pass `patient_id` and `field_name` as AAD parameter in `_aesgcm.encrypt()` and `_aesgcm.decrypt()` calls. |
| F6 | Docker containers may run as root | `docker-compose.yml` | No `user:` directive or Dockerfile `USER` instruction observed | Add non-root user to Dockerfiles and specify `user:` in docker-compose.yml. |
| F7 | Backend port 8500 exposed to host network | `docker-compose.yml` | API may be directly accessible bypassing any reverse proxy or WAF | Bind to internal Docker network only. Expose only the reverse proxy (443) to the host. |
| F8 | Secrets passed via env_file visible in `docker inspect` | `docker-compose.yml` | Any user with Docker access can read all secrets | Use Docker secrets or mount secrets as files with restricted permissions. |

### High Findings

| # | Finding | File | Risk | Remediation |
|---|---------|------|------|-------------|
| F9 | No authentication middleware observed on API routes | `backend/app/routers/suspects.py` | API endpoints may be accessible without authentication | Implement FastAPI dependency injection for JWT validation on all routes. |
| F10 | No rate limiting on API endpoints | Backend | Vulnerable to brute force, denial of service, and API abuse | Add `slowapi` middleware with per-endpoint rate limits. |
| F11 | No audit logging for PHI access | Backend | Cannot demonstrate compliance with HIPAA audit controls (164.312(b)) | Implement comprehensive audit logging middleware. |
| F12 | No CORS configuration observed | Backend | Cross-origin requests may be unrestricted | Add `CORSMiddleware` with explicit origin whitelist. |

---

## Implementation Priority Order

For a healthcare SaaS application handling PHI, address items in this order:

**Phase 1 -- Immediate (Weeks 1-2): Stop the Bleeding**
1. Remove default database credentials from source code (F2)
2. Add authentication to all API endpoints (F9)
3. Implement TLS for MySQL and Redis connections (F3, F4)
4. Run containers as non-root (F6)
5. Restrict Docker port exposure (F7)
6. Move encryption keys to a secrets manager (F1)

**Phase 2 -- Short Term (Weeks 3-6): Core Security**
1. Implement JWT authentication with RS256 (Section 1.1)
2. Implement RBAC with multi-tenant isolation (Section 2.1)
3. Implement comprehensive audit logging (Section 4.2)
4. Add rate limiting and CORS (F10, F12)
5. Implement MFA (Section 1.3)
6. Session management with auto-logoff (Section 1.4)

**Phase 3 -- Medium Term (Weeks 7-12): Hardening**
1. Implement input validation on all endpoints (Section 5.1)
2. Add security headers (Section 5.4)
3. Network segmentation (Section 6.2)
4. Docker container hardening (Section 6.1)
5. AI/Gemini security controls (Section 7)
6. Migrate from .env to secrets manager (F8)

**Phase 4 -- Ongoing: Compliance and Maturity**
1. Formal HIPAA Risk Analysis (Section 8.1.1)
2. SOC 2 Type II preparation (Section 8.4)
3. Incident response plan finalization (Section 9)
4. Penetration testing
5. Security awareness training
6. BAA execution with all parties (Section 8.3)

---

## Review and Sign-Off

| Reviewer | Role | Date | Signature |
|----------|------|------|-----------|
| ________ | Security Officer | ________ | ________ |
| ________ | CTO / Engineering Lead | ________ | ________ |
| ________ | Privacy Officer | ________ | ________ |
| ________ | Compliance Officer | ________ | ________ |

---

*This document should be treated as Confidential. Review quarterly and after any significant system changes, security incidents, or regulatory updates.*
