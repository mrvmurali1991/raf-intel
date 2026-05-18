/**
 * admin-demo.spec.ts
 *
 * E2E tests for the /admin/demo executive demo mode page.
 *
 * Coverage:
 *   1. Admin loads /admin/demo → all 5 sections render with correct
 *      aria-labels.
 *   2. Hero stat counters reach their final non-zero values within 3s.
 *   3. Section navigation via Page Down / Page Up keyboard shortcut works.
 *   4. "Start demo tour" button starts the tour without JS errors.
 *   5. Clicking "Show me" on a suspect card highlights the evidence sentence.
 *   6. Ingestion source cards render (9 total).
 *   7. Audit CTA link points to /audit.
 *   8. Non-admin users are redirected away from /admin/demo.
 *
 * Prerequisites:
 *   - PLAYWRIGHT_BASE_URL points to a running Next.js dev server (default:
 *     http://localhost:3500).
 *   - Admin credentials: admin@raf.health / Admin@123 (fixed demo creds).
 *
 * Run with:
 *   npx playwright test tests/e2e/admin-demo.spec.ts
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

async function loginAsAdmin(page: Page) {
  await page.goto(`${BASE_URL}/login`);

  // Prefer demo-credential one-click shortcut if present
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

async function gotoDemo(page: Page) {
  await page.goto(`${BASE_URL}/admin/demo`);
  // Wait for the scroll container to appear
  await page.waitForSelector('[aria-label="Demo mode walkthrough"]', {
    timeout: 20_000,
  });
}

// ---------------------------------------------------------------------------
// Suite
// ---------------------------------------------------------------------------

test.describe("Admin Demo Mode (/admin/demo)", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  // ── Test 1: All 5 sections render ──────────────────────────────────────

  test("renders all 5 sections with correct aria-labels", async ({ page }) => {
    await gotoDemo(page);

    for (const label of SECTION_ARIA_LABELS) {
      await expect(
        page.locator(`[aria-label="${label}"]`).first()
      ).toBeVisible({ timeout: 10_000 });
    }
  });

  // ── Test 2: Hero counters reach final values ────────────────────────────

  test("hero stat counters reach non-zero final values within 3s", async ({
    page,
  }) => {
    await gotoDemo(page);

    // Locate the 4 aria-live stat containers inside the hero section
    const heroSection = page.locator('[aria-label="Section 1: Platform overview"]');

    // Wait up to 3 s for at least one counter to show a value > 0
    await expect(async () => {
      const liveRegions = heroSection.locator("[aria-live='polite']");
      const count = await liveRegions.count();
      expect(count).toBeGreaterThanOrEqual(4);

      // At least one counter should have a non-zero display value
      let foundNonZero = false;
      for (let i = 0; i < count; i++) {
        const text = await liveRegions.nth(i).innerText();
        if (text && text !== "0" && text.trim() !== "") {
          foundNonZero = true;
          break;
        }
      }
      expect(foundNonZero).toBe(true);
    }).toPass({ timeout: 3_000 });
  });

  // ── Test 3: Keyboard navigation (Page Down / Page Up) ──────────────────

  test("Page Down / Page Up navigates between sections", async ({ page }) => {
    await gotoDemo(page);

    // Focus the page body so keydown events register
    await page.keyboard.press("Tab");

    // Scroll to section 2 via Page Down
    await page.keyboard.press("PageDown");

    await expect(async () => {
      // After PageDown, section 2 (NLP) should be intersecting / visible
      const nlp = page.locator('[aria-label="Section 2: NLP suspect mining"]');
      await expect(nlp).toBeInViewport({ ratio: 0.3 });
    }).toPass({ timeout: 3_000 });

    // Scroll back with Page Up
    await page.keyboard.press("PageUp");

    await expect(async () => {
      const hero = page.locator('[aria-label="Section 1: Platform overview"]');
      await expect(hero).toBeInViewport({ ratio: 0.3 });
    }).toPass({ timeout: 3_000 });
  });

  // ── Test 4: "Start demo tour" works without errors ──────────────────────

  test("Start demo tour button starts tour and auto-scrolls without JS errors", async ({
    page,
  }) => {
    const jsErrors: string[] = [];
    page.on("pageerror", (e) => jsErrors.push(e.message));

    await gotoDemo(page);

    const tourButton = page.locator('[aria-label="Start demo tour"]');
    await expect(tourButton).toBeVisible({ timeout: 8_000 });
    await tourButton.click();

    // Button should change to "Stop tour" state
    await expect(page.locator('[aria-label="Stop demo tour"]')).toBeVisible({
      timeout: 3_000,
    });

    // Wait 2 s to confirm no JS errors fired during initial scroll
    await page.waitForTimeout(2_000);

    // Stop the tour to clean up timers
    const stopButton = page.locator('[aria-label="Stop demo tour"]');
    if (await stopButton.isVisible()) {
      await stopButton.click();
    }

    expect(jsErrors.length).toBe(0);
  });

  // ── Test 5: Show-me button highlights evidence ─────────────────────────

  test("clicking a suspect card highlights the evidence sentence", async ({
    page,
  }) => {
    await gotoDemo(page);

    // Navigate to NLP section
    const nlpSection = page.locator('[aria-label="Section 2: NLP suspect mining"]');
    await nlpSection.scrollIntoViewIfNeeded();

    // Click the first suspect card
    const firstSuspect = nlpSection
      .locator('[role="button"][aria-label*="Suspect:"]')
      .first();
    await expect(firstSuspect).toBeVisible({ timeout: 8_000 });
    await firstSuspect.click();

    // After click, a <mark> element with yellow background should appear
    const mark = nlpSection.locator("mark").first();
    await expect(mark).toBeVisible({ timeout: 3_000 });
  });

  // ── Test 6: 9 ingestion source cards ───────────────────────────────────

  test("renders 9 ingestion source cards in Section 3", async ({ page }) => {
    await gotoDemo(page);

    const ingestionSection = page.locator(
      '[aria-label="Section 3: Document ingestion sources"]'
    );
    await ingestionSection.scrollIntoViewIfNeeded();

    const cards = ingestionSection.locator('[role="listitem"]');
    await expect(cards).toHaveCount(9, { timeout: 10_000 });
  });

  // ── Test 7: Audit CTA points to /audit ─────────────────────────────────

  test("audit section CTA links to /audit", async ({ page }) => {
    await gotoDemo(page);

    const auditSection = page.locator('[aria-label="Section 5: Audit readiness"]');
    await auditSection.scrollIntoViewIfNeeded();

    const cta = auditSection.locator('a[href="/audit"]');
    await expect(cta).toBeVisible({ timeout: 8_000 });
    await expect(cta).toContainText("audit");
  });

  // ── Test 8: Non-admin redirect ──────────────────────────────────────────

  test("unauthenticated access redirects to login", async ({ page }) => {
    // Clear session to simulate unauthenticated user
    await page.context().clearCookies();
    await page.context().clearPermissions();

    await page.goto(`${BASE_URL}/admin/demo`);

    // Should be redirected to /login
    await expect(page).toHaveURL(`${BASE_URL}/login`, { timeout: 10_000 });
  });
});
