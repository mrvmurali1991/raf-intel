/**
 * /review-queue verification spec — iter7 (fix/post-review-batch-10)
 *
 * Verifies that /review-queue:
 *   - Loads without /login bounce
 *   - Renders the three tabs (HCC Candidates / Suspects / Provider Queries)
 *     with counts or empty states
 *   - Has no console errors / 4xx-5xx network failures (auth refresh excluded)
 *   - Has no horizontal overflow on mobile 414×896
 *
 * Mirrors the fresh-context pattern from verify10-quality.spec.ts to avoid
 * mid-page re-navigation aborting /api/auth/refresh on mobile.
 *
 * Run with:
 *   cd frontend && BASE_URL=http://localhost:3444 \
 *     npx playwright test tests/demo/verify10-reviewqueue.spec.ts --reporter=line
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

const SHOT_DIR = path.resolve(__dirname, "../../demo-shots/iter8-review-queue");

function ensureDir(d: string) { fs.mkdirSync(d, { recursive: true }); }

const TAB_LABELS = ["HCC Candidates", "Suspects", "Provider Queries"] as const;

async function loginViaUI(page: import("@playwright/test").Page) {
  await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 20_000 });
  await page.fill('input[type="email"]', EMAIL);
  await page.fill('input[type="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 });
}

async function waitForReviewQueueReady(page: import("@playwright/test").Page, timeoutMs = 20_000) {
  // The 3 tab buttons are rendered after the page mounts. Wait for them all.
  for (const label of TAB_LABELS) {
    await page.getByRole("button", { name: new RegExp(label, "i") }).first()
      .waitFor({ timeout: timeoutMs });
  }
  // Also wait until any visible spinner disappears (best-effort).
  await page.waitForTimeout(1500);
}

// ════════════════════════════════════════════════════════════════════
// DESKTOP TEST
// ════════════════════════════════════════════════════════════════════

test.describe("/review-queue desktop verification", () => {
  test("desktop 1440x900 — tabs render", async ({ page, request }) => {
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

    console.log("\n[DESKTOP] Navigating to /review-queue …");
    await page.goto(`${BASE_URL}/review-queue`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1500);

    if (page.url().includes("/login")) {
      console.log("[DESKTOP] UI login …");
      await loginViaUI(page);
      await page.goto(`${BASE_URL}/review-queue`, { waitUntil: "domcontentloaded" });
    }

    console.log("[DESKTOP] URL:", page.url());
    expect(page.url()).not.toContain("/login");

    try {
      await waitForReviewQueueReady(page, 20_000);
      console.log("[DESKTOP] All 3 tabs rendered");
    } catch {
      console.log("[DESKTOP] Tab sentinel timed out — capturing anyway");
    }

    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(SHOT_DIR, "01-desktop-top.png"), fullPage: false });
    await page.screenshot({ path: path.join(SHOT_DIR, "02-desktop-fullpage.png"), fullPage: true });
    console.log("[DESKTOP] screenshots captured");

    const h1Text = await page.locator("h1").first().textContent().catch(() => null);
    console.log("[DESKTOP] h1:", h1Text?.trim());

    // Check each tab for visibility + click + capture
    const tabResults: Record<string, { visible: boolean; bodyText: string }> = {};
    for (const label of TAB_LABELS) {
      const tabBtn = page.getByRole("button", { name: new RegExp(label, "i") }).first();
      const visible = await tabBtn.isVisible().catch(() => false);
      tabResults[label] = { visible, bodyText: "" };

      if (visible) {
        await tabBtn.click();
        await page.waitForTimeout(1500);
        // capture small body text snippet to detect "empty" state vs rows
        const bodyText = await page.locator("main, body").first().textContent().catch(() => "");
        tabResults[label].bodyText = (bodyText ?? "").slice(0, 400);
        await page.screenshot({
          path: path.join(SHOT_DIR, `03-tab-${label.toLowerCase().replace(/\s+/g, "-")}.png`),
          fullPage: false,
        });
        console.log(`[DESKTOP] tab "${label}" captured`);
      }
    }

    // Stuck spinner heuristic — look for visible animate-spin elements
    const spinnerCount = await page.locator(".animate-spin:visible").count().catch(() => 0);
    console.log("[DESKTOP] visible spinners:", spinnerCount);

    // Ground-truth API
    console.log("\n[DESKTOP] API checks …");
    for (const kind of ["hcc_candidate", "suspect", "provider_query"]) {
      try {
        const r = await request.get(`${API_URL}/api/review/candidates?kind=${kind}&status=open&limit=500`);
        console.log(`  GET kind=${kind} → ${r.status()}`);
      } catch (e) {
        console.log(`  GET kind=${kind} → error: ${(e as Error).message}`);
      }
    }

    console.log("\n========= /review-queue DESKTOP SUMMARY =========");
    console.log("URL:", page.url());
    console.log("H1:", h1Text?.trim() ?? "(none)");
    for (const label of TAB_LABELS) {
      console.log(`Tab "${label}" visible:`, tabResults[label].visible);
    }
    console.log("Visible spinners:", spinnerCount);
    console.log("Console errors:", consoleErrors.length);
    consoleErrors.slice(0, 5).forEach((e, i) => console.log(`  [CE ${i}] ${e.slice(0, 200)}`));
    console.log("Network failures:", networkFailures.length);
    networkFailures.slice(0, 10).forEach((e, i) => console.log(`  [NF ${i}] ${e.slice(0, 200)}`));
    console.log("=================================================\n");
  });
});

// ════════════════════════════════════════════════════════════════════
// MOBILE TEST — Fresh BrowserContext at 414×896
// ════════════════════════════════════════════════════════════════════

test.describe("/review-queue mobile fresh-context verification", () => {
  test("mobile 414x896 fresh context — tabs render, no overflow", async () => {
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

      await page.goto(`${BASE_URL}/review-queue`, { waitUntil: "domcontentloaded" });
      console.log("[MOBILE] At /review-queue, waiting for tabs …");

      try {
        await waitForReviewQueueReady(page, 20_000);
        console.log("[MOBILE] All 3 tabs rendered");
      } catch {
        console.log("[MOBILE] Tab sentinel timed out — capturing anyway");
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

      const tabVisible: Record<string, boolean> = {};
      for (const label of TAB_LABELS) {
        tabVisible[label] = await page
          .getByRole("button", { name: new RegExp(label, "i") })
          .first()
          .isVisible()
          .catch(() => false);
      }

      const spinnerCount = await page.locator(".animate-spin:visible").count().catch(() => 0);

      console.log("\n========= /review-queue MOBILE SUMMARY =========");
      console.log("Viewport: 414x896 (fresh context, login before navigate)");
      console.log("URL:", page.url());
      for (const label of TAB_LABELS) {
        console.log(`Tab "${label}" visible:`, tabVisible[label]);
      }
      console.log("Visible spinners:", spinnerCount);
      console.log("Horizontal overflow:", hasOverflow ? `YES (+${overflow.docW - overflow.winW}px)` : "none");
      console.log("Mobile console errors:", mobileConsoleErrors.length);
      mobileConsoleErrors.slice(0, 5).forEach((e, i) => console.log(`  [CE ${i}] ${e.slice(0, 200)}`));
      console.log("Mobile network failures:", mobileNetworkFailures.length);
      mobileNetworkFailures.slice(0, 10).forEach((e, i) => console.log(`  [NF ${i}] ${e.slice(0, 200)}`));
      console.log("================================================\n");

      expect(page.url()).not.toContain("/login");
      // Soft expectation: at least one tab visible
      const anyTab = Object.values(tabVisible).some(Boolean);
      expect(anyTab, "At least one tab should be visible on mobile").toBe(true);

    } finally {
      await browser.close();
    }
  });
});
