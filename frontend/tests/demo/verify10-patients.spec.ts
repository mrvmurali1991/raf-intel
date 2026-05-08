/**
 * /patients (PatientsPage) end-to-end verification spec.
 *
 * THROWAWAY — verification only.
 *
 * Run with:
 *   cd frontend && BASE_URL=http://localhost:3444 \
 *     npx playwright test tests/demo/verify10-patients.spec.ts --reporter=line
 */

import { test, expect, type Page, type Request, type APIRequestContext } from "@playwright/test";
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
const API_URL = process.env.API_URL ?? "http://localhost:8500";
const EMAIL = "admin@raf.health";
const PASSWORD = "Admin@123";

const SHOT_DIR = path.resolve(__dirname, "../../demo-shots/iter3-01-patients");

function ensureDir(d: string) {
  fs.mkdirSync(d, { recursive: true });
}

interface FailedRequest {
  url: string;
  status: number | null;
  statusText: string;
  method: string;
}

/**
 * Log in directly via the backend API and inject the resulting refresh-token
 * cookie + access token into the browser context. This bypasses the strict
 * 5/min IP rate limit on /api/auth/login that breaks UI-form login during
 * iterative test runs.
 */
async function apiLoginAndInject(page: Page, request: APIRequestContext): Promise<string> {
  const resp = await request.post(`${API_URL}/api/auth/login`, {
    data: { email: EMAIL, password: PASSWORD },
    headers: { "Content-Type": "application/json" },
    failOnStatusCode: false,
  });
  if (!resp.ok()) {
    throw new Error(`API login failed ${resp.status()}: ${await resp.text()}`);
  }
  const body = (await resp.json()) as { access_token: string };
  const accessToken = body.access_token;

  // Read Set-Cookie header to extract raf_refresh_token
  const setCookie = resp.headers()["set-cookie"] ?? "";
  const m = /raf_refresh_token=([^;]+)/.exec(setCookie);
  const refreshToken = m ? m[1] : "";

  const cookies: Parameters<typeof page.context.prototype.addCookies>[0] = [];
  if (refreshToken) {
    cookies.push({
      name: "raf_refresh_token",
      value: refreshToken,
      domain: "localhost",
      path: "/",
      httpOnly: true,
      secure: false,
      sameSite: "Lax",
    });
  }
  // raf_authenticated flag — read by middleware to allow SSR-protected routes
  cookies.push({
    name: "raf_authenticated",
    value: "true",
    domain: "localhost",
    path: "/",
    httpOnly: false,
    secure: false,
    sameSite: "Strict",
  });
  await page.context().addCookies(cookies);

  // Visit a lightweight page so we can inject access token into in-memory
  // axios defaults via window.localStorage / fetch interception.
  // The frontend keeps access token only in a module-scoped variable, but on
  // page load it bootstraps by calling /api/auth/refresh (which reads the
  // refresh cookie) — so injecting the refresh cookie alone is sufficient.
  return accessToken;
}

test.describe("/patients verification", () => {
  test("verify patients list end-to-end", async ({ page, request }) => {
    ensureDir(SHOT_DIR);

    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    const failedRequests: FailedRequest[] = [];

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
    page.on("requestfailed", (req: Request) => {
      const f = req.failure();
      if (isNoiseRequest(req.url(), f?.errorText)) return;
      failedRequests.push({
        url: req.url(),
        status: null,
        statusText: f?.errorText ?? "failed",
        method: req.method(),
      });
      console.error("[REQ FAILED]", req.method(), req.url(), f?.errorText);
    });
    page.on("response", (resp) => {
      const s = resp.status();
      if (s >= 400) {
        if (isNoiseRequest(resp.url())) return;
        failedRequests.push({
          url: resp.url(),
          status: s,
          statusText: resp.statusText(),
          method: resp.request().method(),
        });
        console.error("[HTTP ERROR]", s, resp.request().method(), resp.url());
      }
    });

    // ---------- Step 1 — Login via API (avoids login-form rate limiter) ----------
    console.log("[1] API login + cookie injection");
    await apiLoginAndInject(page, request);

    // ---------- Step 2 — Visit /patients (desktop 1440x900) ----------
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE_URL}/patients`, { waitUntil: "domcontentloaded" });
    // Wait for data to render
    await page.waitForTimeout(6000);

    console.log("[2] URL after nav:", page.url());

    // ---------- Step 3 — Inspect Population hero card values ----------
    // Hero block has "Population Overview" / "Patient Population" header.
    const heroHeading = page.getByText(/Patient Population/i).first();
    const heroCount = await heroHeading.count();
    console.log("[3] hero heading count:", heroCount);

    // Read total patients big number
    const allFilterPill = page.getByRole("button", { name: /All Patients/i }).first();
    const allPillText = await allFilterPill.textContent().catch(() => null);
    console.log("[3] All Patients pill text:", allPillText?.trim());

    // Count rows in the patient table (rows are role="row" divs)
    const rowCount = await page.locator('[role="row"]').count();
    console.log("[3] role=row count:", rowCount);

    // Collect RAF score column text from rows
    const rafCellTexts: string[] = [];
    const rows = page.locator('[role="row"]');
    const numRows = await rows.count();
    for (let i = 0; i < Math.min(numRows, 10); i++) {
      const txt = await rows.nth(i).textContent().catch(() => "");
      rafCellTexts.push((txt || "").replace(/\s+/g, " ").slice(0, 200));
    }
    console.log("[3] sample row texts:");
    rafCellTexts.forEach((t, i) => console.log(`    [row ${i}] ${t}`));

    // ---------- Step 4 — Screenshot full page (desktop) ----------
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
    await page.waitForTimeout(400);
    await page.screenshot({
      path: path.join(SHOT_DIR, "01-desktop-top.png"),
      fullPage: false,
    });
    await page.screenshot({
      path: path.join(SHOT_DIR, "02-desktop-fullpage.png"),
      fullPage: true,
    });
    console.log("[4] desktop screenshots saved");

    // ---------- Step 5 — Hero card close-up ----------
    {
      const hero = page.getByText(/Patient Population/i).first();
      const cnt = await hero.count();
      if (cnt > 0) {
        await hero.scrollIntoViewIfNeeded();
        const box = await hero.boundingBox();
        if (box) {
          await page.screenshot({
            path: path.join(SHOT_DIR, "03-hero-card.png"),
            clip: {
              x: 0,
              y: Math.max(0, box.y - 20),
              width: 1440,
              height: 360,
            },
          });
          console.log("[5] hero close-up saved");
        }
      }
    }

    // ---------- Step 6 — Risk distribution bar close-up ----------
    {
      // Look for the colored stacked bar segments — they have aria-label "Filter to ... risk"
      const bar = page.locator('[aria-label*="Filter to"][aria-label*="risk"]').first();
      const barCount = await bar.count();
      console.log("[6] risk-bar aria segments:", barCount);
      if (barCount > 0) {
        await bar.scrollIntoViewIfNeeded();
        const box = await bar.boundingBox();
        if (box) {
          await page.screenshot({
            path: path.join(SHOT_DIR, "04-risk-bar.png"),
            clip: {
              x: 0,
              y: Math.max(0, box.y - 60),
              width: 1440,
              height: 180,
            },
          });
        }
      }
    }

    // ---------- Step 7 — Filter pills close-up ----------
    {
      const allPill = page.getByRole("button", { name: /All Patients/i }).first();
      const cnt = await allPill.count();
      if (cnt > 0) {
        await allPill.scrollIntoViewIfNeeded();
        const box = await allPill.boundingBox();
        if (box) {
          await page.screenshot({
            path: path.join(SHOT_DIR, "05-filter-pills.png"),
            clip: {
              x: 0,
              y: Math.max(0, box.y - 10),
              width: 1440,
              height: 80,
            },
          });
          console.log("[7] filter pills saved (pill height:", Math.round(box.height), ")");
        }
      }
    }

    // ---------- Step 8 — Table screenshot + row hover ----------
    {
      const firstRow0 = page.locator('[role="row"]').first();
      const cnt = await firstRow0.count();
      if (cnt > 0) {
        await firstRow0.scrollIntoViewIfNeeded();
        const box = await firstRow0.boundingBox();
        if (box) {
          await page.screenshot({
            path: path.join(SHOT_DIR, "06-patient-table.png"),
            clip: {
              x: 0,
              y: Math.max(0, box.y - 80),
              width: 1440,
              height: 700,
            },
          });
          console.log("[8] table screenshot saved");
        }
      }
      const firstRow = page.locator('[role="row"][aria-label]').first();
      const fr = await firstRow.count();
      if (fr > 0) {
        await firstRow.hover().catch(() => null);
        await page.waitForTimeout(400);
        const box = await firstRow.boundingBox();
        if (box) {
          await page.screenshot({
            path: path.join(SHOT_DIR, "07-row-hover.png"),
            clip: {
              x: 0,
              y: Math.max(0, box.y - 8),
              width: 1440,
              height: box.height + 16,
            },
          });
        }
      }
    }

    // ---------- Step 9 — Filter pills functionality ----------
    const filterCheck: Record<string, { initialRows: number; afterRows: number }> = {};
    for (const label of ["High Risk", "Medium", "Low", "Unscored", "All Patients"]) {
      const pill = page.getByRole("button", { name: new RegExp(label, "i") }).first();
      const cnt = await pill.count();
      if (cnt === 0) {
        console.log(`[9] pill "${label}" NOT found`);
        continue;
      }
      const before = await page.locator('[role="row"]').count();
      await pill.click();
      await page.waitForTimeout(1500);
      const after = await page.locator('[role="row"]').count();
      filterCheck[label] = { initialRows: before, afterRows: after };
      console.log(`[9] pill "${label}": rows ${before} -> ${after}`);
    }

    // Restore "All Patients"
    const restoreAll = page.getByRole("button", { name: /All Patients/i }).first();
    if (await restoreAll.count()) {
      await restoreAll.click();
      await page.waitForTimeout(1500);
    }

    // ---------- Step 10 — Search box ----------
    const searchInput = page.locator('input[type="text"], input[type="search"]').first();
    let searchWorks = false;
    let searchPlaceholder = "";
    if (await searchInput.count()) {
      searchPlaceholder = (await searchInput.getAttribute("placeholder")) ?? "";
      console.log("[10] search placeholder raw:", JSON.stringify(searchPlaceholder));
      const codepoints = Array.from(searchPlaceholder).map(c => c.codePointAt(0)?.toString(16));
      console.log("[10] search placeholder codepoints:", codepoints.join(","));
      const beforeSearch = await page.locator('[role="row"]').count();
      // type a likely-no-match string
      await searchInput.fill("ZZZZZNOMATCH");
      await page.waitForTimeout(2000);
      const afterSearch = await page.locator('[role="row"]').count();
      console.log(`[10] search 'ZZZZZNOMATCH': rows ${beforeSearch} -> ${afterSearch}`);
      searchWorks = afterSearch < beforeSearch;
      // restore
      await searchInput.fill("");
      await page.waitForTimeout(1500);
    } else {
      console.log("[10] no search input found");
    }

    // ---------- Step 11 — Click first DATA patient row -> /patients/{pid} ----------
    // The first [role="row"] is the table header; the data rows have aria-label
    // starting with the patient name.
    let rowClickNavigates = false;
    {
      const dataRow = page.locator('[role="row"][aria-label]').first();
      const cnt = await dataRow.count();
      console.log("[11] data-row count (with aria-label):", cnt);
      if (cnt) {
        const ariaLabel = await dataRow.getAttribute("aria-label");
        console.log("[11] clicking row with aria-label:", ariaLabel?.slice(0, 80));
        const urlBefore = page.url();
        await dataRow.click().catch(() => null);
        await page.waitForTimeout(3500);
        const urlAfter = page.url();
        console.log(`[11] before='${urlBefore}', after='${urlAfter}'`);
        rowClickNavigates = /\/patients\/[^/?#]+/.test(urlAfter) && !urlAfter.endsWith("/patients");
      }
    }
    if (rowClickNavigates) {
      // Go back
      await page.goBack();
      await page.waitForTimeout(2500);
    }

    // ---------- Step 12 — Mobile viewport ----------
    await page.setViewportSize({ width: 414, height: 896 });
    await page.goto(`${BASE_URL}/patients`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(5000);

    await page.screenshot({
      path: path.join(SHOT_DIR, "08-mobile-top.png"),
      fullPage: false,
    });
    await page.screenshot({
      path: path.join(SHOT_DIR, "09-mobile-fullpage.png"),
      fullPage: true,
    });

    // Horizontal overflow check
    const horizOverflow = await page.evaluate(() => {
      const docW = document.documentElement.scrollWidth;
      const winW = window.innerWidth;
      return { docW, winW, overflow: docW - winW };
    });
    console.log("[12] mobile horizontal overflow:", JSON.stringify(horizOverflow));

    // Touch target sizes for filter pills (.rci-filter-pill scopes to the pill row)
    const pillSizes: { label: string; width: number; height: number }[] = [];
    const filterPills = page.locator(".rci-filter-pill");
    const fpCount = await filterPills.count();
    for (let i = 0; i < fpCount; i++) {
      const p = filterPills.nth(i);
      const txt = (await p.textContent().catch(() => "")) ?? "";
      const box = await p.boundingBox();
      if (box) {
        pillSizes.push({
          label: txt.trim().slice(0, 30),
          width: Math.round(box.width),
          height: Math.round(box.height),
        });
      }
    }
    console.log("[12] mobile filter-pill sizes:", JSON.stringify(pillSizes));
    const pillsTooSmall = pillSizes.filter(p => p.height < 44 || p.width < 44);
    console.log("[12] mobile pills < 44x44:", pillsTooSmall.length, JSON.stringify(pillsTooSmall));

    // ---------- Final ----------
    console.log("\n========= SUMMARY =========");
    console.log("Console errors:", consoleErrors.length);
    consoleErrors.slice(0, 10).forEach((e, i) => console.log(`  [CE ${i}] ${e.slice(0, 200)}`));
    console.log("Page errors:", pageErrors.length);
    pageErrors.slice(0, 10).forEach((e, i) => console.log(`  [PE ${i}] ${e.slice(0, 200)}`));
    console.log("Failed requests:", failedRequests.length);
    failedRequests.slice(0, 15).forEach((r, i) =>
      console.log(`  [REQ ${i}] ${r.method} ${r.status ?? "ERR"} ${r.statusText} ${r.url}`)
    );
    console.log("Filter check:", JSON.stringify(filterCheck));
    console.log("Search works:", searchWorks);
    console.log("Row click navigates:", rowClickNavigates);
    console.log("Mobile overflow px:", horizOverflow.overflow);
    console.log("Search placeholder:", JSON.stringify(searchPlaceholder));
    console.log("===========================");

    expect(rowCount).toBeGreaterThan(0);
  });
});
