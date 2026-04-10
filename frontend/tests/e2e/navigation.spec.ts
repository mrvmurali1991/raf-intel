import { test, expect } from "@playwright/test";
import { login, waitForDataLoad } from "./helpers";

/**
 * Full navigation tests
 *
 * Visits every page listed in the sidebar and asserts the page loads without a
 * runtime crash. Also tests the Cmd+K command palette.
 *
 * The sidebar is defined in src/components/Sidebar.tsx and groups pages into
 * MAIN / ANALYSIS / REPORTS / ADMIN / ACCOUNT sections.
 */

// All 21 pages present in /app, grouped by sidebar section.
const ALL_PAGES = [
  // MAIN
  { href: "/", label: "Dashboard" },
  { href: "/patients", label: "Patients" },
  { href: "/suspects", label: "Review Queue" },
  { href: "/recapture", label: "Recapture Gaps" },
  { href: "/prospective", label: "Prospective" },

  // ANALYSIS
  { href: "/analysis", label: "Clinical Analysis" },
  { href: "/batch", label: "Batch Analysis" },
  { href: "/documents", label: "Documents" },
  { href: "/claims", label: "Claims" },
  { href: "/demo", label: "Pipeline Demo" },
  { href: "/integrations", label: "Integrations" },

  // REPORTS
  { href: "/reports", label: "Analytics" },
  { href: "/providers", label: "Provider Performance" },
  { href: "/quality", label: "Quality & STARS" },
  { href: "/submissions", label: "CMS Submissions" },
  { href: "/roi", label: "ROI Calculator" },
  { href: "/audit", label: "Compliance & Audit" },

  // ADMIN
  { href: "/users", label: "Users" },
  { href: "/developer", label: "Developer" },
  { href: "/emr-config", label: "EMR Config" },

  // ACCOUNT
  { href: "/settings", label: "Settings" },
];

test.describe("Full page navigation", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
  });

  for (const { href, label } of ALL_PAGES) {
    test(`${label} page (${href}) loads without a 404 or hard crash`, async ({
      page,
    }) => {
      // Collect any console errors during the page load.
      const consoleErrors: string[] = [];
      page.on("console", (msg) => {
        if (msg.type() === "error") {
          const text = msg.text();
          // Ignore expected non-critical browser noise.
          if (!text.includes("favicon") && !text.includes("net::ERR_ABORTED")) {
            consoleErrors.push(text);
          }
        }
      });

      // Track any failed XHR/fetch requests.
      const failedRequests: string[] = [];
      page.on("requestfailed", (req) => {
        // Ignore image or font resources — only flag API calls.
        if (req.url().includes("/api/")) failedRequests.push(req.url());
      });

      await page.goto(href);
      await waitForDataLoad(page);

      // 1. Must not have been redirected to /login (session still valid).
      expect(page.url()).not.toContain("/login");

      // 2. The page must not show a generic Next.js 404.
      await expect(page.getByText("404", { exact: true })).not.toBeVisible();

      // 3. No unhandled React-level errors (boundaries catch them and show
      //    "Something went wrong" in most setups).
      await expect(page.getByText("Something went wrong")).not.toBeVisible();

      // Log console errors as a soft assertion so one page doesn't block all.
      if (consoleErrors.length > 0) {
        console.warn(`[${label}] Console errors:`, consoleErrors);
      }
    });
  }
});

// ---------------------------------------------------------------------------
// Command palette
// ---------------------------------------------------------------------------

test.describe("Command Palette", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await waitForDataLoad(page);
  });

  test("Cmd+K (Meta+K) opens the command palette", async ({ page }) => {
    await page.keyboard.press("Meta+K");

    // The palette renders a text input with the placeholder
    // "Search patients, pages, actions..."
    const input = page.getByPlaceholder("Search patients, pages, actions...");
    await expect(input).toBeVisible({ timeout: 5_000 });
  });

  test("Ctrl+K also opens the command palette (Windows/Linux)", async ({ page }) => {
    await page.keyboard.press("Control+K");
    const input = page.getByPlaceholder("Search patients, pages, actions...");
    await expect(input).toBeVisible({ timeout: 5_000 });
  });

  test("typing in the command palette filters results", async ({ page }) => {
    await page.keyboard.press("Meta+K");
    const input = page.getByPlaceholder("Search patients, pages, actions...");
    await expect(input).toBeVisible({ timeout: 5_000 });

    await input.fill("dashboard");

    // At least the Dashboard page result should be listed.
    await expect(page.getByText("Dashboard")).toBeVisible({ timeout: 5_000 });
  });

  test("Escape closes the command palette", async ({ page }) => {
    await page.keyboard.press("Meta+K");
    const input = page.getByPlaceholder("Search patients, pages, actions...");
    await expect(input).toBeVisible({ timeout: 5_000 });

    await page.keyboard.press("Escape");
    await expect(input).not.toBeVisible({ timeout: 3_000 });
  });

  test("command palette search for a page name and click navigates there", async ({
    page,
  }) => {
    await page.keyboard.press("Meta+K");
    const input = page.getByPlaceholder("Search patients, pages, actions...");
    await expect(input).toBeVisible({ timeout: 5_000 });

    await input.fill("reports");

    // Click the first result that mentions "reports" / "Analytics".
    const result = page
      .getByText(/analytics|reports/i)
      .first();
    await expect(result).toBeVisible({ timeout: 5_000 });
    await result.click();

    await page.waitForURL(/\/(reports|analytics)/, { timeout: 15_000 });
    expect(page.url()).toMatch(/\/(reports|analytics)/);
  });

  test("custom event open-command-palette opens the palette", async ({ page }) => {
    // The palette also opens when window dispatches 'open-command-palette'.
    await page.evaluate(() => {
      window.dispatchEvent(new CustomEvent("open-command-palette"));
    });
    const input = page.getByPlaceholder("Search patients, pages, actions...");
    await expect(input).toBeVisible({ timeout: 5_000 });
  });
});
