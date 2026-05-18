# Enterprise Documentation

This folder contains the documentation enterprise customers (Medicare Advantage plans, IDNs, ACOs) typically request during procurement and security review.

| Document | Purpose | Audience |
|---|---|---|
| [`DR_RUNBOOK.md`](./DR_RUNBOOK.md) | Disaster recovery runbook with RTO/RPO targets | SRE, security review, BAA addendum |
| [`MODEL_CARD_GEMINI_SUSPECT_MINER.md`](./MODEL_CARD_GEMINI_SUSPECT_MINER.md) | AI safety + bias disclosure for the NLP suspect miner | Compliance, clinical safety, customer CTO |
| [`SINGLE_TENANT_DEPLOY.md`](./SINGLE_TENANT_DEPLOY.md) | Dedicated-infrastructure deployment topology | Customer infra teams, security review |
| [`SUBPROCESSORS.md`](./SUBPROCESSORS.md) | Third-party processors that touch PHI | BAA Exhibit A, customer privacy office |
| [`BAA_TEMPLATE.md`](./BAA_TEMPLATE.md) | Business Associate Agreement template | Legal, contract negotiation |
| [`FEDRAMP_ROADMAP.md`](./FEDRAMP_ROADMAP.md) | Path to FedRAMP Moderate authorization | Government / federal-adjacent customers |
| [`NIST_800_53_CONTROL_MATRIX.md`](./NIST_800_53_CONTROL_MATRIX.md) | 325-control implementation evidence catalog | FedRAMP / SOC 2 / HITRUST overlap |
| [`THREAT_MODEL.md`](./THREAT_MODEL.md) | STRIDE threat model per trust boundary | Security review, pen-test prep |
| [`SECURITY_SCAN_BASELINE.md`](./SECURITY_SCAN_BASELINE.md) | Bandit / pip-audit / Trivy findings + policy | Security review, customer questionnaires |
| [`PERF_BASELINE.md`](./PERF_BASELINE.md) | Locust P50/P95/P99 baseline at 50u | Customer SLO negotiation |
| [`SOC2_EVIDENCE_AUTOMATION.md`](./SOC2_EVIDENCE_AUTOMATION.md) | Daily SOC 2 evidence collection + admin API | Vanta / Drata / A-LIGN integration |
| [`OBSERVABILITY.md`](./OBSERVABILITY.md) | OpenTelemetry / tracing / metrics / alerts | SRE + customer ops |
| [`HEDIS_NCQA_VALIDATION.md`](./HEDIS_NCQA_VALIDATION.md) | Self-validation against NCQA spec | HEDIS measure trust |

## Certifications (status)

| Certification | Status | Target |
|---|---|---|
| SOC 2 Type II | in-progress (audit period H2 2026) | Q1 2027 report |
| HITRUST CSF e1 | in-progress | H1 2027 |
| HITRUST CSF r2 | not started | 2028 |
| HIPAA BAA | available | n/a — operationalized |
| NCQA HEDIS measure certification | not started — first 5 measures self-coded | 2027 |
| FedRAMP Moderate | not started — see roadmap | late 2027 (sponsored) |

## How to request

For SOC 2 / HITRUST / pen-test reports under NDA: email **security@raf.health**.
For BAA negotiation: email **legal@raf.health**.
For technical architecture deep-dives: email **kriya@raf.health**.
