/**
 * Global setup for the live demo run.
 *
 * Runs ONCE before any test, ahead of the projects' ``use.storageState``
 * resolving.  Logs in via the API, captures cookies + localStorage, and
 * writes them to ``.demo-auth-state.json`` so every scene's page fixture
 * can hydrate that state without re-logging in.
 *
 * Why this matters:
 *   - The auth rate-limiter locks the admin account after 5 fresh
 *     UI logins.  The demo has 7 scenes — fresh-login-per-scene
 *     reliably trips the lock halfway through.
 *   - The auth-context's access token is in-memory only.  Page reloads
 *     trigger a /api/auth/refresh via the httpOnly cookie that lives
 *     in the saved storageState — that's what keeps every scene
 *     authenticated.
 */
import { chromium, type FullConfig } from "@playwright/test";
import * as path from "path";
import * as fs from "fs";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3444";
const API_URL = process.env.API_URL ?? "http://localhost:8500";
const EMAIL = process.env.DEMO_EMAIL ?? "admin@raf.health";
const PASSWORD = process.env.DEMO_PASSWORD ?? "Admin@123";
const STATE_FILE = path.resolve(__dirname, ".demo-auth-state.json");

function writeEmptyState(): void {
  // Pre-create the file so the projects' ``storageState`` reference
  // resolves cleanly even if the API login below fails.  Playwright
  // accepts the empty shape and treats it as "no cookies / no origins".
  fs.mkdirSync(path.dirname(STATE_FILE), { recursive: true });
  fs.writeFileSync(STATE_FILE, JSON.stringify({ cookies: [], origins: [] }));
}

export default async function globalSetup(_config: FullConfig): Promise<void> {
  writeEmptyState();

  const browser = await chromium.launch();
  const context = await browser.newContext();

  // Try API login first (faster, no rate-limit on UI flow).
  let loggedIn = false;
  try {
    const resp = await context.request.post(`${API_URL}/api/auth/login`, {
      data: { email: EMAIL, password: PASSWORD },
    });
    if (resp.ok()) {
      // The httpOnly refresh cookie is now set on this context.
      // Hit /api/auth/me once to keep the cookie warm.
      await context.request.get(`${API_URL}/api/auth/me`);
      loggedIn = true;
      // eslint-disable-next-line no-console
      console.log(`  [demo-setup] API login OK (${EMAIL})`);
    } else {
      // eslint-disable-next-line no-console
      console.log(
        `  [demo-setup] API login returned ${resp.status()}, falling back to UI`,
      );
    }
  } catch (e) {
    // eslint-disable-next-line no-console
    console.log(`  [demo-setup] API login error: ${(e as Error).message}`);
  }

  // API login set the refresh cookie on the context.  Save the state
  // immediately — the cookies are already in the right place.  We
  // intentionally do NOT navigate a page here: the React login form
  // detaches its inputs on hydrate (defeats fill / pressSequentially)
  // and the / route's auth-context redirect-dance can fail if any
  // dependent endpoint is degraded.

  await context.storageState({ path: STATE_FILE });
  await browser.close();
  // eslint-disable-next-line no-console
  console.log(`  [demo-setup] api-login=${loggedIn}; auth cached → ${STATE_FILE}`);
}
