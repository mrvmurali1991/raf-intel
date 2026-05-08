/**
 * /reports verification spec — fix/post-review-batch iter7.
 *
 * Run with:
 *   cd frontend && npx playwright test tests/demo/verify10-reports.spec.ts \
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
const EMAIL    = "admin@raf.health";
const PASSWORD = "Admin@123";

const SHOT_DIR = path.resolve(__dirname, "../../demo-shots/iter8-reports");
const FRESH_AUTH_STATE_PATH = "/tmp/fresh-auth-state.json";

function ensureDir(d: string) { fs.mkdirSync(d, { recursive: true }); }

const consoleErrors: string[] = [];
const pageErrors:   string[] = [];
const networkFailures: string[] = [];
let postLogin = false;

test.describe("/reports verification (iter7)", () => {
  test.setTimeout(180_000);

  test("capture reports desktop + mobile", async ({ page }) => {
    ensureDir(SHOT_DIR);

    page.on("pageerror", (err) => {
      if (postLogin) pageErrors.push(err.message);
    });
    page.on("console", (msg) => {
      if (msg.type() === "error" && postLogin) {
        consoleErrors.push(msg.text());
      }
    });
    page.on("response", (resp) => {
      const url = resp.url();
      const status = resp.status();
      if (status >= 400 && url.includes("/api/") && postLogin) {
        if (isNoiseRequest(url)) return;
        networkFailures.push(`${status} ${url}`);
      }
    });

    if (fs.existsSync(FRESH_AUTH_STATE_PATH)) {
      const rawState = JSON.parse(fs.readFileSync(FRESH_AUTH_STATE_PATH, "utf-8"));
      await page.context().addCookies(rawState.cookies);
    }

    await page.goto(`${BASE_URL}/reports`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(2500);

    if (page.url().includes("/login")) {
      await page.fill('input[type="email"]', EMAIL);
      await page.fill('input[type="password"]', PASSWORD);
      await page.click('button[type="submit"]');
      try {
        await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 });
      } catch {}
      await page.goto(`${BASE_URL}/reports`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(2500);
    }

    postLogin = true;
    console.log("[STEP] URL:", page.url());

    try {
      await page.waitForSelector('h1, [role="alert"], [class*="PageHeader"]', { timeout: 30_000 });
    } catch {}
    await page.waitForTimeout(4000);

    const h1Text = await page.locator("h1").first().textContent().catch(() => null);
    console.log("[STEP] h1:", h1Text?.trim());

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
    await page.waitForTimeout(500);

    await page.screenshot({ path: path.join(SHOT_DIR, "01-reports-top.png"), fullPage: false });
    await page.screenshot({ path: path.join(SHOT_DIR, "02-reports-fullpage.png"), fullPage: true });

    // Mobile
    await page.setViewportSize({ width: 414, height: 800 });
    await page.waitForTimeout(800);
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
    await page.waitForTimeout(400);

    await page.screenshot({ path: path.join(SHOT_DIR, "03-reports-mobile-top.png"), fullPage: false });
    await page.screenshot({ path: path.join(SHOT_DIR, "04-reports-mobile-fullpage.png"), fullPage: true });

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
    console.log("[STEP] mobile overflow:", JSON.stringify(overflowInfo));

    // Inventory
    const bodyText = (await page.locator("body").textContent()) || "";
    const checks = ["Report", "Generate", "Download", "Export", "PDF", "CSV", "Schedule"];
    for (const t of checks) {
      const cnt = (bodyText.match(new RegExp(t, "gi")) || []).length;
      console.log(`[INV] "${t}": ${cnt}`);
    }

    console.log("\n========= /reports VERIFICATION =========");
    console.log("URL:                  ", page.url());
    console.log("h1:                   ", h1Text?.trim());
    console.log("Console errors:       ", consoleErrors.length);
    console.log("Page JS errors:       ", pageErrors.length);
    console.log("Network failures:     ", networkFailures.length);
    console.log("Mobile overflow:      ", overflowInfo.hasOverflow,
      `(docW=${overflowInfo.docW}, winW=${overflowInfo.winW})`);
    if (consoleErrors.length > 0) {
      consoleErrors.slice(0, 8).forEach((e, i) => console.log(`  CE[${i}] ${e.slice(0, 200)}`));
    }
    if (pageErrors.length > 0) {
      pageErrors.slice(0, 8).forEach((e, i) => console.log(`  PE[${i}] ${e.slice(0, 200)}`));
    }
    if (networkFailures.length > 0) {
      networkFailures.slice(0, 12).forEach((e, i) => console.log(`  NF[${i}] ${e}`));
    }
    if (overflowInfo.offenders.length > 0) {
      console.log("Offenders:", JSON.stringify(overflowInfo.offenders));
    }
    console.log("Screenshots dir:      ", SHOT_DIR);
    console.log("=======================================\n");
  });
});
