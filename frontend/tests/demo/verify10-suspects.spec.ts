/**
 * /suspects (review queue) end-to-end verification spec.
 *
 * Run with:
 *   cd frontend && npx playwright test tests/demo/verify10-suspects.spec.ts \
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
const API_URL = process.env.API_URL ?? "http://localhost:8500";
const EMAIL = "admin@raf.health";
const PASSWORD = "Admin@123";

const SHOT_DIR = path.resolve(__dirname, "../../demo-shots/iter3-03-suspects");

function ensureDir(d: string) {
  fs.mkdirSync(d, { recursive: true });
}

const consoleErrors: string[] = [];
const pageErrors: string[] = [];
const failedRequests: { url: string; status: number; method: string }[] = [];

test.describe("/suspects iter1-03 verification", () => {
  test.setTimeout(300_000);

  test("verify suspects page desktop + mobile + KG popover", async ({ browser }) => {
    ensureDir(SHOT_DIR);

    // Desktop context first
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
    });
    const page = await context.newPage();

    page.on("pageerror", (err) => {
      pageErrors.push(err.message);
      console.error("[PAGE ERROR]", err.message);
    });
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        consoleErrors.push(msg.text());
        console.error("[CONSOLE ERROR]", msg.text());
      }
    });
    page.on("requestfailed", (req) => {
      if (isNoiseRequest(req.url(), req.failure()?.errorText)) return;
      failedRequests.push({
        url: req.url(),
        status: 0,
        method: req.method(),
      });
      console.error("[REQ FAILED]", req.method(), req.url(), req.failure()?.errorText);
    });
    page.on("response", (resp) => {
      const url = resp.url();
      const status = resp.status();
      if (status >= 400 && (url.includes("/api/") || url.includes(API_URL))) {
        if (isNoiseRequest(url)) return;
        failedRequests.push({ url, status, method: resp.request().method() });
        console.error("[HTTP", status, "]", resp.request().method(), url);
      }
    });

    // ─── 1) Login ───────────────────────────────────────────────
    console.log("[1] Login");
    let loggedInViaApi = false;
    try {
      const loginResp = await page.request.post(`${API_URL}/api/auth/login`, {
        data: { email: EMAIL, password: PASSWORD },
      });
      if (loginResp.ok()) {
        const body = (await loginResp.json()) as { access_token?: string };
        loggedInViaApi = !!body.access_token;
        console.log("[1] API login OK");
      } else {
        console.log("[1] API login HTTP", loginResp.status());
      }
    } catch (e) {
      console.log("[1] API login error:", (e as Error).message);
    }

    if (!loggedInViaApi) {
      console.log("[1] Falling back to UI login");
      await page.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" });
      await page.waitForSelector('input[type="email"]', { timeout: 15_000 });
      await page.fill('input[type="email"]', EMAIL);
      await page.fill('input[type="password"]', PASSWORD);
      await page.click('button[type="submit"]');
      try {
        await page.waitForURL((u) => !u.pathname.startsWith("/login"), {
          timeout: 30_000,
        });
      } catch {
        console.log("[1] WARN: still on /login after submit");
      }
    }

    // ─── 2) Visit /suspects desktop ─────────────────────────────
    console.log("[2] Navigating to /suspects (desktop)");
    await page.goto(`${BASE_URL}/suspects`, { waitUntil: "domcontentloaded" });
    if (page.url().includes("/login")) {
      console.log("[2] WARN: ended up on /login");
    }
    await page.waitForSelector('h1, [role="alert"], button', { timeout: 30_000 });
    await page.waitForTimeout(5000);

    // Top viewport
    await page.screenshot({
      path: path.join(SHOT_DIR, "01-desktop-top.png"),
      fullPage: false,
    });
    // Full page
    await page.screenshot({
      path: path.join(SHOT_DIR, "02-desktop-fullpage.png"),
      fullPage: true,
    });

    const h1 = await page.locator("h1").first().textContent().catch(() => null);
    console.log("[2] h1:", h1?.trim());

    // ─── 3) Inspect status filter chips ──────────────────────────
    console.log("[3] Status filter chips");
    const allChip = page.getByRole("button", { name: /^All\b/ }).first();
    const openChip = page.getByRole("button", { name: /^Open\b/i }).first();
    const acceptedChip = page.getByRole("button", { name: /^Accepted\b/i }).first();
    const dismissedChip = page.getByRole("button", { name: /^Dismissed\b/i }).first();

    const allVisible = await allChip.isVisible().catch(() => false);
    const openVisible = await openChip.isVisible().catch(() => false);
    const acceptedVisible = await acceptedChip.isVisible().catch(() => false);
    const dismissedVisible = await dismissedChip.isVisible().catch(() => false);

    console.log(
      `[3] Chips visible — All:${allVisible} Open:${openVisible} Accepted:${acceptedVisible} Dismissed:${dismissedVisible}`,
    );

    // Status chip group height for touch target check
    const chipGroup = page.locator(".suspects-filter-chip-group").first();
    if (await chipGroup.isVisible().catch(() => false)) {
      const box = await chipGroup.boundingBox();
      console.log("[3] Status chip group bbox:", box);
    }

    // Click Accepted then Dismissed then back to Open
    if (acceptedVisible) {
      await acceptedChip.click();
      await page.waitForTimeout(1500);
      await page.screenshot({
        path: path.join(SHOT_DIR, "03-filter-accepted.png"),
        fullPage: false,
      });
    }
    if (dismissedVisible) {
      await dismissedChip.click();
      await page.waitForTimeout(1500);
      await page.screenshot({
        path: path.join(SHOT_DIR, "04-filter-dismissed.png"),
        fullPage: false,
      });
    }
    if (openVisible) {
      await openChip.click();
      await page.waitForTimeout(1500);
    }

    // ─── 4) Search filter ────────────────────────────────────────
    console.log("[4] Search filter");
    // Dismiss any pre-existing command palette modal so it doesn't block
    const preDialog = await page.locator('[role="dialog"][aria-label="Command palette"]').count();
    console.log(`[4] Pre-existing command palette dialogs: ${preDialog}`);
    if (preDialog > 0) {
      await page.keyboard.press("Escape");
      await page.waitForTimeout(500);
      const afterEsc = await page.locator('[role="dialog"][aria-label="Command palette"]').count();
      console.log(`[4] After Escape, palette count: ${afterEsc}`);
    }
    const searchInput = page.getByPlaceholder(/Search suspects/i).first();
    let paletteAfterTyping = false;
    let typedValueExact = "";
    let rowCountBeforeSearch = 0;
    let rowCountAfterSearch = 0;
    if (await searchInput.isVisible().catch(() => false)) {
      // CRITICAL palette-fix test: type via keyboard.type (not fill) to send real keydowns
      rowCountBeforeSearch = await page.locator('button[aria-label="Accept suspect"], button[title="Accept"]').count();
      await searchInput.click({ timeout: 5000 }).catch(async (e) => {
        console.log(`[4] click failed: ${(e as Error).message.slice(0, 200)}`);
        await searchInput.focus();
      });
      await searchInput.focus();
      await page.keyboard.type("diabetes", { delay: 30 });
      await page.waitForTimeout(800);
      typedValueExact = (await searchInput.inputValue()) ?? "";
      const dialogCount = await page.locator('[role="dialog"]').count();
      const cmdkCount = await page.locator('[cmdk-root], [cmdk-list]').count();
      paletteAfterTyping = dialogCount > 0 || cmdkCount > 0;
      console.log(`[4] PALETTE-FIX inputValue="${typedValueExact}" dialogs=${dialogCount} cmdk=${cmdkCount}`);
      await page.screenshot({
        path: path.join(SHOT_DIR, "04b-search-typed-diabetes.png"),
        fullPage: false,
      });
      rowCountAfterSearch = await page.locator('button[aria-label="Accept suspect"], button[title="Accept"]').count();
      console.log(`[4] rows before=${rowCountBeforeSearch} after=${rowCountAfterSearch}`);
      // clear and re-test with E11
      await searchInput.fill("");
      await page.waitForTimeout(500);
      await searchInput.fill("E11");
      await page.waitForTimeout(1500);
      await page.screenshot({
        path: path.join(SHOT_DIR, "05-search-E11.png"),
        fullPage: false,
      });
      await searchInput.fill("");
      await page.waitForTimeout(1000);
    } else {
      console.log("[4] Search input NOT visible");
    }
    // Surface key results in summary
    (globalThis as any).__paletteAfterTyping = paletteAfterTyping;
    (globalThis as any).__typedValueExact = typedValueExact;
    (globalThis as any).__rowCountBeforeSearch = rowCountBeforeSearch;
    (globalThis as any).__rowCountAfterSearch = rowCountAfterSearch;

    // ─── 5) Confidence band ──────────────────────────────────────
    console.log("[5] Confidence band");
    // Implementation uses chips ("High", "Medium", "Low"), not a dropdown.
    const highChip = page.getByRole("button", { name: /^High$/i }).first();
    const mediumChip = page.getByRole("button", { name: /^Medium$/i }).first();
    const highVisible = await highChip.isVisible().catch(() => false);
    const mediumVisible = await mediumChip.isVisible().catch(() => false);
    console.log(`[5] Confidence chips — High:${highVisible} Medium:${mediumVisible}`);
    if (highVisible) {
      await highChip.click();
      await page.waitForTimeout(1500);
      await page.screenshot({
        path: path.join(SHOT_DIR, "06-confidence-high.png"),
        fullPage: false,
      });
      // reset
      const allConfChip = page.getByRole("button", { name: /^All$/ }).first();
      if (await allConfChip.isVisible().catch(() => false)) {
        await allConfChip.click();
        await page.waitForTimeout(1000);
      }
    }

    // ─── 6) Row inspection ───────────────────────────────────────
    console.log("[6] Suspect rows inspection");
    const acceptBtns = page.locator('button[aria-label="Accept suspect"], button[title="Accept"]');
    const dismissBtns = page.locator('button[aria-label="Dismiss suspect"], button[title="Dismiss"]');
    const acceptCount = await acceptBtns.count();
    const dismissCount = await dismissBtns.count();
    console.log(`[6] Accept buttons: ${acceptCount} | Dismiss buttons: ${dismissCount}`);

    // Touch-target measure for first action button
    if (acceptCount > 0) {
      const box = await acceptBtns.first().boundingBox();
      console.log("[6] First Accept btn bbox:", box);
    }
    if (dismissCount > 0) {
      const box = await dismissBtns.first().boundingBox();
      console.log("[6] First Dismiss btn bbox:", box);
    }

    // Row hover screenshot
    const firstActionRow = acceptBtns.first();
    if (acceptCount > 0) {
      await firstActionRow.scrollIntoViewIfNeeded();
      // hover the row container — go up 8 ancestors to capture row
      await firstActionRow.hover();
      await page.waitForTimeout(800);
      await page.screenshot({
        path: path.join(SHOT_DIR, "07-row-hover.png"),
        fullPage: false,
      });
    }

    // ─── 7) KG popover (HCC chip click) ──────────────────────────
    console.log("[7] KG popover via HCC chip");
    // HCC chips are buttons containing "HCC " text (e.g., "HCC 18")
    const hccChip = page
      .locator('button:has-text("HCC"), button[aria-label*="HCC"]')
      .first();
    const hccVisible = await hccChip.isVisible().catch(() => false);
    console.log("[7] HCC chip visible:", hccVisible);
    if (hccVisible) {
      await hccChip.scrollIntoViewIfNeeded();
      await hccChip.click();
      await page.waitForTimeout(2500);
      await page.screenshot({
        path: path.join(SHOT_DIR, "08-kg-popover.png"),
        fullPage: false,
      });
      // probe popover content
      const popoverText = await page.locator('[role="dialog"], [class*="popover"], [class*="Popover"]').first().textContent().catch(() => null);
      console.log("[7] popover text head:", popoverText?.slice(0, 200));
      // close
      await page.keyboard.press("Escape");
      await page.waitForTimeout(500);
    }

    // ─── 8) API probe for suspects ───────────────────────────────
    console.log("[8] API probe");
    try {
      const resp = await page.request.get(`${API_URL}/api/suspects?limit=5`);
      console.log("[8] /api/suspects status:", resp.status());
      if (resp.ok()) {
        const body = (await resp.json()) as { items?: unknown[]; total?: number };
        console.log("[8] suspects total:", body.total, "items in page:", body.items?.length);
      }
    } catch (e) {
      console.log("[8] suspects probe error:", (e as Error).message);
    }

    await context.close();

    // ─── 9) Mobile (414px) ───────────────────────────────────────
    console.log("[9] Mobile 414px viewport");
    const mobileCtx = await browser.newContext({
      viewport: { width: 414, height: 896 },
      deviceScaleFactor: 2,
      userAgent:
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
    });
    const mPage = await mobileCtx.newPage();

    mPage.on("pageerror", (err) => pageErrors.push("[mobile]" + err.message));
    mPage.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push("[mobile]" + msg.text());
    });
    mPage.on("response", (resp) => {
      const url = resp.url();
      const status = resp.status();
      if (status >= 400 && (url.includes("/api/") || url.includes(API_URL))) {
        if (isNoiseRequest(url)) return;
        failedRequests.push({ url: "[mobile]" + url, status, method: resp.request().method() });
      }
    });

    // Mobile login via UI
    await mPage.goto(`${BASE_URL}/login`, { waitUntil: "domcontentloaded" });
    await mPage.waitForSelector('input[type="email"]', { timeout: 15_000 });
    await mPage.fill('input[type="email"]', EMAIL);
    await mPage.fill('input[type="password"]', PASSWORD);
    await mPage.click('button[type="submit"]');
    try {
      await mPage.waitForURL((u) => !u.pathname.startsWith("/login"), { timeout: 30_000 });
    } catch {
      console.log("[9] mobile still on /login after submit");
    }

    await mPage.goto(`${BASE_URL}/suspects`, { waitUntil: "domcontentloaded" });
    await mPage.waitForSelector('h1, button', { timeout: 30_000 });
    await mPage.waitForTimeout(5000);

    await mPage.screenshot({
      path: path.join(SHOT_DIR, "09-mobile-top.png"),
      fullPage: false,
    });
    await mPage.screenshot({
      path: path.join(SHOT_DIR, "10-mobile-fullpage.png"),
      fullPage: true,
    });

    // Horizontal overflow check
    const overflowMetrics = await mPage.evaluate(() => {
      const docW = document.documentElement.scrollWidth;
      const winW = window.innerWidth;
      return { docW, winW, overflow: docW - winW };
    });
    console.log("[9] Mobile overflow:", overflowMetrics);

    // Touch targets on mobile
    const mAcceptBtns = mPage.locator('button[aria-label="Accept suspect"], button[title="Accept"]');
    const mDismissBtns = mPage.locator('button[aria-label="Dismiss suspect"], button[title="Dismiss"]');
    const mAcceptCount = await mAcceptBtns.count();
    const mDismissCount = await mDismissBtns.count();
    console.log(`[9] Mobile Accept btns: ${mAcceptCount} | Dismiss: ${mDismissCount}`);
    if (mAcceptCount > 0) {
      const box = await mAcceptBtns.first().boundingBox();
      console.log("[9] Mobile Accept bbox:", box);
    }
    if (mDismissCount > 0) {
      const box = await mDismissBtns.first().boundingBox();
      console.log("[9] Mobile Dismiss bbox:", box);
    }
    const mChipGroup = mPage.locator(".suspects-filter-chip-group").first();
    if (await mChipGroup.isVisible().catch(() => false)) {
      const box = await mChipGroup.boundingBox();
      console.log("[9] Mobile status chip group bbox:", box);
    }

    await mobileCtx.close();

    // ─── Summary ─────────────────────────────────────────────────
    console.log("\n========= /suspects VERIFY SUMMARY =========");
    console.log("Accept count desktop:", acceptCount);
    console.log("Dismiss count desktop:", dismissCount);
    console.log("All chip visible:", allVisible);
    console.log("Open chip visible:", openVisible);
    console.log("Palette opened on type:", (globalThis as any).__paletteAfterTyping);
    console.log("Typed value exact:", (globalThis as any).__typedValueExact);
    console.log("Row count before search:", (globalThis as any).__rowCountBeforeSearch);
    console.log("Row count after search:", (globalThis as any).__rowCountAfterSearch);
    console.log("Console errors:", consoleErrors.length);
    console.log("Page errors:", pageErrors.length);
    console.log("Failed network requests:", failedRequests.length);
    failedRequests.forEach((f) => console.log("  ", f.method, f.status, f.url));
    consoleErrors.forEach((e, i) => console.log(`  [CE${i}]`, e));
    pageErrors.forEach((e, i) => console.log(`  [PE${i}]`, e));
    console.log("============================================");
  });
});
