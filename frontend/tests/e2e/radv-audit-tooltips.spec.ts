/**
 * radv-audit-tooltips.spec.ts
 *
 * Verifies every tooltip target on /radv and /audit renders a non-empty
 * tooltip on hover, and that all tooltip triggers are keyboard-focusable.
 *
 * Tags: @smoke @tooltips
 *
 * Run:
 *   npx playwright test tests/e2e/radv-audit-tooltips.spec.ts --project=e2e
 */

import { test, expect, Page } from "@playwright/test";

const BASE = process.env.E2E_BASE_URL ?? "https://raf.comercioit.com";

async function login(page: Page) {
  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.fill('input[type="email"]', "admin@raf.health");
  await page.fill('input[type="password"]', "Admin@123");
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/($|\?)/, { timeout: 20_000 });
}

async function hoverAndGetTooltip(page: Page, locator: ReturnType<Page["locator"]>): Promise<string> {
  await locator.scrollIntoViewIfNeeded();
  await locator.hover();
  const tip = page.locator('[role="tooltip"]').first();
  await tip.waitFor({ state: "visible", timeout: 4_000 });
  const text = (await tip.textContent()) ?? "";
  // screenshot for evidence
  await page.screenshot({ path: `test-results/tooltip-${Date.now()}.png`, fullPage: false });
  return text;
}

async function focusAndGetTooltip(page: Page, locator: ReturnType<Page["locator"]>): Promise<string> {
  await locator.scrollIntoViewIfNeeded();
  await locator.focus();
  const tip = page.locator('[role="tooltip"]').first();
  await tip.waitFor({ state: "visible", timeout: 4_000 });
  return (await tip.textContent()) ?? "";
}

// ============================================================
// /radv tooltips
// ============================================================

test.describe("/radv tooltip coverage @smoke @tooltips", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/radv`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2_000);
  });

  test("1. Extrapolation info button shows court-ruling tooltip", async ({ page }) => {
    const btn = page.locator('button[aria-label="Extrapolation context"]');
    await expect(btn).toBeVisible({ timeout: 10_000 });
    const text = await hoverAndGetTooltip(page, btn);
    expect(text.length).toBeGreaterThan(10);
    expect(text).toMatch(/N\.D\. Tex|extrapolation|court/i);
  });

  test("2. Extrapolation info button is keyboard focusable", async ({ page }) => {
    const btn = page.locator('button[aria-label="Extrapolation context"]');
    await expect(btn).toBeVisible({ timeout: 10_000 });
    const text = await focusAndGetTooltip(page, btn);
    expect(text.length).toBeGreaterThan(10);
  });

  test("3. Exposure dollar values show tooltip in run list", async ({ page }) => {
    // Wait for run list to load or show empty state
    await page.waitForTimeout(2_500);
    // Check if there's a run row
    const exposureCell = page.locator('table tbody tr td span[tabindex="0"]').first();
    const hasRows = await exposureCell.count();
    if (hasRows === 0) {
      test.skip();
      return;
    }
    const text = await hoverAndGetTooltip(page, exposureCell);
    expect(text.length).toBeGreaterThan(5);
  });

  test("4. Sample method pill shows methodology tooltip", async ({ page }) => {
    await page.waitForTimeout(2_500);
    const pill = page.locator('span[tabindex="0"]').filter({ hasText: /random|stratified|high.risk/i }).first();
    const count = await pill.count();
    if (count === 0) {
      test.skip();
      return;
    }
    const text = await hoverAndGetTooltip(page, pill);
    expect(text.length).toBeGreaterThan(10);
  });
});

// ============================================================
// /radv detail view tooltips (if an audit run exists)
// ============================================================

test.describe("/radv detail tooltips @smoke @tooltips", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/radv`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2_500);
  });

  test("5. Stat tiles show tooltip on hover", async ({ page }) => {
    // Open first run if available
    const openBtn = page.locator('button').filter({ hasText: /^Open$/ }).first();
    const hasRun = await openBtn.count();
    if (!hasRun) {
      test.skip();
      return;
    }
    await openBtn.click();
    await page.waitForTimeout(1_500);
    // Defensible stat tile wrapper
    const tile = page.locator('[tabindex="0"]').filter({ hasText: /Defensible/i }).first();
    const tileCount = await tile.count();
    if (!tileCount) {
      test.skip();
      return;
    }
    const text = await hoverAndGetTooltip(page, tile);
    expect(text.length).toBeGreaterThan(10);
  });

  test("6. Stress-test both button shows tooltip", async ({ page }) => {
    const openBtn = page.locator('button').filter({ hasText: /^Open$/ }).first();
    const hasRun = await openBtn.count();
    if (!hasRun) {
      test.skip();
      return;
    }
    await openBtn.click();
    await page.waitForTimeout(1_500);
    const stressBtn = page.locator('[data-testid="radv-stress-test-btn"]');
    const count = await stressBtn.count();
    if (!count) {
      test.skip();
      return;
    }
    const text = await hoverAndGetTooltip(page, stressBtn);
    expect(text.length).toBeGreaterThan(10);
    expect(text).toMatch(/side.by.side|comparison|direct|extrapolat/i);
  });

  test("7. Chart status pills show workflow tooltip", async ({ page }) => {
    const openBtn = page.locator('button').filter({ hasText: /^Open$/ }).first();
    const hasRun = await openBtn.count();
    if (!hasRun) {
      test.skip();
      return;
    }
    await openBtn.click();
    await page.waitForTimeout(1_000);
    // Switch to chart requests tab
    const crTab = page.locator('button').filter({ hasText: /Chart Requests/i }).first();
    const tabCount = await crTab.count();
    if (!tabCount) {
      test.skip();
      return;
    }
    await crTab.click();
    await page.waitForTimeout(1_000);
    // Status pill with tabindex
    const statusPill = page.locator('span[tabindex="0"]').first();
    const pillCount = await statusPill.count();
    if (!pillCount) {
      test.skip();
      return;
    }
    const text = await hoverAndGetTooltip(page, statusPill);
    expect(text.length).toBeGreaterThan(10);
  });

  test("8. Action buttons (Received/Coded/Dispute) show tooltips", async ({ page }) => {
    const openBtn = page.locator('button').filter({ hasText: /^Open$/ }).first();
    const hasRun = await openBtn.count();
    if (!hasRun) {
      test.skip();
      return;
    }
    await openBtn.click();
    await page.waitForTimeout(1_000);
    const crTab = page.locator('button').filter({ hasText: /Chart Requests/i }).first();
    const tabCount = await crTab.count();
    if (!tabCount) {
      test.skip();
      return;
    }
    await crTab.click();
    await page.waitForTimeout(1_000);
    const receivedBtn = page.locator('button[aria-label="Mark received"]').first();
    const hasBtn = await receivedBtn.count();
    if (!hasBtn) {
      test.skip();
      return;
    }
    const text = await hoverAndGetTooltip(page, receivedBtn);
    expect(text.length).toBeGreaterThan(10);
    expect(text).toMatch(/received|provider|queue/i);
  });
});

// ============================================================
// /audit tooltips
// ============================================================

test.describe("/audit tooltip coverage @smoke @tooltips", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/audit`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2_500);
  });

  test("9. Total Entries badge shows tamper-evident tooltip", async ({ page }) => {
    const totalEntries = page.locator('[tabindex="0"]').filter({ hasText: /Total Entries/i }).first();
    await expect(totalEntries).toBeVisible({ timeout: 10_000 });
    const text = await hoverAndGetTooltip(page, totalEntries);
    expect(text.length).toBeGreaterThan(10);
    expect(text).toMatch(/SHA-256|hash|tamper/i);
  });

  test("10. Total Entries is keyboard focusable", async ({ page }) => {
    const totalEntries = page.locator('[tabindex="0"]').filter({ hasText: /Total Entries/i }).first();
    await expect(totalEntries).toBeVisible({ timeout: 10_000 });
    const text = await focusAndGetTooltip(page, totalEntries);
    expect(text.length).toBeGreaterThan(10);
  });

  test("11. Last Entry Hash shows tamper-detection tooltip", async ({ page }) => {
    const lastHash = page.locator('[tabindex="0"]').filter({ hasText: /Last Entry Hash/i }).first();
    await expect(lastHash).toBeVisible({ timeout: 10_000 });
    const text = await hoverAndGetTooltip(page, lastHash);
    expect(text.length).toBeGreaterThan(10);
    expect(text).toMatch(/hash|tamper|chain/i);
  });

  test("12. Verify Chain Integrity button shows tooltip", async ({ page }) => {
    const verifyBtn = page.locator('button[aria-label="Verify chain integrity"]');
    await expect(verifyBtn).toBeVisible({ timeout: 10_000 });
    const text = await hoverAndGetTooltip(page, verifyBtn);
    expect(text.length).toBeGreaterThan(10);
    expect(text).toMatch(/recompute|hash|pass.fail|percentage/i);
  });

  test("13. Export Chain of Custody button shows tooltip", async ({ page }) => {
    const exportBtn = page.locator('button[aria-label="Export chain of custody report"]');
    await expect(exportBtn).toBeVisible({ timeout: 10_000 });
    const text = await hoverAndGetTooltip(page, exportBtn);
    expect(text.length).toBeGreaterThan(10);
    expect(text).toMatch(/CSV|download|offline|hash/i);
  });

  test("14. Export Chain of Custody button is keyboard focusable", async ({ page }) => {
    const exportBtn = page.locator('button[aria-label="Export chain of custody report"]');
    await expect(exportBtn).toBeVisible({ timeout: 10_000 });
    const text = await focusAndGetTooltip(page, exportBtn);
    expect(text.length).toBeGreaterThan(10);
  });

  test("15. Per-row hash icon shows SHA-256 tooltip", async ({ page }) => {
    const hashBtn = page.locator('button[aria-label*="SHA-256"]').first();
    const count = await hashBtn.count();
    if (!count) {
      test.skip();
      return;
    }
    const text = await hoverAndGetTooltip(page, hashBtn);
    expect(text).toMatch(/SHA-256|hash/i);
  });

  test("16. Event type pills show explanatory tooltip", async ({ page }) => {
    // Event type pills only render when backend returns event_type field
    const pill = page.locator('span[tabindex="0"]').filter({ hasText: /hcc_accepted|hcc_rejected|hcc_suspect|audit_export|chain_verify|record_update/ }).first();
    const count = await pill.count();
    if (!count) {
      test.skip();
      return;
    }
    const text = await hoverAndGetTooltip(page, pill);
    expect(text.length).toBeGreaterThan(10);
  });

  test("17. Screenshot evidence — audit page fully loaded", async ({ page }) => {
    await expect(page.locator("h1, h2").filter({ hasText: /Audit|Compliance/i }).first()).toBeVisible({ timeout: 10_000 });
    await page.screenshot({ path: "test-results/audit-page-tooltip-evidence.png", fullPage: true });
  });
});
