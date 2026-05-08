/**
 * Multi-page verification: /analysis, /prospective, /crosswalk
 *
 * THROWAWAY — delete before any commit.
 *
 * Run:
 *   cd frontend && npx playwright test tests/demo/verify10-multi-analysis.spec.ts \
 *       --config playwright.demo.config.ts
 */

import { test, Page } from "@playwright/test";
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
const EMAIL = "admin@raf.health";
const PASSWORD = "Admin@123";

const SHOT_ROOT = path.resolve(__dirname, "../../demo-shots");
const PAGES = ["analysis", "prospective", "crosswalk"] as const;

function ensureDir(d: string) {
  fs.mkdirSync(d, { recursive: true });
}

async function login(page: Page) {
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
}

test.describe("multi-page analysis suite", () => {
  for (const slug of PAGES) {
    test(`verify /${slug}`, async ({ page }) => {
      test.setTimeout(180_000);
      const SHOT_DIR = path.join(SHOT_ROOT, `iter8-${slug}`);
      ensureDir(SHOT_DIR);

      const consoleErrors: string[] = [];
      const pageErrors: string[] = [];
      const networkFailures: { url: string; status: number }[] = [];
      let loggedIn = false;

      page.on("pageerror", (err) => {
        if (!loggedIn) return;
        pageErrors.push(err.message);
      });
      page.on("console", (msg) => {
        if (!loggedIn) return;
        if (msg.type() === "error") {
          consoleErrors.push(msg.text());
        }
      });
      page.on("response", (resp) => {
        if (!loggedIn) return;
        const url = resp.url();
        const status = resp.status();
        if (status >= 400) {
          if (isNoiseRequest(url)) return;
          networkFailures.push({ url, status });
        }
      });

      await login(page);
      loggedIn = true;

      await page.goto(`${BASE_URL}/${slug}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(5000);

      // Check for stuck spinner
      const hasSpinner = await page.evaluate(() => {
        const sels = ['[role="progressbar"]', ".spinner", ".loading", "[data-loading='true']"];
        for (const s of sels) {
          const el = document.querySelector(s);
          if (el && (el as HTMLElement).offsetParent !== null) return true;
        }
        // Look for "Loading..." text
        const txt = document.body.innerText;
        if (/^\s*loading/i.test(txt) && txt.length < 200) return true;
        return false;
      });
      console.log(`[${slug}] stuck-spinner:`, hasSpinner);

      // Desktop
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
      await page.waitForTimeout(800);
      await page.screenshot({ path: path.join(SHOT_DIR, "01-desktop-top.png"), fullPage: false });
      await page.screenshot({ path: path.join(SHOT_DIR, "02-desktop-fullpage.png"), fullPage: true });

      const h1 = await page.locator("h1, h2").first().textContent().catch(() => null);
      console.log(`[${slug}] heading:`, h1?.trim());

      const bodyText = await page.locator("body").innerText().catch(() => "");
      const emptyStateHits = (bodyText.match(/no data|no results|empty|nothing yet|coming soon/gi) || []).length;
      const contentLen = bodyText.replace(/\s+/g, " ").trim().length;
      console.log(`[${slug}] content len:`, contentLen, "empty hits:", emptyStateHits);

      // Mobile 414px
      await page.setViewportSize({ width: 414, height: 900 });
      await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
      await page.waitForTimeout(1500);
      await page.screenshot({ path: path.join(SHOT_DIR, "03-mobile-top.png"), fullPage: false });
      await page.screenshot({ path: path.join(SHOT_DIR, "04-mobile-fullpage.png"), fullPage: true });

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

      console.log(`\n========= /${slug} VERIFICATION =========`);
      console.log(`URL:                 ${page.url()}`);
      console.log(`heading:             ${h1?.trim()}`);
      console.log(`stuck spinner:       ${hasSpinner}`);
      console.log(`content length:      ${contentLen}`);
      console.log(`empty-state hits:    ${emptyStateHits}`);
      console.log(`API failures:        ${networkFailures.length}`);
      networkFailures.slice(0, 10).forEach((f, i) => console.log(`  [NF ${i}] ${f.status} ${f.url}`));
      console.log(`Console errors:      ${consoleErrors.length}`);
      consoleErrors.slice(0, 10).forEach((e, i) => console.log(`  [CE ${i}] ${e.slice(0, 200)}`));
      console.log(`Page JS errors:      ${pageErrors.length}`);
      pageErrors.slice(0, 5).forEach((e, i) => console.log(`  [PE ${i}] ${e.slice(0, 200)}`));
      console.log(`Mobile overflow:     docW=${overflowInfo.docW} viewW=${overflowInfo.viewW} count=${overflowInfo.overflowing.length}`);
      overflowInfo.overflowing.slice(0, 5).forEach((o, i) =>
        console.log(`  [OV ${i}] ${o.tag}.${o.cls} w=${o.w}`)
      );
      console.log(`Screenshots:         ${SHOT_DIR}`);
      console.log("===========================================\n");
    });
  }
});
