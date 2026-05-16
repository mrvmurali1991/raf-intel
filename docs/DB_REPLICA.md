# MySQL Read Replica — Local Scaffold

## Why

A single MySQL instance is a SPOF. Offloading SELECTs (patient lists, RAF
score dashboards, audit reports) to a read replica keeps write latency
predictable under load and buys time before a managed HA solution is needed.

## When to enable

Enable when the primary shows sustained CPU > 70 % or p95 query latency
exceeds ~200 ms. For local development the replica is optional scaffolding
to prove read-routing works before investing in production HA.

## How to start the replica locally

```bash
# Start ONLY the replica (primary must already be running)
docker compose -f docker-compose.local.yml --profile replica up -d mysql-replica

# Verify replication is running
docker exec raf-mysql-replica \
  mysql -uroot -proot -e "SHOW REPLICA STATUS\G" \
  | grep -E "Replica_(IO|SQL)_Running|Seconds_Behind"
```

Expected output:
```
Replica_IO_Running: Yes
Replica_SQL_Running: Yes
Seconds_Behind_Source: 0
```

## How to route backend reads to the replica

Add to `backend/.env` (or the `backend` service environment in `docker-compose.local.yml`):

```
DB_READ_HOST=localhost
DB_READ_PORT=3310
```

The backend `db.py` `get_raf_read_pool()` picks these up at startup. Any
code that calls `raf_read_cursor()` is automatically routed to the replica;
`raf_cursor()` (writes) always hits the primary on port 3309.

## Caveats

- **Read-after-write lag** — replication is asynchronous. A record written
  then immediately read via `raf_read_cursor()` may not yet appear on the
  replica. Use `raf_cursor()` when the read must reflect a just-committed
  write (e.g. post-save confirmation pages).
- **Writes must go to primary** — the replica runs in read-only mode.
  INSERT/UPDATE/DELETE through `raf_read_cursor()` will raise a MySQL error.
- **No automated failover** — if the primary goes down, the replica does not
  promote itself. Manual intervention or a tool like Orchestrator / MHA is
  required. This scaffold is not production-HA; it is a routing proof-of-concept.
- **Binary log position drift** — `replica-init.sql` starts from position 4
  (beginning of the first binlog). If the primary already has data, the
  replica will replay all history on first boot, which can take minutes.
  For a pre-populated primary, use `mysqldump --master-data=2` to seed the
  replica and set `SOURCE_LOG_FILE` / `SOURCE_LOG_POS` explicitly.
- **Credentials** — `root / root` are local-dev-only. Production replicas
  must use a dedicated replication user with only `REPLICATION SLAVE` privilege.
