/**
 * One-time login at the start of the demo run.
 *
 * Saves the resulting browser storage (cookies + localStorage) to
 * .demo-auth-state.json so each scene reuses the same session instead of
 * hitting the auth rate-limiter with a fresh login per scene.  The admin
 * account locks after 5 consecutive logins; the demo has 7 scenes, so
 * fresh-login-per-scene reliably trips the rate limit halfway through.
 */
import { chromium, type FullConfig } from "@playwright/test";
import * as path from "path";
import * as fs from "fs";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3444";
const EMAIL = process.env.DEMO_EMAIL ?? "admin@raf.health";
const PASSWORD = process.env.DEMO_PASSWORD ?? "Admin@123";
const STATE_FILE = path.resolve(__dirname, ".demo-auth-state.json");

export default async function globalSetup(_config: FullConfig): Promise<void> {
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(`${BASE_URL}/login`);
  await page.waitForSelector('input[type="email"]', { state: "visible" });
  await page.fill('input[type="email"]', EMAIL);
  await page.fill('input[type="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 });
  await context.storageState({ path: STATE_FILE });
  await browser.close();
  // eslint-disable-next-line no-console
  console.log(`  [demo-setup] auth cached at ${STATE_FILE}`);
}

// Clean up the auth state file when the suite is done.
export async function globalTeardown(): Promise<void> {
  if (fs.existsSync(STATE_FILE)) {
    fs.unlinkSync(STATE_FILE);
  }
}
