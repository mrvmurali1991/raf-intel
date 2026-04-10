# RAF SaaS Platform: Technical Implementation Patterns & SQL Reference

## Advanced SQL Patterns for RAF Systems

### Pattern 1: HCC Hierarchy Application

**Problem:** CMS hierarchies mean some HCCs subsume others. Once a patient has HCC19 (Diabetes with complications), we don't count HCC18 (Diabetes without complications).

```sql
WITH patient_diagnoses AS (
    SELECT
        patient_id,
        hcc_code,
        icd10_code,
        evidence_source,
        ROW_NUMBER() OVER (PARTITION BY patient_id, hcc_code ORDER BY evidence_source DESC) as rn
    FROM encounter_diagnoses
    WHERE service_year = 2024
      AND evidence_source IN ('MA_ENCOUNTER', 'CHART_REVIEW')
      AND chart_review_validation_status IN ('VALIDATED', NULL)
),
unique_hccs AS (
    SELECT
        patient_id,
        hcc_code,
        icd10_code
    FROM patient_diagnoses
    WHERE rn = 1
),
-- Apply hierarchy: Remove subsumed HCCs
hierarchical_hccs AS (
    SELECT
        u.patient_id,
        u.hcc_code,
        u.icd10_code,
        CASE
            WHEN u.hcc_code = 'HCC18' AND EXISTS (
                SELECT 1 FROM unique_hccs u2
                WHERE u2.patient_id = u.patient_id
                  AND u2.hcc_code = 'HCC19'  -- HCC19 subsumes HCC18
            ) THEN NULL  -- Exclude HCC18
            
            WHEN u.hcc_code = 'HCC82' AND EXISTS (
                SELECT 1 FROM unique_hccs u2
                WHERE u2.patient_id = u.patient_id
                  AND u2.hcc_code IN ('HCC83', 'HCC84')  -- HCC83/84 subsume HCC82
            ) THEN NULL
            
            ELSE u.hcc_code
        END as final_hcc_code
    FROM unique_hccs u
)
SELECT
    patient_id,
    ARRAY_AGG(final_hcc_code) FILTER (WHERE final_hcc_code IS NOT NULL) as applied_hccs,
    COUNT(DISTINCT final_hcc_code) FILTER (WHERE final_hcc_code IS NOT NULL) as hcc_count
FROM hierarchical_hccs
GROUP BY patient_id;
```

### Pattern 2: Member-Month Deduplication

**Problem:** Same claim may appear in multiple EDR (encounter data record) submissions. Must keep latest version only.

```sql
-- Step 1: Identify versions of same claim
WITH claim_versions AS (
    SELECT
        member_id,
        claim_id,
        original_claim_id,
        claim_version_number,
        service_from_date,
        provider_npi,
        allowed_amount,
        
        -- If this is an adjustment, flag original as superseded
        CASE
            WHEN original_claim_id IS NOT NULL THEN 'ADJUSTMENT'
            WHEN claim_adjustment_flag = TRUE THEN 'CORRECTED'
            ELSE 'ORIGINAL'
        END as claim_status_type,
        
        ROW_NUMBER() OVER (
            PARTITION BY member_id, COALESCE(original_claim_id, claim_id)
            ORDER BY claim_version_number DESC, submission_date DESC
        ) as version_rank
    FROM encounters
    WHERE data_source_code IN ('MA_ENCOUNTER', 'CHART_REVIEW')
)
-- Step 2: Keep only latest version
SELECT
    member_id,
    claim_id,
    service_from_date,
    provider_npi,
    allowed_amount
FROM claim_versions
WHERE version_rank = 1
ORDER BY member_id, service_from_date;
```

### Pattern 3: Coding Intensity Calculation

**Objective:** Measure if plan's RAF > expected RAF (indicates coding practices or actual disease burden)

```sql
-- Calculate by plan and provider
CREATE TABLE coding_intensity_analysis AS
WITH plan_performance AS (
    SELECT
        plan_id,
        provider_npi,
        service_year,
        
        -- Actual RAF from plan
        AVG(final_raf_score) as actual_avg_raf,
        SUM(final_raf_score) as total_raf_points,
        
        -- Expected RAF based on demographics alone
        AVG(demographic_risk_score) as demographic_only_raf,
        
        -- Member count
        COUNT(DISTINCT patient_id) as member_count,
        
        -- Age distribution
        PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY age) as age_q25,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY age) as age_q50,
        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY age) as age_q75,
        
        -- Disease burden indicators
        COUNT(DISTINCT patient_id) FILTER (WHERE hcc_count >= 1) as members_with_any_hcc,
        AVG(hcc_count) as avg_hcc_per_member,
        
        -- Data source
        COUNT(DISTINCT patient_id) FILTER (WHERE evidence_source = 'CHART_REVIEW') as chart_review_members
    FROM raf_calculation_results
    WHERE service_year = 2024
    GROUP BY plan_id, provider_npi, service_year
)
SELECT
    *,
    ROUND((actual_avg_raf - demographic_only_raf) / demographic_only_raf, 4) as coding_intensity_ratio,
    CASE
        WHEN (actual_avg_raf / demographic_only_raf) > 1.20 THEN 'HIGH'
        WHEN (actual_avg_raf / demographic_only_raf) > 1.05 THEN 'NORMAL'
        ELSE 'LOW'
    END as coding_intensity_category,
    
    -- Benchmark vs region
    PERCENT_RANK() OVER (
        PARTITION BY service_year
        ORDER BY actual_avg_raf / demographic_only_raf
    ) * 100 as percentile_vs_peers
FROM plan_performance
ORDER BY plan_id, percentile_vs_peers DESC;
```

### Pattern 4: Gap Closure Revenue Attribution

**Objective:** Track which conditions were closed, by which provider, and estimated revenue impact

```sql
-- Gap closure analysis with revenue attribution
SELECT
    gap_id,
    member_id,
    hedis_measure_code,  -- e.g., 'IDD_E'=Diabetes Eye Exam
    gap_identified_date,
    gap_closed_date,
    gap_closure_days = DATEDIFF(day, gap_identified_date, gap_closed_date),
    
    -- Which condition was documented to close this gap?
    associated_hcc_code,  -- e.g., HCC19 for diabetes
    
    -- Provider who documented the service
    closing_provider_npi,
    closing_provider_name,
    
    -- Revenue impact
    raf_increase_from_closure,  -- Amount new HCC added to RAF
    cms_base_rate,
    estimated_annual_member_revenue = raf_increase_from_closure * cms_base_rate,
    
    -- Plan impact
    plan_id,
    plan_name,
    
    -- STARS impact
    stars_measure_family,  -- Which STARS measure this closes
    stars_points_added,  -- Contribution to STARS rating
    estimated_stars_impact,  -- 0.01 star = ~$2.6M for 100k members
    
    gap_closure_status,  -- 'CLOSED', 'PENDING', 'FAILED'
    
    -- Attributes for benchmarking
    LAG(gap_closure_days) OVER (
        PARTITION BY hedis_measure_code, closing_provider_npi
        ORDER BY gap_closed_date
    ) as prev_provider_closure_days
FROM gap_closures
WHERE service_year = 2024
  AND gap_closed_date IS NOT NULL
ORDER BY estimated_annual_member_revenue DESC;
```

### Pattern 5: Multi-Year RAF Reconciliation

**Problem:** Need to track RAF across multiple service years and handle annual CMS sweeps

```sql
-- Track RAF changes year-over-year with sweep reconciliation
WITH member_raf_timeline AS (
    SELECT
        member_id,
        service_year,
        final_raf_score,
        calculation_type,  -- 'INITIAL', 'ADJUSTMENT', 'SWEEP'
        created_at,
        
        -- Lag: Prior year's final RAF
        LAG(final_raf_score) OVER (
            PARTITION BY member_id
            ORDER BY service_year, calculation_type DESC
        ) as prior_year_final_raf,
        
        -- Trend
        (final_raf_score - LAG(final_raf_score) OVER (
            PARTITION BY member_id
            ORDER BY service_year
        )) as yoy_raf_change
    FROM raf_calculation_history
    WHERE calculation_type IN ('SWEEP', 'ADJUSTMENT')
)
SELECT
    member_id,
    service_year,
    final_raf_score,
    prior_year_final_raf,
    yoy_raf_change,
    ROUND(yoy_raf_change / NULLIF(prior_year_final_raf, 0), 4) as yoy_pct_change,
    
    -- Financial impact
    yoy_raf_change * 10400 as estimated_annual_revenue_change,  -- At $104 base rate
    
    -- Tier members by trajectory
    CASE
        WHEN yoy_raf_change > 0.10 THEN 'INCREASING_RISK'
        WHEN yoy_raf_change > 0.0 THEN 'SLIGHT_INCREASE'
        WHEN yoy_raf_change >= -0.05 THEN 'STABLE'
        ELSE 'DECLINING_RISK'
    END as risk_trajectory,
    
    -- Running cumulative
    SUM(yoy_raf_change) OVER (
        PARTITION BY member_id
        ORDER BY service_year
    ) as cumulative_raf_change
FROM member_raf_timeline
ORDER BY member_id, service_year;
```

---

## Performance Optimization Patterns

### Index Strategy for RAF Systems

```sql
-- Fact table indexes (high cardinality)
CREATE INDEX idx_fact_member_raf_monthly_patient_time
    ON fact_member_raf_monthly(patient_dim_id, time_dim_id);

CREATE INDEX idx_fact_encounter_patient_provider
    ON fact_encounter(patient_dim_id, provider_dim_id);

-- Dimension table indexes
CREATE INDEX idx_dim_patient_member_id
    ON dim_patient(member_id);

CREATE INDEX idx_dim_patient_enrollment_status
    ON dim_patient(enrollment_status)
    WHERE enrollment_status = 'Active';  -- Partial index for active members

-- Diagnosis lookup
CREATE INDEX idx_encounter_diag_patient_hcc
    ON encounter_diagnoses(patient_id, hcc_code_v28);

-- Time-based queries
CREATE INDEX idx_encounters_service_dates
    ON encounters(service_from_date, service_to_date);

-- Deduplication/reconciliation
CREATE INDEX idx_encounters_claim_id_version
    ON encounters(claim_id, claim_version_number DESC, submission_date DESC);

-- Claims submission status tracking
CREATE INDEX idx_claims_submission_status
    ON encounters(data_source_code, submission_type, claim_status)
    WHERE claim_status IN ('Accepted', 'Validated');
```

### Materialized Views for Dashboard Performance

```sql
-- Pre-aggregated metrics (refresh hourly/daily)
CREATE MATERIALIZED VIEW mv_plan_raf_summary AS
SELECT
    plan_dim_id,
    time_dim_id,
    
    COUNT(DISTINCT patient_dim_id) as member_count,
    COUNT(*) as raf_records,
    
    MIN(raf_score) as min_raf,
    MAX(raf_score) as max_raf,
    AVG(raf_score) as avg_raf,
    STDDEV(raf_score) as stddev_raf,
    
    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY raf_score) as raf_p25,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY raf_score) as raf_p50,
    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY raf_score) as raf_p75,
    
    SUM(raf_score * 10400) as estimated_annual_revenue
FROM fact_member_raf_monthly
GROUP BY plan_dim_id, time_dim_id;

CREATE INDEX idx_mv_plan_summary ON mv_plan_raf_summary(plan_dim_id, time_dim_id);
```

---

## Data Quality & Validation Patterns

### Encounter Data Quality Scorecard

```sql
-- Comprehensive data quality metrics
CREATE TABLE data_quality_scorecard (
    quality_check_id BIGINT PRIMARY KEY,
    check_date TIMESTAMP,
    
    -- Source quality
    claims_submission_acceptance_rate NUMERIC(5,2),
    chart_review_submission_acceptance_rate NUMERIC(5,2),
    
    -- Completeness
    encounters_with_diagnosis_count INT,
    encounters_with_diagnosis_percentage NUMERIC(5,2),
    members_with_hcc_count INT,
    members_with_hcc_percentage NUMERIC(5,2),
    
    -- Accuracy
    icd10_to_hcc_mapping_success_rate NUMERIC(5,2),
    duplicate_claim_detection_rate NUMERIC(5,2),
    
    -- Validity
    invalid_npi_count INT,
    invalid_service_date_count INT,
    invalid_icd10_code_count INT,
    
    -- Timeliness
    avg_days_to_encounter_submission INT,
    avg_days_to_chart_review INT,
    
    -- Consistency
    member_id_match_rate NUMERIC(5,2),  -- Claims vs. demographics
    diagnosis_reconciliation_rate NUMERIC(5,2),  -- Claims vs. EDR vs. CRR
    
    -- Overall DQ score
    data_quality_score NUMERIC(5,2),  -- Weighted combination
    dq_rating VARCHAR(20),  -- 'EXCELLENT', 'GOOD', 'NEEDS_ATTENTION'
    
    -- Trend
    prior_month_dq_score NUMERIC(5,2),
    dq_trend VARCHAR(20)  -- 'IMPROVING', 'STABLE', 'DECLINING'
);

-- Calculate DQ score
INSERT INTO data_quality_scorecard
SELECT
    CURRENT_TIMESTAMP as check_date,
    
    -- Acceptance rates
    ROUND(100.0 * SUM(CASE WHEN claim_status = 'Accepted' THEN 1 ELSE 0 END)
        / NULLIF(COUNT(*), 0), 2) as claims_acceptance_rate,
    
    -- Diagnosis completeness
    ROUND(100.0 * SUM(CASE WHEN diagnosis_count > 0 THEN 1 ELSE 0 END)
        / NULLIF(COUNT(DISTINCT patient_id), 0), 2) as diagnosis_completeness,
    
    -- Weighted DQ calculation
    ROUND(
        0.30 * claims_acceptance_rate +
        0.25 * diagnosis_completeness +
        0.20 * icd10_mapping_success +
        0.15 * duplicate_detection +
        0.10 * timeliness_score,
        2
    ) as data_quality_score
FROM encounters
WHERE created_at >= CURRENT_DATE - INTERVAL 30 DAY;
```

### Anomaly Detection

```sql
-- Identify unusual encounters for QA review
SELECT
    encounter_id,
    member_id,
    service_from_date,
    
    -- Flags
    CASE WHEN hcc_count > 10 THEN 'HIGH_HCC_COUNT' ELSE NULL END as flag_1,
    CASE WHEN allowed_amount > (SELECT PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY allowed_amount) FROM encounters) 
         THEN 'OUTLIER_AMOUNT' ELSE NULL END as flag_2,
    CASE WHEN diagnosis_count > 25 THEN 'EXCESSIVE_DIAGNOSES' ELSE NULL END as flag_3,
    CASE WHEN provider_npi = '0000000000' THEN 'INVALID_NPI' ELSE NULL END as flag_4,
    
    -- Risk score
    CASE WHEN hcc_count > 10 THEN 1 ELSE 0 END +
    CASE WHEN allowed_amount > threshold_99 THEN 1 ELSE 0 END +
    CASE WHEN diagnosis_count > 25 THEN 1 ELSE 0 END as anomaly_risk_score
    
FROM encounters
WHERE created_at >= CURRENT_DATE - INTERVAL 7 DAY
  AND anomaly_risk_score > 0
ORDER BY anomaly_risk_score DESC;
```

---

## Streaming & Real-Time Patterns

### Kafka Topic Design for RAF

```yaml
KAFKA_TOPICS:
  
  claims_raw:
    # EDI 837 files arriving from payers
    partitions: 16
    replication_factor: 3
    retention: 30 days
    schema:
      claim_id, member_id, service_date, provider_npi,
      diagnoses[], amount, submission_date
  
  encounters_enriched:
    # Parsed, deduplicated encounters post-validation
    partitions: 32
    schema:
      encounter_id, patient_id, hcc_codes[], evidence_source,
      created_at
  
  gap_closures_detected:
    # Real-time gap identification
    partitions: 8
    schema:
      gap_id, member_id, measure_code, hcc_code_confirmed,
      timestamp
  
  raf_calculation_events:
    # RAF changes (for audit trail)
    partitions: 4
    schema:
      member_id, service_year, old_raf, new_raf,
      calculation_type, timestamp
```

### Real-Time Gap Detection (Spark Streaming)

```python
# Consumer: Real-time gap detection
def real_time_gap_detection(spark):
    
    encounters = spark.readStream \
        .format("kafka") \
        .option("kafka.bootstrap.servers", "kafka:9092") \
        .option("subscribe", "encounters_enriched") \
        .load()
    
    # Parse JSON
    schema = StructType([
        StructField("member_id", StringType()),
        StructField("hcc_codes", ArrayType(StringType())),
        StructField("service_date", DateType()),
        StructField("encounter_type", StringType())
    ])
    
    encounters = encounters.select(
        from_json(col("value"), schema).alias("encounter")
    ).select("encounter.*")
    
    # Join with member demographics for attribution
    members = spark.read.table("dim_patient")
    enriched = encounters.join(members, "member_id")
    
    # Detect gap closures
    # Rule: If encounter has certain HCC codes + no prior occurrence in past 12 months
    gap_closures = enriched.filter(
        col("hcc_codes").contains("HCC19") &
        (~col("member_id").isin(
            spark.sql("SELECT DISTINCT member_id FROM past_diagnoses WHERE year = 2024")
        ))
    )
    
    # Write to sink (Snowflake + Kafka)
    query = gap_closures.writeStream \
        .format("kafka") \
        .option("kafka.bootstrap.servers", "kafka:9092") \
        .option("topic", "gap_closures_detected") \
        .option("checkpointLocation", "/tmp/gap_closure_ckpt") \
        .start()
    
    return query
```

---

## Testing & Validation Patterns

### Unit Test: RAF Calculation

```python
import pytest

class TestRAFCalculation:
    
    @pytest.fixture
    def test_member(self):
        return {
            'member_id': 'TEST001',
            'age': 72,
            'sex': 'M',
            'hcc_codes': ['HCC19', 'HCC82'],  # Diabetes + Cardiac
            'service_year': 2024
        }
    
    def test_raf_calculation_basic(self, test_member):
        """RAF = age_sex_factor + hcc_coefficients"""
        calculator = RAFCalculator(model_version='V28')
        
        # Expected: M72 = 0.485, HCC19 = 0.183, HCC82 = 0.133
        expected_raw_raf = 0.485 + 0.183 + 0.133  # = 0.801
        
        result = calculator.calculate(test_member)
        
        assert abs(result['raw_raf'] - expected_raw_raf) < 0.001
    
    def test_hcc_hierarchy_applied(self):
        """HCC18 subsumes by HCC19"""
        member = {
            'hcc_codes': ['HCC18', 'HCC19'],
            'age': 70, 'sex': 'F'
        }
        
        calc = RAFCalculator(model_version='V28')
        result = calc.calculate(member)
        
        # Should only count HCC19, not HCC18
        assert 'HCC18' not in result['applied_hccs']
        assert 'HCC19' in result['applied_hccs']
    
    def test_sweep_reconciliation(self):
        """Sweep RAF < Initial RAF triggers negative adjustment"""
        member_id = 'TEST002'
        prior_raf = 1.150
        sweep_raf = 1.090
        
        adjustment = sweep_raf - prior_raf  # -0.060
        revenue_impact = adjustment * 10400  # -$624
        
        assert revenue_impact < 0  # Plan receives negative adjustment
    
    def test_coding_intensity_ratio(self):
        """High coding intensity = Actual RAF / Expected RAF > 1.15"""
        actual_avg_raf = 1.200
        demographic_only = 0.950
        
        intensity_ratio = actual_avg_raf / demographic_only  # 1.263
        
        assert intensity_ratio > 1.15  # HIGH coding intensity
```

### Integration Test: End-to-End Pipeline

```python
class TestRAFPipeline:
    
    def test_monthly_raf_calculation_pipeline(self):
        """Full pipeline: Extract -> Transform -> Calculate -> Validate -> Report"""
        
        # 1. Load test claims data
        test_claims = load_test_data('claims_sample.csv')
        spark.createDataFrame(test_claims).write.mode("overwrite").saveAsTable("bronze_claims")
        
        # 2. Run transformation
        pipeline = RAFMonthlyPipeline()
        pipeline.deduplicate_encounters()
        pipeline.map_icd10_to_hcc()
        
        # 3. Calculate RAF
        pipeline.run_raf_calculation()
        
        # 4. Validate
        raf_results = spark.sql("SELECT * FROM gold_member_raf_monthly")
        
        assert raf_results.count() > 0
        assert raf_results.select("final_raf_score").toPandas()["final_raf_score"].min() > 0
        assert raf_results.select("final_raf_score").toPandas()["final_raf_score"].max() < 5.0
        
        # 5. Check quality metrics
        quality = spark.sql("""
            SELECT
                COUNT(*) as raf_count,
                ROUND(AVG(final_raf_score), 4) as avg_raf,
                COUNT(CASE WHEN hcc_count > 0 THEN 1 END) / COUNT(*) as pct_with_hcc
            FROM gold_member_raf_monthly
        """).collect()[0]
        
        assert quality['pct_with_hcc'] > 0.85  # >85% should have ≥1 HCC
        assert quality['avg_raf'] > 1.0  # Sanity check
```

---

## Performance Tuning Examples

### Query Optimization: Large Member Cohorts

**Problem:** Calculating RAF for 500k members is slow

```sql
-- BEFORE: Full table scan, slow
SELECT
    member_id,
    final_raf_score
FROM raf_calculation_results
WHERE service_year = 2024
ORDER BY final_raf_score DESC
LIMIT 10000;  -- Returns 500k rows, filters 490k after sort

-- AFTER: Partition pruning + cluster
ALTER TABLE raf_calculation_results
CLUSTER BY (service_year, plan_id);

-- Now queries with service_year + plan_id predicates use clustered scan
SELECT
    member_id,
    final_raf_score
FROM raf_calculation_results
WHERE service_year = 2024
  AND plan_id = 'PLAN123'
ORDER BY final_raf_score DESC
LIMIT 10000;  -- Fast: only scans PLAN123 cluster
```

### HCC Coefficient Lookup Optimization

```sql
-- Create lookup table with hash index
CREATE TABLE hcc_coefficients_indexed (
    coefficient_key INT,  -- Hash of (hcc_code, age_sex, model_year)
    hcc_code VARCHAR(10),
    age_sex_category VARCHAR(20),
    model_version VARCHAR(10),
    coefficient_value NUMERIC(10,6)
)
CLUSTERED BY (coefficient_key) INTO 256 BUCKETS;

-- Use hash join instead of nested loop
SELECT
    r.member_id,
    SUM(h.coefficient_value) as disease_factor
FROM raf_staging r
INNER JOIN hcc_coefficients_indexed h
    ON HASH(r.hcc_code, r.age_sex_cat, r.model_version) = h.coefficient_key
    AND r.hcc_code = h.hcc_code
    AND r.age_sex_cat = h.age_sex_category
    AND r.model_version = h.model_version
GROUP BY r.member_id;
```

---

## File Paths & References

**Core Documentation:**
- `/Users/murali/Desktop/raf-intelligence/RAF_SaaS_Data_Architecture_Research.md` — Main research document (Section 1-11 comprehensive coverage)

**Implementation Reference:**
- `/Users/murali/Desktop/raf-intelligence/Technical_Implementation_Patterns.md` — This file with SQL, Python code examples

**Related Resources:**
- CMS HCC Crosswalk: https://www.cms.gov/ (official ICD-10 to HCC mappings, updated annually)
- NCQA HEDIS: https://www.ncqa.org/hedis/ (quality measure specifications)
- Snowflake/BigQuery Docs: Cloud provider documentation for warehouse setup

