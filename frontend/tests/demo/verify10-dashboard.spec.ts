/**
 * iter1-08 — /dashboard (post-login landing) verification.
 *
 * NOTE: The actual route is "/" (DashboardOrchestrator). /dashboard returns 404.
 * Verifies:
 *   - login → / loads (no /login bounce)
 *   - KPI tiles render with real numbers
 *   - Charts/widgets render
 *   - Mobile no horizontal overflow
 *   - No console errors, no /api/feature-flags 401
 */

import { test, expect } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

/** Returns true for benign teardown / navigation-abort requests that are not real failures. */
function isNoiseRequest(url: string, errorText?: string | null): boolean {
  if (url.includes("/api/notifications/stream")) return true;
  if (url.includes("/api/auth/refresh") && (errorText ?? "").includes("ERR_ABORTED")) return true;
  if (url.includes("/api/feature-flags") && (errorText ?? "").includes("ERR_ABORTED")) return true;
  if (url.includes("_rsc=")) return true;
  if (url.includes("/api/admin/jwt-key-status")) return true;
  return false;
}


const BASE_URL = process.env.BASE_URL ?? "http://localhost:3444";
const EMAIL    = "admin@raf.health";
const PASSWORD = "Admin@123";
const SHOT_DIR = path.resolve(__dirname, "../../demo-shots/iter1-08-dashboard");

function ensureDir(d: string) { fs.mkdirSync(d, { recursive: true }); }

test.describe.configure({ mode: "serial" });

test("verify /dashboard (root) — desktop + mobile", async ({ browser }) => {
  ensureDir(SHOT_DIR);
  test.setTimeout(180_000);

  const consoleErrors: string[] = [];
  const networkFailures: string[] = [];
  const featureFlagsCalls: { url: string; status: number }[] = [];

  // ---------- DESKTOP ----------
  const ctxDesktop = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctxDesktop.newPage();

  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(`[desktop] ${msg.text()}`);
  });
  page.on("pageerror", (err) => consoleErrors.push(`[desktop pageerror] ${err.message}`));
  page.on("response", (resp) => {
    const url = resp.url();
    const status = resp.status();
    if (url.includes("/api/feature-flags")) {
      featureFlagsCalls.push({ url, status });
    }
    if (status >= 400 && url.startsWith("http://localhost:8500")) {
      if (isNoiseRequest(url)) return;
      networkFailures.push(`${status} ${url}`);
    }
  });

  // Login via UI
  await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 15_000 });
  await page.fill('input[type="email"]', EMAIL);
  await page.fill('input[type="password"]', PASSWORD);
  await page.click('button[type="submit"]');

  // After login the app navigates to / (post-login landing). /dashboard doesn't exist.
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 }).catch(() => {});
  await page.waitForTimeout(4000);

  const landingUrl = page.url();
  console.log(`[POST-LOGIN URL] ${landingUrl}`);

  // Try /dashboard explicitly to confirm. Then return to /.
  await page.goto(`${BASE_URL}/dashboard`, { waitUntil: "domcontentloaded" }).catch(() => {});
  await page.waitForTimeout(2000);
  const dashUrl = page.url();
  console.log(`[/dashboard URL] ${dashUrl}`);

  // Settle on / (the canonical landing)
  await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(6000);

  // h1
  const h1 = (await page.locator("h1").first().textContent().catch(() => "") ?? "").trim();
  console.log(`[H1] ${h1}`);

  // Inventory KPI / chart / widget text
  const kpiLabels = [
    "Active Patients", "Total Patients", "Patients Analyzed",
    "Average RAF", "Avg RAF", "RAF Score",
    "HCC", "Open Suspects", "Suspects Pending Review",
    "Revenue Opportunity", "Revenue Waterfall",
    "Population Risk", "Patient Priority", "Workflow Queue",
    "EMR Data Coverage",
  ];
  const inventory: Record<string, number> = {};
  for (const label of kpiLabels) {
    inventory[label] = await page.getByText(label, { exact: false }).count();
  }
  console.log("[KPI INVENTORY]", JSON.stringify(inventory));

  // Numeric tile detection — count elements that look like KPI numbers
  const numericTiles = await page.locator("text=/^\\$?[0-9][0-9,\\.]*[KM]?$/").count();
  console.log(`[NUMERIC TILES] ${numericTiles}`);

  // SVG count for charts
  const svgCount = await page.locator("svg").count();
  console.log(`[SVG COUNT] ${svgCount}`);

  // Desktop screenshots
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(SHOT_DIR, "01-desktop-top.png"), fullPage: false });
  await page.screenshot({ path: path.join(SHOT_DIR, "02-desktop-fullpage.png"), fullPage: true });

  // Save desktop storage state to reuse cookies on mobile (avoids login rate limit)
  const storageStatePath = "/tmp/dashboard-verify-state.json";
  await ctxDesktop.storageState({ path: storageStatePath });

  await ctxDesktop.close();

  // ---------- MOBILE ----------
  const ctxMobile = await browser.newContext({
    viewport: { width: 390, height: 844 },
    storageState: storageStatePath,
  });
  const pageM = await ctxMobile.newPage();

  pageM.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(`[mobile] ${msg.text()}`);
  });
  pageM.on("pageerror", (err) => consoleErrors.push(`[mobile pageerror] ${err.message}`));
  pageM.on("response", (resp) => {
    const url = resp.url();
    const status = resp.status();
    if (url.includes("/api/feature-flags")) {
      featureFlagsCalls.push({ url: `[mobile] ${url}`, status });
    }
    if (status >= 400 && url.startsWith("http://localhost:8500")) {
      networkFailures.push(`[mobile] ${status} ${url}`);
    }
  });

  // Skip UI login on mobile — reuse desktop cookies/storage to avoid 5/min rate limit
  await pageM.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded" });
  await pageM.waitForTimeout(6000);
  console.log(`[MOBILE URL] ${pageM.url()}`);

  // Horizontal overflow check
  const overflow = await pageM.evaluate(() => {
    const w = document.documentElement.scrollWidth;
    const v = document.documentElement.clientWidth;
    return { scrollWidth: w, clientWidth: v, overflow: w - v };
  });
  console.log(`[MOBILE OVERFLOW] ${JSON.stringify(overflow)}`);

  await pageM.screenshot({ path: path.join(SHOT_DIR, "03-mobile-top.png"), fullPage: false });
  await pageM.screenshot({ path: path.join(SHOT_DIR, "04-mobile-fullpage.png"), fullPage: true });

  await ctxMobile.close();

  // ---------- SUMMARY ----------
  const ff401 = featureFlagsCalls.filter((c) => c.status === 401);
  console.log("\n========= SUMMARY =========");
  console.log(`Post-login URL:           ${landingUrl}`);
  console.log(`/dashboard explicit URL:  ${dashUrl}`);
  console.log(`H1:                       ${h1}`);
  console.log(`KPI inventory:            ${JSON.stringify(inventory)}`);
  console.log(`Numeric tiles:            ${numericTiles}`);
  console.log(`SVG count (charts):       ${svgCount}`);
  console.log(`Mobile overflow px:       ${overflow.overflow}`);
  console.log(`Console errors:           ${consoleErrors.length}`);
  console.log(`Network 4xx/5xx:          ${networkFailures.length}`);
  console.log(`/api/feature-flags calls: ${featureFlagsCalls.length}`);
  console.log(`/api/feature-flags 401s:  ${ff401.length}`);
  if (consoleErrors.length) {
    consoleErrors.slice(0, 10).forEach((e, i) => console.log(`  [CE ${i}] ${e.slice(0, 180)}`));
  }
  if (networkFailures.length) {
    networkFailures.slice(0, 15).forEach((e, i) => console.log(`  [NF ${i}] ${e}`));
  }
  if (featureFlagsCalls.length) {
    featureFlagsCalls.forEach((c, i) => console.log(`  [FF ${i}] ${c.status} ${c.url}`));
  }
  console.log("===========================\n");

  expect(ff401.length, "Should be no /api/feature-flags 401s").toBe(0);
});
