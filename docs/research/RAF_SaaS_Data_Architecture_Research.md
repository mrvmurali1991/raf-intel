# Risk Adjustment Factor (RAF) SaaS Platform: Data Architecture & Analytics Research

## Executive Summary

This document provides technical guidance for building a Risk Adjustment Factor (RAF) SaaS platform, covering data models, calculation engines, data warehouses, analytics, reporting, and operational patterns. RAF is a relative measure of predicted costs for beneficiary healthcare based on diagnoses and demographics. A RAF score of 1.0 represents baseline Medicare beneficiary; every 0.1 increase = ~$1,040 additional annual revenue per member.

---

## 1. DATA MODELS FOR CORE ENTITIES

### 1.1 Patient Demographics Model

**Core Entities:**
- Age (granular: age at enrollment, age at service date)
- Sex/Gender
- Residence type (community, skilled nursing facility, institution, unknown)
- Disability status
- Medicaid dual eligibility indicator
- Enrollment segments (Medicare only, Medicare+Medicaid, SNP type)
- Plan attribution and assignment date

**Sample Relational Schema:**

```sql
CREATE TABLE patient_demographics (
    patient_id UUID PRIMARY KEY,
    member_id VARCHAR(50) UNIQUE NOT NULL,
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    date_of_birth DATE NOT NULL,
    sex_code CHAR(1) CHECK (sex_code IN ('M', 'F', 'U')),
    
    -- Current enrollment attributes
    enrollment_status VARCHAR(20),  -- 'Active', 'Terminated', 'Suspended'
    enrollment_date DATE NOT NULL,
    termination_date DATE,
    
    -- CMS-specific attributes
    residence_code VARCHAR(10),  -- '00'=Community, '01'=SNF, '02'=Institution
    disability_indicator BOOLEAN,
    medicaid_dual_eligible BOOLEAN,
    ltc_dual_eligible BOOLEAN,
    
    -- Plan assignment
    plan_id UUID NOT NULL,
    plan_segment_code VARCHAR(10),  -- 'MA001', 'MA002', etc.
    plan_name VARCHAR(200),
    
    -- Geography
    zip_code VARCHAR(5),
    county_fips_code VARCHAR(5),
    state_code CHAR(2),
    
    -- Audit fields
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    data_source_code VARCHAR(20)  -- 'CLAIMS', 'EHR', 'CHART_REVIEW'
);

-- Indexes for common queries
CREATE INDEX idx_member_id ON patient_demographics(member_id);
CREATE INDEX idx_plan_id_status ON patient_demographics(plan_id, enrollment_status);
CREATE INDEX idx_enrollment_date ON patient_demographics(enrollment_date, termination_date);
```

### 1.2 Encounter/Service Event Model

**Key Characteristics:**
- Single encounter per claim/visit/service line
- Supports multiple claim sources: professional (837P), institutional (837I), dental, pharmacy
- Links diagnoses to encounters (1-to-many)
- Captures adjusted/corrected encounter submissions

```sql
CREATE TABLE encounters (
    encounter_id BIGINT PRIMARY KEY,
    patient_id UUID NOT NULL,
    member_id VARCHAR(50) NOT NULL,
    plan_id UUID NOT NULL,
    
    -- Encounter timing
    service_from_date DATE NOT NULL,
    service_to_date DATE,  -- NULL for single-day encounters
    encounter_type_code VARCHAR(10),  -- '11'=Office visit, '21'=Inpatient, etc.
    
    -- Claims metadata
    claim_id VARCHAR(50),
    claim_version_number INT DEFAULT 1,  -- Track adjustments/corrections
    claim_submission_date DATE,
    claim_adjustment_flag BOOLEAN DEFAULT FALSE,
    original_claim_id VARCHAR(50),  -- If this is an adjustment
    
    -- Provider information
    provider_npi VARCHAR(10),
    provider_specialty_code VARCHAR(10),
    facility_npi VARCHAR(10),
    
    -- Service details
    cpt_code VARCHAR(5),
    hcpcs_code VARCHAR(5),
    revenue_code VARCHAR(4),
    
    -- Financial
    allowed_amount NUMERIC(12,2),
    billed_amount NUMERIC(12,2),
    paid_amount NUMERIC(12,2),
    patient_responsibility NUMERIC(12,2),
    
    -- Processing
    claim_status VARCHAR(20),  -- 'Accepted', 'Denied', 'Adjusted'
    denial_reason_code VARCHAR(10),
    
    -- Data collection source
    data_source_code VARCHAR(20),  -- 'MA_ENCOUNTER', 'CHART_REVIEW', 'CHART_REVIEW_CORRECTED'
    submission_type VARCHAR(20),  -- 'EDR', 'CRR', 'CORRECTED'
    
    -- Audit
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    record_sequence_number INT  -- For deduplication
);

CREATE INDEX idx_patient_service_dates ON encounters(patient_id, service_from_date, service_to_date);
CREATE INDEX idx_claim_id ON encounters(claim_id, claim_version_number);
CREATE INDEX idx_provider_npi ON encounters(provider_npi);
CREATE INDEX idx_submission_type_status ON encounters(data_source_code, submission_type, claim_status);
```

### 1.3 Diagnosis Model with HCC Mappings

**Key Requirements:**
- Multiple ICD-10-CM codes per encounter (primary + secondary)
- CMS-official HCC mappings (updated annually, V24/V28/V29 support)
- Hierarchy rules (more severe subsumes less severe)
- Diagnosis present-on-arrival (POA) indicators
- Evidence source tracking (claims, EHR note, chart review)

```sql
CREATE TABLE encounter_diagnoses (
    diagnosis_id BIGINT PRIMARY KEY,
    encounter_id BIGINT NOT NULL,
    patient_id UUID NOT NULL,
    
    -- Diagnosis coding
    icd10_code VARCHAR(7) NOT NULL,  -- e.g., 'E11.65'
    icd10_description VARCHAR(500),
    diagnosis_sequence_number INT,  -- 1=primary, 2+ = secondary
    
    -- CMS HCC mappings (support multiple model versions)
    hcc_code_v24 VARCHAR(10),  -- e.g., 'HCC19'
    hcc_code_v28 VARCHAR(10),
    hcc_code_v29 VARCHAR(10),
    hcc_description VARCHAR(500),
    
    -- Hierarchy rules
    hcc_hierarchy_group VARCHAR(50),  -- Groups of related HCCs
    hcc_subsumption_rule VARCHAR(200),  -- Description of hierarchy
    
    -- Clinical indicators
    present_on_arrival BOOLEAN,
    is_primary_diagnosis BOOLEAN,
    
    -- Evidence source
    evidence_source_code VARCHAR(20),  -- 'CLAIMS', 'EHR', 'CHART_REVIEW', 'CDI'
    evidence_confidence_score NUMERIC(3,2),  -- 0.0 to 1.0
    
    -- Chart review tracking
    chart_review_date DATE,
    chart_reviewer_id VARCHAR(50),
    chart_review_validation_status VARCHAR(20),  -- 'VALIDATED', 'REJECTED', 'PENDING'
    
    -- Audit
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE INDEX idx_patient_hcc ON encounter_diagnoses(patient_id, hcc_code_v28);
CREATE INDEX idx_icd10_hcc ON encounter_diagnoses(icd10_code, hcc_code_v28);
CREATE INDEX idx_source_validation ON encounter_diagnoses(evidence_source_code, chart_review_validation_status);
```

---

## 2. RAF SCORE CALCULATION ENGINE

### 2.1 Calculation Architecture: Batch vs Real-Time

**Batch Processing (Primary):**
- Monthly: Incremental RAF recalculation for new encounters
- Year-end: Full RAF recalculation for all beneficiaries (CMS submissions)
- Processing window: T+5 to T+35 days after month-end
- Used for: Historical trending, bid forecasting, regulatory submissions

**Real-Time Processing (Secondary):**
- Gap closure workflows: Suspect condition identification → outreach
- Member attribution changes
- Plan enrollment changes
- Used for: Care coordination, provider dashboards

### 2.2 RAF Calculation Pipeline

```sql
-- 1. Create member-month summary: validate eligible diagnoses
CREATE TABLE raf_calculation_staging (
    raf_calc_id BIGINT PRIMARY KEY,
    patient_id UUID NOT NULL,
    member_id VARCHAR(50),
    plan_id UUID,
    
    -- Calculation period
    service_year INT,  -- 2024, 2025, etc.
    data_collection_month DATE,
    calculation_run_date TIMESTAMP,
    
    -- Demographic factors (age sex category)
    age_sex_category VARCHAR(20),  -- 'F65_69', 'M70_74', etc.
    age_sex_factor NUMERIC(10,4),
    
    -- Medicaid/institutional adjustments
    medicaid_dual_factor NUMERIC(10,4),
    ltc_institutional_factor NUMERIC(10,4),
    
    -- Eligible diagnoses for this member-month
    unique_hcc_count INT,
    hcc_list TEXT,  -- JSON array of {hcc_code, icd10_code, evidence_source}
    
    -- Raw scores
    demographic_risk_score NUMERIC(10,4),
    disease_risk_score NUMERIC(10,4),
    
    -- RAF calculation
    raw_raf_score NUMERIC(10,4),
    coding_intensity_adjustment NUMERIC(10,4),
    budget_neutrality_factor NUMERIC(10,4),
    final_raf_score NUMERIC(10,4),
    
    -- Validation
    calculation_status VARCHAR(20),  -- 'COMPLETE', 'ERROR', 'PENDING_REVIEW'
    validation_notes TEXT,
    
    created_at TIMESTAMP
);

-- 2. HCC Coefficients (CMS-provided, updated annually)
CREATE TABLE hcc_coefficients (
    coefficient_id BIGINT PRIMARY KEY,
    hcc_model_version VARCHAR(10),  -- 'V24', 'V28', 'V29'
    hcc_model_effective_date DATE,
    
    hcc_code VARCHAR(10),
    hcc_description VARCHAR(500),
    
    -- Risk coefficients by demographic group
    age_sex_category VARCHAR(20),
    coefficient_value NUMERIC(10,6),
    
    -- Hierarchy information
    hcc_group VARCHAR(50),
    is_hierarchical BOOLEAN,
    subsumes_hcc_code VARCHAR(10),  -- If hierarchical, which HCC does this override
    
    created_at TIMESTAMP
);

-- 3. Hierarchy application rules
CREATE TABLE hcc_hierarchies (
    hierarchy_id BIGINT PRIMARY KEY,
    hcc_model_version VARCHAR(10),
    
    parent_hcc_code VARCHAR(10),  -- More severe
    child_hcc_code VARCHAR(10),   -- Less severe (subsumed)
    hierarchy_rule_description VARCHAR(500),
    
    -- CMS V28 Constraining example: diabetes
    constraining_group VARCHAR(50),  -- 'DIABETES_FAMILY'
    constrained_coefficient NUMERIC(10,6)
);
```

### 2.3 Calculation Algorithm (Pseudocode)

```python
def calculate_member_raf(member_id, service_year, data_collection_date):
    """
    CMS RAF Calculation Algorithm
    """
    member = get_patient_demographics(member_id, data_collection_date)
    
    # Step 1: Get age-sex factor (demographic component)
    age = calculate_age(member.dob, data_collection_date)
    sex = member.sex_code
    age_sex_category = get_age_sex_category(age, sex)
    demographic_score = get_coefficient('DEMO', age_sex_category, service_year)
    
    # Step 2: Collect eligible diagnoses
    eligible_diagnoses = get_encounters_diagnoses(
        patient_id=member.patient_id,
        service_year=service_year,
        data_source=['MA_ENCOUNTER', 'CHART_REVIEW'],
        submission_status=['ACCEPTED', 'VALIDATED']
    )
    
    # Step 3: Map diagnoses to HCCs (using annual model version)
    hcc_model_version = get_hcc_model_for_year(service_year)  # V28 for 2024
    hcc_mappings = get_hcc_mappings(eligible_diagnoses, hcc_model_version)
    
    # Step 4: Apply hierarchy rules (more severe subsumes less severe)
    applied_hccs = apply_hcc_hierarchies(hcc_mappings, hcc_model_version)
    
    # Step 5: Look up disease coefficients
    disease_score = 0
    for hcc in applied_hccs:
        age_sex_cat = get_age_sex_category(age, sex)
        hcc_coefficient = get_coefficient(
            hcc_code=hcc,
            age_sex_category=age_sex_cat,
            model_version=hcc_model_version,
            service_year=service_year
        )
        disease_score += hcc_coefficient
    
    # Step 6: Apply dual/LTC institutional factors
    if member.medicaid_dual_eligible:
        disease_score *= 1.10  # Approximate medicaid adjustment
    if member.residence_code == '02':  # Institutional
        disease_score *= 0.95
    
    # Step 7: Calculate raw RAF
    raw_raf = demographic_score + disease_score
    
    # Step 8: Apply budget neutrality and coding intensity adjustments
    budget_neutrality_factor = get_budget_neutrality_factor(service_year)
    coding_intensity_adj = apply_coding_intensity_adjustment(
        member_plan=member.plan_id,
        service_year=service_year
    )
    
    final_raf = raw_raf * budget_neutrality_factor * (1 + coding_intensity_adj)
    
    return {
        'member_id': member_id,
        'service_year': service_year,
        'age_sex_factor': demographic_score,
        'disease_risk_factor': disease_score,
        'applied_hccs': applied_hccs,
        'raw_raf': raw_raf,
        'final_raf': final_raf,
        'evidence_sources': [d.evidence_source for d in eligible_diagnoses]
    }
```

### 2.4 Batch Processing Architecture (Monthly/Annual Cycles)

```python
# Batch RAF Calculation Job
BATCH_CONFIG = {
    'monthly_incremental': {
        'schedule': 'First day of month T+5 through T+35',
        'lookback_window': '30 days',
        'scope': 'New encounters since last run',
        'parallelism': 'By plan_id (partition)',
        'checkpoint': 'Encounter ID high water mark'
    },
    'year_end_full': {
        'schedule': 'Jan 1 - Feb 28 of following year',
        'lookback_window': '365 days (full service year)',
        'scope': 'All active members',
        'parallelism': 'By plan_id shards × 4-8 workers',
        'checkpoint': 'Member ID range completion'
    },
    'sweep_reconciliation': {
        'schedule': 'March - May (post CMS reconciliation)',
        'scope': 'Members with RAF changes > 0.05',
        'trigger': 'CMS payment adjustment file ingestion'
    }
}

# Implementation: Spark/Databricks or Airflow + SQL
class RAFBatchCalculator:
    def run_monthly_incremental(self, execution_date):
        """
        Incremental RAF recalculation for new encounters
        """
        # 1. Load new encounters since last checkpoint
        new_encounters = spark.sql("""
            SELECT DISTINCT patient_id, member_id, plan_id
            FROM encounters
            WHERE created_at >= date_sub(current_timestamp(), 35)
              AND data_source_code IN ('MA_ENCOUNTER', 'CHART_REVIEW')
              AND claim_status IN ('Accepted', 'Validated')
        """)
        
        # 2. Recalculate RAF for affected members
        raf_results = new_encounters.repartition('plan_id').apply(
            self.calculate_member_raf_vectorized
        )
        
        # 3. Store results
        raf_results.write.insertInto('raf_calculation_results')
        
        # 4. Log checkpoint
        self.update_checkpoint('monthly_incremental', execution_date)
    
    def run_year_end_full(self, service_year):
        """
        Full RAF recalculation for CMS submission
        """
        # 1. Get all active members for service year
        active_members = spark.sql(f"""
            SELECT patient_id, member_id, plan_id
            FROM patient_demographics
            WHERE plan_id IN (SELECT plan_id FROM active_plans)
              AND enrollment_date <= '{service_year}-12-31'
              AND (termination_date IS NULL OR termination_date >= '{service_year}-01-01')
        """)
        
        # 2. Parallel RAF calculation by plan shards
        raf_results = active_members.repartition(
            numPartitions=32,
            partitionBy='plan_id'
        ).apply(self.calculate_member_raf_vectorized)
        
        # 3. Validation checks
        self.validate_raf_results(raf_results, service_year)
        
        # 4. Generate CMS submission file
        cms_submission = self.generate_cms_submission_file(raf_results)
        cms_submission.coalesce(1).write.csv(
            f's3://raf-submissions/{service_year}/cms_mao_004_file.csv'
        )
```

---

## 3. DATA WAREHOUSE SCHEMA FOR RISK ADJUSTMENT ANALYTICS

### 3.1 Dimensional Star Schema Design

**Core Pattern:** Fact tables (quantitative measures) + Dimension tables (descriptive context)

```sql
-- FACT TABLE: Monthly Member RAF Summary
CREATE TABLE fact_member_raf_monthly (
    raf_fact_id BIGINT PRIMARY KEY,
    
    -- Dimensional keys
    patient_dim_id INT,
    plan_dim_id INT,
    time_dim_id INT,  -- Month-year: 202401, 202402, etc.
    provider_dim_id INT,
    
    -- Measures
    raf_score NUMERIC(10,4),
    raw_raf_score NUMERIC(10,4),
    demographic_risk_factor NUMERIC(10,4),
    disease_risk_factor NUMERIC(10,4),
    
    hcc_count INT,
    unique_diagnoses_count INT,
    encounter_count INT,
    
    -- Revenue impact
    estimated_annual_revenue NUMERIC(14,2),  -- RAF * CMS base rate
    previous_month_raf NUMERIC(10,4),
    raf_change NUMERIC(10,4),
    
    -- Data quality
    data_completeness_score NUMERIC(3,2),
    evidence_source_code VARCHAR(20),
    chart_review_flag BOOLEAN,
    
    created_at TIMESTAMP
);

-- DIMENSION: Patient/Member
CREATE TABLE dim_patient (
    patient_dim_id INT PRIMARY KEY,
    patient_id UUID,
    member_id VARCHAR(50),
    
    member_name VARCHAR(200),
    date_of_birth DATE,
    age INT,
    age_group VARCHAR(20),  -- '65-69', '70-74', etc.
    sex CHAR(1),
    
    enrollment_status VARCHAR(20),
    residence_type VARCHAR(30),  -- Community, SNF, Institution
    medicaid_dual BOOLEAN,
    ltc_institutional BOOLEAN,
    
    zip_code VARCHAR(5),
    county_name VARCHAR(100),
    state VARCHAR(2),
    region VARCHAR(50),
    
    created_at TIMESTAMP,
    scd_effective_date DATE,  -- Slowly Changing Dimension Type 2
    scd_end_date DATE
);

-- DIMENSION: Plan/Contract
CREATE TABLE dim_plan (
    plan_dim_id INT PRIMARY KEY,
    plan_id UUID,
    plan_name VARCHAR(200),
    plan_code VARCHAR(50),
    plan_type VARCHAR(50),  -- MA-PD, MA-only, SNP, etc.
    parent_organization VARCHAR(200),
    
    service_year INT,
    cms_contract_id VARCHAR(20),
    
    market_region VARCHAR(100),
    state_code CHAR(2),
    
    enrollment_count INT,
    attributed_provider_count INT,
    
    created_at TIMESTAMP
);

-- DIMENSION: Time (Gregorian)
CREATE TABLE dim_time (
    time_dim_id INT PRIMARY KEY,
    date DATE UNIQUE,
    
    year INT,
    month INT,
    quarter INT,
    week INT,
    day_of_week INT,
    
    year_month VARCHAR(7),  -- '2024-01'
    year_quarter VARCHAR(7), -- '2024-Q1'
    
    is_month_end BOOLEAN,
    is_year_end BOOLEAN
);

-- DIMENSION: Diagnosis/HCC
CREATE TABLE dim_diagnosis (
    diagnosis_dim_id INT PRIMARY KEY,
    icd10_code VARCHAR(7),
    icd10_description VARCHAR(500),
    
    hcc_code_v28 VARCHAR(10),
    hcc_code_v29 VARCHAR(10),
    hcc_description VARCHAR(500),
    hcc_family VARCHAR(50),
    
    is_hierarchical BOOLEAN,
    subsumed_by_hcc VARCHAR(10),
    
    clinical_category VARCHAR(100),
    severity_indicator VARCHAR(20)
);

-- DIMENSION: Provider
CREATE TABLE dim_provider (
    provider_dim_id INT PRIMARY KEY,
    provider_npi VARCHAR(10),
    provider_name VARCHAR(200),
    provider_specialty VARCHAR(100),
    
    organization_name VARCHAR(200),
    organization_npi VARCHAR(10),
    
    state VARCHAR(2),
    county VARCHAR(100),
    
    attributed_member_count INT
);

-- FACT TABLE: Encounter-level detail (for drill-down)
CREATE TABLE fact_encounter (
    encounter_fact_id BIGINT PRIMARY KEY,
    
    patient_dim_id INT,
    plan_dim_id INT,
    time_dim_id INT,
    provider_dim_id INT,
    
    encounter_count INT DEFAULT 1,
    claim_amount NUMERIC(12,2),
    paid_amount NUMERIC(12,2),
    
    hcc_count INT,
    chart_review_generated_hcc_count INT,
    
    service_type VARCHAR(20),  -- 'Office Visit', 'Inpatient', etc.
    data_source VARCHAR(20),   -- 'MA_ENCOUNTER', 'CHART_REVIEW'
    
    created_at TIMESTAMP
);
```

### 3.2 Data Mart: Risk Adjustment Metrics

```sql
-- Aggregated risk metrics for dashboards
CREATE TABLE mart_raf_performance (
    performance_id BIGINT PRIMARY KEY,
    
    -- Grouping dimensions
    plan_id UUID,
    provider_npi VARCHAR(10),
    service_year INT,
    calculation_month DATE,
    
    -- RAF metrics
    total_members INT,
    members_with_claims INT,
    average_raf_score NUMERIC(10,4),
    median_raf_score NUMERIC(10,4),
    raf_percentile_25 NUMERIC(10,4),
    raf_percentile_75 NUMERIC(10,4),
    
    -- Gap closure
    members_with_gap_closures INT,
    gap_closures_count INT,
    gap_closure_revenue_impact NUMERIC(14,2),
    
    -- Coding intensity (RAF / expected)
    coding_intensity_ratio NUMERIC(10,4),  -- Actual / CMS expected
    
    -- Trend
    month_over_month_raf_change NUMERIC(10,4),
    year_over_year_raf_change NUMERIC(10,4),
    
    created_at TIMESTAMP
);
```

---

## 4. DASHBOARDS AND KPIs

### 4.1 Executive Dashboard KPIs

```yaml
RAF_REVENUE_DASHBOARD:
  total_attributed_members:
    measure: COUNT(member_id)
    filter: "enrollment_status = 'Active'"
    update_frequency: Daily
    
  total_raf_points:
    measure: SUM(raf_score)
    benchmark: Prior year same month
    variance_threshold: 3%
    
  estimated_annual_revenue:
    measure: "SUM(raf_score * cms_base_rate)"
    drill_down: By plan, provider, member segment
    
  revenue_variance_ytd:
    measure: "(Actual RAF - Forecast RAF) / Forecast RAF"
    variance_driver: New diagnoses, coding intensity, member churn
    
  gap_closure_revenue_impact:
    measure: "SUM(raf_increase * members_closed * cms_base_rate)"
    by: Provider, measure type, quarter
    
CODER_PRODUCTIVITY_DASHBOARD:
  members_reviewed_daily:
    measure: COUNT(DISTINCT patient_id) WHERE chart_review_date = TODAY
    by_coder_id: Individual productivity
    
  hccs_identified_per_review:
    measure: AVG(hcc_count) GROUP BY chart_reviewer_id
    benchmark: Team average = 2.3 HCCs/review
    
  validation_rate:
    measure: COUNT(validated) / COUNT(submitted)
    target: >95%
    
  suspected_conditions_accuracy:
    measure: "Actual HCCs / Suspected HCCs"
    by_condition: Diabetes, CHF, COPD accuracy tracking

QUALITY_METRICS_DASHBOARD:
  hedis_gap_count:
    measure: COUNT(gap_id) WHERE gap_closed_date IS NULL
    by: Measure type, member segment
    filter: "due_date < TODAY"
    
  gap_closure_rate:
    measure: "closed_gaps / eligible_gaps"
    by_period: Monthly, rolling 90-day
    trend: vs. prior year
    
  gap_closure_days_to_completion:
    measure: "AVG(DATEDIFF(day, identified_date, closed_date))"
    percentile_50: Median days
    percentile_90: 90th percentile (outliers)
    
  stars_rating_impact:
    measure: Estimated star rating based on gap rates
    revenue_impact: "STARS improvement × QBP incentive %"
    example: "3.0 -> 4.0 stars = 13.4-17.6% revenue increase"
```

### 4.2 Operational Dashboards

**Gap Closure Workflow Dashboard:**
- Suspects by condition (HCC19=Diabetes, HCC85=CHF, etc.)
- Outreach status (Not Started, In Progress, Completed, Failed)
- Average days-to-closure by measure type
- Provider engagement rate (# closing gaps / # assigned gaps)

**Data Quality Dashboard:**
- Claim acceptance rate (accepted / submitted)
- Encounter reconciliation status (EDR vs CRR submissions)
- Duplicate claims detected and resolved
- Patient matching accuracy (deduplication rate)
- ICD-10 to HCC mapping validation rate

---

## 5. REPORTING REQUIREMENTS FOR HEALTH PLANS

### 5.1 CMS Regulatory Submissions

**MAO-004 File (Monthly Risk Adjustment Data):**
- Due: Last day of month for prior month encounters
- Format: 837 claim records (professional, institutional)
- Content: Encounter data with diagnoses, demographics
- Contains: 9000+ ICD-10 codes mapped to HCC categories

**MAO-002 File (Annual Risk Adjustment Data):**
- Due: March 31 (for prior year)
- Content: Final RAF scores by member
- Submission: One record per enrolled member

**Chart Review Record (CRR):**
- Alternative to EDR for chart-identified diagnoses
- Format: Custom CMS format (not 837)
- Validation requirement: NCQA audit for public reporting

### 5.2 NCQA HEDIS & STAR Ratings (Annual)

**Submission Timeline:**
- Data Cutoff: December 31
- HEDIS Measure Codes: 90+ measures across 6 domains
  - Effectiveness of Care (30+ measures)
  - Access/Availability of Care (5+ measures)
  - Experience of Care (5-7 CAHPS questions)
  - Utilization and Risk-Adjusted Utilization (15+ measures)
  - Health Plan Descriptive Information

**Required Reporting Components:**
1. Measure-specific denominators & numerators
2. Medical record audit samples (NCQA-approved auditors)
3. Claims data validation
4. Supplemental analysis files
5. Data quality audit certification

**Star Rating Release:** October of following year

### 5.3 Internal Reporting Schedule

```yaml
MONTHLY_REPORTS:
  - RAF performance by plan, provider, member segment
  - Gap closure status and revenue impact
  - Claim submission metrics (acceptance rate, rejections)
  - Coder productivity and quality metrics
  
QUARTERLY_REPORTS:
  - HEDIS gap analysis and projection
  - Provider benchmarking and performance tiers
  - Bid forecast updates (if applicable)
  - Risk model changes impact analysis
  
ANNUAL_REPORTS:
  - Year-end RAF scores and CMS submission file
  - HEDIS results and STARS projection
  - Actuarial reconciliation vs. estimates
  - Next year assumption updates
```

---

## 6. DATA RECONCILIATION: CLAIMS, ENCOUNTERS, CHART REVIEW

### 6.1 Three-Way Reconciliation Framework

```sql
-- Claims vs. Encounters Reconciliation
CREATE TABLE reconciliation_three_way (
    reconciliation_id BIGINT PRIMARY KEY,
    
    member_id VARCHAR(50),
    service_date_from DATE,
    service_date_to DATE,
    
    -- Claims data
    claims_claim_id VARCHAR(50),
    claims_cpt_code VARCHAR(5),
    claims_paid_amount NUMERIC(12,2),
    claims_diagnoses_submitted INT,
    
    -- Encounter EDR (MAO submitted)
    encounter_edrs_submitted INT,
    encounter_npi VARCHAR(10),
    encounter_diagnoses_count INT,
    
    -- Chart Review CRR
    chart_review_submitted BOOLEAN,
    chart_review_additional_diagnoses INT,
    chart_review_date DATE,
    chart_reviewer_id VARCHAR(50),
    
    -- Reconciliation status
    match_status VARCHAR(20),  -- 'MATCHED', 'VARIANCE', 'UNMATCHED_CLAIM', 'UNMATCHED_EDR'
    variance_explanation VARCHAR(500),
    
    -- Diagnosis reconciliation
    icd10_variance TEXT,  -- JSON: claims vs EDR vs CRR codes
    hcc_assignment_match BOOLEAN,
    
    resolved_date DATE,
    resolution_notes TEXT
);

-- Key reconciliation checks:
-- 1. Claim exists in both claims system AND EDR submission
-- 2. Service dates align (within tolerance: +/- 1 day)
-- 3. Member/patient ID match
-- 4. Provider NPI match (if available)
-- 5. Diagnosis codes align (ICD-10 vs submitted ICD-10)
-- 6. Chart review diagnoses supplement (not duplicate) claims diagnoses

-- Tolerance thresholds:
-- - Service date variance: +/- 1 day
-- - Diagnosis count variance: +/- 10% or max 2 codes
-- - Amount variance: +/- 5% or max $100
```

### 6.2 Encounter Data Validation Workflow

```python
def validate_encounter_submission(encounter_batch):
    """
    Multi-stage validation similar to CMS MA EDS
    """
    results = {
        'syntax_errors': [],
        'logic_errors': [],
        'content_warnings': [],
        'accepted': [],
        'rejected': []
    }
    
    for encounter in encounter_batch:
        # Stage 1: Syntax/Format Validation
        syntax_check = validate_837_format(encounter)
        if not syntax_check.valid:
            results['syntax_errors'].append({
                'claim_id': encounter.claim_id,
                'errors': syntax_check.errors
            })
            continue
        
        # Stage 2: Content Validation
        content_checks = [
            validate_member_exists(encounter.member_id),
            validate_npi_format(encounter.provider_npi),
            validate_service_date_in_range(encounter.service_from_date),
            validate_cpt_hcpcs_codes(encounter.cpt_code),
            validate_icd10_codes(encounter.diagnosis_codes),
            validate_diagnosis_poa_indicators(encounter.poa_flags)
        ]
        
        failed_checks = [c for c in content_checks if not c.valid]
        if failed_checks:
            results['logic_errors'].extend(failed_checks)
            # Some are fatal (reject), others are warnings (accept + flag)
            if any(c.is_fatal for c in failed_checks):
                results['rejected'].append(encounter)
                continue
        
        # Stage 3: Deduplication & Matching
        duplicate_check = check_duplicate_encounter(
            member_id=encounter.member_id,
            service_date=encounter.service_from_date,
            provider_npi=encounter.provider_npi,
            claim_amount=encounter.allowed_amount
        )
        
        if duplicate_check.is_duplicate:
            # If exact duplicate, reject and link to original
            results['rejected'].append({
                'encounter': encounter,
                'reason': 'Duplicate of ' + duplicate_check.original_claim_id
            })
            continue
        
        if duplicate_check.is_adjusted:
            # If adjustment, mark original as superseded
            mark_claim_superseded(
                claim_id=duplicate_check.original_claim_id,
                adjusted_by=encounter.claim_id
            )
        
        # Stage 4: Diagnosis validation
        for diagnosis in encounter.diagnosis_codes:
            icd10_validation = validate_icd10_for_service_date(
                code=diagnosis,
                service_date=encounter.service_from_date
            )
            if not icd10_validation.valid:
                results['content_warnings'].append({
                    'claim_id': encounter.claim_id,
                    'icd10': diagnosis,
                    'issue': icd10_validation.issue
                })
        
        # Stage 5: HCC Mapping
        encounter.hcc_mappings = map_diagnoses_to_hcc(
            diagnoses=encounter.diagnosis_codes,
            model_version='V28',
            service_year=encounter.service_year
        )
        
        results['accepted'].append(encounter)
    
    return results
```

---

## 7. PREDICTIVE ANALYTICS FOR SUSPECT CONDITIONS

### 7.1 Clinical Suspecting Algorithm

**Objective:** Identify members likely to have undocumented conditions requiring chart review

```sql
-- Suspect Condition Detection Table
CREATE TABLE suspect_conditions (
    suspect_id BIGINT PRIMARY KEY,
    
    member_id VARCHAR(50),
    patient_id UUID,
    suspected_hcc_code VARCHAR(10),
    suspected_condition_name VARCHAR(200),
    
    -- Detection method
    detection_method VARCHAR(50),  -- 'DIAGNOSIS_HISTORY', 'LAB_RESULTS', 'MEDICATION', 'PROCEDURE', 'COST_PATTERN'
    confidence_score NUMERIC(3,2),  -- 0.0-1.0
    
    -- Evidence
    supporting_evidence TEXT,  -- JSON: {method, value, date}
    
    -- Example logic:
    -- HCC19 (Diabetes Mellitus) suspect if:
    --   - A1C lab value > 6.5 in past 12 months AND
    --   - No ICD10 E11.x diagnosis coded
    --   - confidence = normalized_a1c_value * recency_factor
    
    suspect_generated_date DATE,
    outreach_status VARCHAR(20),  -- 'NEW', 'OUTREACHED', 'VALIDATED', 'REJECTED', 'CHART_REVIEW'
    
    chart_review_date DATE,
    chart_review_result VARCHAR(20),  -- 'CONFIRMED', 'REJECTED', 'PENDING'
    
    revenue_impact_if_confirmed NUMERIC(12,2)  -- If confirmed, additional RAF * base rate
);

-- Suspect condition detection: Machine Learning Model
CREATE TABLE ml_suspect_model_features (
    feature_id BIGINT PRIMARY KEY,
    member_id VARCHAR(50),
    
    -- Lab-based features
    a1c_latest_result NUMERIC(6,2),
    a1c_last_90_days BOOLEAN,
    creatinine_latest NUMERIC(6,2),
    egfr_latest NUMERIC(6,2),
    
    -- Procedure-based features
    has_ecg_past_year BOOLEAN,
    has_stress_test_past_year BOOLEAN,
    has_echo_past_year BOOLEAN,
    
    -- Medication-based features
    on_diabetes_meds BOOLEAN,
    on_cardiac_meds BOOLEAN,
    on_copd_meds BOOLEAN,
    medication_refill_adherence NUMERIC(3,2),
    
    -- Claims-based features
    copay_oop_amount_ytd NUMERIC(12,2),
    inpatient_days_past_year INT,
    ed_visits_past_year INT,
    specialist_visits_diabetes_care INT,
    
    -- Historical patterns
    icd10_history_diabetes BOOLEAN,
    icd10_history_heart_disease BOOLEAN,
    years_since_last_diabetes_code INT,
    
    -- Derived features
    risk_profile_segment VARCHAR(50),  -- 'HIGH_UTILIZERS', 'CHRONIC_DISEASE_BURDEN', 'EPISODIC_CARE'
    
    feature_extraction_date TIMESTAMP
);

-- Model predictions
CREATE TABLE ml_suspect_predictions (
    prediction_id BIGINT PRIMARY KEY,
    member_id VARCHAR(50),
    
    predicted_hcc_code VARCHAR(10),
    prediction_probability NUMERIC(3,2),  -- 0.0-1.0
    
    model_version VARCHAR(20),  -- 'v1.2.3'
    model_training_date DATE,
    
    prediction_date TIMESTAMP,
    
    -- Model features used in prediction
    top_3_feature_importances TEXT  -- JSON: [{'feature': 'a1c_latest', 'importance': 0.32}, ...]
);
```

### 7.2 Suspect Analytics KPIs

```yaml
SUSPECT_ANALYTICS_METRICS:
  
  suspect_identification_rate:
    measure: "Suspects identified / member month"
    by: HCC code, detection method
    benchmark: ~15-20 suspects per 1,000 members/month
  
  suspect_accuracy:
    measure: "Suspects confirmed via chart review / Suspects outreached"
    target: >40%
    by_hcc_code: Diabetes (50%), CHF (45%), COPD (35%)
  
  revenue_per_confirmed_suspect:
    measure: "RAF increase × members × CMS base rate"
    example: "HCC19 confirmation = ~$150 per member/year"
  
  outreach_time_to_resolution:
    measure: "Days from suspect ID to chart review completion"
    percentile_50: 45 days
    percentile_90: 90 days
    
  model_prediction_accuracy:
    measure: "Precision, Recall, F-score of ML model"
    precision: Confirmed / Predicted (false positive rate)
    recall: Confirmed / Actually Present (sensitivity)
    f_score: Harmonic mean (balance metric)
```

---

## 8. BENCHMARKING ACROSS PROVIDER GROUPS, REGIONS, LINES OF BUSINESS

### 8.1 Benchmarking Schema

```sql
-- Provider Performance Benchmark
CREATE TABLE benchmark_provider_performance (
    benchmark_id BIGINT PRIMARY KEY,
    
    -- Grouping dimensions
    provider_npi VARCHAR(10),
    provider_name VARCHAR(200),
    provider_specialty VARCHAR(100),
    
    service_year INT,
    benchmark_period VARCHAR(20),  -- 'MONTHLY', 'QUARTERLY', 'ANNUAL'
    
    -- Patient risk adjustment
    member_count INT,
    average_member_age NUMERIC(5,2),
    medicaid_dual_percentage NUMERIC(5,2),
    
    -- RAF performance
    average_raf_score NUMERIC(10,4),
    median_raf_score NUMERIC(10,4),
    raf_per_member_opportunity NUMERIC(10,4),  -- (Projected - Actual) / Actual
    
    -- Coding intensity
    coding_intensity_ratio NUMERIC(10,4),  -- Provider RAF / Regional average RAF
    benchmark_peer_group VARCHAR(50),  -- 'Primary Care', 'Cardiologist', 'Endocrinologist'
    coding_intensity_percentile INT,  -- 1-100
    
    -- Quality metrics
    gap_closure_rate NUMERIC(5,2),  -- %
    hedis_measure_performance VARCHAR(500),  -- JSON: {measure: rate}
    
    -- Cost metrics
    pmpm_medical_cost NUMERIC(10,2),
    pmpm_pharmacy_cost NUMERIC(10,2),
    total_cost_per_member NUMERIC(10,2),
    cost_trend_yoy NUMERIC(5,2),  -- %
    
    -- Comparison to benchmarks
    vs_regional_average NUMERIC(10,4),  -- Difference from region
    vs_national_average NUMERIC(10,4),
    vs_peer_group_percentile INT,  -- 1-100
    
    performance_rating VARCHAR(20),  -- 'HIGH_PERFORMER', 'AVERAGE', 'NEEDS_IMPROVEMENT'
    
    benchmark_date TIMESTAMP
);

-- Regional/Line of Business Benchmarking
CREATE TABLE benchmark_regional_lob_summary (
    benchmark_summary_id BIGINT PRIMARY KEY,
    
    region VARCHAR(100),  -- 'Northeast', 'Texas MA', etc.
    line_of_business VARCHAR(50),  -- 'MA-PD', 'SNP', 'MEDICAID_MA'
    
    service_year INT,
    
    -- Aggregate metrics
    total_members INT,
    total_raf_points NUMERIC(14,4),
    average_raf_score NUMERIC(10,4),
    
    average_age NUMERIC(5,2),
    percentage_male NUMERIC(5,2),
    percentage_dual_eligible NUMERIC(5,2),
    
    -- Coding intensity distribution
    coding_intensity_25th NUMERIC(10,4),
    coding_intensity_50th NUMERIC(10,4),  -- Median
    coding_intensity_75th NUMERIC(10,4),
    
    -- Top HCCs by prevalence
    top_10_hccs TEXT,  -- JSON: [{hcc: 'HCC19', prevalence: 0.23, avg_coefficient: 0.18}, ...]
    
    -- Quality benchmarks
    average_gap_closure_rate NUMERIC(5,2),
    average_stars_rating NUMERIC(3,1),
    
    created_at TIMESTAMP
);
```

### 8.2 Benchmarking Query Examples

```sql
-- Provider percentile ranking (vs specialty peers)
SELECT 
    p.provider_name,
    p.provider_specialty,
    b.coding_intensity_ratio,
    PERCENT_RANK() OVER (
        PARTITION BY p.provider_specialty
        ORDER BY b.coding_intensity_ratio
    ) * 100 as percentile_rank,
    
    COUNT(*) OVER (PARTITION BY p.provider_specialty) as peer_group_size
FROM benchmark_provider_performance b
JOIN dim_provider p ON b.provider_npi = p.provider_npi
WHERE b.service_year = 2024
ORDER BY p.provider_specialty, percentile_rank DESC;

-- Regional comparison: Member risk profiles
SELECT 
    region,
    line_of_business,
    service_year,
    
    ROUND(average_raf_score, 4) as avg_raf,
    (average_raf_score - LAG(average_raf_score) 
        OVER (PARTITION BY region, lob ORDER BY service_year)) as yoy_change,
    
    ROUND(average_age, 1) as avg_age,
    ROUND(percentage_dual_eligible * 100, 1) as pct_dual,
    
    CASE 
        WHEN average_raf_score > 1.10 THEN 'Higher Risk'
        WHEN average_raf_score > 0.95 THEN 'Average Risk'
        ELSE 'Lower Risk'
    END as risk_profile
FROM benchmark_regional_lob_summary
ORDER BY region, line_of_business, service_year DESC;
```

---

## 9. DATA PIPELINE ARCHITECTURE

### 9.1 ETL/ELT Architecture

**Recommended Stack:** Cloud-based modern data stack
- **Ingestion:** Fivetran, Stitch, or Apache NiFi
- **Processing:** Databricks (Spark), dbt for transformations
- **Warehouse:** Snowflake or BigQuery
- **Orchestration:** Airflow, Dagster

```yaml
PIPELINE_ARCHITECTURE:
  
  EXTRACT:
    - Claims systems (837 files, daily batch)
    - EHR systems (via FHIR APIs, if available; else nightly exports)
    - Chart review system (daily submissions)
    - CMS files (annual: MMR, MOR, MAO-4)
    - Lab systems (through HIE if available)
    
  TRANSFORM (ELT preferred):
    - Land raw files in S3/GCS/Azure Blob (bronze layer)
    - Parse 837 headers, validate syntax in Spark
    - Join claims to member master (deduplication)
    - Map ICD-10 to HCC (using CMS crosswalks)
    - Calculate RAF at member-month grain
    - Aggregate to plan, provider, region (silver layer)
    - Create dimensional schema (gold layer)
    
  LOAD:
    - Fact tables: encounter-level (837 records), RAF monthly summary
    - Dimension tables: patient, plan, provider, diagnosis, time
    - Data marts: Performance metrics, gap closure tracking
    - External exports: CMS submission files, HEDIS reporting files

  ORCHESTRATION:
    - Daily (T+1): Claims processing, encounter validation, incremental RAF
    - Weekly: Quality checks, data reconciliation, gap closure reporting
    - Monthly: Consolidated RAF run, performance dashboards, manager reports
    - Quarterly: Provider benchmarking updates, model retraining
    - Annual (Jan-Mar): Year-end RAF, CMS submissions, HEDIS audits
```

### 9.2 Batch Processing: Monthly RAF Pipeline

```python
# Airflow DAG or Databricks Job
class RAFMonthlyPipeline:
    def __init__(self):
        self.execution_date = pendulum.now().subtract(days=1)
        self.data_warehouse = "snowflake"
        
    def run(self):
        # Stage 1: Extract & Load (T+1)
        self.extract_encounters_837()
        self.extract_chart_review_submissions()
        self.validate_claim_format()
        
        # Stage 2: Transform (T+5)
        self.deduplicate_encounters()
        self.reconcile_with_member_master()
        self.validate_diagnosis_codes()
        self.map_icd10_to_hcc()
        
        # Stage 3: Calculate (T+5 to T+35)
        self.run_raf_calculation()
        
        # Stage 4: Validate & Report (T+35)
        self.validate_raf_outputs()
        self.generate_performance_reports()
        
    def extract_encounters_837(self):
        """
        Extract 837 claim files from payers
        """
        # Pseudocode
        raw_837_files = s3.list_objects(
            bucket='claims-inbound',
            prefix=f'encounters/{self.execution_date.format("YYYY-MM-DD")}/'
        )
        
        for file in raw_837_files:
            parsed_claims = parse_837_edi_file(file)
            spark.createDataFrame(parsed_claims).write.mode("append").saveAsTable(
                "bronze_claims_837_raw"
            )
    
    def validate_claim_format(self):
        """
        CMS-style syntax validation
        """
        validation_results = spark.sql("""
            WITH claim_validation AS (
                SELECT
                    claim_id,
                    CASE
                        WHEN NPI IS NULL OR length(NPI) <> 10 THEN 'Invalid NPI'
                        WHEN member_id IS NULL THEN 'Missing Member ID'
                        WHEN service_from_date > service_to_date THEN 'Invalid Service Dates'
                        WHEN array_size(diagnosis_codes) > 25 THEN 'Too Many Diagnoses'
                        ELSE NULL
                    END as validation_error
                FROM bronze_claims_837_raw
            )
            SELECT * FROM claim_validation WHERE validation_error IS NOT NULL
        """)
        
        # Log rejected claims
        self.log_validation_failures(validation_results)
    
    def deduplicate_encounters(self):
        """
        Identify and handle duplicate claims
        """
        spark.sql("""
            WITH encounter_dedup AS (
                SELECT
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY member_id, service_from_date, provider_npi, allowed_amount
                        ORDER BY claim_version_number DESC, created_at DESC
                    ) as row_num
                FROM bronze_claims_837_raw
                WHERE validation_error IS NULL
            )
            SELECT * INTO silver_encounters FROM encounter_dedup WHERE row_num = 1
        """)
    
    def map_icd10_to_hcc(self):
        """
        Map diagnosis codes to HCC categories
        """
        spark.sql("""
            SELECT
                e.encounter_id,
                e.patient_id,
                e.service_from_date,
                ed.icd10_code,
                h.hcc_code_v28,
                h.hcc_description,
                ed.evidence_source_code
            INTO silver_encounter_diagnoses
            FROM silver_encounters e
            JOIN bronze_encounter_diagnoses ed ON e.encounter_id = ed.encounter_id
            LEFT JOIN hcc_crosswalk h
                ON ed.icd10_code = h.icd10_code
                AND YEAR(e.service_from_date) = h.effective_year
        """)
    
    def run_raf_calculation(self):
        """
        Execute RAF calculation
        """
        raf_calc = RAFBatchCalculator()
        raf_results = raf_calc.calculate_all_members(
            service_year=2024,
            execution_month=self.execution_date
        )
        
        raf_results.write.mode("append").saveAsTable("gold_member_raf_monthly")
    
    def generate_performance_reports(self):
        """
        Generate dashboards and manager reports
        """
        # Aggregate to plan/provider/region
        spark.sql("""
            INSERT INTO mart_raf_performance
            SELECT
                plan_id,
                service_year,
                DATE_TRUNC('month', created_at) as calc_month,
                COUNT(DISTINCT patient_id) as member_count,
                ROUND(AVG(final_raf_score), 4) as avg_raf,
                ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY final_raf_score), 4) as median_raf,
                SUM(final_raf_score * cms_base_rate) as estimated_annual_revenue
            FROM gold_member_raf_monthly
            GROUP BY plan_id, service_year, DATE_TRUNC('month', created_at)
        """)
        
        # Email reports to stakeholders
        self.email_monthly_report()
```

### 9.3 Real-Time Streaming: Gap Closure Detection

```python
# Kafka + Spark Streaming for gap identification
class GapClosureStreamingPipeline:
    
    def __init__(self):
        self.kafka_broker = "kafka-cluster:9092"
        self.topic = "encounters_stream"
        
    def run(self):
        spark = SparkSession.builder \
            .appName("GapClosureDetection") \
            .getOrCreate()
        
        # Read from Kafka
        df = spark.readStream \
            .format("kafka") \
            .option("kafka.bootstrap.servers", self.kafka_broker) \
            .option("subscribe", self.topic) \
            .load()
        
        # Parse encounter record
        encounters = df.select(
            from_json(col("value"), schema=encounter_schema).alias("encounter")
        ).select("encounter.*")
        
        # Join with member demographics
        members = spark.read.table("dim_patient")
        enriched = encounters.join(members, "member_id", "left")
        
        # Detect gap closures (real-time)
        gap_closures = enriched \
            .filter("icd10_code IN ('E11.9', 'I50.9', 'J44.0')") \
            .select(
                col("member_id"),
                col("icd10_code"),
                col("hcc_code"),
                col("service_from_date"),
                current_timestamp().alias("detection_time")
            )
        
        # Write to Kafka topic + database
        gap_closures.writeStream \
            .format("kafka") \
            .option("kafka.bootstrap.servers", self.kafka_broker) \
            .option("topic", "gap_closures_detected") \
            .option("checkpointLocation", "/tmp/gap_closure_checkpoint") \
            .start()
        
        gap_closures.writeStream \
            .format("snowflake") \
            .options(**snowflake_options) \
            .option("dbtable", "gap_closures_real_time") \
            .option("checkpointLocation", "/tmp/snowflake_checkpoint") \
            .start()
```

---

## 10. HANDLING MULTIPLE PAYMENT YEARS AND SWEEPS

### 10.1 Multi-Year RAF Tracking

**Challenge:** RAF scores calculated for multiple service years simultaneously; CMS performs annual sweeps (reconciliation) based on actual claims run-out.

```sql
CREATE TABLE raf_calculation_history (
    raf_history_id BIGINT PRIMARY KEY,
    
    patient_id UUID,
    member_id VARCHAR(50),
    plan_id UUID,
    
    -- Key: Service year (year diagnoses occurred)
    service_year INT,  -- 2024, 2025, etc.
    
    -- Calculation versions (multiple per year due to adjustments)
    calculation_version INT,  -- 1=Initial, 2=Adjustment, 3=Sweep, etc.
    calculation_type VARCHAR(20),  -- 'INITIAL', 'ADJUSTMENT', 'SWEEP'
    
    -- RAF scores
    raw_raf_score NUMERIC(10,4),
    demographic_factor NUMERIC(10,4),
    disease_factor NUMERIC(10,4),
    final_raf_score NUMERIC(10,4),
    
    -- Applied HCCs (for audit trail)
    applied_hcc_codes TEXT,  -- JSON array
    
    -- CMS submission status
    cms_submitted BOOLEAN,
    cms_submission_date DATE,
    cms_payment_period VARCHAR(20),  -- CMS pays during year+1 (SY 2024 paid in 2025)
    
    -- Sweep reconciliation
    sweep_difference NUMERIC(10,4),  -- New RAF - Previous RAF
    sweep_adjustment_amount NUMERIC(14,2),  -- Sweep $$ = (new - old) * base rate
    sweep_payment_date DATE,
    
    -- Audit trail
    calculation_date TIMESTAMP,
    change_reason_description VARCHAR(500),
    changed_by_system VARCHAR(100),  -- 'RAF_BATCH', 'MANUAL_ADJUSTMENT', 'CMS_SWEEP'
    
    UNIQUE(patient_id, service_year, calculation_version)
);

-- Example: Multi-year timeline
-- Service Year 2024 (diagnoses in 2024):
--   Initial RAF (Jan 2024): 1.150  -> CMS pays ~$11,960/year
--   Adjusted (Apr 2024): 1.175 due to new chart reviews -> +$260/year
--   Sweep (Jun 2025): 1.145 (final) -> -$260 adjustment payment
--
-- Service Year 2025 (diagnoses in 2025):
--   Initial RAF (Jan 2025): 1.190  -> CMS pays in 2026
--   Expected sweep (Jun 2026): TBD based on final claims run-out
```

### 10.2 Sweep Reconciliation Process

```python
class CMS_Sweep_Reconciliation:
    """
    Handle annual CMS settlement of RAF scores
    Based on: 12 months of claims run-out (settlement lag = 6 months)
    """
    
    def process_sweep(self, service_year, sweep_date):
        """
        CMS sweeps occur ~6 months after service year-end
        2024 Service Year sweep: June 2025
        """
        
        # Step 1: Collect final claims (including late submissions)
        final_claims = self.get_settled_claims(
            service_year=service_year,
            cutoff_date=sweep_date - timedelta(days=30)  # 30-day run-out buffer
        )
        
        # Step 2: Recalculate RAF with settled claims
        prior_raf = self.get_previous_raf_version(
            service_year=service_year,
            calculation_type='ADJUSTMENT'  # Most recent pre-sweep
        )
        
        sweep_raf = self.calculate_member_raf(
            service_year=service_year,
            claims_set=final_claims,  # Using FINAL claims
            calculation_type='SWEEP'
        )
        
        # Step 3: Calculate adjustments
        differences = sweep_raf.join(
            prior_raf,
            on=['member_id', 'service_year'],
            how='outer'
        ).select(
            col("member_id"),
            col("sweep_raf.raf_score").alias("final_raf"),
            col("prior_raf.raf_score").alias("prior_raf"),
            (col("sweep_raf.raf_score") - col("prior_raf.raf_score")).alias("raf_diff"),
            (col("sweep_raf.raf_score") - col("prior_raf.raf_score") * base_rate).alias("adjustment_$")
        )
        
        # Step 4: Determine payment direction
        #   If final_raf > prior_raf: Health plan owes CMS (payment to plan)
        #   If final_raf < prior_raf: Plan owes CMS (payment back to CMS)
        
        # Step 5: Record in accounting system
        differences.write.insertInto("raf_sweep_adjustments")
        
        # Step 6: Generate CMS 834 adjustment file (EDI format)
        # This file is submitted to CMS for processing
        
        return differences
    
    def validate_sweep_reasonableness(self, sweep_results):
        """
        Sanity checks on sweep adjustments
        """
        validations = {
            'total_adjustment_tolerance': 0.05,  # ±5% of total RAF value
            'member_adjustment_outlier_threshold': 0.50,  # Flag members > 0.5 RAF change
            'new_claims_rate': 0.10,  # <10% should be new claims (rest run-out)
        }
        
        # Flag unusual patterns for manual review
        outliers = sweep_results.filter(
            abs(col("raf_diff")) > validations['member_adjustment_outlier_threshold']
        )
        
        return outliers
```

---

## 11. ACTUARIAL INTEGRATION AND BID-LEVEL RAF PROJECTIONS

### 11.1 Bid Forecasting Model

**Context:** Health plans prepare bids annually (June-August) for next year's contract, requiring RAF projections 12+ months in advance.

```sql
CREATE TABLE actuarial_bid_model (
    bid_model_id BIGINT PRIMARY KEY,
    
    -- Bid metadata
    service_year INT,  -- 2026, 2027
    bid_version INT,  -- 1=Initial, 2=Mid-year adjustment, 3=Final
    bid_submission_date DATE,
    
    -- Plan segments
    plan_segment_code VARCHAR(10),
    benefit_design VARCHAR(100),  -- MA-only, MA-PD, SNP
    market_region VARCHAR(100),
    
    -- Member projections
    projected_member_count INT,
    projected_new_enrollees INT,
    projected_disenrollees INT,
    retention_rate NUMERIC(5,3),
    
    -- RAF projections (key driver)
    base_year_avg_raf NUMERIC(10,4),  -- Prior year actual
    
    -- Trend assumptions
    morbidity_trend_pct NUMERIC(5,3),  -- Annual disease progression rate
    coding_intensity_trend_pct NUMERIC(5,3),
    hcc_mix_shift_pct NUMERIC(5,3),  -- Prevalence shift toward more severe HCCs
    
    -- Forecast RAF
    projected_avg_raf NUMERIC(10,4),  -- Base + trend adjustments
    projected_raf_std_dev NUMERIC(10,4),
    projected_raf_distribution TEXT,  -- JSON: percentiles
    
    -- Financial impact
    cms_base_rate_per_member NUMERIC(10,2),  -- Set by CMS
    projected_capitation_revenue NUMERIC(14,2),  -- Raf * base rate * members
    
    -- Risk factors
    member_age_shift_impact NUMERIC(10,4),
    dual_eligible_percentage_impact NUMERIC(10,4),
    ltc_concentration_impact NUMERIC(10,4),
    
    -- Actuarial assumptions
    lapse_assumption_rate NUMERIC(5,3),
    new_member_raf_assumption NUMERIC(10,4),  -- New members assumed lower RAF
    
    created_at TIMESTAMP
);

-- Historical comparison table
CREATE TABLE actuarial_projections_vs_actual (
    projection_variance_id BIGINT PRIMARY KEY,
    
    service_year INT,
    projection_period VARCHAR(20),  -- When projection was made (e.g., 'June 2024 for SY2025')
    
    plan_segment_code VARCHAR(10),
    
    -- What was projected
    projected_avg_raf NUMERIC(10,4),
    projected_member_count INT,
    projected_capitation_revenue NUMERIC(14,2),
    
    -- What actually happened
    actual_avg_raf NUMERIC(10,4),
    actual_member_count INT,
    actual_capitation_revenue NUMERIC(14,2),
    
    -- Variance analysis
    raf_variance_pct NUMERIC(5,2),  -- (Actual - Projected) / Projected
    member_count_variance_pct NUMERIC(5,2),
    revenue_variance NUMERIC(14,2),
    
    -- Root cause analysis
    variance_explanation TEXT,  -- JSON: {factor: impact_pct}
    
    created_at TIMESTAMP
);
```

### 11.2 Bid Model Integration

```python
class ActuarialBidModel:
    
    def project_next_year_raf(self, base_year=2024, projection_year=2025):
        """
        Forecast RAF for bid submission
        Key inputs: Historical trends, plan assumptions, CMS model changes
        """
        
        # Step 1: Get baseline RAF
        baseline_raf = self.get_actual_average_raf(
            service_year=base_year,
            by_plan=True
        )
        
        # Step 2: Apply trend assumptions
        # a) Morbidity trend (members getting sicker over time)
        morbidity_trend = 0.025  # 2.5% annual increase in disease burden
        
        # b) Coding intensity trend (improved documentation)
        coding_trend = 0.015  # 1.5% annual coding improvement
        
        # c) HCC model changes (CMS adjustments)
        hcc_model_impact = self.get_hcc_model_impact(
            from_version='V28',
            to_version='V29',
            projection_year=projection_year
        )  # Could be +2% or -3% depending on model changes
        
        # Step 3: Calculate projected RAF
        projected_raf = baseline_raf * (
            1 + morbidity_trend +
            coding_trend +
            hcc_model_impact
        )
        
        # Step 4: Adjust for member mix shifts
        age_shift = self.calculate_age_shift_impact(
            current_age_dist=self.get_member_age_distribution(base_year),
            projected_age_dist=self.project_age_distribution(projection_year)
        )
        
        dual_eligible_shift = self.calculate_dual_eligible_shift()
        
        # Step 5: Account for enrollment changes
        # New enrollees typically have lower RAF (healthier selection)
        projected_enrollment = baseline_members * (1 + enrollment_growth_rate)
        weighted_raf = (
            (existing_members * projected_raf) +
            (new_members * new_member_raf_assumption)
        ) / projected_enrollment
        
        # Step 6: Validate against actuary review
        bid_model = ActuarialBidModel(
            service_year=projection_year,
            projected_avg_raf=weighted_raf,
            projected_member_count=projected_enrollment,
            projected_capitation_revenue=weighted_raf * cms_base_rate * projected_enrollment
        )
        
        return bid_model
    
    def get_hcc_model_impact(self, from_version, to_version, projection_year):
        """
        Estimate impact of HCC model changes
        Example: V28 to V29 change in 2025
        """
        # Could use historical data on V24->V28 transition
        # Or actuarial guidance from CMS
        
        # For 2024 V24->V28 transition: CMS estimated -3.12% impact
        # Could assume similar -2% to -3% for subsequent transitions
        
        if from_version == 'V28' and to_version == 'V29':
            return -0.020  # Conservative -2% assumption
        
        return 0.0
```

### 11.3 Actuarial Financial Model Integration

```sql
-- Connection to medical loss ratio (MLR) and financial projections
CREATE TABLE actuarial_financial_model (
    model_id BIGINT PRIMARY KEY,
    
    service_year INT,
    plan_segment_code VARCHAR(10),
    
    -- Revenue side
    capitation_rate_per_member NUMERIC(10,2),  -- CMS base rate
    raf_adjustment_factor NUMERIC(10,4),  -- Plan's actual RAF / CMS average RAF
    quality_bonus_percentage NUMERIC(5,3),  -- STARS bonus
    
    actual_raf NUMERIC(10,4),
    total_members INT,
    total_capitation_revenue NUMERIC(14,2),  -- RAF * rate * members
    
    -- Cost side
    medical_loss_ratio_assumption NUMERIC(5,3),  -- 83%, 85%, etc.
    pharmacy_cost_pmpm NUMERIC(10,2),
    medical_cost_pmpm NUMERIC(10,2),
    
    total_projected_medical_cost NUMERIC(14,2),
    total_projected_pharmacy_cost NUMERIC(14,2),
    
    -- Operating expenses
    admin_expense_percentage NUMERIC(5,3),  -- % of capitation revenue
    commissions_percentage NUMERIC(5,3),
    
    -- Bottom line
    underwriting_profit NUMERIC(14,2),
    margin_percentage NUMERIC(5,3),  -- Profit / Revenue
    
    -- Sensitivity analysis (RAF impact on profitability)
    revenue_per_0_1_raf_change NUMERIC(14,2),  -- $1,040 per member per 0.1 RAF
    
    created_at TIMESTAMP
);
```

---

## CONCLUSION

This research provides technical foundations for building a comprehensive RAF SaaS platform. Key architectural recommendations:

1. **Data Model:** Multi-tenant dimensional schema with fact/dimension tables supporting patient, encounter, diagnosis, HCC, RAF, and performance metrics
2. **Calculation Engine:** Hybrid batch (monthly/annual) + real-time (gap closure) processing using Spark/Databricks
3. **Warehouse:** Snowflake/BigQuery with ELT pattern; star schema for analytics
4. **Dashboards:** Executive (revenue/RAF trends), operational (quality/productivity), and clinical (suspect identification)
5. **Reporting:** CMS regulatory (MAO-002, MAO-004), NCQA HEDIS/STARS, internal KPI reporting
6. **Data Pipeline:** Cloud ETL (Fivetran/dbt), Kafka streaming for real-time gap detection, Airflow orchestration
7. **Analytics:** Predictive models for suspect conditions; benchmarking across providers, regions, LOBs
8. **Multi-Year:** Track multiple service years; handle annual CMS sweeps and payment reconciliation
9. **Actuarial:** Bid forecasting models integrating RAF projections with financial planning

**Sources Used:**
- [Risk Adjustment of Medicare Capitation Payments Using the CMS-HCC Model - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC4194896/)
- [The HHS-HCC Risk Adjustment Model for Individual and Small Group Markets under the Affordable Care Act - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC4214270/)
- [Healthcare Data Warehouse for Payers: Complete 2025 Guide](https://www.invene.com/blog/healthcare-data-warehouse)
- [RAF Score Optimization: Medicare Advantage Revenue Guide for CTOs](https://www.invene.com/blog/raf-score)
- [A Framework for Designing a Healthcare Outcome Data Warehouse - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC2047311/)
- [Close Care Gaps: Data Architecture for Systematic Results](https://www.invene.com/blog/close-care-gaps)
- [How CMS-HCC Version 28 will impact risk adjustment factor (RAF) scores | Wolters Kluwer](https://www.wolterskluwer.com/en/expert-insights/how-cms-hcc-version-28-will-impact-risk-adjustment-factor-raf-scores)
- [Apache Kafka in the Healthcare Industry](https://www.kai-waehner.de/blog/2022/03/28/apache-kafka-data-streaming-healthcare-industry/)
- [ETL in The Healthcare Industry: Challenges & Best Practices](https://kodjin.com/blog/etl-process-in-the-healthcare-industry/)
- [Data quality in healthcare - Benefits, challenges, and steps for improvement](https://dataladder.com/data-quality-in-healthcare-data-systems/)
- [State Toolkit for Validating Medicaid Managed Care Encounter Data](https://www.medicaid.gov/medicaid/downloads/ed-validation-toolkit.pdf)
- [HEDIS Measures and Technical Resources - NCQA](https://www.ncqa.org/hedis/measures/)
- [Medicare 2025 Part C & D Star Ratings Technical Notes](https://www.cms.gov/files/document/2025-star-ratings-technical-notes.pdf)
- [Predictive Analytics: The perfect tonic to bolster risk adjustment initiatives](https://www.exlservice.com/insights/white-paper/predictive-analytics-the-perfect-tonic-bolster-risk-adjustment-initiatives)
- [Benchmarking Physician Performance: Reliability of Individual and Composite Measures - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC2667340/)
- [Building Actuarial Cost Models from Health Care Claims Data for Strategic Decision-Making](https://axenehp.com/building-actuarial-cost-models-health-care-claims-data-strategic-decision-making/)
- [Medicare Advantage Plan Cost Projections for Retiree Group Health](https://actuary.org/wp-content/uploads/2025/12/health-practicenote-AcademyMACostProjection.pdf)
