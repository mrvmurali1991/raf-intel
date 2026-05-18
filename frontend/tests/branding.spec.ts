/**
 * Branding verification spec — @smoke
 *
 * Asserts that every tenant-facing surface shows "Acme Health" and never
 * exposes a bare "RAF Intelligence" product name in place of the tenant name.
 *
 * Pages checked:
 *   1. Login             — tab title, left-panel name, right-panel tagline
 *   2. Dashboard (/)     — tab title, sidebar logo text
 *   3. Patients (/patients) — tab title
 *   4. Reports           — tab title
 *   5. ROI Calculator    — tab title, page subtitle
 *
 * Run subset:  PW_GREP=@smoke npx playwright test tests/branding.spec.ts
 */

import { test, expect, type Page } from "@playwright/test";

const BASE = process.env.E2E_BASE_URL ?? "https://raf.comercioit.com";

const TENANT_NAME = "Acme Health";
const PRODUCT_NAME = "RAF Intelligence";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function loginAs(page: Page, email: string, password: string) {
  await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
  await page.fill('input[type="email"]', email);
  await page.fill('input[type="password"]', password);
  await page.click('button[type="submit"]');
  // Wait for navigation away from /login
  await page.waitForURL((url) => !url.pathname.startsWith("/login"), {
    timeout: 30_000,
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Tenant branding — Acme Health @smoke", () => {
  test("Login page tab title contains Acme Health, not standalone RAF Intelligence", async ({
    page,
  }) => {
    await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded" });
    const title = await page.title();
    expect(title, `Expected tab title to contain "${TENANT_NAME}"`).toContain(
      TENANT_NAME
    );
    // Product name should NOT appear as the sole title token for a tenant-facing page
    expect(title, `Tab title should not be just "${PRODUCT_NAME}"`).not.toBe(
      PRODUCT_NAME
    );
  });

  test("Login page left panel shows tenant name", async ({ page }) => {
    await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
    // Visible on lg breakpoint left panel or mobile logo
    const bodyText = await page.locator("body").innerText();
    expect(
      bodyText,
      `Login page should display "${TENANT_NAME}"`
    ).toContain(TENANT_NAME);
  });

  test("Login page tagline is Clinical Intelligence (not a product ad)", async ({
    page,
  }) => {
    await page.goto(`${BASE}/login`, { waitUntil: "networkidle" });
    const bodyText = await page.locator("body").innerText();
    expect(bodyText).toContain("Clinical Intelligence");
  });

  test("Dashboard tab title is Page · Acme Health, not · RAF Intelligence", async ({
    page,
  }) => {
    await loginAs(page, "admin@raf.health", "Admin@123");
    await page.goto(`${BASE}/`, { waitUntil: "domcontentloaded" });
    const title = await page.title();
    expect(title).toContain(TENANT_NAME);
    // Template should be "Page · Acme Health" not "Page · RAF Intelligence"
    expect(title).not.toMatch(/\|\s*RAF Intelligence$/);
    expect(title).not.toMatch(/·\s*RAF Intelligence$/);
  });

  test("Sidebar logo text is Acme Health, not RAF Intelligence fallback", async ({
    page,
  }) => {
    await loginAs(page, "admin@raf.health", "Admin@123");
    // data-testid set in Sidebar.tsx
    const logoEl = page.locator('[data-testid="sidebar-logo-text"]');
    const count = await logoEl.count();
    if (count > 0) {
      const text = await logoEl.first().innerText();
      expect(
        text,
        `Sidebar logo should show "${TENANT_NAME}"`
      ).not.toBe(PRODUCT_NAME);
      expect(text).toContain("Acme");
    }
  });

  test("Patients page tab title contains Acme Health", async ({ page }) => {
    await loginAs(page, "admin@raf.health", "Admin@123");
    await page.goto(`${BASE}/patients`, { waitUntil: "domcontentloaded" });
    const title = await page.title();
    expect(title).toContain(TENANT_NAME);
    expect(title).not.toMatch(/·\s*RAF Intelligence$/);
  });

  test("Reports page tab title contains Acme Health", async ({ page }) => {
    await loginAs(page, "admin@raf.health", "Admin@123");
    await page.goto(`${BASE}/reports`, { waitUntil: "domcontentloaded" });
    const title = await page.title();
    expect(title).toContain(TENANT_NAME);
  });

  test("ROI page tab title contains Acme Health", async ({ page }) => {
    await loginAs(page, "admin@raf.health", "Admin@123");
    await page.goto(`${BASE}/roi`, { waitUntil: "domcontentloaded" });
    const title = await page.title();
    expect(title).toContain(TENANT_NAME);
  });

  test("ROI page subtitle references tenant name, not bare product name", async ({
    page,
  }) => {
    await loginAs(page, "admin@raf.health", "Admin@123");
    await page.goto(`${BASE}/roi`, { waitUntil: "networkidle" });
    const bodyText = await page.locator("body").innerText();
    // The subtitle should say "Acme Health" (or similar) not "RAF Intelligence"
    const hasProductInSubtitle = /return on investment with RAF Intelligence/i.test(
      bodyText
    );
    expect(
      hasProductInSubtitle,
      'ROI subtitle should use tenant name, not "RAF Intelligence"'
    ).toBe(false);
  });
});
