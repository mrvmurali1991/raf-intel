/**
 * auth.ts — Shared authentication helpers for E2E tests.
 *
 * Exports:
 *   loginAs(page, role)  — log in using a named role (admin | coder | physician)
 *   loginAsAdmin(page)   — convenience alias
 *   logout(page)         — sign out and wait for /login
 *   getAuthToken(page)   — read the bearer token from localStorage
 */

import { type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Canonical seeded credentials
// ---------------------------------------------------------------------------

export const CREDENTIALS = {
  admin: { email: "admin@raf.health", password: "Admin@123" },
  coder: { email: "coder@raf.health", password: "Admin@123" },
  physician: { email: "physician@raf.health", password: "Admin@123" },
} as const;

export type UserRole = keyof typeof CREDENTIALS;

// ---------------------------------------------------------------------------
// Core helpers
// ---------------------------------------------------------------------------

/**
 * Log in as the given role. Waits for redirect away from /login, then
 * suppresses the onboarding wizard so it never blocks subsequent assertions.
 */
export async function loginAs(page: Page, role: UserRole = "admin"): Promise<void> {
  const { email, password } = CREDENTIALS[role];

  await page.goto("/login");
  await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 15_000 });

  await page.fill('input[type="email"]', email);
  await page.fill('input[type="password"]', password);
  await page.click('button[type="submit"]');

  await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 30_000 });
  await page.evaluate(() => localStorage.setItem("raf_onboarding_complete", "true"));
}

/** Convenience alias — logs in as the canonical admin. */
export async function loginAsAdmin(page: Page): Promise<void> {
  await loginAs(page, "admin");
}

/**
 * Click the sign-out control (any common selector) and wait for redirect.
 */
export async function logout(page: Page): Promise<void> {
  const selectors = [
    '[aria-label="Sign out"]',
    '[data-testid="logout"]',
    'button:has-text("Sign out")',
    'button:has-text("Logout")',
  ];
  for (const sel of selectors) {
    const el = page.locator(sel).first();
    if (await el.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await el.click();
      break;
    }
  }
  await page.waitForURL(/\/login/, { timeout: 15_000 });
}

/**
 * Read the bearer token that the app stores in localStorage after login.
 * Returns undefined when no token is present.
 */
export async function getAuthToken(page: Page): Promise<string | undefined> {
  return page.evaluate(() => {
    return (
      localStorage.getItem("access_token") ??
      localStorage.getItem("token") ??
      sessionStorage.getItem("access_token") ??
      sessionStorage.getItem("token") ??
      undefined
    );
  });
}
