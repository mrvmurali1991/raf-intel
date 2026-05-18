# Authenticate with JWT (login → refresh → scopes)

> Audience: Developer / Integrator  •  Time: 7 min

This tutorial gets you authenticated against the RAF Intelligence API: log in, refresh
an expiring access token, request scoped tokens for a service account, and call a
protected endpoint.

## Prerequisites

- The platform reachable at `http://localhost:8500` (or your tenant). Verify:

```bash
BASE=http://localhost:8500
curl -s "$BASE/health" | jq
# Expected output: {"status":"ok","time":"..."}
```

- `jq` installed for the examples.

## Step 1 — Log in

```bash
BASE=http://localhost:8500
LOGIN=$(curl -s -X POST "$BASE/api/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@raf.health","password":"Admin@123"}')

echo "$LOGIN" | jq
```

Expected output:

```json
{
  "access_token": "eyJhbGci...",
  "refresh_token": "eyJhbGci...",
  "access_expires_in": 900,
  "refresh_expires_in": 2592000,
  "user": { "id": 1, "email": "admin@raf.health", "roles": ["admin"] }
}
```

The access token lives 15 minutes; refresh lives 30 days. Store both — the access in
memory, the refresh in a secure cookie or OS keychain.

## Step 2 — Decode the access token

Access tokens are signed with RS256. Decode (without verifying) to see the claims:

```bash
ACCESS=$(echo "$LOGIN" | jq -r .access_token)
echo "$ACCESS" | cut -d. -f2 | base64 -d 2>/dev/null | jq
```

You'll see claims like:

```json
{
  "sub": "1",
  "email": "admin@raf.health",
  "roles": ["admin"],
  "scopes": ["suspects:read", "suspects:write", "patients:read", "..."],
  "tenant_id": "t_demo",
  "exp": 1716222345,
  "iat": 1716221445,
  "iss": "raf-intel"
}
```

For real verification fetch the JWKS at `GET $BASE/.well-known/jwks.json` and verify
the signature with any standard JWT library.

## Step 3 — Call a protected endpoint

```bash
ACCESS=$(echo "$LOGIN" | jq -r .access_token)

curl -s "$BASE/api/patients?limit=3" \
  -H "Authorization: Bearer $ACCESS" | jq '.patients[] | .id'
# Expected output: 3 patient IDs (the demo seed uses 3, 7, 8, 22)
```

If the call returns 401 your token expired (or you typed it wrong). Refresh it
(Step 4).

## Step 4 — Refresh

When you see 401 with body `{"detail": "token_expired"}`:

```bash
REFRESH=$(echo "$LOGIN" | jq -r .refresh_token)

NEW=$(curl -s -X POST "$BASE/api/auth/refresh" \
  -H 'Content-Type: application/json' \
  -d "{\"refresh_token\":\"$REFRESH\"}")

echo "$NEW" | jq '{access_token, refresh_token}'
```

The platform rotates the refresh token on every refresh, so always replace your stored
refresh token with the new value. Reusing an old refresh token after it has been
rotated triggers a security alert and disables the account session.

## Step 5 — Service accounts (for backend-to-backend)

For server-side integrations, create a service account instead of a real user:

1. As an admin, `/settings/api-keys` → **Create service account**.
2. Pick the minimum scopes (least privilege; see Step 7).
3. Save the `client_id` and `client_secret` shown once — they're not retrievable
   later.

Then perform a client-credentials grant:

```bash
curl -s -X POST "$BASE/api/auth/token" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d "grant_type=client_credentials&client_id=$CID&client_secret=$CSECRET&scope=suspects:read"
```

You get back an access token (no refresh — service accounts re-authenticate on
expiry).

## Step 6 — MFA-required users

If a user has MFA enabled, `POST /api/auth/login` returns:

```json
{ "mfa_required": true, "mfa_session": "<short_lived_token>" }
```

Complete the second factor:

```bash
curl -s -X POST "$BASE/api/auth/mfa/verify" \
  -H 'Content-Type: application/json' \
  -d '{"mfa_session":"...", "code":"123456"}'
```

Returns the same shape as Step 1. Service accounts cannot have MFA.

## Step 7 — Scopes (least privilege)

Scopes are dot-delimited `resource:action` strings. The most common:

| Scope | What it allows |
|---|---|
| `patients:read` | Read patient records |
| `patients:write` | Create/update patient records |
| `suspects:read` | List suspects |
| `suspects:write` | Accept/dismiss suspects |
| `suspects:force` | Force-accept |
| `meat:attest` | Sign MEAT attestations |
| `audit:read` | Read audit events |
| `webhooks:deliver` | Receive webhooks (assigned to webhook endpoints, not users) |

Request only what you need. Tokens with extra scopes are flagged in the SOC 2
review (Tutorial 11).

## Common pitfalls

- **Refresh-after-refresh** — you must replace the stored refresh token on every call.
  Otherwise the next refresh fails.
- **Storing access tokens long-term** — they expire in 15 min by design. Refresh.
- **Bearer prefix** — `Authorization: Bearer <token>`, not `JWT <token>`.

## Troubleshooting

- **401 with `wrong_audience`** — your token was minted for a different tenant.
- **401 with `revoked`** — admin disabled the session. Log in again.
- **CORS errors in browser** — call the API from your own backend; the browser CORS
  policy allows only your tenant origin.

## Next step

Now use that token against the suspect workflow:

[Tutorial 15 — Use the `/api/suspects` API end-to-end](15-dev-suspect-api.md)
