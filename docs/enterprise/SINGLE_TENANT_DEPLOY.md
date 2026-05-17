# Single-Tenant Deployment Guide

Many Medicare Advantage plans (Humana, UnitedHealthcare regionals, Blues) require dedicated infrastructure for HCC risk-adjustment workloads. This document describes the single-tenant deployment topology and the differences from our multi-tenant SaaS default.

---

## 1. Single-tenant vs multi-tenant

| Dimension | Multi-tenant SaaS (default) | Single-tenant (this guide) |
|---|---|---|
| Database | One MySQL instance, `tenant_id` filter on every row | Dedicated MySQL per customer |
| Network | Shared OVH/AWS VPC | Dedicated VPC, VPN/PrivateLink |
| Encryption keys | Platform-managed | **Customer-managed (CMK/BYOK)** via AWS KMS or Azure Key Vault |
| FHIR auto-sync | Shared scheduler | Dedicated worker |
| Audit log | Dual-write (JSONL+DB+S3) | Same + per-tenant S3 bucket under customer's AWS account |
| Compliance certs | RAF's SOC 2 / HITRUST | RAF's certs + customer's own controls |
| Upgrade cadence | Continuous | Per-customer change window |

---

## 2. Target topology

```
Customer AWS Account (e.g. 123456789012)
├── VPC raf-prod (10.0.0.0/16)
│   ├── ALB → ECS Fargate × N
│   │   ├── raf-backend  (FastAPI, port 8500)
│   │   ├── celery-worker
│   │   └── celery-beat
│   ├── RDS MySQL 8.0 Multi-AZ (raf_intelligence)
│   ├── ElastiCache Redis (Celery broker)
│   ├── S3 raf-audit-customer (Object Lock COMPLIANCE)
│   ├── S3 raf-uploads-customer (chart-chase docs)
│   ├── KMS Customer-managed key (envelope encryption)
│   └── PrivateLink → OpenEMR / Epic (no public egress)
└── Route 53 raf-customer.example.com
```

---

## 3. Provisioning checklist

### 3.1 AWS infrastructure (Terraform)

We ship `infra/terraform/single-tenant/` (to be added in next release):

```bash
cd infra/terraform/single-tenant
terraform init
terraform plan -var customer_id=acme-health -var region=us-east-1
terraform apply
```

Outputs:
- VPC id
- DB endpoint
- KMS key ARN
- S3 bucket names
- IAM role ARNs for the backend task

### 3.2 Application config

Set environment variables on the ECS task:

```ini
APP_ENV=production
RAF_DB_HOST=<rds-endpoint>
RAF_DB_PORT=3306
RAF_DB_NAME=raf_intelligence
RAF_DB_USER=<from secrets manager>
RAF_DB_PASSWORD=<from secrets manager>
JWT_SECRET=<32+ random hex from KMS>
TENANT_ISOLATION=strict   # rejects any request without X-Active-Tenant
AUDIT_S3_BUCKET=raf-audit-acme-health
AUDIT_S3_PREFIX=audit/
AUDIT_S3_ROLE_ARN=arn:aws:iam::123:role/raf-audit-writer
AWS_KMS_KEY_ARN=arn:aws:kms:us-east-1:123:key/...
FHIR_TIMEOUT_SECONDS=5.0
GEMINI_API_KEY=<from secrets manager>
TWILIO_ACCOUNT_SID=<optional>
TWILIO_AUTH_TOKEN=<optional>
SENDGRID_API_KEY=<optional>
SENDGRID_WEBHOOK_KEY=<optional>
SENTRY_DSN=<optional>
```

### 3.3 Database initialization

```bash
# 1. Create the schema
docker run --rm -i mysql:8 mysql -h $RDS_ENDPOINT -u root -p$PASS < /sql/init/00_schema.sql

# 2. Run migrations
docker run --rm \
  -e RAF_DB_HOST=$RDS_ENDPOINT \
  -e RAF_DB_USER=root \
  -e RAF_DB_PASSWORD=$PASS \
  -e RAF_DB_NAME=raf_intelligence \
  -e JWT_SECRET=$JWT \
  raf-intelligence:latest \
  alembic upgrade head

# 3. Seed knowledge graph + HCC tables
docker run --rm raf-intelligence:latest python scripts/seed_knowledge_graph.py
```

### 3.4 First-tenant bootstrap

```bash
# Create admin user
curl -X POST https://raf-customer.example.com/api/auth/bootstrap-admin \
  -H "X-Bootstrap-Token: <one-time token from terraform output>" \
  -d '{"email":"admin@customer.example.com","password":"<temp>","full_name":"Customer Admin"}'
```

The bootstrap endpoint is **disabled after first use** (`config.BOOTSTRAP_ALLOWED` flips to false).

### 3.5 EHR connection

Per-tenant config in `fhir_connections` table (admin UI at `/admin/emr-config`):
- Base URL
- OAuth2 client_id + secret (encrypted with customer's KMS key)
- Token endpoint
- Scopes

---

## 4. CMK / BYOK details

Sensitive fields encrypted with customer's AWS KMS key:
- `fhir_connections.client_secret`
- `users.mfa_secret`
- `tenant_branding.api_keys` (when used)
- `outreach_consents.consent_method` (when method=='paper_form' includes signature)
- All values in `secrets` table

Implementation: `backend/app/services/encryption_service.py` — set `AWS_KMS_KEY_ARN` env var; the service auto-detects and uses AWS SDK's `encrypt`/`decrypt` (lazy-imported boto3). Falls back to local Fernet only when KMS env vars are unset (dev/staging).

Customer key rotation: trigger via `POST /api/admin/encryption/rotate-key` (admin-only). This re-encrypts all CMK-protected rows in batches with audit logging.

---

## 5. Networking

### 5.1 Inbound

- ALB on TCP 443 only. TLS 1.2+ (1.3 preferred), HSTS with 2-year max-age + includeSubDomains.
- ACM certificate from AWS Certificate Manager.
- WAF rules: AWS Managed Rules Common, OWASP Top 10, rate limit 1000 req/5 min per IP.

### 5.2 Outbound

- VPC endpoints for: S3, KMS, Secrets Manager, RDS, ECR.
- **PrivateLink** for EHR if customer's EHR is on AWS (Epic on AWS, OpenEMR cloud).
- Outbound NAT only for Gemini, Twilio, SendGrid. Per-destination security group.

### 5.3 No public access to DB / Redis / S3

- RDS: in private subnets, no public IP, security group allows only the backend task.
- Redis: same.
- S3: bucket policies deny `aws:SecureTransport=false`, `aws:PrincipalOrgID != customer's`.

---

## 6. Compliance differences

| Control | Multi-tenant SaaS | Single-tenant |
|---|---|---|
| SOC 2 Type II | RAF's report | RAF's report + customer's CSP report (e.g. AWS SOC 2) |
| HITRUST | RAF's e1 / r2 | Inherit + customer's controls |
| BAA | RAF as BA | RAF as BA + customer's KMS / S3 are customer's own controls (RAF never decrypts CMK-protected data outside the customer's VPC) |
| FedRAMP | Out of scope | Possible on AWS GovCloud — see FedRAMP roadmap doc |

---

## 7. Operational responsibilities

| Task | RAF | Customer |
|---|---|---|
| Application code + container images | ✅ | |
| Bug fixes + security patches (apply within 30 days of release) | ✅ | |
| Database backups (config) | ✅ | |
| Database backups (storage cost + retention policy) | | ✅ |
| KMS key rotation | | ✅ |
| Network ACLs / security groups | shared | shared |
| Compliance evidence collection (SOC 2 logs, etc.) | ✅ for RAF controls | ✅ for customer controls |
| 24/7 incident response | ✅ (SEV-1) | optional escalation |
| EHR credential management | | ✅ |

---

## 8. Onboarding timeline

| Day | Milestone |
|---|---|
| 1 | Kickoff, share Terraform module + this doc |
| 5 | Customer's infra team provisions VPC + RDS + S3 + KMS |
| 7 | RAF deploys backend image to customer's ECS |
| 10 | Smoke tests + DR drill |
| 14 | First-user onboarding (admin + 5 coders) |
| 30 | Production go-live with SLA |

---

## 9. References

- `/Users/murali/Desktop/raf-intelligence/backend/app/services/encryption_service.py` — KMS integration
- `/Users/murali/Desktop/raf-intelligence/backend/app/services/immutable_audit.py` — `archive_audit_jsonl_to_s3()`
- `/Users/murali/Desktop/raf-intelligence/docs/enterprise/DR_RUNBOOK.md` — disaster recovery
- `/Users/murali/Desktop/raf-intelligence/docs/enterprise/SUBPROCESSORS.md` — third-party processor list (for BAA)
