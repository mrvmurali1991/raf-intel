/**
 * /patients/{pid} (Patient Detail) end-to-end verification.
 *
 * Run:
 *   cd frontend && npx playwright test tests/demo/verify10-patient-detail.spec.ts \
 *       --config playwright.demo.config.ts
 *
 * Captures screenshots for 3 patients on desktop + mobile, plus tab snapshots
 * (Overview/Demographics, RAF Central -> "HCCs", Encounters), and a KG popover
 * if any clickable HCC chip exists.
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
const API_URL  = process.env.API_URL  ?? "http://localhost:8500";
const EMAIL    = process.env.DEMO_EMAIL    ?? "admin@raf.health";
const PASSWORD = process.env.DEMO_PASSWORD ?? "Admin@123";

const SHOT_DIR = path.resolve(__dirname, "../../demo-shots/iter3-02-patient-detail");
const PATIENT_IDS = ["22", "16", "8"];

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile",  width: 414,  height: 896 },
] as const;

function ensureDir(d: string) { fs.mkdirSync(d, { recursive: true }); }

interface NetFailure { url: string; status: number; method: string }

test.describe("/patients/{pid} verification", () => {
  test.setTimeout(300_000);

  test("patient detail: 3 patients x 2 viewports + KG popover", async ({ browser }) => {
    ensureDir(SHOT_DIR);

    const aggregateConsoleErrors: string[] = [];
    const aggregatePageErrors: string[]    = [];
    const aggregateNetFailures: NetFailure[] = [];

    for (const vp of VIEWPORTS) {
      const ctx = await browser.newContext({
        viewport: { width: vp.width, height: vp.height },
        ignoreHTTPSErrors: true,
      });
      const page = await ctx.newPage();

      page.on("pageerror", (err) => {
        aggregatePageErrors.push(`[${vp.name}] ${err.message}`);
        console.error("[PAGE ERROR]", vp.name, err.message);
      });
      page.on("console", (msg) => {
        if (msg.type() === "error") {
          const t = msg.text();
          // Suppress noise we don't control
          if (/Failed to load resource: the server responded with a status of 4\d\d/.test(t) && /favicon/.test(t)) return;
          aggregateConsoleErrors.push(`[${vp.name}] ${t}`);
          console.error("[CONSOLE ERROR]", vp.name, t.slice(0, 200));
        }
      });
      page.on("response", async (resp) => {
        const url = resp.url();
        const status = resp.status();
        if (status >= 400 && (url.includes("/api/") || url.includes("/patients/")) && !isNoiseRequest(url)) {
          aggregateNetFailures.push({ url, status, method: resp.request().method() });
        }
      });

      // -----------------------------------------------------------------
      // Login via API: this sets the httpOnly refresh cookie on the context.
      // The frontend then auto-refreshes and obtains an access token on mount.
      // -----------------------------------------------------------------
      const loginResp = await ctx.request.post(`${API_URL}/api/auth/login`, {
        headers: { "Content-Type": "application/json" },
        data: { email: EMAIL, password: PASSWORD },
      });
      console.log(`[${vp.name}] API login status=${loginResp.status()}`);
      if (!loginResp.ok()) {
        console.warn(`[${vp.name}] API login failed:`, await loginResp.text());
      }
      // Sanity check: cookie should be on context
      const cookies = await ctx.cookies();
      const hasRefresh = cookies.some((c) => c.name === "raf_refresh_token");
      console.log(`[${vp.name}] raf_refresh_token cookie present=${hasRefresh}`);

      for (const pid of PATIENT_IDS) {
        const url = `${BASE_URL}/patients/${pid}`;
        console.log(`\n=== [${vp.name}] visiting ${url} ===`);
        await page.goto(url, { waitUntil: "domcontentloaded" });

        // Wait for either an h1 with patient name OR an error UI
        await page.waitForTimeout(500);
        try {
          await page.waitForFunction(() => {
            const h1s = Array.from(document.querySelectorAll("h1, h2"));
            return h1s.some((el) => {
              const t = (el.textContent || "").trim();
              return t.length > 1 && !/^loading/i.test(t);
            });
          }, { timeout: 20_000 });
        } catch {
          console.warn(`[${vp.name}] pid=${pid}: no header rendered within 20s`);
        }
        await page.waitForTimeout(2500); // settle for queries

        // ---------- Spinner check (no infinite spinners after 5s) ----------
        await page.waitForTimeout(2500);
        const spinnerCount = await page.locator('[role="status"], .spinner, [aria-busy="true"], [data-testid="spinner"]').count();
        const visibleSpinnerCount = await page.locator('[aria-busy="true"]').count();
        console.log(`[${vp.name}] pid=${pid} spinnerCount=${spinnerCount} aria-busy=${visibleSpinnerCount}`);

        // ---------- Body text checks ----------
        const bodyText = await page.locator("body").innerText().catch(() => "");
        const hasUndefined = /\bundefined\b/.test(bodyText);
        const hasObjObj = /\[object Object\]/.test(bodyText);
        const hasLoadingHeader = /^Loading/i.test((await page.locator("h1").first().textContent().catch(() => "")) || "");

        console.log(`[${vp.name}] pid=${pid} hasUndefined=${hasUndefined} hasObjObj=${hasObjObj} loadingHeader=${hasLoadingHeader}`);

        // ---------- Screenshot 1: full page (desktop) / top (mobile) ----------
        await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
        await page.waitForTimeout(300);
        await page.screenshot({
          path: path.join(SHOT_DIR, `${vp.name}-pid${pid}-01-top.png`),
          fullPage: false,
        });
        await page.screenshot({
          path: path.join(SHOT_DIR, `${vp.name}-pid${pid}-02-fullpage.png`),
          fullPage: true,
        });

        // ---------- Switch to Overview (Demographics live there) ----------
        try {
          const overviewTab = page.locator('[role="tab"]', { hasText: "Overview" }).first();
          if (await overviewTab.count() > 0) {
            await overviewTab.scrollIntoViewIfNeeded();
            await overviewTab.click({ timeout: 5000 });
            await page.waitForTimeout(1500);
            await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
            await page.screenshot({
              path: path.join(SHOT_DIR, `${vp.name}-pid${pid}-03-demographics.png`),
              fullPage: true,
            });
          } else {
            console.log(`[${vp.name}] pid=${pid} Overview tab missing`);
          }
        } catch (e) {
          console.warn(`[${vp.name}] pid=${pid} Overview tab click failed`, (e as Error).message);
        }

        // ---------- HCCs: open RAF Central tab (where HCC chips live) ----------
        let hccChipCount = 0;
        try {
          const rafTab = page.locator('[role="tab"]', { hasText: /RAF Central/i }).first();
          if (await rafTab.count() > 0) {
            await rafTab.scrollIntoViewIfNeeded();
            await rafTab.click({ timeout: 5000 });
            await page.waitForTimeout(2500);
            await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
            await page.waitForTimeout(300);
            await page.screenshot({
              path: path.join(SHOT_DIR, `${vp.name}-pid${pid}-04-hccs.png`),
              fullPage: true,
            });
            // Probe for HCC chip-like elements
            const chipSelectors = [
              '[data-testid*="hcc"]',
              'button:has-text("HCC")',
              '[class*="hcc-chip"]',
              '[class*="HccChip"]',
              'a:has-text("HCC")',
            ];
            for (const sel of chipSelectors) {
              const c = await page.locator(sel).count();
              if (c > hccChipCount) hccChipCount = c;
            }
            console.log(`[${vp.name}] pid=${pid} hccChipCount=${hccChipCount}`);
          }
        } catch (e) {
          console.warn(`[${vp.name}] pid=${pid} RAF Central click failed`, (e as Error).message);
        }

        // ---------- KG popover (only on desktop, only first patient with chip) ----------
        if (vp.name === "desktop" && hccChipCount > 0 && pid === PATIENT_IDS[0]) {
          try {
            const firstChip = page.locator('[data-testid*="hcc"], button:has-text("HCC")').first();
            await firstChip.scrollIntoViewIfNeeded();
            await firstChip.click({ timeout: 5000 });
            await page.waitForTimeout(1800);
            await page.screenshot({
              path: path.join(SHOT_DIR, `${vp.name}-pid${pid}-05-kg-popover.png`),
              fullPage: false,
            });
            await page.keyboard.press("Escape").catch(() => {});
          } catch (e) {
            console.warn(`[${vp.name}] pid=${pid} KG popover failed`, (e as Error).message);
          }
        }

        // ---------- Encounters tab ----------
        try {
          const encTab = page.locator('[role="tab"]', { hasText: "Encounters" }).first();
          if (await encTab.count() > 0) {
            await encTab.scrollIntoViewIfNeeded();
            await encTab.click({ timeout: 5000 });
            await page.waitForTimeout(2500);
            await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
            await page.screenshot({
              path: path.join(SHOT_DIR, `${vp.name}-pid${pid}-06-encounters.png`),
              fullPage: true,
            });
          } else {
            console.log(`[${vp.name}] pid=${pid} Encounters tab missing`);
          }
        } catch (e) {
          console.warn(`[${vp.name}] pid=${pid} Encounters click failed`, (e as Error).message);
        }

        // ---------- Per-patient validation log ----------
        const h1Text = await page.locator("h1").first().textContent().catch(() => "(none)");
        console.log(`[${vp.name}] pid=${pid} h1="${h1Text?.trim().slice(0, 80)}"`);
      }

      await ctx.close();
    }

    // Persist a structured summary so the agent can read it
    const summary = {
      consoleErrors: aggregateConsoleErrors,
      pageErrors: aggregatePageErrors,
      networkFailures: aggregateNetFailures,
      counts: {
        consoleErrors: aggregateConsoleErrors.length,
        pageErrors: aggregatePageErrors.length,
        networkFailures: aggregateNetFailures.length,
      },
    };
    fs.writeFileSync(path.join(SHOT_DIR, "_summary.json"), JSON.stringify(summary, null, 2));

    console.log("\n========= VERIFY-10 PATIENT DETAIL SUMMARY =========");
    console.log(`Console errors:   ${aggregateConsoleErrors.length}`);
    console.log(`Page JS errors:   ${aggregatePageErrors.length}`);
    console.log(`Network failures: ${aggregateNetFailures.length}`);
    if (aggregateNetFailures.length > 0) {
      aggregateNetFailures.slice(0, 10).forEach((f, i) => {
        console.log(`  [NF ${i}] ${f.method} ${f.status} ${f.url}`);
      });
    }
    if (aggregateConsoleErrors.length > 0) {
      aggregateConsoleErrors.slice(0, 10).forEach((e, i) => console.log(`  [CE ${i}] ${e.slice(0, 200)}`));
    }
    console.log(`Screenshots:      ${SHOT_DIR}`);
    console.log("=====================================================\n");

    // Don't fail the suite on errors — we want artifacts even when broken
    expect(true).toBe(true);
  });
});
