/**
 * /providers 360° verification spec.
 *
 * THROWAWAY — delete before any commit.
 *
 * Run:
 *   cd frontend && npx playwright test tests/demo/verify10-providers.spec.ts \
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
  if (url.includes("/api/auth/me") && (errorText ?? "").includes("ERR_ABORTED")) return true;
  return false;
}


const BASE_URL = process.env.BASE_URL ?? "http://localhost:3444";
const API_URL  = process.env.API_URL  ?? "http://localhost:8500";
const EMAIL    = "admin@raf.health";
const PASSWORD = "Admin@123";

const SHOT_DIR = path.resolve(__dirname, "../../demo-shots/iter3-04-providers");
const FRESH_AUTH_STATE_PATH = "/tmp/fresh-auth-state.json";

function ensureDir(d: string) { fs.mkdirSync(d, { recursive: true }); }

const consoleErrors: string[] = [];
const pageErrors:   string[] = [];
const networkFailures: { url: string; status: number }[] = [];
const featureFlagCalls: { status: number; url: string }[] = [];

test.describe("/providers verification", () => {
  test("capture + inspect /providers", async ({ page }) => {
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
    page.on("response", async (resp) => {
      const url = resp.url();
      const status = resp.status();
      if (url.includes("/api/feature-flags")) {
        featureFlagCalls.push({ status, url });
      }
      if (status >= 400 && url.includes("/api/")) {
        if (isNoiseRequest(url)) return;
        networkFailures.push({ url, status });
      }
    });

    // ----- Auth via UI (refresh-token cookies rotate, so always login fresh) -----
    await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 15_000 });
    await page.fill('input[type="email"]', EMAIL);
    await page.fill('input[type="password"]', PASSWORD);
    await page.click('button[type="submit"]');
    try {
      await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 });
    } catch {
      console.warn("[AUTH] waitForURL timed out; current URL:", page.url());
    }
    await page.waitForTimeout(2000);
    await page.goto(`${BASE_URL}/providers`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(3000);

    console.log("[STEP] URL after auth:", page.url());

    // wait for React Query data
    await page.waitForTimeout(7000);

    // ----- Desktop top -----
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(SHOT_DIR, "01-desktop-top.png"), fullPage: false });
    console.log("[SHOT] 01-desktop-top.png");

    // h1 text
    const h1 = await page.locator("h1, h2").first().textContent().catch(() => null);
    console.log("[INFO] heading:", h1?.trim());

    // ----- Full page desktop -----
    await page.screenshot({ path: path.join(SHOT_DIR, "02-desktop-fullpage.png"), fullPage: true });
    console.log("[SHOT] 02-desktop-fullpage.png");

    // ----- Inspect for major sections -----
    const sectionLabels = [
      "Provider Scorecards",
      "Worklist",
      "Active Alerts",
      "Per-HCC Performance",
      "Top HCC Opportunities",
      "Trends",
      "Scorecard",
      "Roster",
      "RAF",
    ];
    const sectionFound: Record<string, number> = {};
    for (const txt of sectionLabels) {
      sectionFound[txt] = await page.getByText(txt, { exact: false }).count();
    }
    console.log("[SECTIONS]", JSON.stringify(sectionFound));

    // ----- Provider table inspection -----
    // Look for provider names in the table; we know real names from API include Robert Kim, Sarah Mitchell
    const knownNames = ["Robert Kim", "Sarah Mitchell", "Mitchell", "Kim"];
    const namesFound: Record<string, number> = {};
    for (const n of knownNames) {
      namesFound[n] = await page.getByText(n, { exact: false }).count();
    }
    console.log("[NAMES]", JSON.stringify(namesFound));

    // Check for "no data" / empty state phrases
    const noDataPhrases = ["no data", "No providers", "No data", "No scorecards"];
    const noDataHits: Record<string, number> = {};
    for (const p of noDataPhrases) {
      noDataHits[p] = await page.getByText(p, { exact: false }).count();
    }
    console.log("[NO_DATA_HITS]", JSON.stringify(noDataHits));

    // ----- Scorecard section screenshot -----
    {
      const el = page.getByText("Provider Scorecards", { exact: false }).first();
      if (await el.count()) {
        await el.scrollIntoViewIfNeeded();
        await page.waitForTimeout(800);
        const box = await el.boundingBox();
        if (box) {
          const clipY = Math.max(0, box.y - 40);
          await page.screenshot({
            path: path.join(SHOT_DIR, "03-scorecards.png"),
            clip: { x: 0, y: clipY, width: 1440, height: Math.min(900, 900) },
          });
          console.log("[SHOT] 03-scorecards.png");
        }
      }
    }

    // ----- Alerts section -----
    {
      const el = page.getByText("Active Alerts", { exact: false }).first();
      if (await el.count()) {
        await el.scrollIntoViewIfNeeded();
        await page.waitForTimeout(600);
        await page.screenshot({ path: path.join(SHOT_DIR, "04-alerts.png"), fullPage: false });
        console.log("[SHOT] 04-alerts.png");
      } else {
        console.log("[SHOT] 04-alerts.png skipped — no Active Alerts section visible");
      }
    }

    // ----- Per-HCC perf -----
    {
      const el = page.getByText("Per-HCC Performance", { exact: false }).first();
      if (await el.count()) {
        await el.scrollIntoViewIfNeeded();
        await page.waitForTimeout(600);
        await page.screenshot({ path: path.join(SHOT_DIR, "05-per-hcc.png"), fullPage: false });
        console.log("[SHOT] 05-per-hcc.png");
      }
    }

    // ----- Opportunities -----
    {
      const el = page.getByText("Top HCC Opportunities", { exact: false }).first();
      if (await el.count()) {
        await el.scrollIntoViewIfNeeded();
        await page.waitForTimeout(600);
        await page.screenshot({ path: path.join(SHOT_DIR, "06-opportunities.png"), fullPage: false });
        console.log("[SHOT] 06-opportunities.png");
      }
    }

    // ----- Drilldown via Scorecard button -----
    {
      // Scroll back up to roster
      await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
      await page.waitForTimeout(400);
      const scorecardBtn = page.getByRole("button", { name: /scorecard/i }).first();
      const cnt = await scorecardBtn.count();
      console.log("[DRILLDOWN] scorecard buttons found:", cnt);
      if (cnt > 0) {
        try {
          await scorecardBtn.scrollIntoViewIfNeeded();
          await scorecardBtn.click({ timeout: 5000 });
          await page.waitForTimeout(2500);
          await page.screenshot({ path: path.join(SHOT_DIR, "07-drilldown.png"), fullPage: true });
          console.log("[SHOT] 07-drilldown.png");
        } catch (e) {
          console.log("[DRILLDOWN] click failed:", (e as Error).message);
        }
      }
    }

    // ----- Mobile 414px -----
    await page.setViewportSize({ width: 414, height: 900 });
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
    await page.waitForTimeout(1500);
    await page.screenshot({ path: path.join(SHOT_DIR, "08-mobile-top.png"), fullPage: false });
    await page.screenshot({ path: path.join(SHOT_DIR, "09-mobile-fullpage.png"), fullPage: true });
    console.log("[SHOT] 08-mobile-top.png + 09-mobile-fullpage.png");

    // ----- CRITICAL: Mobile 414px drilldown gap check -----
    let drilldownGapPx: number | null = null;
    let drilldownOpened = false;
    try {
      const mobileScorecardBtn = page.getByRole("button", { name: /scorecard/i }).first();
      const mcnt = await mobileScorecardBtn.count();
      console.log("[MOBILE-DRILLDOWN] scorecard buttons found:", mcnt);
      if (mcnt > 0) {
        await mobileScorecardBtn.scrollIntoViewIfNeeded();
        await mobileScorecardBtn.click({ timeout: 5000 });
        await page.waitForTimeout(2500);
        drilldownOpened = true;
        await page.screenshot({
          path: path.join(SHOT_DIR, "10-mobile-drilldown-fullpage.png"),
          fullPage: true,
        });
        console.log("[SHOT] 10-mobile-drilldown-fullpage.png");

        // Measure gap between radar wrap bottom and the FIRST sibling after it (score pills row).
        // This catches the "phantom blank space" bug where the SVG used to overflow its wrap.
        drilldownGapPx = await page.evaluate(() => {
          const radar = document.querySelector<HTMLElement>(".provider-radar-wrap");
          if (!radar) return -1;
          const radarRect = radar.getBoundingClientRect();
          const next = radar.nextElementSibling as HTMLElement | null;
          if (!next) return -2;
          const nextRect = next.getBoundingClientRect();
          return Math.round(nextRect.top - radarRect.bottom);
        });
        console.log("[MOBILE-DRILLDOWN] gap px:", drilldownGapPx);

        // Also capture a tight clipped shot of radar + next row for inspection
        const clipInfo = await page.evaluate(() => {
          const radar = document.querySelector<HTMLElement>(".provider-radar-wrap");
          if (!radar) return null;
          const r = radar.getBoundingClientRect();
          return {
            x: 0,
            y: Math.max(0, r.top + window.scrollY - 60),
            absTop: r.top + window.scrollY,
          };
        });
        if (clipInfo) {
          await page.evaluate((y) => window.scrollTo({ top: y, behavior: "instant" }), Math.max(0, clipInfo.absTop - 80));
          await page.waitForTimeout(400);
          await page.screenshot({
            path: path.join(SHOT_DIR, "11-mobile-drilldown-radar-zoom.png"),
            clip: { x: 0, y: 0, width: 414, height: 700 },
          });
          console.log("[SHOT] 11-mobile-drilldown-radar-zoom.png");
        }
      }
    } catch (e) {
      console.log("[MOBILE-DRILLDOWN] error:", (e as Error).message);
    }

    // Check horizontal overflow at 414px
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
          if (overflowing.length >= 8) break;
        }
      }
      return { docW, viewW, overflowing };
    });
    console.log("[OVERFLOW]", JSON.stringify(overflowInfo));

    // ----- Final summary -----
    console.log("\n========= /providers VERIFICATION =========");
    console.log(`URL:                 ${page.url()}`);
    console.log(`heading:             ${h1?.trim()}`);
    console.log(`feature-flag calls:  ${featureFlagCalls.length}`);
    featureFlagCalls.forEach((c, i) => console.log(`  [FF ${i}] status=${c.status}`));
    console.log(`API failures:        ${networkFailures.length}`);
    networkFailures.slice(0, 10).forEach((f, i) => console.log(`  [NF ${i}] ${f.status} ${f.url}`));
    console.log(`Console errors:      ${consoleErrors.length}`);
    consoleErrors.slice(0, 5).forEach((e, i) => console.log(`  [CE ${i}] ${e.slice(0, 140)}`));
    console.log(`Page JS errors:      ${pageErrors.length}`);
    pageErrors.slice(0, 5).forEach((e, i) => console.log(`  [PE ${i}] ${e.slice(0, 140)}`));
    console.log(`Sections found:      ${JSON.stringify(sectionFound)}`);
    console.log(`Names found:         ${JSON.stringify(namesFound)}`);
    console.log(`No-data hits:        ${JSON.stringify(noDataHits)}`);
    console.log(`Mobile overflow:     docW=${overflowInfo.docW} viewW=${overflowInfo.viewW} count=${overflowInfo.overflowing.length}`);
    console.log(`Mobile drilldown:    opened=${drilldownOpened} gapPx=${drilldownGapPx}`);
    console.log(`Screenshots:         ${SHOT_DIR}`);
    console.log("===========================================\n");
  });
});
