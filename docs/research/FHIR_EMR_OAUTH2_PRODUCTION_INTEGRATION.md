# Healthcare SaaS FHIR OAuth2 EMR Integration: Production Implementation Guide

**Date:** April 5, 2026  
**Focus:** Practical production-level implementation details for SMART on FHIR, OAuth2 flows, token management, and multi-tenant architecture.

---

## Table of Contents

1. [SMART on FHIR Authorization Code Flow](#smart-on-fhir-authorization-code-flow)
2. [Backend vs Frontend OAuth2 Implementation](#backend-vs-frontend-oauth2-implementation)
3. [Token Storage and Refresh Management](#token-storage-and-refresh-management)
4. [OpenEMR-Specific OAuth2 Configuration](#openemr-specific-oauth2-configuration)
5. [Multi-Tenant EMR Connections](#multi-tenant-emr-connections)
6. [SMART Backend Services Authentication](#smart-backend-services-authentication)
7. [Production Architecture & Real Examples](#production-architecture--real-examples)
8. [Security Best Practices](#security-best-practices)

---

## SMART on FHIR Authorization Code Flow

### Overview

SMART on FHIR is built on OAuth 2.0 and OpenID Connect. It defines standard authorization flows for third-party applications to securely access FHIR resources from EHRs like Epic, Cerner, and OpenEMR.

### Complete Authorization Code Flow (Frontend Launch)

#### Step 1: Endpoint Discovery via Well-Known Configuration

**Request:**
```
GET /{fhir-base-url}/.well-known/smart-configuration
```

**Example with OpenEMR:**
```
GET https://openemr.example.com/apis/default/fhir/.well-known/smart-configuration
```

**Example with Epic:**
```
GET https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4/.well-known/smart-configuration
```

**Response (JSON):**
```json
{
  "authorization_endpoint": "https://openemr.example.com/oauth2/default/authorize",
  "token_endpoint": "https://openemr.example.com/oauth2/default/token",
  "token_endpoint_auth_methods_supported": [
    "client_secret_basic",
    "client_secret_post",
    "private_key_jwt"
  ],
  "token_endpoint_auth_signing_alg_values_supported": [
    "RS384",
    "ES384"
  ],
  "revocation_endpoint": "https://openemr.example.com/oauth2/default/revoke",
  "introspection_endpoint": "https://openemr.example.com/oauth2/default/introspect",
  "scopes_supported": [
    "openid",
    "fhirUser",
    "offline_access",
    "online_access",
    "api:oemr",
    "api:fhir",
    "patient/Patient.read",
    "patient/Patient.rs",
    "patient/Observation.read",
    "user/Patient.read"
  ],
  "response_types_supported": [
    "code",
    "id_token"
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

#### Step 2: User Initiates Authorization Request

Your application redirects the user's browser to the EHR's authorization endpoint with PKCE parameters.

**Request:**
```
GET {authorization_endpoint}
  ?response_type=code
  &client_id=YOUR_CLIENT_ID
  &redirect_uri=https://yourapp.com/callback
  &scope=patient/Patient.rs%20patient/Observation.rs%20offline_access%20openid
  &state=A_RANDOM_UNIQUE_VALUE_AT_LEAST_122_BITS
  &code_challenge=E9Mrozoa2owUednw8ZG4Q1eRvMJ34G5LP7PEcde7Qg8
  &code_challenge_method=S256
  &aud=https://openemr.example.com/apis/default/fhir
```

**Key Parameters:**

| Parameter | Purpose | Notes |
|-----------|---------|-------|
| `response_type` | Request authorization code | Always "code" |
| `client_id` | Identifies your app | Pre-registered with EHR |
| `redirect_uri` | Where to send user after auth | Must be HTTPS, pre-registered |
| `scope` | Requested permissions | Space-separated, see table below |
| `state` | CSRF protection | Random, 43+ chars, ≥122 bits entropy |
| `code_challenge` | PKCE hash | SHA256(code_verifier) base64url-encoded |
| `code_challenge_method` | PKCE method | Use "S256" (SHA256), not "plain" |
| `aud` | Authorization audience | FHIR server base URL |
| `launch` | For EHR-initiated launch | Optional, echoes value from EHR |

**PKCE Code Verifier Generation (Node.js example):**
```javascript
const crypto = require('crypto');

// Generate random code verifier (43-128 chars)
const codeVerifier = crypto
  .randomBytes(32)
  .toString('base64')
  .replace(/\+/g, '-')
  .replace(/\//g, '_')
  .replace(/=/g, '');

// Create challenge (S256 method: SHA256 + base64url)
const codeChallenge = crypto
  .createHash('sha256')
  .update(codeVerifier)
  .digest('base64')
  .replace(/\+/g, '-')
  .replace(/\//g, '_')
  .replace(/=/g, '');

console.log('Code Verifier:', codeVerifier);
console.log('Code Challenge:', codeChallenge);
```

**Scopes Explained:**

| Scope | Level | Type | Purpose |
|-------|-------|------|---------|
| `openid` | Identity | OpenID | Enable OpenID Connect (required) |
| `fhirUser` | Identity | OpenID | Get authenticated user info |
| `offline_access` | Session | OAuth | Long-lived refresh token |
| `online_access` | Session | OAuth | Short-lived, user must be active |
| `api:fhir` | API | SMART | Access FHIR resources |
| `api:oemr` | API | OpenEMR | Access OpenEMR REST API |
| `patient/Patient.read` | Patient | SMART | Read patient demographics |
| `patient/Patient.rs` | Patient | SMART | Read+search patient |
| `patient/Observation.read` | Patient | SMART | Read observations (lab, vitals) |
| `user/Patient.read` | User | SMART | User access to patients |

#### Step 3: User Authenticates with EHR

The EHR displays login screen. User enters credentials. EHR validates and asks for consent.

#### Step 4: EHR Redirects to Your App with Authorization Code

**Response (URL redirect):**
```
https://yourapp.com/callback
  ?code=OIDC_AUTH_CODE_HERE
  &state=A_RANDOM_UNIQUE_VALUE_AT_LEAST_122_BITS
  &patient=12345
```

**Your app MUST validate:**
1. `state` parameter matches request state (CSRF protection)
2. `code` is present and non-empty
3. Extract `patient` context if present

#### Step 5: Backend Exchanges Code for Access Token

Your **backend server** (not frontend) makes this request to avoid exposing credentials:

**Request:**
```
POST {token_endpoint}
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&code=OIDC_AUTH_CODE_HERE
&redirect_uri=https://yourapp.com/callback
&client_id=YOUR_CLIENT_ID
&client_secret=YOUR_CLIENT_SECRET
&code_verifier=ORIGINAL_CODE_VERIFIER_STRING
```

**cURL Example:**
```bash
curl -X POST https://openemr.example.com/oauth2/default/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=authorization_code" \
  -d "code=OIDC_AUTH_CODE_HERE" \
  -d "redirect_uri=https://yourapp.com/callback" \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET" \
  -d "code_verifier=ORIGINAL_CODE_VERIFIER_STRING"
```

**Response (JSON):**
```json
{
  "access_token": "eyJhbGciOiJSUzM4NCIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "refresh_token": "0b43cb14eee...a234a6edf68c4d04",
  "refresh_token_expires_in": 2592000,
  "scope": "patient/Patient.rs patient/Observation.rs offline_access openid",
  "id_token": "eyJhbGciOiJSUzM4NCIsInR5cCI6IkpXVCJ9...",
  "patient": "12345"
}
```

**Token Response Fields:**

| Field | Type | Lifetime | Purpose |
|-------|------|----------|---------|
| `access_token` | JWT | 1 hour (3600s) | Bearer token for API calls |
| `token_type` | String | N/A | Always "Bearer" |
| `expires_in` | Integer | Seconds | When access token expires |
| `refresh_token` | String | 30 days typical | Get new access token |
| `refresh_token_expires_in` | Integer | Seconds | When refresh token expires |
| `scope` | String | Granted scopes | Authorized permissions |
| `id_token` | JWT | Same as access token | OpenID user info |
| `patient` | String | Launch context | Patient ID from EHR |

#### Step 6: Use Access Token to Query FHIR Resources

**Request:**
```
GET https://openemr.example.com/apis/default/fhir/Patient/12345
Authorization: Bearer eyJhbGciOiJSUzM4NCIsInR5cCI6IkpXVCJ9...
Accept: application/fhir+json
```

**Response (FHIR Patient Resource):**
```json
{
  "resourceType": "Patient",
  "id": "12345",
  "meta": {
    "versionId": "1",
    "lastUpdated": "2026-04-05T10:30:00Z"
  },
  "identifier": [
    {
      "system": "http://hospital.example.com/mrn",
      "value": "MRN123456"
    }
  ],
  "name": [
    {
      "use": "official",
      "family": "Smith",
      "given": ["John"]
    }
  ],
  "birthDate": "1990-01-15",
  "gender": "male",
  "address": [
    {
      "line": ["123 Main St"],
      "city": "Boston",
      "state": "MA",
      "postalCode": "02101"
    }
  ]
}
```

---

## Backend vs Frontend OAuth2 Implementation

### Pattern 1: Backend for Frontend (BFF) - Recommended for Production

**Architecture:**
```
┌──────────────────────┐
│   Frontend Web App   │
│   (SPA/React)        │
└──────────┬───────────┘
           │ /auth/login (no credentials)
           │
┌──────────▼───────────────────────────────────┐
│         Backend for Frontend (BFF)            │
│  - Handles OAuth2 authorization code flow     │
│  - Stores refresh token in secure session    │
│  - Returns access token to frontend in       │
│    httpOnly cookie or session                │
│  - Refreshes tokens automatically            │
└──────────┬────────────────────────────────────┘
           │ /oauth2/authorize (redirect)
           │
┌──────────▼───────────────────┐
│   EHR OAuth2 Server           │
│   (Epic/Cerner/OpenEMR)       │
└────────────────────────────────┘
```

**Why BFF is Best:**

1. **Token Security:** Refresh tokens stay on backend, never reach browser
2. **CSRF Protection:** Backend manages state parameter
3. **Automatic Refresh:** Backend refreshes tokens before expiration
4. **Session Management:** Backend controls session lifecycle
5. **Compliance:** Easier to audit token usage and access

**BFF Implementation (Node.js + Express):**

```javascript
const express = require('express');
const session = require('express-session');
const axios = require('axios');
const crypto = require('crypto');

const app = express();

// Session store (use Redis in production, not memory)
app.use(session({
  secret: process.env.SESSION_SECRET,
  resave: false,
  saveUninitialized: false,
  cookie: {
    secure: true,           // HTTPS only
    httpOnly: true,         // No JavaScript access
    sameSite: 'Strict',     // CSRF protection
    maxAge: 1000 * 60 * 60  // 1 hour
  }
}));

// Step 1: Frontend calls /auth/login - BFF initiates OAuth flow
app.get('/auth/login', (req, res) => {
  // Generate PKCE
  const codeVerifier = crypto
    .randomBytes(32)
    .toString('base64')
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
  
  const codeChallenge = crypto
    .createHash('sha256')
    .update(codeVerifier)
    .digest('base64')
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
  
  const state = crypto.randomBytes(32).toString('hex');
  
  // Store in session for validation later
  req.session.codeVerifier = codeVerifier;
  req.session.state = state;
  req.session.save(() => {
    // Redirect user to EHR's authorization endpoint
    const authUrl = `https://openemr.example.com/oauth2/default/authorize?` +
      `response_type=code` +
      `&client_id=${process.env.FHIR_CLIENT_ID}` +
      `&redirect_uri=${encodeURIComponent(process.env.REDIRECT_URI)}` +
      `&scope=${encodeURIComponent('patient/Patient.rs patient/Observation.rs offline_access openid')}` +
      `&state=${state}` +
      `&code_challenge=${codeChallenge}` +
      `&code_challenge_method=S256` +
      `&aud=${encodeURIComponent('https://openemr.example.com/apis/default/fhir')}`;
    
    res.redirect(authUrl);
  });
});

// Step 2: EHR redirects here with authorization code
app.get('/auth/callback', async (req, res) => {
  const { code, state } = req.query;
  
  // Validate state (CSRF protection)
  if (state !== req.session.state) {
    return res.status(400).send('Invalid state parameter');
  }
  
  try {
    // Exchange code for tokens
    const tokenResponse = await axios.post(
      'https://openemr.example.com/oauth2/default/token',
      {
        grant_type: 'authorization_code',
        code,
        redirect_uri: process.env.REDIRECT_URI,
        client_id: process.env.FHIR_CLIENT_ID,
        client_secret: process.env.FHIR_CLIENT_SECRET,
        code_verifier: req.session.codeVerifier
      },
      { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } }
    );
    
    // Store tokens in session (encrypted in production)
    req.session.accessToken = tokenResponse.data.access_token;
    req.session.refreshToken = tokenResponse.data.refresh_token;
    req.session.expiresAt = Date.now() + tokenResponse.data.expires_in * 1000;
    req.session.patientId = tokenResponse.data.patient;
    
    req.session.save(() => {
      // Redirect to frontend app
      res.redirect('https://yourapp.com/dashboard');
    });
  } catch (error) {
    console.error('Token exchange failed:', error.response?.data);
    res.status(500).send('Authentication failed');
  }
});

// Step 3: Frontend API calls go through BFF
app.get('/api/fhir/patient/:id', async (req, res) => {
  let accessToken = req.session.accessToken;
  
  // Auto-refresh if expired
  if (Date.now() >= req.session.expiresAt - 60000) { // 1 min buffer
    try {
      const refreshResponse = await axios.post(
        'https://openemr.example.com/oauth2/default/token',
        {
          grant_type: 'refresh_token',
          refresh_token: req.session.refreshToken,
          client_id: process.env.FHIR_CLIENT_ID,
          client_secret: process.env.FHIR_CLIENT_SECRET
        }
      );
      
      req.session.accessToken = refreshResponse.data.access_token;
      req.session.expiresAt = Date.now() + refreshResponse.data.expires_in * 1000;
      accessToken = refreshResponse.data.access_token;
    } catch (error) {
      return res.status(401).send('Session expired, please login again');
    }
  }
  
  // Query FHIR with current access token
  try {
    const fhirResponse = await axios.get(
      `https://openemr.example.com/apis/default/fhir/Patient/${req.params.id}`,
      {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Accept': 'application/fhir+json'
        }
      }
    );
    
    res.json(fhirResponse.data);
  } catch (error) {
    console.error('FHIR request failed:', error.response?.data);
    res.status(error.response?.status || 500).json(error.response?.data || {});
  }
});

// Step 4: Logout
app.post('/auth/logout', async (req, res) => {
  try {
    // Revoke refresh token
    await axios.post(
      'https://openemr.example.com/oauth2/default/revoke',
      {
        token: req.session.refreshToken,
        client_id: process.env.FHIR_CLIENT_ID,
        client_secret: process.env.FHIR_CLIENT_SECRET
      }
    );
  } catch (error) {
    console.error('Token revocation failed:', error.message);
  }
  
  req.session.destroy();
  res.send('Logged out');
});

app.listen(3001, () => console.log('BFF listening on port 3001'));
```

### Pattern 2: Frontend SPA (Not Recommended for Healthcare)

```
┌──────────────────────────┐
│   Frontend Web App       │
│   (SPA/React/Vue)        │
│   - Has access token     │
│   - Sends API requests   │
└──────────┬───────────────┘
           │
┌──────────▼──────────────────┐
│   EHR OAuth2 Server         │
│   (Epic/Cerner/OpenEMR)     │
└─────────────────────────────┘
```

**Problems in Healthcare:**

1. Refresh tokens exposed in browser (XSS risk)
2. Difficult to secure token refresh
3. Audit trail unclear
4. Session management complex
5. Higher compliance risk

**Only use if:**
- No sensitive data (public health info)
- Using Authorization Code Flow with PKCE
- Have robust XSS protection
- Short-lived access tokens only

---

## Token Storage and Refresh Management

### Backend Token Storage

**Database Schema (PostgreSQL):**

```sql
CREATE TABLE oauth_tokens (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  user_id UUID NOT NULL REFERENCES users(id),
  
  -- Token values (encrypted at rest)
  access_token_encrypted TEXT NOT NULL,
  refresh_token_encrypted TEXT NOT NULL,
  
  -- Metadata
  access_token_expires_at TIMESTAMP NOT NULL,
  refresh_token_expires_at TIMESTAMP,
  issued_at TIMESTAMP NOT NULL DEFAULT NOW(),
  
  -- EMR context
  emr_system VARCHAR(50) NOT NULL, -- 'epic', 'cerner', 'openemr', etc.
  emr_instance_id VARCHAR(255) NOT NULL, -- Which Epic org, which Cerner instance
  fhir_base_url TEXT NOT NULL,
  
  -- Patient context
  patient_id VARCHAR(255), -- EMR patient ID
  patient_mrn VARCHAR(255),
  
  -- Scopes and context
  scopes TEXT NOT NULL, -- Space-separated scopes
  id_token_encrypted TEXT, -- For OpenID Connect
  
  -- Audit
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  last_used_at TIMESTAMP,
  revoked_at TIMESTAMP,
  
  -- Indexes
  UNIQUE(tenant_id, user_id, emr_instance_id),
  INDEX(tenant_id, user_id),
  INDEX(emr_instance_id),
  INDEX(refresh_token_expires_at)
);

-- Encryption key stored in environment variable
-- All sensitive fields encrypted with AES-256-GCM
```

**Token Encryption (Node.js):**

```javascript
const crypto = require('crypto');

class TokenEncryption {
  constructor(encryptionKey) {
    // Key should be 32 bytes for AES-256
    this.key = Buffer.from(encryptionKey, 'hex');
  }
  
  encrypt(plaintext) {
    const iv = crypto.randomBytes(16);
    const cipher = crypto.createCipheriv('aes-256-gcm', this.key, iv);
    
    let encrypted = cipher.update(plaintext, 'utf8', 'hex');
    encrypted += cipher.final('hex');
    
    const authTag = cipher.getAuthTag();
    
    // Return: iv + authTag + ciphertext (all hex)
    return `${iv.toString('hex')}:${authTag.toString('hex')}:${encrypted}`;
  }
  
  decrypt(encrypted) {
    const [ivHex, authTagHex, ciphertext] = encrypted.split(':');
    const iv = Buffer.from(ivHex, 'hex');
    const authTag = Buffer.from(authTagHex, 'hex');
    
    const decipher = crypto.createDecipheriv('aes-256-gcm', this.key, iv);
    decipher.setAuthTag(authTag);
    
    let decrypted = decipher.update(ciphertext, 'hex', 'utf8');
    decrypted += decipher.final('utf8');
    
    return decrypted;
  }
}

// Usage
const encryption = new TokenEncryption(process.env.TOKEN_ENCRYPTION_KEY);
const encrypted = encryption.encrypt('eyJhbGciOiJSUzM4NC...');
const decrypted = encryption.decrypt(encrypted);
```

### Automatic Token Refresh Strategy

**Proactive Refresh (Recommended):**

```javascript
class TokenManager {
  constructor(db, encryption) {
    this.db = db;
    this.encryption = encryption;
  }
  
  async getValidAccessToken(userId, tenantId, emrInstanceId) {
    // Fetch token from DB
    const record = await this.db.query(
      `SELECT * FROM oauth_tokens 
       WHERE user_id = $1 AND tenant_id = $2 AND emr_instance_id = $3 
       AND revoked_at IS NULL`,
      [userId, tenantId, emrInstanceId]
    );
    
    if (!record) {
      throw new Error('No token found for this user/EMR');
    }
    
    const decrypted = this.encryption.decrypt(record.access_token_encrypted);
    
    // Check if expired or expiring soon (1 min buffer)
    const expiresAt = new Date(record.access_token_expires_at);
    const bufferTime = new Date(Date.now() + 60000); // 1 min
    
    if (expiresAt <= bufferTime) {
      // Refresh token before expiration
      const newTokens = await this.refreshAccessToken(
        userId,
        tenantId,
        record
      );
      return newTokens.access_token;
    }
    
    return decrypted;
  }
  
  async refreshAccessToken(userId, tenantId, record) {
    const refreshToken = this.encryption.decrypt(
      record.refresh_token_encrypted
    );
    
    try {
      // Call EMR token endpoint
      const response = await axios.post(
        `${record.fhir_base_url.replace(/\/fhir.*/, '')}/oauth2/default/token`,
        {
          grant_type: 'refresh_token',
          refresh_token: refreshToken,
          client_id: process.env.FHIR_CLIENT_ID,
          client_secret: process.env.FHIR_CLIENT_SECRET
        }
      );
      
      // Update DB with new tokens
      const now = Date.now();
      const newAccessExpires = new Date(now + response.data.expires_in * 1000);
      const newRefreshExpires = response.data.refresh_token_expires_in
        ? new Date(now + response.data.refresh_token_expires_in * 1000)
        : null;
      
      await this.db.query(
        `UPDATE oauth_tokens 
         SET access_token_encrypted = $1,
             access_token_expires_at = $2,
             refresh_token_encrypted = $3,
             refresh_token_expires_at = $4,
             updated_at = NOW(),
             last_used_at = NOW()
         WHERE id = $5`,
        [
          this.encryption.encrypt(response.data.access_token),
          newAccessExpires,
          this.encryption.encrypt(response.data.refresh_token),
          newRefreshExpires,
          record.id
        ]
      );
      
      return response.data;
    } catch (error) {
      if (error.response?.status === 401) {
        // Refresh token expired, user must re-authenticate
        await this.db.query(
          `UPDATE oauth_tokens SET revoked_at = NOW() WHERE id = $1`,
          [record.id]
        );
        throw new Error('Session expired. Please login again.');
      }
      throw error;
    }
  }
}
```

### Refresh Token Expiration & Revocation

**Lifetime Policies:**

| Token Type | Typical Lifetime | Use Case |
|------------|-----------------|----------|
| Access Token | 1 hour | API requests |
| Refresh Token (online) | 1 day | User actively using system |
| Refresh Token (offline) | 7-30 days | Background/scheduled jobs |
| ID Token | Same as access token | User identity verification |

**Token Revocation (Logout):**

```javascript
app.post('/auth/logout', async (req, res) => {
  const { userId, tenantId } = req.user;
  
  // Get all tokens for this user
  const tokens = await db.query(
    `SELECT * FROM oauth_tokens 
     WHERE user_id = $1 AND tenant_id = $2 AND revoked_at IS NULL`,
    [userId, tenantId]
  );
  
  // Revoke at EMR level
  for (const token of tokens) {
    try {
      const refreshToken = encryption.decrypt(token.refresh_token_encrypted);
      await axios.post(
        `${token.fhir_base_url.replace(/\/fhir.*/, '')}/oauth2/default/revoke`,
        {
          token: refreshToken,
          client_id: process.env.FHIR_CLIENT_ID,
          client_secret: process.env.FHIR_CLIENT_SECRET
        }
      );
    } catch (error) {
      console.error(`Failed to revoke token for ${token.emr_instance_id}:`, error.message);
      // Continue with database revocation even if EMR call fails
    }
    
    // Revoke in local database
    await db.query(
      `UPDATE oauth_tokens SET revoked_at = NOW() WHERE id = $1`,
      [token.id]
    );
  }
  
  res.json({ success: true, message: 'Logged out from all EMRs' });
});
```

---

## OpenEMR-Specific OAuth2 Configuration

### OpenEMR OAuth2 Endpoints

**Base Pattern:**
```
https://{openemr-host}/oauth2/{site}/
```

**Default Site:**
```
https://localhost:9300/oauth2/default/
```

**Multisite Installation:**
```
https://localhost:9300/oauth2/alternate-site-name/
```

### Key Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/.well-known/smart-configuration` | GET | Discover OAuth endpoints and capabilities |
| `/authorize` | GET | User authentication and authorization |
| `/token` | POST | Exchange code for tokens |
| `/introspect` | POST | Check if token is valid (RFC 7662) |
| `/revoke` | POST | Revoke a token |
| `/userinfo` | GET | Get authenticated user info (OpenID) |

### OpenEMR FHIR API Base URL

**Format:**
```
https://{openemr-host}/apis/{site}/fhir
```

**Default site:**
```
https://localhost:9300/apis/default/fhir
```

### Supported Scopes in OpenEMR

**OpenID Connect Scopes:**
- `openid` - Required for all flows
- `fhirUser` - Get current user claims
- `profile` - Get user profile info
- `email` - Get user email

**Session Scopes:**
- `offline_access` - Long-lived refresh token (30 days)
- `online_access` - Short-lived refresh token (1 day)

**API Scopes:**
- `api:oemr` - OpenEMR REST API access
- `api:fhir` - FHIR REST API access

**Resource Scopes (FHIR):**
- `patient/Patient.read` - Read patient demographics
- `patient/Patient.rs` - Read+search patient
- `patient/Observation.read` - Read observations
- `patient/Observation.rs` - Read+search observations
- `patient/Condition.read`, `patient/Condition.rs`
- `patient/MedicationRequest.read`, `patient/MedicationRequest.rs`
- `patient/Encounter.read`, `patient/Encounter.rs`
- `patient/AllergyIntolerance.read`, `patient/AllergyIntolerance.rs`
- `patient/Immunization.read`, `patient/Immunization.rs`
- `patient/DocumentReference.read`, `patient/DocumentReference.rs`
- `user/Patient.read` - User can access any patient
- `system/Patient.rs` - Backend services can access all patients

### Grant Types OpenEMR Supports

**1. Authorization Code (Recommended for user-facing apps)**
```
grant_type=authorization_code
```

**2. Client Credentials (For backend/system apps)**
```
grant_type=client_credentials
```

**3. Refresh Token**
```
grant_type=refresh_token
```

**4. Password (Not recommended for production)**
```
grant_type=password
```

### OpenEMR Client Registration

**Admin Portal:**
1. Navigate to: Administration → Config → Connectors
2. Enable "OpenEMR Standard FHIR REST API"
3. Click "Register API Client"

**Programmatic Registration (if enabled):**
```bash
curl -X POST https://openemr.example.com/oauth2/default/client_registration \
  -H "Content-Type: application/json" \
  -d '{
    "client_name": "My FHIR App",
    "redirect_uris": ["https://yourapp.com/callback"],
    "token_endpoint_auth_method": "client_secret_basic",
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "scope": "openid offline_access api:fhir patient/Patient.rs patient/Observation.rs"
  }'
```

---

## Multi-Tenant EMR Connections

### Architecture Overview

A SaaS platform typically manages connections to multiple customer EMR instances.

```
┌─────────────────────────────────────────────────────────┐
│             SaaS Application (Your Platform)             │
│  - RAF/HCC Coding  - Data Analytics - Population Health │
└─────────────────────────────────────────────────────────┘
           │                │                │
           │                │                │
    ┌──────▼───┐    ┌──────▼───┐    ┌──────▼───┐
    │  Epic     │    │ Cerner   │    │ OpenEMR  │
    │ Customer  │    │ Customer │    │ Customer │
    │ Instance  │    │ Instance │    │ Instance │
    │ (Epic #1) │    │(Cerner#2)│    │(OpenEMR#3)
    └───────────┘    └──────────┘    └──────────┘
```

### Multi-Tenant Data Model

**Database Schema:**

```sql
CREATE TABLE tenants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name VARCHAR(255) NOT NULL,
  slug VARCHAR(100) UNIQUE NOT NULL,
  status VARCHAR(50), -- 'active', 'suspended'
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE emr_connections (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  
  -- EMR Type and Instance
  emr_system VARCHAR(50) NOT NULL, -- 'epic', 'cerner', 'openemr'
  instance_name VARCHAR(255), -- Friendly name: "Boston Medical Center Epic"
  instance_identifier VARCHAR(255) UNIQUE, -- Technical ID
  
  -- Connection URLs
  fhir_base_url TEXT NOT NULL,
  oauth_base_url TEXT NOT NULL,
  
  -- OAuth2 Client Credentials
  client_id VARCHAR(255) NOT NULL,
  client_secret_encrypted TEXT NOT NULL,
  client_secret_algorithm VARCHAR(50), -- encryption algorithm used
  
  -- Connection Status
  status VARCHAR(50), -- 'active', 'testing', 'error', 'expired'
  last_sync_at TIMESTAMP,
  last_error TEXT,
  error_count INTEGER DEFAULT 0,
  
  -- Connection Metadata
  api_version VARCHAR(50), -- 'STU3', 'R4'
  connection_type VARCHAR(50), -- 'oauth', 'basic_auth', 'api_key'
  
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  
  UNIQUE(tenant_id, emr_system, instance_identifier),
  INDEX(tenant_id),
  INDEX(status)
);

CREATE TABLE oauth_tokens (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  emr_connection_id UUID NOT NULL REFERENCES emr_connections(id) ON DELETE CASCADE,
  
  -- User association
  user_id UUID REFERENCES users(id), -- NULL for system/service tokens
  user_email VARCHAR(255),
  
  -- Token Storage (AES-256 encrypted)
  access_token_encrypted TEXT NOT NULL,
  refresh_token_encrypted TEXT,
  id_token_encrypted TEXT,
  
  -- Expiration
  access_token_expires_at TIMESTAMP NOT NULL,
  refresh_token_expires_at TIMESTAMP,
  
  -- OAuth Metadata
  scopes TEXT NOT NULL,
  token_type VARCHAR(50), -- 'Bearer', etc.
  issued_at TIMESTAMP DEFAULT NOW(),
  
  -- Usage Tracking
  last_used_at TIMESTAMP,
  used_count INTEGER DEFAULT 0,
  
  -- Audit
  created_at TIMESTAMP DEFAULT NOW(),
  updated_at TIMESTAMP DEFAULT NOW(),
  revoked_at TIMESTAMP,
  revoked_reason VARCHAR(255),
  
  -- Context
  patient_id VARCHAR(255), -- If user-specific
  patient_mrn VARCHAR(255),
  
  UNIQUE(tenant_id, user_id, emr_connection_id),
  INDEX(tenant_id),
  INDEX(emr_connection_id),
  INDEX(refresh_token_expires_at),
  INDEX(revoked_at)
);
```

### Managing Tokens Per EMR Instance

**Token Lookup Service:**

```javascript
class EMRTokenService {
  constructor(db, encryption) {
    this.db = db;
    this.encryption = encryption;
  }
  
  /**
   * Get valid access token for a specific EMR instance
   * Automatically refreshes if needed
   */
  async getAccessToken(tenantId, userId, emrConnectionId) {
    // Fetch token record
    const token = await this.db.query(
      `SELECT t.*, e.oauth_base_url, e.client_id, e.client_secret_encrypted
       FROM oauth_tokens t
       JOIN emr_connections e ON t.emr_connection_id = e.id
       WHERE t.tenant_id = $1 
       AND t.user_id = $2 
       AND t.emr_connection_id = $3
       AND t.revoked_at IS NULL
       AND e.status = 'active'`,
      [tenantId, userId, emrConnectionId]
    );
    
    if (!token) {
      throw new Error('No valid token for this EMR connection');
    }
    
    const accessToken = this.encryption.decrypt(token.access_token_encrypted);
    const expiresAt = new Date(token.access_token_expires_at);
    const bufferTime = new Date(Date.now() + 60000); // 1 min
    
    if (expiresAt <= bufferTime) {
      return await this.refreshToken(token);
    }
    
    // Update last_used_at
    await this.db.query(
      `UPDATE oauth_tokens 
       SET last_used_at = NOW(), used_count = used_count + 1
       WHERE id = $1`,
      [token.id]
    );
    
    return accessToken;
  }
  
  /**
   * Refresh a token using stored refresh token
   */
  async refreshToken(tokenRecord) {
    const refreshToken = this.encryption.decrypt(
      tokenRecord.refresh_token_encrypted
    );
    const clientSecret = this.encryption.decrypt(
      tokenRecord.client_secret_encrypted
    );
    
    try {
      const response = await axios.post(
        `${tokenRecord.oauth_base_url}/token`,
        {
          grant_type: 'refresh_token',
          refresh_token: refreshToken,
          client_id: tokenRecord.client_id,
          client_secret: clientSecret
        }
      );
      
      // Update token in DB
      await this.db.query(
        `UPDATE oauth_tokens 
         SET access_token_encrypted = $1,
             access_token_expires_at = $2,
             refresh_token_encrypted = $3,
             refresh_token_expires_at = $4,
             updated_at = NOW(),
             last_used_at = NOW()
         WHERE id = $5`,
        [
          this.encryption.encrypt(response.data.access_token),
          new Date(Date.now() + response.data.expires_in * 1000),
          this.encryption.encrypt(response.data.refresh_token),
          response.data.refresh_token_expires_in
            ? new Date(Date.now() + response.data.refresh_token_expires_in * 1000)
            : null,
          tokenRecord.id
        ]
      );
      
      return response.data.access_token;
    } catch (error) {
      if (error.response?.status === 401) {
        // Refresh token expired
        await this.db.query(
          `UPDATE oauth_tokens 
           SET revoked_at = NOW(), 
               revoked_reason = 'Refresh token expired'
           WHERE id = $1`,
          [tokenRecord.id]
        );
        throw new Error('Session expired. User must re-authenticate.');
      }
      throw error;
    }
  }
  
  /**
   * Get all EMR connections for a tenant
   */
  async getConnectionsForTenant(tenantId) {
    return await this.db.query(
      `SELECT id, emr_system, instance_name, status, last_sync_at 
       FROM emr_connections 
       WHERE tenant_id = $1 
       ORDER BY emr_system, instance_name`,
      [tenantId]
    );
  }
}
```

### Cross-Tenant Security

**Critical: Prevent Token Leakage Between Tenants**

```javascript
// Middleware to enforce tenant isolation
const tenantAuthMiddleware = async (req, res, next) => {
  const { tenantId, userId } = req.user;
  const { emrConnectionId } = req.params;
  
  // Verify EMR connection belongs to user's tenant
  const connection = await db.query(
    `SELECT id FROM emr_connections 
     WHERE id = $1 AND tenant_id = $2`,
    [emrConnectionId, tenantId]
  );
  
  if (!connection) {
    return res.status(403).json({ error: 'Unauthorized access' });
  }
  
  next();
};

// FHIR proxy endpoint
app.get('/fhir/:emrConnectionId/Patient/:patientId', 
  tenantAuthMiddleware, 
  async (req, res) => {
    const { tenantId, userId } = req.user;
    const { emrConnectionId, patientId } = req.params;
    
    const tokenService = new EMRTokenService(db, encryption);
    
    try {
      // Get valid access token for this EMR
      const accessToken = await tokenService.getAccessToken(
        tenantId, 
        userId, 
        emrConnectionId
      );
      
      // Get connection details
      const connection = await db.query(
        `SELECT fhir_base_url FROM emr_connections WHERE id = $1`,
        [emrConnectionId]
      );
      
      // Make FHIR request
      const fhirResponse = await axios.get(
        `${connection.fhir_base_url}/Patient/${patientId}`,
        {
          headers: {
            'Authorization': `Bearer ${accessToken}`,
            'Accept': 'application/fhir+json'
          }
        }
      );
      
      res.json(fhirResponse.data);
    } catch (error) {
      if (error.message.includes('Session expired')) {
        return res.status(401).json({ error: 'Please re-authenticate with your EMR' });
      }
      res.status(500).json({ error: 'FHIR request failed' });
    }
  }
);
```

---

## SMART Backend Services Authentication

### JWT-Based Server-to-Server Authentication

SMART Backend Services (also called "Backend OAuth 2.0") allows backend systems to authenticate without user involvement using asymmetric cryptography.

**Use Cases:**
- Batch data exports
- Scheduled jobs
- Background synchronization
- Service-to-service APIs

### Complete Backend Services Flow

#### Step 1: Asymmetric Key Generation

**Generate RSA-4096 keypair (in production setup):**

```bash
# Generate private key (keep secure)
openssl genrsa -out private_key.pem 4096

# Extract public key
openssl rsa -in private_key.pem -pubout -out public_key.pem

# Convert to JWK format for registration with EMR
openssl rsa -in private_key.pem -pubout -outform PEM | \
  python3 -c "
import json, sys, base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

pem = sys.stdin.read()
public_key = serialization.load_pem_public_key(
    pem.encode(), backend=default_backend()
)
numbers = public_key.public_numbers()

n = numbers.n
e = numbers.e

# Convert to base64url
n_bytes = n.to_bytes((n.bit_length() + 7) // 8, 'big')
e_bytes = e.to_bytes((e.bit_length() + 7) // 8, 'big')

n_b64 = base64.urlsafe_b64encode(n_bytes).decode().rstrip('=')
e_b64 = base64.urlsafe_b64encode(e_bytes).decode().rstrip('=')

jwk = {
    'kty': 'RSA',
    'kid': 'my-key-id-1',
    'use': 'sig',
    'alg': 'RS384',
    'n': n_b64,
    'e': e_b64
}

print(json.dumps(jwk, indent=2))
  "
```

#### Step 2: Register Public Key with EMR

**OpenEMR Client Registration with JWK:**

```bash
curl -X POST https://openemr.example.com/oauth2/default/client_registration \
  -H "Content-Type: application/json" \
  -d '{
    "client_name": "RAF HCC Batch Processor",
    "token_endpoint_auth_method": "private_key_jwt",
    "jwks_uri": "https://yourapp.com/.well-known/jwks.json",
    "grant_types": ["client_credentials"],
    "scope": "system/Patient.rs system/Observation.rs system/Condition.rs"
  }'
```

Or upload JWK directly:

```bash
curl -X POST https://openemr.example.com/oauth2/default/client_registration \
  -H "Content-Type: application/json" \
  -d '{
    "client_name": "RAF HCC Batch Processor",
    "token_endpoint_auth_method": "private_key_jwt",
    "jwks": {
      "keys": [
        {
          "kty": "RSA",
          "kid": "my-key-id-1",
          "use": "sig",
          "alg": "RS384",
          "n": "xGOr-H7A...",
          "e": "AQAB"
        }
      ]
    },
    "grant_types": ["client_credentials"],
    "scope": "system/Patient.rs system/Observation.rs"
  }'
```

**Response:**
```json
{
  "client_id": "7b4a8f6c-e8d2-4a4b-9e5f-3c1b8e7a4d2f",
  "client_name": "RAF HCC Batch Processor",
  "grant_types": ["client_credentials"],
  "scope": "system/Patient.rs system/Observation.rs system/Condition.rs"
}
```

#### Step 3: Generate JWT Assertion

**JWT Header:**
```json
{
  "alg": "RS384",
  "kid": "my-key-id-1",
  "typ": "JWT",
  "jku": "https://yourapp.com/.well-known/jwks.json"
}
```

**JWT Payload (Claims):**
```json
{
  "iss": "7b4a8f6c-e8d2-4a4b-9e5f-3c1b8e7a4d2f",
  "sub": "7b4a8f6c-e8d2-4a4b-9e5f-3c1b8e7a4d2f",
  "aud": "https://openemr.example.com/oauth2/default/token",
  "exp": 1712288100,
  "iat": 1712287800,
  "jti": "unique-nonce-12345"
}
```

**JWT Generation (Node.js):**

```javascript
const jwt = require('jsonwebtoken');
const fs = require('fs');

const privateKey = fs.readFileSync('./private_key.pem', 'utf8');

const payload = {
  iss: '7b4a8f6c-e8d2-4a4b-9e5f-3c1b8e7a4d2f', // client_id
  sub: '7b4a8f6c-e8d2-4a4b-9e5f-3c1b8e7a4d2f',
  aud: 'https://openemr.example.com/oauth2/default/token',
  exp: Math.floor(Date.now() / 1000) + 300, // 5 min expiration
  iat: Math.floor(Date.now() / 1000),
  jti: crypto.randomUUID() // Unique ID to prevent replay
};

const assertion = jwt.sign(payload, privateKey, {
  algorithm: 'RS384',
  keyid: 'my-key-id-1'
});

console.log('JWT Assertion:', assertion);
```

#### Step 4: Exchange JWT for Access Token

**Request:**
```
POST https://openemr.example.com/oauth2/default/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials
&client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer
&client_assertion={SIGNED_JWT}
&scope=system/Patient.rs%20system/Observation.rs
```

**cURL Example:**
```bash
curl -X POST https://openemr.example.com/oauth2/default/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials" \
  -d "client_assertion_type=urn:ietf:params:oauth:client-assertion-type:jwt-bearer" \
  -d "client_assertion=${JWT_ASSERTION}" \
  -d "scope=system/Patient.rs system/Observation.rs"
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJSUzM4NCIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 60,
  "scope": "system/Patient.rs system/Observation.rs"
}
```

**Important:** Backend Services tokens are **short-lived** (60-300 seconds), require new JWT generation for each request, and are NOT refreshable.

#### Step 5: Use Token for Batch Operations

```javascript
class BackendServicesClient {
  constructor(clientId, privateKey, emrTokenUrl, fhirBaseUrl) {
    this.clientId = clientId;
    this.privateKey = privateKey;
    this.emrTokenUrl = emrTokenUrl;
    this.fhirBaseUrl = fhirBaseUrl;
    this.accessToken = null;
    this.tokenExpiresAt = 0;
  }
  
  async getAccessToken() {
    // Reuse token if still valid
    if (this.accessToken && Date.now() < this.tokenExpiresAt - 10000) {
      return this.accessToken;
    }
    
    // Generate new JWT assertion
    const assertion = jwt.sign(
      {
        iss: this.clientId,
        sub: this.clientId,
        aud: this.emrTokenUrl,
        exp: Math.floor(Date.now() / 1000) + 300,
        iat: Math.floor(Date.now() / 1000),
        jti: crypto.randomUUID()
      },
      this.privateKey,
      { algorithm: 'RS384', keyid: 'my-key-id-1' }
    );
    
    // Exchange JWT for access token
    const response = await axios.post(
      this.emrTokenUrl,
      {
        grant_type: 'client_credentials',
        client_assertion_type: 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
        client_assertion: assertion,
        scope: 'system/Patient.rs system/Observation.rs system/Condition.rs'
      }
    );
    
    this.accessToken = response.data.access_token;
    this.tokenExpiresAt = Date.now() + response.data.expires_in * 1000;
    
    return this.accessToken;
  }
  
  /**
   * Batch export all patients' observations
   */
  async exportObservations(patientIds) {
    const accessToken = await this.getAccessToken();
    const observations = [];
    
    for (const patientId of patientIds) {
      const response = await axios.get(
        `${this.fhirBaseUrl}/Observation?subject=Patient/${patientId}`,
        {
          headers: {
            'Authorization': `Bearer ${accessToken}`,
            'Accept': 'application/fhir+json'
          }
        }
      );
      
      if (response.data.entry) {
        observations.push(...response.data.entry.map(e => e.resource));
      }
    }
    
    return observations;
  }
  
  /**
   * Search all patients (system-level)
   */
  async getAllPatients(lastUpdated) {
    const accessToken = await this.getAccessToken();
    
    const response = await axios.get(
      `${this.fhirBaseUrl}/Patient?_lastUpdated=ge${lastUpdated}`,
      {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Accept': 'application/fhir+json'
        }
      }
    );
    
    return response.data;
  }
}

// Usage
const backend = new BackendServicesClient(
  '7b4a8f6c-e8d2-4a4b-9e5f-3c1b8e7a4d2f',
  fs.readFileSync('./private_key.pem', 'utf8'),
  'https://openemr.example.com/oauth2/default/token',
  'https://openemr.example.com/apis/default/fhir'
);

const observations = await backend.exportObservations(['123', '456', '789']);
```

---

## Production Architecture & Real Examples

### Architecture Pattern: Innovaccer/Arcadia Model

Healthcare data platforms like Innovaccer and Arcadia use a **hub-and-spoke** architecture:

```
┌──────────────────────────────────────────────────────────────────┐
│                   SaaS Application (Your Platform)                │
│  Unified Data Layer (GraphQL/REST)                                │
│  - Normalizes data from all EMRs into single schema               │
│  - Handles patient deduplication                                  │
│  - Manages access control per tenant                              │
└──────────────────────────────────────────────────────────────────┘
           │                    │                    │
           │ FHIR API Calls     │ FHIR API Calls     │ FHIR API Calls
           │
    ┌──────▼─────────────────────────────────────────────────────┐
    │         EMR Integration Layer (API Adapters)                │
    │  - Handles OAuth2 for each EMR type                         │
    │  - Manages token lifecycle                                  │
    │  - Translates EMR-specific formats to FHIR                  │
    │  - Error handling & retry logic                             │
    │  - Rate limiting per EMR                                    │
    └──────┬──────────────────────────────────────────────────────┘
           │
      ┌────┴──────┬──────────┬──────────┐
      │            │          │          │
    Epic      Cerner    OpenEMR    Other
```

### Example: RAF/HCC Integration Platform

**Technical Stack:**
- Backend: Node.js, Express, PostgreSQL
- Frontend: React, Apollo Client
- FHIR Server: HAPI FHIR or Firely
- EMR Integration: Direct FHIR API calls

**Key Components:**

```
┌─────────────────────────────────────────────────────┐
│              RAF/HCC Platform                        │
│                                                       │
│  ┌──────────────────────────────────────────────┐  │
│  │  Frontend (React)                             │  │
│  │  - Patient search                             │  │
│  │  - Code assignment                            │  │
│  │  - HCC mapping visualization                  │  │
│  └──────────────────────────────────────────────┘  │
│                    ▲                                 │
│                    │ REST/GraphQL                    │
│                    │                                 │
│  ┌──────────────────────────────────────────────┐  │
│  │  Backend API (Node.js)                        │  │
│  │  - Token management                           │  │
│  │  - Patient deduplication                      │  │
│  │  - HCC algorithm & scoring                    │  │
│  │  - Access control                             │  │
│  └──────────────────────────────────────────────┘  │
│                    ▲                                 │
│                    │ OAuth2 + FHIR                   │
│                    │                                 │
│  ┌──────────────────────────────────────────────┐  │
│  │  EMR Integration Service                      │  │
│  │  - OAuth2 flows (auth code, backend svcs)    │  │
│  │  - Token storage & refresh                    │  │
│  │  - FHIR resource translation                  │  │
│  │  - Batch sync jobs                            │  │
│  │  - Audit logging                              │  │
│  └──────────────────────────────────────────────┘  │
│                    ▲                                 │
│                    │ FHIR                            │
└────────────────────┼──────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
        ▼            ▼            ▼
      Epic        Cerner      OpenEMR
```

### Real-World Example: FHIR API Call Flow for RAF Coding

**Scenario:** User selects patient in RAF platform, needs to retrieve clinical data for HCC coding.

```javascript
// 1. Frontend requests patient data
// GET /api/patients/12345
//   - Includes tenant_id in JWT
//   - Includes emr_connection_id

// 2. Backend route handler
app.get('/api/patients/:patientId', async (req, res) => {
  const { tenantId, userId } = req.user;
  const { patientId } = req.params;
  const { emrConnectionId } = req.query;
  
  // 3. Get EMR connection details
  const emrConnection = await db.query(
    `SELECT * FROM emr_connections 
     WHERE id = $1 AND tenant_id = $2 AND status = 'active'`,
    [emrConnectionId, tenantId]
  );
  
  const tokenService = new EMRTokenService(db, encryption);
  
  // 4. Get valid access token (auto-refresh if needed)
  const accessToken = await tokenService.getAccessToken(
    tenantId,
    userId,
    emrConnectionId
  );
  
  try {
    // 5. Fetch patient demographics
    const [patientRes, observationsRes, conditionsRes] = await Promise.all([
      axios.get(
        `${emrConnection.fhir_base_url}/Patient/${patientId}`,
        {
          headers: {
            'Authorization': `Bearer ${accessToken}`,
            'Accept': 'application/fhir+json'
          }
        }
      ),
      
      // 6. Fetch observations (labs, vitals)
      axios.get(
        `${emrConnection.fhir_base_url}/Observation?subject=Patient/${patientId}&_count=100`,
        {
          headers: {
            'Authorization': `Bearer ${accessToken}`,
            'Accept': 'application/fhir+json'
          }
        }
      ),
      
      // 7. Fetch conditions (diagnoses)
      axios.get(
        `${emrConnection.fhir_base_url}/Condition?subject=Patient/${patientId}&_count=100`,
        {
          headers: {
            'Authorization': `Bearer ${accessToken}`,
            'Accept': 'application/fhir+json'
          }
        }
      )
    ]);
    
    // 8. Transform FHIR to internal format for HCC analysis
    const patientData = {
      demographics: transformPatient(patientRes.data),
      observations: transformObservations(observationsRes.data),
      conditions: transformConditions(conditionsRes.data),
      metadata: {
        emrSystem: emrConnection.emr_system,
        lastSync: new Date(),
        totalHCCs: 0 // Will be calculated
      }
    };
    
    // 9. Return to frontend
    res.json(patientData);
    
  } catch (error) {
    if (error.response?.status === 401) {
      return res.status(401).json({ error: 'EMR session expired' });
    }
    res.status(500).json({ error: 'Failed to fetch patient data' });
  }
});

function transformPatient(fhirPatient) {
  return {
    id: fhirPatient.id,
    firstName: fhirPatient.name?.[0]?.given?.[0],
    lastName: fhirPatient.name?.[0]?.family,
    dob: fhirPatient.birthDate,
    gender: fhirPatient.gender,
    mrn: fhirPatient.identifier?.[0]?.value
  };
}

function transformObservations(fhirBundle) {
  const observations = [];
  
  fhirBundle.entry?.forEach(entry => {
    const obs = entry.resource;
    observations.push({
      type: obs.code?.coding?.[0]?.display,
      value: obs.valueQuantity?.value,
      unit: obs.valueQuantity?.unit,
      date: obs.effectiveDateTime,
      status: obs.status
    });
  });
  
  return observations;
}

function transformConditions(fhirBundle) {
  const conditions = [];
  
  fhirBundle.entry?.forEach(entry => {
    const cond = entry.resource;
    conditions.push({
      code: cond.code?.coding?.[0]?.code,
      description: cond.code?.coding?.[0]?.display,
      status: cond.clinicalStatus?.coding?.[0]?.code,
      recordedDate: cond.recordedDate,
      hccCode: mapICD10ToHCC(cond.code?.coding?.[0]?.code)
    });
  });
  
  return conditions;
}
```

---

## Security Best Practices

### 1. Token Transport Security

**ALWAYS:**
- Use HTTPS/TLS 1.2+ for all OAuth2 requests
- Verify SSL certificates (don't disable in production)
- Use secure WebSocket (WSS) for real-time data

**Example:**
```javascript
const axios = require('axios');
const https = require('https');

const httpsAgent = new https.Agent({
  rejectUnauthorized: true, // Verify SSL
  minVersion: 'TLSv1.2'
});

const response = await axios.get(fhirUrl, {
  httpsAgent
});
```

### 2. Token Storage Rules

**DO:**
- Store refresh tokens in encrypted database
- Use AES-256-GCM encryption
- Use environment variables for encryption keys
- Implement access logging for token retrieval

**DON'T:**
- Store tokens in browser localStorage
- Log tokens in application logs
- Send tokens in URLs (query parameters)
- Store unencrypted in database

### 3. Scope Minimization

Always request minimum scopes needed:

```javascript
// Good - specific scopes
scope: 'patient/Patient.rs patient/Observation.rs'

// Bad - overly broad
scope: 'api:fhir'  // Too much access

// Better for backend services
scope: 'system/Patient.rs system/Condition.rs'  // Not user-scoped
```

### 4. PKCE is Mandatory

```javascript
// Always use S256, never "plain"
code_challenge_method: 'S256'

// Code verifier: 43-128 characters
const codeVerifier = crypto.randomBytes(32).toString('base64url');
```

### 5. State Parameter Validation

```javascript
// Generate secure state (≥122 bits entropy)
const state = crypto.randomBytes(16).toString('hex'); // 128 bits

// Always validate on callback
if (callbackState !== sessionState) {
  throw new Error('CSRF attack detected');
}
```

### 6. JWT Claims Validation

When receiving tokens from EMR:

```javascript
const jwt = require('jsonwebtoken');
const fs = require('fs');

// Get EMR's public key (from JWKS endpoint)
const emrPublicKey = await fetchEMRPublicKey();

const decoded = jwt.verify(accessToken, emrPublicKey, {
  algorithms: ['RS384'],
  issuer: expectedIssuer,
  audience: expectedAudience
});
```

### 7. Token Rotation

Implement automatic refresh:

```javascript
// Refresh token 5 minutes before expiration
const REFRESH_BUFFER_MS = 5 * 60 * 1000;

if (Date.now() >= tokenExpiry - REFRESH_BUFFER_MS) {
  await refreshAccessToken();
}
```

### 8. Audit Logging

```javascript
class AuditLog {
  async logTokenAccess(tenantId, userId, emrInstanceId, action) {
    await db.query(
      `INSERT INTO audit_logs 
       (tenant_id, user_id, emr_instance_id, action, ip_address, user_agent, timestamp)
       VALUES ($1, $2, $3, $4, $5, $6, NOW())`,
      [tenantId, userId, emrInstanceId, action, req.ip, req.get('user-agent')]
    );
  }
}

// Log every token use
await auditLog.logTokenAccess(tenantId, userId, emrInstanceId, 'token_used');
```

### 9. Revocation on Logout

```javascript
app.post('/logout', async (req, res) => {
  const { tenantId, userId } = req.user;
  
  // Get all active tokens
  const tokens = await db.query(
    `SELECT * FROM oauth_tokens 
     WHERE tenant_id = $1 AND user_id = $2 AND revoked_at IS NULL`
  );
  
  // Revoke at EMR
  for (const token of tokens) {
    await axios.post(
      `${token.oauth_base_url}/revoke`,
      {
        token: encryption.decrypt(token.refresh_token_encrypted),
        client_id: process.env.FHIR_CLIENT_ID,
        client_secret: process.env.FHIR_CLIENT_SECRET
      }
    ).catch(err => console.error('Revocation failed:', err));
  }
  
  // Mark as revoked locally
  await db.query(
    `UPDATE oauth_tokens 
     SET revoked_at = NOW() 
     WHERE tenant_id = $1 AND user_id = $2`,
    [tenantId, userId]
  );
  
  res.json({ success: true });
});
```

### 10. Error Handling

Never leak sensitive information in errors:

```javascript
// Bad
res.status(500).json({ 
  error: 'Invalid token: eyJhbGciOi...'
});

// Good
res.status(401).json({ 
  error: 'Authentication failed. Please login again.' 
});

console.error('Token validation failed:', error);  // Log internals
res.status(401).send('Unauthorized');               // Generic to client
```

---

## Summary: Complete Integration Checklist

### Pre-Integration
- [ ] Register OAuth2 client with each EMR
- [ ] Obtain client_id and client_secret
- [ ] Generate RSA keypair for Backend Services (if needed)
- [ ] Get FHIR base URL for each EMR
- [ ] Configure redirect URIs

### Authorization Code Flow (User-Facing)
- [ ] Implement `.well-known/smart-configuration` discovery
- [ ] Generate PKCE code_challenge and code_verifier
- [ ] Generate secure state parameter
- [ ] Redirect user to EMR authorization endpoint
- [ ] Handle callback with authorization code
- [ ] Exchange code for tokens on backend
- [ ] Store tokens encrypted in database
- [ ] Implement automatic token refresh
- [ ] Use Bearer token in FHIR API requests

### Backend Services (System/Batch)
- [ ] Register client with JWT authentication
- [ ] Store private key securely
- [ ] Implement JWT assertion generation
- [ ] Exchange JWT for short-lived access tokens
- [ ] Re-generate JWT for each request

### Multi-Tenant Architecture
- [ ] Isolate tokens by tenant and EMR instance
- [ ] Enforce tenant checks in middleware
- [ ] Implement per-tenant token discovery
- [ ] Support multiple EMR connections per tenant
- [ ] Log all token access per tenant

### Security
- [ ] Use HTTPS/TLS 1.2+ everywhere
- [ ] Encrypt tokens at rest (AES-256-GCM)
- [ ] Use environment variables for secrets
- [ ] Implement PKCE with S256
- [ ] Validate state parameter
- [ ] Implement token revocation on logout
- [ ] Log audit trail of token access
- [ ] Set appropriate token expiration times
- [ ] Monitor for token expiration errors
- [ ] Implement error handling without leaking tokens

---

## Key References

- [SMART on FHIR App Launch v2.2.0](https://build.fhir.org/ig/HL7/smart-app-launch/app-launch.html)
- [SMART Backend Services](https://build.fhir.org/ig/HL7/smart-app-launch/backend-services.html)
- [OpenEMR FHIR API Documentation](https://github.com/openemr/openemr/blob/master/Documentation/api/FHIR_API.md)
- [OAuth 2.0 Token Introspection (RFC 7662)](https://datatracker.ietf.org/doc/html/rfc7662)
- [PKCE (RFC 7636)](https://datatracker.ietf.org/doc/html/rfc7636)
- [Best Practices in Authorization for SMART on FHIR](https://docs.smarthealthit.org/authorization/best-practices/)
- [Epic on FHIR Documentation](https://fhir.epic.com/)
- [SMART Token Introspection](https://hl7.org/fhir/uv/bulkdata/STU1.0.1/authorization/index.html)

