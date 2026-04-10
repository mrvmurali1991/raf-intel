# RAF Calculation SaaS - Implementation Architecture Guide

**Purpose**: Reference for building a risk adjustment factor calculation engine  
**Scope**: Data models, calculation flow, integration points  
**Target Audience**: Engineers, Architects, Product Managers

---

## 1. Data Model Overview

### 1.1 Core Entity Relationships

```
┌─────────────┐
│   Patient   │
├─────────────┤
│ patient_id  │ (Primary Key)
│ first_name  │
│ last_name   │
│ dob         │
│ sex         │
│ address     │
└──────┬──────┘
       │
       ├─────────────────┬──────────────────┬──────────────────┐
       │                 │                  │                  │
       ▼                 ▼                  ▼                  ▼
  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
  │Enrollments  │  │  Diagnoses   │  │   Demographics   │  │ Interactions │
  ├─────────────┤  ├──────────────┤  ├──────────────┤  ├──────────────┤
  │ patient_id  │  │ diagnosis_id │  │ patient_id   │  │ patient_id   │
  │ enroll_date │  │ patient_id   │  │ patient_id   │  │ hcc_1        │
  │ disenroll_  │  │ icd10_code   │  │ eff_date     │  │ hcc_2        │
  │ date        │  │ service_date │  │ medicaid     │  │ coeff        │
  │ plan_type   │  │ encounter_   │  │ disability   │  │ eff_date     │
  │ benefit_yr  │  │ type         │  │ institution  │  │ end_date     │
  │ status      │  │ documentation│  │ status       │  └──────────────┘
  │ (new|       │  │ date         │  │              │
  │  continuing)│  │ suppress_reason
  │            │  │              │  │ living_     │
  │ institutional│  │              │  │ situation   │
  │_            │  │              │  └──────────────┘
  │ status      │  │              │
  └─────────────┘  └──────────────┘
```

### 1.2 Detailed Table Schemas

#### Patient Table

```sql
CREATE TABLE patients (
  patient_id UUID PRIMARY KEY,
  mrn VARCHAR(50) UNIQUE NOT NULL,  -- Medical Record Number
  first_name VARCHAR(100) NOT NULL,
  last_name VARCHAR(100) NOT NULL,
  dob DATE NOT NULL,
  gender ENUM('M', 'F', 'X', 'U') NOT NULL,
  medicare_number VARCHAR(20),  -- Optional, but useful
  address_line1 VARCHAR(255),
  address_line2 VARCHAR(255),
  city VARCHAR(100),
  state CHAR(2),
  zip_code VARCHAR(10),
  phone VARCHAR(15),
  email VARCHAR(255),
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
  data_source VARCHAR(100),  -- "claims", "ehr", "manual", etc.
  
  INDEX idx_mrn (mrn),
  INDEX idx_medicare_number (medicare_number),
  INDEX idx_dob (dob)
);
```

#### Enrollments Table

```sql
CREATE TABLE enrollments (
  enrollment_id UUID PRIMARY KEY,
  patient_id UUID NOT NULL REFERENCES patients(patient_id),
  plan_id UUID NOT NULL REFERENCES plans(plan_id),
  enrollment_date DATE NOT NULL,
  disenrollment_date DATE,  -- NULL if still enrolled
  plan_type ENUM(
    'Medicare_Advantage',
    'PACE',
    'ACA_Marketplace',
    'ESRD_MA',
    'Other'
  ) NOT NULL,
  benefit_year YEAR NOT NULL,
  enrollee_status ENUM(
    'new',
    'continuing',
    'aged_in',
    'disabled'
  ) NOT NULL,
  institutional_status ENUM(
    'community',
    'skilled_nursing',
    'long_term_care',
    'assisted_living',
    'other_institution'
  ) NOT NULL DEFAULT 'community',
  medicaid_status ENUM(
    'non_dual',
    'full_benefit_dual',
    'limited_benefit_dual',
    'other'
  ) NOT NULL DEFAULT 'non_dual',
  disability_status BOOLEAN NOT NULL DEFAULT FALSE,
  esrd_status ENUM(
    'non_esrd',
    'dialysis',
    'transplant_0_2_months',
    'transplant_4_9_months',
    'transplant_10_plus_months'
  ) NOT NULL DEFAULT 'non_esrd',
  data_lock_date DATE,  -- Date diagnosis data locked for RAF calc
  raf_calculation_date TIMESTAMP,  -- When RAF was calculated
  
  UNIQUE(patient_id, plan_id, benefit_year),
  INDEX idx_patient_id (patient_id),
  INDEX idx_plan_id (plan_id),
  INDEX idx_benefit_year (benefit_year),
  INDEX idx_plan_type (plan_type)
);
```

#### Diagnoses Table

```sql
CREATE TABLE diagnoses (
  diagnosis_id UUID PRIMARY KEY,
  patient_id UUID NOT NULL REFERENCES patients(patient_id),
  enrollment_id UUID REFERENCES enrollments(enrollment_id),
  icd10_code VARCHAR(10) NOT NULL,
  icd10_description VARCHAR(500),
  service_date DATE NOT NULL,
  benefit_year YEAR NOT NULL,  -- Calendar year for MA
  encounter_type ENUM(
    'office_visit',
    'inpatient',
    'ed_visit',
    'telehealth',
    'other'
  ),
  provider_npi VARCHAR(10),
  provider_name VARCHAR(255),
  documentation_date DATE,
  data_source VARCHAR(50),  -- "claims", "ehr", "chart_review", etc.
  
  -- Mapping fields (populated by system)
  hcc_code INT,  -- e.g., 20, 85, 328
  hcc_version VARCHAR(10),  -- "V24", "V28", etc.
  hcc_category VARCHAR(100),  -- Descriptive category name
  is_valid_for_raf BOOLEAN NOT NULL DEFAULT TRUE,
  validation_notes TEXT,
  
  -- Hierarchy suppression tracking
  suppressed_by_hcc INT,  -- If HCC hierarchy suppressed this diagnosis
  suppress_reason VARCHAR(255),
  
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
  
  INDEX idx_patient_id (patient_id),
  INDEX idx_icd10_code (icd10_code),
  INDEX idx_benefit_year (benefit_year),
  INDEX idx_hcc_code (hcc_code),
  UNIQUE(patient_id, icd10_code, service_date, benefit_year)
);
```

#### Demographics Table

```sql
CREATE TABLE patient_demographics (
  demographic_id UUID PRIMARY KEY,
  patient_id UUID NOT NULL REFERENCES patients(patient_id) UNIQUE,
  benefit_year YEAR NOT NULL,
  age_on_jan1 INT NOT NULL,  -- Age on Jan 1 of benefit year
  age_band VARCHAR(20),  -- "65-69", "70-74", etc.
  gender CHAR(1) NOT NULL,
  
  -- Coefficients (v28 values)
  base_demographic_coefficient DECIMAL(10, 6) NOT NULL,
  medicaid_adjustment DECIMAL(10, 6) DEFAULT 0,
  disability_adjustment DECIMAL(10, 6) DEFAULT 0,
  institutional_adjustment DECIMAL(10, 6) DEFAULT 0,
  total_demographic_coefficient DECIMAL(10, 6) NOT NULL,
  
  -- Additional factors
  part_b_months INT,  -- Number of months with Part B coverage
  is_continuing_enrollee BOOLEAN NOT NULL,
  
  coefficient_source VARCHAR(100),  -- "CMS_V28", "PACE_V22", etc.
  effective_date DATE NOT NULL,
  
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
  
  INDEX idx_patient_id (patient_id),
  INDEX idx_benefit_year (benefit_year)
);
```

#### HCC Coefficients Reference Table

```sql
CREATE TABLE hcc_coefficients (
  coefficient_id UUID PRIMARY KEY,
  hcc_code INT NOT NULL,
  hcc_description VARCHAR(500) NOT NULL,
  model_version VARCHAR(10) NOT NULL,  -- "V24", "V28", "V22", "ESRD_V2019"
  plan_type VARCHAR(50),  -- "MA", "PACE", "ACA", "ESRD" (NULL = all types)
  setting VARCHAR(50),  -- "community", "institutional", NULL = both
  enrollee_status VARCHAR(50),  -- "continuing", "new", NULL = both
  coefficient_value DECIMAL(10, 6) NOT NULL,
  
  -- Hierarchy rules
  hierarchy_parent_hcc INT,  -- If this HCC is suppressed by parent
  hierarchy_children JSON,  -- Array of HCC codes suppressed by this one
  
  effective_date DATE NOT NULL,
  end_date DATE,  -- NULL if current
  
  source_document VARCHAR(255),  -- "CMS_2024_Advance_Notice", etc.
  
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  
  UNIQUE(hcc_code, model_version, plan_type, setting, enrollee_status, effective_date),
  INDEX idx_model_version (model_version),
  INDEX idx_hcc_code (hcc_code),
  INDEX idx_effective_date (effective_date)
);
```

#### Disease Interactions Table

```sql
CREATE TABLE disease_interactions (
  interaction_id UUID PRIMARY KEY,
  model_version VARCHAR(10) NOT NULL,
  hcc_code_1 INT NOT NULL,
  hcc_code_2 INT NOT NULL,
  hcc_description_1 VARCHAR(300),
  hcc_description_2 VARCHAR(300),
  interaction_coefficient DECIMAL(10, 6) NOT NULL,
  plan_type VARCHAR(50),  -- "MA", "PACE", NULL = all
  setting VARCHAR(50),  -- "community", "institutional"
  
  interaction_type ENUM(
    'comorbidity',
    'medication_interaction',
    'complexity_factor'
  ),
  clinical_notes TEXT,
  
  effective_date DATE NOT NULL,
  end_date DATE,  -- NULL if current; use for tracking removals (e.g., immune+cancer in V28)
  
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  
  UNIQUE(model_version, hcc_code_1, hcc_code_2, plan_type, setting, effective_date),
  INDEX idx_model_version (model_version),
  INDEX idx_hcc_pair (hcc_code_1, hcc_code_2)
);
```

#### HCC Count Modifiers Table

```sql
CREATE TABLE hcc_count_modifiers (
  modifier_id UUID PRIMARY KEY,
  model_version VARCHAR(10) NOT NULL,
  hcc_count INT NOT NULL,  -- 5, 6, 7, ..., 10
  modifier_coefficient DECIMAL(10, 6) NOT NULL,
  plan_type VARCHAR(50),
  
  effective_date DATE NOT NULL,
  end_date DATE,
  
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  
  UNIQUE(model_version, hcc_count, plan_type, effective_date),
  INDEX idx_model_version (model_version)
);
```

#### Normalization Factors Table

```sql
CREATE TABLE normalization_factors (
  factor_id UUID PRIMARY KEY,
  benefit_year YEAR NOT NULL,
  model_version VARCHAR(10) NOT NULL,
  plan_type VARCHAR(50),  -- "MA", "PACE", NULL = applies to all
  normalization_factor DECIMAL(10, 6) NOT NULL,
  description VARCHAR(500),
  
  effective_date DATE NOT NULL,
  
  source_document VARCHAR(255),  -- "CMS_2026_Rate_Announcement"
  
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  
  UNIQUE(benefit_year, model_version, plan_type),
  INDEX idx_benefit_year (benefit_year),
  INDEX idx_model_version (model_version)
);
```

#### RAF Calculations Table (Output/Results)

```sql
CREATE TABLE raf_calculations (
  calculation_id UUID PRIMARY KEY,
  patient_id UUID NOT NULL REFERENCES patients(patient_id),
  enrollment_id UUID NOT NULL REFERENCES enrollments(enrollment_id),
  benefit_year YEAR NOT NULL,
  calculation_date TIMESTAMP NOT NULL DEFAULT NOW(),
  
  -- Component scores
  demographic_coefficient DECIMAL(10, 6) NOT NULL,
  disease_score DECIMAL(10, 6) NOT NULL,  -- Sum of HCCs
  interaction_score DECIMAL(10, 6) NOT NULL,
  hcc_count_modifier DECIMAL(10, 6) NOT NULL,
  
  -- Raw RAF
  raw_raf DECIMAL(10, 6) NOT NULL,
  
  -- Normalization & blending
  normalization_factor DECIMAL(10, 6) NOT NULL,
  v24_adjusted_raf DECIMAL(10, 6),  -- If blend year
  v28_adjusted_raf DECIMAL(10, 6),  -- If blend year
  v24_blend_pct INT,  -- e.g., 67 for PY2024
  v28_blend_pct INT,  -- e.g., 33 for PY2024
  
  -- Final RAF
  adjusted_raf DECIMAL(10, 6) NOT NULL,
  
  -- Supporting data
  hcc_list JSON,  -- Array of {hcc_code, coefficient, description}
  interaction_list JSON,  -- Array of {hcc_pair, coefficient}
  hcc_count INT NOT NULL,
  
  -- Metadata
  model_version VARCHAR(10) NOT NULL,  -- "V28", "V24/V28_blend", etc.
  calculated_by VARCHAR(100),  -- "system", "manual_review", etc.
  notes TEXT,
  
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
  
  UNIQUE(patient_id, enrollment_id, benefit_year),
  INDEX idx_patient_id (patient_id),
  INDEX idx_benefit_year (benefit_year),
  INDEX idx_adjusted_raf (adjusted_raf)
);
```

---

## 2. Calculation Flow Architecture

### 2.1 High-Level Processing Flow

```
Input: Patient ID + Benefit Year + Plan Type
  ↓
1. LOAD DATA LAYER
  ├─ Fetch patient demographics
  ├─ Fetch all diagnoses for benefit year
  ├─ Verify enrollment status
  └─ Confirm plan type and settings
  ↓
2. VALIDATION LAYER
  ├─ Validate all ICD-10 codes exist
  ├─ Check service dates in benefit year
  ├─ Verify 12-month Part B data (new vs. continuing)
  └─ Flag invalid/unsupported codes
  ↓
3. MAPPING LAYER
  ├─ Map each ICD-10 → HCC code
  ├─ Select correct model version
  └─ Load appropriate coefficient tables
  ↓
4. CALCULATION LAYER
  ├─ Calculate demographic component
  ├─ Apply HCC hierarchy
  ├─ Sum HCC coefficients
  ├─ Identify & add interactions
  ├─ Apply HCC count modifier
  ├─ Sum to raw RAF
  └─ Apply normalization
  ↓
5. BLENDING LAYER (if transition year)
  ├─ Calculate V24 component
  ├─ Calculate V28 component
  ├─ Blend using year-specific percentages
  └─ Return blended result
  ↓
6. OUTPUT LAYER
  ├─ Store results in RAF calculations table
  ├─ Generate audit trail
  ├─ Return adjusted RAF + components
  └─ Send for downstream payment systems
```

### 2.2 Detailed Calculation Algorithm

```python
def calculate_raf(patient_id, benefit_year, plan_type):
    """
    Main RAF calculation orchestrator
    """
    
    # Step 1: Load data
    patient = load_patient(patient_id)
    enrollment = load_enrollment(patient_id, benefit_year, plan_type)
    diagnoses = load_diagnoses(patient_id, benefit_year)
    
    # Step 2: Validate inputs
    validate_patient_data(patient, enrollment)
    validate_diagnoses(diagnoses, benefit_year)
    
    # Step 3: Determine calculation context
    model_version = determine_model_version(enrollment)
    is_continuing = check_continuing_enrollee_status(patient, benefit_year)
    is_institutional = enrollment.institutional_status != 'community'
    
    # Step 4: Calculate demographic component
    demo_coeff = get_demographic_coefficient(
        patient.dob, 
        patient.gender,
        enrollment.medicaid_status,
        enrollment.disability_status,
        enrollment.institutional_status,
        model_version,
        benefit_year
    )
    
    # Step 5: Process diagnoses (map to HCCs)
    hcc_list = []
    for diagnosis in diagnoses:
        # Map ICD-10 to HCC
        hcc_code = map_icd10_to_hcc(
            diagnosis.icd10_code,
            model_version
        )
        
        if hcc_code:
            hcc_list.append({
                'icd10': diagnosis.icd10_code,
                'hcc_code': hcc_code,
                'service_date': diagnosis.service_date
            })
    
    # Step 6: Apply HCC hierarchy
    hcc_list = apply_hierarchy(hcc_list, model_version)
    # Result: Remove duplicates, suppress lower-severity variants
    
    # Step 7: Get unique HCC codes (one per category per year)
    unique_hccs = get_unique_hcc_codes(hcc_list)
    
    # Step 8: Sum HCC coefficients
    disease_score = 0.0
    hcc_details = []
    for hcc_code in unique_hccs:
        # Get coefficient for this HCC, considering:
        # - model version (V24, V28, V22, ESRD)
        # - plan type (MA, PACE, ACA)
        # - setting (community vs institutional)
        # - enrollee status (new vs continuing)
        
        coeff = get_hcc_coefficient(
            hcc_code,
            model_version,
            plan_type,
            is_institutional,
            is_continuing
        )
        
        disease_score += coeff
        hcc_details.append({
            'hcc_code': hcc_code,
            'coefficient': coeff
        })
    
    # Step 9: Calculate disease interaction terms
    interaction_score = 0.0
    interaction_details = []
    
    for i, hcc1 in enumerate(unique_hccs):
        for hcc2 in unique_hccs[i+1:]:
            # Look up interaction coefficient
            # (Order doesn't matter; check both directions)
            interaction = get_interaction(
                hcc1, hcc2,
                model_version,
                plan_type,
                is_institutional
            )
            
            if interaction:
                interaction_score += interaction['coefficient']
                interaction_details.append({
                    'hcc_pair': (hcc1, hcc2),
                    'coefficient': interaction['coefficient']
                })
    
    # Step 10: Calculate HCC count modifier
    hcc_count = len(unique_hccs)
    hcc_count_modifier = 0.0
    
    if hcc_count >= 5:
        hcc_count_modifier = get_hcc_count_modifier(
            hcc_count,
            model_version,
            plan_type
        )
    
    # Step 11: Sum components to raw RAF
    raw_raf = (
        demo_coeff +
        disease_score +
        interaction_score +
        hcc_count_modifier
    )
    
    # Step 12: Apply normalization factor
    normalization_factor = get_normalization_factor(
        benefit_year,
        model_version,
        plan_type
    )
    
    normalized_raf = raw_raf / normalization_factor
    
    # Step 13: If transition year, apply blending
    if is_blend_year(benefit_year):
        v24_raf = calculate_raf_v24(
            patient_id, 
            benefit_year,
            demo_coeff,
            unique_hccs,
            plan_type,
            is_institutional,
            is_continuing
        )
        v28_raf = normalized_raf  # Already V28
        
        blend_v24_pct, blend_v28_pct = get_blend_percentages(benefit_year)
        
        final_raf = (
            (v24_raf * blend_v24_pct / 100.0) +
            (v28_raf * blend_v28_pct / 100.0)
        )
    else:
        final_raf = normalized_raf
    
    # Step 14: Store and return result
    result = {
        'calculation_id': generate_uuid(),
        'patient_id': patient_id,
        'benefit_year': benefit_year,
        'demographic_coefficient': demo_coeff,
        'disease_score': disease_score,
        'interaction_score': interaction_score,
        'hcc_count_modifier': hcc_count_modifier,
        'raw_raf': raw_raf,
        'normalization_factor': normalization_factor,
        'adjusted_raf': final_raf,
        'hcc_count': hcc_count,
        'hcc_details': hcc_details,
        'interaction_details': interaction_details,
        'model_version': model_version
    }
    
    store_raf_calculation(result)
    return result
```

---

## 3. Integration Points

### 3.1 Data Ingestion Pipelines

#### Source 1: Claims Data (Daily/Weekly)

**Input Format**: Flat file or API
```json
{
  "claims": [
    {
      "member_id": "12345",
      "claim_date": "2025-06-15",
      "diagnosis_code": "E11.9",
      "diagnosis_type": "primary|secondary",
      "provider_npi": "1234567890",
      "place_of_service": "office|inpatient|ed"
    }
  ]
}
```

**Processing**:
1. Validate claim structure
2. Match to patient (MRN/member ID)
3. Create diagnosis record
4. Schedule RAF recalculation if new/updated diagnosis

#### Source 2: EHR/Clinical Data (Real-time/Batch)

**Input Format**: HL7 FHIR API or CSV
```json
{
  "patient_id": "uuid",
  "encounters": [
    {
      "encounter_date": "2025-07-01",
      "diagnoses": ["E11.9", "I50.9"],
      "clinical_notes": "..."
    }
  ]
}
```

**Processing**:
1. Extract diagnoses from structured fields
2. Optional: NLP on clinical notes for additional diagnoses
3. Mark encounter as source
4. Create diagnosis records

#### Source 3: Manual Chart Review (Batch)

**Input Format**: Web UI form or CSV upload
```csv
patient_id,date,icd10_code,reviewer_id,notes
uuid-123,2025-06-15,N18.3,reviewer-001,Stage 3B CKD confirmed by clinical note
```

**Processing**:
1. Validate ICD-10 code format
2. Create diagnosis with "manual_review" data source
3. Mark for audit
4. Require supervisor approval before RAF calc

---

### 3.2 Output Integration

#### Payment System Integration

**RAF scores feed into**:
1. **Capitation Calculation Engine**
   - Input: Benchmark rate + RAF × Member count
   - Output: Monthly capitation payment

2. **Reporting/Analytics Dashboard**
   - Display RAF distribution
   - Flag high-risk patients
   - Track coding completeness

3. **Quality/Compliance Systems**
   - Risk score trends
   - Audit triggers
   - OIG monitoring

**API Endpoint**:
```
GET /api/v1/raf/{enrollment_id}/{benefit_year}

Response:
{
  "enrollment_id": "uuid",
  "adjusted_raf": 1.845,
  "hcc_count": 7,
  "last_updated": "2025-07-01T14:30:00Z"
}
```

---

## 4. Technology Stack Recommendations

### 4.1 Core Components

| Component | Recommendation | Reasoning |
|-----------|---|---|
| **Database** | PostgreSQL with TimescaleDB | Time-series diagnosis data, complex queries, JSONB for hierarchies |
| **Calculation Engine** | Python (pandas, numpy) or Rust | Performance-critical, handle bulk calculations, parallelize |
| **API Layer** | FastAPI or gRPC | Real-time RAF lookups, high throughput |
| **Cache Layer** | Redis | Cache coefficient tables, normalization factors, frequent lookups |
| **Message Queue** | Kafka or RabbitMQ | Async diagnosis processing, calculation triggers |
| **Workflows** | Airflow or Dagster | Daily/weekly RAF batch calculations, data pipelines |
| **Data Warehouse** | Snowflake or BigQuery | Historical tracking, analytics, audit trails |
| **Monitoring** | Prometheus + Grafana | Track calculation performance, accuracy |

### 4.2 Data Refresh Strategy

**Monthly Cycle**:
1. **Day 1-5**: Ingest claims/EHR data
2. **Day 6**: Run initial validation & mapping
3. **Day 7-10**: Chart review (clinical validation)
4. **Day 11**: Lock diagnosis data for RAF calculation
5. **Day 12-15**: Batch RAF recalculation for all patients
6. **Day 16**: Validate results & audit
7. **Day 17**: Push to payment systems
8. **Day 18-31**: Ad-hoc RAF updates, reporting

**Data Refresh Requirements**:
- New HCC/coefficient tables: Typically April (annual)
- Normalization factors: Typically April (annual)
- Normalization factors can update mid-year
- ICD-10 code set: October 1 (annual)
- Keep historical versions for audit trail

---

## 5. Quality Assurance & Validation

### 5.1 Test Cases

**Test 1: New Enrollee (No HCC Credits)**
```python
def test_new_enrollee_no_hcc():
    # 65-year-old male, non-dual
    # Enrolled March 2025 (less than 12 months data)
    # Diagnoses: E11.9, I50.9, N18.3
    
    raf = calculate_raf(patient_id, 2025)
    
    assert raf['demographic_coefficient'] == 0.527  # Base only
    assert raf['disease_score'] == 0.0  # No HCC for new enrollee
    assert raf['interaction_score'] == 0.0
    assert raf['adjusted_raf'] < 1.0  # Below average
```

**Test 2: Hierarchy Rules Compliance**
```python
def test_hierarchy_suppression():
    # Patient with both:
    # - E34 (Breast cancer): HCC 9 (0.940)
    # - C50.9 (Metastatic breast cancer): HCC 8 (1.089)
    # Should only count HCC 8 (more severe)
    
    raf = calculate_raf(patient_id, 2025)
    
    assert len(raf['hcc_details']) == 1
    assert raf['hcc_details'][0]['hcc_code'] == 8
    assert raf['disease_score'] == 1.089
```

**Test 3: Disease Interaction Application**
```python
def test_disease_interaction():
    # Patient with:
    # - E11.9 (Diabetes): HCC 20 (0.166)
    # - I50.9 (CHF): HCC 85 (0.360)
    # - Interaction: +0.112
    
    raf = calculate_raf(patient_id, 2025)
    
    assert raf['disease_score'] == 0.166 + 0.360
    assert raf['interaction_score'] == 0.112
    assert raf['adjusted_raf'] > (0.166 + 0.360)
```

**Test 4: Blend Calculation (PY2024)**
```python
def test_v24_v28_blend_2024():
    # Both V24 and V28 calculated
    # Blend: 67% V24 + 33% V28
    
    raf = calculate_raf(patient_id, 2024)
    
    v24_raf = 1.500
    v28_raf = 1.300
    expected = (v24_raf * 0.67) + (v28_raf * 0.33)
    
    assert abs(raf['adjusted_raf'] - expected) < 0.001
```

**Test 5: ESRD HCC Zero-Weighting**
```python
def test_esrd_zero_weighted_hccs():
    # ESRD dialysis patient
    # Diagnoses include CKD Stage 5 (HCC 327)
    # HCC 327 should be zero-weighted in ESRD model
    
    raf = calculate_raf(patient_id, 2025, plan_type='ESRD_MA')
    
    # HCC 327 in HCC list but coefficient = 0.0
    hcc_327 = [h for h in raf['hcc_details'] if h['hcc_code'] == 327][0]
    assert hcc_327['coefficient'] == 0.0
    
    # Disease score doesn't include it
    assert raf['disease_score'] > 0  # Other HCCs count
```

---

## 6. Security & Compliance

### 6.1 Data Protection

- **HIPAA Compliance**: Encrypt PII at rest and in transit
- **Audit Logging**: All RAF calculation changes logged with timestamp, user, reason
- **Role-Based Access**: Restrict diagnosis editing, coefficient changes to authorized users
- **Data Retention**: 7-year retention for audits
- **Backup Strategy**: Daily incremental, weekly full, monthly archive

### 6.2 Calculation Validation

- **Peer Review**: All manual diagnoses require second review before RAF impact
- **Variance Reports**: Flag RAF changes >10% month-over-month
- **Audit Trail**: Store before/after RAF, diagnosis changes, coefficient versions
- **OIG Compliance**: Monthly report of new/removed diagnoses by provider

---

## 7. Performance Optimization

### 7.1 Database Indexing Strategy

```sql
-- Critical indexes for performance
CREATE INDEX idx_patient_diagnosis_year ON diagnoses(patient_id, benefit_year);
CREATE INDEX idx_hcc_code_model_date ON hcc_coefficients(hcc_code, model_version, effective_date);
CREATE INDEX idx_enrollment_patient_year ON enrollments(patient_id, benefit_year);
CREATE INDEX idx_raf_calc_patient_year ON raf_calculations(patient_id, benefit_year);
```

### 7.2 Caching Strategy

**Cache Layers**:
1. **L1 (In-Memory)**: Coefficient tables (refresh weekly)
2. **L2 (Redis)**: Patient demographic data (TTL: 24 hours)
3. **L3 (Database)**: Full diagnosis history with query caching

**Typical Lookup Time**:
- Single patient RAF: 100-500ms
- Batch (10K patients): 30-60 seconds
- Full population (500K patients): 2-4 hours

---

## 8. Deployment & Monitoring

### 8.1 CI/CD Pipeline

```
Code Commit → Unit Tests → Integration Tests → Staging Deploy → Prod Deploy
              ↓            ↓                  ↓                 ↓
            pytest      pytest + DB      Manual QA          Blue-Green
                        integration      Sign-off           Deployment
```

### 8.2 Monitoring Metrics

- **Calculation Accuracy**: % of RAFs matching manual validation
- **Processing Time**: Latency percentiles (p50, p95, p99)
- **Data Quality**: % diagnoses mapped to valid HCC
- **Completeness**: % patients with at least 1 diagnosis vs. 0 diagnoses
- **Error Rate**: Failed calculations, timeout, invalid data

---

**Document Version**: 1.0  
**Last Updated**: April 2026  
**For**: Engineering teams building RAF calculation SaaS
