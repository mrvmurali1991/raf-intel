import { test, expect } from "@playwright/test";
import { login, waitForDataLoad } from "./helpers";

/**
 * Dashboard tests
 *
 * Verifies that the Population Intelligence Dashboard renders its key sections
 * and that interactive controls (refresh, navigation links) work as expected.
 */
test.describe("Dashboard", () => {
  // Log in once before every test in this file.
  test.beforeEach(async ({ page }) => {
    await login(page);
    // The dashboard makes several parallel API calls; wait for them to settle.
    await waitForDataLoad(page);
  });

  // ---------------------------------------------------------------------------
  // Page load
  // ---------------------------------------------------------------------------

  test("dashboard loads and displays the page heading", async ({ page }) => {
    await expect(page.getByText("Population Intelligence Dashboard")).toBeVisible();
  });

  // ---------------------------------------------------------------------------
  // KPI strip
  // ---------------------------------------------------------------------------

  test("KPI card — Total Population is visible", async ({ page }) => {
    await expect(page.getByText("Total Population")).toBeVisible();
  });

  test("KPI card — Patients Analyzed is visible", async ({ page }) => {
    await expect(page.getByText("Patients Analyzed")).toBeVisible();
  });

  test("KPI card — Average RAF Score is visible", async ({ page }) => {
    await expect(page.getByText("Average RAF Score")).toBeVisible();
  });

  test("KPI card — Revenue Opportunity is visible", async ({ page }) => {
    await expect(page.getByText("Revenue Opportunity")).toBeVisible();
  });

  // ---------------------------------------------------------------------------
  // Risk distribution section
  // ---------------------------------------------------------------------------

  test("Population Risk Stratification section renders", async ({ page }) => {
    await expect(page.getByText("Population Risk Stratification")).toBeVisible();
  });

  test("risk tier labels (High / Medium / Low) are rendered", async ({ page }) => {
    await expect(page.getByText("High Risk")).toBeVisible();
    await expect(page.getByText("Medium Risk")).toBeVisible();
    await expect(page.getByText("Low Risk")).toBeVisible();
  });

  // ---------------------------------------------------------------------------
  // Refresh button
  // ---------------------------------------------------------------------------

  test("clicking Sync EMR Data re-triggers data fetch without navigating away", async ({
    page,
  }) => {
    // Intercept the first of the re-fetched endpoints so we can confirm the
    // refresh actually fired a network request.
    let refreshRequestSeen = false;
    page.on("request", (req) => {
      if (req.url().includes("/api/")) refreshRequestSeen = true;
    });

    await page.click("text=Sync EMR Data");

    // Wait briefly for any re-fetch to start.
    await page.waitForTimeout(1_000);

    expect(refreshRequestSeen).toBe(true);
    // Still on the dashboard.
    expect(page.url()).toMatch(/\/$/);
  });

  // ---------------------------------------------------------------------------
  // Quick action navigation
  // ---------------------------------------------------------------------------

  test("Analyze Patients quick-action navigates to /analysis", async ({ page }) => {
    await page.click("text=Analyze Patients");
    await page.waitForURL("/analysis", { timeout: 15_000 });
    expect(page.url()).toContain("/analysis");
  });

  test("Review Suspects quick-action navigates to /suspects", async ({ page }) => {
    await page.click("text=Review Suspects");
    await page.waitForURL("/suspects", { timeout: 15_000 });
    expect(page.url()).toContain("/suspects");
  });

  test("View Reports quick-action navigates to /reports", async ({ page }) => {
    await page.click("text=View Reports");
    await page.waitForURL("/reports", { timeout: 15_000 });
    expect(page.url()).toContain("/reports");
  });

  // ---------------------------------------------------------------------------
  // Sidebar navigation
  // ---------------------------------------------------------------------------

  test("sidebar link to Patients navigates correctly", async ({ page }) => {
    // The sidebar renders anchor tags with the href set to /patients.
    await page.click('a[href="/patients"]');
    await page.waitForURL("/patients", { timeout: 15_000 });
    expect(page.url()).toContain("/patients");
  });

  // ---------------------------------------------------------------------------
  // HCC and data completeness sections
  // ---------------------------------------------------------------------------

  test("Most Common HCC Codes section is rendered", async ({ page }) => {
    await expect(page.getByText("Most Common HCC Codes")).toBeVisible();
  });

  test("EMR Data Coverage section is rendered", async ({ page }) => {
    await expect(page.getByText("EMR Data Coverage")).toBeVisible();
  });
});
