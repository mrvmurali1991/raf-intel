# RAF Intelligence User Guide

Welcome. This guide is a role-based learning path through the RAF Intelligence platform.
Pick the lane that matches your job. Each tutorial is 5–15 minutes of hands-on time and
links to the next one when you finish.

Before you start, confirm you can reach the demo environment and log in:

- URL: `http://localhost:3000` (local) or your tenant URL
- Demo admin: `admin@raf.health` / `Admin@123`
- Backend health: `curl http://localhost:8500/health`

The seeded demo database contains four reference patients you will see throughout these
tutorials: **patient IDs 3, 7, 8, and 22**. Patient 3 has the richest suspect history
and is used in most coder examples.

---

## For a Coder (5 tutorials, ~35 min)

You triage AI-surfaced HCC suspects, attach MEAT evidence, and accept or decline them
into the prospective queue.

1. [Coder getting started — login and sidebar tour](01-coder-getting-started.md)
2. [Accept your first HCC suspect](02-coder-first-suspect.md)
3. [Review MEAT evidence and force-accept](03-coder-review-meat.md)
4. [Reverse an accepted suspect (writeback)](04-coder-reverse-writeback.md)
5. [Keyboard shortcuts: A / D / R + g-prefix nav](05-coder-keyboard-shortcuts.md)

## For a Physician / MD (3 tutorials, ~25 min)

You run pre-visit huddles, MEAT-sign attestations, and review patient charts inline.

6. [Run your morning huddle on `/md/today`](06-md-huddle.md)
7. [Sign a MEAT attestation (`meat_signed=true`)](07-md-signed-attestation.md)
8. [Read a patient chart — every chip explained](08-md-patient-review.md)

## For a Manager / Admin (5 tutorials, ~50 min)

You provision users, run RADV audits, supply SOC 2 evidence, send outreach, and watch
document ingestion.

9. [Provision a user with MFA and a role](09-admin-user-provisioning.md)
10. [Run a RADV audit from sample to export](10-admin-radv-audit.md)
11. [Review SOC 2 daily evidence](11-admin-soc2-evidence.md)
12. [Send a TCPA-compliant outreach campaign](12-admin-outreach.md)
13. [Configure document ingestion (all 9 sources)](13-admin-document-ingestion.md)

## For a Developer / Integrator (3 tutorials, ~20 min)

You consume our REST API, post webhooks, and embed RAF Intelligence in another product.

14. [Authenticate with JWT (login → refresh → scopes)](14-dev-api-auth.md)
15. [Use the `/api/suspects` API end-to-end](15-dev-suspect-api.md)
16. [Receive webhooks (FHIR / Twilio / SendGrid)](16-dev-webhooks.md)

---

## Building this guide locally

If you have MkDocs Material installed, you can render this directory as a static site:

```bash
make user-guide
```

The target copies `docs/user-guide/*.md` into `docs-site/` and, if `mkdocs` is on your
`PATH`, runs `mkdocs build`. Otherwise it just copies the markdown so you can browse it
directly from a static server or your IDE.

## Conventions used in these tutorials

- `cURL` examples assume `BASE=http://localhost:8500`.
- Frontend paths begin with `/` and refer to the Next.js app served on port 3000.
- Code blocks marked `Expected output` show what you should see after a step.
- Each tutorial ends with **Next step** linking the following file.

Found a mistake? Open a PR on `docs/user-guide-tutorials` or message the platform team.
