/**
 * md-huddle-polish.spec.ts
 *
 * E2E tests for the polished /md/today physician huddle page.
 *
 * Scenarios:
 *  1. Empty state renders correctly when there are no visits
 *  2. Loading skeleton is shown on first navigation before data arrives
 *  3. Card animations don't break when prefers-reduced-motion is set
 *  4. Print stylesheet hides action buttons (emulateMedia print)
 *  5. Keyboard shortcuts banner is visible
 *  6. High-revenue tile glow class is applied when revenue > $50k (unit-level DOM check)
 */

import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers/auth";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Log in and navigate to /md/today, waiting for the page to settle. */
async function gotoHuddle(page: Parameters<typeof loginAsAdmin>[0]) {
  await loginAsAdmin(page);
  await page.goto("/md/today");
  await page.waitForLoadState("networkidle", { timeout: 20_000 });
}

// ---------------------------------------------------------------------------
// 1. Empty state
// ---------------------------------------------------------------------------

test.describe("/md/today — empty state", () => {
  test("renders premium empty state when no visits are scheduled", async ({
    page,
  }) => {
    await loginAsAdmin(page);

    // Intercept the /api/md/today endpoint and return an empty briefings list
    await page.route("**/api/md/today**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          provider_id: 1,
          date: "2099-01-01",
          briefings: [],
          next_visit_date: "2099-01-08",
          summary: {
            total_visits: 0,
            total_open_hcc_gaps: 0,
            reviewed_count: 0,
            review_progress_pct: 0,
            total_revenue_at_stake_dollars: 0,
            total_supporting_labs: 0,
          },
        }),
      });
    });

    await page.goto("/md/today");
    await page.waitForLoadState("networkidle", { timeout: 20_000 });

    // Empty-state container must be visible
    const emptyState = page.locator('[data-testid="empty-state"]');
    await expect(emptyState).toBeVisible({ timeout: 10_000 });

    // Heading
    await expect(
      emptyState.locator("text=/No visits scheduled today/i")
    ).toBeVisible();

    // Next-visit date sub-text
    await expect(
      emptyState.locator("text=/Your next visit is on/i")
    ).toBeVisible();

    // "Review last visit's notes" button present and focusable
    const btn = emptyState.getByRole("button", {
      name: /Review last visit/i,
    });
    await expect(btn).toBeVisible();
    await expect(btn).toBeEnabled();
  });
});

// ---------------------------------------------------------------------------
// 2. Loading skeleton
// ---------------------------------------------------------------------------

test.describe("/md/today — loading skeleton", () => {
  test("loading skeleton appears on first navigation before data resolves", async ({
    page,
  }) => {
    await loginAsAdmin(page);

    // Delay the API so we can catch the skeleton
    let resolveDelay: () => void;
    const delayPromise = new Promise<void>((res) => {
      resolveDelay = res;
    });

    await page.route("**/api/md/today**", async (route) => {
      await delayPromise; // hold the response
      await route.continue();
    });

    // Navigate — don't wait for network idle so skeleton shows
    await page.goto("/md/today");

    // Skeleton should appear immediately before network settles
    const skeleton = page.locator('[data-testid="huddle-skeleton"]');
    await expect(skeleton).toBeVisible({ timeout: 8_000 });

    // Unblock the API
    resolveDelay!();

    // Eventually skeleton disappears and content or empty-state appears
    await expect(skeleton).not.toBeVisible({ timeout: 15_000 });
  });
});

// ---------------------------------------------------------------------------
// 3. Card animations with prefers-reduced-motion
// ---------------------------------------------------------------------------

test.describe("/md/today — reduced-motion", () => {
  test("cards render without broken layout when prefers-reduced-motion: reduce", async ({
    page,
  }) => {
    // Emulate reduced-motion preference before navigation
    await page.emulateMedia({ reducedMotion: "reduce" });

    await loginAsAdmin(page);

    // Return a mocked response with one briefing card
    await page.route("**/api/md/today**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          provider_id: 1,
          date: "2099-01-01",
          briefings: [
            {
              patient_id: 42,
              patient_name: "Jane Test",
              age: 68,
              sex: "F",
              mrn: "MRN001",
              visit_time: "09:00 AM",
              reason: "Annual wellness",
              reviewed: false,
              top_gaps: [
                {
                  hcc_code: 18,
                  description: "Diabetes with chronic complications",
                  confidence: 0.9,
                  estimated_annual_revenue_dollars: 3200,
                  suspect_id: 999,
                },
              ],
            },
          ],
          summary: {
            total_visits: 1,
            total_open_hcc_gaps: 1,
            reviewed_count: 0,
            review_progress_pct: 0,
            total_revenue_at_stake_dollars: 3200,
            total_supporting_labs: 0,
          },
        }),
      });
    });

    await page.goto("/md/today");
    await page.waitForLoadState("networkidle", { timeout: 20_000 });

    // Card must be present and visible — no animation crash
    const card = page.locator("article").first();
    await expect(card).toBeVisible({ timeout: 10_000 });

    // Verify the card has no transform animation applied (animation:none injected)
    const animationValue = await card.evaluate((el) => {
      const style = window.getComputedStyle(el);
      return style.animationName;
    });
    // Under prefers-reduced-motion the browser should report 'none'
    expect(["none", ""]).toContain(animationValue);
  });
});

// ---------------------------------------------------------------------------
// 4. Print stylesheet hides action buttons
// ---------------------------------------------------------------------------

test.describe("/md/today — print styles", () => {
  test("action buttons are hidden in print media", async ({ page }) => {
    await loginAsAdmin(page);

    // Return one card with action buttons
    await page.route("**/api/md/today**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          provider_id: 1,
          date: "2099-01-01",
          briefings: [
            {
              patient_id: 77,
              patient_name: "Print Test Patient",
              age: 55,
              sex: "M",
              top_gaps: [
                {
                  hcc_code: 85,
                  description: "Congestive heart failure",
                  confidence: 0.75,
                  suspect_id: 777,
                },
              ],
            },
          ],
          summary: {
            total_visits: 1,
            total_open_hcc_gaps: 1,
            reviewed_count: 0,
            review_progress_pct: 0,
          },
        }),
      });
    });

    await page.goto("/md/today");
    await page.waitForLoadState("networkidle", { timeout: 20_000 });

    // Switch to print media
    await page.emulateMedia({ media: "print" });

    // Accept button should be hidden via print-hide class
    const acceptBtn = page.getByRole("button", { name: /Accept HCC/i }).first();
    const declineBtn = page.getByRole("button", { name: /Decline HCC/i }).first();

    // In print mode, print-hide elements must have display:none
    const acceptVisible = await acceptBtn
      .isVisible()
      .catch(() => false);
    const declineVisible = await declineBtn
      .isVisible()
      .catch(() => false);

    expect(acceptVisible).toBe(false);
    expect(declineVisible).toBe(false);

    // The shortcuts banner should also be hidden
    const banner = page.locator('footer[aria-label="Keyboard shortcuts"]');
    const bannerVisible = await banner.isVisible().catch(() => false);
    expect(bannerVisible).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 5. Keyboard shortcuts banner visible in screen mode
// ---------------------------------------------------------------------------

test.describe("/md/today — shortcuts banner", () => {
  test("keyboard shortcuts footer is visible on screen", async ({ page }) => {
    await loginAsAdmin(page);

    await page.route("**/api/md/today**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          provider_id: 1,
          date: "2099-01-01",
          briefings: [],
          summary: {
            total_visits: 0,
            total_open_hcc_gaps: 0,
            reviewed_count: 0,
            review_progress_pct: 0,
          },
        }),
      });
    });

    await page.goto("/md/today");
    await page.waitForLoadState("networkidle", { timeout: 20_000 });

    const footer = page.locator('footer[aria-label="Keyboard shortcuts"]');
    await expect(footer).toBeVisible({ timeout: 8_000 });

    // Key labels present
    await expect(footer.locator("text=navigate")).toBeVisible();
    await expect(footer.locator("text=accept")).toBeVisible();
    await expect(footer.locator("text=decline")).toBeVisible();
    await expect(footer.locator("text=review")).toBeVisible();
  });
});

// ---------------------------------------------------------------------------
// 6. Revenue glow class
// ---------------------------------------------------------------------------

test.describe("/md/today — revenue glow", () => {
  test("revenue tile gets glow class when total > $50k", async ({ page }) => {
    await loginAsAdmin(page);

    await page.route("**/api/md/today**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          provider_id: 1,
          date: "2099-01-01",
          briefings: [],
          summary: {
            total_visits: 0,
            total_open_hcc_gaps: 0,
            reviewed_count: 0,
            review_progress_pct: 0,
            total_revenue_at_stake_dollars: 75000,
            total_supporting_labs: 0,
          },
        }),
      });
    });

    await page.goto("/md/today");
    await page.waitForLoadState("networkidle", { timeout: 20_000 });

    // The revenue stat tile should carry the glow animation class
    const glowEl = page.locator(".huddle-revenue-glow");
    await expect(glowEl).toBeVisible({ timeout: 8_000 });
  });

  test("revenue tile does NOT glow when revenue <= $50k", async ({ page }) => {
    await loginAsAdmin(page);

    await page.route("**/api/md/today**", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          provider_id: 1,
          date: "2099-01-01",
          briefings: [],
          summary: {
            total_visits: 0,
            total_open_hcc_gaps: 0,
            reviewed_count: 0,
            review_progress_pct: 0,
            total_revenue_at_stake_dollars: 10000,
            total_supporting_labs: 0,
          },
        }),
      });
    });

    await page.goto("/md/today");
    await page.waitForLoadState("networkidle", { timeout: 20_000 });

    const glowEl = page.locator(".huddle-revenue-glow");
    const count = await glowEl.count();
    expect(count).toBe(0);
  });
});
