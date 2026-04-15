/**
 * global-setup.ts
 *
 * Performs login once and saves the auth state (cookies + localStorage) to
 * e2e/.auth/user.json.  All other E2E specs depend on this setup project so
 * they start already authenticated.
 *
 * Environment:
 *   PLAYWRIGHT_BASE_URL  — frontend URL (default http://localhost:3001)
 *   TEST_USERNAME        — login email (default admin@raf.health)
 *   TEST_PASSWORD        — login password (default Admin@123)
 */

import { test as setup, expect } from "@playwright/test";
import path from "path";

const AUTH_FILE = path.join(__dirname, ".auth/user.json");

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL || "http://localhost:3001";
const USERNAME = process.env.TEST_USERNAME || "admin@raf.health";
const PASSWORD = process.env.TEST_PASSWORD || "Admin@123";

setup("authenticate", async ({ page }) => {
  await page.goto(`${BASE_URL}/login`);

  // Fill in credentials
  await page.getByLabel(/email/i).fill(USERNAME);
  await page.getByLabel(/password/i).fill(PASSWORD);

  // Submit
  await page.getByRole("button", { name: /sign in|login/i }).click();

  // Wait until we're redirected away from /login (dashboard or patient list)
  await expect(page).not.toHaveURL(/\/login/, { timeout: 15_000 });

  // Save auth state for all other tests
  await page.context().storageState({ path: AUTH_FILE });
});
