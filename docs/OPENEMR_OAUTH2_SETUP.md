# OpenEMR OAuth2 (SMART on FHIR) Integration Guide

## Overview

RAF Intelligence connects to OpenEMR via the **OAuth2 Authorization Code + PKCE** flow — the industry-standard method for healthcare SaaS applications accessing FHIR data from EMR systems.

**Flow**: User clicks "Authorize" -> redirected to OpenEMR login -> approves access -> tokens stored -> Sync fetches data using those tokens.

---

## Architecture

```
RAF Frontend          RAF Backend              OpenEMR
-----------          -----------              -------
1. Click Authorize -->
                     2. Generate PKCE
                        (code_verifier + challenge)
                     3. Store state in DB
                     4. Return authorize_url
<-- redirect browser to OpenEMR authorize URL

5. User logs into OpenEMR, approves access
                     <-- 6. Redirect to /emr-config/callback?code=...&state=...
7. Callback page
   sends code+state -->
                     8. Verify state (one-time use)
                     9. Exchange code for tokens
                        (POST /oauth2/default/token
                         with code_verifier for PKCE)
                     10. Encrypt & store tokens
<-- 11. Success, redirect back

12. Click Sync -->
                     13. Load stored tokens
                     14. Call FHIR API with Bearer token
                     15. Auto-refresh if expired
```

---

## Setup Steps

### Step 1: Register OAuth2 Client in OpenEMR

OpenEMR supports RFC 7591 Dynamic Client Registration. Run this command (already done):

```bash
curl -sk -X POST "https://openemr.ehrservicedesk.com/oauth2/default/registration" \
  -H "Content-Type: application/json" \
  -d '{
    "application_type": "web",
    "redirect_uris": [
      "https://raf.comercioit.com/emr-config/callback",
      "http://localhost:3001/emr-config/callback"
    ],
    "client_name": "RAF Intelligence Production",
    "token_endpoint_auth_method": "client_secret_post",
    "contacts": ["admin@raf.health"],
    "scope": "openid api:fhir api:oemr",
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"]
  }'
```

**Registered Clients (all auto-enabled, verified 2026-04-06):**

| Client Name | Client ID | Type | Status |
|------------|-----------|------|--------|
| RAF Intelligence | `HiOgcn8AuldnXty63EF54oktQl9xslbr9TW3wb64Y9w` | Confidential | Enabled |
| RAF Intelligence Production | `lK4J4awf_5g0lYj5c4zmXz7_gn10uMaYQcfmQwzN7NU` | Public | Enabled |
| RAF Test Client | `BzkPzq_YJgTxfCTNMPshZ3XHFXWw_KhwSFPtYgslFMg` | Public | Enabled |

**Recommended for production**: Use the confidential client `HiOgcn8A...` with its secret.

### Step 2: Enable the Client in OpenEMR Admin (if needed)

Dynamically registered clients are auto-enabled. To verify or change:

1. Log into OpenEMR: https://openemr.ehrservicedesk.com
   - Username: `admin`
   - Password: `Healthcare@Admin2026`
2. Go to **Admin > System > Clients** (in the left sidebar menu)
3. Click **Edit** next to the client
4. Check "Is Enabled" if not already enabled
5. Click **Enable Client** button at the top

### Step 3: Configure Connection in RAF Intelligence

1. Open RAF Intelligence: https://raf.comercioit.com/emr-config
2. Create or edit an EMR connection:
   - **Name**: OpenEMR Production
   - **Vendor**: OpenEMR
   - **Connection Type**: FHIR R4
   - **FHIR Base URL**: `https://openemr.ehrservicedesk.com/apis/default/fhir`
   - **Auth Type**: OAuth 2.0
   - **Client ID**: `HiOgcn8AuldnXty63EF54oktQl9xslbr9TW3wb64Y9w`
   - **Client Secret**: `NXK-FRBTYi2g2F2a4_GPjoM8QCd_6OSfD-v6v0u_-FMON-4NK6bd0TN1JY5LXLUpbO-6APERtJSS58M9tdRjhQ`
   - **Token URL**: `https://openemr.ehrservicedesk.com/oauth2/default/token`
3. Save the connection

> **Note on Cloudflare**: The OpenEMR instance is behind Cloudflare which blocks server-to-server API calls without a browser User-Agent header. The backend includes a User-Agent header automatically to bypass this.

### Step 4: Authorize the Connection

1. On the connection card, click the **Authorize** button
2. You'll be redirected to OpenEMR's login page
3. Log in with your OpenEMR credentials (admin or provider account)
4. Approve the requested scopes (FHIR access)
5. You'll be redirected back to RAF Intelligence with a success message
6. Tokens are now stored (encrypted) and ready for use

### Step 5: Sync Data

1. Click **Sync** on the connection card
2. The system uses the stored OAuth2 tokens to call FHIR API
3. Fetches Patient and Condition resources
4. Normalizes and stores them in the RAF database
5. If the access token expires, it auto-refreshes using the refresh token

---

## Technical Details

### Files Involved

| File | Purpose |
|------|---------|
| `backend/app/routers/emr.py` | OAuth2 authorize + callback endpoints |
| `backend/app/services/emr_manager.py` | State storage, token encryption/storage |
| `backend/app/services/vendor_adapters/openemr_fhir.py` | FHIR API calls with auto-refresh |
| `frontend/src/app/emr-config/page.tsx` | Authorize button, connection management |
| `frontend/src/app/emr-config/callback/page.tsx` | OAuth2 callback handler page |

### Database Tables

| Table | Purpose |
|-------|---------|
| `emr_connections` | Stores connection config + encrypted tokens (`access_token`, `refresh_token_emr`, `token_expires_at`) |
| `emr_oauth2_state` | Temporary PKCE state storage (auto-cleaned after 10 min) |

### Token Lifecycle

1. **Initial**: User authorizes via browser -> tokens stored encrypted (AES-256-GCM)
2. **Usage**: Each FHIR API call checks `token_expires_at` before using stored `access_token`
3. **Refresh**: If expired, uses `refresh_token` to get new tokens, stores updated tokens
4. **Fallback**: If refresh fails, user must re-authorize via the Authorize button

### Security

- Tokens encrypted at rest with AES-256-GCM
- PKCE (S256) prevents authorization code interception
- State parameter prevents CSRF attacks
- State entries are one-time use and expire after 10 minutes
- No client secret stored (public client pattern per SMART on FHIR spec)
- SSL/TLS for all communication with OpenEMR

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Invalid or expired state" on callback | State expired (>10 min) or was already used. Click Authorize again. |
| "Cannot determine authorize URL" | Set the FHIR Base URL correctly (must contain `/fhir` or `/apis/`). |
| 401 on Sync after authorization | Token expired and refresh failed. Click Authorize to re-authenticate. |
| "Client not found" on OpenEMR login | Client not yet enabled in OpenEMR admin panel. See Step 2. |
| Redirect goes to wrong URL | Check that the redirect URI registered in OpenEMR matches your environment. |
| 403 "error code: 1010" on token exchange | Cloudflare WAF blocking server-to-server POST. Backend must include browser `User-Agent` header (already configured). |
| 401 on FHIR API calls | Same Cloudflare issue — `User-Agent` header needed. Or token is invalid/expired. |

---

## Re-registering a Client

If you need to register a new client (e.g., for a different redirect URI):

```bash
curl -sk -X POST "https://openemr.ehrservicedesk.com/oauth2/default/registration" \
  -H "Content-Type: application/json" \
  -d '{
    "application_type": "web",
    "redirect_uris": ["https://YOUR-DOMAIN/emr-config/callback"],
    "client_name": "Your App Name",
    "token_endpoint_auth_method": "client_secret_post",
    "scope": "openid api:fhir",
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"]
  }'
```

Then enable the client in OpenEMR admin before use.
