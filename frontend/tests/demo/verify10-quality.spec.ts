/**
 * /quality verification spec — iter1-06
 *
 * Run with:
 *   cd frontend && npx playwright test tests/demo/verify10-quality.spec.ts \
 *       --config playwright.demo.config.ts
 */

import { test } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3444";
const API_URL  = process.env.API_URL  ?? "http://localhost:8500";
const EMAIL    = "admin@raf.health";
const PASSWORD = "Admin@123";

const SHOT_DIR = path.resolve(__dirname, "../../demo-shots/iter4-06-quality");
const FRESH_AUTH_STATE_PATH = "/tmp/fresh-auth-state.json";

function ensureDir(d: string) { fs.mkdirSync(d, { recursive: true }); }

const consoleErrors: string[] = [];
const pageErrors:    string[] = [];
const networkFailures: string[] = [];

test.describe("/quality verification", () => {
  test("desktop + mobile capture", async ({ page, request }) => {
    ensureDir(SHOT_DIR);

    page.on("pageerror", (err) => {
      pageErrors.push(err.message);
      console.error("[PAGE ERROR]", err.message);
    });
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        consoleErrors.push(msg.text());
        console.error("[CONSOLE ERROR]", msg.text().slice(0, 200));
      }
    });
    page.on("requestfailed", (req) => {
      const failure = req.failure();
      const msg = `${req.method()} ${req.url()} — ${failure?.errorText ?? "unknown"}`;
      networkFailures.push(msg);
      console.error("[NETWORK FAIL]", msg);
    });
    page.on("response", (resp) => {
      const status = resp.status();
      if (status >= 500) {
        const msg = `${status} ${resp.request().method()} ${resp.url()}`;
        networkFailures.push(msg);
        console.error("[HTTP " + status + "]", msg);
      }
    });

    // ──── Auth ────
    console.log("\n[STEP 1] Auth …");
    if (fs.existsSync(FRESH_AUTH_STATE_PATH)) {
      try {
        const rawState = JSON.parse(fs.readFileSync(FRESH_AUTH_STATE_PATH, "utf-8")) as {
          cookies: Array<{
            name: string; value: string; domain: string; path: string;
            expires: number; httpOnly: boolean; secure: boolean; sameSite: string;
          }>;
        };
        await page.context().addCookies(rawState.cookies as Parameters<typeof page.context.addCookies>[0]);
        console.log("[STEP 1] cookies injected from", FRESH_AUTH_STATE_PATH);
      } catch (e) {
        console.log("[STEP 1] could not load fresh state:", (e as Error).message);
      }
    }

    await page.goto(`${BASE_URL}/quality`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2500);

    if (page.url().includes("/login")) {
      console.log("[STEP 1] UI login fallback …");
      await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 15_000 });
      await page.fill('input[type="email"]', EMAIL);
      await page.fill('input[type="password"]', PASSWORD);
      await page.click('button[type="submit"]');
      try {
        await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 });
      } catch {
        console.log("[STEP 1] login waitURL timed out");
      }
      await page.goto(`${BASE_URL}/quality`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(2500);
    }

    console.log("[STEP 1] URL:", page.url());

    // ──── Wait for mount ────
    console.log("\n[STEP 2] Waiting for React mount …");
    try {
      await page.waitForSelector('h1, [role="alert"], [class*="PageHeader"]', { timeout: 30_000 });
    } catch {
      console.log("[STEP 2] no h1/alert/PageHeader within 30s");
    }
    await page.waitForTimeout(5000);

    // ──── Desktop screenshots ────
    console.log("\n[STEP 3] Desktop screenshots …");
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(SHOT_DIR, "01-desktop-top.png"), fullPage: false });
    await page.screenshot({ path: path.join(SHOT_DIR, "02-desktop-fullpage.png"), fullPage: true });

    const h1Text = await page.locator("h1").first().textContent().catch(() => null);
    console.log("[STEP 3] h1:", h1Text?.trim());

    // ──── Quality content presence ────
    console.log("\n[STEP 4] Inventory …");
    const checks: Array<[string, string]> = [
      ["Quality / STARS heading", "Quality"],
      ["STARS rating",  "STARS"],
      ["HEDIS",         "HEDIS"],
      ["Care Gaps",     "Care Gap"],
      ["Summary tab",   "Summary"],
      ["Measures",      "Measures"],
    ];
    for (const [label, txt] of checks) {
      const cnt = await page.getByText(txt, { exact: false }).count();
      console.log(`[STEP 4] ${label}: ${cnt > 0 ? "PRESENT (" + cnt + ")" : "ABSENT"}`);
    }

    // KPI / metric tiles
    const statCards = await page.locator('[class*="StatCard"], [data-testid*="stat"], [class*="card"]').count();
    console.log("[STEP 4] card-like elements:", statCards);

    // ──── Try clicking tabs (Stars, HEDIS, Care Gaps) for additional shots ────
    const tabsToTry = ["Stars", "HEDIS", "Care Gaps", "Summary"];
    for (const tabLabel of tabsToTry) {
      const tab = page.getByRole("tab", { name: new RegExp(tabLabel, "i") }).first();
      const cnt = await tab.count();
      if (cnt > 0) {
        try {
          await tab.click({ timeout: 5000 });
          await page.waitForTimeout(1500);
          await page.screenshot({
            path: path.join(SHOT_DIR, `03-tab-${tabLabel.toLowerCase().replace(/\s+/g, "-")}.png`),
            fullPage: false,
          });
          console.log(`[STEP 4] tab "${tabLabel}" captured`);
        } catch (e) {
          console.log(`[STEP 4] tab "${tabLabel}" click failed:`, (e as Error).message);
        }
      }
    }

    // ──── Mobile (414x896) ────
    // Navigate fresh at the new viewport.  Auth init + cold query cache can
    // take 6-9 s on the first load, so wait for the page header (h1) or the
    // KPI strip to appear rather than relying on a fixed 5 s sleep.
    console.log("\n[STEP 5] Mobile viewport …");
    await page.setViewportSize({ width: 414, height: 896 });
    await page.goto(`${BASE_URL}/quality`, { waitUntil: "domcontentloaded" });
    // Wait up to 15 s for the quality page header or KPI content to appear.
    try {
      await page.waitForFunction(
        () =>
          document.body.innerText.includes("Total Measures") ||
          document.body.innerText.includes("STARS Estimate") ||
          document.body.innerText.includes("Quality Measures"),
        { timeout: 15_000 }
      );
      console.log("[STEP 5] content appeared");
    } catch {
      console.log("[STEP 5] content did not appear within 15 s — capturing anyway");
    }
    await page.waitForTimeout(800); // settle animations
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(SHOT_DIR, "04-mobile-top.png"), fullPage: false });
    await page.screenshot({ path: path.join(SHOT_DIR, "05-mobile-fullpage.png"), fullPage: true });

    // overflow check: docElement.scrollWidth vs window.innerWidth
    const overflow = await page.evaluate(() => ({
      docW: document.documentElement.scrollWidth,
      winW: window.innerWidth,
    }));
    console.log("[STEP 5] mobile docW:", overflow.docW, "winW:", overflow.winW,
      "overflow:", overflow.docW > overflow.winW ? "YES (" + (overflow.docW - overflow.winW) + "px)" : "no");

    // ──── API ground-truth ────
    console.log("\n[STEP 6] API checks …");
    for (const url of [
      `${API_URL}/api/quality/summary`,
      `${API_URL}/api/quality/measures`,
      `${API_URL}/api/quality/stars`,
      `${API_URL}/api/quality/care-gaps`,
    ]) {
      try {
        const r = await request.get(url);
        console.log(`[STEP 6] GET ${url} → ${r.status()}`);
      } catch (e) {
        console.log(`[STEP 6] GET ${url} → error: ${(e as Error).message}`);
      }
    }

    // ──── Summary ────
    console.log("\n========= /quality VERIFY SUMMARY =========");
    console.log(`URL:                ${page.url()}`);
    console.log(`H1:                 ${h1Text?.trim() ?? "(none)"}`);
    console.log(`Console errors:     ${consoleErrors.length}`);
    console.log(`Page JS errors:     ${pageErrors.length}`);
    console.log(`Network failures:   ${networkFailures.length}`);
    console.log(`Mobile overflow:    ${overflow.docW > overflow.winW ? "YES" : "NO"}`);
    console.log(`Shots dir:          ${SHOT_DIR}`);
    if (consoleErrors.length > 0) {
      console.log("-- console errors (first 8) --");
      consoleErrors.slice(0, 8).forEach((e, i) => console.log(`  [CE ${i}] ${e.slice(0, 180)}`));
    }
    if (pageErrors.length > 0) {
      console.log("-- page JS errors --");
      pageErrors.slice(0, 8).forEach((e, i) => console.log(`  [PE ${i}] ${e.slice(0, 180)}`));
    }
    if (networkFailures.length > 0) {
      console.log("-- network failures --");
      networkFailures.slice(0, 8).forEach((e, i) => console.log(`  [NF ${i}] ${e.slice(0, 180)}`));
    }
    console.log("===========================================\n");
  });
});
