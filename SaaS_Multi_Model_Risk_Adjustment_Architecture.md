# SaaS Multi-Model Risk Adjustment Architecture & Implementation Guide

## Document Overview

This document provides technical architecture patterns, implementation details, and technology recommendations for a SaaS platform supporting multiple risk adjustment models (HHS-HCC, CMS-HCC V24/V28, CDPS, ACG, DxCG, Impact Pro) across healthcare payers.

---

## 1. Architecture Overview

### 1.1 Layered Architecture Pattern

```
┌──────────────────────────────────────────────────────────────┐
│                    Presentation Layer                         │
│  ├─ Web UI (React, Vue, Angular)                            │
│  ├─ REST API (OpenAPI/Swagger)                              │
│  ├─ Mobile app (optional)                                    │
│  └─ Reporting dashboards (Tableau, Superset, Kibana)        │
├──────────────────────────────────────────────────────────────┤
│              Business Logic & Orchestration                   │
│  ├─ Workflow engine (Apache Airflow, Temporal)              │
│  ├─ Risk calculation orchestration                           │
│  ├─ Payment formula execution                                │
│  └─ Compliance rule engine                                   │
├──────────────────────────────────────────────────────────────┤
│              Risk Calculation Microservices                   │
│  ├─ HHS-HCC Calculator (Python/Java)                        │
│  ├─ CMS-HCC V24 Calculator                                  │
│  ├─ CMS-HCC V28 Calculator (with constraining)              │
│  ├─ CDPS/CDPS+Rx Calculator                                 │
│  ├─ ACG Calculator                                           │
│  ├─ DxCG Calculator                                          │
│  ├─ Frailty Score Calculator                                │
│  └─ ESRD Modifier Service                                    │
├──────────────────────────────────────────────────────────────┤
│              Data Processing & Validation                     │
│  ├─ ETL pipelines (Apache Spark, custom)                    │
│  ├─ Claim normalization                                      │
│  ├─ Code validation service                                  │
│  ├─ MEAT criteria validator                                 │
│  └─ Deduplication service                                    │
├──────────────────────────────────────────────────────────────┤
│              Compliance & Audit Layer                         │
│  ├─ EDGE/MAO-004 validator                                  │
│  ├─ RADV evidence gathering                                 │
│  ├─ Audit log service (immutable)                           │
│  ├─ Encryption service                                       │
│  └─ Access control (RBAC)                                    │
├──────────────────────────────────────────────────────────────┤
│                  Data Layer                                   │
│  ├─ Relational DB (PostgreSQL)                              │
│  ├─ Time-series DB (TimescaleDB, InfluxDB)                 │
│  ├─ Cache layer (Redis)                                      │
│  ├─ Document store (optional, for unstructured)             │
│  └─ Data warehouse (Snowflake, BigQuery)                    │
├──────────────────────────────────────────────────────────────┤
│              Infrastructure & DevOps                          │
│  ├─ Kubernetes cluster management                            │
│  ├─ Container registry (Docker Hub, ECR)                    │
│  ├─ Monitoring (Prometheus, Datadog)                        │
│  ├─ Logging (ELK, Splunk)                                   │
│  └─ CI/CD pipelines (GitHub Actions, GitLab CI)            │
└──────────────────────────────────────────────────────────────┘
```

### 1.2 Data Flow Architecture

```
                    Claims/Enrollment Data
                            │
                    ┌───────┴────────┐
                    │                 │
              SFTP/FTPS          REST API
              (Batch)           (Real-time)
                    │                 │
                    └───────┬─────────┘
                            │
                    ┌───────▼────────────┐
                    │  Input Validation  │
                    │  ├─ Format check   │
                    │  ├─ File integrity │
                    │  └─ Row count      │
                    └───────┬────────────┘
                            │
                    ┌───────▼────────────┐
                    │ Normalization      │
                    │ ├─ ICD-10 format   │
                    │ ├─ Date formats    │
                    │ └─ ID standards    │
                    └───────┬────────────┘
                            │
        ┌───────────────────┴────────────────────┐
        │                                          │
   ┌────▼──────┐                         ┌────────▼────┐
   │  Medical  │                         │  Pharmacy   │
   │  Claims   │                         │  Claims     │
   └────┬──────┘                         └────────┬────┘
        │                                        │
        │   ┌──────────────────────────────────┐ │
        │   │  Code Mapping Service             │ │
        │   │ ├─ ICD-10 validation              │ │
        │   │ ├─ HCC assignment (all models)    │ │
        │   │ ├─ NDC mapping (pharmacy)         │ │
        │   │ └─ Hierarchy application          │ │
        │   └──────────────────────────────────┘ │
        │              │                          │
        └──────────────┼──────────────────────────┘
                       │
        ┌──────────────▼──────────────┐
        │  Member Aggregation         │
        │  ├─ Dedup claims            │
        │  ├─ HOS-M survey data       │
        │  ├─ Demographics assembly   │
        │  └─ Eligibility tracking    │
        └──────────────┬──────────────┘
                       │
   ┌───────┬───────┬───┴───┬──────────┬──────────┐
   │       │       │       │          │          │
 ┌─▼─┐ ┌──▼──┐ ┌─▼──┐ ┌──▼──┐ ┌────▼────┐ ┌──▼──┐
 │HHS│ │CMS  │ │CMS │ │CDPS │ │Frailty  │ │ESRD │
 │HCC│ │HCC  │ │HCC │ │+Rx  │ │Calc     │ │Mod  │
 │   │ │V24  │ │V28 │ │     │ │         │ │     │
 └──┬┘ └──┬──┘ └─┬──┘ └──┬──┘ └────┬────┘ └──┬──┘
    │    │     │    │         │       │
    │    │     │    │  ┌──────┴───┐  │
    │    │     │    │  │ ACG/DxCG │  │
    │    │     │    │  │ Engines  │  │
    │    │     │    │  └──────┬───┘  │
    │    │     │    │         │      │
    └────┼─────┼────┼─────┬───┴──────┘
         │     │    │     │
    ┌────▼─────▼────▼─────▼──────────┐
    │  Risk Score Validation         │
    │  ├─ Outlier detection          │
    │  ├─ Hierarchy conflicts        │
    │  ├─ Constraining rules (V28)   │
    │  └─ MEAT criteria check        │
    └────┬──────────────────────────┘
         │
    ┌────▼──────────────────────┐
    │  Payment Calculation      │
    │  ├─ Capitation formulas   │
    │  ├─ Transfer formula (ACA)│
    │  ├─ Frailty multipliers   │
    │  └─ State rate cells      │
    └────┬──────────────────────┘
         │
    ┌────▼──────────────────────┐
    │  Compliance Validation    │
    │  ├─ EDGE/MAO-004 check    │
    │  ├─ RADV audit trail      │
    │  ├─ Evidence gathering    │
    │  └─ Documentation links   │
    └────┬──────────────────────┘
         │
    Risk Score Report
    (Excel, JSON, API)
```

---

## 2. Core Microservices Design

### 2.1 HHS-HCC Calculator Service

**Purpose**: Calculate risk adjustment for ACA marketplace plans

**Key Characteristics**:
- 127 HCC categories
- Concurrent scoring (current year predicts current year)
- Includes pharmacy costs
- Pregnancy code handling (656 codes)

**Implementation**:

```python
# Pseudocode for HHS-HCC Calculator

class HHSHCCCalculator:
    def __init__(self):
        self.hcc_hierarchies = load_hierarchies()  # Parent-child relationships
        self.hcc_coefficients = load_coefficients()  # Risk weights
        self.code_to_hcc_map = load_icd_to_hcc_mapping()  # 9,797 codes → 127 HCCs
        
    def calculate_score(self, member_id, diagnosis_codes, rx_codes, demographics):
        """
        Args:
            member_id: unique member identifier
            diagnosis_codes: list of ICD-10 codes from claims
            rx_codes: list of NDC codes from pharmacy claims
            demographics: {age, sex, region}
            
        Returns:
            {
                'member_id': str,
                'raw_risk_score': float,
                'hcc_list': list[int],
                'hcc_rationale': dict,
                'model': 'HHS_HCC',
                'version': '127',
                'timestamp': datetime
            }
        """
        
        # 1. Validate and normalize codes
        valid_diagnosis_codes = self.validate_codes(diagnosis_codes, code_type='icd10')
        valid_rx_codes = self.validate_codes(rx_codes, code_type='ndc')
        
        # 2. Map to HCC categories
        assigned_hccs = set()
        hcc_evidence = {}
        
        for code in valid_diagnosis_codes:
            if code in self.code_to_hcc_map:
                hcc = self.code_to_hcc_map[code]
                assigned_hccs.add(hcc)
                if hcc not in hcc_evidence:
                    hcc_evidence[hcc] = []
                hcc_evidence[hcc].append(code)
        
        # 3. Apply HCC hierarchies (remove parent if child present)
        final_hccs = self.apply_hierarchies(assigned_hccs)
        
        # 4. Map pharmacy codes to HCCs (if applicable)
        for rx_code in valid_rx_codes:
            hcc = self.map_rx_to_hcc(rx_code)
            if hcc:
                final_hccs.add(hcc)
                if hcc not in hcc_evidence:
                    hcc_evidence[hcc] = []
                hcc_evidence[hcc].append(f"RX:{rx_code}")
        
        # 5. Apply demographic factors
        demo_factor = self.get_demographic_factor(demographics)
        
        # 6. Calculate raw risk score
        raw_score = demo_factor  # Start with demographic base
        for hcc in final_hccs:
            raw_score += self.hcc_coefficients.get(hcc, 0)
        
        # 7. Apply pregnancy multiplier if applicable
        if self.has_pregnancy_codes(valid_diagnosis_codes):
            raw_score *= self.pregnancy_multiplier
        
        return {
            'member_id': member_id,
            'raw_risk_score': raw_score,
            'hcc_list': sorted(list(final_hccs)),
            'hcc_rationale': hcc_evidence,
            'model': 'HHS_HCC',
            'version': '127',
            'timestamp': datetime.now()
        }
    
    def apply_hierarchies(self, hcc_set):
        """Remove parent HCCs when child is present"""
        final_hccs = set(hcc_set)
        for parent, children in self.hcc_hierarchies.items():
            if parent in final_hccs:
                if any(child in final_hccs for child in children):
                    final_hccs.discard(parent)  # Remove parent
        return final_hccs
```

**Deployment Pattern**:
- Docker container with Python runtime
- Kubernetes service with auto-scaling
- Health checks on HCC coefficient freshness
- Separate deployment track for ACA-specific logic

### 2.2 CMS-HCC Calculator Service (V24/V28)

**Purpose**: Calculate risk adjustment for Medicare Advantage, PACE, ESRD programs

**Key Challenges**:
- V24 and V28 blending during transition (2024-2029)
- V28 constraining rules (prevent double-counting related HCCs)
- ESRD special handling (omit kidney disease HCCs)
- Frailty adjustment integration

**Implementation**:

```python
class CMSHCCCalculator:
    def __init__(self, version='V28', blend_ratio=None):
        """
        Args:
            version: 'V24' or 'V28' (or 'blend' for PACE)
            blend_ratio: {'V28': 0.67, 'V24': 0.33} for blended scoring
        """
        self.version = version
        self.blend_ratio = blend_ratio
        
        if version in ['V28', 'blend']:
            self.v28_hierarchies = load_v28_hierarchies()  # 115 HCCs
            self.v28_constraints = load_v28_constraints()  # Constraining rules
            self.v28_coefficients = load_v28_coefficients()
            
        if version in ['V24', 'blend']:
            self.v24_hierarchies = load_v24_hierarchies()  # 86 HCCs
            self.v24_coefficients = load_v24_coefficients()
        
        self.code_to_v28_hcc = load_v28_icd_mapping()  # 7,770 codes → 115 HCCs
        self.code_to_v24_hcc = load_v24_icd_mapping()  # 9,797 codes → 86 HCCs
    
    def calculate_score(self, member_id, diagnosis_codes, demographics, 
                       payment_year=2025, population='MA', include_esrd=False):
        """
        Args:
            member_id: unique member
            diagnosis_codes: ICD-10 codes
            demographics: {age, sex, dual_eligible, institutional}
            payment_year: for determining blend ratios (PACE transition)
            population: 'MA' | 'PACE' | 'D-SNP' | 'ESRD'
            include_esrd: whether to apply ESRD model
        """
        
        scores = {}
        
        # Calculate V28 if applicable
        if self.version in ['V28', 'blend']:
            scores['V28'] = self._calculate_v28(
                member_id, diagnosis_codes, demographics, 
                is_esrd=include_esrd
            )
        
        # Calculate V24 if applicable (for blending)
        if self.version in ['V24', 'blend']:
            scores['V24'] = self._calculate_v24(
                member_id, diagnosis_codes, demographics
            )
        
        # Determine blend ratio based on payment year
        if self.version == 'blend':
            final_score = self._blend_scores(scores, payment_year)
        else:
            final_score = scores.get(self.version)
        
        return final_score
    
    def _calculate_v28(self, member_id, diagnosis_codes, demographics, is_esrd=False):
        """
        V28-specific calculation with constraining rules
        """
        # Validate codes (V28 uses 7,770 valid codes)
        valid_codes = [c for c in diagnosis_codes if c in self.code_to_v28_hcc]
        
        # Map to HCC
        assigned_hccs = set()
        hcc_evidence = {}
        
        for code in valid_codes:
            hcc = self.code_to_v28_hcc[code]
            assigned_hccs.add(hcc)
            if hcc not in hcc_evidence:
                hcc_evidence[hcc] = []
            hcc_evidence[hcc].append(code)
        
        # Apply ESRD special logic
        if is_esrd:
            assigned_hccs = self._apply_esrd_logic(assigned_hccs)
        
        # Apply hierarchies
        final_hccs = self.apply_v28_hierarchies(assigned_hccs)
        
        # Apply constraining rules (CRITICAL for V28)
        constrained_hccs = self._apply_constraining(final_hccs)
        
        # Calculate score with constrained HCCs
        demo_factor = self.get_demographic_factor(demographics)
        score = demo_factor
        
        for hcc in constrained_hccs:
            score += self.v28_coefficients.get(hcc, 0)
        
        return {
            'member_id': member_id,
            'model': 'CMS_HCC',
            'version': 'V28',
            'raw_risk_score': score,
            'assigned_hccs': sorted(list(assigned_hccs)),
            'constrained_hccs': sorted(list(constrained_hccs)),
            'hcc_evidence': hcc_evidence,
            'demographic_factor': demo_factor
        }
    
    def _apply_constraining(self, hcc_set):
        """
        V28 constraining: Related HCCs get same coefficient
        Example: Diabetes + diabetic complication = only one coefficient
        """
        constrained = set(hcc_set)
        
        # Apply constraint rules
        for constraint_group in self.v28_constraints:
            # constraint_group = {
            #     'member_hccs': [hcc1, hcc2],
            #     'logic': 'keep_highest_only' | 'keep_parent' | 'keep_child'
            # }
            
            intersection = [h for h in constraint_group['member_hccs'] if h in constrained]
            
            if len(intersection) > 1:
                if constraint_group['logic'] == 'keep_highest_only':
                    # Keep HCC with highest coefficient
                    highest = max(intersection, 
                                 key=lambda h: self.v28_coefficients.get(h, 0))
                    for hcc in intersection:
                        if hcc != highest:
                            constrained.discard(hcc)
        
        return constrained
    
    def _apply_esrd_logic(self, hcc_set):
        """
        Remove kidney-disease HCCs for ESRD patients
        (all have ESRD so these don't add discriminating value)
        """
        esrd_exclusion_hccs = {136, 137, 138}  # Dialysis, renal failure, nephritis (V28)
        return hcc_set - esrd_exclusion_hccs
    
    def _blend_scores(self, scores, payment_year):
        """PACE transition blending logic"""
        # 2024: 33% V28, 67% V24
        # 2025: 67% V28, 33% V24
        # 2026: 100% V28
        
        blend_map = {
            2024: {'V28': 0.33, 'V24': 0.67},
            2025: {'V28': 0.67, 'V24': 0.33},
            2026: {'V28': 1.00, 'V24': 0.00},
        }
        
        blend = blend_map.get(payment_year, {'V28': 1.00, 'V24': 0.00})
        
        final_score = (
            blend.get('V28', 0) * scores.get('V28', {}).get('raw_risk_score', 0) +
            blend.get('V24', 0) * scores.get('V24', {}).get('raw_risk_score', 0)
        )
        
        return {
            'member_id': scores['V28']['member_id'],
            'model': 'CMS_HCC',
            'version': 'BLENDED',
            'payment_year': payment_year,
            'blend_ratio': blend,
            'v28_score': scores.get('V28', {}).get('raw_risk_score'),
            'v24_score': scores.get('V24', {}).get('raw_risk_score'),
            'final_risk_score': final_score
        }
```

### 2.3 CDPS Calculator Service

**Purpose**: Medicaid managed care capitation adjustment

**Key Differences from CMS-HCC**:
- 52 specific categories (vs. 115 CMS-HCC V28)
- Fewer total codes (gaming-resistant design)
- Medicaid-specific conditions emphasized
- Psychiatric, pulmonary, renal categories recently updated

**Implementation Pattern**:

```python
class CDPSCalculator:
    def __init__(self, version='7.0'):
        """
        CDPS+Rx version 7.0 includes pharmacy
        """
        self.version = version
        self.major_categories = 19  # Defined body system categories
        self.specific_categories = 52
        
        self.icd_to_cdps = load_cdps_icd_mapping()
        self.ndc_to_therapeutic = load_ndc_therapeutic_mapping()
        self.cdps_weights = load_cdps_weights()  # Linear regression coefficients
        self.hierarchies = load_cdps_hierarchies()
    
    def calculate_score(self, member_id, diagnosis_codes, rx_codes, 
                       demographics, state='CA'):
        """
        Args:
            state: different Medicaid programs might weight differently
        """
        
        # Map diagnoses to CDPS categories
        assigned_categories = set()
        
        for code in diagnosis_codes:
            if code in self.icd_to_cdps:
                category = self.icd_to_cdps[code]
                assigned_categories.add(category)
        
        # Map pharmacy to CDPS (if using CDPS+Rx)
        for rx_code in rx_codes:
            if rx_code in self.ndc_to_therapeutic:
                therapeutic = self.ndc_to_therapeutic[rx_code]
                # Some therapeutics map to CDPS categories
                if therapeutic in self.ndc_therapeutic_to_cdps:
                    category = self.ndc_therapeutic_to_cdps[therapeutic]
                    assigned_categories.add(category)
        
        # Apply hierarchies (fewer than CMS-HCC due to gaming resistance)
        final_categories = self.apply_hierarchies(assigned_categories)
        
        # Linear regression model: calculate predicted spend
        base_spend = self.get_base_spend(demographics, state)
        
        category_adjustments = 0
        for category in final_categories:
            adjustment = self.cdps_weights.get(category, 1.0)
            category_adjustments += adjustment
        
        predicted_spend = base_spend * category_adjustments
        
        # Normalize to risk score (relative to state average)
        state_avg_spend = self.get_state_average_spend(state)
        risk_score = predicted_spend / state_avg_spend
        
        return {
            'member_id': member_id,
            'model': 'CDPS',
            'version': self.version,
            'assigned_categories': sorted(list(assigned_categories)),
            'final_categories': sorted(list(final_categories)),
            'predicted_spend': predicted_spend,
            'state_average_spend': state_avg_spend,
            'risk_score': risk_score
        }
```

### 2.4 Frailty Score Calculator Service

**Purpose**: PACE and FIDE SNP organizational frailty adjustment

**Implementation**:

```python
class FrailtyCalculator:
    def __init__(self):
        self.hos_m_adl_items = 6  # HOS-M core ADL items
        self.frailty_factors_v24 = load_v24_frailty_factors()
        self.frailty_factors_v28 = load_v28_frailty_factors()
    
    def calculate_organizational_frailty(self, hos_m_responses_list, 
                                        payment_year=2025, 
                                        program='PACE'):
        """
        Args:
            hos_m_responses_list: list of individual HOS-M survey responses
            payment_year: for V24/V28 blending
            program: 'PACE' | 'FIDE_SNP'
        
        Returns:
            Organizational frailty score
        """
        
        # Calculate individual frailty scores
        individual_scores = []
        
        for response in hos_m_responses_list:
            # Response contains ADL limitation levels
            individual_score = self._calculate_individual_frailty(response)
            individual_scores.append(individual_score)
        
        # Aggregate to organizational level
        org_score = sum(individual_scores) / len(individual_scores)
        
        # Apply V24/V28 blending if applicable
        if program == 'PACE' and payment_year >= 2024:
            org_score = self._blend_frailty_versions(org_score, payment_year)
        
        return {
            'organizational_frailty_score': org_score,
            'participant_count': len(hos_m_responses_list),
            'payment_year': payment_year,
            'program': program,
            'meets_minimum_threshold': org_score >= self.get_program_minimum(program)
        }
    
    def _calculate_individual_frailty(self, hos_m_response):
        """
        HOS-M response contains ADL limitations
        - Walking alone
        - Dressing
        - Bathing
        - Using toilet
        - Getting in/out of bed
        - Eating
        """
        
        adl_limitation_count = sum([
            hos_m_response.get('adl_walking', 0),
            hos_m_response.get('adl_dressing', 0),
            hos_m_response.get('adl_bathing', 0),
            hos_m_response.get('adl_toilet', 0),
            hos_m_response.get('adl_bed', 0),
            hos_m_response.get('adl_eating', 0)
        ])
        
        # Map to frailty factor
        factor = self.frailty_factors_v28.get(adl_limitation_count, 0)
        return factor
    
    def _blend_frailty_versions(self, frailty_score, payment_year):
        """PACE gradual transition from V24 to V28"""
        blend_map = {
            2024: {'V28': 0.33, 'V24': 0.67},
            2025: {'V28': 0.67, 'V24': 0.33},
            2026: {'V28': 1.00, 'V24': 0.00},
        }
        
        blend = blend_map.get(payment_year, {'V28': 1.00})
        # In real implementation would recalculate with both versions
        return frailty_score  # Simplified
```

---

## 3. Data Pipeline Architecture

### 3.1 Batch Processing Pipeline

**Technology Stack**:
- **Orchestration**: Apache Airflow or Temporal
- **Processing**: Apache Spark or custom Python/Java
- **Storage**: PostgreSQL (transactional), S3 (archives)
- **Message Queue**: Kafka (optional, for streaming subset)

**Pipeline Stages**:

```python
# Apache Airflow DAG structure

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.spark_submit import SparkSubmitOperator
from datetime import datetime, timedelta

default_args = {
    'owner': 'risk_adjustment',
    'retries': 3,
    'retry_delay': timedelta(hours=2),
    'email_on_failure': True,
}

with DAG(
    dag_id='risk_adjustment_daily',
    default_args=default_args,
    schedule_interval='0 2 * * *',  # 2 AM daily
    catchup=False,
) as dag:
    
    # Stage 1: Ingest
    ingest_claims = PythonOperator(
        task_id='ingest_claims_from_sftp',
        python_callable=ingest_claims_from_sftp,
        op_kwargs={
            'sftp_path': '/claims/daily/',
            'target_bucket': 's3://raw-claims/'
        }
    )
    
    # Stage 2: Validate
    validate_format = SparkSubmitOperator(
        task_id='validate_claim_format',
        application='/jobs/spark/validate_claims.py',
        conf={
            'spark.executor.memory': '4g',
            'spark.executor.cores': 4,
        }
    )
    
    # Stage 3: Normalize
    normalize_codes = SparkSubmitOperator(
        task_id='normalize_icd_codes',
        application='/jobs/spark/normalize_codes.py',
    )
    
    # Stage 4: Deduplicate
    dedup = SparkSubmitOperator(
        task_id='deduplicate_by_member',
        application='/jobs/spark/dedup.py',
    )
    
    # Stage 5: Calculate Scores (parallel)
    calc_hhs_hcc = SparkSubmitOperator(
        task_id='calculate_hhs_hcc_scores',
        application='/jobs/spark/calc_hhs_hcc.py',
    )
    
    calc_cms_hcc = SparkSubmitOperator(
        task_id='calculate_cms_hcc_scores',
        application='/jobs/spark/calc_cms_hcc.py',
    )
    
    calc_cdps = SparkSubmitOperator(
        task_id='calculate_cdps_scores',
        application='/jobs/spark/calc_cdps.py',
    )
    
    # Stage 6: Validate Output
    validate_output = PythonOperator(
        task_id='validate_risk_scores',
        python_callable=validate_scores,
    )
    
    # Stage 7: Compliance Check
    compliance_check = PythonOperator(
        task_id='edge_mao004_validation',
        python_callable=validate_edge_compliance,
    )
    
    # Stage 8: Report Generation
    generate_reports = PythonOperator(
        task_id='generate_final_reports',
        python_callable=generate_reports,
    )
    
    # DAG flow
    ingest_claims >> validate_format >> normalize_codes >> dedup
    dedup >> [calc_hhs_hcc, calc_cms_hcc, calc_cdps]
    [calc_hhs_hcc, calc_cms_hcc, calc_cdps] >> validate_output
    validate_output >> compliance_check >> generate_reports
```

### 3.2 Code Mapping & Validation Service

**Purpose**: Centralized management of diagnostic code mappings across all models

**Database Schema**:

```sql
-- ICD-10 Code Master
CREATE TABLE icd10_codes (
    icd10_code VARCHAR(10) PRIMARY KEY,
    description TEXT,
    valid_from DATE,
    valid_to DATE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- HCC Assignment Mappings (versioned)
CREATE TABLE code_to_hcc_mapping (
    mapping_id BIGSERIAL PRIMARY KEY,
    icd10_code VARCHAR(10) NOT NULL,
    model_name VARCHAR(50),  -- 'HHS_HCC', 'CMS_HCC_V24', 'CMS_HCC_V28', 'CDPS'
    model_version VARCHAR(20),
    hcc_code INT NOT NULL,
    hcc_description TEXT,
    effective_date DATE NOT NULL,
    end_date DATE,
    created_by VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (icd10_code) REFERENCES icd10_codes(icd10_code),
    INDEX idx_code_model_version (icd10_code, model_name, model_version, effective_date)
);

-- HCC Hierarchies (version-specific)
CREATE TABLE hcc_hierarchies (
    hierarchy_id BIGSERIAL PRIMARY KEY,
    parent_hcc INT NOT NULL,
    child_hcc INT NOT NULL,
    model_name VARCHAR(50),
    model_version VARCHAR(20),
    effective_date DATE NOT NULL,
    end_date DATE,
    UNIQUE KEY unique_hierarchy (parent_hcc, child_hcc, model_name, model_version)
);

-- HCC Coefficients (risk weights)
CREATE TABLE hcc_coefficients (
    coefficient_id BIGSERIAL PRIMARY KEY,
    hcc_code INT NOT NULL,
    model_name VARCHAR(50),
    model_version VARCHAR(20),
    coefficient_value DECIMAL(10, 6) NOT NULL,
    demographic_category VARCHAR(100),  -- 'age_0_5', 'age_65_plus', etc.
    effective_date DATE NOT NULL,
    end_date DATE,
    source TEXT,  -- 'CMS_2024_Advance_Notice', etc.
    UNIQUE KEY unique_coefficient (hcc_code, model_name, model_version, demographic_category, effective_date)
);

-- NDC to Therapeutic Mapping (pharmacy)
CREATE TABLE ndc_therapeutic_mapping (
    ndc_code VARCHAR(11) PRIMARY KEY,
    therapeutic_class VARCHAR(100),
    therapeutic_category VARCHAR(50),
    includes_cdps BOOLEAN DEFAULT FALSE,
    cdps_category INT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Code Change Audit Trail
CREATE TABLE code_mapping_audit (
    audit_id BIGSERIAL PRIMARY KEY,
    icd10_code VARCHAR(10),
    model_name VARCHAR(50),
    old_hcc INT,
    new_hcc INT,
    change_type VARCHAR(50),  -- 'ADD', 'REMOVE', 'REASSIGN'
    reason TEXT,
    changed_by VARCHAR(100),
    changed_at TIMESTAMP DEFAULT NOW(),
    effective_date DATE,
    INDEX idx_code_change (icd10_code, changed_at)
);
```

**Service Implementation**:

```python
class CodeMappingService:
    def __init__(self, db_connection):
        self.db = db_connection
        self.cache = {}  # In-memory cache for performance
    
    def get_hcc_assignment(self, icd10_code, model_name, model_version, 
                          effective_date=None):
        """
        Retrieve HCC assignment for a given diagnosis code and model.
        
        Uses caching layer for performance.
        """
        
        cache_key = f"{icd10_code}:{model_name}:{model_version}"
        
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        if effective_date is None:
            effective_date = datetime.now().date()
        
        query = """
            SELECT hcc_code, hcc_description
            FROM code_to_hcc_mapping
            WHERE icd10_code = %s
            AND model_name = %s
            AND model_version = %s
            AND effective_date <= %s
            AND (end_date IS NULL OR end_date > %s)
            ORDER BY effective_date DESC
            LIMIT 1
        """
        
        result = self.db.execute_query(query, (
            icd10_code, model_name, model_version, 
            effective_date, effective_date
        ))
        
        if result:
            self.cache[cache_key] = result[0]
            return result[0]
        
        return None
    
    def validate_code(self, icd10_code):
        """Validate that ICD-10 code exists in master table"""
        query = "SELECT 1 FROM icd10_codes WHERE icd10_code = %s"
        return bool(self.db.execute_query(query, (icd10_code,)))
    
    def get_hierarchies(self, model_name, model_version):
        """Load HCC hierarchies for a specific model version"""
        query = """
            SELECT parent_hcc, child_hcc
            FROM hcc_hierarchies
            WHERE model_name = %s
            AND model_version = %s
            AND effective_date <= NOW()
            AND (end_date IS NULL OR end_date > NOW())
        """
        
        results = self.db.execute_query(query, (model_name, model_version))
        
        # Build hierarchy dict
        hierarchies = {}
        for parent, child in results:
            if parent not in hierarchies:
                hierarchies[parent] = []
            hierarchies[parent].append(child)
        
        return hierarchies
    
    def get_coefficients(self, model_name, model_version, 
                        demographic_category=None):
        """Get risk weights for HCCs"""
        
        query = """
            SELECT hcc_code, coefficient_value
            FROM hcc_coefficients
            WHERE model_name = %s
            AND model_version = %s
        """
        params = [model_name, model_version]
        
        if demographic_category:
            query += " AND demographic_category = %s"
            params.append(demographic_category)
        
        query += """
            AND effective_date <= NOW()
            AND (end_date IS NULL OR end_date > NOW())
        """
        
        results = self.db.execute_query(query, tuple(params))
        
        return {hcc: coeff for hcc, coeff in results}
    
    def audit_code_change(self, icd10_code, model_name, old_hcc, new_hcc, 
                         reason, user):
        """Log code mapping changes for audit trail"""
        
        query = """
            INSERT INTO code_mapping_audit
            (icd10_code, model_name, old_hcc, new_hcc, change_type, 
             reason, changed_by, effective_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        """
        
        change_type = 'REMOVE' if new_hcc is None else ('ADD' if old_hcc is None else 'REASSIGN')
        
        self.db.execute_query(query, (
            icd10_code, model_name, old_hcc, new_hcc, change_type,
            reason, user
        ))
        
        # Invalidate cache
        cache_key = f"{icd10_code}:{model_name}"
        self.cache.pop(cache_key, None)
```

---

## 4. Compliance & Audit Architecture

### 4.1 EDGE/MAO-004 Validation Service

**Purpose**: Ensure submitted HCCs are accepted by CMS and match expectations

**Implementation**:

```python
class EDGEComplianceValidator:
    def __init__(self, db_connection):
        self.db = db_connection
    
    def validate_submitted_diagnoses(self, member_id, submitted_codes, 
                                     mao004_response):
        """
        Compare submitted diagnosis codes with CMS MAO-004 accepted codes.
        
        MAO-004 = Monthly report showing CMS-accepted diagnoses per member
        """
        
        accepted_codes = set(mao004_response['accepted_codes'])
        submitted_set = set(submitted_codes)
        
        validation_results = {
            'member_id': member_id,
            'submitted_count': len(submitted_set),
            'accepted_count': len(accepted_codes),
            'rejected_codes': list(submitted_set - accepted_codes),
            'unexpected_accepts': list(accepted_codes - submitted_set),
            'reconciled': submitted_set == accepted_codes
        }
        
        # Log discrepancies
        if not validation_results['reconciled']:
            self._log_mao004_discrepancy(validation_results)
        
        return validation_results
    
    def validate_transfer_formula_inputs(self, state, plan_id, risk_pool_data):
        """
        Validate inputs to ACA risk adjustment transfer formula
        
        Inputs needed:
        - Plan risk score
        - Statewide average premium
        - Plan rating factors
        - Actuarial value
        - Enrollment by rating area
        """
        
        required_fields = [
            'plan_risk_score',
            'statewide_avg_premium',
            'plan_premium',
            'age_factor',
            'tobacco_factor',
            'actuarial_value',
            'enrollment'
        ]
        
        missing = [f for f in required_fields if f not in risk_pool_data]
        
        if missing:
            raise ValueError(f"Missing required fields: {missing}")
        
        # Validate ranges
        if not (0.5 <= risk_pool_data['age_factor'] <= 3.0):
            raise ValueError(f"Age factor out of range: {risk_pool_data['age_factor']}")
        
        if not (0 <= risk_pool_data['actuarial_value'] <= 1.0):
            raise ValueError(f"Actuarial value out of range: {risk_pool_data['actuarial_value']}")
        
        return True
    
    def _log_mao004_discrepancy(self, results):
        """Log discrepancies for investigation"""
        query = """
            INSERT INTO mao004_discrepancies
            (member_id, rejected_codes, unexpected_accepts, logged_at)
            VALUES (%s, %s, %s, NOW())
        """
        
        self.db.execute_query(query, (
            results['member_id'],
            json.dumps(results['rejected_codes']),
            json.dumps(results['unexpected_accepts'])
        ))
```

### 4.2 RADV Audit Preparation Service

**Purpose**: Maintain evidence for CMS Risk Adjustment Data Validation (RADV) audits

**Implementation**:

```python
class RADVAuditService:
    def __init__(self, db_connection, doc_storage):
        self.db = db_connection
        self.doc_storage = doc_storage  # S3, Azure Blob, etc.
    
    def link_diagnosis_to_source(self, member_id, icd10_code, 
                                source_document_id, claim_date,
                                npi_provider):
        """
        Create audit trail linking each HCC diagnosis to source documentation
        
        Required for RADV audit defense
        """
        
        query = """
            INSERT INTO diagnosis_documentation_links
            (member_id, icd10_code, source_document_id, claim_date, 
             npi_provider, linked_at, audit_ready)
            VALUES (%s, %s, %s, %s, %s, NOW(), TRUE)
        """
        
        self.db.execute_query(query, (
            member_id, icd10_code, source_document_id, 
            claim_date, npi_provider
        ))
    
    def validate_meat_criteria(self, member_id, diagnosis_code, 
                              clinical_note):
        """
        Validate MEAT criteria (Monitoring, Evaluating, Assessing, Treating)
        
        All submitted diagnoses must meet MEAT criteria or risk audit rejection
        """
        
        meat_criteria = {
            'monitoring': False,  # Patient being monitored for condition
            'evaluating': False,  # Provider evaluated for condition
            'assessing': False,   # Assessment/diagnosis documented
            'treating': False     # Treatment provided for condition
        }
        
        # NLP analysis of clinical note
        note_lower = clinical_note.lower()
        
        if any(word in note_lower for word in ['monitor', 'monitoring', 'monitored']):
            meat_criteria['monitoring'] = True
        
        if any(word in note_lower for word in ['evaluate', 'evaluation', 'assessed', 'assessment']):
            meat_criteria['evaluating'] = True
        
        if any(word in note_lower for word in ['diagnosis', 'diagnosed', 'condition']):
            meat_criteria['assessing'] = True
        
        if any(word in note_lower for word in ['treatment', 'treated', 'therapy', 'medication']):
            meat_criteria['treating'] = True
        
        meets_meat = sum(meat_criteria.values()) >= 3  # Need at least 3
        
        # Log MEAT validation
        query = """
            INSERT INTO meat_validation_log
            (member_id, diagnosis_code, monitoring, evaluating, assessing, 
             treating, meets_criteria, validated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        """
        
        self.db.execute_query(query, (
            member_id, diagnosis_code,
            meat_criteria['monitoring'],
            meat_criteria['evaluating'],
            meat_criteria['assessing'],
            meat_criteria['treating'],
            meets_meat
        ))
        
        return meets_meat
    
    def generate_radv_package(self, audit_year, sample_member_ids):
        """
        Generate complete documentation package for CMS RADV audit
        
        Includes:
        - Risk scores by model
        - HCC assignments with source codes
        - MEAT validation results
        - Documentation links
        - Provider records
        """
        
        package = {
            'audit_year': audit_year,
            'generated_at': datetime.now().isoformat(),
            'sample_count': len(sample_member_ids),
            'members': []
        }
        
        for member_id in sample_member_ids:
            # Retrieve all information
            risk_scores = self._get_member_risk_scores(member_id)
            hcc_assignments = self._get_member_hcc_assignments(member_id)
            documentation = self._get_member_documentation(member_id)
            
            package['members'].append({
                'member_id': member_id,
                'risk_scores': risk_scores,
                'hcc_assignments': hcc_assignments,
                'documentation_references': documentation
            })
        
        # Save to S3 for audit
        package_path = f"s3://radv-audit/{audit_year}/{uuid.uuid4()}.json"
        self.doc_storage.save(package_path, json.dumps(package))
        
        return package_path
```

---

## 5. Deployment & DevOps

### 5.1 Container Strategy

**Dockerfile for Risk Calculator Microservice**:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ .

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')"

# Expose port
EXPOSE 8000

# Run application
CMD ["gunicorn", "--workers=4", "--bind=0.0.0.0:8000", "app:app"]
```

**Kubernetes Deployment**:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hhs-hcc-calculator
  labels:
    app: risk-adjustment
    component: calculator
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: risk-adjustment
      component: calculator
  template:
    metadata:
      labels:
        app: risk-adjustment
        component: calculator
    spec:
      containers:
      - name: hhs-hcc-calculator
        image: registry.mycompany.com/risk-adjustment/hhs-hcc-calculator:v1.2.3
        imagePullPolicy: IfNotPresent
        ports:
        - containerPort: 8000
          name: http
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: url
        - name: HCC_COEFFICIENTS_VERSION
          value: "127"
        resources:
          requests:
            memory: "2Gi"
            cpu: "1000m"
          limits:
            memory: "4Gi"
            cpu: "2000m"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 40
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /ready
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 5
        volumeMounts:
        - name: hcc-mappings
          mountPath: /app/data/mappings
      volumes:
      - name: hcc-mappings
        configMap:
          name: hcc-mappings-v127
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: hhs-hcc-calculator-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: hhs-hcc-calculator
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

### 5.2 Monitoring & Observability

**Prometheus Metrics**:

```python
from prometheus_client import Counter, Histogram, Gauge

# Score calculation metrics
risk_scores_calculated = Counter(
    'risk_scores_calculated_total',
    'Total risk scores calculated',
    ['model', 'version', 'status']
)

score_calculation_duration = Histogram(
    'score_calculation_seconds',
    'Time to calculate risk score',
    ['model'],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0)
)

hcc_assignments_per_member = Histogram(
    'hcc_assignments_per_member',
    'Number of HCCs assigned per member',
    ['model'],
    buckets=(0, 3, 5, 10, 15, 20)
)

# Code validation metrics
invalid_codes_detected = Counter(
    'invalid_codes_detected_total',
    'Invalid diagnosis codes detected',
    ['code_type', 'model']
)

# Data quality metrics
mao004_discrepancies = Gauge(
    'mao004_discrepancies_current',
    'Current MAO-004 discrepancies requiring investigation'
)

# Payment metrics
transfer_amounts_by_plan = Gauge(
    'aca_transfer_amount_dollars',
    'ACA risk adjustment transfer amount',
    ['state', 'plan_id', 'direction']
)
```

**Alert Rules**:

```yaml
groups:
- name: risk_adjustment
  rules:
  - alert: HighRejectionRate
    expr: |
      (
        increase(risk_scores_calculated_total{status="rejected"}[5m]) /
        increase(risk_scores_calculated_total[5m])
      ) > 0.05
    for: 10m
    annotations:
      summary: "High risk score rejection rate"
      description: "More than 5% of risk scores rejected in last 5 minutes"
  
  - alert: MAO004Discrepancies
    expr: mao004_discrepancies_current > 100
    for: 1h
    annotations:
      summary: "Unresolved MAO-004 discrepancies"
      description: "{{ $value }} members with rejected diagnoses"
  
  - alert: SlowScoreCalculation
    expr: |
      histogram_quantile(0.95, 
        rate(score_calculation_seconds_bucket[5m])) > 2.0
    for: 5m
    annotations:
      summary: "Slow risk score calculation"
      description: "P95 calculation time > 2 seconds"
```

---

## 6. Configuration Management

### 6.1 Model Configuration Versioning

**YAML Configuration for Model Versions**:

```yaml
# models/cms_hcc_v28_config.yaml

model:
  name: CMS_HCC
  version: V28
  effective_date: 2024-01-01
  description: "CMS HCC Model Version 28"
  
hcc_categories:
  total_count: 115
  hierarchies_enabled: true
  constraining_enabled: true
  
code_mappings:
  icd10_count: 7770
  source: "CMS 2024 Advance Notice"
  mapping_file: "v28_icd10_hcc_mapping.csv"
  last_updated: 2024-01-01
  
coefficients:
  demographic_stratification:
    - age_0_34_male
    - age_0_34_female
    - age_35_49_male
    - age_35_49_female
    - age_50_64_male
    - age_50_64_female
    - age_65_69_male
    - age_65_69_female
    - age_70_74_male
    - age_70_74_female
    - age_75_79_male
    - age_75_79_female
    - age_80_plus_male
    - age_80_plus_female
  coefficient_file: "v28_hcc_coefficients.csv"
  
special_populations:
  esrd:
    exclude_hccs: [136, 137, 138]
    alternate_coefficients: true
  institutional:
    applies_to: ['LTI']
    frailty_adjustment: true
  
constraints:
  - group_id: "diabetes_complications"
    member_hccs: [37, 38, 39]
    rule: "keep_highest_coefficient"
  
  - group_id: "psychiatric"
    member_hccs: [57, 58, 59, 60]
    rule: "keep_parent_only"

transitions:
  from_version: V24
  blend_schedule:
    2024: {V28: 0.33, V24: 0.67}
    2025: {V28: 0.67, V24: 0.33}
    2026: {V28: 1.0, V24: 0.0}
  encounter_data_requirement: 2029
```

**Python Configuration Loader**:

```python
import yaml
from dataclasses import dataclass
from typing import Dict

@dataclass
class ModelConfig:
    name: str
    version: str
    effective_date: str
    hcc_categories: int
    hierarchies_enabled: bool
    constraining_enabled: bool
    esrd_exclusions: list
    
class ModelConfigLoader:
    def __init__(self, config_dir='/app/config/models'):
        self.config_dir = config_dir
        self.configs = {}
    
    def load_config(self, model_name, model_version):
        config_file = f"{self.config_dir}/{model_name}_{model_version}.yaml"
        
        with open(config_file, 'r') as f:
            raw_config = yaml.safe_load(f)
        
        config = ModelConfig(
            name=raw_config['model']['name'],
            version=raw_config['model']['version'],
            effective_date=raw_config['model']['effective_date'],
            hcc_categories=raw_config['hcc_categories']['total_count'],
            hierarchies_enabled=raw_config['hcc_categories']['hierarchies_enabled'],
            constraining_enabled=raw_config['hcc_categories']['constraining_enabled'],
            esrd_exclusions=raw_config['special_populations']['esrd']['exclude_hccs']
        )
        
        self.configs[f"{model_name}_{model_version}"] = config
        return config
```

---

## 7. Testing Strategy

### 7.1 Unit Tests for Risk Calculators

```python
import pytest
from risk_calculators import HHSHCCCalculator

class TestHHSHCCCalculator:
    
    @pytest.fixture
    def calculator(self):
        return HHSHCCCalculator()
    
    def test_basic_hcc_assignment(self, calculator):
        """Test that valid diagnosis codes map to HCC"""
        codes = ['E11.9']  # Type 2 diabetes
        result = calculator.calculate_score(
            member_id='TEST001',
            diagnosis_codes=codes,
            rx_codes=[],
            demographics={'age': 60, 'sex': 'M'}
        )
        
        assert len(result['hcc_list']) > 0
        assert result['raw_risk_score'] > 0
    
    def test_hierarchy_application(self, calculator):
        """Test that parent HCC removed when child present"""
        # Parent and child HCCs
        codes = ['E11.9', 'E11.21']  # Diabetes and diabetic neuropathy
        result = calculator.calculate_score(
            member_id='TEST002',
            diagnosis_codes=codes,
            rx_codes=[],
            demographics={'age': 60, 'sex': 'M'}
        )
        
        # Child HCC should be present, parent should be removed
        assert len(result['hcc_list']) == 1
    
    def test_invalid_code_rejection(self, calculator):
        """Test that invalid codes are rejected"""
        codes = ['Z99Z']  # Invalid code
        result = calculator.calculate_score(
            member_id='TEST003',
            diagnosis_codes=codes,
            rx_codes=[],
            demographics={'age': 60, 'sex': 'M'}
        )
        
        assert 'Z99Z' not in result.get('hcc_rationale', {})
    
    def test_pregnancy_multiplier(self, calculator):
        """Test pregnancy code handling"""
        pregnancy_codes = ['O09.892']  # Supervision of high risk pregnancy
        result = calculator.calculate_score(
            member_id='TEST004',
            diagnosis_codes=pregnancy_codes,
            rx_codes=[],
            demographics={'age': 30, 'sex': 'F'}
        )
        
        # Risk score should include pregnancy multiplier
        assert result['raw_risk_score'] > 0
    
    @pytest.mark.parametrize("age,sex,expected_factor", [
        (25, 'M', 1.0),
        (65, 'M', 2.5),
        (75, 'F', 3.0),
    ])
    def test_demographic_factors(self, calculator, age, sex, expected_factor):
        """Test demographic risk adjustment factors"""
        result = calculator.calculate_score(
            member_id='TEST005',
            diagnosis_codes=[],
            rx_codes=[],
            demographics={'age': age, 'sex': sex}
        )
        
        assert abs(result['raw_risk_score'] - expected_factor) < 0.1
```

### 7.2 Integration Tests

```python
def test_end_to_end_risk_adjustment_pipeline():
    """Test complete pipeline from claims to risk scores"""
    
    # Load test claims
    test_claims = load_test_fixture('test_claims.json')
    
    # Run pipeline
    scores = execute_pipeline(test_claims)
    
    # Validate output
    assert len(scores) == len(test_claims)
    assert all('raw_risk_score' in score for score in scores)
    assert all('hcc_list' in score for score in scores)
    assert all(score['raw_risk_score'] > 0 for score in scores)
    
    # Validate against expected
    expected = load_test_fixture('expected_scores.json')
    for actual, exp in zip(scores, expected):
        assert actual['member_id'] == exp['member_id']
        # Allow small differences due to floating point
        assert abs(actual['raw_risk_score'] - exp['raw_risk_score']) < 0.01

def test_mao004_reconciliation():
    """Test EDGE/MAO-004 validation"""
    
    submitted_codes = ['E11.9', 'I10', 'J45.902']
    mao004_codes = ['E11.9', 'I10']  # Third code rejected
    
    validator = EDGEComplianceValidator(db_connection)
    results = validator.validate_submitted_diagnoses(
        member_id='TEST001',
        submitted_codes=submitted_codes,
        mao004_response={'accepted_codes': mao004_codes}
    )
    
    assert not results['reconciled']
    assert 'J45.902' in results['rejected_codes']
```

---

## 8. Technology Stack Summary

| Component | Recommended | Alternatives |
|-----------|-------------|--------------|
| **Orchestration** | Apache Airflow | Temporal, Prefect, Dagster |
| **Data Processing** | Apache Spark | Flink, Dask, native Python |
| **Relational DB** | PostgreSQL | MySQL, SQL Server |
| **Time-Series DB** | TimescaleDB | InfluxDB, Prometheus |
| **Cache** | Redis | Memcached |
| **Message Queue** | Apache Kafka | RabbitMQ, AWS SQS |
| **Container Orchestration** | Kubernetes | Docker Swarm, ECS |
| **Language** | Python | Java, Go, Rust |
| **Web Framework** | FastAPI | Flask, Django |
| **Monitoring** | Prometheus + Grafana | Datadog, New Relic |
| **Logging** | ELK Stack | Splunk, CloudWatch |
| **Data Warehouse** | Snowflake | BigQuery, Redshift |

---

## 9. Conclusion

A production-grade SaaS platform for multi-model risk adjustment requires:

1. **Modular microservices** architecture supporting parallel score calculation
2. **Versioned code mappings** maintained in database with audit trails
3. **Multi-tenant data isolation** with shared infrastructure efficiency
4. **Comprehensive compliance** infrastructure (EDGE, RADV, MEAT validation)
5. **Robust monitoring** with alerting on quality/compliance metrics
6. **Flexible configuration** for model updates and state variations
7. **Strong testing** strategy covering unit, integration, and compliance scenarios

The architecture must balance **performance** (score millions of members daily), **accuracy** (98%+ coding validation), **compliance** (auditable and defensible), and **cost** (efficient resource utilization).

