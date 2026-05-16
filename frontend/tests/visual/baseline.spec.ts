import { test, expect } from "@playwright/test";
import { LOCAL_BASE_URL, hideVolatileElements } from "./utils";

/**
 * Visual Regression Baseline Tests
 *
 * Auth is pre-loaded via storageState (see global-setup.ts + playwright.config.ts visual project).
 * Run with --update-snapshots to regenerate baselines after intentional UI changes.
 */

const SCREENSHOT_OPTS = {
  maxDiffPixels: 200,
  fullPage: true,
} as const;

test.describe("Visual Regression Baselines", () => {
  test("home dashboard", async ({ page }) => {
    await page.goto(`${LOCAL_BASE_URL}/`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
    await hideVolatileElements(page);
    await expect(page).toHaveScreenshot("home.png", SCREENSHOT_OPTS);
  });

  test("patients list", async ({ page }) => {
    await page.goto(`${LOCAL_BASE_URL}/patients`);
    await page.waitForLoadState("networkidle");
    await hideVolatileElements(page);
    await expect(page).toHaveScreenshot("patients.png", SCREENSHOT_OPTS);
  });

  test("patients list — 1024px tablet view", async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 768 });
    await page.goto(`${LOCAL_BASE_URL}/patients`);
    await page.waitForLoadState("networkidle");
    await hideVolatileElements(page);
    await expect(page).toHaveScreenshot("patients-tablet.png", SCREENSHOT_OPTS);
  });

  test("review queue", async ({ page }) => {
    await page.goto(`${LOCAL_BASE_URL}/review-queue`);
    await page.waitForLoadState("networkidle");
    await hideVolatileElements(page);
    await expect(page).toHaveScreenshot("review-queue.png", SCREENSHOT_OPTS);
  });

  test("recapture", async ({ page }) => {
    await page.goto(`${LOCAL_BASE_URL}/recapture`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(800);
    await hideVolatileElements(page);
    await expect(page).toHaveScreenshot("recapture.png", SCREENSHOT_OPTS);
  });

  test("analysis", async ({ page }) => {
    await page.goto(`${LOCAL_BASE_URL}/analysis`);
    await page.waitForLoadState("networkidle");
    await hideVolatileElements(page);
    await expect(page).toHaveScreenshot("analysis.png", SCREENSHOT_OPTS);
  });
});
