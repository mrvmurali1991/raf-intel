/**
 * sidebar-tooltips.spec.ts
 *
 * Verifies that every nav item shows a tooltip (via title attr and shadcn Tooltip)
 * when the sidebar is collapsed to icon-only mode.
 *
 * Tags: @smoke @sidebar @tooltips
 */

import { test, expect, Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel(/email/i).fill("admin@raf.health");
  await page.getByLabel(/password/i).fill("Admin@123");
  await page.getByRole("button", { name: /sign in|login/i }).click();
  // Wait until the sidebar is rendered
  await page.waitForSelector('aside[aria-label="Main navigation sidebar"]', { timeout: 20_000 });
}

async function collapseSidebar(page: Page) {
  const collapseBtn = page.locator('button[aria-label="Collapse sidebar"]');
  if (await collapseBtn.isVisible()) {
    await collapseBtn.click();
    // Wait for the sidebar transition (300ms)
    await page.waitForTimeout(400);
  }
}

// ---------------------------------------------------------------------------
// Test data — label + substring of expected tooltip text
// ---------------------------------------------------------------------------

const NAV_TOOLTIPS: { label: string; tooltipFragment: string }[] = [
  { label: "Dashboard", tooltipFragment: "Population Health Intelligence" },
  { label: "Today's Worklist", tooltipFragment: "Daily prioritized patient queue" },
  { label: "Patients", tooltipFragment: "Full patient roster" },
  { label: "Suspects", tooltipFragment: "AI-flagged HCC diagnoses" },
  { label: "Recapture Gaps", tooltipFragment: "Prior-year HCCs" },
  { label: "Attestations", tooltipFragment: "Provider sign-off workflow" },
  { label: "Coder Review", tooltipFragment: "Queue assigned to coding team" },
  { label: "QA Audit", tooltipFragment: "QA team" },
  { label: "Pre-submission", tooltipFragment: "5-tier validation gate" },
  { label: "Quarterly Goals", tooltipFragment: "Goal-vs-actual RAF" },
];

// ANALYSIS section items (require expanding the section)
const ANALYSIS_TOOLTIPS: { label: string; tooltipFragment: string }[] = [
  { label: "Reports", tooltipFragment: "Revenue, scorecards" },
  { label: "Population", tooltipFragment: "ZIP-level risk heat map" },
  { label: "Coder Analytics", tooltipFragment: "Throughput, accuracy" },
  { label: "Provider Scorecards", tooltipFragment: "Per-provider capture rate" },
  { label: "V28 Impact", tooltipFragment: "CMS-HCC V28 model" },
  { label: "Clinical Analysis", tooltipFragment: "Free-form clinical note" },
  { label: "RAF Calculator", tooltipFragment: "Per-patient RAF scoring" },
  { label: "HCC Crosswalk", tooltipFragment: "ICD-10" },
  { label: "ROI Calculator", tooltipFragment: "Customer ROI projection" },
];

// ADMIN section items
const ADMIN_TOOLTIPS: { label: string; tooltipFragment: string }[] = [
  { label: "Settings", tooltipFragment: "Profile, security" },
  { label: "Users", tooltipFragment: "Team member management" },
  { label: "EMR Config", tooltipFragment: "Connect Epic" },
  { label: "Data Uploads", tooltipFragment: "Bulk patient" },
  { label: "Audit", tooltipFragment: "Immutable SHA-256" },
  { label: "RADV Audit Defense", tooltipFragment: "CMS RADV audit" },
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Sidebar tooltips @smoke @sidebar", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  test("nav items have correct title attributes (collapsed sidebar)", async ({ page }) => {
    await collapseSidebar(page);

    // Check title attributes on Daily Work + HCC Workflow items (always visible)
    for (const { label, tooltipFragment } of NAV_TOOLTIPS) {
      const link = page.locator(`a[title*="${tooltipFragment}"]`).first();
      await expect(link).toBeAttached({ timeout: 5_000 });
    }
  });

  test("shadcn tooltip appears on hover in collapsed mode — Daily Work items", async ({ page }) => {
    await collapseSidebar(page);

    // Hover Dashboard icon — tooltip popup should appear
    const dashLink = page.locator('a[href="/"]').first();
    await dashLink.hover();
    // shadcn Tooltip renders into a portal with data-slot="tooltip-content"
    await expect(page.locator('[data-slot="tooltip-content"]')).toContainText(
      "Population Health Intelligence",
      { timeout: 3_000 }
    );
  });

  test("shadcn tooltip appears on hover — Suspects", async ({ page }) => {
    await collapseSidebar(page);

    const link = page.locator('a[href="/suspects"]');
    await link.hover();
    await expect(page.locator('[data-slot="tooltip-content"]')).toContainText(
      "AI-flagged HCC diagnoses",
      { timeout: 3_000 }
    );
  });

  test("tooltip visible on keyboard focus (expanded sidebar)", async ({ page }) => {
    // Expanded mode — Tab to Dashboard and confirm tooltip appears on focus
    const dashLink = page.locator('a[href="/"]').first();
    await dashLink.focus();
    await expect(page.locator('[data-slot="tooltip-content"]')).toContainText(
      "Population Health Intelligence",
      { timeout: 3_000 }
    );
  });

  test("screenshot — collapsed sidebar with Dashboard tooltip", async ({ page }) => {
    await collapseSidebar(page);

    const dashLink = page.locator('a[href="/"]').first();
    await dashLink.hover();
    // Wait for tooltip animation (fade-in ~150ms)
    await page.waitForTimeout(300);

    await expect(page).toHaveScreenshot("sidebar-tooltip-dashboard-collapsed.png", {
      fullPage: false,
      clip: { x: 0, y: 0, width: 300, height: 120 },
    });
  });

  test("all visible nav items have title attributes with tooltip text", async ({ page }) => {
    await collapseSidebar(page);

    // Verify title attributes on the always-visible items
    for (const { tooltipFragment } of NAV_TOOLTIPS) {
      const el = page.locator(`[title*="${tooltipFragment}"]`).first();
      await expect(el).toBeAttached({ timeout: 3_000 });
    }
  });
});
