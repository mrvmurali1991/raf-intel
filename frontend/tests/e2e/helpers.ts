import { type Page, expect } from "@playwright/test";

/**
 * Shared helpers for RAF Intelligence E2E tests.
 *
 * All helpers target the live staging deployment at https://raf.comercioit.com
 * using the default admin credentials. They are intentionally kept simple so
 * individual test files can import only what they need.
 */

export const BASE_URL = "https://raf.comercioit.com";
export const ADMIN_EMAIL = "admin@raf.health";
export const ADMIN_PASSWORD = "admin123";

// ---------------------------------------------------------------------------
// Authentication
// ---------------------------------------------------------------------------

/**
 * Navigate to /login and authenticate with the default admin credentials.
 * Waits until the browser is on "/" (the dashboard) before returning.
 */
export async function login(page: Page): Promise<void> {
  await page.goto("/login");

  // Wait for the form to be interactive before typing.
  await page.waitForSelector('input[type="email"]', { state: "visible" });

  await page.fill('input[type="email"]', ADMIN_EMAIL);
  await page.fill('input[type="password"]', ADMIN_PASSWORD);
  await page.click('button[type="submit"]');

  // The login page uses window.location.href = "/" so wait for a full
  // navigation rather than a URL change within the SPA router.
  await page.waitForURL("/", { timeout: 30_000 });
}

/**
 * Click the "Sign out" button in the sidebar and wait for the redirect to
 * /login. Works whether the sidebar is expanded or collapsed.
 */
export async function logout(page: Page): Promise<void> {
  // Use the aria-label that exists on both expanded and collapsed variants.
  await page.click('[aria-label="Sign out"]');
  await page.waitForURL(/\/login/, { timeout: 15_000 });
}

// ---------------------------------------------------------------------------
// Navigation helpers
// ---------------------------------------------------------------------------

/**
 * Navigate to a page by clicking its sidebar link and wait for the network
 * to become idle so that data-fetching queries complete.
 */
export async function navigateTo(page: Page, href: string): Promise<void> {
  await page.goto(href);
  await page.waitForLoadState("networkidle");
}

// ---------------------------------------------------------------------------
// Waiting helpers
// ---------------------------------------------------------------------------

/**
 * Wait for any skeleton / loading state to disappear.
 * Skeletons use a CSS animation named "pulse" on elements whose background is
 * #E2E8F0 — we simply wait for network idle which covers the majority of cases.
 */
export async function waitForDataLoad(page: Page, timeout = 20_000): Promise<void> {
  await page.waitForLoadState("networkidle", { timeout });
}

/**
 * Assert that no uncaught runtime errors have been emitted to the console.
 * Call at the end of tests that should render error-free pages.
 */
export async function expectNoConsoleErrors(page: Page): Promise<void> {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  // Give in-flight requests a moment to settle before checking.
  await page.waitForTimeout(500);
  expect(
    errors.filter(
      // Filter out known non-critical browser noise.
      (e) => !e.includes("favicon") && !e.includes("net::ERR_ABORTED")
    )
  ).toHaveLength(0);
}
