# Epic SMART on FHIR Integration

Spec: SMART App Launch Framework STU 2.2 (https://hl7.org/fhir/smart-app-launch/STU2.2/)

## What is implemented

| Component | Location | Status |
|-----------|----------|--------|
| `/.well-known/smart-configuration` (issuer-side) | `GET /smart/.well-known/smart-configuration` | Complete |
| `/.well-known/smart-configuration` (tenant SMART API) | `GET /api/smart/.well-known/smart-configuration` | Complete |
| PKCE S256 authorization endpoint | `GET /smart/authorize` | Complete |
| Token endpoint (authorization_code + client_credentials) | `POST /smart/token` | Complete |
| EHR-launch landing page with in-browser PKCE generation | `GET /smart/launch?iss=&launch=` | Complete |
| Frontend launch page | `/smart/launch` (Next.js) | Complete |
| OAuth2 callback — code exchange, token storage (AES-256-GCM) | `GET /api/smart/callback` | Complete |
| SMART registration CRUD (admin-only) | `POST/GET/PUT/DELETE /api/smart/registrations` | Complete |
| Session listing | `GET /api/smart/sessions` | Complete |
| FHIR Patient fetch with access token + internal ID mapping | `GET /api/smart/patient` | Complete |
| Token auto-refresh via stored refresh_token | `smart_fhir_service.refresh_session_token()` | Complete |
| Epic wizard UI on /emr-config | `EpicSmartWizard` component | Complete |

## Scopes requested

```
openid  fhirUser  launch  launch/patient
patient/Patient.read
patient/Condition.read
patient/Encounter.read
patient/Observation.read
```

## EHR-launch flow

```
Epic EHR  →  GET /smart/launch?iss=<fhir_base>&launch=<token>
          Browser generates PKCE verifier/challenge in JS
          →  Discovery: GET <iss>/.well-known/smart-configuration
          →  Redirect: GET <epic_authz_endpoint>?...&code_challenge=S256...
Epic EHR  →  GET /api/smart/callback?code=<code>&state=<state>
          Server: POST <epic_token_endpoint> with code_verifier (PKCE)
          Server: stores access_token + refresh_token encrypted (AES-256-GCM)
          Server: fetches Patient/{id} via FHIR R4 API
          Server: maps to internal OpenEMR patient_id via MRN or name+DOB
```

## Standalone launch (from /emr-config wizard)

1. Admin registers Epic app via the "Add Epic Connection" wizard on `/emr-config`.
   Fields: FHIR base URL, Client ID, Redirect URI.
   The wizard tests SMART discovery before saving.
2. Registration is persisted to `smart_app_registrations` (client_secret AES-256-GCM encrypted).
3. Initiate launch: `GET /api/smart/launch?registration_id=<id>`.
   Server generates PKCE pair, stores session, redirects to Epic authorize endpoint.
4. Epic redirects to the registered redirect_uri with `code` and `state`.
5. `GET /api/smart/callback` exchanges the code for tokens and activates the session.

## Epic App Orchard checklist

- [ ] Register application at https://fhir.epic.com/Developer/Apps
- [ ] Set redirect URI to `https://<your-domain>/api/smart/callback`
- [ ] Request scopes listed above
- [ ] Set grant type: Authorization Code with PKCE
- [ ] Copy Client ID into the /emr-config wizard
- [ ] For production: Epic requires a published, SMART-conformant app — use the conformance test at https://inferno.healthit.gov/

## Known gaps / next steps

| Item | Priority |
|------|----------|
| id_token signature verification (RS256) | High — currently claims decoded without sig check; used only for launch context display, not authorization |
| Interactive consent screen on `/smart/authorize` | Required for Epic App Orchard certification; current MVP auto-approves |
| `patient/Observation.read` data pull into RAF pipeline | Medium — access_token is stored; FHIR fetch for Observations not yet wired into ingestion |
| `offline_access` scope for long-lived refresh tokens | Low — refresh_token flow is implemented; scope not requested by default |
| JWKS endpoint for private_key_jwt client auth | Low — endpoint advertised in discovery but JWT client auth not wired |

## Testing

### SMART App Launch Conformance (Inferno)

```bash
# Run against local dev server (must be reachable from inferno.healthit.gov or use ngrok)
# Discovery endpoint under test:
GET /smart/.well-known/smart-configuration
```

Expected response includes `code_challenge_methods_supported: ["S256"]` and all required scopes.

### Local end-to-end test

```bash
# 1. Start a PKCE flow against the local issuer
curl "http://localhost:8000/smart/launch"

# 2. Authorize (auto-approved in dev)
curl -G "http://localhost:8000/smart/authorize" \
  --data-urlencode "response_type=code" \
  --data-urlencode "client_id=raf-intelligence" \
  --data-urlencode "redirect_uri=http://localhost:8000/smart/callback" \
  --data-urlencode "scope=openid fhirUser patient/Patient.read patient/Condition.read patient/Encounter.read patient/Observation.read" \
  --data-urlencode "state=teststate" \
  --data-urlencode "code_challenge=<S256_challenge>" \
  --data-urlencode "code_challenge_method=S256"
# Follow redirect → /smart/callback?code=<code>&state=teststate

# 3. Exchange code for token
curl -X POST http://localhost:8000/smart/token \
  -d "grant_type=authorization_code&code=<code>&code_verifier=<verifier>&redirect_uri=http://localhost:8000/smart/callback&client_id=raf-intelligence"
```
