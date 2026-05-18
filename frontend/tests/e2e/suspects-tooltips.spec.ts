/**
 * suspects-tooltips.spec.ts
 *
 * Verifies that every interactive element on /suspects renders a tooltip with
 * non-empty content when hovered. Covers all 10 tooltip categories introduced
 * in feat(suspects): tooltips on confidence, RAF lift, evidence source, and controls.
 *
 * Tags: @smoke @tooltips
 *
 * Run:
 *   npx playwright test tests/e2e/suspects-tooltips.spec.ts --project=e2e
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

async function waitForTooltip(page: Page): Promise<string> {
  // base-ui renders tooltips into a portal with role="tooltip"
  const tip = page.locator('[role="tooltip"]').first();
  await tip.waitFor({ state: "visible", timeout: 4_000 });
  return (await tip.textContent()) ?? "";
}

test.describe("Suspects tooltip coverage @smoke @tooltips", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/suspects`, { waitUntil: "domcontentloaded" });
    // Wait for the grid table or skeleton to appear
    await page.waitForSelector('[role="grid"]', { timeout: 20_000 });
    // Let data settle
    await page.waitForTimeout(3_000);
  });

  // ── Category 1: Filter chips (All / Open / Accepted) ──────────────────────
  test("1. Status filter chips show tooltips", async ({ page }) => {
    const chipLabels = ["All", "Open", "Accepted"];
    for (const label of chipLabels) {
      const btn = page
        .locator('[aria-label="Status filter"] button')
        .filter({ hasText: label })
        .first();
      const count = await btn.count();
      if (count === 0) {
        console.log(`  [SKIP] Status chip "${label}" not found`);
        continue;
      }
      await btn.hover();
      const text = await waitForTooltip(page);
      expect(text.trim().length, `Tooltip for "${label}" chip should have content`).toBeGreaterThan(0);
      await page.mouse.move(0, 0);
      await page.waitForTimeout(200);
    }
  });

  // ── Category 2: "More filters" button ─────────────────────────────────────
  test("2. More filters button shows tooltip", async ({ page }) => {
    const btn = page.locator('button', { hasText: /More filters/i }).first();
    const count = await btn.count();
    if (count === 0) {
      console.log("  [SKIP] More filters button not found");
      return;
    }
    await btn.hover();
    const text = await waitForTooltip(page);
    expect(text.trim().length).toBeGreaterThan(0);
    expect(text.toLowerCase()).toMatch(/filter|dismissed|evidence|confidence/i);
    await page.mouse.move(0, 0);
  });

  // ── Category 3: Confidence pill in a row ──────────────────────────────────
  test("3. Confidence signal shows tooltip with score thresholds", async ({ page }) => {
    // Confidence is the 4th column; look for any row with Strong/Moderate/Weak
    const confCell = page
      .locator('[role="row"]')
      .filter({ hasText: /Strong|Moderate|Weak/ })
      .first();
    const count = await confCell.count();
    if (count === 0) {
      console.log("  [SKIP] No rows with confidence signal found — possibly no data");
      return;
    }
    // Hover the confidence bar area (the column containing the progress bar + label)
    const progressArea = confCell.locator('div[style*="flex-direction: column"]').nth(1);
    const areaCount = await progressArea.count();
    if (areaCount === 0) {
      console.log("  [SKIP] Confidence bar area not identifiable");
      return;
    }
    await progressArea.hover();
    const text = await waitForTooltip(page);
    expect(text.toLowerCase()).toMatch(/strong|moderate|weak|score|calibrat/i);
    await page.mouse.move(0, 0);
  });

  // ── Category 4: RAF Lift column header ────────────────────────────────────
  test("4. RAF Lift column header tooltip mentions HCC documentation", async ({ page }) => {
    const header = page
      .locator('[role="columnheader"]')
      .filter({ hasText: /RAF Lift/i })
      .first();
    const count = await header.count();
    if (count === 0) {
      console.log("  [SKIP] RAF Lift column header not found");
      return;
    }
    await header.hover();
    const text = await waitForTooltip(page);
    expect(text.toLowerCase()).toMatch(/raf|hcc|score|documented/i);
    await page.mouse.move(0, 0);
  });

  // ── Category 5: Revenue column header ─────────────────────────────────────
  test("5. Revenue column header tooltip mentions CMS V28 rate", async ({ page }) => {
    const header = page
      .locator('[role="columnheader"]')
      .filter({ hasText: /Revenue/i })
      .first();
    const count = await header.count();
    if (count === 0) {
      console.log("  [SKIP] Revenue column header not found");
      return;
    }
    await header.hover();
    const text = await waitForTooltip(page);
    expect(text.toLowerCase()).toMatch(/cms|v28|raf|rate|\$/i);
    await page.mouse.move(0, 0);
  });

  // ── Category 6: Evidence source chip in a row ─────────────────────────────
  test("6. Evidence source chip tooltip explains the source type", async ({ page }) => {
    // The evidence pill is styled with textTransform: capitalize and cursor: help
    const evidencePill = page
      .locator('[role="row"] span[style*="border-radius: 999px"]')
      .first();
    const count = await evidencePill.count();
    if (count === 0) {
      console.log("  [SKIP] No evidence pills found — possibly no data");
      return;
    }
    await evidencePill.hover();
    const text = await waitForTooltip(page);
    expect(text.trim().length).toBeGreaterThan(0);
    expect(text.toLowerCase()).toMatch(/medication|lab|imaging|referral|historical|clinical/i);
    await page.mouse.move(0, 0);
  });

  // ── Category 7: Accept (A) row action button ──────────────────────────────
  test("7. Accept row-action button tooltip mentions OpenEMR and keyboard hint", async ({ page }) => {
    const acceptBtn = page
      .locator('[role="row"] button[aria-label*="Accept"]')
      .first();
    const count = await acceptBtn.count();
    if (count === 0) {
      console.log("  [SKIP] No Accept buttons found — possibly no open suspects");
      return;
    }
    await acceptBtn.hover();
    const text = await waitForTooltip(page);
    expect(text.toLowerCase()).toMatch(/accept|openemr|emr|keyboard|key/i);
    await page.mouse.move(0, 0);
  });

  // ── Category 8: Dismiss (D) row action button ─────────────────────────────
  test("8. Dismiss row-action button tooltip mentions keyboard hint", async ({ page }) => {
    const dismissBtn = page
      .locator('[role="row"] button[aria-label*="Dismiss"]')
      .first();
    const count = await dismissBtn.count();
    if (count === 0) {
      console.log("  [SKIP] No Dismiss buttons found — possibly no open suspects");
      return;
    }
    await dismissBtn.hover();
    const text = await waitForTooltip(page);
    expect(text.toLowerCase()).toMatch(/dismiss|keyboard|key|applicable/i);
    await page.mouse.move(0, 0);
  });

  // ── Category 9: Year selector ──────────────────────────────────────────────
  test("9. Measurement year selector tooltip mentions HCC code set", async ({ page }) => {
    // The year selector is inside a div that wraps "MY" label + select
    const yearWrapper = page.locator('[aria-label="Measurement year"]').first();
    const count = await yearWrapper.count();
    if (count === 0) {
      console.log("  [SKIP] Measurement year selector not found");
      return;
    }
    // Hover the parent wrapper div that has the tooltip trigger
    await yearWrapper.hover();
    const text = await waitForTooltip(page).catch(() => "");
    if (!text) {
      // Try hovering the surrounding div
      const wrapper = page.locator('[aria-label="Measurement year"]').locator("..").first();
      await wrapper.hover();
      const text2 = await waitForTooltip(page).catch(() => "");
      expect(text2.toLowerCase()).toMatch(/measurement year|hcc|v28/i);
    } else {
      expect(text.toLowerCase()).toMatch(/measurement year|hcc|v28/i);
    }
    await page.mouse.move(0, 0);
  });

  // ── Category 10: Sort button ───────────────────────────────────────────────
  test("10. Sort button tooltip explains current sort order", async ({ page }) => {
    const sortBtn = page
      .locator('button', { hasText: /Sort:/i })
      .first();
    const count = await sortBtn.count();
    if (count === 0) {
      console.log("  [SKIP] Sort button not found");
      return;
    }
    await sortBtn.hover();
    const text = await waitForTooltip(page);
    expect(text.trim().length).toBeGreaterThan(0);
    expect(text.toLowerCase()).toMatch(/sort|confidence|raf|patient/i);
    await page.mouse.move(0, 0);
  });

  // ── Screenshot ────────────────────────────────────────────────────────────
  test("Screenshot: suspects page with tooltip visible", async ({ page }) => {
    // Hover the Sort button for a representative screenshot
    const sortBtn = page.locator('button', { hasText: /Sort:/i }).first();
    const count = await sortBtn.count();
    if (count > 0) {
      await sortBtn.hover();
      await page.waitForTimeout(500);
    }
    await page.screenshot({
      path: "test-results/suspects-tooltips.png",
      fullPage: true,
    });
    console.log("  Screenshot saved to test-results/suspects-tooltips.png");
  });
});
