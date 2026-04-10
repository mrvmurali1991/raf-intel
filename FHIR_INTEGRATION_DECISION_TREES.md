# FHIR EMR Integration: Decision Trees & Production Patterns

**Date:** April 5, 2026

---

## Quick Decision Trees

### Decision 1: Which OAuth2 Flow Should I Use?

```
START: "I need to integrate with an EMR via FHIR"
  │
  ├─ Will users authenticate interactively?
  │  │
  │  ├─ YES: Need user login via EMR
  │  │  └─ Use: AUTHORIZATION CODE FLOW
  │  │     └─ With PKCE (always)
  │  │     └─ Backend for Frontend pattern
  │  │     └─ Store refresh token encrypted on backend
  │  │
  │  └─ NO: Backend/system service
  │     │
  │     ├─ Do I have a pre-existing session/context?
  │     │  │
  │     │  ├─ YES: User exists, app is running as that user
  │     │  │  └─ Use: AUTHORIZATION CODE FLOW
  │     │  │     └─ Get tokens from user's session
  │     │  │
  │     │  └─ NO: Background job, scheduled sync, no user
  │     │     └─ Use: BACKEND SERVICES (Client Credentials)
  │     │        └─ With JWT assertion
  │     │        └─ System-level scopes
  │     │        └─ Generate new JWT per request
  │     │        └─ Accept short-lived tokens (60-300s)

END
```

### Decision 2: Where Should I Store Tokens?

```
START: "I have OAuth2 tokens"
  │
  ├─ Is this a web application?
  │  │
  │  ├─ YES: Is backend present? (API server)
  │  │  │
  │  │  ├─ YES:
  │  │  │  └─ Store refresh token in: ENCRYPTED DATABASE
  │  │  │     ├─ Use AES-256-GCM encryption
  │  │  │     ├─ Key in environment variable
  │  │  │     ├─ Access tokens in memory/session (short-lived)
  │  │  │     └─ Frontend gets tokens via httpOnly cookies
  │  │  │
  │  │  └─ NO: Pure frontend SPA
  │  │     └─ Store in: MEMORY ONLY
  │  │        ├─ Never use localStorage
  │  │        ├─ Never use sessionStorage
  │  │        ├─ Lost on page refresh (acceptable)
  │  │        └─ Better: Implement backend-for-frontend
  │  │
  │  └─ NO: Mobile app?
  │     └─ Store in: SECURE ENCLAVE
  │        ├─ iOS Keychain
  │        ├─ Android Keystore
  │        └─ Never in SharedPreferences/UserDefaults
  │
  └─ NOT A WEB/MOBILE: Backend service?
     └─ Store in: SECURE FILE + MEMORY CACHE
        ├─ Read from encrypted file at startup
        ├─ Cache in memory with access protection
        └─ Update file when tokens are refreshed

END
```

### Decision 3: Single vs Multi-Tenant Architecture

```
START: "I'm building a SaaS platform"
  │
  ├─ Will ONE tenant connect to ONE EMR?
  │  │
  │  ├─ YES (Simple case):
  │  │  └─ Simpler architecture possible
  │  │     ├─ Store connection details once
  │  │     ├─ Standard token management
  │  │     └─ Less complex access control
  │  │
  │  └─ NO: Multi-connection needed
  │     │
  │     ├─ Each tenant connects to multiple EMRs?
  │     │  │
  │     │  ├─ YES:
  │     │  │  └─ MULTI-TENANT ARCHITECTURE REQUIRED
  │     │  │     ├─ Database tables:
  │     │  │     │  ├─ tenants
  │     │  │     │  ├─ emr_connections (1-N per tenant)
  │     │  │     │  └─ oauth_tokens (M-N per connection)
  │     │  │     ├─ Enforce tenant isolation in all queries
  │     │  │     ├─ Token lookup by (tenant, user, emr_connection)
  │     │  │     └─ Audit all token access by tenant
  │     │  │
  │     │  └─ NO: Single EMR per tenant
  │     │     └─ SIMPLIFIED MULTI-TENANT
  │     │        ├─ Database tables:
  │     │        │  ├─ tenants
  │     │        │  ├─ oauth_tokens (1-1 per tenant)
  │     │        │  └─ connection_metadata
  │     │        └─ Simpler query patterns
  │
  └─ How many concurrent users per tenant?
     │
     ├─ <100: Sessions can be in-memory
     │
     ├─ 100-10K: Use Redis for session storage
     │
     └─ >10K: Use database, implement caching layer

END
```

### Decision 4: Token Refresh Strategy

```
START: "I have an access token"
  │
  ├─ Do I know when it expires?
  │  │
  │  ├─ YES:
  │  │  └─ PROACTIVE REFRESH (Recommended)
  │  │     ├─ Check on every API call:
  │  │     │  ├─ If expires_at - now < BUFFER (5-10 min)
  │  │     │  └─ Refresh token before use
  │  │     ├─ Prevents 401 errors in production
  │  │     └─ Clean user experience
  │  │
  │  └─ NO: Expires_in unknown
  │     └─ REACTIVE REFRESH
  │        ├─ Try API call
  │        ├─ On 401: Refresh token
  │        ├─ Retry API call
  │        └─ If refresh fails: Re-authenticate user
  │
  ├─ How are tokens refreshed?
  │  │
  │  ├─ Short-lived tokens (1 hour)?
  │  │  └─ Refresh every 50 minutes
  │  │     └─ User barely notices
  │  │
  │  └─ Long-lived tokens (7+ days)?
  │     └─ Refresh when < 1 day remaining
  │        └─ Or daily background job
  │
  └─ What if refresh fails?
     │
     ├─ 401 Unauthorized:
     │  └─ Refresh token invalid/expired
     │     └─ User must re-authenticate
     │        └─ Redirect to login
     │
     ├─ 500 Server Error:
     │  └─ EMR temporarily down
     │     └─ Retry with exponential backoff
     │     └─ Max 3 retries with 1s, 2s, 4s delays
     │
     └─ Network Error:
        └─ Connection issue
           └─ Retry with exponential backoff
           └─ Keep existing token valid

END
```

### Decision 5: Handling Multiple EMR Systems

```
START: "I support Epic, Cerner, and OpenEMR"
  │
  ├─ Build unified adapter layer?
  │  │
  │  ├─ YES (Recommended):
  │  │  └─ ADAPTER PATTERN
  │  │     ├─ Abstract FHIR interface
  │  │     ├─ Concrete implementations per EMR
  │  │     ├─ Code once, works with all EMRs
  │  │     └─ Handles EMR-specific quirks:
  │  │        ├─ Epic: special scopes, auth nuances
  │  │        ├─ Cerner: pagination differences
  │  │        └─ OpenEMR: self-hosted considerations
  │  │
  │  └─ NO: Direct integration per EMR
  │     └─ More code to maintain
  │        └─ Harder to add new EMRs
  │        └─ Inconsistent error handling
  │
  ├─ How do I discover EMR types?
  │  │
  │  ├─ Use well-known endpoint
  │  │  └─ Check issuer in token response
  │  │  └─ Or store emr_system in connection metadata
  │  │
  │  └─ Detect via OAuth response fields
  │     └─ Epic: specific scopes
  │     └─ Cerner: tenant_id format
  │     └─ OpenEMR: response structure
  │
  └─ How do I handle EMR-specific quirks?
     │
     ├─ Example: Scope differences
     │  └─ Create EMR-specific scope tables
     │     └─ Map from generic → EMR-specific
     │
     ├─ Example: Search parameter differences
     │  └─ Create abstract query builder
     │     └─ Translate to EMR dialect
     │
     └─ Example: Error message differences
        └─ Normalize to standard error codes
           └─ Log original error for debugging

END
```

---

## Production Patterns

### Pattern 1: Backend for Frontend (BFF)

**When to use:** Always, for web applications with users

**Architecture:**
```
┌──────────────────────────────────┐
│   Frontend (React/Vue/SPA)       │
│   - No secrets stored             │
│   - No direct EMR calls           │
│   - Calls BFF via REST API        │
└──────────┬───────────────────────┘
           │ HTTP (no FHIR directly)
           │
┌──────────▼───────────────────────┐
│   Backend for Frontend (BFF)       │
│   - Handles OAuth2 flow           │
│   - Manages refresh tokens        │
│   - Calls EMR FHIR APIs           │
│   - Normalizes data formats       │
│   - Enforces access control       │
└──────────┬───────────────────────┘
           │ HTTPS + Bearer Token
           │
┌──────────▼───────────────────────┐
│   EMR FHIR Server                 │
│   (Epic, Cerner, OpenEMR, etc)    │
└───────────────────────────────────┘
```

**Benefits:**
- Tokens never reach frontend
- CSRF protection via state
- Automatic refresh logic centralized
- Audit trail clear
- Session management simple

**Implementation:**
```javascript
// BFF Server
const express = require('express');
const app = express();

app.get('/api/*', async (req, res) => {
  // 1. Get user from session
  const { tenantId, userId } = req.user;
  
  // 2. Get valid token (auto-refresh)
  const token = await getValidToken(userId, tenantId);
  
  // 3. Call EMR FHIR
  const emrResponse = await callEMRFHIR(token, req.path);
  
  // 4. Return to frontend
  res.json(emrResponse);
});
```

### Pattern 2: Token Rotation & Refresh

**Proactive Refresh (Recommended):**

```javascript
class TokenRefreshService {
  private REFRESH_BUFFER_MS = 5 * 60 * 1000; // 5 minutes
  
  async ensureValidToken(tokenRecord) {
    const now = Date.now();
    const expiresAt = new Date(tokenRecord.access_token_expires_at).getTime();
    
    // If expires in < 5 minutes, refresh now
    if (expiresAt - now < this.REFRESH_BUFFER_MS) {
      return await this.refreshToken(tokenRecord);
    }
    
    return tokenRecord.access_token;
  }
  
  private async refreshToken(tokenRecord) {
    const refreshToken = decrypt(tokenRecord.refresh_token_encrypted);
    
    try {
      const response = await axios.post(tokenRecord.oauth_base_url + '/token', {
        grant_type: 'refresh_token',
        refresh_token: refreshToken,
        client_id: FHIR_CLIENT_ID,
        client_secret: FHIR_CLIENT_SECRET
      });
      
      // Update database
      await updateTokenInDB(tokenRecord.id, response.data);
      
      // Log refresh
      await auditLog('token_refreshed', tokenRecord.user_id);
      
      return response.data.access_token;
    } catch (error) {
      if (error.status === 401) {
        // Refresh token expired
        await markTokenRevoked(tokenRecord.id, 'refresh_token_expired');
        throw new Error('Session expired. Please login again.');
      }
      throw error;
    }
  }
}
```

### Pattern 3: Multi-Tenant Token Isolation

**Enforce security at every level:**

```javascript
// Database query with tenant isolation
async function getUserTokens(userId, tenantId) {
  const tokens = await db.query(
    `SELECT * FROM oauth_tokens 
     WHERE user_id = $1 
     AND tenant_id = $2 
     AND revoked_at IS NULL`,
    [userId, tenantId]
  );
  
  return tokens;
}

// Middleware to verify tenant access
app.use((req, res, next) => {
  const userTenantId = req.user.tenantId;
  const requestedTenantId = req.params.tenantId;
  
  if (userTenantId !== requestedTenantId) {
    return res.status(403).json({ error: 'Access denied' });
  }
  
  next();
});

// FHIR API endpoint with tenant check
app.get('/api/fhir/:emrConnectionId/Patient/:patientId', async (req, res) => {
  const { tenantId, userId } = req.user;
  const { emrConnectionId, patientId } = req.params;
  
  // Verify EMR connection belongs to tenant
  const connection = await db.query(
    `SELECT * FROM emr_connections 
     WHERE id = $1 AND tenant_id = $2`,
    [emrConnectionId, tenantId]
  );
  
  if (!connection) {
    return res.status(403).json({ error: 'Unauthorized access' });
  }
  
  // Get token for this specific connection
  const token = await getTokenForConnection(userId, tenantId, emrConnectionId);
  
  // Call FHIR
  const patient = await axios.get(
    `${connection.fhir_base_url}/Patient/${patientId}`,
    { headers: { 'Authorization': `Bearer ${token}` } }
  );
  
  res.json(patient.data);
});
```

### Pattern 4: Automatic Error Recovery

```javascript
class FHIRClientWithRetry {
  async callWithRetry(fn, maxRetries = 3) {
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        return await fn();
      } catch (error) {
        const errorType = this.classifyError(error);
        
        // Unrecoverable errors
        if (errorType === 'INVALID_SCOPE' || errorType === 'INVALID_CLIENT') {
          throw error; // Don't retry
        }
        
        // Token expired - refresh and retry
        if (errorType === 'TOKEN_EXPIRED') {
          await this.refreshToken();
          continue;
        }
        
        // Rate limited - backoff and retry
        if (errorType === 'RATE_LIMIT') {
          const waitMs = error.response.headers['retry-after'] * 1000 || 60000;
          await new Promise(r => setTimeout(r, waitMs));
          continue;
        }
        
        // Server errors - exponential backoff
        if (errorType === 'SERVER_ERROR' && attempt < maxRetries) {
          const delayMs = Math.pow(2, attempt - 1) * 1000;
          await new Promise(r => setTimeout(r, delayMs));
          continue;
        }
        
        // Final retry failed
        if (attempt === maxRetries) {
          throw error;
        }
      }
    }
  }
  
  classifyError(error) {
    const status = error.response?.status;
    
    if (status === 401) return 'TOKEN_EXPIRED';
    if (status === 403) return 'FORBIDDEN';
    if (status === 404) return 'NOT_FOUND';
    if (status === 429) return 'RATE_LIMIT';
    if (status >= 500) return 'SERVER_ERROR';
    
    return 'UNKNOWN';
  }
}
```

### Pattern 5: Audit Logging

```javascript
class AuditLogger {
  async logTokenAccess(userId, tenantId, action, details = {}) {
    await db.query(
      `INSERT INTO audit_logs 
       (user_id, tenant_id, action, ip_address, user_agent, details, timestamp)
       VALUES ($1, $2, $3, $4, $5, $6, NOW())`,
      [
        userId,
        tenantId,
        action,
        details.ipAddress,
        details.userAgent,
        JSON.stringify(details)
      ]
    );
  }
  
  async logFHIRRequest(userId, tenantId, emrSystem, endpoint, statusCode, responseTime) {
    await db.query(
      `INSERT INTO fhir_audit_logs
       (user_id, tenant_id, emr_system, endpoint, status_code, response_time_ms, timestamp)
       VALUES ($1, $2, $3, $4, $5, $6, NOW())`,
      [userId, tenantId, emrSystem, endpoint, statusCode, responseTime]
    );
  }
}

// Usage
await auditLogger.logTokenAccess(userId, tenantId, 'token_issued', {
  ipAddress: req.ip,
  userAgent: req.get('user-agent'),
  emrSystem: 'epic',
  scopes: 'patient/Patient.rs'
});

await auditLogger.logFHIRRequest(userId, tenantId, 'epic', '/Patient/123', 200, 145);
```

---

## Operational Checklist

### Pre-Integration

- [ ] Register application with each EMR
- [ ] Receive client_id and client_secret
- [ ] For Backend Services: generate RSA keypair
- [ ] Obtain FHIR base URLs
- [ ] Document redirect URIs
- [ ] Set up encryption keys for token storage
- [ ] Prepare database schemas

### Development

- [ ] Implement SMART configuration discovery
- [ ] Build OAuth2 authorization code flow
- [ ] Build token exchange
- [ ] Build token refresh logic
- [ ] Build FHIR API client
- [ ] Implement error handling
- [ ] Write integration tests

### Security Review

- [ ] All OAuth2 over HTTPS/TLS 1.2+
- [ ] PKCE with S256 implemented
- [ ] Tokens encrypted at rest
- [ ] No tokens in logs
- [ ] State parameter validated
- [ ] Refresh tokens stored encrypted
- [ ] Token revocation on logout
- [ ] Audit logging enabled
- [ ] Access controls tested
- [ ] Penetration testing done

### Deployment Preparation

- [ ] Token encryption key in environment
- [ ] Database migrations ready
- [ ] Monitoring/alerting set up
- [ ] Rate limiting configured
- [ ] Error recovery tested
- [ ] Token refresh tested
- [ ] Multi-EMR tested
- [ ] Load testing completed

### Post-Deployment

- [ ] Monitor token refresh rate
- [ ] Monitor API response times
- [ ] Monitor error rates
- [ ] Monitor token expiration failures
- [ ] Set up alerting for unusual patterns
- [ ] Regular security audits
- [ ] Update tokens on EMR changes
- [ ] Test recovery procedures

---

## Common Gotchas & Solutions

### Gotcha 1: Authorization Code Expires

**Problem:** "Invalid authorization code" error

**Cause:** User took too long to approve, or code was already used

**Solution:**
```javascript
// Codes expire in minutes (typically 10)
const maxCodeAge = 10 * 60 * 1000;

app.get('/callback', async (req, res) => {
  const { code, state } = req.query;
  const codeIssuedAt = req.session.codeIssuedAt;
  
  if (Date.now() - codeIssuedAt > maxCodeAge) {
    return res.status(400).send('Authorization code expired. Please try again.');
  }
  
  // Proceed with token exchange
});
```

### Gotcha 2: Refresh Token Invalid After Use

**Problem:** "Invalid refresh token" after first refresh

**Cause:** Some EMRs rotate refresh tokens on use

**Solution:**
```javascript
// Always update refresh token in DB after refresh
const tokenResponse = await axios.post(tokenEndpoint, {
  grant_type: 'refresh_token',
  refresh_token: currentRefreshToken
});

// NEW refresh token may be different
await db.query(
  `UPDATE oauth_tokens 
   SET refresh_token_encrypted = $1,
       access_token_encrypted = $2,
       access_token_expires_at = $3
   WHERE id = $4`,
  [
    encrypt(tokenResponse.data.refresh_token), // Use new token
    encrypt(tokenResponse.data.access_token),
    new Date(Date.now() + tokenResponse.data.expires_in * 1000),
    tokenRecord.id
  ]
);
```

### Gotcha 3: Scope Mismatch on Refresh

**Problem:** Refreshed token has fewer scopes than original

**Cause:** EMR's scope management changed or user revoked permissions

**Solution:**
```javascript
// Always verify scopes after refresh
const grantedScopes = tokenResponse.data.scope.split(' ');
const requestedScopes = ['patient/Patient.rs', 'patient/Observation.rs'];

const missingScopes = requestedScopes.filter(s => !grantedScopes.includes(s));

if (missingScopes.length > 0) {
  // User needs to re-authenticate
  await revokeAllTokens(userId, tenantId);
  throw new Error(`Insufficient permissions. Please re-authenticate.`);
}
```

### Gotcha 4: Patient ID Changed Between Systems

**Problem:** Patient ID works with Epic but not Cerner for same patient

**Cause:** Each EMR has different patient IDs for same person

**Solution:**
```javascript
// Maintain mapping of patient across EMRs
const patientIdMapping = await db.query(
  `SELECT emr_system, emr_patient_id 
   FROM patient_mappings 
   WHERE internal_patient_id = $1`,
  [internalPatientId]
);

// Map internal ID → EMR-specific ID
const getPatientIdForEMR = (internalId, emrSystem) => {
  const mapping = patientIdMapping.find(m => m.emr_system === emrSystem);
  return mapping?.emr_patient_id;
};
```

### Gotcha 5: Rate Limiting Without Retry-After

**Problem:** Getting 429 errors, no idea when to retry

**Cause:** EMR doesn't send Retry-After header

**Solution:**
```javascript
// Use exponential backoff with jitter
async function retryWithBackoff(fn, maxAttempts = 5) {
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      return await fn();
    } catch (error) {
      if (error.status === 429) {
        const baseDelay = Math.pow(2, attempt) * 1000; // 1s, 2s, 4s, 8s...
        const jitter = Math.random() * 1000; // Random 0-1s
        const delay = baseDelay + jitter;
        
        await new Promise(r => setTimeout(r, delay));
        continue;
      }
      throw error;
    }
  }
}
```

---

## Next Steps

1. **Review** the three main documents in order:
   - This file (Decision Trees)
   - `FHIR_EMR_OAUTH2_PRODUCTION_INTEGRATION.md` (Full guide)
   - `FHIR_EMR_CODE_EXAMPLES_API_REFERENCE.md` (Code examples)

2. **Choose** your architecture:
   - Pick OAuth2 flow (almost always: Authorization Code)
   - Pick storage strategy (almost always: Encrypted DB for backend, Session for frontend)
   - Determine multi-tenancy needs

3. **Implement** step-by-step:
   - Start with one EMR (OpenEMR recommended for testing)
   - Get authorization code flow working
   - Add token refresh
   - Add error handling
   - Test with real EMR sandbox

4. **Harden** for production:
   - Add encryption
   - Add audit logging
   - Add monitoring
   - Security review
   - Load testing

5. **Expand** to other EMRs:
   - Once working with one, adding others is easier
   - Build adapter abstraction
   - Add EMR-specific handling as needed

