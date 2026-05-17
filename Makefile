# ---------------------------------------------------------------------------
# RAF Intelligence — Makefile
# ---------------------------------------------------------------------------

REMOTE_HOST   := ubuntu@10.1.1.66
REMOTE_DIR    := /home/ubuntu/raf-intelligence
SSH_OPTS      := -o StrictHostKeyChecking=accept-new
COMPOSE_FILE  := docker-compose.yml
COMPOSE_PROD  := docker-compose.prod.yml

# ---- Local Development ---------------------------------------------------

dev-frontend:
	cd frontend && NEXT_PUBLIC_API_URL=http://localhost:8500 npx next dev --turbopack -p 3000

dev-backend:
	cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8500 --reload

dev:
	trap 'kill 0' EXIT; $(MAKE) dev-backend & $(MAKE) dev-frontend & wait

# Local stack with MySQL (docker-compose.local.yml)
local-up:
	docker compose -f docker-compose.local.yml up -d --build

local-down:
	docker compose -f docker-compose.local.yml down

# ---- Production Deployment (simple — no Celery) --------------------------

deploy:
	rsync -avz --delete --exclude='node_modules' --exclude='.next' --exclude='.env.local' --exclude='__pycache__' --exclude='.venv' -e "ssh $(SSH_OPTS)" ./frontend/ $(REMOTE_HOST):$(REMOTE_DIR)/frontend/
	rsync -avz --exclude='__pycache__' --exclude='.venv' --exclude='.env.local' -e "ssh $(SSH_OPTS)" ./backend/ $(REMOTE_HOST):$(REMOTE_DIR)/backend/
	rsync -avz --exclude docker-compose.local.yml -e "ssh $(SSH_OPTS)" ./docker-compose.yml ./docker-compose.prod.yml ./Makefile $(REMOTE_HOST):$(REMOTE_DIR)/
	ssh $(SSH_OPTS) $(REMOTE_HOST) "test -f $(REMOTE_DIR)/.env || { echo 'ERROR: .env not found on remote server'; exit 1; }"
	ssh $(SSH_OPTS) $(REMOTE_HOST) "cd $(REMOTE_DIR) && mkdir -p data/uploads data/logs data/redis && docker compose down && docker compose build && docker compose up -d"

deploy-frontend:
	rsync -avz --delete --exclude='node_modules' --exclude='.next' --exclude='.env.local' -e "ssh $(SSH_OPTS)" ./frontend/ $(REMOTE_HOST):$(REMOTE_DIR)/frontend/
	ssh $(SSH_OPTS) $(REMOTE_HOST) "cd $(REMOTE_DIR) && docker compose build frontend && docker compose up -d --no-deps frontend"

deploy-backend:
	rsync -avz --exclude='__pycache__' --exclude='.venv' --exclude='.env.local' -e "ssh $(SSH_OPTS)" ./backend/ $(REMOTE_HOST):$(REMOTE_DIR)/backend/
	ssh $(SSH_OPTS) $(REMOTE_HOST) "cd $(REMOTE_DIR) && docker compose build backend && docker compose up -d --no-deps backend"

# ---- Production Deployment (full — with Celery/Redis) --------------------

deploy-prod:
	rsync -avz --delete --exclude='node_modules' --exclude='.next' --exclude='.env.local' --exclude='__pycache__' --exclude='.venv' -e "ssh $(SSH_OPTS)" ./frontend/ $(REMOTE_HOST):$(REMOTE_DIR)/frontend/
	rsync -avz --exclude='__pycache__' --exclude='.venv' --exclude='.env.local' -e "ssh $(SSH_OPTS)" ./backend/ $(REMOTE_HOST):$(REMOTE_DIR)/backend/
	rsync -avz --exclude docker-compose.local.yml -e "ssh $(SSH_OPTS)" ./docker-compose.prod.yml ./Makefile $(REMOTE_HOST):$(REMOTE_DIR)/
	ssh $(SSH_OPTS) $(REMOTE_HOST) "test -f $(REMOTE_DIR)/.env || { echo 'ERROR: .env not found on remote server'; exit 1; }"
	ssh $(SSH_OPTS) $(REMOTE_HOST) "cd $(REMOTE_DIR) && mkdir -p data/uploads data/logs data/redis && docker compose -f $(COMPOSE_PROD) down && docker compose -f $(COMPOSE_PROD) build && docker compose -f $(COMPOSE_PROD) up -d"

# ---- Logs ----------------------------------------------------------------

logs:
	ssh $(SSH_OPTS) $(REMOTE_HOST) "cd $(REMOTE_DIR) && docker compose logs --tail=50 -f"

logs-backend:
	ssh $(SSH_OPTS) $(REMOTE_HOST) "docker logs raf-backend --tail=50 -f"

logs-frontend:
	ssh $(SSH_OPTS) $(REMOTE_HOST) "docker logs raf-frontend --tail=50 -f"

logs-worker:
	ssh $(SSH_OPTS) $(REMOTE_HOST) "docker logs raf-worker --tail=50 -f"

# ---- Status / Helpers ----------------------------------------------------

status:
	ssh $(SSH_OPTS) $(REMOTE_HOST) "cd $(REMOTE_DIR) && docker compose ps"

restart:
	ssh $(SSH_OPTS) $(REMOTE_HOST) "cd $(REMOTE_DIR) && docker compose restart"

shell-backend:
	ssh $(SSH_OPTS) $(REMOTE_HOST) "docker exec -it raf-backend bash"

# ---- Database Backup & Restore -------------------------------------------

backup:
	./scripts/backup.sh --full

backup-raf:
	./scripts/backup.sh --raf-only

backup-openemr:
	./scripts/backup.sh --openemr-only

restore:
	@if [ -z "$(FILE)" ]; then echo "ERROR: FILE is required. Usage: make restore FILE=path/to/backup.sql.gz DB=raf|openemr"; exit 1; fi
	@if [ -z "$(DB)" ]; then echo "ERROR: DB is required. Usage: make restore FILE=path/to/backup.sql.gz DB=raf|openemr"; exit 1; fi
	./scripts/restore.sh $(FILE) --$(DB)

# ---- Frontend E2E Testing ------------------------------------------------

e2e:
	@echo "Running Playwright E2E suite (spawns local dev server)..."
	bash frontend/scripts/e2e.sh

e2e-staging:
	@echo "Running Playwright E2E suite against staging (https://raf.comercioit.com)..."
	cd frontend && npx playwright test --project=e2e

.PHONY: dev dev-frontend dev-backend local-up local-down deploy deploy-frontend deploy-backend deploy-prod logs logs-backend logs-frontend logs-worker status restart shell-backend backup backup-raf backup-openemr restore e2e e2e-staging
