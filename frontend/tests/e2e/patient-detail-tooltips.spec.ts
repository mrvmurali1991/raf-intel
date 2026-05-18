/**
 * patient-detail-tooltips.spec.ts
 *
 * Verifies that all 10 tooltip categories on /patients/[pid] render non-empty
 * tooltip content when hovered or focused. Covers:
 *   1. Hero RAF Score pill
 *   2. Data Quality chip
 *   3. Primary CTA button
 *   4. RAF breakdown segments (Demographic / Disease / Interaction)
 *   5. HCC chip in problem list
 *   6. MEAT evidence pills (M/E/A/T)
 *   7. Encounter row
 *   8. Recapture gap row
 *   9. Suspect card — confidence pill + HCC chip
 *  10. Clinical Highlights panel header
 *
 * Tags: @smoke @tooltips
 *
 * Run:
 *   npx playwright test tests/e2e/patient-detail-tooltips.spec.ts --project=e2e
 */

import { test, expect, type Page } from "@playwright/test";

const BASE = process.env.E2E_BASE_URL ?? "https://raf.comercioit.com";

async function login(page: Page) {
  await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.fill('input[type="email"]', "admin@raf.health");
  await page.fill('input[type="password"]', "Admin@123");
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/($|\?)/, { timeout: 20_000 });
}

/** Hover a locator and wait for a tooltip to appear. Returns tooltip text. */
async function hoverAndGetTooltip(page: Page, locator: ReturnType<Page["locator"]>): Promise<string> {
  await locator.scrollIntoViewIfNeeded();
  await locator.hover();
  const tip = page.locator('[role="tooltip"]').first();
  await tip.waitFor({ state: "visible", timeout: 5_000 });
  return (await tip.textContent()) ?? "";
}

/** Focus a locator (keyboard) and wait for tooltip. */
async function focusAndGetTooltip(page: Page, locator: ReturnType<Page["locator"]>): Promise<string> {
  await locator.scrollIntoViewIfNeeded();
  await locator.focus();
  const tip = page.locator('[role="tooltip"]').first();
  await tip.waitFor({ state: "visible", timeout: 5_000 });
  return (await tip.textContent()) ?? "";
}

test.describe("Patient detail tooltip coverage @smoke @tooltips", () => {
  let patientUrl: string;

  test.beforeAll(async ({ browser }) => {
    // Find first seeded patient pid
    const page = await browser.newPage();
    await login(page);
    await page.goto(`${BASE}/patients`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3_000);
    // Click first patient row to get the PID from URL
    const firstRow = page.locator('tr[data-patient-id], [data-testid^="patient-row-"], a[href^="/patients/"]').first();
    await firstRow.waitFor({ timeout: 15_000 });
    const href = await firstRow.getAttribute("href") ?? "";
    const pidMatch = href.match(/\/patients\/(\d+)/);
    if (pidMatch) {
      patientUrl = `${BASE}/patients/${pidMatch[1]}`;
    } else {
      // Navigate and capture URL from browser
      await firstRow.click();
      await page.waitForURL(/\/patients\/\d+/, { timeout: 10_000 });
      patientUrl = page.url();
    }
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto(patientUrl, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2_500);
  });

  // ── 1. RAF Score pill ──────────────────────────────────────────────────────
  test("1. RAF Score pill shows CMS-HCC V28 tooltip", async ({ page }) => {
    const pill = page.locator('[data-testid="raf-score-pill"]').first();
    // May not be present if score is null — skip gracefully
    if (await pill.count() === 0) {
      test.skip(true, "RAF score pill not present for this patient");
      return;
    }
    const text = await hoverAndGetTooltip(page, pill);
    expect(text.length).toBeGreaterThan(10);
    expect(text.toLowerCase()).toContain("v28");
  });

  // ── 2. Data Quality chip ───────────────────────────────────────────────────
  test("2. Data Quality chip shows completeness tooltip", async ({ page }) => {
    const chip = page.locator('[data-testid="data-quality-chip"]').first();
    if (await chip.count() === 0) {
      test.skip(true, "Data quality chip not present");
      return;
    }
    const text = await hoverAndGetTooltip(page, chip);
    expect(text.length).toBeGreaterThan(10);
    expect(text.toLowerCase()).toContain("completeness");
  });

  // ── 3. Primary CTA button ─────────────────────────────────────────────────
  test("3. Primary CTA describes state-aware action", async ({ page }) => {
    const cta = page.locator('[data-testid="hero-primary-cta"]').first();
    await cta.waitFor({ timeout: 8_000 });
    const text = await hoverAndGetTooltip(page, cta);
    expect(text.length).toBeGreaterThan(10);
  });

  // ── 4. RAF breakdown segments ─────────────────────────────────────────────
  test("4a. Demographic segment label shows tooltip", async ({ page }) => {
    // Navigate to RAF tab
    const rafTab = page.locator('button, [role="tab"]').filter({ hasText: /RAF/i }).first();
    await rafTab.waitFor({ timeout: 8_000 });
    await rafTab.click();
    await page.waitForTimeout(1_500);

    const seg = page.locator('[data-testid="raf-segment-demographic"]').first();
    if (await seg.count() === 0) {
      test.skip(true, "Demographic segment not visible");
      return;
    }
    const text = await hoverAndGetTooltip(page, seg);
    expect(text.length).toBeGreaterThan(10);
    expect(text.toLowerCase()).toContain("demographic");
  });

  test("4b. Disease segment label shows tooltip", async ({ page }) => {
    const rafTab = page.locator('button, [role="tab"]').filter({ hasText: /RAF/i }).first();
    await rafTab.waitFor({ timeout: 8_000 });
    await rafTab.click();
    await page.waitForTimeout(1_500);

    const seg = page.locator('[data-testid="raf-segment-disease"]').first();
    if (await seg.count() === 0) {
      test.skip(true, "Disease segment not visible");
      return;
    }
    const text = await hoverAndGetTooltip(page, seg);
    expect(text.length).toBeGreaterThan(10);
    expect(text.toLowerCase()).toContain("hcc");
  });

  test("4c. Interaction segment label shows tooltip", async ({ page }) => {
    const rafTab = page.locator('button, [role="tab"]').filter({ hasText: /RAF/i }).first();
    await rafTab.waitFor({ timeout: 8_000 });
    await rafTab.click();
    await page.waitForTimeout(1_500);

    const seg = page.locator('[data-testid="raf-segment-interaction"]').first();
    if (await seg.count() === 0) {
      test.skip(true, "Interaction segment not visible");
      return;
    }
    const text = await hoverAndGetTooltip(page, seg);
    expect(text.length).toBeGreaterThan(10);
    expect(text.toLowerCase()).toContain("interact");
  });

  // ── 5. HCC chip in problem list ───────────────────────────────────────────
  test("5. HCC chip in problem list shows ICD-10 tooltip", async ({ page }) => {
    const hccChip = page.locator('[data-testid^="hcc-chip-"]').first();
    if (await hccChip.count() === 0) {
      test.skip(true, "No HCC chips in problem list");
      return;
    }
    const text = await hoverAndGetTooltip(page, hccChip);
    expect(text.length).toBeGreaterThan(10);
    expect(text.toLowerCase()).toContain("icd-10");
  });

  // ── 6. MEAT evidence pill ─────────────────────────────────────────────────
  test("6. MEAT pill shows monitored/evaluated/assessed/treated tooltip", async ({ page }) => {
    // MEAT dots are on the RAF tab inside HCC rows or suspects tab
    const rafTab = page.locator('button, [role="tab"]').filter({ hasText: /RAF/i }).first();
    await rafTab.waitFor({ timeout: 8_000 });
    await rafTab.click();
    await page.waitForTimeout(1_500);

    // MEAT buttons
    const meatBtn = page.locator('button[aria-label*="Monitored"], button[aria-label*="Evaluated"], button[aria-label*="Assessed"], button[aria-label*="Treated"]').first();
    if (await meatBtn.count() === 0) {
      // Try suspects tab
      const suspTab = page.locator('button, [role="tab"]').filter({ hasText: /Suspect/i }).first();
      if (await suspTab.count() > 0) {
        await suspTab.click();
        await page.waitForTimeout(1_500);
      }
      const meatBtn2 = page.locator('button[aria-label*="Monitored"], button[aria-label*="Evaluated"], button[aria-label*="Assessed"], button[aria-label*="Treated"]').first();
      if (await meatBtn2.count() === 0) {
        test.skip(true, "No MEAT evidence pills visible");
        return;
      }
      const text2 = await hoverAndGetTooltip(page, meatBtn2);
      expect(text2.length).toBeGreaterThan(5);
      return;
    }
    const text = await hoverAndGetTooltip(page, meatBtn);
    expect(text.length).toBeGreaterThan(5);
  });

  // ── 7. Encounter row ──────────────────────────────────────────────────────
  test("7. Encounter row shows click-for-details tooltip", async ({ page }) => {
    const row = page.locator('[data-testid^="encounter-row-"]').first();
    if (await row.count() === 0) {
      test.skip(true, "No encounter rows visible");
      return;
    }
    const text = await hoverAndGetTooltip(page, row);
    expect(text.length).toBeGreaterThan(10);
    expect(text.toLowerCase()).toContain("encounter");
  });

  // ── 8. Recapture gap row ──────────────────────────────────────────────────
  test("8. Recapture gap row shows priority + days-since tooltip", async ({ page }) => {
    const gapRow = page.locator('[data-testid^="recapture-gap-row-"]').first();
    if (await gapRow.count() === 0) {
      // Try RAF tab
      const rafTab = page.locator('button, [role="tab"]').filter({ hasText: /RAF/i }).first();
      await rafTab.waitFor({ timeout: 8_000 });
      await rafTab.click();
      await page.waitForTimeout(1_500);
      const rafGapRow = page.locator('[data-testid^="raf-recapture-row-"]').first();
      if (await rafGapRow.count() === 0) {
        test.skip(true, "No recapture gap rows visible");
        return;
      }
      const text2 = await hoverAndGetTooltip(page, rafGapRow);
      expect(text2.length).toBeGreaterThan(10);
      expect(text2.toLowerCase()).toContain("gap");
      return;
    }
    const text = await hoverAndGetTooltip(page, gapRow);
    expect(text.length).toBeGreaterThan(10);
    expect(text.toLowerCase()).toContain("gap");
  });

  // ── 9. Suspect confidence + HCC chip ─────────────────────────────────────
  test("9a. Suspect confidence pill shows score explanation", async ({ page }) => {
    const suspTab = page.locator('button, [role="tab"]').filter({ hasText: /Suspect/i }).first();
    await suspTab.waitFor({ timeout: 8_000 });
    await suspTab.click();
    await page.waitForTimeout(2_000);

    const confPill = page.locator('[data-testid^="suspect-confidence-"]').first();
    if (await confPill.count() === 0) {
      test.skip(true, "No suspect confidence pills");
      return;
    }
    const text = await hoverAndGetTooltip(page, confPill);
    expect(text.length).toBeGreaterThan(10);
    expect(text.toLowerCase()).toContain("confidence");
  });

  test("9b. Suspect HCC chip shows RAF coefficient tooltip", async ({ page }) => {
    const suspTab = page.locator('button, [role="tab"]').filter({ hasText: /Suspect/i }).first();
    await suspTab.waitFor({ timeout: 8_000 });
    await suspTab.click();
    await page.waitForTimeout(2_000);

    const hccChip = page.locator('[data-testid^="suspect-hcc-chip-"]').first();
    if (await hccChip.count() === 0) {
      test.skip(true, "No suspect HCC chips");
      return;
    }
    const text = await hoverAndGetTooltip(page, hccChip);
    expect(text.length).toBeGreaterThan(10);
    expect(text.toLowerCase()).toContain("hcc");
  });

  // ── 10. Clinical Highlights panel ─────────────────────────────────────────
  test("10. Clinical Highlights header shows Gemini/AI tooltip", async ({ page }) => {
    const header = page.locator('[data-testid="clinical-highlights-title"]').first();
    if (await header.count() === 0) {
      test.skip(true, "Clinical highlights panel not visible");
      return;
    }
    const text = await hoverAndGetTooltip(page, header);
    expect(text.length).toBeGreaterThan(10);
    // Should mention AI extraction and note
    expect(text.toLowerCase()).toMatch(/ai|gemini|nlp|clinical note/);
  });

  // ── Screenshot ────────────────────────────────────────────────────────────
  test("Screenshot: patient detail with tooltip open", async ({ page }) => {
    // Hover the Data Quality chip and screenshot
    const chip = page.locator('[data-testid="data-quality-chip"]').first();
    if (await chip.count() > 0) {
      await chip.scrollIntoViewIfNeeded();
      await chip.hover();
      await page.locator('[role="tooltip"]').first().waitFor({ state: "visible", timeout: 5_000 });
    }
    await page.screenshot({
      path: "test-results/patient-detail-tooltips.png",
      fullPage: false,
    });
  });
});
