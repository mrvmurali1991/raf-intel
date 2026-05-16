/**
 * WCAG 2.1 AA smoke test using axe-core.
 *
 * Runs accessibility scans on a handful of public + authenticated pages
 * and asserts that no serious/critical violations are present. We
 * deliberately skip when the `CI` environment variable is unset so local
 * runs without the `@axe-core/playwright` dependency installed don't
 * break existing flows.
 *
 * NOTE: This suite intentionally targets the LOCAL dev server
 * (`http://localhost:3444` by default) rather than the staging baseURL
 * in `playwright.config.ts`. Accessibility regressions must be caught
 * against the in-repo source, not whatever happens to be deployed to
 * staging. Override the target with `AXE_BASE_URL` if needed.
 *
 * To run:
 *   npm install
 *   CI=true npx playwright test tests/e2e/axe-smoke.spec.ts
 */
import { test, expect, request as pwRequest } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// Guard: only run when CI=true so unconfigured local devs aren't broken.
const shouldRun = !!process.env.CI;

// Local Next dev server. Override via env if the port ever shifts.
const AXE_BASE_URL = process.env.AXE_BASE_URL ?? "http://localhost:3444";
const BACKEND_HEALTH = process.env.AXE_BACKEND_HEALTH ?? "http://localhost:8500/health";

// Backend reachability probe — used to skip the authenticated /patients scan
// when the API is not running locally. We treat any <500 as "alive"
// (only network errors / 5xx are treated as unreachable).
async function backendReachable(): Promise<boolean> {
  try {
    const ctx = await pwRequest.newContext({ ignoreHTTPSErrors: true });
    const res = await ctx.get(BACKEND_HEALTH, { timeout: 3000 });
    await ctx.dispose();
    return res.status() < 500;
  } catch {
    return false;
  }
}

// Local dev server reachability probe — skip the whole suite if it's down.
async function frontendReachable(): Promise<boolean> {
  try {
    const ctx = await pwRequest.newContext({ ignoreHTTPSErrors: true });
    const res = await ctx.get(`${AXE_BASE_URL}/login`, { timeout: 5000 });
    await ctx.dispose();
    return res.status() < 500;
  } catch {
    return false;
  }
}

test.describe("WCAG 2.1 AA — axe-core smoke", () => {
  test.skip(!shouldRun, "Set CI=true to run axe accessibility scan (requires @axe-core/playwright)");

  // Only treat serious + critical violations as test failures. Minor and
  // moderate findings are tracked separately via Storybook a11y addon.
  const FAIL_IMPACTS = new Set(["serious", "critical"]);

  test.beforeAll(async () => {
    const alive = await frontendReachable();
    test.skip(!alive, `Local frontend at ${AXE_BASE_URL} unreachable — skipping axe scan`);
  });

  test("/login has no serious/critical a11y violations", async ({ page }) => {
    await page.goto(`${AXE_BASE_URL}/login`);
    await page.waitForLoadState("networkidle");

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();

    const serious = results.violations.filter((v: { impact?: string | null }) => FAIL_IMPACTS.has(v.impact ?? ""));
    expect(serious, JSON.stringify(serious, null, 2)).toHaveLength(0);
  });

  test("/login with invalid email focused has no serious/critical a11y violations", async ({ page }) => {
    await page.goto(`${AXE_BASE_URL}/login`);
    await page.waitForLoadState("networkidle");

    // Best-effort focus on the email input. Some forms use name="username".
    const emailInput = page.locator('input[type="email"], input[name="email"], input[name="username"]').first();
    if (await emailInput.count()) {
      await emailInput.focus();
      await emailInput.fill("not-an-email");
      await emailInput.blur();
    }

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();

    const serious = results.violations.filter((v: { impact?: string | null }) => FAIL_IMPACTS.has(v.impact ?? ""));
    expect(serious, JSON.stringify(serious, null, 2)).toHaveLength(0);
  });

  test("404 page has no serious/critical a11y violations", async ({ page }) => {
    // Next.js renders the not-found page for any unknown route.
    const response = await page.goto(`${AXE_BASE_URL}/__definitely_not_a_real_page__`);
    // 404 status is expected; we still scan the rendered markup.
    if (response) {
      expect([404, 200]).toContain(response.status());
    }
    await page.waitForLoadState("networkidle");

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();

    const serious = results.violations.filter((v: { impact?: string | null }) => FAIL_IMPACTS.has(v.impact ?? ""));
    expect(serious, JSON.stringify(serious, null, 2)).toHaveLength(0);
  });

  test("/patients (admin) has no serious/critical a11y violations", async ({ page }) => {
    // Skip if backend isn't up — we can't authenticate without /api/auth/login.
    const alive = await backendReachable();
    test.skip(!alive, `Backend at ${BACKEND_HEALTH} unreachable — skipping authenticated /patients scan`);

    // Real admin login via the login form (uses canonical demo creds).
    await page.goto(`${AXE_BASE_URL}/login`);
    await page.waitForLoadState("networkidle");

    await page.locator('input[type="email"], input[name="email"]').first().fill("admin@raf.health");
    await page.locator('input[type="password"], input[name="password"]').first().fill("Admin@123");
    await Promise.all([
      page.waitForURL((url) => !url.pathname.startsWith("/login"), { timeout: 30_000 }).catch(() => null),
      page.locator('button[type="submit"]').first().click(),
    ]);

    // Navigate to the patients list.
    await page.goto(`${AXE_BASE_URL}/patients`);
    await page.waitForLoadState("domcontentloaded");
    // Best-effort: give CSR a beat to hydrate without hanging on hung XHRs.
    await page.waitForTimeout(2000);

    // If the redirect bounced us back to /login (e.g. auth failed in this env),
    // skip rather than fail — the scan target requires an authenticated view.
    if (page.url().includes("/login")) {
      test.skip(true, "Admin login did not succeed in this environment — skipping /patients scan");
    }

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();

    const serious = results.violations.filter((v: { impact?: string | null }) => FAIL_IMPACTS.has(v.impact ?? ""));
    expect(serious, JSON.stringify(serious, null, 2)).toHaveLength(0);
  });
});
