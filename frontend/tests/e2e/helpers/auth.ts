/**
 * auth.ts — Shared authentication helpers for E2E tests.
 *
 * All helpers target the base URL configured in playwright.config.ts
 * (https://raf.comercioit.com by default, overridable via E2E_BASE_URL).
 */

import { type Page, expect } from "@playwright/test";

export const ADMIN_EMAIL = "admin@raf.health";
export const ADMIN_PASSWORD = "Admin@123";

/**
 * Perform a full login flow with arbitrary credentials.
 * Asserts the browser lands on "/" after successful authentication.
 */
export async function loginAs(
  page: Page,
  email: string,
  password: string
): Promise<void> {
  await page.goto("/login");
  await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 15_000 });

  await page.fill('input[type="email"]', email);
  await page.fill('input[type="password"]', password);
  await page.click('button[type="submit"]');

  // Handle full-page navigation (window.location.href = "/")
  await page.waitForURL((url) => !url.pathname.includes("/login"), {
    timeout: 30_000,
  });

  // Suppress the first-run onboarding wizard so it never blocks tests.
  await page.evaluate(() =>
    localStorage.setItem("raf_onboarding_complete", "true")
  );
}

/**
 * Convenience wrapper — logs in as the canonical admin user.
 */
export async function loginAsAdmin(page: Page): Promise<void> {
  await loginAs(page, ADMIN_EMAIL, ADMIN_PASSWORD);
}

/**
 * Click the "Sign out" control and wait for redirect to /login.
 */
export async function logout(page: Page): Promise<void> {
  await page.click('[aria-label="Sign out"]');
  await page.waitForURL(/\/login/, { timeout: 15_000 });
}

/**
 * Inject axe-core from CDN into the current page and run an audit.
 * Returns the AxeResults object so callers can assert on violations.
 *
 * Skipped violation categories:
 *   - color-contrast  (checked separately via Storybook / VRT pipeline)
 *
 * Asserted violations (zero tolerance):
 *   - heading-order
 *   - label
 *   - duplicate-id
 */
export async function runAxeAudit(
  page: Page
): Promise<{ violations: Array<{ id: string; description: string }> }> {
  // Inject axe-core via CDN if not already present.
  const axeInjected = await page.evaluate(() => typeof (window as unknown as Record<string, unknown>)["axe"] !== "undefined");
  if (!axeInjected) {
    await page.addScriptTag({
      url: "https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.9.1/axe.min.js",
    });
  }

  const results = await page.evaluate(async () => {
    const axe = (window as unknown as Record<string, unknown>)["axe"] as {
      run: (el: Document, opts: Record<string, unknown>) => Promise<{ violations: Array<{ id: string; description: string }> }>;
    };
    return axe.run(document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa"] },
      rules: { "color-contrast": { enabled: false } },
    });
  }) as { violations: Array<{ id: string; description: string }> };

  return results;
}

/**
 * Assert that no heading-order, label, or duplicate-id violations exist.
 */
export async function assertNoA11yViolations(page: Page): Promise<void> {
  const results = await runAxeAudit(page);
  const criticalIds = new Set(["heading-order", "label", "duplicate-id"]);
  const critical = results.violations.filter((v) => criticalIds.has(v.id));
  expect(
    critical,
    `Axe violations: ${critical.map((v) => `${v.id}: ${v.description}`).join(", ")}`
  ).toHaveLength(0);
}
