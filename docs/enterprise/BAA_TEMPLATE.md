# Business Associate Agreement (Template)

**Status:** Template only. Final terms negotiated per customer with legal counsel.
**Last reviewed:** 2026-05-18

---

This Business Associate Agreement ("**BAA**") is entered into between **[CUSTOMER LEGAL NAME]** ("**Covered Entity**" or "**CE**") and **RAF Intelligence, Inc.** ("**Business Associate**" or "**BA**"), effective on the date of last signature below ("**Effective Date**").

## 1. Background

Covered Entity and Business Associate have entered into a master services agreement (the "**Underlying Agreement**") pursuant to which Business Associate provides software and services that may involve the use or disclosure of Protected Health Information ("**PHI**"). This BAA sets forth the terms required by the Health Insurance Portability and Accountability Act of 1996, as amended ("**HIPAA**"), including the Privacy, Security, and Breach Notification Rules at 45 C.F.R. Parts 160 and 164.

## 2. Definitions

Capitalized terms not otherwise defined have the meanings given in 45 C.F.R. §§ 160.103, 164.103, 164.304, 164.402, 164.501, and 164.504, as amended.

## 3. Permitted uses and disclosures by BA

3.1 BA may use or disclose PHI only as necessary to perform services described in the Underlying Agreement, as required by law, or for proper management and administration of BA.

3.2 BA may use PHI for **data aggregation services** as defined in 45 C.F.R. § 164.501, including:
  - **Clinical decision support** (HCC suspect mining via the Gemini Suspect Miner model, documented in `MODEL_CARD_GEMINI_SUSPECT_MINER.md`).
  - **De-identified analytics** in accordance with 45 C.F.R. § 164.514(b) safe-harbor de-identification.
  - **Quality measurement** (HEDIS / Star Ratings / Health Equity Index calculations).

3.3 BA shall not use or disclose PHI for marketing, sale, or fundraising without specific written authorization from the CE.

## 4. Safeguards

BA agrees to:

4.1 **Administrative**: maintain a written information security program reasonably designed to comply with 45 C.F.R. § 164.308.

4.2 **Physical**: maintain physical safeguards at all facilities where PHI is processed.

4.3 **Technical**: implement technical safeguards that include, at minimum:
  - **Encryption in transit** (TLS 1.2+).
  - **Encryption at rest** (AES-256; customer-managed keys available per `SINGLE_TENANT_DEPLOY.md`).
  - **Access controls** with role-based authorization and audit logging.
  - **Hash-chained immutable audit log** of PHI access events (see `backend/app/services/immutable_audit.py`).
  - **Boot-time integrity verification** of the audit chain.

4.4 BA shall, when CMS or other regulator requires, support a customer-managed encryption key (CMK / BYOK) deployment in which BA personnel cannot decrypt PHI at rest. See `SINGLE_TENANT_DEPLOY.md` §4.

## 5. Reporting

5.1 **Security incident**: BA shall report to CE any actual or attempted unauthorized access, use, disclosure, modification, or destruction of PHI **within 5 business days** of discovery.

5.2 **Breach of unsecured PHI**: BA shall report to CE **within 24 hours** of discovery and, in any case, no later than 60 days following discovery, providing:
  - Identification of each individual whose PHI has been (or is reasonably believed to have been) accessed, acquired, used, or disclosed.
  - Description of what occurred, when it occurred, and the nature of the PHI involved.
  - Remediation actions taken or planned.

5.3 BA shall mitigate, to the extent practicable, any harmful effect known to BA from any improper use or disclosure of PHI by BA.

## 6. Sub-processors

6.1 BA may use sub-processors to assist in performing services. The current sub-processor list is attached as **Exhibit A** (file: `SUBPROCESSORS.md`).

6.2 BA shall ensure each sub-processor is bound by written agreement containing terms no less stringent than those in this BAA, including direct BA-equivalent obligations.

6.3 BA shall provide CE with at least **30 days' prior written notice** before adding any new sub-processor. CE may object in writing within 30 days; if a material objection cannot be resolved, CE may terminate the Underlying Agreement without penalty.

## 7. Access, amendment, and accounting

7.1 BA shall, within 10 business days of CE's written request, make PHI available to enable CE to comply with 45 C.F.R. §§ 164.524 (access), 164.526 (amendment), and 164.528 (accounting of disclosures).

7.2 BA shall maintain a log of disclosures of PHI sufficient for CE to respond to accounting requests for the prior 6 years. The hash-chained audit log at `immutable_audit_log` satisfies this requirement.

## 8. Audit

8.1 BA shall make its internal practices, books, and records available to the Secretary of Health and Human Services for purposes of determining CE's compliance with HIPAA.

8.2 Upon CE's reasonable written request, BA shall provide:
  - Most recent SOC 2 Type II report.
  - Most recent HITRUST certification (when available).
  - Most recent third-party penetration test report.
  - Internal audit-control reports as agreed.

## 9. Termination

9.1 Either party may terminate this BAA upon **30 days' written notice** if the other party materially breaches and fails to cure within the notice period.

9.2 Upon termination, BA shall return or destroy all PHI in BA's possession. If return or destruction is not feasible, BA shall extend the protections of this BAA to such PHI and limit further use or disclosure. BA shall provide written certification of destruction or return within 30 days.

9.3 BA's obligations regarding hash-chained audit records survive termination for the legally required retention period (typically 6 years for HIPAA, longer where state law requires).

## 10. Indemnification

Each party indemnifies the other for losses arising from the indemnifying party's material breach of this BAA, subject to caps and exclusions in the Underlying Agreement.

## 11. Insurance

BA shall maintain commercially reasonable insurance:
- **Cyber liability**: minimum $5,000,000 aggregate.
- **Errors & omissions**: minimum $5,000,000 aggregate.
- **Commercial general liability**: minimum $2,000,000.

## 12. Compliance with state law

This BAA shall be construed consistently with HIPAA. To the extent state law is more stringent (e.g., California CMIA, Texas HB 300, New York SHIELD), the more stringent provision shall apply.

## 13. Conflict resolution

If any term of this BAA conflicts with the Underlying Agreement, the BAA controls with respect to PHI.

## 14. Governing law / forum

[STATE], without regard to its conflict-of-laws principles.

## 15. Counterparts

This BAA may be signed in counterparts, including electronically.

---

**Exhibit A**: Sub-processors list (`SUBPROCESSORS.md`).
**Exhibit B** *(optional)*: Customer-specific data residency requirements.

---

**Customer (CE)**

Name: ___________________________
Title: ___________________________
Date: ___________________________

**RAF Intelligence, Inc. (BA)**

Name: ___________________________
Title: ___________________________
Date: ___________________________

---

*This template is provided for reference only. Final BAA terms must be reviewed and customized by qualified legal counsel for each customer engagement.*
