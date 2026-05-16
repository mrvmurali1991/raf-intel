import { chromium, type FullConfig } from "@playwright/test";
import { LOCAL_BASE_URL, ADMIN_EMAIL, ADMIN_PASSWORD } from "./utils";
import path from "path";
import fs from "fs";

export const STORAGE_STATE_PATH = path.join(__dirname, ".auth-state.json");

/**
 * Global setup: log in once and save the browser storage state.
 * All visual tests reuse this state, avoiding repeated login round-trips
 * and the auth-race flakiness that comes with per-test login.
 */
export default async function globalSetup(_config: FullConfig): Promise<void> {
  const browser = await chromium.launch();
  const page = await browser.newPage();

  await page.goto(`${LOCAL_BASE_URL}/login`);
  await page.waitForSelector('input[type="email"]', { state: "visible" });
  await page.fill('input[type="email"]', ADMIN_EMAIL);
  await page.fill('input[type="password"]', ADMIN_PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), {
    timeout: 30_000,
  });
  await page.waitForLoadState("networkidle");

  // Persist cookies + localStorage so tests skip the login step entirely.
  const dir = path.dirname(STORAGE_STATE_PATH);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  await page.context().storageState({ path: STORAGE_STATE_PATH });

  await browser.close();
}
