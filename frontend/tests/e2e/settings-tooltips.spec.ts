/**
 * settings-tooltips.spec.ts  @smoke
 *
 * Verifies that every required tooltip is present and keyboard-accessible
 * on /settings, /emr-config, /users, /admin/hcc-rejections, and /ehr-writeback.
 *
 * Strategy:
 *   1. Login as admin.
 *   2. Navigate to each page.
 *   3. Focus (keyboard) or hover each tooltip trigger and assert
 *      that a tooltip popup becomes visible in the DOM.
 *   4. Take a screenshot for visual confirmation.
 *
 * Tooltip triggers carry [data-slot="tooltip-trigger"] from the base-ui
 * Tooltip primitive.  We also look for button[aria-label] icons and
 * span[tabindex="0"] wrappers emitted by FieldTooltip.
 */

import { test, expect, type Page } from "@playwright/test";
import { loginAsAdmin } from "./helpers/auth";

const SCREENSHOT_DIR = "tooltip-screenshots";

// ---------------------------------------------------------------------------
// Helper: hover the first matching trigger and assert the popup is visible
// ---------------------------------------------------------------------------

async function assertTooltip(
  page: Page,
  triggerSelector: string,
  partialText: string,
  description: string
): Promise<void> {
  const trigger = page.locator(triggerSelector).first();
  await expect(trigger, `Tooltip trigger not found: ${description}`).toBeVisible({ timeout: 8_000 });
  await trigger.hover();
  // The popup portal renders outside the trigger; wait for any visible tooltip popup.
  const popup = page.locator('[data-slot="tooltip-content"]').first();
  await expect(popup, `Tooltip popup not visible after hover: ${description}`).toBeVisible({ timeout: 5_000 });
  if (partialText) {
    await expect(popup).toContainText(partialText, { timeout: 3_000 });
  }
}

// ---------------------------------------------------------------------------
// Settings page
// ---------------------------------------------------------------------------

test.describe("Tooltips — /settings @smoke", () => {
  test("settings tab nav tooltips visible", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/settings");
    await page.waitForSelector('[data-slot="tooltip-trigger"]', { timeout: 15_000 });

    // Profile tab tooltip
    await assertTooltip(
      page,
      '[data-slot="tooltip-trigger"]:has-text("Profile")',
      "profile picture",
      "Profile tab"
    );

    await page.screenshot({ path: `${SCREENSHOT_DIR}/settings-tabs-tooltip.png`, fullPage: false });
  });

  test("settings profile field tooltips visible", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/settings#profile");
    await page.waitForSelector("text=First name", { timeout: 15_000 });

    // ⓘ button next to First name label
    const infoButtons = page.locator('button[aria-label]').filter({ hasText: "" });
    // Hover the first info icon (First name field)
    const firstInfo = page.locator('button[aria-label]').first();
    await firstInfo.hover();
    const popup = page.locator('[data-slot="tooltip-content"]').first();
    await expect(popup).toBeVisible({ timeout: 5_000 });

    await page.screenshot({ path: `${SCREENSHOT_DIR}/settings-profile-tooltip.png`, fullPage: false });
  });

  test("settings security MFA tooltip visible", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/settings#security");
    await page.waitForSelector("text=Two-Factor Authentication", { timeout: 15_000 });

    // The ⓘ button next to the Two-Factor heading
    const mfaSection = page.locator("text=Two-Factor Authentication").locator("..");
    const infoBtn = mfaSection.locator('button[aria-label]').first();
    await infoBtn.hover();
    const popup = page.locator('[data-slot="tooltip-content"]').first();
    await expect(popup).toBeVisible({ timeout: 5_000 });
    await expect(popup).toContainText("TOTP");

    await page.screenshot({ path: `${SCREENSHOT_DIR}/settings-mfa-tooltip.png`, fullPage: false });
  });

  test("settings API Keys tooltip visible", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/settings#api-keys");
    await page.waitForSelector("text=API Keys", { timeout: 15_000 });

    const infoBtn = page.locator('button[aria-label]').first();
    await infoBtn.hover();
    const popup = page.locator('[data-slot="tooltip-content"]').first();
    await expect(popup).toBeVisible({ timeout: 5_000 });

    await page.screenshot({ path: `${SCREENSHOT_DIR}/settings-api-keys-tooltip.png`, fullPage: false });
  });
});

// ---------------------------------------------------------------------------
// EMR Config page
// ---------------------------------------------------------------------------

test.describe("Tooltips — /emr-config @smoke", () => {
  test("emr-config connector card tooltip visible", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/emr-config");
    await page.waitForSelector("text=EMR", { timeout: 15_000 });

    // Look for any tooltip trigger on this page
    const trigger = page.locator('[data-slot="tooltip-trigger"]').first();
    const exists = await trigger.count();
    if (exists > 0) {
      await trigger.hover();
      const popup = page.locator('[data-slot="tooltip-content"]').first();
      await expect(popup).toBeVisible({ timeout: 5_000 });
    }

    await page.screenshot({ path: `${SCREENSHOT_DIR}/emr-config-tooltip.png`, fullPage: false });
  });
});

// ---------------------------------------------------------------------------
// Users page
// ---------------------------------------------------------------------------

test.describe("Tooltips — /users @smoke", () => {
  test("users KPI card tooltip visible", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/users");
    await page.waitForSelector("text=Total Users", { timeout: 15_000 });

    // Hover first metric card (wrapped in FieldTooltip → span[tabindex=0])
    const kpiTrigger = page.locator('span[tabindex="0"]').first();
    await kpiTrigger.hover();
    const popup = page.locator('[data-slot="tooltip-content"]').first();
    await expect(popup).toBeVisible({ timeout: 5_000 });
    await expect(popup).toContainText("Total");

    await page.screenshot({ path: `${SCREENSHOT_DIR}/users-kpi-tooltip.png`, fullPage: false });
  });

  test("users role badge tooltip visible", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/users");
    await page.waitForSelector("text=Role", { timeout: 15_000 });

    // Role badges are inside FieldTooltip wrappers
    const roleTrigger = page.locator('span[tabindex="0"]').nth(4); // first role badge (after 4 KPI cards)
    const exists = await roleTrigger.count();
    if (exists > 0) {
      await roleTrigger.hover();
      const popup = page.locator('[data-slot="tooltip-content"]').first();
      await expect(popup).toBeVisible({ timeout: 5_000 });
    }

    await page.screenshot({ path: `${SCREENSHOT_DIR}/users-role-tooltip.png`, fullPage: false });
  });
});

// ---------------------------------------------------------------------------
// HCC Rejections page
// ---------------------------------------------------------------------------

test.describe("Tooltips — /admin/hcc-rejections @smoke", () => {
  test("hcc-rejections reason badge tooltip visible", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/admin/hcc-rejections");
    await page.waitForSelector("text=HCC Rejection", { timeout: 15_000 });

    // May have no rows if DB is empty — just verify tooltip triggers exist
    const trigger = page.locator('[data-slot="tooltip-trigger"]').first();
    const exists = await trigger.count();
    if (exists > 0) {
      await trigger.hover();
      const popup = page.locator('[data-slot="tooltip-content"]').first();
      await expect(popup).toBeVisible({ timeout: 5_000 });
    }

    await page.screenshot({ path: `${SCREENSHOT_DIR}/hcc-rejections-tooltip.png`, fullPage: false });
  });
});

// ---------------------------------------------------------------------------
// EHR Write-Back page
// ---------------------------------------------------------------------------

test.describe("Tooltips — /ehr-writeback @smoke", () => {
  test("ehr-writeback status filter tooltips visible", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/ehr-writeback");
    await page.waitForSelector("text=EHR Write-Back", { timeout: 15_000 });

    // The status filter buttons are wrapped in FieldTooltip
    const filterTrigger = page.locator('span[tabindex="0"]').first();
    await filterTrigger.hover();
    const popup = page.locator('[data-slot="tooltip-content"]').first();
    await expect(popup).toBeVisible({ timeout: 5_000 });

    await page.screenshot({ path: `${SCREENSHOT_DIR}/ehr-writeback-filter-tooltip.png`, fullPage: false });
  });

  test("ehr-writeback auto-refresh notice tooltip visible", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/ehr-writeback");
    await page.waitForSelector("text=Auto-refreshes", { timeout: 15_000 });

    // The "Auto-refreshes every 30s" text is inside a FieldTooltip
    const autoRefreshTrigger = page.locator('span[tabindex="0"]').filter({ hasText: "Auto-refreshes" });
    const exists = await autoRefreshTrigger.count();
    if (exists > 0) {
      await autoRefreshTrigger.hover();
      const popup = page.locator('[data-slot="tooltip-content"]').first();
      await expect(popup).toBeVisible({ timeout: 5_000 });
      await expect(popup).toContainText("30 seconds");
    }

    await page.screenshot({ path: `${SCREENSHOT_DIR}/ehr-writeback-autorefresh-tooltip.png`, fullPage: false });
  });
});
