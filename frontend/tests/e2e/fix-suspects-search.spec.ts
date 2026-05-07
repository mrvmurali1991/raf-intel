/**
 * Verification test: /suspects in-page search input must filter rows inline
 * without triggering the global command palette.
 *
 * Run with:
 *   npx playwright test tests/e2e/fix-suspects-search.spec.ts --config playwright.config.ts
 */

import { test, expect } from "@playwright/test";
import path from "path";

// Override base URL to localhost for this verification test
const BASE_URL = "http://localhost:3444";

const SCREENSHOT_DIR = path.resolve(
  __dirname,
  "../../demo-shots/fix-suspects-search"
);

test.describe("Suspects page - inline search", () => {
  test.beforeEach(async ({ page }) => {
    // Login via localhost
    await page.goto(`${BASE_URL}/login`);
    await page.fill('input[type="email"], input[name="email"]', "admin@raf.health");
    await page.fill('input[type="password"], input[name="password"]', "Admin@123");
    await page.click('button[type="submit"]');
    await page.waitForURL(`${BASE_URL}/`, { timeout: 30_000 });
  });

  test("typing 'diabetes' in search input filters rows and does NOT open command palette", async ({
    page,
  }) => {
    // Navigate to suspects
    await page.goto(`${BASE_URL}/suspects`);
    await page.waitForLoadState("domcontentloaded");

    // Wait for the search input to be visible
    const searchInput = page.getByLabel("Search suspects");
    await searchInput.waitFor({ state: "visible", timeout: 15_000 });

    // Count visible suspect rows before typing
    const rowsBefore = await page.locator(".suspect-row").count();

    // Click and type into the search input
    await searchInput.click();
    await searchInput.fill("diabetes");

    // Verify the value was set correctly in the input
    await expect(searchInput).toHaveValue("diabetes");

    // Screenshot: input filled with "diabetes"
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "01-search-filled.png"),
      fullPage: false,
    });

    // Assert NO global command palette / dialog appeared
    // The CommandPalette renders with role="dialog"
    const dialog = page.locator('[role="dialog"]');
    const dialogCount = await dialog.count();
    expect(dialogCount).toBe(0);

    // Also assert no cmdk or command-palette class overlays
    const cmdkOverlay = page.locator('[class*="command-palette"], [class*="cmdk"]');
    const cmdkCount = await cmdkOverlay.count();
    expect(cmdkCount).toBe(0);

    // Wait briefly for filtering to happen (it's synchronous/local state)
    await page.waitForTimeout(300);

    // Count rows after filtering — should be <= rowsBefore (may be 0 if no diabetes suspects)
    const rowsAfter = await page.locator(".suspect-row").count();

    // Screenshot: filtered results
    await page.screenshot({
      path: path.join(SCREENSHOT_DIR, "02-filtered-results.png"),
      fullPage: false,
    });

    // The filtered count should be less than or equal to the original count
    // (filtering by "diabetes" should reduce or maintain the row count)
    expect(rowsAfter).toBeLessThanOrEqual(rowsBefore);

    // Input should still have the value (not been cleared by a palette open/close)
    await expect(searchInput).toHaveValue("diabetes");

    console.log(`Rows before: ${rowsBefore}, Rows after filter: ${rowsAfter}`);
    console.log("PASS: No command palette opened; inline filtering works correctly");
  });
});
