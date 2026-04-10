# RAF Research Documentation Index

**Complete Technical Reference for Risk Adjustment Factor Calculation**  
**Last Updated**: April 1, 2026

---

## Overview

Four comprehensive documents have been created to serve as the complete technical reference for building a RAF (Risk Adjustment Factor) calculation SaaS product. These documents cover methodology, coefficients, system architecture, and implementation guidance.

---

## Document 1: RESEARCH_COMPLETE_RAF_COMPREHENSIVE_GUIDE.md

**Length**: ~15,000 words  
**Purpose**: Master summary document covering all RAF calculation aspects  
**Best For**: Executive briefing, quick reference, high-level understanding

### Contents:
- Core RAF formula and component breakdown
- Model versions (V24, V28, V22) and transition timeline
- Patient vs. encounter vs. year-level calculations
- Program-specific models (MA, ACA, PACE, ESRD)
- Normalization factors
- New vs. continuing enrollee models
- Community vs. institutional models
- HCC coefficients with specific examples
- Disease interactions matrix
- HCC hierarchy rules
- Worked calculation example (step-by-step)
- Data quality and validation requirements
- Implementation checklist
- Key numbers and benchmarks
- Common errors and solutions
- Regulatory and compliance notes

### Key Takeaways:
- RAF = Demographic + HCCs + Interactions + HCC Count Modifier
- V28 has 115 HCCs (vs. 86 in V24), 7,770 ICD-10 codes
- PY2024-2025 uses V24/V28 blend; PY2026+ is 100% V28
- Normalization factors ~1.03-1.05 (adjust raw RAF)
- New enrollees get demographics only; no HCC credit

---

## Document 2: RAF_Calculation_Deep_Dive.md

**Length**: ~25,000 words  
**Purpose**: Comprehensive methodology and technical specifications  
**Best For**: Technical implementation, regulatory reference, product documentation

### Major Sections:
1. Core RAF Calculation Formula (with examples)
2. CMS-HCC Model Versions (V24, V28, V22, ESRD specifications)
3. Demographic Factors (age-sex, Medicaid, disability, institution)
4. HCC Coefficients and Disease Interactions (with coefficient tables)
5. Patient vs Encounter vs Year-Level Calculations (with rules)
6. Program-Specific Models (MA, ACA, PACE, ESRD with detailed specs)
7. Normalization Factors (definition, purpose, calculation methodology)
8. New vs Continuing Enrollee Models (definitions and differences)
9. Community vs Institutional Models (settings and adjustments)
10. V24 to V28 Transition Timeline (2024-2026 with blend percentages)
11. Key Regulatory and Compliance Notes

### Key Details:
- Complete demographic coefficient tables (age-sex bands, adjustments)
- HCC organization by disease group (cancer, diabetes, cardiac, etc.)
- Disease interaction terms with examples
- ESRD-specific model rules (zero-weighting kidney disease HCCs)
- PACE slower transition timeline (to 2029)
- ACA marketplace using HHS-HCC model (not CMS-HCC)
- Specific V28 changes vs V24

### Use This For:
- Building functional specifications
- Understanding regulatory requirements
- Writing product documentation
- Training staff on RAF concepts
- Compliance validation

---

## Document 3: RAF_Technical_Reference_Coefficients.md

**Length**: ~20,000 words  
**Purpose**: Detailed coefficient tables and worked calculation examples  
**Best For**: Algorithm implementation, testing, validation, training

### Sections:
1. Demographic Coefficient Tables
   - Age-sex matrices for aged and disabled beneficiaries
   - Medicaid dual eligible adjustments
   - Institutional multipliers

2. HCC Coefficient Examples (V24 vs V28)
   - High-risk conditions (cancer, heart failure)
   - Cardiovascular HCCs
   - Diabetes HCCs (constrained in V28)
   - Kidney disease HCCs (reorganized in V28)
   - Neurological HCCs

3. Disease Interaction Coefficients
   - Known interactions with estimated values
   - Interactions removed in V28

4. HCC Count Modifier Coefficients
   - 5-10+ HCC bonus structure

5. Normalization Factor Examples
   - Year-by-year values
   - Impact calculations

6. Blend Calculation Examples
   - V24/V28 blend for PY2024
   - V24/V28 blend for PY2025

7. Program-Specific Calculation Examples
   - Medicare Advantage (standard patient)
   - ESRD dialysis patient
   - PACE program calculation
   - New enrollee (zero HCC credits)

8. Validation Checklist
   - Data validation rules
   - Calculation validation rules
   - Program-specific validation

9. Common Calculation Errors
   - 10 detailed error scenarios with solutions

### Use This For:
- Building lookup tables
- Unit testing calculations
- Validating implementation
- Training engineers
- Creating test cases
- Example-based verification

---

## Document 4: SaaS_Implementation_Architecture.md

**Length**: ~20,000 words  
**Purpose**: System design and technical architecture  
**Best For**: Engineering, architecture, database design, integration planning

### Major Sections:
1. Data Model Overview
   - Entity relationship diagrams
   - 6 detailed SQL table schemas:
     - `patients` - Core patient data
     - `enrollments` - Plan enrollment details
     - `diagnoses` - ICD-10 codes with HCC mappings
     - `patient_demographics` - Demographic coefficients
     - `hcc_coefficients` - Reference coefficient tables
     - `disease_interactions` - Interaction term definitions
     - `hcc_count_modifiers` - Count modifier table
     - `normalization_factors` - Year/program normalization
     - `raf_calculations` - Results/output storage

2. Calculation Flow Architecture
   - High-level processing flow diagram
   - Detailed Python pseudocode algorithm
   - Step-by-step calculation sequence

3. Integration Points
   - Claims data ingestion (daily/weekly)
   - EHR/clinical data integration
   - Manual chart review workflow
   - Payment system output

4. Technology Stack Recommendations
   - Database: PostgreSQL + TimescaleDB
   - Language: Python (pandas/numpy) or Rust
   - API: FastAPI or gRPC
   - Cache: Redis
   - Queue: Kafka or RabbitMQ
   - Workflows: Airflow or Dagster
   - Data warehouse: Snowflake or BigQuery

5. Data Refresh Strategy
   - Monthly cycle schedule
   - Annual update requirements
   - Historical version tracking

6. Quality Assurance & Validation
   - 5+ detailed test cases with assertions
   - New enrollee verification
   - Hierarchy rule compliance
   - Disease interaction testing
   - Blend calculation validation
   - ESRD zero-weighting

7. Security & Compliance
   - HIPAA encryption requirements
   - Audit logging specifications
   - Role-based access control
   - Data retention policies
   - Backup and recovery

8. Performance Optimization
   - Database indexing strategy
   - Caching layers (L1, L2, L3)
   - Lookup time benchmarks
   - Batch processing capacity

9. Deployment & Monitoring
   - CI/CD pipeline structure
   - Monitoring metrics (accuracy, latency, data quality)

### Use This For:
- Database schema design
- System architecture decisions
- Implementation planning
- Code structure and organization
- Integration point definition
- DevOps and deployment planning
- Performance tuning
- Testing strategy

---

## Quick Navigation Guide

### By Role

**Executive/Product Manager**:
1. Start: RESEARCH_COMPLETE_RAF_COMPREHENSIVE_GUIDE.md (Sections 1-5)
2. Reference: RAF_Key_Benchmarks_Summary.md
3. Deep dive: RAF_Calculation_Deep_Dive.md (Section 1)

**Engineer/Developer**:
1. Start: SaaS_Implementation_Architecture.md (Sections 1-4)
2. Reference: RAF_Technical_Reference_Coefficients.md (Sections 1-4)
3. Algorithm: SaaS_Implementation_Architecture.md (Section 2)

**Actuary/Compliance Officer**:
1. Start: RAF_Calculation_Deep_Dive.md (All sections)
2. Reference: RAF_Technical_Reference_Coefficients.md (Sections 2-4)
3. Audit: SaaS_Implementation_Architecture.md (Section 6)

**Data Analyst**:
1. Start: SaaS_Implementation_Architecture.md (Section 1)
2. Reference: RAF_Technical_Reference_Coefficients.md
3. Reporting: RAF_Calculation_Deep_Dive.md (Section 10)

### By Topic

**Understanding RAF Formula**:
- RESEARCH_COMPLETE_RAF_COMPREHENSIVE_GUIDE.md (Parts 1-4)
- RAF_Calculation_Deep_Dive.md (Sections 1-2)

**Coefficients and Values**:
- RAF_Technical_Reference_Coefficients.md (Sections 1-7)
- RESEARCH_COMPLETE_RAF_COMPREHENSIVE_GUIDE.md (Parts 8-9)

**Model Versions and Transitions**:
- RAF_Calculation_Deep_Dive.md (Section 2)
- RESEARCH_COMPLETE_RAF_COMPREHENSIVE_GUIDE.md (Part 2)
- RAF_Technical_Reference_Coefficients.md (Section 6)

**Different Programs (MA, PACE, ACA, ESRD)**:
- RAF_Calculation_Deep_Dive.md (Section 6)
- RESEARCH_COMPLETE_RAF_COMPREHENSIVE_GUIDE.md (Part 4)
- RAF_Technical_Reference_Coefficients.md (Section 7)

**Building the System**:
- SaaS_Implementation_Architecture.md (All sections)
- RAF_Technical_Reference_Coefficients.md (Sections 8-9)

**Testing and Validation**:
- SaaS_Implementation_Architecture.md (Section 6)
- RAF_Technical_Reference_Coefficients.md (Sections 8-9)
- RESEARCH_COMPLETE_RAF_COMPREHENSIVE_GUIDE.md (Parts 12-13)

---

## Key Statistics Summary

### Model Specifications
- V28: 115 HCCs, 7,770 ICD-10 codes (7% reduction in codes)
- V24: 86 HCCs, 9,797 ICD-10 codes
- V22 (PACE): 86 HCCs (2017 model, transitioning)
- HHS-HCC (ACA): 127 HCCs, 7,768 ICD-10 codes

### Financial Impact
- CMS projected V28 transition: -3.12% average RAF reduction
- Medicare savings from V28: ~$11 billion
- Per-patient RAF difference of 0.01: ~$120-200 annually
- Payment difference, new vs. continuing enrollee: 50-75%

### Transition Timeline
- PY2024: 67% V24 + 33% V28
- PY2025: 33% V24 + 67% V28
- PY2026+: 100% V28
- PACE: Different timeline (100% V28 by 2029)

### Normalization Factors
- 2024: 1.030
- 2025: 1.045
- 2026: ~1.050

---

## Implementation Effort Estimate

### Phase 1: Core Engine (3 months)
- Basic demographic calculation
- HCC mapping
- Hierarchy rules
- Simple summation
**Deliverable**: Single-patient V28 RAF calculation

### Phase 2: Advanced Features (3 months)
- Disease interactions
- HCC count modifiers
- Blend calculation
- Multiple program support
**Deliverable**: Accurate RAF for diverse populations

### Phase 3: Data Integration (3 months)
- Claims pipeline
- EHR integration
- Chart review workflow
- Diagnosis validation
**Deliverable**: Automated diagnosis ingestion

### Phase 4: Production (3 months)
- Reporting
- Audit trails
- Compliance features
- Performance optimization
**Deliverable**: Production-ready SaaS system

**Total**: ~12 months to full production deployment

---

## Source Documentation

All information is derived from:
- CMS official Advance Notices (2024-2026)
- CMS Rate Announcements
- CMS-HCC Model V28 Clinical Revision files
- MedPAC reports
- Insurance industry research
- Academic publications
- Regulatory guidance

See individual documents for complete source citations.

---

## Document Maintenance

**Update Schedule**:
- April annually: Update for new coefficient releases
- October annually: Update for ICD-10 code set changes
- Ad-hoc: When major regulatory changes announced

**Version Control**:
- Current: v1.0 (April 2026)
- All documents timestamped with last update date
- Historical versions archived

---

## Getting Started

1. **Quick Orientation** (30 minutes):
   - Read this index
   - Skim RESEARCH_COMPLETE_RAF_COMPREHENSIVE_GUIDE.md

2. **Detailed Learning** (4-6 hours):
   - Read RAF_Calculation_Deep_Dive.md
   - Study RAF_Technical_Reference_Coefficients.md examples

3. **Implementation Planning** (2-3 hours):
   - Review SaaS_Implementation_Architecture.md
   - Identify required systems and data

4. **Deep Technical Work** (ongoing):
   - Reference specific sections as needed
   - Build calculation engine
   - Validate against examples

---

## Questions and Support

For questions on:
- **RAF Formula**: See RAF_Calculation_Deep_Dive.md Sections 1-2
- **Coefficients**: See RAF_Technical_Reference_Coefficients.md Sections 2-4
- **Implementation**: See SaaS_Implementation_Architecture.md Sections 1-4
- **Validation**: See RAF_Technical_Reference_Coefficients.md Section 8
- **Compliance**: See RAF_Calculation_Deep_Dive.md Section 11

---

**Total Documentation Package**: ~80,000 words  
**Estimated Read Time**: 12-16 hours  
**Suitable For**: Complete SaaS product development  
**Current Through**: April 2026 (CMS 2024 Model announcements)

