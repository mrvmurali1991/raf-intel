# RAF SaaS: CMS Regulatory Compliance & Submission Requirements

## 1. CMS Data Submission Requirements

### 1.1 MAO-004 File (Risk Adjustment Data Submission)

**Regulatory Basis:** 42 CFR §422.504(c) - Medicare Advantage Plans must report encounters

**Due Date:** Last calendar day of the month following the month of service

**Format:** EDI 837 Health Care Claim (professional: 837P, institutional: 837I)

**Content Requirements:**

```
MAO-004 File Structure:
├── Header (GS/ST segments)
├── Patient Demographics (NM1 segments)
│   └── Member ID (CMS-specific format)
│   └── DOB, Sex (for CMS validation)
│   └── Provider NPI (servicing provider)
│
├── Service Lines (CLP/SVC segments)
│   ├── Service dates (from/to)
│   ├── Place of service code
│   ├── CPT/HCPCS code (procedure)
│   └── Revenue code (institutional only)
│
├── Diagnosis Codes (DTP/HI segments)
│   ├── ICD-10-CM codes (primary + secondary)
│   ├── Sequence position
│   ├── Present-on-arrival (POA) indicators
│   └── Condition type codes
│
└── Trailer (SE/GE/IEA segments)
    └── Record count validation
```

**Validation Rules (CMS MA EDS Front-End):**

```sql
-- Syntax validation
SELECT
    claim_id,
    CASE
        WHEN member_id IS NULL OR member_id = '' THEN 'E1_MISSING_MEMBER_ID'
        WHEN NPI NOT REGEXP '^[0-9]{10}$' THEN 'E2_INVALID_NPI'
        WHEN service_from_date > service_to_date THEN 'E3_INVALID_DATES'
        WHEN ARRAY_SIZE(diagnosis_codes) = 0 THEN 'E4_NO_DIAGNOSES'
        WHEN ARRAY_SIZE(diagnosis_codes) > 25 THEN 'E5_TOO_MANY_DIAGNOSES'
        WHEN icd10_code NOT IN (SELECT code FROM icd10_valid_2024) THEN 'E6_INVALID_ICD10'
        WHEN place_of_service NOT IN (11, 21, 23, 31, 32) THEN 'E7_INVALID_POS'
    END as rejection_reason
FROM encounters_submitted
WHERE submission_date = CURRENT_DATE;

-- Logic validation
SELECT
    claim_id,
    CASE
        WHEN revenue_code = '0001' AND place_of_service <> 21 
            THEN 'L1_INPATIENT_REVENUE_OUTPATIENT_POS'
        WHEN diagnosis_count > 12 AND clinical_complexity_flag = FALSE
            THEN 'L2_UNUSUAL_DIAGNOSIS_COUNT'
        WHEN allowed_amount > PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY allowed_amount)
            THEN 'L3_OUTLIER_AMOUNT'
    END as logic_warning
FROM encounters_submitted;
```

### 1.2 MAO-002 File (Annual Reconciliation)

**Due Date:** March 31 (for prior calendar year, finalized 12 months post-service)

**Content:** One record per enrolled member with:
- Member ID & Demographic info
- Service Year
- Final RAF score (after sweep reconciliation)
- HCC codes applied
- Coding data source summary

```sql
-- MAO-002 Report Query
SELECT
    member_id,
    first_name,
    last_name,
    date_of_birth,
    sex,
    
    -- Enrollment
    enrollment_date,
    termination_date,
    plan_id,
    
    -- Risk Adjustment
    service_year,
    final_raf_score,
    
    -- HCC data source breakdown
    hcc_codes_from_claims,
    hcc_codes_from_chart_review,
    hcc_codes_from_cdm,  -- CDI-identified
    
    -- Data submission tracking
    encounter_records_count,
    chart_review_records_count,
    
    -- Submission status
    cms_submitted BOOLEAN,
    cms_submission_date,
    cms_validation_status
FROM raf_annual_summary
WHERE service_year = 2024
ORDER BY member_id;
```

### 1.3 Chart Review Record (CRR) Submission

**Purpose:** Alternative documentation pathway for diagnoses identified via medical record review (not in claims)

**Format:** CMS-specific fixed-length record format (not EDI 837)

**Validation:** NCQA audit requirement for public reporting

```
CRR Record Format:
- Position 1-15: Member ID (CMS format)
- Position 16-23: Service date (YYYYMMDD)
- Position 24-26: HCC code
- Position 27-33: ICD-10 code
- Position 34-40: Reviewer ID/NPI
- Position 41-48: Review date (YYYYMMDD)
- Position 49-50: Review status (01=Confirmed, 02=Questionable, 03=Rejected)
```

**Submission Requirements:**

```python
class CRRSubmissionValidator:
    
    def validate_crr_record(self, record):
        """Validate Chart Review Record"""
        
        validations = {
            'member_id': {
                'required': True,
                'format': r'^[A-Z0-9]{15}$',
                'check': self.member_exists_in_enrollment
            },
            'icd10_code': {
                'required': True,
                'format': r'^[A-Z][0-9]{2}\.[A-Z0-9]{1,4}$',
                'check': self.icd10_valid_for_date
            },
            'hcc_code': {
                'required': True,
                'format': r'^HCC[0-9]{1,3}$',
                'check': self.hcc_maps_from_icd10
            },
            'reviewer_credentials': {
                'required': True,
                'allowed_credentials': ['RN', 'MD', 'RHIA'],
                'check': self.reviewer_qualified
            },
            'review_date': {
                'required': True,
                'must_be_within': 12,  # months of service date
                'check': self.is_timely
            }
        }
        
        validation_results = {}
        for field, rules in validations.items():
            result = self.run_validations(record[field], rules)
            validation_results[field] = result
        
        return validation_results
    
    def icd10_valid_for_date(self, code, service_date):
        """Check ICD-10 code validity for service date"""
        # ICD-10 codes change October 1 annually
        fiscal_year = 2024 if service_date.month < 10 else 2025
        valid_codes = self.get_valid_icd10_codes(fiscal_year)
        
        return code in valid_codes
    
    def hcc_maps_from_icd10(self, hcc, icd10, service_year):
        """Verify HCC is valid mapping from ICD-10 for service year"""
        crosswalk = self.get_hcc_crosswalk(service_year)
        
        valid_hccs = crosswalk.get(icd10, [])
        return hcc in valid_hccs
```

---

## 2. HEDIS & STAR Ratings Reporting

### 2.1 HEDIS Measure Submission

**Regulatory Authority:** NCQA (National Committee for Quality Assurance)

**Submission Timeline:**

```
May 1: Data cutoff (calendar year ending April 30)
May 15: Submission window opens
June 30: Submission deadline
July-Sept: NCQA audit of submitted measures
October: Public reporting of measures and STARS
```

**Core Measure Categories:**

```sql
CREATE TABLE hedis_measures_catalog (
    measure_code VARCHAR(20) PRIMARY KEY,  -- e.g., 'IDD_E'
    measure_name VARCHAR(200),
    measure_category VARCHAR(50),  -- 'Effectiveness', 'Access', 'Experience', etc.
    
    numerator_definition TEXT,
    denominator_definition TEXT,
    exclusions TEXT,
    
    data_sources VARCHAR(500),  -- Claims, EHR, Medical Records, Survey
    
    stars_measure BOOLEAN,
    stars_domain VARCHAR(50),  -- 'Effective Care', 'Quality', etc.
    
    service_year INT
);

-- Example HEDIS measures
INSERT INTO hedis_measures_catalog VALUES
('IDD_E', 'Diabetes: Eye Exam', 'Effectiveness of Care',
 'Members 18-75 with diabetes who had eye exam in measurement year',
 'Members 18-75 with Type 1 or 2 diabetes',
 'Pregnancy, vision loss, blindness',
 'Claims, EHR, Medical Records', TRUE, 'Effective Care', 2024),

('IDD_A', 'Diabetes: Hemoglobin A1C Control', 'Effectiveness of Care',
 'Members 18-75 with diabetes AND A1C < 8.0%',
 'Members 18-75 with Type 1 or 2 diabetes',
 'End-stage renal disease, dialysis',
 'Lab Results, EHR, Medical Records', TRUE, 'Effective Care', 2024),

('CAD_A', 'Coronary Artery Disease: Beta-Blocker After MI', 'Effectiveness of Care',
 'Members 18+ with CAD who received beta-blocker within 3 days of MI',
 'Members 18+ with MI during measurement year',
 'Contraindications to beta-blockers',
 'Claims, Medical Records', TRUE, 'Effective Care', 2024);
```

### 2.2 STARS Rating Calculation

**Formula:** Quality measures aggregated by domain, weighted by importance

```python
class STARSRatingCalculator:
    
    def calculate_stars_rating(self, plan_data, service_year=2024):
        """
        STARS Rating = weighted average of measure performance
        
        Domain Weights (2024):
        - Staying Healthy: 25%
        - Managing Chronic Conditions: 25%
        - Member Satisfaction: 15%
        - Care Coordination: 10%
        - Safety: 15%
        - Plan Responsiveness: 10%
        """
        
        measures = {
            'Staying Healthy': {
                'IDD_E': 0.45,  # Diabetes Eye Exam (measure weight)
                'IDD_P': 0.35,  # Diabetes Prevention
                'CCS': 0.20,    # Cancer Screenings
            },
            'Managing Chronic Conditions': {
                'IDD_A': 0.40,  # Diabetes A1C Control
                'CAD_A': 0.35,  # CAD Beta-Blocker
                'CHF_A': 0.25,  # CHF Management
            },
            'Member Satisfaction': {
                'CAHPS_RATING': 0.50,  # Member rating of plan
                'CAHPS_COMMUNICATION': 0.50,
            },
            'Care Coordination': {
                'READMISSION': 0.50,  # 30-day readmission rate
                'DSCH_PLANNING': 0.50,
            },
            'Safety': {
                'FALLS_RISK': 0.50,
                'MEDICATION_REVIEW': 0.50,
            },
            'Plan Responsiveness': {
                'COMPLAINT_RESPONSE': 0.50,
                'APPEALS_RESPONSE': 0.50,
            }
        }
        
        domain_scores = {}
        
        for domain, domain_measures in measures.items():
            domain_score = 0
            total_weight = sum(domain_measures.values())
            
            for measure_code, measure_weight in domain_measures.items():
                measure_result = plan_data.get(measure_code, 0)  # 0-100%
                
                # Convert to 1-5 STARS scale
                # 90-100% = 5 stars, 70-89% = 4 stars, etc.
                measure_stars = self.convert_percentage_to_stars(measure_result)
                
                domain_score += (measure_stars * measure_weight / total_weight)
            
            domain_scores[domain] = domain_score
        
        # Calculate final rating
        weights = {
            'Staying Healthy': 0.25,
            'Managing Chronic Conditions': 0.25,
            'Member Satisfaction': 0.15,
            'Care Coordination': 0.10,
            'Safety': 0.15,
            'Plan Responsiveness': 0.10,
        }
        
        overall_stars = sum(
            domain_scores[domain] * weight
            for domain, weight in weights.items()
        )
        
        return {
            'overall_stars': round(overall_stars, 1),
            'domain_scores': domain_scores,
            'measure_results': plan_data,
            'revenue_impact': self.calculate_stars_bonus(round(overall_stars, 1))
        }
    
    def calculate_stars_bonus(self, stars_rating):
        """
        Quality Bonus Payment (QBP) calculation
        Plans with 4.0+ stars receive bonus payments
        """
        # 2024 thresholds
        bonuses = {
            5.0: 0.10,   # 10% bonus
            4.5: 0.075,  # 7.5% bonus
            4.0: 0.05,   # 5% bonus
            3.5: 0.025,  # 2.5% bonus
            0.0: 0.0     # No bonus
        }
        
        for stars_threshold in sorted(bonuses.keys(), reverse=True):
            if stars_rating >= stars_threshold:
                return bonuses[stars_threshold]
        
        return 0.0
```

### 2.3 Gap Closure Tracking for HEDIS

```sql
-- Integrated gap closure analytics
CREATE TABLE hedis_gap_analytics (
    gap_id BIGINT PRIMARY KEY,
    member_id VARCHAR(50),
    plan_id UUID,
    service_year INT,
    
    -- HEDIS Measure Mapping
    hedis_measure_code VARCHAR(20),  -- 'IDD_E', 'CAD_A', etc.
    gap_description VARCHAR(200),  -- 'No eye exam in past year'
    
    -- Service Required to Close Gap
    required_service_code VARCHAR(20),  -- CPT, HCPCS
    required_service_description VARCHAR(200),
    
    -- Diagnosis(s) to Document
    target_hcc_code VARCHAR(10),  -- Documenting this HCC closes the gap
    target_icd10_code VARCHAR(7),
    
    -- Gap Lifecycle
    gap_identified_date DATE,
    gap_due_date DATE,  -- By end of measurement year (April 30)
    gap_closed_date DATE,
    
    days_to_close INT GENERATED ALWAYS AS (DATEDIFF(day, gap_identified_date, gap_closed_date)),
    
    -- Closure method
    closure_method VARCHAR(50),  -- 'CLAIMS', 'CHART_REVIEW', 'MEMBER_SERVICE'
    closing_provider_npi VARCHAR(10),
    
    -- Financial Impact
    raf_increase_from_closure NUMERIC(10,4),
    estimated_annual_member_revenue = raf_increase_from_closure * 10400,
    
    -- STARS impact
    stars_domain_affected VARCHAR(50),  -- 'Effective Care', 'Staying Healthy', etc.
    stars_points_value NUMERIC(5,3),  -- Contribution to STARS rating
    
    -- Gap Status
    gap_status VARCHAR(20),  -- 'OPEN', 'PENDING', 'CLOSED', 'FAILED'
    
    created_at TIMESTAMP
);

-- Dashboard: Gap closure rate by measure
SELECT
    hedis_measure_code,
    COUNT(*) as total_gaps,
    COUNT(CASE WHEN gap_closed_date IS NOT NULL THEN 1 END) as closed_gaps,
    ROUND(100.0 * COUNT(CASE WHEN gap_closed_date IS NOT NULL THEN 1 END)
        / NULLIF(COUNT(*), 0), 1) as closure_rate,
    
    AVG(days_to_close) as avg_days_to_close,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY days_to_close) as median_days,
    PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY days_to_close) as p90_days,
    
    SUM(CASE WHEN gap_closed_date IS NOT NULL THEN estimated_annual_member_revenue ELSE 0 END) as revenue_impact,
    
    SUM(CASE WHEN gap_closed_date IS NOT NULL THEN stars_points_value ELSE 0 END) as stars_impact
FROM hedis_gap_analytics
WHERE service_year = 2024
  AND gap_due_date <= CURRENT_DATE
GROUP BY hedis_measure_code
ORDER BY closure_rate DESC;
```

---

## 3. Data Quality & Audit Requirements

### 3.1 CMS Edits & Validation

**CMS Performs Multi-Layered Validation:**

```python
class CMS_Validation_Framework:
    """
    Mimics CMS MA EDS validation layers
    """
    
    SYNTACTICAL_EDITS = {
        'S1': 'Member ID missing or invalid format',
        'S2': 'Service date range invalid (from > to)',
        'S3': 'NPI format invalid (not 10 digits)',
        'S4': 'ICD-10 code invalid format',
        'S5': 'Diagnosis count exceeds 25',
        'S6': 'Required fields missing',
    }
    
    LOGICAL_EDITS = {
        'L1': 'Diagnosis not compatible with member age',
        'L2': 'Diagnosis not compatible with sex',
        'L3': 'Conflicting diagnoses (both present and not present)',
        'L4': 'Invalid place of service for service type',
        'L5': 'Diagnosis code not valid for service date (ICD-10 effective date)',
    }
    
    CONTENT_EDITS = {
        'C1': 'Member not enrolled on service date',
        'C2': 'Service date after termination date',
        'C3': 'Provider NPI not valid/active',
        'C4': 'Duplicate encounter (exact duplicate)',
        'C5': 'Conflicting encounter (adjustment reconciliation needed)',
    }
    
    @staticmethod
    def apply_all_validations(encounter):
        results = {
            'syntactical_errors': [],
            'logical_errors': [],
            'content_errors': [],
            'warnings': [],
            'accepted': False
        }
        
        # Layer 1: Syntactical
        if not CMS_Validation_Framework.validate_syntax(encounter):
            results['syntactical_errors'].append('Format violation')
            return results  # Stop processing
        
        # Layer 2: Logical
        if not CMS_Validation_Framework.validate_logic(encounter):
            results['logical_errors'].append('Logic violation')
            # May still accept with warning
        
        # Layer 3: Content
        if not CMS_Validation_Framework.validate_content(encounter):
            results['content_errors'].append('Content violation')
        
        # Determine acceptance
        results['accepted'] = len(results['syntactical_errors']) == 0
        
        return results
```

### 3.2 NCQA Audit Preparation

**NCQA Audits 25-33% of submitted data (random sample)**

```sql
-- Audit trail for NCQA compliance
CREATE TABLE ncqa_audit_trail (
    audit_event_id BIGINT PRIMARY KEY,
    
    -- Audit Context
    audit_date TIMESTAMP,
    audit_type VARCHAR(50),  -- 'SAMPLE_SELECTION', 'VALIDATION', 'CERTIFICATION'
    
    -- HEDIS Measure
    hedis_measure_code VARCHAR(20),
    
    -- Beneficiary
    member_id VARCHAR(50),
    member_dob DATE,
    
    -- Numerator/Denominator
    denominator_eligible BOOLEAN,
    numerator_criterion_met BOOLEAN,
    
    -- Evidence Review
    evidence_reviewed VARCHAR(500),  -- Claims, medical record, lab results
    evidence_validation_status VARCHAR(20),  -- 'CONFIRMED', 'QUESTIONABLE', 'NOT_MET'
    
    -- Coder/Reviewer
    reviewed_by_user_id VARCHAR(50),
    reviewer_credentials VARCHAR(50),  -- 'RN', 'RHIA', 'MD'
    
    -- Quality Metrics
    data_completeness_score NUMERIC(3,2),
    accuracy_score NUMERIC(3,2),
    
    -- Documentation
    audit_notes TEXT,
    
    created_at TIMESTAMP,
    UNIQUE(hedis_measure_code, member_id, audit_date)
);

-- Audit sample selection (stratified random)
WITH audit_sample AS (
    SELECT
        hedis_measure_code,
        member_id,
        
        ROW_NUMBER() OVER (
            PARTITION BY hedis_measure_code
            ORDER BY RANDOM()
        ) as sample_rank
    FROM hedis_gap_analytics
    WHERE service_year = 2024
      AND gap_status = 'CLOSED'
)
SELECT *
FROM audit_sample
WHERE sample_rank <= CEIL(
    (SELECT COUNT(*) FROM audit_sample) * 0.30  -- 30% sample size
)
ORDER BY hedis_measure_code, sample_rank;
```

---

## 4. Risk Adjustment Model Updates & Transitions

### 4.1 CMS-HCC Model Versioning

**Historical Timeline:**
- 2004-2006: HCC v1.0
- 2007-2013: HCC v12, v21-v22
- 2014-2022: HCC v23-v24
- 2024: HCC v28 (significant redesign)
- 2025+: HCC v29, v30 (projected)

**V28 Model Changes (2024):**

```sql
CREATE TABLE hcc_model_version_comparison (
    comparison_id BIGINT PRIMARY KEY,
    
    hcc_model_version VARCHAR(10),  -- 'V24', 'V28'
    effective_year INT,
    
    -- Structural changes
    total_hcc_categories INT,
    total_mapped_icd10_codes INT,
    
    -- V24: 86 HCC categories, 9797 ICD-10 codes
    -- V28: 115 HCC categories, 7770 ICD-10 codes
    
    -- Key changes
    change_description VARCHAR(500)
);

-- V28 Constraining Example: Diabetes coefficients
INSERT INTO hcc_model_version_comparison VALUES
(1, 'V24', 2023, 86, 9797,
 'HCC18 (Diabetes w/o complications): 0.302
  HCC19 (Diabetes w/ complications): 0.288
  Total for member with both: 0.590'),

(2, 'V28', 2024, 115, 7770,
 'HCC18 & HCC19 constrained to single coefficient: 0.166
  Impact: -72% reduction for members with both diagnoses');

-- Blended transition (2023 data collection)
CREATE TABLE hcc_v24_v28_blended_scoring (
    member_id VARCHAR(50),
    service_year INT,
    
    -- V24 calculation (67% weight in 2023)
    raf_v24 NUMERIC(10,4),
    
    -- V28 calculation (33% weight in 2023)
    raf_v28 NUMERIC(10,4),
    
    -- Blended result
    raf_blended = (raf_v24 * 0.67) + (raf_v28 * 0.33) NUMERIC(10,4),
    
    -- Full V28 (100% weight in 2024 forward)
    raf_v28_final NUMERIC(10,4),
    
    -- Impact analysis
    revenue_impact_v24_to_v28 = (raf_v28_final - raf_v24) * 10400
);
```

### 4.2 Transition Management

```python
class HCCModelTransitionManager:
    """
    Manage multi-year transitions between HCC models
    """
    
    def calculate_raf_with_model_version(self, member, service_year):
        """
        Select appropriate model version for service year
        """
        model_mapping = {
            2023: {
                'primary_model': 'V24',
                'secondary_model': 'V28',
                'blending': (0.67, 0.33)  # 67% V24, 33% V28
            },
            2024: {
                'primary_model': 'V28',
                'secondary_model': None,
                'blending': (1.0, 0.0)  # 100% V28
            },
            2025: {
                'primary_model': 'V29',  # Projected
                'secondary_model': None,
                'blending': (1.0, 0.0)
            }
        }
        
        model_config = model_mapping[service_year]
        
        # Calculate with primary model
        raf_primary = self.calculate_raf(member, model_config['primary_model'])
        
        if model_config['secondary_model']:
            # Blended calculation
            raf_secondary = self.calculate_raf(member, model_config['secondary_model'])
            primary_weight, secondary_weight = model_config['blending']
            
            raf_final = (raf_primary * primary_weight) + (raf_secondary * secondary_weight)
        else:
            raf_final = raf_primary
        
        return {
            'service_year': service_year,
            'model_version': model_config['primary_model'],
            'final_raf': raf_final,
            'revenue_estimate': raf_final * self.cms_base_rate()
        }
    
    def communicate_model_changes(self, stakeholders=['plans', 'providers', 'clinicians']):
        """
        Prepare communication materials for model transitions
        """
        changes_by_audience = {
            'plans': {
                'financial_impact': 'Average RAF impact: -3.12% in 2024 V24->V28',
                'member_communication': 'No member-facing changes required',
                'system_updates': 'Update HCC mapping tables, coefficient lookup'
            },
            'providers': {
                'coding_changes': 'More detailed ICD-10 specificity required',
                'revenue_impact': 'RAF scores may decrease; document carefully',
                'training': 'CDI team training on new HCC codes'
            },
            'clinicians': {
                'documentation': 'Accurate, specific diagnoses matter more',
                'examples': 'Diabetes: specify type, complications, other factors',
                'resources': 'Provide HCC code lookup tool, coding guidelines'
            }
        }
        
        return changes_by_audience
```

---

## 5. Compliance Checklist

### Pre-Submission Validation

```yaml
CMS_SUBMISSION_CHECKLIST:
  
  DATA_COMPLETENESS:
    - [] All required fields present in EDI 837 records
    - [] Service dates within CMS submission window
    - [] Member enrollment validation (service date within coverage)
    - [] No gaps in serial claim submissions (>30 days investigated)
  
  ACCURACY_VALIDATION:
    - [] ICD-10 codes valid for service date
    - [] NPI valid and active provider
    - [] Place of service compatible with service type
    - [] Age/sex compatibility with diagnoses
    - [] Diagnosis sequence order correct
  
  DUPLICATE_PREVENTION:
    - [] No exact claim duplicates
    - [] Adjusted claims properly linked to original
    - [] Member-month records unique
    - [] Deduplication logic documented
  
  HCC_MAPPING:
    - [] All diagnoses mapped to correct HCC (using CMS crosswalk)
    - [] Hierarchies applied correctly
    - [] Constraining rules enforced (V28)
    - [] Mapping validation > 99%
  
  QUALITY_CONTROLS:
    - [] Data quality score > 95%
    - [] Acceptance rate > 98%
    - [] Outlier review completed
    - [] Reconciliation of claims vs EDR vs CRR complete
  
  AUDIT_PREPARATION:
    - [] NCQA audit trail complete
    - [] Sample selection documented
    - [] Reviewer credentials verified
    - [] Evidence retention (claims, medical records) = 10 years
  
  SUBMISSION_PROCESS:
    - [] File format validated (837 syntax)
    - [] Test submission successful
    - [] CMS EDI receipt confirmation obtained
    - [] Rejection reasons resolved (if any)
    - [] Final acceptance from CMS documented
```

---

## References & Resources

**CMS Official Documentation:**
- [42 CFR §422.504 - Risk Adjustment Data Submission](https://www.cms.gov/)
- [CMS-HCC Model Documentation](https://www.cms.gov/Medicare/Health-Plans/MedicareAdvtgSpecRateStats/Risk-Adjusters-01012024.html)
- [MA EDS Submission & Processing Guide](https://www.csscoperations.com/)

**NCQA Standards:**
- [HEDIS Technical Specifications](https://www.ncqa.org/hedis/)
- [STARS Measure Set](https://www.cms.gov/Medicare/Prescription-Drug-Coverage/PrescriptionDrugCovContra/CMS-Star-Ratings.html)

**Industry Resources:**
- [AAPC HCC Coding Guide](https://www.aapc.com/blog/)
- [ICD-10 to HCC Crosswalk (Annual Update)](https://www.cms.gov/)
- [CMS HCC Model V28 Documentation](https://www.cms.gov/)

