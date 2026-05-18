/**
 * help-panel.spec.ts
 *
 * Verifies the contextual `?` help button and slide-out panel on every
 * major page.  For each route:
 *   1. Navigate to the page (authenticated as admin).
 *   2. Click the `[data-testid="help-button"]`.
 *   3. Assert the help panel opens and contains non-empty text.
 *
 * Also verifies the `?` keyboard shortcut opens the panel.
 *
 * Tags: @smoke  (runs in CI by default)
 *
 * @smoke
 */

import { test, expect, type Page } from "@playwright/test";
import { loginAsAdmin } from "./helpers/auth";

// ---------------------------------------------------------------------------
// Routes to verify
// ---------------------------------------------------------------------------

const ROUTES = [
  { path: "/",         label: "Dashboard" },
  { path: "/worklist", label: "Worklist" },
  { path: "/recapture", label: "Recapture Gaps" },
  { path: "/suspects", label: "Suspect HCCs" },
  { path: "/v28-impact", label: "V28 Impact" },
  { path: "/radv",     label: "RADV" },
  { path: "/audit",    label: "Audit" },
  { path: "/goals",    label: "Goals" },
  { path: "/reports",  label: "Reports" },
  { path: "/patients", label: "Patients" },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function openHelpPanel(page: Page): Promise<void> {
  const btn = page.locator('[data-testid="help-button"]').first();
  await expect(btn).toBeVisible({ timeout: 15_000 });
  await btn.click();
  await expect(page.locator('[data-testid="help-panel"]')).toBeVisible({ timeout: 8_000 });
}

async function assertPanelHasContent(page: Page): Promise<void> {
  const panel = page.locator('[data-testid="help-panel"]');
  // At minimum the panel should contain more than 50 chars of visible text
  const text = await panel.innerText();
  expect(text.trim().length).toBeGreaterThan(50);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Help panel @smoke", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  for (const { path, label } of ROUTES) {
    test(`${label} (${path}) — ? button opens panel with content`, async ({ page }) => {
      await page.goto(path);
      // Wait for page to settle — data loading is not required, just the header
      await page.waitForLoadState("domcontentloaded");
      // Give Next.js client components time to hydrate
      await page.waitForTimeout(1_500);

      await openHelpPanel(page);
      await assertPanelHasContent(page);

      // Panel close works
      const closeBtn = page.locator('[data-testid="help-panel"] button[aria-label="Close help panel"]');
      await closeBtn.click();
      await expect(page.locator('[data-testid="help-panel"]')).not.toBeVisible({ timeout: 5_000 });
    });
  }

  test("? keyboard shortcut opens help panel", async ({ page }) => {
    await page.goto("/worklist");
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(1_500);

    // Ensure no input is focused so the shortcut fires
    await page.click("body");
    await page.keyboard.press("?");

    // Either the help panel or the keyboard shortcuts overlay should open
    const panelVisible = await page.locator('[data-testid="help-panel"]').isVisible({ timeout: 5_000 }).catch(() => false);
    const overlayVisible = await page.locator('[data-testid="shortcut-help-overlay"]').isVisible({ timeout: 5_000 }).catch(() => false);
    expect(panelVisible || overlayVisible).toBeTruthy();
  });

  test("Dashboard help panel screenshot", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("domcontentloaded");
    await page.waitForTimeout(2_000);

    await openHelpPanel(page);
    await assertPanelHasContent(page);

    // Screenshot the open panel for visual reference
    await page.screenshot({
      path: "test-results/help-panel-dashboard.png",
      fullPage: false,
    });
  });
});
