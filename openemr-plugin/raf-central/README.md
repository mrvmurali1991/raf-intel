# RAF Central — OpenEMR plugin

Drop-in launcher that surfaces the RAF Intelligence "RAF Central" unified
panel inside the OpenEMR patient chart. The provider never leaves OpenEMR
and never re-enters credentials — a short-lived HMAC-signed JWT is minted
server-side and exchanged for a scoped RAF session on iframe load.

## What ships in this folder

| File | Purpose |
| ---- | ------- |
| `cog_launcher.php` | The endpoint OpenEMR embeds. Mints an embed JWT from `RAF_EMBED_SECRET` and renders an iframe pointing at `/embed/raf-central/:pid?t=...` on the RAF frontend. |
| `inject_cog_button.js` | Optional userscript that adds a floating "RAF Central" button to the patient chart and toggles a right-hand iframe overlay. |
| `README.md` | This file. |

## Backend configuration (RAF side)

Set one new variable on the RAF backend and restart the API:

```bash
OPENEMR_EMBED_SECRET=<generate a long random string>
OPENEMR_EMBED_DEFAULT_TENANT_ID=<optional — only for single-tenant demos>
EMBED_ACCESS_TOKEN_EXPIRE_MINUTES=30   # default is fine
```

The embed exchange endpoint is `POST /api/auth/embed/exchange` and it is
rate-limited to 30/minute per IP. Successful exchanges are audit-logged
under the action `embed_exchange_success`.

## OpenEMR-side configuration

1. **Install the plugin folder**
   ```bash
   cp -r openemr-plugin/raf-central \
     /var/www/localhost/htdocs/openemr/interface/modules/
   ```

2. **Configure the shared secret and frontend URL.** Administration → Globals
   → Miscellaneous → "Custom Globals" (or a site-specific config file):
   ```
   RAF_EMBED_SECRET  = (match the value you set on the RAF backend)
   RAF_FRONTEND_URL  = https://raf.example.com
   RAF_USER_EMAIL    = provider1@example.com   # RAF user the iframe impersonates
   RAF_TENANT_ID     = demo-tenant              # optional, single-tenant only
   ```

3. **Wire the button** into the patient summary page. Pick one:
   - **Userscript**: paste `inject_cog_button.js` into Administration →
     Globals → Custom Scripts → "Patient Summary Custom Script". The button
     appears on every chart.
   - **Template include**: copy the userscript to
     `interface/patient_file/summary/js/raf-central.js` and reference it
     from `demographics.php` before `</body>`:
     ```php
     <script src="js/raf-central.js"></script>
     ```

## Launch URL

Direct URL for testing without the userscript:

```
https://openemr.example.com/interface/modules/raf-central/cog_launcher.php?pid=12345
```

The launcher will:
1. Verify the OpenEMR session is authenticated (same-origin require).
2. Read `RAF_EMBED_SECRET` + `RAF_USER_EMAIL` from globals.
3. Mint a JWT with `{ sub: RAF_USER_EMAIL, pid, exp: now+5min, type: "embed" }`.
4. Render an iframe: `RAF_FRONTEND_URL/embed/raf-central/{pid}?t={jwt}`.

The iframe's `/embed/raf-central/{pid}` route POSTs the token once to
`/api/auth/embed/exchange`, stores the returned access token in memory, and
renders the full RAF Central panel. Every inline action inside the panel
(accept suspect, dismiss, push MEAT, add problem, etc.) is authenticated
through the RAF API exactly as it is in the standalone app — there is no
second integration surface.

## Security checklist

- [x] Shared secret is HS256-signed, not a symmetric password exchange.
- [x] Token TTL ≤ 10 minutes (default 5). Clock skew tolerance = JWT default.
- [x] `type: embed` claim is enforced server-side; access/refresh tokens
      cannot be presented here.
- [x] RAF backend refuses the exchange if the token's `tenant_id` does not
      match the target user's tenant.
- [x] Refresh cookie is `HttpOnly; Secure; SameSite=None` in production so
      cross-origin iframe refresh works without leaking the cookie to JS.
- [x] Every embed launch is audit-logged on both sides (OpenEMR SystemLogger
      and RAF `audit_log`).

## Rolling the secret

1. Generate a new random string and set `OPENEMR_EMBED_SECRET` on the RAF
   backend first. Redeploy.
2. Update `RAF_EMBED_SECRET` in OpenEMR globals.
3. In-flight iframe sessions (≤30 min) survive the roll because they already
   hold a full access token; only new exchanges require the new secret.
