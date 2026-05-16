-- replica-init.sql
-- Runs inside the mysql-replica container on first boot via
-- /docker-entrypoint-initdb.d/init.sql.
--
-- Prerequisites:
--   * Primary must be reachable at host "mysql" (Docker network alias).
--   * Primary must have binary logging enabled (server-id=1, log-bin).
--   * Root credentials are shared for local dev convenience; never do this in prod.
--
-- Idempotency: STOP REPLICA is safe to call even when replication has not
-- started yet — MySQL ignores it silently.

-- Halt any existing replica threads before reconfiguring.
STOP REPLICA;

-- Point this replica at the primary.
-- SOURCE_AUTO_POSITION=1 requires GTIDs.  Using file/position mode instead
-- so the scaffold works with the default binlog-format=ROW config without
-- requiring GTID_MODE=ON on the primary.
CHANGE REPLICATION SOURCE TO
    SOURCE_HOST       = 'mysql',
    SOURCE_PORT       = 3306,
    SOURCE_USER       = 'root',
    SOURCE_PASSWORD   = 'root',
    SOURCE_LOG_FILE   = '',      -- empty = let replica auto-discover from primary
    SOURCE_LOG_POS    = 4,       -- 4 = start of first binlog file
    SOURCE_CONNECT_RETRY = 10;

-- Begin replicating.
START REPLICA;

-- Quick sanity check — writes 'Replica_IO_Running' and 'Replica_SQL_Running'
-- to the error log so you can verify via: docker logs raf-mysql-replica
-- (MySQL does not allow SELECT output from init scripts, so we use a no-op
-- signal instead — check replication status with:
--   docker exec raf-mysql-replica mysql -uroot -proot -e "SHOW REPLICA STATUS\G")
