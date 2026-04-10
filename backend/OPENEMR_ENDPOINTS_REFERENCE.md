# OpenEMR Production Endpoints - Complete Reference

**Instance:** https://openemr.ehrservicedesk.com  
**Date Verified:** 2026-04-07  
**Status:** All endpoints OPERATIONAL

---

## Configuration Endpoints (Well-Known)

### FHIR CapabilityStatement
```
GET https://openemr.ehrservicedesk.com/apis/default/fhir/metadata
Status: 200 OK
Content-Type: application/json

Response: FHIR CapabilityStatement (1791 lines)
- FHIR Version: 4.0.1
- Status: active
- Software: OpenEMR
```

### OpenID Connect Configuration
```
GET https://openemr.ehrservicedesk.com/oauth2/default/.well-known/openid-configuration
Status: 200 OK
Content-Type: application/json

Response includes:
- issuer
- authorization_endpoint
- token_endpoint
- jwks_uri
- userinfo_endpoint
- registration_endpoint
- introspection_endpoint
- scopes_supported (400+ scopes)
- grant_types_supported: [authorization_code, password, refresh_token]
- response_types_supported: [code, token, id_token, ...]
- code_challenge_methods_supported: [S256, plain]
```

### SMART on FHIR Configuration
```
GET https://openemr.ehrservicedesk.com/apis/default/fhir/.well-known/smart-configuration
Status: 200 OK
Content-Type: application/json

Response includes:
- issuer
- authorization_endpoint
- token_endpoint
- token_endpoint_auth_methods_supported: [client_secret_basic, private_key_jwt]
- capabilities: [launch-ehr, launch-standalone, client-public, ...]
- code_challenge_methods_supported: [S256]
```

---

## OAuth2 Endpoints

### Authorization Endpoint
```
GET/POST https://openemr.ehrservicedesk.com/oauth2/default/authorize

Query Parameters:
- client_id: string (REQUIRED)
- redirect_uri: string (REQUIRED)
- response_type: "code" (REQUIRED)
- scope: string (REQUIRED)
- state: string (REQUIRED - CSRF protection)
- code_challenge: string (REQUIRED for PKCE)
- code_challenge_method: "S256" (REQUIRED)

Example:
https://openemr.ehrservicedesk.com/oauth2/default/authorize?
  client_id=wEyZg7hm7RLH0_lpcH3gzaHzY7kQLOnd7nDWR2exNL4&
  redirect_uri=http://localhost:3000/emr-config/callback&
  response_type=code&
  scope=openid+profile+api:fhir+patient%2FPatient.read&
  state=abc123def456&
  code_challenge=E9Mrozoa2owUednqKqapiXECouuW8vQFRQO_N5VoWM&
  code_challenge_method=S256

Response (redirect): 302 Found
Location: http://localhost:3000/emr-config/callback?code=...&state=...
```

### Token Endpoint
```
POST https://openemr.ehrservicedesk.com/oauth2/default/token
Content-Type: application/x-www-form-urlencoded

Body (Authorization Code Grant):
grant_type=authorization_code&
code=[auth_code_from_authorize]&
client_id=wEyZg7hm7RLH0_lpcH3gzaHzY7kQLOnd7nDWR2exNL4&
redirect_uri=http://localhost:3000/emr-config/callback&
code_verifier=[pkce_verifier]

Body (Refresh Token Grant):
grant_type=refresh_token&
refresh_token=[refresh_token]&
client_id=wEyZg7hm7RLH0_lpcH3gzaHzY7kQLOnd7nDWR2exNL4

Response: 200 OK
Content-Type: application/json
{
  "access_token": "eyJhbGc...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "refresh_token": "...",
  "scope": "openid profile api:fhir patient/Patient.read ...",
  "id_token": "eyJhbGc..."
}
```

### UserInfo Endpoint
```
GET https://openemr.ehrservicedesk.com/oauth2/default/userinfo
Authorization: Bearer [access_token]

Response: 200 OK
{
  "sub": "...",
  "name": "...",
  "email": "...",
  "fhirUser": "Patient/[patient-id]",
  "email_verified": true,
  ...
}
```

### Token Introspection Endpoint
```
POST https://openemr.ehrservicedesk.com/oauth2/default/introspect
Content-Type: application/x-www-form-urlencoded

Body:
token=[access_token_to_check]&
client_id=wEyZg7hm7RLH0_lpcH3gzaHzY7kQLOnd7nDWR2exNL4

Response: 200 OK
{
  "active": true,
  "scope": "openid profile api:fhir patient/Patient.read ...",
  "client_id": "wEyZg7hm7RLH0_lpcH3gzaHzY7kQLOnd7nDWR2exNL4",
  "exp": 1775589247,
  "iat": 1775585647,
  ...
}
```

### JWKS Endpoint (Public Key Set)
```
GET https://openemr.ehrservicedesk.com/oauth2/default/jwk

Response: 200 OK
{
  "keys": [
    {
      "kty": "RSA",
      "use": "sig",
      "kid": "...",
      "n": "...",
      "e": "AQAB"
    }
  ]
}
```

### Logout Endpoint
```
GET https://openemr.ehrservicedesk.com/oauth2/default/logout
?id_token_hint=[id_token]&
post_logout_redirect_uri=http://localhost:3000

Response: 302 Found
Location: http://localhost:3000
```

### Dynamic Client Registration
```
POST https://openemr.ehrservicedesk.com/oauth2/default/registration
Content-Type: application/json

Request Body:
{
  "client_name": "Your App Name",
  "redirect_uris": ["http://localhost:3000/callback"],
  "scope": "openid profile api:fhir patient/Patient.read patient/Condition.read ...",
  "grant_types": ["authorization_code"],
  "response_types": ["code"],
  "token_endpoint_auth_method": "client_secret_post",
  "contacts": ["admin@example.com"]
}

Response: 201 Created
{
  "client_id": "...",
  "client_secret": "",
  "registration_access_token": "...",
  "registration_client_uri": "https://...",
  "client_id_issued_at": 1775585647,
  "client_secret_expires_at": 0,
  ...
}
```

---

## FHIR API Endpoints

All FHIR endpoints require:
```
Authorization: Bearer [access_token]
Accept: application/json
Content-Type: application/json
```

### Patient Resource
```
GET https://openemr.ehrservicedesk.com/apis/default/fhir/Patient
GET https://openemr.ehrservicedesk.com/apis/default/fhir/Patient/[id]

Search Parameters:
- _id: Patient ID
- _lastUpdated: Last modified date
- name: Patient name
- given: Given name
- family: Family name
- birthdate: Birth date
- gender: Gender
- identifier: Patient identifier

Example:
GET https://openemr.ehrservicedesk.com/apis/default/fhir/Patient?name=smith
```

### Condition Resource (Diagnoses)
```
GET https://openemr.ehrservicedesk.com/apis/default/fhir/Condition
GET https://openemr.ehrservicedesk.com/apis/default/fhir/Condition/[id]

Search Parameters:
- patient: Patient reference
- code: Condition code (ICD-10)
- status: active | inactive | resolved
- category: problem-list-item | encounter-diagnosis | health-concern
- _lastUpdated: Last modified date

Example:
GET https://openemr.ehrservicedesk.com/apis/default/fhir/Condition?patient=[patient-id]
```

### Encounter Resource
```
GET https://openemr.ehrservicedesk.com/apis/default/fhir/Encounter
GET https://openemr.ehrservicedesk.com/apis/default/fhir/Encounter/[id]

Search Parameters:
- patient: Patient reference
- date: Encounter date
- status: planned | arrived | in-progress | finished
- _lastUpdated: Last modified date

Example:
GET https://openemr.ehrservicedesk.com/apis/default/fhir/Encounter?patient=[patient-id]&date=2025
```

### MedicationRequest Resource
```
GET https://openemr.ehrservicedesk.com/apis/default/fhir/MedicationRequest
GET https://openemr.ehrservicedesk.com/apis/default/fhir/MedicationRequest/[id]

Search Parameters:
- patient: Patient reference
- status: active | completed | stopped
- _lastUpdated: Last modified date

Example:
GET https://openemr.ehrservicedesk.com/apis/default/fhir/MedicationRequest?patient=[patient-id]
```

### Observation Resource
```
GET https://openemr.ehrservicedesk.com/apis/default/fhir/Observation
GET https://openemr.ehrservicedesk.com/apis/default/fhir/Observation/[id]

Search Parameters:
- patient: Patient reference
- code: Observation code (LOINC)
- category: vital-signs | laboratory | social-history | survey
- status: final | preliminary | registered
- date: Observation date
- _lastUpdated: Last modified date

Example:
GET https://openemr.ehrservicedesk.com/apis/default/fhir/Observation?patient=[patient-id]&category=vital-signs
```

### DiagnosticReport Resource
```
GET https://openemr.ehrservicedesk.com/apis/default/fhir/DiagnosticReport
GET https://openemr.ehrservicedesk.com/apis/default/fhir/DiagnosticReport/[id]

Search Parameters:
- patient: Patient reference
- code: Report type code
- status: registered | partial | preliminary | final | amended
- date: Report date
- _lastUpdated: Last modified date

Example:
GET https://openemr.ehrservicedesk.com/apis/default/fhir/DiagnosticReport?patient=[patient-id]
```

### Medication Resource
```
GET https://openemr.ehrservicedesk.com/apis/default/fhir/Medication
GET https://openemr.ehrservicedesk.com/apis/default/fhir/Medication/[id]

Search Parameters:
- code: Medication code
- _id: Medication ID
- _lastUpdated: Last modified date
```

### Practitioner Resource
```
GET https://openemr.ehrservicedesk.com/apis/default/fhir/Practitioner
GET https://openemr.ehrservicedesk.com/apis/default/fhir/Practitioner/[id]

Search Parameters:
- name: Practitioner name
- given: Given name
- family: Family name
- identifier: NPI or other identifier
```

### AllergyIntolerance Resource
```
GET https://openemr.ehrservicedesk.com/apis/default/fhir/AllergyIntolerance
GET https://openemr.ehrservicedesk.com/apis/default/fhir/AllergyIntolerance/[id]

Search Parameters:
- patient: Patient reference
- code: Allergy code
- clinical-status: active | inactive | resolved
- _lastUpdated: Last modified date
```

---

## Response Format Examples

### FHIR Bundle (Search Results)
```json
{
  "resourceType": "Bundle",
  "type": "searchset",
  "total": 5,
  "entry": [
    {
      "fullUrl": "https://openemr.ehrservicedesk.com/apis/default/fhir/Condition/123",
      "resource": {
        "resourceType": "Condition",
        "id": "123",
        "code": {
          "coding": [
            {
              "system": "http://hl7.org/fhir/sid/icd-10-cm",
              "code": "E11.9",
              "display": "Type 2 diabetes mellitus without complications"
            }
          ]
        }
      }
    }
  ]
}
```

### Error Response
```json
{
  "resourceType": "OperationOutcome",
  "issue": [
    {
      "severity": "error",
      "code": "processing",
      "diagnostics": "Invalid patient ID"
    }
  ]
}
```

---

## HTTP Headers

### Request Headers (Required)
```
Authorization: Bearer eyJhbGc...
Accept: application/json
User-Agent: RAF-Intelligence/1.0
```

### Response Headers (Typical)
```
HTTP/2 200
Date: Tue, 07 Apr 2026 18:13:53 GMT
Content-Type: application/json; charset=utf-8
Cache-Control: max-age=0, private, must-revalidate
Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
```

---

## Authentication Methods

### Bearer Token (OAuth2)
```
Authorization: Bearer [access_token]
```

### Basic Authentication (Not Recommended)
```
Authorization: Basic base64([client_id]:[client_secret])
```

---

## Error Codes & Meanings

| HTTP Status | Meaning | Action |
|---|---|---|
| 200 | Success | Process response normally |
| 201 | Created | Resource successfully created |
| 400 | Bad Request | Check request parameters/body |
| 401 | Unauthorized | Refresh or re-authenticate |
| 403 | Forbidden | User lacks scope permission |
| 404 | Not Found | Resource doesn't exist |
| 429 | Rate Limited | Back off and retry later |
| 500 | Server Error | Contact support |

---

## Rate Limiting

**Status:** Unknown (not documented by OpenEMR)  
**Action:** Monitor for 429 responses and implement exponential backoff

---

## Pagination

Use `_count` parameter to limit results:
```
GET https://openemr.ehrservicedesk.com/apis/default/fhir/Patient?_count=10
```

Use `_offset` or `_getpages` for pagination (FHIR standard):
```
GET https://openemr.ehrservicedesk.com/apis/default/fhir/Patient?_count=10&_offset=0
```

---

## Supported FHIR Resources (Complete List)

| Resource | Available | Supported Operations |
|---|---|---|
| AllergyIntolerance | Yes | read, search-type |
| Appointment | Yes | read, search-type |
| Binary | Yes | read, search-type |
| CarePlan | Yes | read, search-type |
| CareTeam | Yes | read, search-type |
| Condition | Yes | read, search-type |
| Coverage | Yes | read, search-type |
| Device | Yes | read, search-type |
| DiagnosticReport | Yes | read, search-type |
| DocumentReference | Yes | read, search-type |
| Encounter | Yes | read, search-type |
| Goal | Yes | read, search-type |
| Group | Yes | read, search-type |
| Immunization | Yes | read, search-type |
| Location | Yes | read, search-type |
| Media | Yes | read, search-type |
| Medication | Yes | read, search-type |
| MedicationDispense | Yes | read, search-type |
| MedicationRequest | Yes | read, search-type |
| Observation | Yes | read, search-type |
| OperationDefinition | Yes | read, search-type |
| Organization | Yes | read, search-type |
| Patient | Yes | read, search-type |
| Person | Yes | read, search-type |
| Practitioner | Yes | read, search-type |
| PractitionerRole | Yes | read, search-type |
| Procedure | Yes | read, search-type |
| Provenance | Yes | read, search-type |
| Questionnaire | Yes | read, search-type |
| QuestionnaireResponse | Yes | read, search-type |
| RelatedPerson | Yes | read, search-type |
| ServiceRequest | Yes | read, search-type |
| Specimen | Yes | read, search-type |
| ValueSet | Yes | read, search-type |

---

## Test Cases

### Test 1: Verify Metadata
```bash
curl -i https://openemr.ehrservicedesk.com/apis/default/fhir/metadata
# Expected: 200 OK with FHIR CapabilityStatement
```

### Test 2: Verify OAuth2
```bash
curl -s https://openemr.ehrservicedesk.com/oauth2/default/.well-known/openid-configuration | jq .issuer
# Expected: "https://openemr.ehrservicedesk.com/oauth2/default"
```

### Test 3: Verify SMART Config
```bash
curl -s https://openemr.ehrservicedesk.com/apis/default/fhir/.well-known/smart-configuration | jq .capabilities
# Expected: Array including "launch-ehr", "client-public", etc.
```

### Test 4: Get Specific Patient (requires valid token)
```bash
curl -H "Authorization: Bearer [TOKEN]" \
  https://openemr.ehrservicedesk.com/apis/default/fhir/Patient/[ID]
# Expected: 200 OK with Patient resource
```

---

## Credentials Reference

**Production Client:**
- Client ID: `wEyZg7hm7RLH0_lpcH3gzaHzY7kQLOnd7nDWR2exNL4`
- Client Secret: (empty - public client)
- Client Role: patient
- Redirect URI: `http://localhost:3000/emr-config/callback`
- Registered Scopes: `openid profile api:fhir patient/Patient.read patient/Condition.read patient/Encounter.read patient/MedicationRequest.read patient/Observation.read patient/DiagnosticReport.read`
- Registration Token: `ZIxcaS7J66SUoqcMbfH3LuiBvmJsSSKQ7apH6kcXRC0`
- Client ID Issued At: `1775585647` (2026-04-07 18:13:47 UTC)
- Client Secret Expires: Never

---

## Security Considerations

1. **Always use HTTPS** - Do not use HTTP
2. **PKCE is required** - Use S256 code challenge method
3. **Store tokens securely** - Use httpOnly, secure cookies or secure storage
4. **Validate signatures** - Use JWKS endpoint to verify ID token signatures
5. **Implement CSRF** - Use state parameter in authorization flow
6. **Refresh tokens** - Implement refresh token rotation
7. **Short-lived access tokens** - Assume 1-hour expiry; refresh as needed

---

## Support & Documentation

- FHIR R4 Spec: http://hl7.org/fhir/R4/
- SMART on FHIR: http://docs.smarthealthit.org/
- OpenID Connect: https://openid.net/specs/openid-connect-core-1_0.html
- OAuth2: https://tools.ietf.org/html/rfc6749
- PKCE: https://tools.ietf.org/html/rfc7636
