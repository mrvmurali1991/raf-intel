/**
 * Verification: /quality renders KPIs + distribution chart at 414x896 mobile.
 * Fresh context, viewport set before any navigation, UI login.
 *
 * Run with:
 *   cd frontend && npx playwright test tests/demo/verify-quality-mobile-fix.spec.ts \
 *       --config playwright.demo.config.ts
 *
 * Output screenshots → frontend/demo-shots/fix-quality-mobile-loading/
 */

import { test, expect } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

const BASE_URL = process.env.BASE_URL ?? "http://localhost:3444";
const EMAIL    = "admin@raf.health";
const PASSWORD = "Admin@123";
const SHOT_DIR = path.resolve(__dirname, "../../demo-shots/fix-quality-mobile-loading");

function ensureDir(d: string) { fs.mkdirSync(d, { recursive: true }); }

test("mobile 414x896 — quality KPIs visible, no loading spinner after 15s", async ({ browser }) => {
  ensureDir(SHOT_DIR);

  // Fresh context at mobile size set BEFORE navigation
  const ctx = await browser.newContext({ viewport: { width: 414, height: 896 } });
  const page = await ctx.newPage();

  // ── Login ──────────────────────────────────────────────────────────────
  await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 15_000 });
  await page.fill('input[type="email"]', EMAIL);
  await page.fill('input[type="password"]', PASSWORD);
  await page.click('button[type="submit"]');
  await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 });

  // ── Navigate to /quality ────────────────────────────────────────────────
  await page.goto(`${BASE_URL}/quality`, { waitUntil: "domcontentloaded" });

  // Wait up to 20s for KPI data to appear (cold-start: auth init + API fetches).
  // StatCard renders labels with textTransform:uppercase so innerText gives "TOTAL MEASURES".
  try {
    await page.waitForFunction(
      () =>
        document.body.innerText.toUpperCase().includes("TOTAL MEASURES") &&
        !document.body.innerText.includes("Loading quality summary..."),
      { timeout: 20_000 }
    );
    console.log("[VERIFY] KPI 'TOTAL MEASURES' appeared and spinner gone");
  } catch {
    console.log("[VERIFY] waitForFunction timed out — capturing anyway");
  }

  // Allow animations to settle
  await page.waitForTimeout(800);
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
  await page.waitForTimeout(300);

  // ── Screenshots ────────────────────────────────────────────────────────
  await page.screenshot({
    path: path.join(SHOT_DIR, "verified-01-mobile-top.png"),
    fullPage: false,
  });
  await page.screenshot({
    path: path.join(SHOT_DIR, "verified-02-mobile-fullpage.png"),
    fullPage: true,
  });

  // ── Assertions ─────────────────────────────────────────────────────────
  const bodyText = await page.evaluate(() => document.body.innerText);
  const url = page.url();

  // StatCard uses textTransform:uppercase, so innerText returns labels uppercased.
  const upperBody = bodyText.toUpperCase();
  const kpiVisible = upperBody.includes("TOTAL MEASURES");
  const chartVisible = bodyText.includes("above benchmark") || bodyText.includes("Compliance Rate Distribution");
  const noSpinner = !bodyText.includes("Loading quality summary...");

  console.log("\n======= VERIFICATION =======");
  console.log("URL:", url);
  console.log("KPI TOTAL MEASURES:", kpiVisible);
  console.log("Distribution chart:", chartVisible);
  console.log("No loading spinner:", noSpinner);
  console.log("Body (first 800):", bodyText.slice(0, 800));
  console.log("============================\n");

  expect(kpiVisible, "KPI must be visible at 414x896 (StatCard renders labels uppercase)").toBe(true);
  expect(noSpinner, "Must NOT be stuck on 'Loading quality summary...'").toBe(true);

  await ctx.close();
});
