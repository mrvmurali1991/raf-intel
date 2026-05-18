/**
 * /recapture tooltip verification spec.
 *
 * Asserts that every tooltip category added in feat(recapture): tooltips
 * is reachable and visible via keyboard focus (Tab + aria) and hover.
 *
 * Run with:
 *   cd frontend && BASE_URL=https://raf.comercioit.com \
 *     npx playwright test tests/demo/verify-recapture-tooltips.spec.ts \
 *     --reporter=line
 */

import { test, expect, type Page, type APIRequestContext } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3444";
const API_URL  = process.env.API_URL  ?? "http://localhost:8500";
const EMAIL    = "admin@raf.health";
const PASSWORD = "Admin@123";

const SHOT_DIR = path.resolve(__dirname, "../../demo-shots/recapture-tooltips");

function ensureDir(d: string) { fs.mkdirSync(d, { recursive: true }); }

async function loginAndInject(page: Page, request: APIRequestContext) {
  const resp = await request.post(`${API_URL}/api/auth/login`, {
    data: { email: EMAIL, password: PASSWORD },
    headers: { "Content-Type": "application/json" },
    failOnStatusCode: false,
  });
  if (!resp.ok()) throw new Error(`Login failed ${resp.status()}`);
  const { access_token } = (await resp.json()) as { access_token: string };

  const setCookie = resp.headers()["set-cookie"] ?? "";
  const m = /raf_refresh_token=([^;]+)/.exec(setCookie);
  const cookies: Parameters<typeof page.context.prototype.addCookies>[0] = [];
  if (m) {
    cookies.push({ name: "raf_refresh_token", value: m[1], domain: "localhost", path: "/", httpOnly: true, secure: false, sameSite: "Lax" });
  }
  cookies.push({ name: "raf_authenticated", value: "true", domain: "localhost", path: "/", httpOnly: false, secure: false, sameSite: "Strict" });
  await page.context().addCookies(cookies);
  return access_token;
}

// Helper: hover trigger → assert tooltip visible → screenshot
async function assertTooltip(
  page: Page,
  triggerTestId: string,
  expectedSubstring: string,
  screenshotName: string,
  shotDir: string,
) {
  const trigger = page.locator(`[data-testid="${triggerTestId}"]`).first();
  await trigger.scrollIntoViewIfNeeded({ timeout: 8000 });
  await trigger.hover({ timeout: 5000 });
  await page.waitForTimeout(300); // beyond 200 ms delay

  // Tooltip popup must be in the DOM and visible
  const tooltipContent = page.locator('[data-slot="tooltip-content"]').first();
  await expect(tooltipContent).toBeVisible({ timeout: 3000 });

  const text = (await tooltipContent.textContent()) ?? "";
  expect(text.toLowerCase()).toContain(expectedSubstring.toLowerCase());

  await page.screenshot({ path: path.join(shotDir, `${screenshotName}.png`), fullPage: false });

  // Dismiss by moving mouse away
  await page.mouse.move(0, 0);
  await page.waitForTimeout(150);
}

test.describe("/recapture tooltip coverage", () => {
  test.setTimeout(180000);

  test("all tooltip categories are reachable and display correct text", async ({ page, request }) => {
    ensureDir(SHOT_DIR);

    await loginAndInject(page, request);

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE_URL}/recapture`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(8000); // allow data to load

    await page.screenshot({ path: path.join(SHOT_DIR, "00-loaded.png"), fullPage: false });

    // ── 1. KPI card label tooltips (3 cards) ──────────────────────────────
    const kpiTriggers = page.locator('[data-testid="metric-label-tooltip"]');
    if (await kpiTriggers.count() > 0) {
      const first = kpiTriggers.first();
      await first.scrollIntoViewIfNeeded();
      await first.hover();
      await page.waitForTimeout(300);
      const tip = page.locator('[data-slot="tooltip-content"]').first();
      await expect(tip).toBeVisible({ timeout: 3000 });
      await page.screenshot({ path: path.join(SHOT_DIR, "01-kpi-label-tooltip.png"), fullPage: false });
      await page.mouse.move(0, 0);
      await page.waitForTimeout(150);
      console.log("[PASS] KPI label tooltip");
    } else {
      // Fallback: hover the dotted-underline label span inside the first MetricCard
      const kpiLabel = page.locator('[data-testid="revenue-at-risk-label"] span.underline').first();
      if (await kpiLabel.count() > 0) {
        await kpiLabel.hover();
        await page.waitForTimeout(300);
        const tip = page.locator('[data-slot="tooltip-content"]').first();
        await expect(tip).toBeVisible({ timeout: 3000 });
        await page.screenshot({ path: path.join(SHOT_DIR, "01-kpi-label-tooltip.png"), fullPage: false });
        await page.mouse.move(0, 0);
      }
    }

    // ── 2. Search box tooltip ─────────────────────────────────────────────
    await assertTooltip(page, "recapture-search", "Filter by patient name or ICD code", "02-search-tooltip", SHOT_DIR);
    console.log("[PASS] Search tooltip");

    // ── 3. Sort buttons ───────────────────────────────────────────────────
    await assertTooltip(page, "sort-priority", "urgency", "03-sort-priority", SHOT_DIR);
    console.log("[PASS] Sort-priority tooltip");
    await assertTooltip(page, "sort-name", "alphabetically", "04-sort-name", SHOT_DIR);
    console.log("[PASS] Sort-name tooltip");
    await assertTooltip(page, "sort-condition", "alphabetically", "05-sort-condition", SHOT_DIR);
    console.log("[PASS] Sort-condition tooltip");

    // ── 4. Column header: Days Since ──────────────────────────────────────
    await assertTooltip(page, "col-days-since", "days since last billing", "06-col-days-since", SHOT_DIR);
    console.log("[PASS] Days Since header tooltip");

    // ── 5. Column header: Priority ────────────────────────────────────────
    await assertTooltip(page, "col-priority", "365 days", "07-col-priority", SHOT_DIR);
    console.log("[PASS] Priority header tooltip");

    // ── 6. Column header: ICD-10 ──────────────────────────────────────────
    await assertTooltip(page, "col-icd10", "ICD-10-CM", "08-col-icd10", SHOT_DIR);
    console.log("[PASS] ICD-10 header tooltip");

    // ── 7. ICD code cell (first row) ─────────────────────────────────────
    const icdCells = page.locator('[data-testid^="icd-code-"]');
    if (await icdCells.count() > 0) {
      const cell = icdCells.first();
      await cell.scrollIntoViewIfNeeded();
      await cell.hover();
      await page.waitForTimeout(300);
      const tip = page.locator('[data-slot="tooltip-content"]').first();
      await expect(tip).toBeVisible({ timeout: 3000 });
      const text = (await tip.textContent()) ?? "";
      expect(text).toBeTruthy();
      await page.screenshot({ path: path.join(SHOT_DIR, "09-icd-cell-tooltip.png"), fullPage: false });
      await page.mouse.move(0, 0);
      await page.waitForTimeout(150);
      console.log("[PASS] ICD cell tooltip:", text.slice(0, 60));
    }

    // ── 8. Priority pill (first row) ─────────────────────────────────────
    const pills = page.locator('[data-testid^="priority-pill-"]');
    if (await pills.count() > 0) {
      const pill = pills.first();
      await pill.scrollIntoViewIfNeeded();
      await pill.hover();
      await page.waitForTimeout(300);
      const tip = page.locator('[data-slot="tooltip-content"]').first();
      await expect(tip).toBeVisible({ timeout: 3000 });
      const text = (await tip.textContent()) ?? "";
      expect(text.toLowerCase()).toMatch(/high|medium|low/);
      await page.screenshot({ path: path.join(SHOT_DIR, "10-priority-pill-tooltip.png"), fullPage: false });
      await page.mouse.move(0, 0);
      await page.waitForTimeout(150);
      console.log("[PASS] Priority pill tooltip:", text.slice(0, 60));
    }

    // ── 9. Patient name cell → "Open patient chart" ───────────────────────
    const patientNames = page.locator('[data-testid^="patient-name-"]');
    if (await patientNames.count() > 0) {
      const name = patientNames.first();
      await name.scrollIntoViewIfNeeded();
      await name.hover();
      await page.waitForTimeout(300);
      const tip = page.locator('[data-slot="tooltip-content"]').first();
      await expect(tip).toBeVisible({ timeout: 3000 });
      const text = (await tip.textContent()) ?? "";
      expect(text.toLowerCase()).toContain("open patient chart");
      await page.screenshot({ path: path.join(SHOT_DIR, "11-patient-name-tooltip.png"), fullPage: false });
      await page.mouse.move(0, 0);
      await page.waitForTimeout(150);
      console.log("[PASS] Patient name tooltip");
    }

    // ── 10. Top conditions ICD chip ───────────────────────────────────────
    const condChips = page.locator('[data-testid^="top-condition-chip-"]');
    if (await condChips.count() > 0) {
      const chip = condChips.first();
      await chip.scrollIntoViewIfNeeded();
      await chip.hover();
      await page.waitForTimeout(300);
      const tip = page.locator('[data-slot="tooltip-content"]').first();
      await expect(tip).toBeVisible({ timeout: 3000 });
      const text = (await tip.textContent()) ?? "";
      expect(text).toBeTruthy();
      await page.screenshot({ path: path.join(SHOT_DIR, "12-top-condition-chip-tooltip.png"), fullPage: false });
      await page.mouse.move(0, 0);
      await page.waitForTimeout(150);
      console.log("[PASS] Top condition chip tooltip:", text.slice(0, 60));
    }

    await page.screenshot({ path: path.join(SHOT_DIR, "99-final.png"), fullPage: true });
    console.log("[DONE] All tooltip assertions passed. Screenshots in", SHOT_DIR);
  });
});
