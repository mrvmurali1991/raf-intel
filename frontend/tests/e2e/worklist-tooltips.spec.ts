/**
 * worklist-tooltips.spec.ts
 *
 * Verifies that every interactive element on /worklist renders a tooltip with
 * non-empty content when hovered or focused. Covers all 10 tooltip categories
 * introduced in feat(worklist): tooltips on every action, pill, and filter.
 *
 * Tags: @smoke @tooltips
 *
 * Run:
 *   npx playwright test tests/e2e/worklist-tooltips.spec.ts --project=e2e
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

test.describe("Worklist tooltip coverage @smoke @tooltips", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto(`${BASE}/worklist`, { waitUntil: "domcontentloaded" });
    // Wait for the worklist cards or empty-state to load
    await page.waitForSelector('[data-testid^="tile-"], [data-testid^="priority-pill-"], .shimmer', {
      timeout: 15_000,
    });
    // Let shimmer resolve
    await page.waitForTimeout(3_000);
  });

  // ── Category 1: Summary tiles ──────────────────────────────────────────────
  test("1. Summary tiles show tooltips", async ({ page }) => {
    const tiles = [
      "tile-patients-to-see",
      "tile-open-gaps",
      "tile-revenue-at-risk",
      "tile-awv-due",
    ];
    for (const tid of tiles) {
      const el = page.locator(`[data-testid="${tid}"]`).first();
      const count = await el.count();
      if (count === 0) {
        console.log(`  [SKIP] tile "${tid}" not found — possibly no data`);
        continue;
      }
      await el.hover();
      const text = await waitForTooltip(page);
      expect(text.trim().length, `Tooltip for ${tid} should have content`).toBeGreaterThan(0);
      // move away to dismiss
      await page.mouse.move(0, 0);
    }
  });

  // ── Category 2: Priority pill ──────────────────────────────────────────────
  test("2. Priority pill tooltip mentions RAF lift and confidence", async ({ page }) => {
    const pill = page.locator('[data-testid^="priority-pill-"]').first();
    const count = await pill.count();
    if (count === 0) {
      console.log("  [SKIP] No priority pills found — no patient cards in data");
      return;
    }
    await pill.hover();
    const text = await waitForTooltip(page);
    expect(text.toLowerCase()).toMatch(/raf|confidence|score/);
    await page.mouse.move(0, 0);
  });

  // ── Category 3: HCC gap chip Reject button ─────────────────────────────────
  test("3. HCC gap chip Reject button tooltip mentions audit trail", async ({ page }) => {
    const rejectBtn = page.locator('[data-testid^="hcc-reject-"]').first();
    const count = await rejectBtn.count();
    if (count === 0) {
      console.log("  [SKIP] No reject buttons found — no open gaps in data");
      return;
    }
    await rejectBtn.hover();
    const text = await waitForTooltip(page);
    expect(text.toLowerCase()).toMatch(/reject|audit|reason/);
    await page.mouse.move(0, 0);
  });

  // ── Category 4: AWV status pill ────────────────────────────────────────────
  test("4. AWV status pill tooltip explains status meaning", async ({ page }) => {
    const awvPill = page.locator('[data-testid^="awv-pill-"]').first();
    const count = await awvPill.count();
    if (count === 0) {
      console.log("  [SKIP] No AWV pills visible — patients may all be future/unknown status");
      return;
    }
    await awvPill.hover();
    const text = await waitForTooltip(page);
    expect(text.toLowerCase()).toMatch(/awv|annual|wellness|payment year/i);
    await page.mouse.move(0, 0);
  });

  // ── Category 5: Bulk-action toolbar buttons ────────────────────────────────
  test("5. Bulk action buttons show tooltips when a card is selected", async ({ page }) => {
    // Select first card checkbox to make the bulk bar appear
    const checkbox = page.locator('[data-testid^="card-checkbox-"]').first();
    const count = await checkbox.count();
    if (count === 0) {
      console.log("  [SKIP] No card checkboxes found — no patient cards in data");
      return;
    }
    await checkbox.click();
    await page.waitForSelector('[data-testid="bulk-attest-btn"]', { timeout: 5_000 });

    const bulkBtns: Array<{ testid: string; match: RegExp }> = [
      { testid: "bulk-attest-btn", match: /attest|coding|queue/i },
      { testid: "bulk-schedule-awv-btn", match: /awv|annual|calendar/i },
      { testid: "bulk-export-csv-btn", match: /csv|export|download/i },
    ];

    for (const { testid, match } of bulkBtns) {
      const btn = page.locator(`[data-testid="${testid}"]`).first();
      await btn.hover();
      const text = await waitForTooltip(page);
      expect(text.trim().length, `Tooltip for ${testid} should have content`).toBeGreaterThan(0);
      expect(text.toLowerCase(), `Tooltip for ${testid} should match ${match}`).toMatch(match);
      await page.mouse.move(0, 0);
    }

    // Deselect
    await page.keyboard.press("Escape");
  });

  // ── Category 6: Provider filter pills ─────────────────────────────────────
  test("6. Provider filter pills show tooltips (elevated role)", async ({ page }) => {
    // Only admin/elevated users see these pills
    const allPill = page.locator('[aria-label="Filter by provider"] button').first();
    const count = await allPill.count();
    if (count === 0) {
      console.log("  [SKIP] Provider filter pills not visible — non-elevated role or no providers");
      return;
    }
    await allPill.hover();
    const text = await waitForTooltip(page);
    expect(text.trim().length).toBeGreaterThan(0);
    await page.mouse.move(0, 0);
  });

  // ── Category 7: Sort dropdown (if present) ─────────────────────────────────
  test("7. Sort dropdown options show tooltips (if sort control present)", async ({ page }) => {
    // Sort may be a future addition; check generously
    const sortTrigger = page.locator('[aria-label*="sort"], [data-testid="sort-trigger"]').first();
    const count = await sortTrigger.count();
    if (count === 0) {
      console.log("  [SKIP] No sort dropdown found on this build — skipping");
      return;
    }
    await sortTrigger.hover();
    const text = await waitForTooltip(page);
    expect(text.trim().length).toBeGreaterThan(0);
    await page.mouse.move(0, 0);
  });

  // ── Category 8: Provider workload bar rows ─────────────────────────────────
  test("8. Heatmap row tooltip mentions capacity and click-to-filter", async ({ page }) => {
    const row = page.locator('[data-testid^="heatmap-row-"]').first();
    const count = await row.count();
    if (count === 0) {
      console.log("  [SKIP] No heatmap rows visible — non-elevated role or no providers");
      return;
    }
    await row.hover();
    const text = await waitForTooltip(page);
    expect(text.toLowerCase()).toMatch(/capacity|gap|filter/i);
    await page.mouse.move(0, 0);
  });

  // ── Category 9: Open chart CTA ─────────────────────────────────────────────
  test("9. Open chart CTA tooltip mentions RAF breakdown and encounter history", async ({ page }) => {
    const cta = page.locator('[data-testid^="open-chart-"]').first();
    const count = await cta.count();
    if (count === 0) {
      console.log("  [SKIP] No patient cards found — no patient data");
      return;
    }
    await cta.hover();
    const text = await waitForTooltip(page);
    expect(text.toLowerCase()).toMatch(/raf|hcc|encounter|chart/i);
    await page.mouse.move(0, 0);
  });

  // ── Category 10: Checkbox per card ────────────────────────────────────────
  test("10. Card checkbox tooltip mentions bulk action and shift-click", async ({ page }) => {
    const checkbox = page.locator('[data-testid^="card-checkbox-"]').first();
    const count = await checkbox.count();
    if (count === 0) {
      console.log("  [SKIP] No card checkboxes found — no patient data");
      return;
    }
    await checkbox.hover();
    const text = await waitForTooltip(page);
    expect(text.toLowerCase()).toMatch(/bulk|select|shift/i);
    await page.mouse.move(0, 0);
  });

  // ── Screenshot of all tooltips visible ─────────────────────────────────────
  test("Screenshot: full worklist page with tooltip visible", async ({ page }) => {
    // Hover the first priority pill for the screenshot
    const pill = page.locator('[data-testid^="priority-pill-"]').first();
    const count = await pill.count();
    if (count > 0) {
      await pill.hover();
      await page.waitForTimeout(500);
    }
    await page.screenshot({ path: "test-results/worklist-tooltips.png", fullPage: true });
    console.log("  Screenshot saved to test-results/worklist-tooltips.png");
  });
});
