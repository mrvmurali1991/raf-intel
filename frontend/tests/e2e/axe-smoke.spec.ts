/**
 * WCAG 2.1 AA smoke test using axe-core.
 *
 * Runs accessibility scans on a handful of public pages and asserts that
 * no serious/critical violations are present. We deliberately skip when
 * the `CI` environment variable is unset so local runs without the
 * `@axe-core/playwright` dependency installed don't break existing flows.
 *
 * To run locally:
 *   npm install
 *   CI=true npx playwright test tests/e2e/axe-smoke.spec.ts
 */
import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// Guard: only run when CI=true so unconfigured local devs aren't broken.
const shouldRun = !!process.env.CI;

test.describe("WCAG 2.1 AA — axe-core smoke", () => {
  test.skip(!shouldRun, "Set CI=true to run axe accessibility scan (requires @axe-core/playwright)");

  // Only treat serious + critical violations as test failures. Minor and
  // moderate findings are tracked separately via Storybook a11y addon.
  const FAIL_IMPACTS = new Set(["serious", "critical"]);

  test("/login has no serious/critical a11y violations", async ({ page }) => {
    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();

    const serious = results.violations.filter((v: { impact?: string | null }) => FAIL_IMPACTS.has(v.impact ?? ""));
    expect(serious, JSON.stringify(serious, null, 2)).toHaveLength(0);
  });

  test("/login with invalid email focused has no serious/critical a11y violations", async ({ page }) => {
    await page.goto("/login");
    await page.waitForLoadState("networkidle");

    // Best-effort focus on the email input. Some forms use name="username".
    const emailInput = page.locator('input[type="email"], input[name="email"], input[name="username"]').first();
    if (await emailInput.count()) {
      await emailInput.focus();
      await emailInput.fill("not-an-email");
      await emailInput.blur();
    }

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();

    const serious = results.violations.filter((v: { impact?: string | null }) => FAIL_IMPACTS.has(v.impact ?? ""));
    expect(serious, JSON.stringify(serious, null, 2)).toHaveLength(0);
  });

  test("404 page has no serious/critical a11y violations", async ({ page }) => {
    // Next.js renders the not-found page for any unknown route.
    const response = await page.goto("/__definitely_not_a_real_page__");
    // 404 status is expected; we still scan the rendered markup.
    if (response) {
      expect([404, 200]).toContain(response.status());
    }
    await page.waitForLoadState("networkidle");

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();

    const serious = results.violations.filter((v: { impact?: string | null }) => FAIL_IMPACTS.has(v.impact ?? ""));
    expect(serious, JSON.stringify(serious, null, 2)).toHaveLength(0);
  });
});
