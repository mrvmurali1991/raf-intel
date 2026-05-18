/**
 * v28-impact.spec.ts
 *
 * Tests for /v28-impact — V28 transition impact dashboard.
 *
 * Scenarios:
 *   - Page loads with at least one h2 KPI tile.
 *   - Histogram has an aria-label (accessible chart).
 *   - At 1024 px width the layout renders a 2-column grid.
 *   - No critical axe violations.
 */

import { test, expect } from "@playwright/test";
import { loginAsAdmin, assertNoA11yViolations } from "./helpers/auth";

test.describe("/v28-impact — V28 transition impact", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/v28-impact");
    await page.waitForLoadState("networkidle");
  });

  test("page loads with KPI tiles using h2 headings", async ({ page }) => {
    const h2s = page.locator("h2");
    await expect(h2s.first()).toBeVisible({ timeout: 15_000 });
    const h2Count = await h2s.count();
    expect(h2Count).toBeGreaterThanOrEqual(1);
  });

  test("histogram chart has aria-label attribute", async ({ page }) => {
    // Charts are rendered as SVG, canvas, or a div with role='img'.
    const chart = page.locator(
      "svg[aria-label], canvas[aria-label], [role='img'][aria-label], [aria-label*='histogram' i], [aria-label*='chart' i], [aria-label*='distribution' i]"
    ).first();

    if (await chart.isVisible({ timeout: 10_000 }).catch(() => false)) {
      const label = await chart.getAttribute("aria-label");
      expect(label).toBeTruthy();
    } else {
      // Chart may be wrapped — look for any aria-labelled element inside a chart container.
      const chartContainer = page.locator("[aria-label]").filter({ has: page.locator("svg, canvas") }).first();
      const label = await chartContainer.getAttribute("aria-label").catch(() => null);
      expect(label, "Expected a chart aria-label on the page").toBeTruthy();
    }
  });

  test("responsive layout at 1024px renders 2-column grid", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 768 });
    await page.waitForLoadState("networkidle");

    // Grid containers with 2-col class (Tailwind md:grid-cols-2 or explicit CSS grid).
    const gridCells = page.locator(
      "[class*='grid-cols-2'] > *, [class*='col-span'], [class*='grid'] > [class*='col']"
    );

    const cellCount = await gridCells.count();
    // At 1024px we expect at least 2 grid siblings.
    expect(cellCount).toBeGreaterThanOrEqual(2);
  });

  test("no critical axe violations", async ({ page }) => {
    await assertNoA11yViolations(page);
  });
});
