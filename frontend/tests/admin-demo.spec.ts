/**
 * admin-demo.spec.ts
 *
 * E2E tests for the /admin/demo executive demo mode page.
 *
 * Coverage:
 *   1. Admin loads /admin/demo → all 5 sections render with correct aria-labels.
 *   2. Hero stat counters reach non-zero final values within 3 s.
 *   3. Page Down / Page Up keyboard navigation works.
 *   4. "Start demo tour" auto-scrolls without JS errors.
 *   5. Clicking a suspect card highlights the evidence sentence (mark element).
 *   6. Section 3 renders exactly 9 ingestion source cards.
 *   7. Audit CTA link points to /audit.
 *   8. Unauthenticated access redirects to /login.
 *
 * Prerequisites:
 *   - PLAYWRIGHT_BASE_URL points to the running Next.js dev server (default
 *     http://localhost:3500).
 *   - Admin credentials: admin@raf.health / Admin@123 (fixed demo creds).
 *
 * Run with:
 *   npx playwright test tests/admin-demo.spec.ts
 */

import { test, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3500";
const ADMIN_EMAIL = "admin@raf.health";
const ADMIN_PASSWORD = "Admin@123";

const SECTION_ARIA_LABELS = [
  "Section 1: Platform overview",
  "Section 2: NLP suspect mining",
  "Section 3: Document ingestion sources",
  "Section 4: Doctor's huddle preview",
  "Section 5: Audit readiness",
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function loginAsAdmin(page: Page): Promise<void> {
  await page.goto(`${BASE_URL}/login`);

  // One-click shortcut if demo credentials panel is visible
  const adminRow = page.locator('[data-testid="demo-credential-admin"]');
  if (await adminRow.isVisible({ timeout: 2_000 }).catch(() => false)) {
    await adminRow.click();
  } else {
    await page.fill('input[type="email"], input[name="email"]', ADMIN_EMAIL);
    await page.fill(
      'input[type="password"], input[name="password"]',
      ADMIN_PASSWORD
    );
  }

  await page.click('button[type="submit"]');
  await page.waitForURL(`${BASE_URL}/`, { timeout: 15_000 });
}

async function gotoDemo(page: Page): Promise<void> {
  await page.goto(`${BASE_URL}/admin/demo`);
  await page.waitForSelector('[aria-label="Demo mode walkthrough"]', {
    timeout: 20_000,
  });
}

// ---------------------------------------------------------------------------
// Test suite
// ---------------------------------------------------------------------------

test.describe("Admin Demo Mode (/admin/demo)", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  // ── 1: All 5 sections ──────────────────────────────────────────────────

  test("renders all 5 sections with correct aria-labels", async ({ page }) => {
    await gotoDemo(page);

    for (const label of SECTION_ARIA_LABELS) {
      await expect(
        page.locator(`[aria-label="${label}"]`).first()
      ).toBeVisible({ timeout: 10_000 });
    }
  });

  // ── 2: Hero counters animate to final values ──────────────────────────

  test("hero stat counters reach non-zero final values within 3 s", async ({
    page,
  }) => {
    await gotoDemo(page);

    const hero = page.locator('[aria-label="Section 1: Platform overview"]');

    await expect(async () => {
      const liveRegions = hero.locator("[aria-live='polite']");
      const count = await liveRegions.count();
      expect(count).toBeGreaterThanOrEqual(4);

      let foundNonZero = false;
      for (let i = 0; i < count; i++) {
        const text = await liveRegions.nth(i).innerText();
        if (text && text.trim() !== "0" && text.trim() !== "") {
          foundNonZero = true;
          break;
        }
      }
      expect(foundNonZero).toBe(true);
    }).toPass({ timeout: 3_500 });
  });

  // ── 3: Keyboard navigation ─────────────────────────────────────────────

  test("Page Down navigates to Section 2 and Page Up returns to Section 1", async ({
    page,
  }) => {
    await gotoDemo(page);

    // Focus the page so keydown fires
    await page.keyboard.press("Tab");

    await page.keyboard.press("PageDown");

    await expect(async () => {
      const nlp = page.locator('[aria-label="Section 2: NLP suspect mining"]');
      await expect(nlp).toBeInViewport({ ratio: 0.3 });
    }).toPass({ timeout: 3_000 });

    await page.keyboard.press("PageUp");

    await expect(async () => {
      const hero = page.locator('[aria-label="Section 1: Platform overview"]');
      await expect(hero).toBeInViewport({ ratio: 0.3 });
    }).toPass({ timeout: 3_000 });
  });

  // ── 4: Start demo tour ─────────────────────────────────────────────────

  test("Start demo tour runs without JS errors", async ({ page }) => {
    const jsErrors: string[] = [];
    page.on("pageerror", (e) => jsErrors.push(e.message));

    await gotoDemo(page);

    const startBtn = page.locator('[aria-label="Start demo tour"]');
    await expect(startBtn).toBeVisible({ timeout: 8_000 });
    await startBtn.click();

    await expect(
      page.locator('[aria-label="Stop demo tour"]')
    ).toBeVisible({ timeout: 3_000 });

    // Let it run briefly then stop
    await page.waitForTimeout(1_500);
    const stopBtn = page.locator('[aria-label="Stop demo tour"]');
    if (await stopBtn.isVisible()) await stopBtn.click();

    expect(jsErrors).toHaveLength(0);
  });

  // ── 5: Suspect evidence highlight ─────────────────────────────────────

  test("clicking a suspect card highlights evidence with a mark element", async ({
    page,
  }) => {
    await gotoDemo(page);

    const nlp = page.locator('[aria-label="Section 2: NLP suspect mining"]');
    await nlp.scrollIntoViewIfNeeded();

    const firstCard = nlp
      .locator('[role="button"][aria-label*="Suspect:"]')
      .first();
    await expect(firstCard).toBeVisible({ timeout: 8_000 });
    await firstCard.click();

    const mark = nlp.locator("mark").first();
    await expect(mark).toBeVisible({ timeout: 3_000 });
  });

  // ── 6: 9 source cards in Section 3 ────────────────────────────────────

  test("Section 3 renders exactly 9 ingestion source cards", async ({ page }) => {
    await gotoDemo(page);

    const ingestion = page.locator(
      '[aria-label="Section 3: Document ingestion sources"]'
    );
    await ingestion.scrollIntoViewIfNeeded();

    const cards = ingestion.locator('[role="listitem"]');
    await expect(cards).toHaveCount(9, { timeout: 10_000 });
  });

  // ── 7: Audit CTA link ─────────────────────────────────────────────────

  test("audit section CTA links to /audit", async ({ page }) => {
    await gotoDemo(page);

    const auditSection = page.locator(
      '[aria-label="Section 5: Audit readiness"]'
    );
    await auditSection.scrollIntoViewIfNeeded();

    const cta = auditSection.locator('a[href="/audit"]');
    await expect(cta).toBeVisible({ timeout: 8_000 });
    await expect(cta).toContainText(/audit/i);
  });

  // ── 8: Unauthenticated redirect ───────────────────────────────────────

  test("unauthenticated user is redirected to /login", async ({ page }) => {
    await page.context().clearCookies();

    await page.goto(`${BASE_URL}/admin/demo`);

    await expect(page).toHaveURL(new RegExp("/login"), { timeout: 10_000 });
  });
});
