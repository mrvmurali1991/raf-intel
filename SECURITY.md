# Security Policy

## Reporting a vulnerability

If you discover a security issue in RAF Intelligence, please **do not** open a public GitHub issue. Email **security@raf.health** with:

1. A description of the vulnerability
2. Steps to reproduce
3. Affected component(s) / endpoint(s)
4. Suggested mitigation (if known)
5. Your contact details for follow-up

We acknowledge every report within **24 hours**. Confirmed HIGH-severity vulnerabilities are patched within **30 days** with a coordinated disclosure window.

## In-scope

- `backend/` — FastAPI application
- `frontend/` — Next.js application
- Container images (`raf-backend`, `raf-frontend`)
- Production endpoints under `raf.health` and `*.raf.health`

## Out-of-scope

- Self-hosted single-tenant deployments — file with the deploying customer
- Third-party services (Twilio, SendGrid, Gemini, AWS) — file with the vendor
- Demo/staging environments unless the bug demonstrates a class of risk in production
- Social engineering / physical attacks
- DoS / DDoS at the infrastructure layer

## Safe harbor

We will not pursue legal action against good-faith security researchers who:
- Make a good-faith effort to avoid privacy violations, destruction of data, and degradation of service
- Only test against accounts they own (or with explicit permission from the account owner)
- Do not exfiltrate beyond the minimum necessary to demonstrate the vulnerability
- Notify us promptly and give us reasonable time to remediate before public disclosure

## Hall of fame

After remediation, with researcher consent, we publish a recognition list at `docs/enterprise/security-acknowledgments.md`.
