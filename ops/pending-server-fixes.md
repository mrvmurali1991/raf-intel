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

**Maintenance window required** — `systemctl restart mysql` drops all active DB
connections for ~5 s. Schedule during off-hours or when no demo is in progress.

Binlog growth was observed at ~100 MB/min on this host (see memory note). The
runtime-applied `SET GLOBAL binlog_expire_logs_seconds=7200` is **lost on every
MySQL restart**. These steps write it permanently into the config file on the
**host** MySQL (not inside a container — the RAF DB runs on host MySQL accessed
via `host.docker.internal`).

### Step 1 — Back up the existing config

```bash
sudo cp /etc/mysql/mysql.conf.d/mysqld.cnf \
        /etc/mysql/mysql.conf.d/mysqld.cnf.bak.$(date +%F)
```

### Step 2 — Verify what is currently in the file

```bash
grep -n "binlog_expire\|max_binlog_size" /etc/mysql/mysql.conf.d/mysqld.cnf
```

### Step 3a — If the `binlog_expire_logs_seconds` line exists (possibly commented out)

Use `sed` to uncomment/set it and add `max_binlog_size` if absent:

```bash
# Uncomment or replace the expiry line
sudo sed -i \
  's/^#\?\s*binlog_expire_logs_seconds\s*=.*/binlog_expire_logs_seconds = 7200/' \
  /etc/mysql/mysql.conf.d/mysqld.cnf

# Add max_binlog_size after the [mysqld] section header if not already present
grep -q "^max_binlog_size" /etc/mysql/mysql.conf.d/mysqld.cnf || \
  sudo sed -i '/^\[mysqld\]/a max_binlog_size = 500M' \
    /etc/mysql/mysql.conf.d/mysqld.cnf
```

### Step 3b — If neither line exists at all

Append both settings at the end of the `[mysqld]` block manually:

```bash
sudo tee -a /etc/mysql/mysql.conf.d/mysqld.cnf <<'EOF'

# RAF-ops: limit binlog disk consumption
binlog_expire_logs_seconds = 7200
max_binlog_size            = 500M
EOF
```

### Step 4 — Verify the file looks correct before restarting

```bash
grep -A2 "binlog" /etc/mysql/mysql.conf.d/mysqld.cnf
```

Expected output:
```
binlog_expire_logs_seconds = 7200
max_binlog_size            = 500M
```

### Step 5 — Restart MySQL (maintenance window)

```bash
sudo systemctl restart mysql
sudo systemctl status mysql   # confirm Active: running
```

### Step 6 — Verify the live variables

```bash
mysql -u root -p -e "SHOW VARIABLES LIKE 'binlog_expire%'; SHOW VARIABLES LIKE 'max_binlog_size';"
```

Expected output:
```
+----------------------------+-------+
| Variable_name              | Value |
+----------------------------+-------+
| binlog_expire_logs_seconds | 7200  |
+----------------------------+-------+
| Variable_name   | Value     |
+-----------------+-----------+
| max_binlog_size | 524288000 |
+-----------------+-----------+
```

### Step 7 — Optionally purge existing stale binlogs immediately

```bash
mysql -u root -p -e "PURGE BINARY LOGS BEFORE NOW() - INTERVAL 2 HOUR;"
```

Check disk freed:
```bash
du -sh /var/lib/mysql/mysql-bin.* 2>/dev/null | tail -5
df -h /var/lib/mysql
```

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

## 6. TLS certificate expiry check and renewal

### Background — Cloudflare vs. origin cert

Cloudflare terminates public TLS (browsers connect to Cloudflare, not to
`10.1.0.204`). There are two separate certs to be aware of:

| Cert | Where it lives | Typical validity |
|------|----------------|-----------------|
| **Edge cert** (Cloudflare-managed) | Cloudflare PoP — auto-renewed | 90 d, fully automatic |
| **Origin cert** (Cloudflare Origin CA or Let's Encrypt) | `/home/ubuntu/raf-intelligence/nginx/certs/` on the host, mounted into the nginx container | 15 yr (Cloudflare Origin CA) *or* 90 d (Let's Encrypt) |

The prior audit noted the **origin cert** expiry around 2026-05-25 — this is the
one that needs attention.

### Step 1 — Check expiry of both domains from the server right now

```bash
# Frontend domain
openssl s_client -connect raf.comercioit.com:443 -servername raf.comercioit.com \
  </dev/null 2>/dev/null | openssl x509 -noout -dates

# API domain
openssl s_client -connect raf-api.comercioit.com:443 -servername raf-api.comercioit.com \
  </dev/null 2>/dev/null | openssl x509 -noout -dates
```

The `notAfter` field is the expiry date.

### Step 2 — Determine which cert type is in use

```bash
ls -la /home/ubuntu/raf-intelligence/nginx/certs/
# Look for: fullchain.pem / privkey.pem (Let's Encrypt)
# or:        origin.crt / origin.key   (Cloudflare Origin CA)
```

Check the issuer:
```bash
openssl x509 -in /home/ubuntu/raf-intelligence/nginx/certs/fullchain.pem \
  -noout -issuer -dates 2>/dev/null || \
openssl x509 -in /home/ubuntu/raf-intelligence/nginx/certs/origin.crt \
  -noout -issuer -dates 2>/dev/null
```

### Step 3a — Renewal: Let's Encrypt / Certbot

```bash
# Dry-run first
sudo certbot renew --dry-run

# Actual renewal
sudo certbot renew

# Reload nginx inside container to pick up new cert
docker compose -f /home/ubuntu/raf-intelligence/docker-compose.prod.yml \
  exec nginx nginx -s reload
```

Confirm new expiry date with the openssl command in Step 1.

### Step 3b — Renewal: Cloudflare Origin CA cert

Cloudflare Origin CA certs are valid for 15 years by default, so this is rarely
needed. If it has expired (or you need a fresh one):

1. In the Cloudflare dashboard go to **SSL/TLS > Origin Server > Create Certificate**.
2. Select the hostnames (`raf.comercioit.com`, `raf-api.comercioit.com`), set
   validity to 15 years, download `origin.crt` and `origin.key`.
3. Copy them to the server (no secrets in this file — transfer via SCP):
   ```bash
   scp origin.crt origin.key \
     ubuntu@10.1.0.204:/home/ubuntu/raf-intelligence/nginx/certs/
   ```
4. Reload nginx:
   ```bash
   docker compose -f /home/ubuntu/raf-intelligence/docker-compose.prod.yml \
     exec nginx nginx -s reload
   ```

### Step 4 — Install the automated weekly check (crontab on 10.1.0.204)

The script `scripts/check_cert_expiry.sh` checks both domains and exits 1
(triggering cron mail) if any cert is within 30 days of expiry.

Add to the `ubuntu` user's crontab (`crontab -e`):

```cron
# Check TLS cert expiry every Monday at 08:00 UTC; email on warning
0 8 * * 1 /home/ubuntu/raf-intelligence/scripts/check_cert_expiry.sh \
            >> /var/log/raf-cert-check.log 2>&1
```

Set `MAILTO` at the top of the crontab to receive email alerts:

```cron
MAILTO=mrvmurali1991@gmail.com
```

Manual run to verify the script works:

```bash
bash /home/ubuntu/raf-intelligence/scripts/check_cert_expiry.sh
```

Expected output (healthy state):
```
2026-04-22T08:00:01Z OK: raf.comercioit.com cert expires in 245 day(s) (...)
2026-04-22T08:00:02Z OK: raf-api.comercioit.com cert expires in 245 day(s) (...)
```

Log is appended to `/var/log/raf-cert-check.log`; rotate with:
```bash
sudo logrotate -f /etc/logrotate.d/raf-cert-check  # if a logrotate conf exists
```

---

## 7. Image / requirements drift check before every deploy

Docker images can silently drift from `requirements.txt` when a container is
restarted without a full rebuild (e.g., `docker compose restart backend`). Run
the smoke test and the pip drift check before **every** deploy, regardless of
how small the change appears.

### Step 1 — Run the smoke test (Agent-K script, run on the server)

```bash
bash /home/ubuntu/raf-intelligence/scripts/smoke_test.sh
```

The script exits 0 on pass and prints a PASS/FAIL summary per check. Do **not**
deploy if any check fails.

### Step 2 — Verify pip packages inside the running backend container match requirements.txt

Run this one-liner on the server:

```bash
docker exec raf-backend bash -c "
  pip freeze > /tmp/installed.txt
  # Strip version pins from requirements.txt for a name-only comparison
  awk -F'[=><!]' '{print tolower(\$1)}' /app/requirements.txt | sort > /tmp/req_names.txt
  awk -F'==' '{print tolower(\$1)}' /tmp/installed.txt | sort > /tmp/inst_names.txt
  # Packages in requirements.txt but missing from the container
  comm -23 /tmp/req_names.txt /tmp/inst_names.txt
"
```

An empty output means no drift. Any lines printed are package names that are
declared in `requirements.txt` but not installed in the running image — rebuild
before deploying:

```bash
docker compose -f /home/ubuntu/raf-intelligence/docker-compose.prod.yml \
  build --no-cache backend
docker compose -f /home/ubuntu/raf-intelligence/docker-compose.prod.yml \
  up -d backend
```

### Step 3 — Confirm the container is healthy after rebuild

```bash
docker ps --format '{{.Names}} {{.Status}}' | grep backend
# Expected: raf-backend Up X seconds (healthy)
```
