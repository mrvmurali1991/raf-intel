/**
 * /raf-calculate verification spec — iter7 (fix/post-review-batch-10)
 *
 * Mirrors verify10-quality.spec.ts pattern: desktop 1440x900 + mobile 414x896
 * with fresh BrowserContext for mobile to avoid auth re-navigation races.
 *
 * Run with:
 *   cd frontend && BASE_URL=http://localhost:3444 \
 *     npx playwright test tests/demo/verify10-rafcalc.spec.ts --reporter=line
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
  if (url.includes("/api/auth/me") && (errorText ?? "").includes("ERR_ABORTED")) return true;
  return false;
}


const BASE_URL = process.env.BASE_URL ?? "http://localhost:3444";
const API_URL  = process.env.API_URL  ?? "http://localhost:8500";
const EMAIL    = "admin@raf.health";
const PASSWORD = "Admin@123";

const SHOT_DIR = path.resolve(__dirname, "../../demo-shots/iter7-raf-calculate");

function ensureDir(d: string) { fs.mkdirSync(d, { recursive: true }); }

async function loginViaUI(page: import("@playwright/test").Page) {
  await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 20_000 });
  await page.fill('input[type="email"]', EMAIL);
  await page.fill('input[type="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 });
}

// ══════════════════════════════════════════════════════════════════════════════
// DESKTOP TEST
// ══════════════════════════════════════════════════════════════════════════════

test.describe("/raf-calculate desktop verification", () => {
  test("desktop 1440x900 — calculator UI renders", async ({ page, request }) => {
    ensureDir(SHOT_DIR);
    await page.setViewportSize({ width: 1440, height: 900 });

    const consoleErrors: string[] = [];
    const networkFailures: string[] = [];
    let preLogin = true;

    page.on("pageerror", (err) => console.error("[PAGE ERROR]", err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        // Exclude pre-login auth refresh noise
        if (preLogin && /\/api\/auth\/refresh/i.test(msg.text())) return;
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
      if (s >= 400) {
        if (preLogin && resp.url().includes("/api/auth/")) return;
        if (isNoiseRequest(resp.url())) return;
        const msg = `${s} ${resp.request().method()} ${resp.url()}`;
        networkFailures.push(msg);
        console.error("[HTTP " + s + "]", msg);
      }
    });

    console.log("\n[DESKTOP] Navigating to /raf-calculate …");
    await page.goto(`${BASE_URL}/raf-calculate`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1500);

    if (page.url().includes("/login")) {
      console.log("[DESKTOP] UI login …");
      await loginViaUI(page);
      preLogin = false;
      await page.goto(`${BASE_URL}/raf-calculate`, { waitUntil: "domcontentloaded" });
    } else {
      preLogin = false;
    }

    console.log("[DESKTOP] URL:", page.url());

    // Wait for spinner to disappear / content to settle
    await page.waitForTimeout(3000);

    // Check for stuck spinner
    const spinnerStuck = await page.locator('[role="progressbar"], .MuiCircularProgress-root, [class*="spinner" i], [class*="loading" i]').first().isVisible().catch(() => false);
    console.log("[DESKTOP] Spinner visible after 3s:", spinnerStuck);

    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(SHOT_DIR, "01-desktop-top.png"), fullPage: false });
    await page.screenshot({ path: path.join(SHOT_DIR, "02-desktop-fullpage.png"), fullPage: true });
    console.log("[DESKTOP] screenshots captured");

    const h1Text = await page.locator("h1").first().textContent().catch(() => null);
    const bodyText = await page.locator("body").textContent().catch(() => "");
    console.log("[DESKTOP] h1:", h1Text?.trim());
    console.log("[DESKTOP] body length:", bodyText?.length ?? 0);

    // Heuristic: look for calc-related strings
    const keywords = ["RAF", "Calculate", "HCC", "Score", "Member", "Patient"];
    const found = keywords.filter(k => bodyText?.toLowerCase().includes(k.toLowerCase()));
    console.log("[DESKTOP] Keywords found:", found.join(", "));

    console.log("\n========= /raf-calculate DESKTOP SUMMARY =========");
    console.log("URL:", page.url());
    console.log("H1:", h1Text?.trim() ?? "(none)");
    console.log("Spinner stuck:", spinnerStuck);
    console.log("Console errors:", consoleErrors.length);
    consoleErrors.slice(0, 10).forEach((e, i) => console.log(`  [CE ${i}] ${e.slice(0, 200)}`));
    console.log("Network failures:", networkFailures.length);
    networkFailures.slice(0, 10).forEach((e, i) => console.log(`  [NF ${i}] ${e.slice(0, 200)}`));
    console.log("===========================================\n");
  });
});

// ══════════════════════════════════════════════════════════════════════════════
// MOBILE TEST — Fresh BrowserContext at 414×896
// ══════════════════════════════════════════════════════════════════════════════

test.describe("/raf-calculate mobile fresh-context verification", () => {
  test("mobile 414x896 fresh context — no horizontal overflow", async () => {
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
    let preLogin = true;

    page.on("pageerror", (err) => console.error("[MOBILE PAGE ERROR]", err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        if (preLogin && /\/api\/auth\/refresh/i.test(msg.text())) return;
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
      if (s >= 400) {
        if (preLogin && resp.url().includes("/api/auth/")) return;
        if (isNoiseRequest(resp.url())) return;
        const msg = `${s} ${resp.request().method()} ${resp.url()}`;
        mobileNetworkFailures.push(msg);
        console.log("[MOBILE HTTP]", msg);
      }
    });

    try {
      console.log("\n[MOBILE] Fresh context 414x896 — login …");
      await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" });
      await loginViaUI(page);
      preLogin = false;
      console.log("[MOBILE] Logged in, URL:", page.url());

      await page.goto(`${BASE_URL}/raf-calculate`, { waitUntil: "domcontentloaded" });
      console.log("[MOBILE] At /raf-calculate, settling …");
      await page.waitForTimeout(3500);

      const spinnerStuck = await page.locator('[role="progressbar"], .MuiCircularProgress-root, [class*="spinner" i]').first().isVisible().catch(() => false);

      await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
      await page.waitForTimeout(400);

      await page.screenshot({ path: path.join(SHOT_DIR, "03-mobile-top.png"), fullPage: false });
      await page.screenshot({ path: path.join(SHOT_DIR, "04-mobile-fullpage.png"), fullPage: true });
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

      const h1Text = await page.locator("h1").first().textContent().catch(() => null);

      console.log("\n========= /raf-calculate MOBILE SUMMARY =========");
      console.log("Viewport: 414x896 (fresh context)");
      console.log("URL:", page.url());
      console.log("H1:", h1Text?.trim() ?? "(none)");
      console.log("Spinner stuck:", spinnerStuck);
      console.log("Horizontal overflow:", hasOverflow ? `YES (+${overflow.docW - overflow.winW}px)` : "none");
      console.log("Mobile console errors:", mobileConsoleErrors.length);
      mobileConsoleErrors.slice(0, 10).forEach((e, i) => console.log(`  [CE ${i}] ${e.slice(0, 200)}`));
      console.log("Mobile network failures:", mobileNetworkFailures.length);
      mobileNetworkFailures.slice(0, 10).forEach((e, i) => console.log(`  [NF ${i}] ${e.slice(0, 200)}`));
      console.log("===========================================\n");

      expect(hasOverflow, "No horizontal overflow on 414x896").toBe(false);
    } finally {
      await browser.close();
    }
  });
});
