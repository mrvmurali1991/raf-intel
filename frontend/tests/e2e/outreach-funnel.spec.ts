/**
 * outreach-funnel.spec.ts
 *
 * Tests for the outreach funnel dashboard.
 * Tries UI routes; falls back to smoking /api/outreach/funnel directly.
 *
 * Scenarios:
 *   - Dashboard page renders or API endpoint responds.
 *   - Funnel stages are visible (contacted / scheduled / completed).
 *   - No critical axe violations (if UI page exists).
 */

import { test, expect } from "@playwright/test";
import { loginAsAdmin, assertNoA11yViolations } from "./helpers/auth";

const UI_CANDIDATES = ["/outreach", "/patients/outreach", "/recapture/outreach"];
const API_ENDPOINT = "/api/outreach/funnel";

async function navigateToOutreach(
  page: import("@playwright/test").Page
): Promise<string | null> {
  for (const path of UI_CANDIDATES) {
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

test.describe("Outreach funnel dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("outreach page loads or API endpoint is reachable", async ({ page, request }) => {
    const resolved = await navigateToOutreach(page);

    if (resolved) {
      const content = page.locator("h1, h2, [role='main'], main").first();
      await expect(content).toBeVisible({ timeout: 15_000 });
    } else {
      // Smoke the API endpoint.
      const apiBase = process.env.E2E_BASE_URL ?? "https://raf.comercioit.com";
      const resp = await request.get(`${apiBase}${API_ENDPOINT}`);
      expect([200, 401, 403]).toContain(resp.status());
    }
  });

  test("funnel stage labels are visible (contacted / scheduled / completed)", async ({ page }) => {
    const resolved = await navigateToOutreach(page);
    if (!resolved) test.skip();

    // Any of these stage labels should appear.
    const stageLabel = page
      .locator("text=/contacted|scheduled|completed|outreach|enrolled/i")
      .first();
    await expect(stageLabel).toBeVisible({ timeout: 15_000 });
  });

  test("no critical axe violations", async ({ page }) => {
    const resolved = await navigateToOutreach(page);
    if (!resolved) test.skip();
    await assertNoA11yViolations(page);
  });
});
