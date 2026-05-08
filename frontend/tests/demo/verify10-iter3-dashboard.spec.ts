/**
 * iter3-08 — admin dashboard verification (post-fix c608bb5).
 *
 * Verifies fixes from iter2:
 *  - mobile (414px) scrollWidth === 414 (no horizontal overflow)
 *  - H1 boundingBox.x >= 60 (clear of hamburger right edge)
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
const SHOT_DIR = path.resolve(__dirname, "../../demo-shots/iter3-08-dashboard");

function ensureDir(d: string) { fs.mkdirSync(d, { recursive: true }); }

test.describe.configure({ mode: "serial" });

test("iter3 verify dashboard — desktop + mobile 414px", async ({ browser }) => {
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

  await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 15_000 });
  await page.fill('input[type="email"]', EMAIL);
  await page.fill('input[type="password"]', PASSWORD);
  await page.click('button[type="submit"]');

  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 }).catch(() => {});
  await page.waitForTimeout(4000);

  const landingUrl = page.url();
  console.log(`[POST-LOGIN URL] ${landingUrl}`);

  await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(6000);

  const h1 = (await page.locator("h1").first().textContent().catch(() => "") ?? "").trim();
  console.log(`[H1] ${h1}`);

  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(SHOT_DIR, "01-desktop-top.png"), fullPage: false });
  await page.screenshot({ path: path.join(SHOT_DIR, "02-desktop-fullpage.png"), fullPage: true });

  const storageStatePath = "/tmp/iter3-dashboard-state.json";
  await ctxDesktop.storageState({ path: storageStatePath });
  await ctxDesktop.close();

  // ---------- MOBILE 414px ----------
  const ctxMobile = await browser.newContext({
    viewport: { width: 414, height: 896 },
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

  await pageM.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded" });
  await pageM.waitForTimeout(6000);
  console.log(`[MOBILE URL] ${pageM.url()}`);

  const overflow = await pageM.evaluate(() => {
    const w = document.documentElement.scrollWidth;
    const v = document.documentElement.clientWidth;
    return { scrollWidth: w, clientWidth: v, overflow: w - v };
  });
  console.log(`[MOBILE OVERFLOW] ${JSON.stringify(overflow)}`);

  const h1Box = await pageM.locator("h1").first().boundingBox();
  console.log(`[MOBILE H1 BOX] ${JSON.stringify(h1Box)}`);

  const h1Text = (await pageM.locator("h1").first().textContent().catch(() => "") ?? "").trim();
  console.log(`[MOBILE H1 TEXT] ${h1Text}`);

  const hamburgerRight = await pageM.evaluate(() => {
    const btn = document.querySelector('[aria-label*="menu" i], [aria-label*="navigation" i], button.hamburger, .hamburger');
    if (!btn) return null;
    const r = btn.getBoundingClientRect();
    return { left: r.left, right: r.right, width: r.width };
  });
  console.log(`[MOBILE HAMBURGER] ${JSON.stringify(hamburgerRight)}`);

  await pageM.screenshot({ path: path.join(SHOT_DIR, "03-mobile-top.png"), fullPage: false });
  await pageM.screenshot({ path: path.join(SHOT_DIR, "04-mobile-fullpage.png"), fullPage: true });

  await ctxMobile.close();

  const ff401 = featureFlagsCalls.filter((c) => c.status === 401);
  console.log("\n========= ITER3 SUMMARY =========");
  console.log(`Desktop H1:               ${h1}`);
  console.log(`Mobile H1:                ${h1Text}`);
  console.log(`Mobile H1 box:            ${JSON.stringify(h1Box)}`);
  console.log(`Mobile hamburger:         ${JSON.stringify(hamburgerRight)}`);
  console.log(`Mobile overflow px:       ${overflow.overflow}`);
  console.log(`Mobile scrollWidth:       ${overflow.scrollWidth}`);
  console.log(`Console errors:           ${consoleErrors.length}`);
  console.log(`Network 4xx/5xx:          ${networkFailures.length}`);
  console.log(`/api/feature-flags 401s:  ${ff401.length}`);
  if (consoleErrors.length) {
    consoleErrors.slice(0, 10).forEach((e, i) => console.log(`  [CE ${i}] ${e.slice(0, 220)}`));
  }
  if (networkFailures.length) {
    networkFailures.slice(0, 15).forEach((e, i) => console.log(`  [NF ${i}] ${e}`));
  }
  if (featureFlagsCalls.length) {
    featureFlagsCalls.forEach((c, i) => console.log(`  [FF ${i}] ${c.status} ${c.url}`));
  }
  console.log("==================================\n");

  expect(ff401.length, "Should be no /api/feature-flags 401s").toBe(0);
  expect(overflow.overflow, "Should be no horizontal overflow").toBeLessThanOrEqual(0);
  if (h1Box) {
    expect(h1Box.x, "H1 x should be >= 60 (clear of hamburger)").toBeGreaterThanOrEqual(60);
  }
});
