# FHIR EMR Integration: Complete Code Examples & API Reference

**Date:** April 5, 2026

---

## Table of Contents

1. [OAuth2 Request/Response Examples](#oauth2-requestresponse-examples)
2. [FHIR API Request Examples](#fhir-api-request-examples)
3. [Multi-EMR Discovery Matrix](#multi-emr-discovery-matrix)
4. [Error Handling Patterns](#error-handling-patterns)
5. [Production Code Snippets](#production-code-snippets)

---

## OAuth2 Request/Response Examples

### Epic Authorization Code Flow - Complete Example

**1. Discovery Endpoint**

```bash
curl -X GET "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/.well-known/smart-configuration" \
  -H "Accept: application/json"
```

**Response:**
```json
{
  "authorization_endpoint": "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/authorize",
  "token_endpoint": "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token",
  "token_endpoint_auth_methods_supported": [
    "client_secret_basic",
    "client_secret_post",
    "private_key_jwt"
  ],
  "revocation_endpoint": "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/revoke",
  "revocation_endpoint_auth_methods_supported": [
    "client_secret_basic",
    "client_secret_post"
  ],
  "introspection_endpoint": "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/introspect",
  "scopes_supported": [
    "openid",
    "fhirUser",
    "offline_access",
    "online_access",
    "launch/patient",
    "launch/encounter",
    "launch/appointment",
    "patient/Patient.read",
    "patient/Patient.search",
    "patient/Observation.read",
    "patient/Observation.search",
    "patient/Condition.read",
    "patient/Condition.search",
    "user/Patient.read",
    "user/Patient.search"
  ],
  "response_types_supported": [
    "code",
    "id_token"
  ],
  "grant_types_supported": [
    "authorization_code",
    "client_credentials"
  ],
  "code_challenge_methods_supported": [
    "S256",
    "plain"
  ],
  "subject_types_supported": [
    "public",
    "pairwise"
  ],
  "id_token_signing_alg_values_supported": [
    "RS384"
  ]
}
```

**2. Authorization Request (Frontend Redirect)**

```
GET https://fhir.epic.com/interconnect-fhir-oauth/oauth2/authorize
  ?response_type=code
  &client_id=client_id_from_epic_registration
  &redirect_uri=https%3A%2F%2Fyourapp.com%2Fcallback
  &scope=patient%2FPatient.rs%20patient%2FObservation.rs%20offline_access%20openid
  &state=af0ifjsldkj_state_value
  &code_challenge=E9Mrozoa2owUednw8ZG4Q1eRvMJ34G5LP7PEcde7Qg8
  &code_challenge_method=S256
  &aud=https%3A%2F%2Ffhir.epic.com%2Finterconnect-fhir-oauth%2Fapi%2FFHIR%2FR4
```

**3. Authorization Response (Redirect Back)**

```
GET https://yourapp.com/callback
  ?code=ZmE4N2U0YzMtZjdjZS00ODc3LWI2OTEtOTQ0MDk2ZDkxODQ4
  &state=af0ifjsldkj_state_value
```

**4. Token Exchange (Backend POST)**

```bash
curl -X POST "https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=authorization_code" \
  -d "code=ZmE4N2U0YzMtZjdjZS00ODc3LWI2OTEtOTQ0MDk2ZDkxODQ4" \
  -d "redirect_uri=https://yourapp.com/callback" \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET" \
  -d "code_verifier=dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
```

**Token Response:**
```json
{
  "access_token": "eyJhbGciOiJSUzM4NCIsInR5cCI6IkpXVCIsImtpZCI6IjEifQ.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyLCJleHAiOjE2MDAwMDAwMDB9.signature",
  "token_type": "Bearer",
  "expires_in": 3600,
  "refresh_token": "eyJhbGciOiJSUzM4NCIsInR5cCI6IkpXVCJ9...",
  "refresh_token_expires_in": 2592000,
  "scope": "patient/Patient.rs patient/Observation.rs offline_access openid",
  "id_token": "eyJhbGciOiJSUzM4NCIsInR5cCI6IkpXVCJ9...",
  "patient": "Zmlo84bIVJVqR0QeQxcZvJ4",
  "encounter": "7S8ZmqfRxX1TrEITc2pDn5"
}
```

### Cerner Authorization Code Flow - Complete Example

**1. Discovery Endpoint**

```bash
curl -X GET "https://fhir-ehr.sandboxcerner.com/r4/.well-known/smart-configuration" \
  -H "Accept: application/json"
```

**Response:**
```json
{
  "authorization_endpoint": "https://authorization.sandboxcerner.com/tenants/0d9f8995-8412-40ab-8521-707e6ba80c86/oauth2/authorize",
  "token_endpoint": "https://authorization.sandboxcerner.com/tenants/0d9f8995-8412-40ab-8521-707e6ba80c86/oauth2/token",
  "revocation_endpoint": "https://authorization.sandboxcerner.com/tenants/0d9f8995-8412-40ab-8521-707e6ba80c86/oauth2/revoke",
  "introspection_endpoint": "https://authorization.sandboxcerner.com/tenants/0d9f8995-8412-40ab-8521-707e6ba80c86/oauth2/introspect",
  "response_types_supported": [
    "code",
    "id_token"
  ],
  "grant_types_supported": [
    "authorization_code",
    "client_credentials",
    "refresh_token"
  ],
  "scopes_supported": [
    "openid",
    "profile",
    "email",
    "address",
    "phone",
    "fhirUser",
    "offline_access",
    "online_access",
    "launch/patient",
    "launch/encounter",
    "patient/Patient.read",
    "patient/Patient.search",
    "patient/Observation.read",
    "patient/Observation.search",
    "patient/Condition.read",
    "patient/Condition.search",
    "user/Patient.read"
  ],
  "code_challenge_methods_supported": [
    "S256"
  ]
}
```

**2. Authorization Request**

```
GET https://authorization.sandboxcerner.com/tenants/0d9f8995-8412-40ab-8521-707e6ba80c86/oauth2/authorize
  ?response_type=code
  &client_id=YOUR_CERNER_CLIENT_ID
  &redirect_uri=https%3A%2F%2Fyourapp.com%2Fcallback
  &scope=patient%2FPatient.read%20patient%2FObservation.read%20offline_access%20openid%20fhirUser
  &state=state_value_12345
  &code_challenge=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
  &code_challenge_method=S256
  &aud=https%3A%2F%2Ffhir-ehr.sandboxcerner.com%2Fr4
```

**3. Token Exchange**

```bash
curl -X POST "https://authorization.sandboxcerner.com/tenants/0d9f8995-8412-40ab-8521-707e6ba80c86/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=authorization_code" \
  -d "code=AUTHORIZATION_CODE_HERE" \
  -d "redirect_uri=https://yourapp.com/callback" \
  -d "client_id=YOUR_CERNER_CLIENT_ID" \
  -d "client_secret=YOUR_CERNER_CLIENT_SECRET" \
  -d "code_verifier=ORIGINAL_CODE_VERIFIER"
```

**4. Token Response**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token_expires_in": 604800,
  "scope": "patient/Patient.read patient/Observation.read offline_access openid fhirUser",
  "id_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "patient": "12345678",
  "encounter": "87654321"
}
```

### OpenEMR Authorization Code Flow - Complete Example

**1. Discovery Endpoint**

```bash
curl -X GET "https://openemr.example.com/apis/default/fhir/.well-known/smart-configuration" \
  -H "Accept: application/json"
```

**Response:**
```json
{
  "authorization_endpoint": "https://openemr.example.com/oauth2/default/authorize",
  "token_endpoint": "https://openemr.example.com/oauth2/default/token",
  "token_endpoint_auth_methods_supported": [
    "client_secret_basic",
    "client_secret_post",
    "private_key_jwt"
  ],
  "revocation_endpoint": "https://openemr.example.com/oauth2/default/revoke",
  "introspection_endpoint": "https://openemr.example.com/oauth2/default/introspect",
  "response_types_supported": [
    "code",
    "id_token"
  ],
  "grant_types_supported": [
    "authorization_code",
    "client_credentials",
    "refresh_token",
    "password"
  ],
  "scopes_supported": [
    "openid",
    "fhirUser",
    "profile",
    "email",
    "offline_access",
    "online_access",
    "api:oemr",
    "api:fhir",
    "patient/Patient.read",
    "patient/Patient.rs",
    "patient/Observation.read",
    "patient/Observation.rs",
    "patient/Condition.read",
    "patient/Condition.rs",
    "patient/MedicationRequest.read",
    "patient/MedicationRequest.rs",
    "patient/Encounter.read",
    "patient/Encounter.rs",
    "patient/AllergyIntolerance.read",
    "patient/AllergyIntolerance.rs",
    "patient/Immunization.read",
    "patient/Immunization.rs",
    "patient/DocumentReference.read",
    "patient/DocumentReference.rs",
    "user/Patient.read",
    "system/Patient.rs"
  ],
  "code_challenge_methods_supported": [
    "S256",
    "plain"
  ]
}
```

**2. Authorization Request**

```
GET https://openemr.example.com/oauth2/default/authorize
  ?response_type=code
  &client_id=openemr_client_id
  &redirect_uri=https%3A%2F%2Fyourapp.com%2Fcallback
  &scope=patient%2FPatient.rs%20patient%2FObservation.rs%20patient%2FCondition.rs%20offline_access%20openid
  &state=state_1234567890
  &code_challenge=E9Mrozoa2owUednw8ZG4Q1eRvMJ34G5LP7PEcde7Qg8
  &code_challenge_method=S256
  &aud=https%3A%2F%2Fopenemr.example.com%2Fapis%2Fdefault%2Ffhir
```

**3. Token Exchange**

```bash
curl -X POST "https://openemr.example.com/oauth2/default/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=authorization_code" \
  -d "code=AUTH_CODE_HERE" \
  -d "redirect_uri=https://yourapp.com/callback" \
  -d "client_id=openemr_client_id" \
  -d "client_secret=openemr_client_secret" \
  -d "code_verifier=ORIGINAL_CODE_VERIFIER"
```

**4. Token Response**

```json
{
  "access_token": "eyJhbGciOiJSUzM4NCIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "refresh_token": "0b43cb14eee...a234a6edf68c4d04",
  "refresh_token_expires_in": 2592000,
  "scope": "patient/Patient.rs patient/Observation.rs patient/Condition.rs offline_access openid",
  "id_token": "eyJhbGciOiJSUzM4NCIsInR5cCI6IkpXVCJ9...",
  "patient": "abc123xyz"
}
```

---

## FHIR API Request Examples

### Patient Demographics Request

**Endpoint Pattern:**
```
GET /{fhir_base_url}/Patient/{patient_id}
Authorization: Bearer {access_token}
Accept: application/fhir+json
```

**All EMRs:**

```bash
# Epic
curl -X GET "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/Patient/Zmlo84bIVJVqR0QeQxcZvJ4" \
  -H "Authorization: Bearer eyJhbGciOiJSUzM4NCIs..." \
  -H "Accept: application/fhir+json"

# Cerner
curl -X GET "https://fhir-ehr.sandboxcerner.com/r4/Patient/12345678" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIs..." \
  -H "Accept: application/fhir+json"

# OpenEMR
curl -X GET "https://openemr.example.com/apis/default/fhir/Patient/abc123xyz" \
  -H "Authorization: Bearer eyJhbGciOiJSUzM4NCIs..." \
  -H "Accept: application/fhir+json"
```

**Response (All EMRs Return Same FHIR R4 Format):**

```json
{
  "resourceType": "Patient",
  "id": "12345",
  "meta": {
    "versionId": "1",
    "lastUpdated": "2026-04-05T10:30:00Z"
  },
  "text": {
    "status": "generated",
    "div": "<div xmlns=\"http://www.w3.org/1999/xhtml\">...</div>"
  },
  "identifier": [
    {
      "system": "urn:oid:2.16.840.1.113883.4.3.2",
      "value": "MRN123456"
    },
    {
      "system": "http://example.com/SSN",
      "value": "123-45-6789"
    }
  ],
  "name": [
    {
      "use": "official",
      "family": "Smith",
      "given": [
        "John",
        "Michael"
      ]
    },
    {
      "use": "nickname",
      "given": [
        "Jack"
      ]
    }
  ],
  "telecom": [
    {
      "system": "phone",
      "value": "(617) 555-1234",
      "use": "home"
    },
    {
      "system": "email",
      "value": "john.smith@example.com",
      "use": "work"
    }
  ],
  "gender": "male",
  "birthDate": "1990-01-15",
  "deceasedBoolean": false,
  "address": [
    {
      "use": "home",
      "type": "both",
      "line": [
        "123 Main Street",
        "Apt 4B"
      ],
      "city": "Boston",
      "state": "MA",
      "postalCode": "02101",
      "country": "USA"
    }
  ],
  "contact": [
    {
      "relationship": [
        {
          "coding": [
            {
              "system": "http://terminology.hl7.org/CodeSystem/v2-0131",
              "code": "N",
              "display": "Next-of-Kin"
            }
          ]
        }
      ],
      "name": {
        "use": "official",
        "family": "Smith",
        "given": [
          "Mary"
        ]
      },
      "telecom": [
        {
          "system": "phone",
          "value": "(617) 555-5678"
        }
      ]
    }
  ]
}
```

### Patient Search Request

**Endpoint Pattern:**
```
GET /{fhir_base_url}/Patient?{search_parameters}
Authorization: Bearer {access_token}
Accept: application/fhir+json
```

**Examples:**

```bash
# Search by last name
curl -X GET "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/Patient?family=Smith" \
  -H "Authorization: Bearer eyJhbGciOiJSUzM4NCIs..."

# Search by MRN (medical record number)
curl -X GET "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/Patient?identifier=MRN123456" \
  -H "Authorization: Bearer eyJhbGciOiJSUzM4NCIs..."

# Search by birth date and name
curl -X GET "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/Patient?family=Smith&given=John&birthdate=1990-01-15" \
  -H "Authorization: Bearer eyJhbGciOiJSUzM4NCIs..."

# Search with pagination
curl -X GET "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/Patient?family=Smith&_count=50&_offset=100" \
  -H "Authorization: Bearer eyJhbGciOiJSUzM4NCIs..."
```

**Search Response (Bundle):**

```json
{
  "resourceType": "Bundle",
  "type": "searchset",
  "total": 3,
  "link": [
    {
      "relation": "self",
      "url": "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/Patient?family=Smith"
    },
    {
      "relation": "next",
      "url": "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/Patient?family=Smith&_offset=50"
    }
  ],
  "entry": [
    {
      "fullUrl": "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/Patient/Zmlo84bIVJVqR0QeQxcZvJ4",
      "resource": {
        "resourceType": "Patient",
        "id": "Zmlo84bIVJVqR0QeQxcZvJ4",
        "name": [
          {
            "family": "Smith",
            "given": ["John"]
          }
        ]
      },
      "search": {
        "mode": "match",
        "score": 1.0
      }
    },
    {
      "fullUrl": "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/Patient/Zmlo84bIVJVqR0QeQxcZvL3",
      "resource": {
        "resourceType": "Patient",
        "id": "Zmlo84bIVJVqR0QeQxcZvL3",
        "name": [
          {
            "family": "Smith",
            "given": ["Jane"]
          }
        ]
      },
      "search": {
        "mode": "match",
        "score": 0.9
      }
    }
  ]
}
```

### Conditions (Diagnoses) Request

**Endpoint Pattern:**
```
GET /{fhir_base_url}/Condition?subject=Patient/{patient_id}
Authorization: Bearer {access_token}
Accept: application/fhir+json
```

**Examples:**

```bash
# Get all conditions for a patient
curl -X GET "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/Condition?subject=Patient/Zmlo84bIVJVqR0QeQxcZvJ4" \
  -H "Authorization: Bearer eyJhbGciOiJSUzM4NCIs..."

# Get active conditions only
curl -X GET "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/Condition?subject=Patient/Zmlo84bIVJVqR0QeQxcZvJ4&clinical-status=active" \
  -H "Authorization: Bearer eyJhbGciOiJSUzM4NCIs..."

# Get conditions with specific code (ICD-10)
curl -X GET "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/Condition?subject=Patient/Zmlo84bIVJVqR0QeQxcZvJ4&code=E11" \
  -H "Authorization: Bearer eyJhbGciOiJSUzM4NCIs..."
```

**Response:**

```json
{
  "resourceType": "Bundle",
  "type": "searchset",
  "total": 5,
  "entry": [
    {
      "resource": {
        "resourceType": "Condition",
        "id": "cond-001",
        "meta": {
          "lastUpdated": "2026-03-15T14:30:00Z"
        },
        "clinicalStatus": {
          "coding": [
            {
              "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
              "code": "active",
              "display": "Active"
            }
          ]
        },
        "verificationStatus": {
          "coding": [
            {
              "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
              "code": "confirmed",
              "display": "Confirmed"
            }
          ]
        },
        "category": [
          {
            "coding": [
              {
                "system": "http://terminology.hl7.org/CodeSystem/condition-category",
                "code": "encounter-diagnosis",
                "display": "Encounter Diagnosis"
              }
            ]
          }
        ],
        "code": {
          "coding": [
            {
              "system": "http://hl7.org/fhir/sid/icd-10-cm",
              "code": "E11.22",
              "display": "Type 2 diabetes mellitus with diabetic chronic kidney disease"
            }
          ],
          "text": "Type 2 diabetes mellitus with diabetic chronic kidney disease"
        },
        "subject": {
          "reference": "Patient/Zmlo84bIVJVqR0QeQxcZvJ4"
        },
        "onsetDateTime": "2020-06-15",
        "recordedDate": "2020-06-20T09:00:00Z"
      }
    },
    {
      "resource": {
        "resourceType": "Condition",
        "id": "cond-002",
        "clinicalStatus": {
          "coding": [
            {
              "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
              "code": "active"
            }
          ]
        },
        "code": {
          "coding": [
            {
              "system": "http://hl7.org/fhir/sid/icd-10-cm",
              "code": "I10",
              "display": "Essential (primary) hypertension"
            }
          ]
        },
        "subject": {
          "reference": "Patient/Zmlo84bIVJVqR0QeQxcZvJ4"
        },
        "onsetDateTime": "2015-03-10",
        "recordedDate": "2015-03-15T10:00:00Z"
      }
    }
  ]
}
```

### Observations (Labs, Vitals) Request

**Endpoint Pattern:**
```
GET /{fhir_base_url}/Observation?subject=Patient/{patient_id}&_sort=-date
Authorization: Bearer {access_token}
Accept: application/fhir+json
```

**Examples:**

```bash
# Get all observations
curl -X GET "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/Observation?subject=Patient/Zmlo84bIVJVqR0QeQxcZvJ4&_sort=-date&_count=100" \
  -H "Authorization: Bearer eyJhbGciOiJSUzM4NCIs..."

# Get lab results only
curl -X GET "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/Observation?subject=Patient/Zmlo84bIVJVqR0QeQxcZvJ4&category=laboratory" \
  -H "Authorization: Bearer eyJhbGciOiJSUzM4NCIs..."

# Get vitals
curl -X GET "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/Observation?subject=Patient/Zmlo84bIVJVqR0QeQxcZvJ4&category=vital-signs" \
  -H "Authorization: Bearer eyJhbGciOiJSUzM4NCIs..."

# Get specific lab (HbA1c)
curl -X GET "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/Observation?subject=Patient/Zmlo84bIVJVqR0QeQxcZvJ4&code=4548-4" \
  -H "Authorization: Bearer eyJhbGciOiJSUzM4NCIs..."

# Get observations in date range
curl -X GET "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/Observation?subject=Patient/Zmlo84bIVJVqR0QeQxcZvJ4&date=ge2026-01-01&date=le2026-12-31" \
  -H "Authorization: Bearer eyJhbGciOiJSUzM4NCIs..."
```

**Response:**

```json
{
  "resourceType": "Bundle",
  "type": "searchset",
  "total": 25,
  "entry": [
    {
      "resource": {
        "resourceType": "Observation",
        "id": "obs-001",
        "meta": {
          "lastUpdated": "2026-04-01T10:00:00Z"
        },
        "status": "final",
        "category": [
          {
            "coding": [
              {
                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                "code": "laboratory",
                "display": "Laboratory"
              }
            ]
          }
        ],
        "code": {
          "coding": [
            {
              "system": "http://loinc.org",
              "code": "2345-7",
              "display": "Glucose [Mass/volume] in Serum or Plasma"
            }
          ],
          "text": "Glucose"
        },
        "subject": {
          "reference": "Patient/Zmlo84bIVJVqR0QeQxcZvJ4"
        },
        "effectiveDateTime": "2026-04-01T08:30:00Z",
        "issued": "2026-04-01T10:00:00Z",
        "valueQuantity": {
          "value": 145,
          "unit": "mg/dL",
          "system": "http://unitsofmeasure.org",
          "code": "mg/dL"
        },
        "referenceRange": [
          {
            "low": {
              "value": 70,
              "unit": "mg/dL"
            },
            "high": {
              "value": 100,
              "unit": "mg/dL"
            },
            "text": "70-100 mg/dL"
          }
        ]
      }
    },
    {
      "resource": {
        "resourceType": "Observation",
        "id": "obs-002",
        "status": "final",
        "category": [
          {
            "coding": [
              {
                "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                "code": "vital-signs",
                "display": "Vital Signs"
              }
            ]
          }
        ],
        "code": {
          "coding": [
            {
              "system": "http://loinc.org",
              "code": "55284-4",
              "display": "Blood Pressure"
            }
          ]
        },
        "subject": {
          "reference": "Patient/Zmlo84bIVJVqR0QeQxcZvJ4"
        },
        "effectiveDateTime": "2026-04-01T09:15:00Z",
        "component": [
          {
            "code": {
              "coding": [
                {
                  "system": "http://loinc.org",
                  "code": "8480-6",
                  "display": "Systolic blood pressure"
                }
              ]
            },
            "valueQuantity": {
              "value": 135,
              "unit": "mmHg",
              "system": "http://unitsofmeasure.org",
              "code": "mm[Hg]"
            }
          },
          {
            "code": {
              "coding": [
                {
                  "system": "http://loinc.org",
                  "code": "8462-4",
                  "display": "Diastolic blood pressure"
                }
              ]
            },
            "valueQuantity": {
              "value": 85,
              "unit": "mmHg",
              "system": "http://unitsofmeasure.org",
              "code": "mm[Hg]"
            }
          }
        ]
      }
    }
  ]
}
```

---

## Multi-EMR Discovery Matrix

### Quick Reference: All EMR Discovery Endpoints

| EMR System | FHIR Base URL | Discovery Endpoint | OAuth Token URL |
|------------|---------------|-------------------|-----------------|
| Epic (Public) | `https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4` | `https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/.well-known/smart-configuration` | `https://fhir.epic.com/interconnect-fhir-oauth/oauth2/token` |
| Epic (Sandbox) | `https://fhirprd.epic.com/interconnect-fhir-oauth/api/FHIR/R4` | Append `/.well-known/smart-configuration` | `https://fhirprd.epic.com/interconnect-fhir-oauth/oauth2/token` |
| Cerner (Sandbox) | `https://fhir-ehr.sandboxcerner.com/r4` | `https://fhir-ehr.sandboxcerner.com/r4/.well-known/smart-configuration` | `https://authorization.sandboxcerner.com/tenants/{tenant_id}/oauth2/token` |
| Cerner (Production) | Varies by org | Append `/.well-known/smart-configuration` | Varies by org |
| OpenEMR (Default) | `https://localhost:9300/apis/default/fhir` | `https://localhost:9300/apis/default/fhir/.well-known/smart-configuration` | `https://localhost:9300/oauth2/default/token` |
| OpenEMR (Multisite) | `https://localhost:9300/apis/{site}/fhir` | Append `/.well-known/smart-configuration` | `https://localhost:9300/oauth2/{site}/token` |

### Supported Scopes by EMR

| Scope Category | Epic | Cerner | OpenEMR | Notes |
|---|---|---|---|---|
| `openid` | ✓ | ✓ | ✓ | Always required |
| `fhirUser` | ✓ | ✓ | ✓ | Get current user info |
| `offline_access` | ✓ | ✓ | ✓ | Long-lived refresh token |
| `online_access` | ✓ | ✓ | ✓ | Short-lived session |
| `patient/Patient.read` | ✓ | ✓ | ✓ | Read-only |
| `patient/Patient.rs` | ✓ | ✓ | ✓ | Read+search |
| `patient/Observation.read` | ✓ | ✓ | ✓ | Labs/vitals read-only |
| `patient/Observation.rs` | ✓ | ✓ | ✓ | Labs/vitals read+search |
| `patient/Condition.read` | ✓ | ✓ | ✓ | Diagnoses read-only |
| `patient/Condition.rs` | ✓ | ✓ | ✓ | Diagnoses read+search |
| `patient/Encounter.read` | ✓ | ✓ | ✓ | Visits read-only |
| `patient/Encounter.rs` | ✓ | ✓ | ✓ | Visits read+search |
| `user/Patient.read` | ✓ | ✓ | ✓ | User access to any patient |
| `system/Patient.rs` | ✓ (via Backend Services) | ✓ | ✓ | Backend access, all patients |
| `launch/patient` | ✓ | ✓ | ✗ | EHR-initiated launch |

---

## Error Handling Patterns

### OAuth2 Error Responses

**Invalid Request:**
```json
{
  "error": "invalid_request",
  "error_description": "Missing required parameter: client_id"
}
```

**Invalid Client:**
```json
{
  "error": "invalid_client",
  "error_description": "The client_id is not registered"
}
```

**Invalid Scope:**
```json
{
  "error": "invalid_scope",
  "error_description": "The requested scope is not valid for this client"
}
```

**Unauthorized Client:**
```json
{
  "error": "unauthorized_client",
  "error_description": "The client is not authorized to use the authorization code grant"
}
```

**Invalid Grant:**
```json
{
  "error": "invalid_grant",
  "error_description": "The authorization code has expired or is invalid"
}
```

**Code Expired:**
```json
{
  "error": "invalid_grant",
  "error_description": "Authorization code has expired"
}
```

### FHIR API Error Responses

**401 Unauthorized (Invalid/Expired Token):**
```json
{
  "resourceType": "OperationOutcome",
  "issue": [
    {
      "severity": "error",
      "code": "security",
      "diagnostics": "Invalid token or token has expired"
    }
  ]
}
```

**403 Forbidden (Insufficient Scopes):**
```json
{
  "resourceType": "OperationOutcome",
  "issue": [
    {
      "severity": "error",
      "code": "forbidden",
      "diagnostics": "User does not have permission to access this resource. Required scope: patient/Patient.read"
    }
  ]
}
```

**404 Not Found:**
```json
{
  "resourceType": "OperationOutcome",
  "issue": [
    {
      "severity": "error",
      "code": "not-found",
      "diagnostics": "Patient with id 'xyz' not found"
    }
  ]
}
```

**429 Too Many Requests (Rate Limit):**
```json
{
  "resourceType": "OperationOutcome",
  "issue": [
    {
      "severity": "error",
      "code": "throttled",
      "diagnostics": "Rate limit exceeded. Retry after 60 seconds"
    }
  ]
}
```

**500 Server Error:**
```json
{
  "resourceType": "OperationOutcome",
  "issue": [
    {
      "severity": "error",
      "code": "server-error",
      "diagnostics": "An unexpected server error occurred"
    }
  ]
}
```

### Production Error Handling Code

```javascript
class FHIRErrorHandler {
  handleOAuth2Error(error) {
    const status = error.response?.status;
    const data = error.response?.data;
    
    switch (status) {
      case 400:
        if (data.error === 'invalid_request') {
          return { code: 'INVALID_REQUEST', message: 'Missing required parameter' };
        }
        if (data.error === 'invalid_client') {
          return { code: 'INVALID_CLIENT', message: 'Client not registered with EMR' };
        }
        if (data.error === 'invalid_scope') {
          return { code: 'INVALID_SCOPE', message: 'Requested scopes not authorized' };
        }
        if (data.error === 'invalid_grant') {
          return { code: 'INVALID_GRANT', message: 'Authorization code expired' };
        }
        break;
      case 401:
        return { code: 'UNAUTHORIZED', message: 'Invalid client credentials' };
      case 403:
        return { code: 'FORBIDDEN', message: 'Client not authorized for this grant type' };
      default:
        return { code: 'UNKNOWN_ERROR', message: 'OAuth2 error' };
    }
  }
  
  handleFHIRError(error) {
    const status = error.response?.status;
    const outcome = error.response?.data;
    
    if (status === 401) {
      return {
        code: 'TOKEN_EXPIRED',
        message: 'Access token expired',
        action: 'REFRESH_TOKEN'
      };
    }
    
    if (status === 403) {
      return {
        code: 'INSUFFICIENT_SCOPE',
        message: 'Token does not have required scope',
        action: 'RE_AUTHENTICATE'
      };
    }
    
    if (status === 404) {
      return {
        code: 'RESOURCE_NOT_FOUND',
        message: 'Patient or resource not found',
        action: 'CHECK_PATIENT_ID'
      };
    }
    
    if (status === 429) {
      const retryAfter = error.response?.headers?.['retry-after'] || '60';
      return {
        code: 'RATE_LIMITED',
        message: `Rate limit exceeded`,
        action: 'RETRY',
        retryAfter: parseInt(retryAfter) * 1000
      };
    }
    
    if (status >= 500) {
      return {
        code: 'SERVER_ERROR',
        message: 'EMR server error',
        action: 'RETRY'
      };
    }
    
    return {
      code: 'UNKNOWN_ERROR',
      message: 'FHIR request failed',
      action: 'LOG_AND_ALERT'
    };
  }
  
  async retryWithExponentialBackoff(fn, maxRetries = 3) {
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        return await fn();
      } catch (error) {
        if (attempt === maxRetries) throw error;
        
        const errorInfo = this.handleFHIRError(error);
        
        if (errorInfo.code === 'RATE_LIMITED') {
          await new Promise(resolve => 
            setTimeout(resolve, errorInfo.retryAfter)
          );
        } else if (errorInfo.action === 'RETRY') {
          const delay = Math.pow(2, attempt - 1) * 1000; // 1s, 2s, 4s
          await new Promise(resolve => setTimeout(resolve, delay));
        } else {
          throw error;
        }
      }
    }
  }
}
```

---

## Production Code Snippets

### Complete Patient Data Fetch Service

```javascript
class PatientDataService {
  constructor(tokenService, emrConnectionService, encryption) {
    this.tokenService = tokenService;
    this.emrConnectionService = emrConnectionService;
    this.encryption = encryption;
    this.errorHandler = new FHIRErrorHandler();
  }
  
  /**
   * Fetch complete patient record for RAF/HCC coding
   */
  async getPatientForRAFCoding(tenantId, userId, emrConnectionId, patientId) {
    const connection = await this.emrConnectionService.getConnection(
      emrConnectionId,
      tenantId
    );
    
    const token = await this.tokenService.getAccessToken(
      tenantId,
      userId,
      emrConnectionId
    );
    
    try {
      const [patient, conditions, observations, medications, encounters, allergies] = 
        await Promise.all([
          this.getPatient(connection, token, patientId),
          this.getConditions(connection, token, patientId),
          this.getObservations(connection, token, patientId),
          this.getMedications(connection, token, patientId),
          this.getEncounters(connection, token, patientId),
          this.getAllergies(connection, token, patientId)
        ]);
      
      return {
        patient,
        conditions,
        observations,
        medications,
        encounters,
        allergies,
        metadata: {
          fetchedAt: new Date(),
          emrSystem: connection.emr_system,
          dataQuality: this.assessDataQuality({
            patient, conditions, observations
          })
        }
      };
    } catch (error) {
      const errorInfo = this.errorHandler.handleFHIRError(error);
      
      if (errorInfo.code === 'TOKEN_EXPIRED') {
        await this.tokenService.refreshAccessToken(tenantId, userId, emrConnectionId);
        return this.getPatientForRAFCoding(tenantId, userId, emrConnectionId, patientId);
      }
      
      throw new Error(`Failed to fetch patient data: ${errorInfo.message}`);
    }
  }
  
  async getPatient(connection, token, patientId) {
    const response = await this.errorHandler.retryWithExponentialBackoff(async () => {
      return await axios.get(
        `${connection.fhir_base_url}/Patient/${patientId}`,
        { headers: this.getHeaders(token) }
      );
    });
    
    return response.data;
  }
  
  async getConditions(connection, token, patientId) {
    const response = await this.errorHandler.retryWithExponentialBackoff(async () => {
      return await axios.get(
        `${connection.fhir_base_url}/Condition?subject=Patient/${patientId}&_count=1000`,
        { headers: this.getHeaders(token) }
      );
    });
    
    return response.data.entry?.map(e => e.resource) || [];
  }
  
  async getObservations(connection, token, patientId) {
    const response = await this.errorHandler.retryWithExponentialBackoff(async () => {
      return await axios.get(
        `${connection.fhir_base_url}/Observation?subject=Patient/${patientId}&_sort=-date&_count=1000`,
        { headers: this.getHeaders(token) }
      );
    });
    
    return response.data.entry?.map(e => e.resource) || [];
  }
  
  async getMedications(connection, token, patientId) {
    const response = await this.errorHandler.retryWithExponentialBackoff(async () => {
      return await axios.get(
        `${connection.fhir_base_url}/MedicationRequest?subject=Patient/${patientId}&status=active,intended&_count=1000`,
        { headers: this.getHeaders(token) }
      );
    });
    
    return response.data.entry?.map(e => e.resource) || [];
  }
  
  async getEncounters(connection, token, patientId) {
    const response = await this.errorHandler.retryWithExponentialBackoff(async () => {
      return await axios.get(
        `${connection.fhir_base_url}/Encounter?subject=Patient/${patientId}&_sort=-date&_count=500`,
        { headers: this.getHeaders(token) }
      );
    });
    
    return response.data.entry?.map(e => e.resource) || [];
  }
  
  async getAllergies(connection, token, patientId) {
    const response = await this.errorHandler.retryWithExponentialBackoff(async () => {
      return await axios.get(
        `${connection.fhir_base_url}/AllergyIntolerance?patient=Patient/${patientId}&_count=1000`,
        { headers: this.getHeaders(token) }
      );
    });
    
    return response.data.entry?.map(e => e.resource) || [];
  }
  
  getHeaders(token) {
    return {
      'Authorization': `Bearer ${token}`,
      'Accept': 'application/fhir+json',
      'Content-Type': 'application/fhir+json'
    };
  }
  
  assessDataQuality(data) {
    const { patient, conditions, observations } = data;
    
    const scores = {
      demographics: patient.name && patient.birthDate ? 100 : 50,
      diagnoses: conditions.length > 0 ? Math.min(100, 20 + conditions.length * 10) : 0,
      labResults: observations.length > 0 ? Math.min(100, 20 + observations.length * 5) : 0
    };
    
    const overall = Math.round(
      (scores.demographics + scores.diagnoses + scores.labResults) / 3
    );
    
    return { scores, overall };
  }
}
```

---

## End of Code Examples & API Reference

For implementation, use the complete integration guide in `FHIR_EMR_OAUTH2_PRODUCTION_INTEGRATION.md`.

