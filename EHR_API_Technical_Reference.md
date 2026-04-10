# EHR/EMR Integration Technical Reference Guide

## Table of Contents
1. [Epic FHIR API Examples](#epic-fhir-api-examples)
2. [Oracle Health (Cerner) API Examples](#oracle-health-cerner-api-examples)
3. [Athenahealth API Examples](#athenahealth-api-examples)
4. [eClinicalWorks FHIR Examples](#eclinicalworks-fhir-examples)
5. [Common Authentication Patterns](#common-authentication-patterns)
6. [FHIR Query Examples](#fhir-query-examples)
7. [Error Handling and Retry Logic](#error-handling-and-retry-logic)
8. [Performance and Caching](#performance-and-caching)

---

## 1. Epic FHIR API Examples

### Authentication - OAuth 2.0 with PKCE

```python
import requests
import json
import base64
import hashlib
import secrets
from urllib.parse import urlencode

class EpicFHIRClient:
    def __init__(self, client_id, client_secret, ehr_url):
        self.client_id = client_id
        self.client_secret = client_secret
        self.ehr_url = ehr_url
        self.access_token = None
        self.token_expiry = None
    
    def get_smart_configuration(self):
        """Discover OAuth endpoints"""
        url = f"{self.ehr_url}/.well-known/smart-configuration"
        response = requests.get(url)
        return response.json()
    
    def generate_pkce_pair(self):
        """Generate PKCE code verifier and challenge"""
        code_verifier = base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode('utf-8').rstrip('=')
        
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).decode('utf-8').rstrip('=')
        
        return code_verifier, code_challenge
    
    def get_authorization_url(self, redirect_uri, scopes):
        """Generate authorization URL"""
        config = self.get_smart_configuration()
        auth_url = config['authorization_endpoint']
        
        code_verifier, code_challenge = self.generate_pkce_pair()
        
        params = {
            'client_id': self.client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': ' '.join(scopes),
            'state': secrets.token_urlsafe(32),
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256'
        }
        
        # Store verifier for token exchange
        self.code_verifier = code_verifier
        self.state = params['state']
        
        return f"{auth_url}?{urlencode(params)}"
    
    def exchange_code_for_token(self, code, redirect_uri):
        """Exchange authorization code for access token"""
        config = self.get_smart_configuration()
        token_url = config['token_endpoint']
        
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'redirect_uri': redirect_uri,
            'code_verifier': self.code_verifier
        }
        
        response = requests.post(token_url, data=data)
        
        if response.status_code == 200:
            token_data = response.json()
            self.access_token = token_data['access_token']
            self.token_expiry = token_data.get('expires_in')
            self.refresh_token = token_data.get('refresh_token')
            return token_data
        else:
            raise Exception(f"Token exchange failed: {response.text}")
    
    def refresh_access_token(self):
        """Refresh expired access token"""
        config = self.get_smart_configuration()
        token_url = config['token_endpoint']
        
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }
        
        response = requests.post(token_url, data=data)
        
        if response.status_code == 200:
            token_data = response.json()
            self.access_token = token_data['access_token']
            self.token_expiry = token_data.get('expires_in')
            return token_data
        else:
            raise Exception(f"Token refresh failed: {response.text}")
```

### FHIR API Calls

```python
class EpicFHIRClient:
    def get_fhir_url(self):
        """Get FHIR base URL from capability statement"""
        url = f"{self.ehr_url}/metadata"
        headers = {'Authorization': f'Bearer {self.access_token}'}
        response = requests.get(url, headers=headers)
        return response.json()
    
    def get_patient(self, patient_id):
        """Retrieve patient demographics"""
        url = f"{self.ehr_url}/Patient/{patient_id}"
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/fhir+json'
        }
        response = requests.get(url, headers=headers)
        return response.json()
    
    def search_conditions(self, patient_id, status=None):
        """Search for patient conditions/diagnoses"""
        url = f"{self.ehr_url}/Condition"
        
        params = {
            'patient': patient_id,
            '_count': 100
        }
        if status:
            params['clinical-status'] = status  # active, recurrence, remission
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/fhir+json'
        }
        
        response = requests.get(url, params=params, headers=headers)
        return response.json()
    
    def search_encounters(self, patient_id, date_from=None, date_to=None):
        """Search for patient encounters"""
        url = f"{self.ehr_url}/Encounter"
        
        params = {
            'patient': patient_id,
            '_count': 100,
            '_sort': '-date'
        }
        
        if date_from:
            params['date'] = f'ge{date_from}'
        if date_to:
            params['date'] = f'le{date_to}'
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/fhir+json'
        }
        
        response = requests.get(url, params=params, headers=headers)
        return response.json()
    
    def search_observations(self, patient_id, code=None):
        """Search for observations (vital signs, lab results)"""
        url = f"{self.ehr_url}/Observation"
        
        params = {
            'patient': patient_id,
            '_count': 100
        }
        
        if code:  # LOINC code
            params['code'] = code
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/fhir+json'
        }
        
        response = requests.get(url, params=params, headers=headers)
        return response.json()
    
    def get_diagnostic_reports(self, patient_id, category=None):
        """Retrieve diagnostic reports (lab results, imaging)"""
        url = f"{self.ehr_url}/DiagnosticReport"
        
        params = {
            'patient': patient_id,
            '_count': 100,
            '_sort': '-issued'
        }
        
        if category:  # lab, imaging, etc.
            params['category'] = category
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/fhir+json'
        }
        
        response = requests.get(url, params=params, headers=headers)
        return response.json()
    
    def extract_hcc_data(self, patient_id):
        """Extract HCC-relevant data for a patient"""
        hcc_data = {
            'patient_id': patient_id,
            'conditions': [],
            'encounters': [],
            'observations': []
        }
        
        # Get patient info
        patient = self.get_patient(patient_id)
        hcc_data['demographics'] = {
            'name': patient.get('name', [{}])[0],
            'birthDate': patient.get('birthDate'),
            'gender': patient.get('gender')
        }
        
        # Get active conditions
        conditions_response = self.search_conditions(patient_id, status='active')
        for entry in conditions_response.get('entry', []):
            condition = entry['resource']
            coding = condition.get('code', {}).get('coding', [])
            
            for code in coding:
                if code.get('system') == 'http://hl7.org/fhir/sid/icd-10-cm':
                    hcc_data['conditions'].append({
                        'icd10_code': code.get('code'),
                        'display': code.get('display'),
                        'recorded_date': condition.get('recordedDate'),
                        'onset': condition.get('onsetDateTime')
                    })
        
        # Get encounters (for validation)
        encounters_response = self.search_encounters(patient_id)
        for entry in encounters_response.get('entry', []):
            encounter = entry['resource']
            hcc_data['encounters'].append({
                'date': encounter.get('period', {}).get('start'),
                'type': encounter.get('type', [{}])[0].get('text'),
                'status': encounter.get('status')
            })
        
        return hcc_data
```

---

## 2. Oracle Health (Cerner) API Examples

### Authentication

```python
class CernerFHIRClient:
    def __init__(self, client_id, client_secret, auth_url, fhir_url, tenant_id):
        self.client_id = client_id
        self.client_secret = client_secret
        self.auth_url = auth_url
        self.fhir_url = fhir_url
        self.tenant_id = tenant_id
        self.access_token = None
    
    def get_authorization_url(self, redirect_uri, scopes):
        """Generate Cerner authorization URL"""
        params = {
            'client_id': self.client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': ' '.join(scopes),
            'state': secrets.token_urlsafe(32)
        }
        
        self.state = params['state']
        return f"{self.auth_url}?{urlencode(params)}"
    
    def exchange_code_for_token(self, code):
        """Exchange authorization code for access token"""
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': self.client_id,
            'client_secret': self.client_secret
        }
        
        response = requests.post(self.auth_url, data=data)
        
        if response.status_code == 200:
            token_data = response.json()
            self.access_token = token_data['access_token']
            return token_data
        else:
            raise Exception(f"Token exchange failed: {response.text}")
    
    def get_capability_statement(self):
        """Get FHIR capability statement"""
        url = f"{self.fhir_url}/r4/{self.tenant_id}/metadata"
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/fhir+json'
        }
        
        response = requests.get(url, headers=headers)
        return response.json()
```

### FHIR API Calls

```python
class CernerFHIRClient:
    def search_conditions(self, patient_id):
        """Search Condition resources for patient"""
        url = f"{self.fhir_url}/r4/{self.tenant_id}/Condition"
        
        params = {
            'patient': patient_id
        }
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/fhir+json'
        }
        
        response = requests.get(url, params=params, headers=headers)
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 401:
            raise Exception("Unauthorized - check token validity")
        elif response.status_code == 403:
            raise Exception("Forbidden - check scopes and permissions")
        else:
            raise Exception(f"Request failed: {response.status_code}")
    
    def search_encounters(self, patient_id):
        """Search Encounter resources"""
        url = f"{self.fhir_url}/r4/{self.tenant_id}/Encounter"
        
        params = {
            'patient': patient_id
        }
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/fhir+json'
        }
        
        response = requests.get(url, params=params, headers=headers)
        return response.json()
    
    def get_patient_procedures(self, patient_id):
        """Search Procedure resources"""
        url = f"{self.fhir_url}/r4/{self.tenant_id}/Procedure"
        
        params = {
            'patient': patient_id
        }
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/fhir+json'
        }
        
        response = requests.get(url, params=params, headers=headers)
        return response.json()
    
    def get_diagnostic_report(self, patient_id):
        """Search DiagnosticReport resources"""
        url = f"{self.fhir_url}/r4/{self.tenant_id}/DiagnosticReport"
        
        params = {
            'patient': patient_id
        }
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/fhir+json'
        }
        
        response = requests.get(url, params=params, headers=headers)
        return response.json()
```

---

## 3. Athenahealth API Examples

### Authentication

```python
class Athenahealth_API_Client:
    def __init__(self, client_id, client_secret, api_url):
        self.client_id = client_id
        self.client_secret = client_secret
        self.api_url = api_url
        self.access_token = None
    
    def get_access_token(self):
        """Get OAuth access token"""
        auth = (self.client_id, self.client_secret)
        data = {'grant_type': 'client_credentials'}
        
        response = requests.post(
            f"{self.api_url}/oauth/token",
            auth=auth,
            data=data
        )
        
        if response.status_code == 200:
            token_data = response.json()
            self.access_token = token_data['access_token']
            return token_data
        else:
            raise Exception(f"Token request failed: {response.text}")
```

### FHIR API Calls

```python
class AthenafheathFHIR_Client:
    def search_patients(self, query, limit=10):
        """Search patients by name or ID"""
        url = f"{self.api_url}/fhir/r4/Patient"
        
        params = {
            '_count': limit
        }
        
        if query.isdigit():
            params['identifier'] = query  # Patient ID
        else:
            params['name'] = query
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/fhir+json'
        }
        
        response = requests.get(url, params=params, headers=headers)
        return response.json()
    
    def get_conditions(self, patient_id):
        """Get conditions for patient"""
        url = f"{self.api_url}/fhir/r4/Condition"
        
        params = {
            'patient': patient_id
        }
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/fhir+json'
        }
        
        response = requests.get(url, params=params, headers=headers)
        return response.json()
    
    def get_risk_adjustment_data(self, patient_id):
        """Get risk adjustment specific data via Risk Adjustment API"""
        url = f"{self.api_url}/rs/api/v1/patients/{patient_id}/risk-adjustments"
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
        
        response = requests.get(url, headers=headers)
        return response.json()
```

---

## 4. eClinicalWorks FHIR Examples

### Authentication

```python
class eClinicalWorks_FHIR_Client:
    def __init__(self, client_id, client_secret, fhir_url, auth_url):
        self.client_id = client_id
        self.client_secret = client_secret
        self.fhir_url = fhir_url
        self.auth_url = auth_url
        self.access_token = None
    
    def get_access_token(self):
        """OAuth 2.0 token request for eCW"""
        data = {
            'grant_type': 'client_credentials',
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'scope': 'fhir'
        }
        
        response = requests.post(f"{self.auth_url}/oauth/token", data=data)
        
        if response.status_code == 200:
            token_data = response.json()
            self.access_token = token_data['access_token']
            return token_data
        else:
            raise Exception(f"Token request failed: {response.text}")
```

### FHIR API Calls

```python
class eClinicalWorks_FHIR_Client:
    def get_patient(self, patient_id):
        """Get patient demographics"""
        url = f"{self.fhir_url}/Patient/{patient_id}"
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/fhir+json'
        }
        
        response = requests.get(url, headers=headers)
        return response.json()
    
    def search_conditions(self, patient_id):
        """Search conditions"""
        url = f"{self.fhir_url}/Condition"
        
        params = {
            'patient': patient_id
        }
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/fhir+json'
        }
        
        response = requests.get(url, params=params, headers=headers)
        return response.json()
    
    def get_observations(self, patient_id):
        """Get vital signs and observations"""
        url = f"{self.fhir_url}/Observation"
        
        params = {
            'patient': patient_id,
            '_count': 100
        }
        
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/fhir+json'
        }
        
        response = requests.get(url, params=params, headers=headers)
        return response.json()
```

---

## 5. Common Authentication Patterns

### Backend Service (System-to-System) Authentication

```python
import jwt
from datetime import datetime, timedelta

class BackendServiceClient:
    """
    For system-to-system integrations without user context
    (e.g., scheduled data extraction)
    """
    
    def __init__(self, client_id, private_key, token_url, scopes):
        self.client_id = client_id
        self.private_key = private_key
        self.token_url = token_url
        self.scopes = scopes
        self.access_token = None
    
    def create_jwt_assertion(self):
        """Create JWT assertion for backend services"""
        now = datetime.utcnow()
        expiry = now + timedelta(minutes=5)
        
        payload = {
            'iss': self.client_id,
            'sub': self.client_id,
            'aud': self.token_url,
            'iat': int(now.timestamp()),
            'exp': int(expiry.timestamp()),
            'scope': ' '.join(self.scopes)
        }
        
        # Sign with private key (RS256)
        token = jwt.encode(
            payload,
            self.private_key,
            algorithm='RS256'
        )
        
        return token
    
    def get_access_token(self):
        """Request access token using JWT assertion"""
        assertion = self.create_jwt_assertion()
        
        data = {
            'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
            'assertion': assertion
        }
        
        response = requests.post(self.token_url, data=data)
        
        if response.status_code == 200:
            token_data = response.json()
            self.access_token = token_data['access_token']
            return token_data
        else:
            raise Exception(f"Token request failed: {response.text}")
```

---

## 6. FHIR Query Examples

### Complex Searches

```python
class FHIRQueryBuilder:
    """Build complex FHIR queries"""
    
    def __init__(self, base_url, access_token):
        self.base_url = base_url
        self.headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/fhir+json'
        }
    
    def search_conditions_by_date_range(self, patient_id, date_from, date_to):
        """Find conditions documented in date range"""
        url = f"{self.base_url}/Condition"
        
        params = {
            'patient': patient_id,
            'recorded': f'ge{date_from}',  # Greater than or equal
            'recorded': f'le{date_to}',    # Less than or equal
            '_sort': '-recorded'
        }
        
        response = requests.get(url, params=params, headers=self.headers)
        return response.json()
    
    def search_hcc_diagnoses(self, patient_id, hcc_codes):
        """Search for specific HCC-mapped diagnoses"""
        url = f"{self.base_url}/Condition"
        
        # Build OR query for multiple ICD-10 codes
        code_param = ','.join(hcc_codes)
        
        params = {
            'patient': patient_id,
            'code': code_param,  # Multiple codes with OR logic
            'clinical-status': 'active'
        }
        
        response = requests.get(url, params=params, headers=self.headers)
        return response.json()
    
    def search_encounters_by_type(self, patient_id, encounter_types):
        """Find encounters by type (office visit, telehealth, etc)"""
        url = f"{self.base_url}/Encounter"
        
        # encounter_types example: ['99213', '99214']  # CPT codes
        type_param = ','.join(encounter_types)
        
        params = {
            'patient': patient_id,
            'type': type_param,
            'status': 'finished',
            '_sort': '-date'
        }
        
        response = requests.get(url, params=params, headers=self.headers)
        return response.json()
    
    def search_recent_lab_results(self, patient_id, days=90):
        """Get lab results from past N days"""
        url = f"{self.base_url}/DiagnosticReport"
        
        from_date = (datetime.now() - timedelta(days=days)).date()
        
        params = {
            'patient': patient_id,
            'issued': f'ge{from_date}',
            'category': 'LAB',
            '_sort': '-issued'
        }
        
        response = requests.get(url, params=params, headers=self.headers)
        return response.json()
    
    def search_observations_by_loinc(self, patient_id, loinc_codes):
        """Search observations by LOINC code"""
        url = f"{self.base_url}/Observation"
        
        code_param = ','.join(loinc_codes)
        
        params = {
            'patient': patient_id,
            'code': code_param,  # LOINC codes
            '_sort': '-date'
        }
        
        response = requests.get(url, params=params, headers=self.headers)
        return response.json()
```

---

## 7. Error Handling and Retry Logic

```python
import time
from functools import wraps

class RetryableAPIClient:
    """Add retry logic to API calls"""
    
    def __init__(self, max_retries=3, backoff_factor=2):
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
    
    def retry_with_backoff(self, func):
        """Decorator for retry logic with exponential backoff"""
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(1, self.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                
                except requests.exceptions.RequestException as e:
                    last_exception = e
                    
                    # Don't retry on 4xx errors (except 429)
                    if hasattr(e, 'response') and e.response is not None:
                        status_code = e.response.status_code
                        
                        if 400 <= status_code < 500 and status_code != 429:
                            raise
                    
                    if attempt < self.max_retries:
                        wait_time = self.backoff_factor ** (attempt - 1)
                        print(f"Attempt {attempt} failed, retrying in {wait_time}s...")
                        time.sleep(wait_time)
            
            raise last_exception
        
        return wrapper

# Usage
client = RetryableAPIClient(max_retries=3, backoff_factor=2)

@client.retry_with_backoff
def get_patient_data(fhir_url, patient_id, token):
    """API call with automatic retry"""
    headers = {'Authorization': f'Bearer {token}'}
    response = requests.get(f"{fhir_url}/Patient/{patient_id}", headers=headers)
    response.raise_for_status()
    return response.json()

# Call with retry logic
try:
    data = get_patient_data(fhir_url, patient_id, token)
except Exception as e:
    print(f"Failed after retries: {e}")
```

### HTTP Error Handling

```python
class FHIRAPIErrorHandler:
    """Handle FHIR-specific API errors"""
    
    @staticmethod
    def handle_response(response):
        """Check response and raise appropriate exceptions"""
        
        if response.status_code == 401:
            raise Exception("Unauthorized: Check access token validity")
        
        elif response.status_code == 403:
            raise Exception("Forbidden: Insufficient permissions (check scopes)")
        
        elif response.status_code == 404:
            raise Exception("Not Found: Resource does not exist")
        
        elif response.status_code == 429:
            raise Exception("Rate Limited: Too many requests")
        
        elif response.status_code == 500:
            raise Exception("Server Error: EHR server error")
        
        elif response.status_code == 503:
            raise Exception("Service Unavailable: EHR temporarily unavailable")
        
        elif response.status_code >= 400:
            # Try to parse FHIR OperationOutcome
            try:
                outcome = response.json()
                if outcome.get('resourceType') == 'OperationOutcome':
                    issues = outcome.get('issue', [])
                    error_text = '; '.join([i.get('diagnostics', '') for i in issues])
                    raise Exception(f"API Error: {error_text}")
            except:
                pass
            
            raise Exception(f"API Error {response.status_code}: {response.text}")
        
        return response.json()
```

---

## 8. Performance and Caching

```python
from functools import lru_cache
from datetime import datetime, timedelta

class CachedFHIRClient:
    """FHIR client with caching for frequently accessed data"""
    
    def __init__(self, base_url, token, cache_ttl_seconds=3600):
        self.base_url = base_url
        self.token = token
        self.cache_ttl = cache_ttl_seconds
        self.cache = {}
    
    def _cache_key(self, endpoint, params):
        """Generate cache key from endpoint and parameters"""
        params_str = '&'.join(f"{k}={v}" for k, v in sorted(params.items()))
        return f"{endpoint}?{params_str}"
    
    def _is_cache_valid(self, key):
        """Check if cache entry is still valid"""
        if key not in self.cache:
            return False
        
        timestamp, _ = self.cache[key]
        age = (datetime.now() - timestamp).total_seconds()
        return age < self.cache_ttl
    
    def get_with_cache(self, endpoint, params):
        """Get FHIR resource with caching"""
        cache_key = self._cache_key(endpoint, params)
        
        # Check cache
        if self._is_cache_valid(cache_key):
            _, data = self.cache[cache_key]
            print(f"Cache hit for {cache_key}")
            return data
        
        # Call API
        url = f"{self.base_url}/{endpoint}"
        headers = {
            'Authorization': f'Bearer {self.token}',
            'Accept': 'application/fhir+json'
        }
        
        response = requests.get(url, params=params, headers=headers)
        data = response.json()
        
        # Cache result
        self.cache[cache_key] = (datetime.now(), data)
        
        return data
    
    def get_patient(self, patient_id):
        """Get patient with caching (longer TTL)"""
        data = self.get_with_cache('Patient', {'_id': patient_id})
        return data
    
    def search_conditions(self, patient_id):
        """Search conditions with caching"""
        data = self.get_with_cache('Condition', {'patient': patient_id})
        return data
    
    def clear_cache(self):
        """Clear all cached data"""
        self.cache.clear()
    
    def clear_cache_for_patient(self, patient_id):
        """Clear cached data for specific patient"""
        keys_to_remove = [k for k in self.cache.keys() if f'patient={patient_id}' in k]
        for key in keys_to_remove:
            del self.cache[key]
```

### Pagination

```python
class PaginatedFHIRQuery:
    """Handle pagination for large result sets"""
    
    def __init__(self, base_url, token):
        self.base_url = base_url
        self.token = token
        self.headers = {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/fhir+json'
        }
    
    def get_all_resources(self, endpoint, params, page_size=100):
        """Iterate through all pages of results"""
        all_resources = []
        params['_count'] = page_size
        
        url = f"{self.base_url}/{endpoint}"
        next_url = None
        
        while True:
            if next_url:
                # Use next link if available
                response = requests.get(next_url, headers=self.headers)
            else:
                response = requests.get(url, params=params, headers=self.headers)
            
            data = response.json()
            
            # Add resources from this page
            for entry in data.get('entry', []):
                all_resources.append(entry['resource'])
            
            # Check for next page
            next_link = None
            for link in data.get('link', []):
                if link.get('relation') == 'next':
                    next_link = link.get('url')
                    break
            
            if not next_link:
                break
            
            next_url = next_link
        
        return all_resources
    
    def batch_get_conditions(self, patient_id, batch_size=50):
        """Get all conditions in batches"""
        conditions = self.get_all_resources(
            'Condition',
            {'patient': patient_id},
            page_size=batch_size
        )
        return conditions
```

---

## Conclusion

These code examples demonstrate:
- OAuth 2.0 authentication with PKCE
- FHIR R4 API patterns across multiple EHRs
- Error handling and retry logic
- Caching for performance
- Pagination for large datasets

All examples assume Python 3.7+, `requests` library, and proper error handling in production environments.

