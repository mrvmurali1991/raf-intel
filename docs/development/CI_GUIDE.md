# CI/CD Guide — RAF Intelligence

This guide explains how to run every CI check locally before pushing, so the GitHub Actions pipeline passes on the first try.

## Prerequisites

| Tool | Install |
|------|---------|
| Python 3.11 | `pyenv install 3.11` |
| Node 20 | `nvm install 20` |
| Docker | docker.com/get-started |
| actionlint (optional) | `brew install actionlint` |

---

## Backend checks

### 1. Create virtualenv (once)

```bash
cd backend
python3.11 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install ruff mypy bandit pip-audit pytest pytest-timeout pytest-asyncio
```

### 2. Lint

```bash
# From repo root
ruff check backend/
mypy backend/app --ignore-missing-imports
```

Expected: zero errors. If mypy reports errors in third-party stubs, they are suppressed by `--ignore-missing-imports`.

### 3. Security scan

```bash
bandit -r backend/app/ -ll -ii
pip-audit -r backend/requirements.txt --skip-editable
```

`bandit` flags LOW severity as informational only; the CI gate uses `-ll -ii` (medium+ issues only).

### 4. Unit tests (no live services needed)

```bash
cd backend
.venv/bin/pytest tests/ -m "not integration" --no-cov -q --timeout=30
```

### 5. Integration tests (needs MySQL + Redis)

Start services via Docker:

```bash
docker run -d --name ci-mysql -e MYSQL_ROOT_PASSWORD=rootpassword \
  -e MYSQL_DATABASE=raf_db -e MYSQL_USER=raf -e MYSQL_PASSWORD=rafpassword \
  -p 3306:3306 mysql:8.0

docker run -d --name ci-redis -p 6379:6379 redis:7-alpine
```

Then:

```bash
export DB_HOST=127.0.0.1 DB_PORT=3306 DB_NAME=raf_db DB_USER=raf \
       DB_PASSWORD=rafpassword DB_SSL_ENABLED=false \
       REDIS_URL=redis://localhost:6379/0 SECRET_KEY=local-test

cd backend
.venv/bin/pytest tests/ -m integration --no-cov -q --timeout=30
```

### 6. Docker build + Trivy scan

```bash
docker build -t raf-backend:local backend/

# Trivy (install: brew install trivy)
trivy image --severity HIGH,CRITICAL --exit-code 1 raf-backend:local
```

---

## Frontend checks

```bash
cd frontend
npm ci

# Lint
npm run lint

# Type check (tsc --noEmit fallback if typecheck script absent)
npx tsc --noEmit

# Build (catches compile-time errors)
npm run build

# E2E (Playwright)
npm run test:e2e
```

---

## Validating workflow YAML

```bash
# Install actionlint
brew install actionlint

# Lint all workflow files
actionlint .github/workflows/*.yml
```

Common actionlint catches: undefined secrets references, wrong `needs` keys, invalid `on` triggers.

---

## Required checks for PR merge

The following jobs are configured as required status checks in GitHub branch protection (set this in repo Settings > Branches):

| Job | Workflow | Hard gate? |
|-----|----------|-----------|
| `lint` | backend-ci | Yes |
| `unit-test` | backend-ci | Yes (soft initially — `continue-on-error: true`) |
| `security-scan` | backend-ci | Yes |
| `docker-build` | backend-ci | Yes |
| `lint` | frontend-ci | Yes |
| `typecheck` | frontend-ci | Yes |
| `build` | frontend-ci | Yes |

`integration-test` and `e2e` are soft gates (`continue-on-error: true`) until the test suite is stable.

---

## Secrets required (GitHub repo/org settings)

| Secret | Used by | Purpose |
|--------|---------|---------|
| `GOOGLE_API_KEY` | backend-ci (integration) | Gemini API calls in integration tests |
| `STAGING_DEPLOY_ROLE_ARN` | deploy-staging | AWS OIDC role for ECR + ECS (TODO: provision) |
| `SLACK_DEPLOY_WEBHOOK` | deploy-staging | Slack deploy notifications (optional) |

OIDC setup for AWS: follow [aws-actions/configure-aws-credentials OIDC guide](https://github.com/aws-actions/configure-aws-credentials#assuming-a-role).

---

## Monthly security scan

Runs automatically on the 1st of each month. Trigger manually:

```
GitHub Actions > Monthly Security Scan > Run workflow
```

Reports are committed to `docs/security/monthly-scan-YYYY-MM-DD.md`.
