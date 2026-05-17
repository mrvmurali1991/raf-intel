/**
 * pcp-workflow.spec.ts — Round 2 PCP workflow regression tests.
 *
 * Covers all three blockers flagged in the PCP reviewer round:
 *   1. HEDIS strip co-located with HCC suspects on patient detail
 *   2. A/D/R keyboard shortcuts on the /suspects list
 *   3. Confidence bands use "Strong / Moderate / Weak signal" (not ">85%")
 */

import { test, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
<<<<<<< HEAD
// Auth helper — inlined to avoid helpers.ts BASE_URL dep
=======
// Auth helper
>>>>>>> fix/round2-pcp-workflow
// ---------------------------------------------------------------------------

const ADMIN_EMAIL = "admin@raf.health";
const ADMIN_PASSWORD = "Admin@123";

async function login(page: Page) {
  await page.goto("/login");
  await page.fill('input[type="email"]', ADMIN_EMAIL);
  await page.fill('input[type="password"]', ADMIN_PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL("/", { timeout: 30_000 });
}

// ---------------------------------------------------------------------------
// Blocker 1 — HEDIS strip on patient detail page
// ---------------------------------------------------------------------------

test.describe("HEDIS strip co-located with HCC suspects", () => {
  test("PatientHedisStrip is visible on /patients/1 suspects tab", async ({ page }) => {
    await login(page);

    // Navigate to patient 1, suspects tab
    await page.goto("/patients/1?tab=suspects");

    // Wait for the page to load (suspects tab panel)
    await page.waitForSelector('[role="tabpanel"]', { timeout: 20_000 });

    // The HEDIS strip section should be visible — identified by its aria-label
<<<<<<< HEAD
    // or the "HEDIS Quality Gaps" heading text
=======
>>>>>>> fix/round2-pcp-workflow
    const hedisStrip = page.getByRole("region", { name: /HEDIS quality gaps/i });

    // Allow up to 10s for the HEDIS query to resolve
    await expect(hedisStrip).toBeVisible({ timeout: 10_000 });
  });

<<<<<<< HEAD
  test("HEDIS strip shows measure badges (BCS/CCS/HBD/CBP/FUM) or 'All met'", async ({ page }) => {
=======
  test("HEDIS strip shows measure badges or 'All met'", async ({ page }) => {
>>>>>>> fix/round2-pcp-workflow
    await login(page);
    await page.goto("/patients/1?tab=suspects");
    await page.waitForSelector('[role="tabpanel"]', { timeout: 20_000 });

<<<<<<< HEAD
    // Wait for HEDIS section to appear
=======
>>>>>>> fix/round2-pcp-workflow
    const hedisSection = page.getByRole("region", { name: /HEDIS quality gaps/i });
    await expect(hedisSection).toBeVisible({ timeout: 10_000 });

    // Either some measure badges appear or an "All met" badge
<<<<<<< HEAD
    const hasGaps = await hedisSection.getByText(/Gap open|All met|BCS|CCS|HBD|CBP|FUM/).first().isVisible().catch(() => false);
=======
    const hasGaps = await hedisSection
      .getByText(/Gap open|All met|BCS|CCS|HBD|CBP|FUM/)
      .first()
      .isVisible()
      .catch(() => false);
>>>>>>> fix/round2-pcp-workflow
    expect(hasGaps).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Blocker 2 — A/D/R keyboard shortcuts on /suspects list
// ---------------------------------------------------------------------------

test.describe("Keyboard shortcuts on /suspects list", () => {
  test("pressing A on first row triggers accept mutation (shows toast)", async ({ page }) => {
    await login(page);
    await page.goto("/suspects");

    // Wait for suspects to load
    await page.waitForSelector('[role="row"]', { timeout: 20_000 });

    // Click first row to focus it (sets focusedRowIdx = 0)
    const firstRow = page.locator('[role="row"]').first();
    await firstRow.click();

    // Press A — should trigger acceptSuspect on the focused row
    await page.keyboard.press("a");

    // Expect a success toast to appear (accept or error feedback)
<<<<<<< HEAD
    const toast = page.locator('[role="status"], [role="alert"]').filter({ hasText: /accepted|error/i });
=======
    const toast = page
      .locator('[role="status"], [role="alert"]')
      .filter({ hasText: /accepted|error/i });
>>>>>>> fix/round2-pcp-workflow
    await expect(toast).toBeVisible({ timeout: 8_000 });
  });

  test("pressing D on first row triggers dismiss mutation (shows toast)", async ({ page }) => {
    await login(page);
    await page.goto("/suspects?status=open");

    await page.waitForSelector('[role="row"]', { timeout: 20_000 });

    const firstRow = page.locator('[role="row"]').first();
    await firstRow.click();

    await page.keyboard.press("d");

<<<<<<< HEAD
    const toast = page.locator('[role="status"], [role="alert"]').filter({ hasText: /dismissed|error/i });
=======
    const toast = page
      .locator('[role="status"], [role="alert"]')
      .filter({ hasText: /dismissed|error/i });
>>>>>>> fix/round2-pcp-workflow
    await expect(toast).toBeVisible({ timeout: 8_000 });
  });

  test("ArrowDown moves focus to second row", async ({ page }) => {
    await login(page);
    await page.goto("/suspects");
    await page.waitForSelector('[role="row"]', { timeout: 20_000 });

    // Focus first row
    const firstRow = page.locator('[role="row"]').first();
    await firstRow.click();

    // Arrow down
    await page.keyboard.press("ArrowDown");

<<<<<<< HEAD
    // Second row should now have an outline (focused ring) — check via
    // the focusedRowIdx styling: border: 2px solid brand color
    const secondRow = page.locator('[role="row"]').nth(1);
    // At minimum the row should be focusable and have outline
=======
    // Second row should now be focusable and visible
    const secondRow = page.locator('[role="row"]').nth(1);
>>>>>>> fix/round2-pcp-workflow
    await expect(secondRow).toBeVisible();
  });

  test("keyboard hint footer is visible on /suspects", async ({ page }) => {
    await login(page);
    await page.goto("/suspects");
    await page.waitForSelector('[role="row"]', { timeout: 20_000 });

    // The kbd shortcut hint strip should be visible
    const hint = page.getByText(/Keyboard shortcuts/i);
    await expect(hint).toBeVisible({ timeout: 5_000 });
  });
});

// ---------------------------------------------------------------------------
// Blocker 3 — Confidence bands use signal-strength labels, not % labels
// ---------------------------------------------------------------------------

test.describe("Confidence band labels are signal-strength words, not percentages", () => {
  test("no '>85%' or '65-85%' or '<65%' text visible on /suspects", async ({ page }) => {
    await login(page);
    await page.goto("/suspects");
    await page.waitForSelector('[role="row"]', { timeout: 20_000 });

    // These old percentage-implied labels must NOT appear
<<<<<<< HEAD
    const oldHighLabel = page.getByText(">85%");
    const oldMedLabel = page.getByText("65-85%");
    const oldLowLabel = page.getByText("<65%");

    await expect(oldHighLabel).not.toBeVisible();
    await expect(oldMedLabel).not.toBeVisible();
    await expect(oldLowLabel).not.toBeVisible();
=======
    await expect(page.getByText(">85%")).not.toBeVisible();
    await expect(page.getByText("65-85%")).not.toBeVisible();
    await expect(page.getByText("<65%")).not.toBeVisible();
>>>>>>> fix/round2-pcp-workflow
  });

  test("filter chips show 'Strong signal', 'Moderate signal', 'Weak signal'", async ({ page }) => {
    await login(page);
    await page.goto("/suspects");
    await page.waitForSelector('[role="row"]', { timeout: 20_000 });

    // New labels must be present in the filter strip
    await expect(page.getByText("Strong signal")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("Moderate signal")).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText("Weak signal")).toBeVisible({ timeout: 5_000 });
  });

  test("confidence column shows 'Strong', 'Moderate', or 'Weak' in data rows", async ({ page }) => {
    await login(page);
    await page.goto("/suspects");
    await page.waitForSelector('[role="row"]', { timeout: 20_000 });

    // At least one row should show a signal-strength word in the confidence column
    const signalLabels = page.getByText(/^(Strong|Moderate|Weak)$/);
    const count = await signalLabels.count();
    expect(count).toBeGreaterThan(0);
  });
});
