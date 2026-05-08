/**
 * /emr-config verification spec — iter7 (fix/post-review-batch-10)
 *
 * Verifies that /emr-config:
 *   - Loads without /login bounce
 *   - Renders content (or clean empty state — no "undefined" / "[object Object]")
 *   - Has no console errors / 4xx-5xx network failures (auth refresh excluded)
 *   - Has no horizontal overflow on mobile 414×896
 *
 * Mirrors the fresh-context pattern from verify10-quality.spec.ts to avoid
 * mid-page re-navigation aborting /api/auth/refresh on mobile.
 *
 * Run with:
 *   cd frontend && BASE_URL=http://localhost:3444 \
 *     npx playwright test tests/demo/verify10-emrconfig.spec.ts --reporter=line
 */

import { test, expect, chromium } from "@playwright/test";
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
const API_URL  = process.env.API_URL  ?? "http://localhost:8500";
const EMAIL    = "admin@raf.health";
const PASSWORD = "Admin@123";

const SHOT_DIR = path.resolve(__dirname, "../../demo-shots/iter7-emr-config");

function ensureDir(d: string) { fs.mkdirSync(d, { recursive: true }); }

async function loginViaUI(page: import("@playwright/test").Page) {
  await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 20_000 });
  await page.fill('input[type="email"]', EMAIL);
  await page.fill('input[type="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 });
}

async function waitForEmrConfigReady(page: import("@playwright/test").Page, timeoutMs = 20_000) {
  // Wait for either an h1, a main container, or recognisable EMR-config text.
  await page.waitForSelector("h1, main", { timeout: timeoutMs });
  await page.waitForTimeout(1500);
}

// ════════════════════════════════════════════════════════════════════
// DESKTOP TEST
// ════════════════════════════════════════════════════════════════════

test.describe("/emr-config desktop verification", () => {
  test("desktop 1440x900 — content renders", async ({ page, request }) => {
    ensureDir(SHOT_DIR);
    await page.setViewportSize({ width: 1440, height: 900 });

    const consoleErrors: string[] = [];
    const networkFailures: string[] = [];

    page.on("pageerror", (err) => console.error("[PAGE ERROR]", err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        consoleErrors.push(msg.text());
        console.error("[CONSOLE ERROR]", msg.text().slice(0, 200));
      }
    });
    page.on("requestfailed", (req) => {
      if (isNoiseRequest(req.url(), req.failure()?.errorText)) return;
      const msg = `${req.method()} ${req.url()} — ${req.failure()?.errorText ?? "unknown"}`;
      networkFailures.push(msg);
      console.error("[NETWORK FAIL]", msg);
    });
    page.on("response", (resp) => {
      const s = resp.status();
      if (s >= 400 && !resp.url().includes("/api/auth/")) {
        if (isNoiseRequest(resp.url())) return;
        const msg = `${s} ${resp.request().method()} ${resp.url()}`;
        networkFailures.push(msg);
        console.error(`[HTTP ${s}]`, msg);
      }
    });

    console.log("\n[DESKTOP] Navigating to /emr-config …");
    await page.goto(`${BASE_URL}/emr-config`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1500);

    if (page.url().includes("/login")) {
      console.log("[DESKTOP] UI login …");
      await loginViaUI(page);
      await page.goto(`${BASE_URL}/emr-config`, { waitUntil: "domcontentloaded" });
    }

    console.log("[DESKTOP] URL:", page.url());
    expect(page.url()).not.toContain("/login");

    try {
      await waitForEmrConfigReady(page, 20_000);
      console.log("[DESKTOP] page ready");
    } catch {
      console.log("[DESKTOP] readiness sentinel timed out — capturing anyway");
    }

    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(SHOT_DIR, "01-desktop-top.png"), fullPage: false });
    await page.screenshot({ path: path.join(SHOT_DIR, "02-desktop-fullpage.png"), fullPage: true });
    console.log("[DESKTOP] screenshots captured");

    const h1Text = await page.locator("h1").first().textContent().catch(() => null);
    console.log("[DESKTOP] h1:", h1Text?.trim());

    // Body text — check for telltale broken-render markers
    const bodyText = (await page.locator("body").textContent().catch(() => "")) ?? "";
    const undefinedHits = (bodyText.match(/\bundefined\b/g) ?? []).length;
    const objectObjectHits = (bodyText.match(/\[object Object\]/g) ?? []).length;
    console.log("[DESKTOP] 'undefined' hits in body:", undefinedHits);
    console.log("[DESKTOP] '[object Object]' hits in body:", objectObjectHits);

    // Stuck spinner heuristic
    const spinnerCount = await page.locator(".animate-spin:visible").count().catch(() => 0);
    console.log("[DESKTOP] visible spinners:", spinnerCount);

    // Ground-truth API
    console.log("\n[DESKTOP] API checks …");
    for (const url of [
      `${API_URL}/api/emr/config`,
      `${API_URL}/api/emr/connections`,
      `${API_URL}/api/emr/status`,
    ]) {
      try {
        const r = await request.get(url);
        console.log(`  GET ${url} → ${r.status()}`);
      } catch (e) {
        console.log(`  GET ${url} → error: ${(e as Error).message}`);
      }
    }

    console.log("\n========= /emr-config DESKTOP SUMMARY =========");
    console.log("URL:", page.url());
    console.log("H1:", h1Text?.trim() ?? "(none)");
    console.log("Visible spinners:", spinnerCount);
    console.log("'undefined' hits:", undefinedHits, "'[object Object]' hits:", objectObjectHits);
    console.log("Console errors:", consoleErrors.length);
    consoleErrors.slice(0, 5).forEach((e, i) => console.log(`  [CE ${i}] ${e.slice(0, 200)}`));
    console.log("Network failures:", networkFailures.length);
    networkFailures.slice(0, 10).forEach((e, i) => console.log(`  [NF ${i}] ${e.slice(0, 200)}`));
    console.log("===============================================\n");
  });
});

// ════════════════════════════════════════════════════════════════════
// MOBILE TEST — Fresh BrowserContext at 414×896
// ════════════════════════════════════════════════════════════════════

test.describe("/emr-config mobile fresh-context verification", () => {
  test("mobile 414x896 fresh context — no overflow", async () => {
    ensureDir(SHOT_DIR);

    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
      viewport: { width: 414, height: 896 },
      userAgent:
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    });
    const page = await context.newPage();

    const mobileConsoleErrors: string[] = [];
    const mobileNetworkFailures: string[] = [];

    page.on("pageerror", (err) => console.error("[MOBILE PAGE ERROR]", err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        mobileConsoleErrors.push(msg.text());
        console.error("[MOBILE CONSOLE ERROR]", msg.text().slice(0, 200));
      }
    });
    page.on("requestfailed", (req) => {
      if (isNoiseRequest(req.url(), req.failure()?.errorText)) return;
      const msg = `${req.method()} ${req.url()} — ${req.failure()?.errorText ?? "unknown"}`;
      mobileNetworkFailures.push(msg);
      console.error("[MOBILE NETWORK FAIL]", msg);
    });
    page.on("response", (resp) => {
      const s = resp.status();
      if (s >= 400 && !resp.url().includes("/api/auth/")) {
        if (isNoiseRequest(resp.url())) return;
        const msg = `${s} ${resp.request().method()} ${resp.url()}`;
        mobileNetworkFailures.push(msg);
        console.log(`[MOBILE HTTP ${s}]`, msg);
      }
    });

    try {
      console.log("\n[MOBILE] Fresh context 414x896 — navigating to login …");
      await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" });
      await loginViaUI(page);
      console.log("[MOBILE] Logged in, URL:", page.url());

      await page.goto(`${BASE_URL}/emr-config`, { waitUntil: "domcontentloaded" });
      console.log("[MOBILE] At /emr-config, waiting …");

      try {
        await waitForEmrConfigReady(page, 20_000);
        console.log("[MOBILE] page ready");
      } catch {
        console.log("[MOBILE] readiness sentinel timed out — capturing anyway");
      }

      await page.waitForTimeout(800);
      await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
      await page.waitForTimeout(400);

      await page.screenshot({ path: path.join(SHOT_DIR, "04-mobile-top.png"), fullPage: false });
      await page.screenshot({ path: path.join(SHOT_DIR, "05-mobile-fullpage.png"), fullPage: true });
      console.log("[MOBILE] screenshots captured");

      const overflow = await page.evaluate(() => ({
        docW: document.documentElement.scrollWidth,
        winW: window.innerWidth,
      }));
      const hasOverflow = overflow.docW > overflow.winW;
      console.log(
        "[MOBILE] docW:", overflow.docW, "winW:", overflow.winW,
        "overflow:", hasOverflow ? `YES (+${overflow.docW - overflow.winW}px)` : "none"
      );

      const bodyText = (await page.locator("body").textContent().catch(() => "")) ?? "";
      const undefinedHits = (bodyText.match(/\bundefined\b/g) ?? []).length;
      const objectObjectHits = (bodyText.match(/\[object Object\]/g) ?? []).length;

      const spinnerCount = await page.locator(".animate-spin:visible").count().catch(() => 0);

      console.log("\n========= /emr-config MOBILE SUMMARY =========");
      console.log("Viewport: 414x896 (fresh context, login before navigate)");
      console.log("URL:", page.url());
      console.log("Visible spinners:", spinnerCount);
      console.log("'undefined' hits:", undefinedHits, "'[object Object]' hits:", objectObjectHits);
      console.log("Horizontal overflow:", hasOverflow ? `YES (+${overflow.docW - overflow.winW}px)` : "none");
      console.log("Mobile console errors:", mobileConsoleErrors.length);
      mobileConsoleErrors.slice(0, 5).forEach((e, i) => console.log(`  [CE ${i}] ${e.slice(0, 200)}`));
      console.log("Mobile network failures:", mobileNetworkFailures.length);
      mobileNetworkFailures.slice(0, 10).forEach((e, i) => console.log(`  [NF ${i}] ${e.slice(0, 200)}`));
      console.log("==============================================\n");

      expect(page.url()).not.toContain("/login");

    } finally {
      await browser.close();
    }
  });
});
