# Pending Server Fixes — Run Manually on Production (10.1.0.204)

These commands require SSH access via the jump host and must be executed by a human
during an appropriate maintenance window. None of these have been applied automatically.

---

## 1. Fix .env file permissions

```bash
chmod 600 /home/ubuntu/raf-intelligence/.env
```

Restricts the `.env` file (which contains secrets) to owner-read/write only.

---

## 2. Persist binlog expiry in MySQL config

The `binlog_expire_logs_seconds = 7200` setting was previously applied at runtime only
and will be lost on MySQL restart. To persist it:

1. Edit `/etc/mysql/mysql.conf.d/mysqld.cnf` — find the line:
   ```
   # binlog_expire_logs_seconds = 7200
   ```
   Uncomment it (remove the leading `#`):
   ```
   binlog_expire_logs_seconds = 7200
   ```
2. Restart MySQL during a maintenance window:
   ```bash
   sudo systemctl restart mysql
   ```

Note: binlog growth was observed at ~100 MB/min on this host. Without this fix,
binlogs accumulate until disk pressure triggers failures.

---

## 3. Install nightly backup crontab entry

Add the following entry to the `ubuntu` user's crontab (`crontab -e`):

```
15 2 * * * cd /home/ubuntu/raf-intelligence && ./scripts/backup.sh >> /var/log/raf-backup.log 2>&1
```

This runs the backup script daily at 02:15 UTC and appends output to the log file.

---

## 4. Seed initial backup

After installing the crontab, trigger an immediate baseline backup:

```bash
cd /home/ubuntu/raf-intelligence && ./scripts/backup.sh
```

Verify the backup completed and the output log looks clean:

```bash
tail -50 /var/log/raf-backup.log
```

---

## 5. Diagnose EMR OAuth2 failure ("assertion type is not supported")

This error indicates a mismatch between the OAuth2 grant type configured in the
backend and what ehrservicedesk.com (external OpenEMR) expects.

Steps to investigate:

1. Check the OpenEMR OAuth2 fields in `/home/ubuntu/raf-intelligence/backend/.env`:
   - `OPENEMR_CLIENT_ID`
   - `OPENEMR_CLIENT_SECRET`
   - `OPENEMR_TOKEN_URL`
   - `OPENEMR_OAUTH_SCOPE`

2. Confirm the OAuth2 client registered at ehrservicedesk.com is **enabled** in the
   OpenEMR admin UI (`Admin > System > OAuth2 Clients`). Dynamically registered clients
   are disabled by default and must be manually enabled.

3. Verify the grant type — the "assertion type is not supported" error typically means
   a JWT Bearer assertion grant (`urn:ietf:params:oauth:grant-type:jwt-bearer`) is being
   sent but the server expects `client_credentials` or `authorization_code`.
   Align the backend's token request with the client configuration in OpenEMR.

4. Re-test after corrections:
   ```bash
   docker compose exec backend python -c "
   from app.services.openemr_service import get_token; import asyncio; asyncio.run(get_token())
   "
   ```

---

## 6. Check Cloudflare / origin TLS certificate renewal

Per prior audit, the origin TLS certificate expires approximately **2026-05-25**.
Check and renew before that date to avoid a production outage.

Steps:

1. Verify current expiry from the server:
   ```bash
   openssl s_client -connect raf-api.comercioit.com:443 -servername raf-api.comercioit.com \
     </dev/null 2>/dev/null | openssl x509 -noout -dates
   ```

2. If using Let's Encrypt (Certbot):
   ```bash
   sudo certbot renew --dry-run
   sudo certbot renew
   ```
   Then reload nginx:
   ```bash
   docker compose -f /home/ubuntu/raf-intelligence/docker-compose.prod.yml exec nginx nginx -s reload
   ```

3. If using a manually uploaded cert in Cloudflare or on the origin, replace the cert
   files under `./nginx/certs/` and reload nginx as above.
