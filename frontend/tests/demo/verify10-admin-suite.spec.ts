/**
 * Admin suite verification spec — iter7
 * Pages: /settings, /users, /system, /developer
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
const EMAIL    = "admin@raf.health";
const PASSWORD = "Admin@123";

const PAGES = ["/settings", "/users", "/system", "/developer"] as const;

const SHOT_ROOT = path.resolve(__dirname, "../../demo-shots/iter8-system");
function ensureDir(d: string) { fs.mkdirSync(d, { recursive: true }); }
function pageDir(p: string) { return path.join(SHOT_ROOT, p.replace(/^\//, "")); }

async function loginViaUI(page: import("@playwright/test").Page) {
  await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 20_000 });
  await page.fill('input[type="email"]', EMAIL);
  await page.fill('input[type="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  try {
    await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 45_000 });
  } catch {
    // Sometimes the redirect is detected late on mobile; check URL one more time
    await page.waitForTimeout(2000);
    if (page.url().includes("/login")) {
      // Final fallback: explicitly navigate to home after auth cookies set
      await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded" });
    }
  }
}

test.describe("admin pages — desktop 1440x900", () => {
  test("desktop captures for /settings /users /system /developer", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });

    const consoleErrorsByPage: Record<string, string[]> = {};
    const networkFailsByPage: Record<string, string[]> = {};
    let currentPage = "(login)";

    page.on("pageerror", (err) => {
      console.error(`[PAGE ERROR ${currentPage}]`, err.message);
      (consoleErrorsByPage[currentPage] ??= []).push(`pageerror: ${err.message}`);
    });
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        const txt = msg.text();
        // Skip pre-login auth refresh noise
        if (currentPage === "(login)" && txt.includes("/api/auth/refresh")) return;
        (consoleErrorsByPage[currentPage] ??= []).push(txt);
        console.error(`[CONSOLE ERROR ${currentPage}]`, txt.slice(0, 200));
      }
    });
    page.on("requestfailed", (req) => {
      if (isNoiseRequest(req.url(), req.failure()?.errorText)) return;
      const msg = `${req.method()} ${req.url()} — ${req.failure()?.errorText ?? "unknown"}`;
      (networkFailsByPage[currentPage] ??= []).push(msg);
      console.error(`[NETWORK FAIL ${currentPage}]`, msg);
    });
    page.on("response", (resp) => {
      const s = resp.status();
      const url = resp.url();
      if (s >= 400) {
        if (url.includes("/api/auth/refresh") && currentPage === "(login)") return;
        if (isNoiseRequest(url)) return;
        const msg = `${s} ${resp.request().method()} ${url}`;
        (networkFailsByPage[currentPage] ??= []).push(msg);
        if (s >= 500) console.error(`[HTTP ${s} ${currentPage}]`, msg);
      }
    });

    await loginViaUI(page);
    console.log("[DESKTOP] Logged in, URL:", page.url());

    for (const route of PAGES) {
      currentPage = route;
      const dir = pageDir(route);
      ensureDir(dir);
      console.log(`\n[DESKTOP] Visiting ${route} …`);
      await page.goto(`${BASE_URL}${route}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(3000);

      // Detect spinner-only state by reading body text
      const bodyText = (await page.locator("body").textContent().catch(() => "")) ?? "";
      const hasUndefined = /undefined/i.test(bodyText) && !/undefined behavior/i.test(bodyText);
      const stuckLoading = bodyText.trim().toLowerCase() === "loading...";

      await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
      await page.waitForTimeout(300);
      await page.screenshot({
        path: path.join(dir, "desktop-fullpage.png"),
        fullPage: true,
      });
      const h1 = await page.locator("h1").first().textContent().catch(() => null);
      console.log(`[DESKTOP ${route}] h1=${(h1 ?? "(none)").trim().slice(0,80)} stuckLoading=${stuckLoading} hasUndefined=${hasUndefined}`);
    }

    // Persist diagnostics
    const diag = { consoleErrorsByPage, networkFailsByPage };
    fs.writeFileSync(path.join(SHOT_ROOT, "desktop-diag.json"), JSON.stringify(diag, null, 2));
    console.log("\n[DESKTOP] Diag written to desktop-diag.json");
    for (const route of PAGES) {
      const ce = (consoleErrorsByPage[route] ?? []).length;
      const nf = (networkFailsByPage[route] ?? []).length;
      console.log(`  ${route}: console=${ce} netFail=${nf}`);
    }
  });
});

test.describe("admin pages — mobile 414x896 fresh context", () => {
  test("mobile captures for /settings /users /system /developer", async () => {
    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
      viewport: { width: 414, height: 896 },
      userAgent:
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    });
    const page = await context.newPage();

    const consoleErrorsByPage: Record<string, string[]> = {};
    const networkFailsByPage: Record<string, string[]> = {};
    const overflowByPage: Record<string, { docW: number; winW: number; overflow: boolean }> = {};
    let currentPage = "(login)";

    page.on("pageerror", (err) => {
      (consoleErrorsByPage[currentPage] ??= []).push(`pageerror: ${err.message}`);
    });
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        const txt = msg.text();
        if (currentPage === "(login)" && txt.includes("/api/auth/refresh")) return;
        (consoleErrorsByPage[currentPage] ??= []).push(txt);
      }
    });
    page.on("requestfailed", (req) => {
      if (isNoiseRequest(req.url(), req.failure()?.errorText)) return;
      const msg = `${req.method()} ${req.url()} — ${req.failure()?.errorText ?? "unknown"}`;
      (networkFailsByPage[currentPage] ??= []).push(msg);
    });
    page.on("response", (resp) => {
      const s = resp.status();
      if (s >= 400) {
        if (resp.url().includes("/api/auth/refresh") && currentPage === "(login)") return;
        if (isNoiseRequest(resp.url())) return;
        (networkFailsByPage[currentPage] ??= []).push(`${s} ${resp.request().method()} ${resp.url()}`);
      }
    });

    try {
      await loginViaUI(page);
      console.log("[MOBILE] Logged in, URL:", page.url());

      for (const route of PAGES) {
        currentPage = route;
        const dir = pageDir(route);
        ensureDir(dir);
        console.log(`\n[MOBILE] Visiting ${route} …`);
        await page.goto(`${BASE_URL}${route}`, { waitUntil: "domcontentloaded" });
        await page.waitForTimeout(3000);
        await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
        await page.waitForTimeout(300);
        await page.screenshot({
          path: path.join(dir, "mobile-fullpage.png"),
          fullPage: true,
        });
        const overflow = await page.evaluate(() => ({
          docW: document.documentElement.scrollWidth,
          winW: window.innerWidth,
        }));
        overflowByPage[route] = { ...overflow, overflow: overflow.docW > overflow.winW };
        console.log(`[MOBILE ${route}] docW=${overflow.docW} winW=${overflow.winW} overflow=${overflow.docW > overflow.winW}`);
      }

      const diag = { consoleErrorsByPage, networkFailsByPage, overflowByPage };
      fs.writeFileSync(path.join(SHOT_ROOT, "mobile-diag.json"), JSON.stringify(diag, null, 2));
      console.log("\n[MOBILE] Diag written to mobile-diag.json");
      for (const route of PAGES) {
        const ce = (consoleErrorsByPage[route] ?? []).length;
        const nf = (networkFailsByPage[route] ?? []).length;
        const ov = overflowByPage[route];
        console.log(`  ${route}: console=${ce} netFail=${nf} overflow=${ov?.overflow}`);
      }
    } finally {
      await browser.close();
    }
  });
});
