/**
 * /worklist 360° verification spec.
 *
 * THROWAWAY — delete before any commit.
 *
 * Run:
 *   cd frontend && npx playwright test tests/demo/verify10-worklist.spec.ts \
 *       --config playwright.demo.config.ts
 */

import { test } from "@playwright/test";
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

const SHOT_DIR = path.resolve(__dirname, "../../demo-shots/iter8-worklist");

function ensureDir(d: string) { fs.mkdirSync(d, { recursive: true }); }

const consoleErrors: string[] = [];
const pageErrors:    string[] = [];
const networkFailures: { url: string; status: number }[] = [];
let loggedIn = false;

test.describe("/worklist verification", () => {
  test("capture + inspect /worklist", async ({ page }) => {
    test.setTimeout(180_000);
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
    page.on("response", (resp) => {
      const url = resp.url();
      const status = resp.status();
      if (status >= 400 && url.includes("/api/")) {
        // Allow pre-login auth/refresh failures and SSE aborts
        if (!loggedIn && url.includes("/api/auth/refresh")) return;
        if (url.includes("/sse") || url.includes("/events") || url.includes("/stream")) return;
        if (isNoiseRequest(url)) return;
        networkFailures.push({ url, status });
      }
    });

    // ----- Auth -----
    await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 15_000 });
    await page.fill('input[type="email"]', EMAIL);
    await page.fill('input[type="password"]', PASSWORD);
    await page.click('button[type="submit"]');
    try {
      await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 });
      loggedIn = true;
    } catch {
      console.warn("[AUTH] waitForURL timed out; current URL:", page.url());
    }
    await page.waitForTimeout(1500);
    loggedIn = true;

    // ----- Navigate -----
    await page.goto(`${BASE_URL}/worklist`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(1000);
    const bouncedToLogin = page.url().includes("/login");
    console.log("[STEP] URL after nav:", page.url(), "bouncedToLogin=", bouncedToLogin);

    // wait for data
    await page.waitForTimeout(7000);

    // ----- Spinner check (after wait, no infinite spinner) -----
    const spinnerCount = await page.locator('[class*="spinner" i], [class*="loading" i], [role="progressbar"]').count();
    console.log("[INFO] spinner-like elements after wait:", spinnerCount);

    // ----- Desktop screenshots -----
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(SHOT_DIR, "01-desktop-top.png"), fullPage: false });
    console.log("[SHOT] 01-desktop-top.png");

    const h1 = await page.locator("h1, h2").first().textContent().catch(() => null);
    console.log("[INFO] heading:", h1?.trim());

    await page.screenshot({ path: path.join(SHOT_DIR, "02-desktop-fullpage.png"), fullPage: true });
    console.log("[SHOT] 02-desktop-fullpage.png");

    // ----- Body text sanity (no [object Object] / undefined leakage) -----
    const bodyText = (await page.locator("body").innerText().catch(() => "")) || "";
    const undefinedCount = (bodyText.match(/\bundefined\b/g) || []).length;
    const objectObjectCount = (bodyText.match(/\[object Object\]/g) || []).length;
    const nanCount = (bodyText.match(/\bNaN\b/g) || []).length;
    console.log("[BODY-LEAK]", JSON.stringify({ undefinedCount, objectObjectCount, nanCount }));

    // ----- Look for table rows or empty state -----
    const rowCount = await page.locator('table tbody tr, [role="row"]').count();
    const emptyStateHits: Record<string, number> = {};
    for (const phrase of ["No items", "No worklist", "No data", "Nothing to review", "All caught up", "Empty"]) {
      emptyStateHits[phrase] = await page.getByText(phrase, { exact: false }).count();
    }
    console.log("[ROWS] table/grid rows:", rowCount);
    console.log("[EMPTY-STATE]", JSON.stringify(emptyStateHits));

    // ----- Mobile 414×896 -----
    await page.setViewportSize({ width: 414, height: 896 });
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
    await page.waitForTimeout(1200);
    await page.screenshot({ path: path.join(SHOT_DIR, "03-mobile-top.png"), fullPage: false });
    await page.screenshot({ path: path.join(SHOT_DIR, "04-mobile-fullpage.png"), fullPage: true });
    console.log("[SHOT] 03-mobile-top.png + 04-mobile-fullpage.png");

    const overflowInfo = await page.evaluate(() => {
      const docW = document.documentElement.scrollWidth;
      const viewW = window.innerWidth;
      const overflowing: { tag: string; cls: string; w: number }[] = [];
      const els = Array.from(document.querySelectorAll<HTMLElement>("*"));
      for (const el of els) {
        const rect = el.getBoundingClientRect();
        if (rect.width > viewW + 5) {
          overflowing.push({
            tag: el.tagName,
            cls: (el.className || "").toString().slice(0, 80),
            w: Math.round(rect.width),
          });
          if (overflowing.length >= 10) break;
        }
      }
      return { docW, viewW, pageOverflow: Math.max(0, docW - viewW), overflowing };
    });
    console.log("[OVERFLOW]", JSON.stringify(overflowInfo));

    // ----- Final summary -----
    console.log("\n========= /worklist VERIFICATION =========");
    console.log(`URL:                 ${page.url()}`);
    console.log(`bouncedToLogin:      ${bouncedToLogin}`);
    console.log(`heading:             ${h1?.trim()}`);
    console.log(`spinner elements:    ${spinnerCount}`);
    console.log(`row count:           ${rowCount}`);
    console.log(`API failures:        ${networkFailures.length}`);
    networkFailures.slice(0, 10).forEach((f, i) => console.log(`  [NF ${i}] ${f.status} ${f.url}`));
    console.log(`Console errors:      ${consoleErrors.length}`);
    consoleErrors.slice(0, 8).forEach((e, i) => console.log(`  [CE ${i}] ${e.slice(0, 200)}`));
    console.log(`Page JS errors:      ${pageErrors.length}`);
    pageErrors.slice(0, 5).forEach((e, i) => console.log(`  [PE ${i}] ${e.slice(0, 200)}`));
    console.log(`Body leaks:          undefined=${undefinedCount} [object Object]=${objectObjectCount} NaN=${nanCount}`);
    console.log(`Mobile overflow:     docW=${overflowInfo.docW} viewW=${overflowInfo.viewW} pageOverflow=${overflowInfo.pageOverflow} count=${overflowInfo.overflowing.length}`);
    console.log(`Screenshots:         ${SHOT_DIR}`);
    console.log("===========================================\n");
  });
});
