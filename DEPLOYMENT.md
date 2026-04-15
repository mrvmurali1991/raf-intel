# RAF Intelligence — Deployment Guide

## Server Details

| Item | Value |
|------|-------|
| Server | `10.1.0.204` |
| SSH Key | `~/Downloads/openvpn-key-v2.pem` |
| SSH User | `ubuntu` |
| Project Path | `/home/ubuntu/raf-intelligence` |
| Git Branch | `local` |
| Frontend URL | `https://raf.comercioit.com` (port 3000) |
| Backend API | `https://raf-api.comercioit.com` (port 8500) |
| OpenEMR | port 8080 |

---

## Prerequisites

- SSH access to the server
- Git repo pushed to `origin/local` branch
- Docker & Docker Compose installed on server

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
