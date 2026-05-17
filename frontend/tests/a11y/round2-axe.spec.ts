/**
 * round2-axe.spec.ts — WCAG 2.2 AA accessibility regression suite.
 *
 * Covers all pages touched by fix/round2-ux-a11y-batch:
 *   /v28-impact, /radv, /hedis, /coder-analytics, /edi-generation,
 *   /admin/bulk-ingest, /smart/launch
 *
 * Asserts zero axe-core violations for:
 *   - color-contrast
 *   - heading-order
 *   - label (form input labels)
 *
 * Credentials: admin@raf.health / Admin@123 (canonical demo user).
 *
 * Run with:
 *   cd frontend && npx playwright test tests/a11y/round2-axe.spec.ts
 */

import { test, expect, Page, BrowserContext } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const BASE_URL = "https://raf.comercioit.com";
const AXE_PATH = path.join(__dirname, "../../public/axe.min.js");

/**
 * Inject axe-core from the bundled public/axe.min.js, run it against the
 * current page DOM, and return the filtered AxeResults object.
 */
async function runAxe(
  page: Page,
  rulesToCheck: string[] = ["color-contrast", "heading-order", "label"],
) {
  const axeSource = fs.readFileSync(AXE_PATH, "utf8");
  await page.evaluate(axeSource);

  const violations = await page.evaluate(
    async (rules: string[]) => {
      // @ts-expect-error — axe is injected globally
      const results = await window.axe.run(document, {
        runOnly: {
          type: "rule",
          values: rules,
        },
        resultTypes: ["violations"],
      });
      return results.violations as Array<{
        id: string;
        impact: string;
        description: string;
        nodes: Array<{ html: string; failureSummary: string }>;
      }>;
    },
    rulesToCheck,
  );

  return violations;
}

/** Log a human-readable summary of violations so CI output is actionable. */
function formatViolations(
  violations: Array<{
    id: string;
    impact: string;
    description: string;
    nodes: Array<{ html: string; failureSummary: string }>;
  }>,
): string {
  return violations
    .map(
      (v) =>
        `\n  [${v.impact}] ${v.id}: ${v.description}\n` +
        v.nodes
          .slice(0, 3)
          .map((n) => `    • ${n.html.slice(0, 120)}\n      ${n.failureSummary}`)
          .join("\n"),
    )
    .join("\n");
}

// ---------------------------------------------------------------------------
// Auth fixture — log in once, reuse session across all tests
// ---------------------------------------------------------------------------

let authContext: BrowserContext | undefined;

test.beforeAll(async ({ browser }) => {
  authContext = await browser.newContext({ ignoreHTTPSErrors: true });
  const loginPage = await authContext.newPage();

  await loginPage.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded", timeout: 30_000 });

  // Fill login form — try common field selectors gracefully
  await loginPage.fill('input[type="email"], input[name="email"]', "admin@raf.health");
  await loginPage.fill('input[type="password"], input[name="password"]', "Admin@123");
  await loginPage.click('button[type="submit"]');

  // Wait for redirect away from /login
  await loginPage.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 20_000 });
  await loginPage.close();
});

test.afterAll(async () => {
  await authContext?.close();
});

// ---------------------------------------------------------------------------
// Per-page helpers
// ---------------------------------------------------------------------------

async function openPage(url: string): Promise<Page> {
  const page = await authContext!.newPage();
  await page.goto(`${BASE_URL}${url}`, { waitUntil: "networkidle", timeout: 40_000 });
  // Allow React hydration + any lazy-loaded content to settle
  await page.waitForTimeout(1500);
  return page;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("WCAG 2.2 AA — round-2 a11y fixes", () => {
  test("/v28-impact — no contrast, heading-order, or label violations", async () => {
    const page = await openPage("/v28-impact");
    const violations = await runAxe(page);
    await page.close();

    expect(
      violations,
      `Axe violations on /v28-impact:${formatViolations(violations)}`,
    ).toHaveLength(0);
  });

  test("/radv — no contrast, heading-order, or label violations", async () => {
    const page = await openPage("/radv");
    const violations = await runAxe(page);
    await page.close();

    expect(
      violations,
      `Axe violations on /radv:${formatViolations(violations)}`,
    ).toHaveLength(0);
  });

  test("/hedis — no contrast, heading-order, or label violations", async () => {
    const page = await openPage("/hedis");
    const violations = await runAxe(page);
    await page.close();

    expect(
      violations,
      `Axe violations on /hedis:${formatViolations(violations)}`,
    ).toHaveLength(0);
  });

  test("/coder-analytics — no contrast, heading-order, or label violations", async () => {
    const page = await openPage("/coder-analytics");
    const violations = await runAxe(page);
    await page.close();

    expect(
      violations,
      `Axe violations on /coder-analytics:${formatViolations(violations)}`,
    ).toHaveLength(0);
  });

  test("/edi-generation — no contrast, heading-order, or label violations (both tabs)", async () => {
    // Test 837 tab (default)
    const page = await openPage("/edi-generation");
    let violations = await runAxe(page);
    expect(
      violations,
      `Axe violations on /edi-generation (837 tab):${formatViolations(violations)}`,
    ).toHaveLength(0);

    // Switch to 834 tab and re-run
    await page.click("button:has-text('834 Enrollment')");
    await page.waitForTimeout(500);
    violations = await runAxe(page);
    await page.close();

    expect(
      violations,
      `Axe violations on /edi-generation (834 tab):${formatViolations(violations)}`,
    ).toHaveLength(0);
  });

  test("/admin/bulk-ingest — no contrast, heading-order, or label violations", async () => {
    const page = await openPage("/admin/bulk-ingest");
    const violations = await runAxe(page);
    await page.close();

    expect(
      violations,
      `Axe violations on /admin/bulk-ingest:${formatViolations(violations)}`,
    ).toHaveLength(0);
  });

  test("/smart/launch — no contrast, heading-order, or label violations", async () => {
    const page = await openPage("/smart/launch");
    // /smart/launch may redirect or show a SMART-on-FHIR setup screen
    // Run axe regardless so we catch anything rendered
    const violations = await runAxe(page);
    await page.close();

    expect(
      violations,
      `Axe violations on /smart/launch:${formatViolations(violations)}`,
    ).toHaveLength(0);
  });

  // ---- Dialog-specific: RADV create-run focus trap ----
  test("/radv create-run dialog — first input receives focus on open", async () => {
    const page = await openPage("/radv");

    // Open the dialog
    await page.click('[data-testid="radv-new-run"]');
    await page.waitForSelector('[role="dialog"]', { timeout: 5_000 });

    // The first input inside the dialog should be focused
    const focusedTag = await page.evaluate(() => document.activeElement?.tagName.toLowerCase());
    expect(focusedTag, "Expected first dialog input to be focused").toBe("input");

    // Axe check while dialog is open
    const violations = await runAxe(page);
    await page.close();

    expect(
      violations,
      `Axe violations on /radv create-run dialog:${formatViolations(violations)}`,
    ).toHaveLength(0);
  });

  test("/radv create-run dialog — Escape closes dialog and restores focus", async () => {
    const page = await openPage("/radv");

    await page.click('[data-testid="radv-new-run"]');
    await page.waitForSelector('[role="dialog"]', { timeout: 5_000 });

    // Press Escape
    await page.keyboard.press("Escape");
    await page.waitForSelector('[role="dialog"]', { state: "hidden", timeout: 5_000 });

    // Trigger button should regain focus
    const focusedTestId = await page.evaluate(() =>
      (document.activeElement as HTMLElement | null)?.getAttribute("data-testid"),
    );
    expect(focusedTestId, "Expected trigger button to regain focus after Escape").toBe(
      "radv-new-run",
    );

    await page.close();
  });
});
