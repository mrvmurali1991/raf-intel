# Provision a user with MFA and a role

> Audience: Manager / Admin  •  Time: 10 min

This tutorial creates a new user, enforces MFA, assigns the right role, and verifies
the user can log in and see only what their role allows.

## Prerequisites

- An admin account. Demo: `admin@raf.health` / `Admin@123`.
- Knowledge of which role you want to assign (see Step 3).

## Step 1 — Open the Users page

Navigate to `/users`. You see a table of every user in the tenant with columns:
**Name**, **Email**, **Role**, **MFA**, **Last login**, **Status**. The data comes from
`GET /api/auth/users`.

## Step 2 — Create the user

Press **Add user** in the top right. The dialog asks for:

- **Email** (required, must be unique across tenants).
- **Full name** (required).
- **Role** (required, dropdown).
- **NPI** (optional, required only for MD-role accounts).
- **Force password reset on first login** (default on, leave on).
- **Require MFA** (default on, leave on).

Fill the form and press **Create**. Under the hood the UI calls:

```bash
curl -s -X POST "http://localhost:8500/api/auth/users" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "email": "newcoder@example.com",
        "full_name": "Pat New",
        "role": "coder",
        "require_mfa": true,
        "force_password_reset": true
      }'
```

**Expected outcome:** the API returns `201 Created` with the new user ID, and an
invitation email is sent to the user containing a one-time password reset link.

## Step 3 — Pick the right role

The platform ships seven roles. Pick the **least privilege** that does the job:

| Role | Can do | Use for |
|---|---|---|
| `viewer` | Read-only on dashboards | Executives, auditors |
| `coder` | Triage suspects, accept/dismiss | Your coding team |
| `coder_senior` | Coder + force-accept + reverse | Team leads |
| `md` | All clinical pages + attest | Physicians |
| `analyst` | Reports, exports, cohort builder | Operations and finance |
| `admin` | User management, settings | Your platform owner |
| `auditor` | Read-only on audit trail + RADV | External SOC 2 auditor (see Tutorial 11) |

Roles compose: a user can be both `md` and `coder_senior` (the union of permissions
applies).

## Step 4 — Walk the user through first login + MFA

Tell the user to:

1. Click the link in the invitation email.
2. Set a password (min 12 chars, one number, one symbol, not a recent breach hash).
3. On the next page, scan the QR code with Google Authenticator, 1Password, or any
   TOTP app.
4. Enter the 6-digit code to confirm.
5. Save the 10 one-time recovery codes shown next — these are the only way back in if
   they lose their phone.

The MFA secret is stored AES-encrypted in `users.totp_secret_enc`. The recovery codes
are bcrypt-hashed (you cannot retrieve them later — only re-issue).

## Step 5 — Verify

In a private window, log in as the new user. You should:

- Be prompted for the MFA code at every login.
- See only the sidebar items their role allows. A `coder` does **not** see
  `/users`, `/system`, or `/audit` admin sections.

Pull the user back up in the admin Users page; the **Last login** column should now
show "a minute ago".

## Step 6 — Reset MFA if a user loses their phone

In the user's row, open the overflow menu → **Reset MFA**. You'll be asked for your
own MFA code (an admin re-confirmation). The next time the user logs in they will
re-scan a fresh QR code. All previous recovery codes are invalidated.

## Step 7 — Deactivate, don't delete

When someone leaves the team, use **Deactivate** (overflow menu). Deactivation:

- Sets `users.status = 'disabled'`.
- Revokes all active refresh tokens.
- Preserves their historical audit entries (required for SOC 2).

Use **Delete** only for typo'd accounts that never logged in.

## Common pitfalls

- **Sending the wrong role** — easy to assign `admin` to "just one more person".
  Don't. Two admins per tenant is the recommended max.
- **Skipping MFA** — the toggle exists for vendor accounts that use SSO, but for
  everyone else MFA must stay on.
- **Sharing logins** — the demo `admin@raf.health` exists for the demo only; never
  share a real admin login. Audit attribution depends on per-user accounts.

## Troubleshooting

- **Invite email not received** — check `/admin/notifications` for the failed-send
  list. If SendGrid is in circuit-open state, retry from the Outreach campaign panel
  (Tutorial 12 covers replay).
- **"409: email exists"** — that email is already a user (possibly in another tenant
  if you're multi-tenant). Use a different email.
- **MFA reset doesn't trigger re-enrollment** — confirm the user logs out fully; an
  open session uses the old token until it expires.

## Next step

Now that users exist, run your first audit:

[Tutorial 10 — Run a RADV audit from sample to export](10-admin-radv-audit.md)
