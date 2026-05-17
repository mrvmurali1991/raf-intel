# Sub-Processors List

This list documents third-party service providers that may process PHI on behalf of customers using RAF Intelligence. Used as Exhibit A in our Business Associate Agreement (BAA).

**Last updated:** 2026-05-18
**Update policy:** customers are notified 30 days before any new sub-processor is added.

---

## Required sub-processors (always in use)

| Provider | Country | Purpose | BAA in effect | Certifications |
|---|---|---|---|---|
| **Amazon Web Services** | USA / customer-chosen region | Infrastructure: compute, RDS, S3, KMS, Secrets Manager | Yes (AWS BAA) | SOC 1/2/3, HIPAA, ISO 27001, FedRAMP High |
| **MySQL (Oracle)** | n/a — runs in our infrastructure | Database engine (no data leaves customer infra) | n/a | n/a |
| **Sentry** *(optional)* | USA | Error monitoring (PHI scrubbed before send via `request_logging.py` middleware) | Yes | SOC 2 Type II, ISO 27001 |
| **Let's Encrypt / AWS Certificate Manager** | USA | TLS certificates | n/a — no PHI exposure | |

## Optional sub-processors (enabled per customer config)

| Provider | Country | Purpose | When enabled | BAA in effect | Certifications |
|---|---|---|---|---|---|
| **Google (Gemini API)** | USA | LLM for HCC suspect extraction | When `GEMINI_API_KEY` set | Yes (Google Cloud BAA) | SOC 1/2/3, HIPAA, ISO 27001/17/18, FedRAMP High |
| **Twilio** | USA | SMS + voice patient outreach | When `TWILIO_ACCOUNT_SID` set | Yes (Twilio BAA, available on Enterprise plan) | SOC 2 Type II, HIPAA, HITRUST |
| **SendGrid (Twilio)** | USA | Transactional email outreach | When `SENDGRID_API_KEY` set | Yes (Twilio BAA) | SOC 2 Type II, ISO 27001, HIPAA |
| **OVHcloud** | Canada / France | Compute / DR site for multi-tenant SaaS only | Multi-tenant SaaS | Yes | SOC 2 Type II, HDS (French HIPAA equiv.), ISO 27001 |

## Sub-processors used for development only (NO PHI access)

| Provider | Purpose |
|---|---|
| GitHub (Microsoft) | Source code repository |
| Anthropic (Claude Code) | AI-assisted code development on synthetic data only |
| Slack | Internal team communications |
| Linear / Jira | Engineering ticketing |
| 1Password | Internal secrets vault |

---

## Data residency

- **Single-tenant deployments**: data resides in customer-chosen AWS region. RAF only accesses through audit-logged break-glass.
- **Multi-tenant SaaS**: data resides in OVHcloud Beauharnois, Quebec (Canada). DR site in AWS us-west-2.
- **Sub-processor data location**: see each provider's BAA / DPA for their data flow.

---

## How to verify BAA status

For any sub-processor listed above:
- Email security@raf.health to request the executed BAA copy.
- All BAAs are reviewed by counsel before signing.
- We do not enable a HIPAA-touching sub-processor without a valid BAA.

---

## How we minimize PHI exposure to sub-processors

1. **Gemini**: full clinical-note text is sent. We do not yet redact PHI from notes (the diagnoses themselves are PHI). Note text is sent over TLS 1.2+, with Google's standard data-handling per BAA. Retention: 0 days (Google does not retain inputs/outputs for API customers under BAA).
2. **Twilio SMS**: PHI scrubbed at template level — diagnoses are NEVER in SMS body. See `backend/app/services/outreach/templates.py:14` BANNED_IN_SMS_VOICE.
3. **SendGrid email**: same template-level scrubbing.
4. **Sentry**: PHI scrubber `_scrub_phi()` in `backend/app/middleware/request_logging.py:17-40` redacts `ssn/dob/fname/lname/address/phone/email/mbi/medicare_id` before sending. PHI-bearing log records are written only to the local hash-chained audit log (which is **not** shipped to Sentry).
5. **AWS**: PHI at rest is encrypted with customer KMS keys; AWS personnel cannot decrypt.

---

## Sub-processor change notification

Email security@raf.health to subscribe to sub-processor changes. We will email at least 30 days before adding a new sub-processor to this list. Customers may object in writing within 30 days; if a material objection cannot be resolved, the customer may terminate without penalty per the MSA.
