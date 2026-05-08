/**
 * Misc verification spec — iter7 (fix/post-review-batch-10)
 * Covers: /login (pre-login fresh context), /emr-config (post-login),
 * /demo (post-login). Captures desktop 1440x900 + mobile 414x896 fullpage.
 */

import { test, expect, chromium, Page } from "@playwright/test";
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
const EMAIL = "admin@raf.health";
const PASSWORD = "Admin@123";

const SHOT_ROOT = path.resolve(__dirname, "../../demo-shots/iter7-misc");

function ensureDir(d: string) { fs.mkdirSync(d, { recursive: true }); }

async function loginViaUI(page: Page) {
  await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 20_000 });
  await page.fill('input[type="email"]', EMAIL);
  await page.fill('input[type="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 });
}

interface Probe {
  consoleErrors: string[];
  networkFailures: string[];
}

function attachProbes(page: Page, label: string): Probe {
  const consoleErrors: string[] = [];
  const networkFailures: string[] = [];
  page.on("pageerror", (err) => console.error(`[${label} PAGEERR]`, err.message));
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      consoleErrors.push(msg.text());
      console.error(`[${label} CONSOLE]`, msg.text().slice(0, 200));
    }
  });
  page.on("requestfailed", (req) => {
    if (isNoiseRequest(req.url(), req.failure()?.errorText)) return;
    const m = `${req.method()} ${req.url()} — ${req.failure()?.errorText ?? "unknown"}`;
    networkFailures.push(m);
    console.error(`[${label} NETFAIL]`, m);
  });
  page.on("response", (resp) => {
    if (resp.status() >= 400) {
      const m = `${resp.status()} ${resp.request().method()} ${resp.url()}`;
      console.log(`[${label} HTTP]`, m);
      if (isNoiseRequest(resp.url())) return;
      if (resp.status() >= 500) networkFailures.push(m);
      else if (resp.status() >= 400 && !resp.url().includes("/api/auth/")) {
        networkFailures.push(m);
      }
    }
  });
  return { consoleErrors, networkFailures };
}

// ── /login (fresh context, NO auth) ─────────────────────────────────────────

test.describe("/login pre-auth verification", () => {
  test("login page renders form at desktop + mobile", async () => {
    const dir = path.join(SHOT_ROOT, "login");
    ensureDir(dir);

    // Desktop
    {
      const browser = await chromium.launch({ headless: true });
      const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
      const page = await ctx.newPage();
      const probe = attachProbes(page, "LOGIN-D");

      await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" });
      await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 20_000 });
      await page.waitForTimeout(1500);

      const emailVisible = await page.locator('input[type="email"]').isVisible();
      const pwVisible    = await page.locator('input[type="password"]').isVisible();
      const submitVisible= await page.locator('button[type="submit"]').isVisible();

      await page.screenshot({ path: path.join(dir, "desktop-fullpage.png"), fullPage: true });

      console.log("\n========= /login DESKTOP SUMMARY =========");
      console.log("URL:", page.url());
      console.log("email input:", emailVisible, "password:", pwVisible, "submit:", submitVisible);
      console.log("console errors:", probe.consoleErrors.length);
      console.log("network failures:", probe.networkFailures.length);
      probe.networkFailures.forEach((e, i) => console.log(`  [NF ${i}] ${e}`));
      console.log("==========================================\n");

      expect(emailVisible).toBe(true);
      expect(pwVisible).toBe(true);
      expect(submitVisible).toBe(true);

      await browser.close();
    }

    // Mobile fresh context
    {
      const browser = await chromium.launch({ headless: true });
      const ctx = await browser.newContext({
        viewport: { width: 414, height: 896 },
        userAgent:
          "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
      });
      const page = await ctx.newPage();
      const probe = attachProbes(page, "LOGIN-M");

      await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" });
      await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 20_000 });
      await page.waitForTimeout(1500);

      const overflow = await page.evaluate(() => ({
        docW: document.documentElement.scrollWidth,
        winW: window.innerWidth,
      }));

      await page.screenshot({ path: path.join(dir, "mobile-fullpage.png"), fullPage: true });

      console.log("\n========= /login MOBILE SUMMARY =========");
      console.log("URL:", page.url());
      console.log("overflow docW:", overflow.docW, "winW:", overflow.winW,
        "->", overflow.docW > overflow.winW ? `OVERFLOW +${overflow.docW - overflow.winW}` : "none");
      console.log("console errors:", probe.consoleErrors.length);
      console.log("network failures:", probe.networkFailures.length);
      probe.networkFailures.forEach((e, i) => console.log(`  [NF ${i}] ${e}`));
      console.log("=========================================\n");

      await browser.close();
    }
  });
});

// ── Post-login pages ────────────────────────────────────────────────────────

async function captureAuthedPage(routePath: string, slug: string) {
  const dir = path.join(SHOT_ROOT, slug);
  ensureDir(dir);

  // Desktop
  {
    const browser = await chromium.launch({ headless: true });
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const page = await ctx.newPage();
    const probe = attachProbes(page, `${slug.toUpperCase()}-D`);

    await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" });
    await loginViaUI(page);
    await page.goto(`${BASE_URL}${routePath}`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3000);

    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(dir, "desktop-fullpage.png"), fullPage: true });

    const h1 = await page.locator("h1").first().textContent().catch(() => null);
    const spinnerCount = await page.locator('[role="progressbar"], .MuiCircularProgress-root').count();

    console.log(`\n========= ${routePath} DESKTOP SUMMARY =========`);
    console.log("URL:", page.url());
    console.log("h1:", h1?.trim() ?? "(none)");
    console.log("active spinners:", spinnerCount);
    console.log("console errors:", probe.consoleErrors.length);
    console.log("network failures:", probe.networkFailures.length);
    probe.networkFailures.forEach((e, i) => console.log(`  [NF ${i}] ${e}`));
    console.log("================================================\n");

    await browser.close();
  }

  // Mobile fresh context
  {
    const browser = await chromium.launch({ headless: true });
    const ctx = await browser.newContext({
      viewport: { width: 414, height: 896 },
      userAgent:
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    });
    const page = await ctx.newPage();
    const probe = attachProbes(page, `${slug.toUpperCase()}-M`);

    await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" });
    await loginViaUI(page);
    await page.goto(`${BASE_URL}${routePath}`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3000);

    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(dir, "mobile-fullpage.png"), fullPage: true });

    const overflow = await page.evaluate(() => ({
      docW: document.documentElement.scrollWidth,
      winW: window.innerWidth,
    }));
    const spinnerCount = await page.locator('[role="progressbar"], .MuiCircularProgress-root').count();

    console.log(`\n========= ${routePath} MOBILE SUMMARY =========`);
    console.log("URL:", page.url());
    console.log("overflow docW:", overflow.docW, "winW:", overflow.winW,
      "->", overflow.docW > overflow.winW ? `OVERFLOW +${overflow.docW - overflow.winW}` : "none");
    console.log("active spinners:", spinnerCount);
    console.log("console errors:", probe.consoleErrors.length);
    console.log("network failures:", probe.networkFailures.length);
    probe.networkFailures.forEach((e, i) => console.log(`  [NF ${i}] ${e}`));
    console.log("===============================================\n");

    await browser.close();
  }
}

test.describe("/emr-config post-login verification", () => {
  test("emr-config renders desktop + mobile", async () => {
    await captureAuthedPage("/emr-config", "emr-config");
  });
});

test.describe("/demo post-login verification", () => {
  test("demo renders desktop + mobile", async () => {
    await captureAuthedPage("/demo", "demo");
  });
});
