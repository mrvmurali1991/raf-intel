# FedRAMP Moderate Roadmap

**Status:** Roadmap. RAF Intelligence is **not currently FedRAMP authorized**.
**Target authorization level:** FedRAMP Moderate (suitable for VA, DoD Medicare-equivalent, and CMS-adjacent workloads).
**Target authorization date:** late 2027 (assumes funded customer sponsor; 12–18 months from kickoff).

---

## 1. Why this matters

Government-adjacent Medicare and dual-eligible plans (VA Choice, Tricare, certain Medicare Special Needs Plans serving veterans) increasingly require FedRAMP-authorized SaaS. RAF Intelligence's commercial deployment is built on top of FedRAMP-authorized infrastructure (AWS) but is not itself authorized as a SaaS.

## 2. Path summary

| Phase | Duration | Key deliverables |
|---|---|---|
| **Phase 0 — Sponsor + readiness** | 1 mo | Federal sponsor agency, SSP scope, GovCloud commitment |
| **Phase 1 — Build to control catalog** | 4 mo | Implement 325 NIST 800-53 rev5 controls in product + ops |
| **Phase 2 — 3PAO assessment** | 2 mo | Hire 3PAO, execute Security Assessment Plan |
| **Phase 3 — JAB / ATO** | 6 mo | Submit package; address PMO/JAB comments; final ATO |
| **Phase 4 — Continuous monitoring** | ongoing | Monthly POA&M reporting, annual reassessment |

Realistic clock: **12–18 months** from funded kickoff to authorized.

---

## 3. Phase-1 control gaps (top 15)

These are the deltas between today's commercial posture and FedRAMP Moderate. Each links to the NIST 800-53 rev5 control family and the current implementation status.

| Control | Family | Current state | Gap |
|---|---|---|---|
| **AC-2 / AC-3** Account / access enforcement | Access Control | Multi-tenant RBAC + JWT | Add SCIM provisioning + JIT debranding; admin actions need separate approval workflow |
| **AC-17(2)** Remote-access cryptography | Access Control | TLS 1.2+ | Move to TLS 1.3-only + FIPS 140-3 validated cipher list |
| **AT-2** Awareness training | Training | Ad-hoc | Annual mandatory training + tracking system |
| **AU-2 / AU-12** Audit events / generation | Audit | Hash-chained immutable log, see `immutable_audit.py` | Add NIST audit event taxonomy mapping; ensure 100% of NIST-required events present |
| **AU-9(2)** Audit storage on separate system | Audit | S3 WORM hourly | Move to FedRAMP-authorized log aggregator (e.g. Splunk Cloud Gov, Sumo Logic FedRAMP) |
| **CM-7** Least functionality | Config Mgmt | Standard | Application allowlisting on containers; remove unused listeners |
| **CP-9 / CP-10** Backup + recovery | Contingency | See `DR_RUNBOOK.md` | Annual DR drill with documented evidence |
| **IA-2(1)** MFA for privileged users | Identification & Auth | Optional in `users.mfa_enabled` | **Mandatory** MFA for all users; PIV/CAC for federal users |
| **IA-5(1)** Authenticator management | Identification & Auth | bcrypt password hashes | Add FIPS-validated password policy + enforced rotation for federal users |
| **IR-4** Incident response | Incident Response | See `DR_RUNBOOK.md` | Federal-incident notification workflow (US-CERT within 1h) |
| **MA-4** Non-local maintenance | Maintenance | n/a | Document break-glass admin access procedures |
| **PE-3** Physical access | Physical & Env | AWS GovCloud inherits | Inherit; document |
| **RA-5** Vulnerability scanning | Risk Assessment | Manual | Monthly authenticated scans (Tenable.io GovCloud); 30-day high-vuln SLA |
| **SC-7** Boundary protection | Sys & Comm | ALB + WAF | Add stateful inspection (e.g. AWS Network Firewall) at VPC boundary |
| **SC-13** Cryptographic protection | Sys & Comm | TLS + AES-256 at rest | **All** crypto via FIPS 140-3 validated module (AWS KMS in FIPS mode); audit all `cryptography` lib usages |

## 4. Infrastructure requirements

### 4.1 AWS GovCloud (US)

Move the FedRAMP deployment to AWS GovCloud (US-East / US-West). Maintain commercial deployment for non-federal customers; the two are operationally separate accounts with no cross-region replication.

```
AWS GovCloud Org
├── raf-fedramp-prod (account)
│   ├── VPC, RDS, S3, KMS-in-FIPS-mode
│   └── ECS Fargate tasks (FIPS-validated Linux AMI)
├── raf-fedramp-staging (account)
└── raf-fedramp-shared-services (logging, monitoring)
```

### 4.2 Container hardening

- Base image: AWS-provided FIPS-compliant Linux (RHEL UBI 9 FIPS variant).
- All Python crypto via `cryptography.hazmat.bindings._rust._openssl.fips_enabled()` verified at boot.
- No outbound internet egress from compute tasks; only VPC endpoints + PrivateLink.

### 4.3 Logging + SIEM

- All app logs → AWS CloudWatch (GovCloud) → forward to FedRAMP-authorized SIEM.
- Audit chain (`immutable_audit_log`) replicates to Splunk Cloud Gov.

---

## 5. Personnel + policy gaps

| Requirement | Today | Needed |
|---|---|---|
| Background checks (NACI / T1) for engineers with prod access | n/a | T1 for all engineers; T3 (Secret) for incident response leads if DoD |
| Annual security training | informal | LMS-tracked, 4 modules, all engineers |
| Information system security officer (ISSO) | n/a | Hire or fractional ISSO with FedRAMP experience |
| Designated approving authority (DAA) | n/a | Federal sponsor agency role |
| Configuration management board | n/a | Quarterly CCB with sponsor representation |

---

## 6. Documentation deliverables

For 3PAO submission:

1. **System Security Plan (SSP)** — 300+ pages, all 325 controls described
2. **Information System Contingency Plan (ISCP)** — extends `DR_RUNBOOK.md`
3. **Incident Response Plan (IRP)** — with US-CERT notification flow
4. **Configuration Management Plan**
5. **Plan of Action and Milestones (POA&M)** — monthly updates
6. **Privacy Threshold Analysis (PTA)** + **Privacy Impact Assessment (PIA)** — for any PII/PHI
7. **E-Authentication Risk Assessment**
8. **Rules of Behavior** for all users with access

## 7. Cost estimate

| Line item | One-time | Annual |
|---|---|---|
| 3PAO assessment | $250–400k | $80–120k continuous monitoring |
| FedRAMP PMO fees | $0 (no fees) | $0 |
| ISSO (fractional) | $0 | $180–250k |
| AWS GovCloud premium | $0 | ~30% surcharge over commercial AWS |
| FIPS-validated tooling licenses | $0 | $50–80k (Tenable, Splunk Gov, etc.) |
| Internal staff time | 1.5 FTE × 18 mo | 0.5 FTE ongoing |

**Total funded estimate:** $1.0M to authorization + $400–600k/year continuous monitoring.

---

## 8. Status (current)

| Item | Status |
|---|---|
| Federal sponsor identified | ❌ Not started — looking for first VA / Medicare-adjacent customer |
| Phase 0 funded | ❌ |
| GovCloud accounts provisioned | ❌ |
| Control implementation | partial (commercial posture covers ~120 of 325) |
| 3PAO engaged | ❌ |
| ATO | ❌ |

## 9. Customers who can help unlock this

If you're a federal-adjacent Medicare plan reading this — talk to us. The first customer to sponsor RAF's FedRAMP authorization gets:
- Co-invested timeline (we share resourcing)
- Named-customer exclusivity in our marketing for the first 12 months post-ATO
- Discounted MSA pricing locked for the first 3 years

Email kriya@raf.health.
