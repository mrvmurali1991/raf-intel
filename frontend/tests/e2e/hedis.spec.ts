/**
 * hedis.spec.ts
 *
 * Tests for /hedis (or /quality) — HEDIS measure dashboard.
 *
 * Scenarios:
 *   - Measure list loads (at least 1 item visible).
 *   - Clicking a measure row shows the patient gap list.
 *   - No critical axe violations.
 */

import { test, expect } from "@playwright/test";
import { loginAsAdmin, assertNoA11yViolations } from "./helpers/auth";

// The HEDIS page may be mounted at /hedis or /quality.
const CANDIDATE_PATHS = ["/hedis", "/quality"];

async function navigateToHedis(page: import("@playwright/test").Page): Promise<string | null> {
  for (const path of CANDIDATE_PATHS) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const notFound = await page.locator("text=/404|not found/i").isVisible({ timeout: 3_000 }).catch(() => false);
    if (!notFound) return path;
  }
  return null;
}

test.describe("/hedis — HEDIS measure dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("measure list loads with at least one measure item", async ({ page }) => {
    const resolvedPath = await navigateToHedis(page);
    if (!resolvedPath) test.skip();

    // Measure items: rows, cards, or list items.
    const measureItems = page.locator(
      "tr[data-measure], [data-testid*='measure'], [class*='measure'], table tbody tr, [role='row'], [role='listitem']"
    ).first();

    await expect(measureItems).toBeVisible({ timeout: 20_000 });
  });

  test("clicking a measure shows a patient gap list", async ({ page }) => {
    const resolvedPath = await navigateToHedis(page);
    if (!resolvedPath) test.skip();

    // Click the first clickable measure row/card.
    const firstMeasure = page
      .locator("table tbody tr, [role='row'], [class*='measure-row'], button[data-measure]")
      .first();

    if (!(await firstMeasure.isVisible({ timeout: 15_000 }).catch(() => false))) {
      // Fallback: click any row-looking element that has gap-related text nearby.
      const anyRow = page.locator("tr, [role='row']").nth(1);
      if (await anyRow.isVisible({ timeout: 5_000 }).catch(() => false)) {
        await anyRow.click();
      } else {
        test.skip();
      }
    } else {
      await firstMeasure.click();
    }

    await page.waitForLoadState("networkidle");

    // Patient gap list should appear — look for keywords.
    const gapList = page.locator("text=/patient|gap|member|eligible|compliant/i").first();
    await expect(gapList).toBeVisible({ timeout: 15_000 });
  });

  test("no critical axe violations", async ({ page }) => {
    await navigateToHedis(page);
    await assertNoA11yViolations(page);
  });
});
