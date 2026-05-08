/**
 * /audit verification spec — fix/post-review-batch-10 iter1.
 *
 * Run with:
 *   cd frontend && npx playwright test tests/demo/verify10-audit.spec.ts \
 *       --config playwright.demo.config.ts --reporter=list
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
const API_URL  = process.env.API_URL  ?? "http://localhost:8500";
const EMAIL    = "admin@raf.health";
const PASSWORD = "Admin@123";

const SHOT_DIR = path.resolve(__dirname, "../../demo-shots/iter4-05-audit");
const FRESH_AUTH_STATE_PATH = "/tmp/fresh-auth-state.json";

function ensureDir(d: string) { fs.mkdirSync(d, { recursive: true }); }

const consoleErrors: string[] = [];
const pageErrors:   string[] = [];
const networkFailures: string[] = [];

test.describe("/audit verification (iter1)", () => {
  test.setTimeout(180_000);

  test("capture audit desktop + mobile", async ({ page }) => {
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
        if (isNoiseRequest(url)) return;
        networkFailures.push(`${status} ${url}`);
        console.error(`[NETWORK ${status}]`, url);
      }
    });

    // ---- Step 1: auth via cookies (with UI fallback) ----
    if (fs.existsSync(FRESH_AUTH_STATE_PATH)) {
      console.log("[STEP 1] Loading fresh auth cookies");
      const rawState = JSON.parse(fs.readFileSync(FRESH_AUTH_STATE_PATH, "utf-8")) as {
        cookies: Array<{
          name: string; value: string; domain: string; path: string;
          expires: number; httpOnly: boolean; secure: boolean; sameSite: string;
        }>;
      };
      await page.context().addCookies(rawState.cookies as Parameters<typeof page.context.prototype.addCookies>[0]);
    }

    await page.goto(`${BASE_URL}/audit`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2500);

    if (page.url().includes("/login")) {
      console.log("[STEP 1] Cookies expired → UI login");
      await page.fill('input[type="email"]', EMAIL);
      await page.fill('input[type="password"]', PASSWORD);
      await page.click('button[type="submit"]');
      try {
        await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 });
      } catch { /* no-op */ }
      await page.goto(`${BASE_URL}/audit`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(2500);
    }

    console.log("[STEP 2] URL after auth:", page.url());

    // Wait for page to render
    try {
      await page.waitForSelector('h1, [role="alert"], [class*="PageHeader"]', { timeout: 30_000 });
    } catch {
      console.log("[STEP 2] WARN: no h1/alert/PageHeader within 30s");
    }
    await page.waitForTimeout(4000);

    const h1Text = await page.locator("h1").first().textContent().catch(() => null);
    console.log("[STEP 2] h1:", h1Text?.trim());

    // ---- Step 3: text inventory ----
    const textChecks = [
      "Compliance & Audit",
      "Generate Audit Package",
      "Audit Packages",
      "RADV",
      "kappa",
      "Cohen",
      "IRR",
      "Inter-rater",
      "Audit Readiness",
      "RADV 2024 Cohort A",
      "Mock CMS Audit Q3",
      "Internal QA Sample",
      "Moderate",
      "Substantial",
      "Almost Perfect",
      "Fair",
      "Slight",
    ];
    for (const t of textChecks) {
      const cnt = await page.getByText(t, { exact: false }).count();
      console.log(`[STEP 3] text "${t}": ${cnt}`);
    }

    // Look for any numeric kappa value (0.NN format)
    const bodyText = (await page.locator("body").textContent()) || "";
    const kappaMatches = bodyText.match(/0\.\d{2}/g) || [];
    console.log(`[STEP 3] numeric 0.NN values found: ${kappaMatches.length} -> ${kappaMatches.slice(0,8).join(", ")}`);

    // Check spinner / loading state
    const loadingCount = await page.locator('text=Loading').count();
    console.log("[STEP 3] 'Loading' text count:", loadingCount);

    // ---- Step 4: desktop screenshots ----
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
    await page.waitForTimeout(500);

    await page.screenshot({
      path: path.join(SHOT_DIR, "01-audit-top.png"),
      fullPage: false,
    });
    console.log("[STEP 4] 01-audit-top.png saved");

    await page.screenshot({
      path: path.join(SHOT_DIR, "02-audit-fullpage.png"),
      fullPage: true,
    });
    console.log("[STEP 4] 02-audit-fullpage.png saved");

    // Generate-Package tile (top card)
    const genCard = page.getByText("Generate Audit Package", { exact: false }).first();
    if (await genCard.count() > 0) {
      await genCard.scrollIntoViewIfNeeded();
      await page.waitForTimeout(400);
      const box = await genCard.boundingBox();
      if (box) {
        await page.screenshot({
          path: path.join(SHOT_DIR, "03-generate-package-tile.png"),
          clip: {
            x: 0,
            y: Math.max(0, box.y - 30),
            width: 1440,
            height: 360,
          },
        });
        console.log("[STEP 4] 03-generate-package-tile.png saved");
      }
    }

    // Audit Packages list / table
    const pkgList = page.getByText("Audit Packages", { exact: false }).first();
    if (await pkgList.count() > 0) {
      await pkgList.scrollIntoViewIfNeeded();
      await page.waitForTimeout(400);
      const box = await pkgList.boundingBox();
      if (box) {
        await page.screenshot({
          path: path.join(SHOT_DIR, "04-audit-packages-tile.png"),
          clip: {
            x: 0,
            y: Math.max(0, box.y - 30),
            width: 1440,
            height: 600,
          },
        });
        console.log("[STEP 4] 04-audit-packages-tile.png saved");
      }
    }

    // ---- Step 5: mobile (414px) ----
    await page.setViewportSize({ width: 414, height: 800 });
    await page.waitForTimeout(800);
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
    await page.waitForTimeout(400);

    await page.screenshot({
      path: path.join(SHOT_DIR, "05-audit-mobile-top.png"),
      fullPage: false,
    });
    console.log("[STEP 5] 05-audit-mobile-top.png saved");

    await page.screenshot({
      path: path.join(SHOT_DIR, "06-audit-mobile-fullpage.png"),
      fullPage: true,
    });
    console.log("[STEP 5] 06-audit-mobile-fullpage.png saved");

    // Horizontal overflow check
    const overflowInfo = await page.evaluate(() => {
      const docW = document.documentElement.scrollWidth;
      const winW = window.innerWidth;
      const offenders: Array<{ tag: string; cls: string; w: number }> = [];
      document.querySelectorAll("*").forEach((el) => {
        const r = (el as HTMLElement).getBoundingClientRect();
        if (r.right > winW + 1 && r.width > 0 && r.width < winW + 200) {
          offenders.push({
            tag: el.tagName,
            cls: ((el as HTMLElement).className || "").toString().slice(0, 50),
            w: Math.round(r.right),
          });
        }
      });
      return { docW, winW, hasOverflow: docW > winW, offenders: offenders.slice(0, 8) };
    });
    console.log("[STEP 5] mobile overflow:", JSON.stringify(overflowInfo));

    // ---- Step 5b: stat-card width audit (mobile) ----
    const statCardInfo = await page.evaluate(() => {
      // Locate AuditReadinessCard via stable data-testid="arc-card".
      const card = document.querySelector('[data-testid="arc-card"]') as HTMLElement | null;
      if (!card) return { found: false, maxChildWidth: 0, kappaVisible: false, scenarioCount: 0 };
      const cardRect = card.getBoundingClientRect();
      let maxW = 0;
      let widest: { tag: string; cls: string; w: number; right: number; text: string } | null = null;
      card.querySelectorAll("*").forEach((el) => {
        const r = (el as HTMLElement).getBoundingClientRect();
        if (r.width > maxW) {
          maxW = r.width;
          widest = {
            tag: el.tagName,
            cls: ((el as HTMLElement).className || "").toString().slice(0, 60),
            w: Math.round(r.width),
            right: Math.round(r.right),
            text: (el.textContent || "").trim().slice(0, 40),
          };
        }
      });

      // Kappa value + band-label visibility (within viewport, non-zero size)
      const kappaValueEl = card.querySelector('[data-testid="irr-kappa-value"]') as HTMLElement | null;
      const kappaBandEl = card.querySelector('[data-testid="irr-band-label"]') as HTMLElement | null;
      const winW = window.innerWidth;
      let kappaVisible = false;
      let kappaInfo: { value: string; band: string; valueRight: number; bandRight: number; winW: number } | null = null;
      if (kappaValueEl && kappaBandEl) {
        const vr = kappaValueEl.getBoundingClientRect();
        const br = kappaBandEl.getBoundingClientRect();
        kappaVisible =
          vr.width > 0 && vr.right <= winW + 1 && vr.left >= -1 &&
          br.width > 0 && br.right <= winW + 1 && br.left >= -1;
        kappaInfo = {
          value: (kappaValueEl.textContent || "").trim(),
          band: (kappaBandEl.textContent || "").trim(),
          valueRight: Math.round(vr.right),
          bandRight: Math.round(br.right),
          winW,
        };
      }

      // RADV scenario count - search whole page (scenarios live in the package list, not arc-card)
      const docEls = Array.from(document.querySelectorAll("*")) as HTMLElement[];
      const scenarioLabels = ["RADV 2024 Cohort A", "Mock CMS Audit Q3", "Internal QA Sample"];
      let scenarioCount = 0;
      scenarioLabels.forEach((lbl) => {
        const matches = docEls.filter((el) => (el.textContent || "").includes(lbl));
        if (matches.length > 0) scenarioCount += 1;
      });

      return {
        found: true,
        cardWidth: Math.round(cardRect.width),
        maxChildWidth: Math.round(maxW),
        widest,
        kappaVisible,
        kappaInfo,
        scenarioCount,
      };
    });
    console.log("[STEP 5b] stat-card audit:", JSON.stringify(statCardInfo, null, 2));

    // ---- Step 6: summary ----
    console.log("\n========= /audit VERIFICATION =========");
    console.log("URL:                  ", page.url());
    console.log("h1:                   ", h1Text?.trim());
    console.log("Console errors:       ", consoleErrors.length);
    console.log("Page JS errors:       ", pageErrors.length);
    console.log("Network failures:     ", networkFailures.length);
    console.log("Mobile overflow:      ", overflowInfo.hasOverflow,
      `(docW=${overflowInfo.docW}, winW=${overflowInfo.winW})`);
    if (consoleErrors.length > 0) {
      console.log("-- Console errors --");
      consoleErrors.slice(0, 6).forEach((e, i) => console.log(`  [${i}] ${e.slice(0, 180)}`));
    }
    if (networkFailures.length > 0) {
      console.log("-- Network failures --");
      networkFailures.slice(0, 8).forEach((e, i) => console.log(`  [${i}] ${e}`));
    }
    console.log("Screenshots dir:      ", SHOT_DIR);
    console.log("=======================================\n");
  });
});
