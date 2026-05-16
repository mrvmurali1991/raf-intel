# HA App Server Deployment

Scaffold for a 2-backend + nginx load-balancer pattern that removes the
single-app-server SPOF from the default stack. Profile-gated so it does not
disrupt local development.

## When to enable

Turn this on once **any** of the following is true:

- Paying customer count exceeds ~5 (loss of the single backend now affects
  multiple tenants simultaneously).
- Contractual uptime SLO > 99.9% (43m/month budget — a single rolling
  restart already exceeds that on a single-instance stack).
- Routine deploys are causing user-visible blips (zero-downtime deploy via
  per-replica drain becomes possible with two backends).

## How to start (local validation)

The HA stack reuses `mysql` from `docker-compose.local.yml` and overlays
two backends + nginx LB + a dedicated `redis`:

```bash
# 1. Stop the default single backend (it binds the same host port 8500).
docker compose -f docker-compose.local.yml stop backend

# 2. Bring up the HA overlay.
docker compose -f docker-compose.local.yml -f docker-compose.ha.yml \
    --profile ha up -d

# 3. Validate round-robin (look for alternating BACKEND_REPLICA_ID in logs).
for i in 1 2 3 4; do curl -s http://localhost:8500/api/v1/health; done
docker logs raf-backend1 --tail 5
docker logs raf-backend2 --tail 5

# 4. Validate LB-local health probe.
curl -s http://localhost:8500/lb-healthz   # -> "ok"
```

Direct per-replica probing (bypass LB) is available at host ports
`8501` (backend1) and `8502` (backend2) for debugging.

## Behavior changes vs. single-backend

- **No sticky sessions.** The LB does round-robin; assumes the backend is
  stateless. Before promoting to prod, **verify session/auth state lives in
  Redis or the DB, NOT in process memory** — any in-process cache, rate
  limiter, or websocket registry will behave inconsistently across replicas.
- **SSE / streaming.** `nginx/lb.conf` already sets `proxy_buffering off`
  for `^/api/v[0-9]+/(stream|events|sse|notifications)`. Add new streaming
  prefixes to that block when introducing new SSE endpoints, otherwise
  events will batch at stream close and the demo "magic moment" auto-sync
  toast will not appear in real time.
- **File uploads.** `data/uploads`, `data/submissions`, and `data/logs` are
  bind-mounted into both replicas. On a single host this is fine; on
  multi-host prod, swap for object storage (S3 / GCS / Azure Blob) — the
  bind-mount strategy does NOT survive cross-host scheduling.
- **Background jobs.** Both replicas run the same scheduler/cron code by
  default. If any periodic task is defined in-process, it will fire 2x.
  Move scheduled work to a dedicated worker service or guard with a Redis
  leader-election lock before enabling HA in prod.

## Production checklist

When promoting this pattern to the production host (or replacing the
single-backend service entirely):

1. **Pin image tags.** Replace `build: ./backend` with a pinned
   `image: registry/raf-backend:<git-sha>` in the prod overlay.
2. **Add backend healthchecks** (Docker `healthcheck:` block) so
   `depends_on: condition: service_healthy` blocks the LB until both
   replicas are accepting traffic.
3. **Front nginx with HAProxy / Cloud LB.** The container-local nginx-lb
   protects against backend crashes but is itself a single process on a
   single host. For cross-host HA, terminate TLS at a managed L4/L7 LB
   (AWS ALB, GCP Cloud LB, Cloudflare) that targets multiple hosts each
   running this stack.
4. **External Redis.** Replace the in-stack `redis` with a managed
   instance (ElastiCache / Memorystore / Upstash) so replicas in different
   hosts share state.
5. **Drain on deploy.** Use `docker compose stop backend1 && wait &&
   deploy && start backend1 && repeat for backend2` — nginx will route to
   the survivor automatically thanks to `max_fails=3 fail_timeout=30s`.
6. **Observability.** Scrape nginx `stub_status` and per-replica metrics;
   alert on upstream peer marked-down events.

## Files

- `docker-compose.ha.yml` — profile-gated overlay (services tagged
  `profiles: [ha]`).
- `nginx/lb.conf` — upstream pool, SSE-safe location block, LB health
  endpoint.
