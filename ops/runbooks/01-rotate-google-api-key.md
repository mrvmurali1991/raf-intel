# Runbook 01 — Rotate `GOOGLE_API_KEY` in Production

**Severity:** BLOCKER
**Time estimate:** ~20 minutes
**Performed by:** Kriya (sole operator)
**References:** `docs/READINESS_MATRIX.md` § 3 Security · Operational Checklist item 1

---

## Why

The earlier secret-leak audit flagged `GOOGLE_API_KEY` in repo history. `.env.example` currently contains the placeholder `your-google-api-key-here`, but the **real** key may still be active and exposed. Burn it.

---

## Prerequisites

- [ ] Owner / Editor role on the GCP project that hosts the key.
- [ ] Browser logged in to <https://console.cloud.google.com>.
- [ ] SSH access to prod: `ubuntu@10.1.0.204` via jump host `15.204.73.232:2222`, key `~/.ssh/openvpn-key-v2.pem`.
- [ ] The current prod `.env` is readable on the prod host at `/opt/raf-intelligence/.env`.

---

## Steps

### 1. Identify the current key in prod

On your laptop:

```bash
ssh -i ~/.ssh/openvpn-key-v2.pem -J ubuntu@15.204.73.232:2222 ubuntu@10.1.0.204 \
  "sudo grep '^GOOGLE_API_KEY=' /opt/raf-intelligence/.env"
```

Expected output:

```
GOOGLE_API_KEY=AIzaSy<...redacted...>
```

Copy the **last 6 chars** somewhere so you can confirm rotation took effect.

### 2. Open the GCP Credentials page

Navigate to <https://console.cloud.google.com/apis/credentials> in the project that owns the key.

You should see a row labelled **API key 1** (or similar) whose value ends with the chars you copied in step 1.

### 3. Create the replacement key

1. Click **+ CREATE CREDENTIALS** → **API key**.
2. In the resulting dialog click **RESTRICT KEY**.
3. Under **API restrictions** select **Restrict key** and tick **only** the APIs RAF actually uses (e.g. *Maps JavaScript API*, *Places API* — whichever the codebase calls).
4. Under **Application restrictions** pick **HTTP referrers** and add:
    - `https://raf.comercioit.com/*`
    - `https://*.comercioit.com/*`
5. Click **SAVE**. Copy the new key string.

Expected: a new row appears in the Credentials list with today's date and a green tick.

### 4. Write the new key to prod `.env`

SSH to prod and edit:

```bash
ssh -i ~/.ssh/openvpn-key-v2.pem -J ubuntu@15.204.73.232:2222 ubuntu@10.1.0.204
sudo cp /opt/raf-intelligence/.env /opt/raf-intelligence/.env.bak.$(date +%Y%m%d-%H%M%S)
sudo sed -i.bak "s|^GOOGLE_API_KEY=.*|GOOGLE_API_KEY=PASTE_NEW_KEY_HERE|" /opt/raf-intelligence/.env
sudo grep '^GOOGLE_API_KEY=' /opt/raf-intelligence/.env
```

Expected: the grep prints the **new** key (different last-6 chars from step 1).

### 5. Restart the backend so the new env is read

Still on prod:

```bash
cd /opt/raf-intelligence
sudo docker compose restart backend
sudo docker compose ps backend
```

Expected: `STATUS` column shows `Up <N> seconds (healthy)`.

### 6. Delete the OLD key in GCP

Back in <https://console.cloud.google.com/apis/credentials> → click the **old** key row → **DELETE** → confirm.

Expected: the old row vanishes. The new key remains as the sole active key.

---

## Verification

### A. App still works with the new key

From your laptop:

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://raf.comercioit.com/healthz
```

Expected: `200`.

Then load any page in the app that uses the Google API (Maps / geocoding / Places autocomplete) and confirm it renders without console errors.

### B. Old key is fully revoked

```bash
curl -s "https://maps.googleapis.com/maps/api/geocode/json?address=test&key=OLD_KEY_VALUE" | head -c 400
```

Expected: a JSON body containing `"error_message": "The provided API key is invalid"` or `REQUEST_DENIED`.

### C. No code path still hard-codes the old key

```bash
git grep -nE 'AIza[0-9A-Za-z_-]{35}' || echo "clean"
git log -p --all -S 'AIzaSy' | head -50
```

Expected: `clean` on the first command. If the second command surfaces a historical commit containing the old key, note it for a future `git filter-repo` purge — but **do not** rewrite history live during this runbook.

---

## Rollback

If the new key breaks production (e.g. the API restriction list was wrong):

1. Re-create a temporary unrestricted key in GCP (same procedure as step 3 but skip the restrictions).
2. SSH to prod, restore `.env`:

   ```bash
   sudo cp /opt/raf-intelligence/.env.bak.<timestamp> /opt/raf-intelligence/.env
   sudo docker compose restart backend
   ```

3. Investigate which API restriction was missing and re-do step 3 correctly.
4. Then delete the temporary unrestricted key.

**Never** un-revoke the original exposed key — it must stay dead.

---

## Sign-off

- [ ] Old key returns `REQUEST_DENIED` (Verification B).
- [ ] App renders Google-powered UI without console errors (Verification A).
- [ ] `git grep` shows no hardcoded `AIza…` strings (Verification C).
- [ ] `/opt/raf-intelligence/.env.bak.<timestamp>` exists on prod for 7-day rollback window.

Record completion date and the new key's last-6 chars in your password manager. Do **not** commit the key anywhere.
