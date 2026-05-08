/**
 * Ops suite verification spec — /claims, /disputes, /submissions, /batch.
 *
 * THROWAWAY — delete before any commit.
 *
 * Run:
 *   cd frontend && npx playwright test tests/demo/verify10-ops-suite.spec.ts \
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
const EMAIL = "admin@raf.health";
const PASSWORD = "Admin@123";

const SHOT_ROOT = path.resolve(__dirname, "../../demo-shots/iter7-ops");

function ensureDir(d: string) {
  fs.mkdirSync(d, { recursive: true });
}

const PAGES = [
  { slug: "claims", route: "/claims" },
  { slug: "disputes", route: "/disputes" },
  { slug: "submissions", route: "/submissions" },
  { slug: "batch", route: "/batch" },
];

test.describe("ops-suite verification", () => {
  test("login then sweep four ops pages", async ({ page }) => {
    test.setTimeout(360_000);

    const consoleErrorsByPage: Record<string, string[]> = {};
    const pageErrorsByPage: Record<string, string[]> = {};
    const netFailByPage: Record<string, { url: string; status: number }[]> = {};
    let currentSlug = "_pre_login_";
    consoleErrorsByPage[currentSlug] = [];
    pageErrorsByPage[currentSlug] = [];
    netFailByPage[currentSlug] = [];

    page.on("pageerror", (err) => {
      (pageErrorsByPage[currentSlug] ??= []).push(err.message);
    });
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        (consoleErrorsByPage[currentSlug] ??= []).push(msg.text());
      }
    });
    page.on("response", (resp) => {
      const url = resp.url();
      const status = resp.status();
      if (status >= 400 && url.includes("/api/")) {
        if (isNoiseRequest(url)) return;
        (netFailByPage[currentSlug] ??= []).push({ url, status });
      }
    });

    // Login
    await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" });
    await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 15_000 });
    await page.fill('input[type="email"]', EMAIL);
    await page.fill('input[type="password"]', PASSWORD);
    await page.click('button[type="submit"]');
    try {
      await page.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 });
    } catch {
      console.warn("[AUTH] waitForURL timed out:", page.url());
    }
    await page.waitForTimeout(2000);

    for (const { slug, route } of PAGES) {
      currentSlug = slug;
      consoleErrorsByPage[slug] = [];
      pageErrorsByPage[slug] = [];
      netFailByPage[slug] = [];
      const dir = path.join(SHOT_ROOT, slug);
      ensureDir(dir);

      console.log(`\n========== ${route} ==========`);
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.goto(`${BASE_URL}${route}`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(6000);
      await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
      await page.waitForTimeout(400);

      await page.screenshot({ path: path.join(dir, "01-desktop-top.png"), fullPage: false });
      await page.screenshot({ path: path.join(dir, "02-desktop-fullpage.png"), fullPage: true });

      const url = page.url();
      const heading = await page
        .locator("h1, h2")
        .first()
        .textContent()
        .catch(() => null);

      // Detect tables / kanban / lists / empty-state
      const tableCount = await page.locator("table").count();
      const tableRowCount = await page.locator("table tbody tr").count();
      const kanbanCount = await page
        .locator('[class*="kanban" i], [data-kanban], [class*="board" i]')
        .count();
      const listItemCount = await page
        .locator('ul li, [role="listitem"], [class*="list-row" i]')
        .count();
      const cardCount = await page
        .locator('[class*="card" i]')
        .count();
      const emptyHits: Record<string, number> = {};
      for (const phrase of [
        "No data",
        "no data",
        "No claims",
        "No disputes",
        "No submissions",
        "No batches",
        "No results",
        "Nothing here",
        "Empty",
        "0 of 0",
      ]) {
        emptyHits[phrase] = await page.getByText(phrase, { exact: false }).count();
      }
      const errorBannerHits = await page
        .getByText(/error|failed|something went wrong/i)
        .count();

      const bodyText = (await page.locator("body").innerText().catch(() => "")) || "";
      const bodyLen = bodyText.length;

      console.log(`[INFO] url=${url}`);
      console.log(`[INFO] heading=${(heading || "").trim()}`);
      console.log(
        `[CONTENT] tables=${tableCount} rows=${tableRowCount} kanban=${kanbanCount} listItems=${listItemCount} cards=${cardCount} bodyLen=${bodyLen}`
      );
      console.log(`[EMPTY_HITS] ${JSON.stringify(emptyHits)}`);
      console.log(`[ERROR_BANNER_HITS] ${errorBannerHits}`);

      // Mobile 414px
      await page.setViewportSize({ width: 414, height: 900 });
      await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
      await page.waitForTimeout(1500);
      await page.screenshot({ path: path.join(dir, "03-mobile-top.png"), fullPage: false });
      await page.screenshot({ path: path.join(dir, "04-mobile-fullpage.png"), fullPage: true });

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
      console.log(
        `[OVERFLOW] docW=${overflowInfo.docW} viewW=${overflowInfo.viewW} count=${overflowInfo.overflowing.length} ${JSON.stringify(overflowInfo.overflowing)}`
      );

      console.log(
        `[CONSOLE_ERRORS] ${slug} count=${consoleErrorsByPage[slug].length}`
      );
      consoleErrorsByPage[slug]
        .slice(0, 8)
        .forEach((e, i) => console.log(`  [CE ${i}] ${e.slice(0, 200)}`));
      console.log(`[PAGE_ERRORS] ${slug} count=${pageErrorsByPage[slug].length}`);
      pageErrorsByPage[slug]
        .slice(0, 5)
        .forEach((e, i) => console.log(`  [PE ${i}] ${e.slice(0, 200)}`));
      console.log(`[NET_FAIL] ${slug} count=${netFailByPage[slug].length}`);
      netFailByPage[slug]
        .slice(0, 12)
        .forEach((f, i) => console.log(`  [NF ${i}] ${f.status} ${f.url}`));
    }

    console.log("\n========== SUMMARY ==========");
    for (const { slug } of PAGES) {
      console.log(
        `${slug}: console=${consoleErrorsByPage[slug]?.length ?? 0} pageErr=${pageErrorsByPage[slug]?.length ?? 0} netFail=${netFailByPage[slug]?.length ?? 0}`
      );
    }
    console.log(`Pre-login console errors: ${consoleErrorsByPage["_pre_login_"]?.length ?? 0}`);
  });
});
