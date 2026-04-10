# OpenEMR FHIR Integration - Quick Start Guide

**For Backend Implementation Team**

---

## Critical Credentials

Store these in environment variables:

```env
OPENEMR_FHIR_BASE=https://openemr.ehrservicedesk.com/apis/default/fhir
OPENEMR_OAUTH_ISSUER=https://openemr.ehrservicedesk.com/oauth2/default
OPENEMR_CLIENT_ID=wEyZg7hm7RLH0_lpcH3gzaHzY7kQLOnd7nDWR2exNL4
OPENEMR_REDIRECT_URI=http://localhost:3000/emr-config/callback
OPENEMR_REGISTRATION_TOKEN=ZIxcaS7J66SUoqcMbfH3LuiBvmJsSSKQ7apH6kcXRC0
```

---

## OAuth2 Authorization Flow

### 1. Generate PKCE Challenge

```python
import hashlib
import base64
import secrets

code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
code_challenge = base64.urlsafe_b64encode(
    hashlib.sha256(code_verifier.encode('utf-8')).digest()
).decode('utf-8').rstrip('=')

# Store code_verifier in session, use code_challenge in URL
```

### 2. Redirect User to Authorization Endpoint

```python
from urllib.parse import urlencode
import uuid

auth_url = "https://openemr.ehrservicedesk.com/oauth2/default/authorize"
params = {
    "client_id": "wEyZg7hm7RLH0_lpcH3gzaHzY7kQLOnd7nDWR2exNL4",
    "redirect_uri": "http://localhost:3000/emr-config/callback",
    "response_type": "code",
    "scope": "openid profile api:fhir patient/Patient.read patient/Condition.read patient/Encounter.read patient/MedicationRequest.read patient/Observation.read patient/DiagnosticReport.read",
    "state": str(uuid.uuid4()),  # CSRF protection
    "code_challenge": code_challenge,
    "code_challenge_method": "S256"
}

redirect_url = f"{auth_url}?{urlencode(params)}"
# Redirect user's browser to redirect_url
```

### 3. Handle Callback

```python
from flask import request
import requests

# User is redirected back with ?code=... and ?state=...
auth_code = request.args.get('code')
state = request.args.get('state')

# Verify state matches what you stored in session
if state != session['oauth_state']:
    raise Exception("CSRF token mismatch")

# Exchange code for access token
token_url = "https://openemr.ehrservicedesk.com/oauth2/default/token"
token_data = {
    "grant_type": "authorization_code",
    "code": auth_code,
    "client_id": "wEyZg7hm7RLH0_lpcH3gzaHzY7kQLOnd7nDWR2exNL4",
    "redirect_uri": "http://localhost:3000/emr-config/callback",
    "code_verifier": session['code_verifier']  # Retrieved from step 1
}

response = requests.post(token_url, data=token_data)
token_response = response.json()

access_token = token_response['access_token']
refresh_token = token_response.get('refresh_token')  # May be present for offline_access
expires_in = token_response['expires_in']  # Seconds until expiry

# Store tokens securely in session/database
session['access_token'] = access_token
session['refresh_token'] = refresh_token
session['token_expires_at'] = now + timedelta(seconds=expires_in)
```

---

## FHIR API Queries

### Patient Demographics

```python
import requests

def get_patient(patient_id, access_token):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    
    url = f"https://openemr.ehrservicedesk.com/apis/default/fhir/Patient/{patient_id}"
    response = requests.get(url, headers=headers)
    
    return response.json()

# Response includes:
# {
#   "resourceType": "Patient",
#   "id": "...",
#   "name": [...],
#   "gender": "...",
#   "birthDate": "...",
#   "address": [...],
#   "telecom": [...]
# }
```

### Conditions (Diagnoses)

```python
def get_conditions(patient_id, access_token):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    
    url = f"https://openemr.ehrservicedesk.com/apis/default/fhir/Condition"
    params = {"patient": patient_id}
    
    response = requests.get(url, headers=headers, params=params)
    bundle = response.json()
    
    conditions = []
    for entry in bundle.get("entry", []):
        conditions.append(entry["resource"])
    
    return conditions

# Each condition includes:
# {
#   "code": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "..."}]},
#   "category": [...],
#   "clinicalStatus": "...",
#   "verificationStatus": "..."
# }
```

### Medications

```python
def get_medications(patient_id, access_token):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    
    url = f"https://openemr.ehrservicedesk.com/apis/default/fhir/MedicationRequest"
    params = {"patient": patient_id}
    
    response = requests.get(url, headers=headers, params=params)
    bundle = response.json()
    
    medications = []
    for entry in bundle.get("entry", []):
        medications.append(entry["resource"])
    
    return medications

# Each medication request includes:
# {
#   "medication": {"reference": "Medication/..."},
#   "dosageInstruction": [...],
#   "status": "active|completed|..."
# }
```

### Observations (Lab Values, Vitals)

```python
def get_observations(patient_id, access_token):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    
    url = f"https://openemr.ehrservicedesk.com/apis/default/fhir/Observation"
    params = {"patient": patient_id}
    
    response = requests.get(url, headers=headers, params=params)
    bundle = response.json()
    
    observations = []
    for entry in bundle.get("entry", []):
        observations.append(entry["resource"])
    
    return observations

# Each observation includes:
# {
#   "code": {"coding": [{"system": "http://loinc.org", "code": "..."}]},
#   "value": {"value": 123, "unit": "..."},
#   "effectiveDateTime": "...",
#   "status": "final|preliminary|..."
# }
```

### Encounters (Clinical Visits)

```python
def get_encounters(patient_id, access_token):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    
    url = f"https://openemr.ehrservicedesk.com/apis/default/fhir/Encounter"
    params = {"patient": patient_id}
    
    response = requests.get(url, headers=headers, params=params)
    bundle = response.json()
    
    encounters = []
    for entry in bundle.get("entry", []):
        encounters.append(entry["resource"])
    
    return encounters

# Each encounter includes:
# {
#   "type": [...],
#   "period": {"start": "...", "end": "..."},
#   "class": {"code": "AMB|IMP|..."},
#   "status": "finished|in-progress|..."
# }
```

---

## Error Handling

```python
import requests
from requests.exceptions import RequestException

def safe_fhir_request(url, access_token, params=None):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        
        if response.status_code == 401:
            # Token expired, refresh it
            refresh_access_token()
            return None
        
        if response.status_code == 403:
            # Insufficient permissions
            raise PermissionError("User lacks permission to access this resource")
        
        if response.status_code == 404:
            # Resource not found
            raise ValueError("Resource not found")
        
        response.raise_for_status()
        return response.json()
    
    except RequestException as e:
        raise Exception(f"FHIR API error: {str(e)}")

def refresh_access_token(refresh_token):
    token_url = "https://openemr.ehrservicedesk.com/oauth2/default/token"
    
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": "wEyZg7hm7RLH0_lpcH3gzaHzY7kQLOnd7nDWR2exNL4"
    }
    
    response = requests.post(token_url, data=data)
    
    if response.status_code != 200:
        raise Exception("Token refresh failed")
    
    token_response = response.json()
    return token_response['access_token']
```

---

## Test Endpoints

### Verify FHIR Server

```bash
curl https://openemr.ehrservicedesk.com/apis/default/fhir/metadata | jq .
```

### Verify OAuth2 Config

```bash
curl https://openemr.ehrservicedesk.com/oauth2/default/.well-known/openid-configuration | jq .
```

### Get Specific Patient (requires valid access token)

```bash
curl -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  https://openemr.ehrservicedesk.com/apis/default/fhir/Patient/123
```

---

## Important Notes

1. **Access Token Lifetime:** Check `expires_in` in token response; typically 1-3600 seconds
2. **Patient Context:** After OAuth, the access token is scoped to the authenticated patient
3. **Rate Limiting:** Unknown; test aggressively at start but monitor for 429 responses
4. **Data Format:** Always JSON; no XML support
5. **Pagination:** Use `_count` parameter for `Bundle.entry` pagination
6. **Search:** All search operations use FHIR standard search parameters

---

## Environment Configuration

```
OPENEMR_ENVIRONMENT=production
OPENEMR_FHIR_BASE=https://openemr.ehrservicedesk.com/apis/default/fhir
OPENEMR_OAUTH_BASE=https://openemr.ehrservicedesk.com/oauth2/default
OPENEMR_CLIENT_ID=wEyZg7hm7RLH0_lpcH3gzaHzY7kQLOnd7nDWR2exNL4
OPENEMR_CALLBACK_URL=http://localhost:3000/emr-config/callback
SECURE_SESSION=true
PKCE_REQUIRED=true
```

---

## Logging / Debugging

Enable these in development:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Log all HTTP requests/responses
import http.client
http.client.HTTPConnection.debuglevel = 1
```

---

## References

- FHIR Base: https://openemr.ehrservicedesk.com/apis/default/fhir/
- SMART Config: https://openemr.ehrservicedesk.com/apis/default/fhir/.well-known/smart-configuration
- OpenID Config: https://openemr.ehrservicedesk.com/oauth2/default/.well-known/openid-configuration
- FHIR R4 Spec: http://hl7.org/fhir/R4/
- SMART on FHIR: http://docs.smarthealthit.org/
