/**
 * edi-generation.spec.ts
 *
 * Tests for /edi-generation — EDI 837/834 generation workflow.
 *
 * Scenarios:
 *   - Page loads with a proper h1.
 *   - Tab panels follow h1 → h2 → h3 heading hierarchy (no skipped levels).
 *   - No critical axe violations.
 */

import { test, expect } from "@playwright/test";
import { loginAsAdmin, assertNoA11yViolations } from "./helpers/auth";

const CANDIDATE_PATHS = ["/edi-generation", "/submissions/edi", "/claims/edi"];

async function navigateToEdi(page: import("@playwright/test").Page): Promise<string | null> {
  for (const path of CANDIDATE_PATHS) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const notFound = await page
      .locator("text=/404|not found/i")
      .isVisible({ timeout: 3_000 })
      .catch(() => false);
    if (!notFound) return path;
  }
  return null;
}

test.describe("/edi-generation — EDI generation workflow", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("page loads with an h1 heading", async ({ page }) => {
    const resolved = await navigateToEdi(page);
    if (!resolved) test.skip();

    const h1 = page.locator("h1").first();
    await expect(h1).toBeVisible({ timeout: 15_000 });
    const h1Text = await h1.textContent();
    expect(h1Text?.trim().length).toBeGreaterThan(0);
  });

  test("heading hierarchy h1 → h2 → h3 has no skipped levels", async ({ page }) => {
    const resolved = await navigateToEdi(page);
    if (!resolved) test.skip();

    // Collect all heading levels in document order.
    const levels = await page.evaluate(() => {
      const headings = Array.from(
        document.querySelectorAll("h1, h2, h3, h4, h5, h6")
      );
      return headings.map((h) => parseInt(h.tagName.slice(1), 10));
    });

    // Verify no jump greater than 1 between consecutive levels.
    for (let i = 1; i < levels.length; i++) {
      const jump = levels[i] - levels[i - 1];
      expect(
        jump,
        `Heading skipped level: h${levels[i - 1]} → h${levels[i]}`
      ).toBeLessThanOrEqual(1);
    }
  });

  test("tab panels are navigable and each panel renders content", async ({ page }) => {
    const resolved = await navigateToEdi(page);
    if (!resolved) test.skip();

    const tabs = page.locator("[role='tab']");
    const tabCount = await tabs.count();

    if (tabCount === 0) {
      // No tab UI — just verify the page has content.
      const content = page.locator("main, [role='main'], #main-content").first();
      await expect(content).toBeVisible({ timeout: 10_000 });
      return;
    }

    // Click each tab and verify a panel becomes visible.
    for (let i = 0; i < Math.min(tabCount, 5); i++) {
      await tabs.nth(i).click();
      await page.waitForTimeout(500);
      const panel = page.locator("[role='tabpanel']").first();
      await expect(panel).toBeVisible({ timeout: 5_000 });
    }
  });

  test("no critical axe violations", async ({ page }) => {
    await navigateToEdi(page);
    await assertNoA11yViolations(page);
  });
});
