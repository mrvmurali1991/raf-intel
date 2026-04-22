# RAF Intelligence — Deployment Guide

## Pre-deploy checklist

> **Why this exists:** The production server frequently carries uncommitted edits
> and unpushed commits (WIP drift). A blind `git pull` can silently overwrite
> in-progress work or leave the running containers out of sync with the new code.
> Run every item below before touching Docker on `10.1.0.204`.

- [ ] **1. Check server git state** — SSH in and confirm there are no uncommitted
  edits or unpushed commits before pulling:
  ```bash
  cd /home/ubuntu/raf-intelligence
  git status
  git log origin/local..HEAD --oneline   # commits not yet on remote
  ```
  Stash or commit any WIP before proceeding; never `git pull` over untracked
  changes.

- [ ] **2. Run smoke_test.sh** — execute on the server and confirm every check
  passes before deploying:
  ```bash
  bash /home/ubuntu/raf-intelligence/scripts/smoke_test.sh
  ```

- [ ] **3. Verify binlog expiry is still set** — host MySQL resets runtime vars on
  restart. Confirm the persisted config is in place (see `ops/pending-server-fixes.md` §2):
  ```bash
  mysql -u root -p -e "SHOW VARIABLES LIKE 'binlog_expire_logs_seconds';"
  # Expected value: 7200
  ```

- [ ] **4. Check TLS cert expiry** — confirm both domains are not within 30 days of
  expiry (see `ops/pending-server-fixes.md` §6):
  ```bash
  bash /home/ubuntu/raf-intelligence/scripts/check_cert_expiry.sh
  ```

- [ ] **5. Verify .env has not drifted** — confirm `DB_SSL_ENABLED=false` is still
  present (production MySQL has no TLS; removing this flag causes connection
  failures):
  ```bash
  grep DB_SSL_ENABLED /home/ubuntu/raf-intelligence/.env
  # Expected: DB_SSL_ENABLED=false
  ```

- [ ] **6. Confirm no live demo is in progress** — restarts cause a ~10–30 s outage
  per service and will disrupt any active demo session. Check with the team first.

---

## Server Details

| Item | Value |
|------|-------|
| Server (private IP) | `10.1.0.204` |
| Jump host (public) | `15.204.73.232:2222` |
| SSH Key | `~/Downloads/openvpn-key-v2.pem` |
| SSH User | `ubuntu` (on both jump host and target) |
| Project Path | `/home/ubuntu/raf-intelligence` |
| Git Branch | `local` |
| Frontend URL | `https://raf.comercioit.com` (port 3000) |
| Backend API | `https://raf-api.comercioit.com` (port 8500) |
| OpenEMR | port 8080 |

---

## Network Topology

```
┌─────────────┐     ┌─────────────────────┐     ┌──────────────────┐
│ Your laptop │────▶│ Jump host (bastion) │────▶│ App server       │
│             │ 2222│ 15.204.73.232       │ 22  │ 10.1.0.204       │
└─────────────┘     └─────────────────────┘     │ (private subnet) │
                                                 └──────────────────┘
```

`10.1.0.204` lives on a private subnet. Direct SSH from outside only works if
you are on the OpenVPN tunnel. From anywhere else (coffee shop, hotel Wi-Fi,
CI), you must hop through the bastion at `15.204.73.232:2222`.

---

## Prerequisites

- SSH key at `~/Downloads/openvpn-key-v2.pem` (chmod 400)
- Git repo pushed to `origin/local` branch
- Docker & Docker Compose installed on server (already set up)
- **One of:**
  - OpenVPN connected → use direct SSH (section below)
  - No VPN → use jump-host SSH (section further down)

---

## Step-by-Step Deployment

### 1. SSH into the server

```bash
ssh -i ~/Downloads/openvpn-key-v2.pem ubuntu@10.1.0.204
```

### 2. Pull latest code

```bash
cd /home/ubuntu/raf-intelligence
git pull origin local
```

### 2.5. Smoke test (run after build, before up)

```bash
bash scripts/smoke_test.sh
```

Run this after every `docker compose build` and before `docker compose up -d`.
The script boots a throwaway backend container (never joined to the live
compose network), verifies that all critical Python modules import cleanly
— including `app.main`, `attestation_service`, `meat_evidence_service`,
`immutable_audit`, `suspect_engine`, and `raf.calculator` — and then probes
the `/health` endpoint with up to 30 seconds of polling.  A non-zero exit
means a dependency is missing or broken (e.g. the tenacity import failure
that previously reached production); fix the issue before proceeding.
The container is killed and removed automatically regardless of outcome.

### 3. Deploy Backend Only (fast — no build needed)

```bash
# Copy updated files into running container
docker cp backend/app/routers/myfile.py raf-backend:/app/app/routers/myfile.py
docker cp backend/app/services/myservice.py raf-backend:/app/app/services/myservice.py

# Restart backend (picks up changes immediately)
docker compose restart backend
```

**Verify:**
```bash
docker ps --format '{{.Names}} {{.Status}}' | grep backend
# Should show: raf-backend Up X seconds (healthy)
```

### 4. Deploy Frontend (requires build — ~3 minutes)

```bash
docker compose build frontend
docker compose up -d frontend
```

**Verify:**
```bash
docker ps --format '{{.Names}} {{.Status}}' | grep frontend
# Should show: raf-frontend Up X seconds (healthy)

curl -s -o /dev/null -w "HTTP %{http_code}" http://localhost:3000/
# Should show: HTTP 200
```

### 5. Deploy Both (full rebuild)

```bash
docker compose build --no-cache
docker compose up -d
```

### 6. Deploy Everything from Local Machine (one-liner)

**Backend only:**
```bash
git push origin local && \
ssh -i ~/Downloads/openvpn-key-v2.pem ubuntu@10.1.0.204 \
  "cd /home/ubuntu/raf-intelligence && git pull origin local && docker compose restart backend"
```

**Frontend only:**
```bash
git push origin local && \
ssh -i ~/Downloads/openvpn-key-v2.pem ubuntu@10.1.0.204 \
  "cd /home/ubuntu/raf-intelligence && git pull origin local && docker compose build frontend && docker compose up -d frontend"
```

**Full stack:**
```bash
git push origin local && \
ssh -i ~/Downloads/openvpn-key-v2.pem ubuntu@10.1.0.204 \
  "cd /home/ubuntu/raf-intelligence && git pull origin local && docker compose build --no-cache && docker compose up -d"
```

---

## Deploying via Jump Host (no VPN)

When you are not on the OpenVPN tunnel, the direct SSH commands above will
time out. Use the bastion at `15.204.73.232:2222` as a `ProxyCommand` hop.

### SSH connection flags (and why each matters)

The connection is fiddly — use these exact flags to avoid lockouts:

| Flag | Purpose |
|------|---------|
| `-F /dev/null` | Ignore your `~/.ssh/config` so local overrides don't interfere |
| `-o IdentitiesOnly=yes` | Only offer the `-i` key; stops ssh-agent from trying every key it has and tripping the "Too many authentication failures" limit |
| `-o StrictHostKeyChecking=no` | Skip host-key prompt (safe here because the hop is known) |
| `-i ~/Downloads/openvpn-key-v2.pem` | **Same key works on both hops** (jump host and target) |
| `-o ProxyCommand="..."` | The hop command — run SSH on the bastion that forwards stdio to the target |

### One-shot SSH

```bash
ssh \
  -F /dev/null -o IdentitiesOnly=yes -o StrictHostKeyChecking=no \
  -i ~/Downloads/openvpn-key-v2.pem \
  -o ProxyCommand="ssh -F /dev/null -o IdentitiesOnly=yes -o StrictHostKeyChecking=no \
     -i ~/Downloads/openvpn-key-v2.pem -p 2222 -W 10.1.0.204:22 ubuntu@15.204.73.232" \
  ubuntu@10.1.0.204
```

### SCP a file up through the bastion

```bash
scp \
  -F /dev/null -o IdentitiesOnly=yes -o StrictHostKeyChecking=no \
  -i ~/Downloads/openvpn-key-v2.pem \
  -o ProxyCommand="ssh -F /dev/null -o IdentitiesOnly=yes -o StrictHostKeyChecking=no \
     -i ~/Downloads/openvpn-key-v2.pem -p 2222 -W 10.1.0.204:22 ubuntu@15.204.73.232" \
  /path/to/local-file.tsx \
  ubuntu@10.1.0.204:/tmp/
```

### Cleaner: bake the hop into `~/.ssh/config`

Drop this into `~/.ssh/config` once, and the flags disappear forever:

```sshconfig
Host raf-bastion
  HostName 15.204.73.232
  Port 2222
  User ubuntu
  IdentityFile ~/Downloads/openvpn-key-v2.pem
  IdentitiesOnly yes

Host raf-prod
  HostName 10.1.0.204
  User ubuntu
  IdentityFile ~/Downloads/openvpn-key-v2.pem
  IdentitiesOnly yes
  ProxyJump raf-bastion
  StrictHostKeyChecking no
```

Then it's just:

```bash
ssh raf-prod
scp ./build.tsx raf-prod:/tmp/
```

### Full-stack deploy via jump host (one-liner)

```bash
git push origin local && \
ssh raf-prod \
  "cd /home/ubuntu/raf-intelligence && git pull origin local && \
   docker compose build frontend && docker compose up -d frontend"
```

---

## Long-running builds: always use tmux

Frontend `docker compose build` takes 3–5 minutes. An SSH session that drops
mid-build leaves the Docker daemon building on a dead PTY — you lose output
and sometimes the build silently dies. Always detach builds into a tmux
session on the server:

```bash
ssh raf-prod bash -lc '
  cd /home/ubuntu/raf-intelligence
  rm -f /tmp/build.log
  tmux new-session -d -s deploy "
    docker compose build frontend > /tmp/build.log 2>&1 && \
    docker compose up -d frontend >> /tmp/build.log 2>&1 && \
    echo BUILD_SENTINEL_DONE >> /tmp/build.log
  "
  echo "Build started in tmux session deploy"
'
```

### Watch progress without re-attaching

```bash
ssh raf-prod "tail -f /tmp/build.log"
```

### Poll for completion (scripts / CI)

```bash
until ssh raf-prod "grep -q BUILD_SENTINEL_DONE /tmp/build.log 2>/dev/null"; do
  sleep 20
done
echo "Build finished. Verifying container..."
ssh raf-prod "docker ps --filter name=frontend --format '{{.Names}} {{.Status}}'"
```

> **Important:** Poll for a unique sentinel (`BUILD_SENTINEL_DONE`), not
> generic `DONE`. Docker Buildx emits `DONE` on every stage (`#1 DONE 0.0s`),
> so `grep DONE` fires on the first stage and you'll think the build is
> finished before it actually is.

### Kill a stuck build

```bash
ssh raf-prod "tmux kill-session -t deploy 2>/dev/null; docker buildx prune -f"
```

---

## Common errors & fixes

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Too many authentication failures` | ssh-agent is offering every key you own to the bastion before the correct one | Add `-o IdentitiesOnly=yes` on **both** the outer command and the inner `ProxyCommand` |
| `Permission denied (publickey)` from bastion | Key file path wrong, or key not chmod 400 | `chmod 400 ~/Downloads/openvpn-key-v2.pem`; verify the file exists |
| `Connection timed out` to `10.1.0.204` | You tried direct SSH without VPN | Use the jump-host command, or connect VPN first |
| `Connection timed out` to `15.204.73.232:2222` | Bastion blocked your IP or is down | Check you're reaching port 2222 (not 22); contact ops if persistent |
| Build hangs on "Collecting build traces" | Buildx cache corruption | `ssh raf-prod "docker buildx prune -f"` then rebuild |
| Container shows "Up X minutes" after `up -d` | `docker compose up -d` is a no-op when image hash didn't change | Force: `docker compose up -d --force-recreate frontend` |
| Same-name tmux session from prior run | Previous deploy crashed | `tmux kill-session -t deploy` before starting a new one |

---

## Containers

| Container | Port | Purpose |
|-----------|------|---------|
| `raf-backend` | 8500 | FastAPI backend |
| `raf-frontend` | 3000 | Next.js frontend |
| `raf-worker` | — | Celery worker (background tasks) |
| `raf-mysql` | 3306 | MySQL database |
| `raf-redis` | 6379 | Cache + Celery broker |
| `raf-openemr` | 8080 | Local OpenEMR instance |

---

## Useful Commands

### Check all containers
```bash
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
```

### View backend logs
```bash
docker logs raf-backend --tail 50 -f
```

### View worker logs
```bash
docker logs raf-worker --tail 50 -f
```

### Restart all services
```bash
docker compose restart
```

### Access MySQL
```bash
docker exec -it raf-mysql mysql -u root -p raf_intelligence
```

### Clear Redis cache
```bash
docker exec raf-redis redis-cli FLUSHALL
```

### Test API health
```bash
# Get auth token
TOKEN=$(curl -s http://localhost:8500/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@raf.health","password":"Admin@123"}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

# Test dashboard
curl -s http://localhost:8500/api/dashboard/stats \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Backend not starting | `docker logs raf-backend --tail 30` — check for import errors |
| Frontend build fails | Check TypeScript errors in build output |
| Container unhealthy | `docker compose restart <service>` |
| Stale data after EMR switch | `docker exec raf-redis redis-cli FLUSHALL` |
| SSH timeout during build | Use `nohup` or run build in `tmux` session |
