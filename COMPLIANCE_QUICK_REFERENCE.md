# Healthcare RAF SaaS: Compliance Quick Reference

**Version:** 1.0 | **Last Updated:** April 2026 | **Quick Links:** Checklists | Cost Estimates | Timeline | Requirements

---

## HIPAA Technical Safeguards Quick Checklist

### Encryption
- [ ] **At Rest:** AES-256 enabled on all data (databases, backups, storage)
- [ ] **In Transit:** TLS 1.2+ enforced (HTTPS, database SSL, APIs)
- [ ] **Keys:** Stored in HSM or managed key service (AWS KMS, Azure Key Vault)
- [ ] **Rotation:** Annual key rotation enabled and documented
- [ ] **FIPS 140-2 Level 2:** Encryption verified compliant

### Access Controls (5-Factor)
1. **Authentication:** MFA for all accounts (except service accounts)
2. **Authorization:** RBAC implemented, least privilege enforced
3. **Audit Logging:** All access logged with user/timestamp/action
4. **Session Management:** Automatic logout after 15 minutes
5. **Password Policy:** Minimum 12 characters, 90-day rotation

### Audit Logging (Real-Time SIEM)
- [ ] Database access logged (all queries)
- [ ] API access logged (all endpoints)
- [ ] User authentication logged (successes/failures)
- [ ] Administrative actions logged (config changes)
- [ ] Logs immutable and tamper-proof
- [ ] Retention: Minimum 6 years
- [ ] Real-time alerts on suspicious activity

### Integrity Controls
- [ ] Hash verification for critical data
- [ ] Digital signatures on sensitive documents
- [ ] Audit trail for all modifications (version control)
- [ ] Database constraints enforce data validity

---

## Certification Timeline & Costs

### SOC 2 Type II
| Phase | Timeline | Cost |
|---|---|---|
| **Planning** | 1-2 months | $5K-15K |
| **Implementation** | 3-4 months | $20K-40K |
| **Observation** | 6-12 months | Included |
| **Audit** | 1-3 months | $10K-50K |
| **Total** | 12-18 months | **$30K-150K** |
| **Annual Maintenance** | Ongoing | **$10K-40K/year** |

### HITRUST CSF (r2 Assessment)
| Phase | Timeline | Cost |
|---|---|---|
| **Planning** | 1-2 months | $5K-20K |
| **Remediation** | 2-6 months | $20K-50K |
| **Assessment** | 2-4 months | $30K-70K |
| **Validation** | 1-2 months | $10K-30K |
| **Total** | 12-15 months | **$70K-170K** |
| **Annual Maintenance** | Ongoing | **$40K-250K/year** |

### Penetration Testing
| Type | Cost | Frequency |
|---|---|---|
| **Initial Assessment** | $10K-30K | Before launch |
| **Full Application Test** | $20K-50K | Annual |
| **Cloud Infrastructure** | $10K-25K | Annual |
| **Re-testing (Fixes)** | $5K-15K | After remediation |
| **Total Year 1** | **$20K-50K** | |

---

## HIPAA BAA Requirements (Upstream & Downstream)

### Upstream BAAs (You → Customers)
Essential elements:
1. Permitted uses/disclosures of PHI
2. Safeguarding requirements (technical, administrative, physical)
3. Breach notification procedures
4. Subcontractor obligations (your vendors)
5. Individual access/amendment rights
6. Audit and inspection rights
7. Contract termination provisions
8. Return/destruction of PHI

**Documentation:**
- [ ] BAA template prepared
- [ ] Legal review completed
- [ ] Signed with all customers processing PHI
- [ ] Updated annually
- [ ] Retention: 6 years minimum

### Downstream BAAs (You ← Vendors)
Vendors requiring BAAs:
- [ ] Cloud providers (AWS, Azure, GCP)
- [ ] Database hosts
- [ ] Email service providers (handling PHI)
- [ ] Backup/disaster recovery vendors
- [ ] SIEM/logging vendors
- [ ] Payment processors
- [ ] Any vendor with PHI access

**Verification:**
- [ ] BAA in place with all PHI-accessing vendors
- [ ] Vendor maintains HIPAA compliance
- [ ] Vendor subcontractors also have BAAs
- [ ] Quarterly vendor security assessments
- [ ] Right to audit vendors documented
- [ ] Incident notification procedures agreed

---

## Cloud Provider Comparison

### AWS Standard (Recommended for Most)
- [ ] 166+ HIPAA-eligible services
- [ ] BAA available (included in service)
- [ ] FedRAMP Authorization (some regions)
- [ ] Best ecosystem for healthcare
- [ ] Global regions available
- [ ] Cost: Standard pricing

**Key Services for Healthcare:**
- RDS (encrypted, automated backups)
- EC2 (compute, must config security)
- S3 (storage, enable encryption)
- KMS (key management)
- VPC (network isolation)

### AWS GovCloud (Federal/DoD Only)
- [ ] FedRAMP Authorization (highest level)
- [ ] Limited service selection (~80 services)
- [ ] Data confined to US government cloud
- [ ] 40-50% higher cost
- [ ] Best for: Federal agencies, VA, military healthcare

### Microsoft Azure (Enterprise Alternative)
- [ ] HIPAA BAA included in Online Services Terms
- [ ] 100+ HIPAA-eligible services
- [ ] Compliance Manager (built-in HIPAA templates)
- [ ] Health Data Services (FHIR, DICOM)
- [ ] Good for: Microsoft-centric enterprises

### Google Cloud (Limited Healthcare)
- [ ] Limited HIPAA-eligible services (~30)
- [ ] Healthcare API available
- [ ] BAA available (limited scope)
- [ ] Growing healthcare ecosystem
- [ ] Best for: Specific Google services

---

## Database Configuration (AWS RDS Example)

### Encryption Setup
```
At Rest:
  ✓ Enable KMS encryption (Customer Managed Key)
  ✓ Enable automatic backups (35+ days)
  ✓ Cross-region backup copies
  ✓ Backup encryption same as database

In Transit:
  ✓ Force SSL/TLS connections
  ✓ Use RDS CA certificate
  ✓ Require certificate validation
  ✓ Disable unencrypted connections
```

### Access Control
```
Network:
  ✓ Private subnet (no internet)
  ✓ Security group: inbound from app tier only
  ✓ Port restrictions (5432 for PostgreSQL, etc.)
  ✓ VPC Flow Logs enabled

Authentication:
  ✓ IAM database authentication enabled
  ✓ Master user password in Secrets Manager
  ✓ Application user roles created
  ✓ No hardcoded passwords in code
```

### Audit Logging
```
  ✓ Database Activity Streams enabled
  ✓ CloudTrail logging all API calls
  ✓ S3 access logging
  ✓ Application-level query logging
  ✓ CloudWatch Logs retention: 6+ years
  ✓ Real-time alerting on anomalies
```

---

## Multi-Tenancy Data Isolation

### Architecture Decision
Choose one:
- [ ] **Database-per-Tenant:** Highest isolation, highest cost
- [ ] **Schema-per-Tenant:** Good balance (recommended)
- [ ] **Shared Schema + RLS:** Lowest cost, requires robust app controls
- [ ] **Hybrid:** Mix tiers based on customer requirements

### Isolation Implementation
```
Database Level:
  ✓ Separate schema per tenant
  OR Row-Level Security (RLS) enforced
  ✓ Tenant_id in all queries

Application Level:
  ✓ Extract tenant_id from auth token
  ✓ Validate user belongs to tenant
  ✓ Include tenant_id in all DB queries
  ✓ Log access with tenant context
  ✓ Reject cross-tenant access attempts

API Level:
  ✓ Tenant_id required in URL/header
  ✓ Validate tenant context
  ✓ Prevent parameter tampering
  ✓ Monitor for isolation breaches

Testing:
  ✓ Attempt to access other tenant's data
  ✓ Verify queries cannot bypass tenant filter
  ✓ Penetration test isolation
  ✓ Load test with concurrent tenants
```

---

## Backup & Disaster Recovery (3-2-1 Rule)

### The 3-2-1 Strategy
```
3 Copies:
  1. Production database (live)
  2. Automated backup (daily snapshots)
  3. Off-site archive (Glacier)

2 Different Media:
  1. Hot storage (production, SSD)
  2. Warm storage (RDS backups)
  3. Cold storage (Glacier archive)

1 Off-Site:
  ✓ Cross-region backup copies
  ✓ Glacier archive in different region
  ✓ 7+ year retention
  ✓ Physically isolated from primary
```

### Configuration
```
Primary Database:
  ✓ Multi-AZ deployment (synchronous replication)
  ✓ Automated backups (35+ day retention)
  ✓ Encryption with KMS

Backup Snapshots:
  ✓ Daily snapshots (in addition to automated backups)
  ✓ Encrypted with same KMS key
  ✓ Copy to secondary region
  ✓ Copy to Glacier (7-year retention)

Disaster Recovery:
  ✓ RTO defined: <4 hours (restore service)
  ✓ RPO defined: <1 hour (acceptable data loss)
  ✓ Failover procedures documented
  ✓ Annual DR drill scheduled
  ✓ Failover time measured

Testing:
  ✓ Quarterly restoration testing
  ✓ Verify data integrity
  ✓ Test application functionality
  ✓ Document test results
  ✓ Annual full DR drill
```

---

## Incident Response & Breach Notification

### 4-Factor Breach Assessment (60-Day Deadline)
When unauthorized access occurs, determine if breach using:
1. **Nature of PHI:** What data was accessed? (names, SSN, medical records?)
2. **Who Accessed:** Employees, criminals, insider threat?
3. **What Was Actually Acquired:** Was PHI actually taken/viewed?
4. **Mitigation:** Encrypted data = lower risk; unencrypted = higher risk

**Decision Tree:**
```
Encrypted ePHI compromised + key not compromised
  → NOT A BREACH (low risk of re-identification)

Unencrypted names/SSN/medical records accessed
  → BREACH (high risk of harm)

Names/dates/medical records (no SSN/address)
  → ASSESS (medium risk) - often breached

Access but no evidence of acquisition
  → ASSESS (may not be breach)
```

### Notification Timeline
```
Discovery → Investigation (1-5 days) 
  ↓
Risk Assessment (3-10 days)
  ↓
Breach Determination (1-5 days)
  ↓
Notification Preparation (1-5 days)
  ↓
Individual Notification (Must be by Day 60)
  ↓
HHS Notification (if 500+, Day 60)
  ↓
Media Notification (if 500+ in state, Day 60)
```

### Documentation
- [ ] Incident discovery log
- [ ] Investigation report
- [ ] Four-factor assessment
- [ ] Breach determination
- [ ] Individual notification letters
- [ ] HHS submission (if applicable)
- [ ] Media notification (if applicable)
- [ ] Remediation plan
- [ ] Root cause analysis
- [ ] Retention: 6+ years

---

## PHI De-Identification Methods

### Safe Harbor (Simpler, Less Data Utility)
Remove all 18 identifiers:
1. Name | 2. Address | 3. City | 4. County
5. Zip Code (keep 3-digit if >20K people) | 6. Birth date
7. Discharge date | 8. Death date | 9. Dates of service
10. Phone | 11. Fax | 12. Email | 13. SSN
14. Medical record number | 15. Account number
16. Certificate/license | 17. Vehicle identifier
18. Device identifier | + Any other unique ID
+ Full-face photograph

**Verification:**
- [ ] All 18 identifiers removed
- [ ] No actual knowledge remaining data identifies person
- [ ] Checklist completed and retained
- [ ] Data limited to intended use

### Expert Determination (More Complex, Greater Data Utility)
Qualified statistical expert determines:
- Risk of re-identification is "very small"
- Using generalization, suppression, perturbation, date-shifting, binning
- Quantified using k-anonymity, l-diversity, or t-closeness
- Expert provides written determination

**Process:**
- [ ] Hire qualified expert (statistician/scientist with healthcare experience)
- [ ] Perform de-identification
- [ ] Expert assesses re-identification risk
- [ ] Expert documents methods and results
- [ ] Risk determined "very small"
- [ ] Expert report retained with data
- [ ] Data retained for minimum 6 years

**Cost:** $5K-25K (expert fees)

---

## Penetration Testing & Vulnerability Assessment

### Mandatory (Proposed Effective 2026)
- **Penetration Testing:** Annual (required by proposed HIPAA rule)
- **Vulnerability Scanning:** Every 6 months (required by proposed rule)

### Scope (What Gets Tested)
- [ ] Web application (all features)
- [ ] Mobile apps (iOS & Android)
- [ ] REST/SOAP APIs
- [ ] Authentication (login, MFA, password reset)
- [ ] Authorization (role-based access)
- [ ] Database systems
- [ ] Cloud infrastructure (AWS, Azure, etc.)
- [ ] Network perimeter
- [ ] VPN/remote access
- [ ] Multi-tenancy isolation
- [ ] Backup systems
- [ ] Disaster recovery systems
- [ ] Third-party integrations

### Remediation Timeline
| Severity | Timeline |
|---|---|
| Critical (RCE, auth bypass) | 48 hours |
| High (SQL injection, priv esc) | 2 weeks |
| Medium (XSS, info disclosure) | 30 days |
| Low (best practice) | 90 days |

### Cost & Frequency
- Initial: $20K-50K
- Annual retesting: $15K-40K
- Vendor selection: CEH/OSCP certified, healthcare experience

---

## State Privacy Laws (Multi-State Compliance)

### Compliance Strategy
All states except Idaho exempt regulated health information (HIPAA-regulated PHI).

**If You Process PHI:**
- HIPAA-regulated = usually exempt from state laws
- BUT: Monitor for healthcare-specific state laws
- AND: Apply strictest state requirement as baseline

### California (CCPA/CPRA) 2026 Changes
- [ ] Health data = "sensitive personal information" (opt-in for sale, not opt-out)
- [ ] Youth (<16) = enhanced protections
- [ ] Geolocation near healthcare facilities = prohibited (AB 45)
- [ ] Reproductive health data = special protections
- [ ] Consumer request deadline: 45 days
- [ ] Cybersecurity audit required (if threshold met)

### Other State Laws (22 States + DC)
Most exempt HIPAA-regulated health information, BUT:
- [ ] All states require breach notification
- [ ] California: 30 days (fastest)
- [ ] Most states: "Without unreasonable delay"
- [ ] Assume 30-day standard for all states

### Multi-State Checklist
- [ ] Privacy policy documents all state requirements
- [ ] Consumer request system handles access/delete/correct
- [ ] Breach notification procedures (30-day assumed)
- [ ] Opt-out mechanisms (for applicable states)
- [ ] Annual law review (new states, amendments)
- [ ] Customer communication (explain state compliance)

---

## Year 1 Cost Summary

| Category | Low | High | Notes |
|---|---|---|---|
| **Personnel** | $100K | $250K | Security officer + compliance |
| **Tools** | $50K | $100K | SIEM, HSM, VPN, monitoring |
| **SOC 2 Audit** | $30K | $50K | First engagement |
| **HITRUST Assessment** | $100K | $160K | Full r2 assessment |
| **Penetration Testing** | $20K | $50K | Initial + retest |
| **Consulting** | $30K | $80K | Implementation support |
| **Training** | $10K | $25K | Staff education |
| **Total** | **$340K** | **$715K** | |
| **Annual (Ongoing)** | **$150K** | **$300K** | Certifications, monitoring, testing |

---

## Monthly Compliance Checklist (Operations)

### Week 1
- [ ] Review security monitoring alerts
- [ ] Investigate failed authentication attempts (5+)
- [ ] Check for policy violations
- [ ] Audit log completeness

### Week 2
- [ ] Access audit (verify least privilege)
- [ ] Backup verification (test restoration)
- [ ] Patch status review (critical patches within 30 days)
- [ ] Third-party compliance check

### Week 3
- [ ] Security metrics reporting
- [ ] Incident log review (any incidents?)
- [ ] Vulnerability scan review
- [ ] Encryption key audit

### Week 4
- [ ] Monthly compliance reporting
- [ ] Training completion verification
- [ ] Risk assessment update (if needed)
- [ ] Compliance metrics dashboard

---

## Key Regulatory Contact Information

### HHS Office for Civil Rights (OCR)
- Breach reports: https://ocrportal.hhs.gov
- Complaints: https://www.hhs.gov/ocr/about-us/contact-us/index.html
- Emergency: HIPAA@hhs.gov

### State Privacy Enforcement
- California Attorney General: ag.ca.gov/privacy
- State-specific privacy agencies (varies)

---

## Red Flags for Non-Compliance

🚩 No encryption at rest or in transit
🚩 No access controls (everyone has admin)
🚩 No audit logging
🚩 No MFA enabled
🚩 No backup system
🚩 No incident response plan
🚩 No BAAs with customers/vendors
🚩 No penetration testing
🚩 No workforce training
🚩 No disaster recovery testing
🚩 No privacy policy
🚩 No breach notification procedures
🚩 No documentation retention
🚩 No vendor management
🚩 No physical security controls

**If any of these are true, compliance is at high risk.**

---

**Questions? Consult with:**
- Healthcare compliance attorney (for legal interpretation)
- Certified HIPAA compliance officer
- Qualified security assessor
- Big Four consulting firms
- Specialized healthcare security vendors

This guide is informational. Actual compliance requires professional assessment and implementation.
