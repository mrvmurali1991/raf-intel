/**
 * /uploads + /documents verification spec — iter7.
 *
 * Run with:
 *   cd frontend && BASE_URL=http://localhost:3444 \
 *     npx playwright test tests/demo/verify10-uploads-docs.spec.ts --reporter=line
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

const SHOT_ROOT = path.resolve(__dirname, "../../demo-shots/iter8-uploads-docs");

function ensureDir(d: string) {
  fs.mkdirSync(d, { recursive: true });
}

interface FailedRequest {
  url: string;
  status: number | null;
  statusText: string;
  method: string;
}

async function apiLoginAndInject(page: Page, request: APIRequestContext): Promise<void> {
  let resp = await request.post(`${API_URL}/api/auth/login`, {
    data: { email: EMAIL, password: PASSWORD },
    headers: { "Content-Type": "application/json" },
    failOnStatusCode: false,
  });
  // Handle 429 rate limit by waiting up to 90s
  let attempts = 0;
  while (resp.status() === 429 && attempts < 9) {
    console.log(`[login] 429 rate limited, waiting 10s (attempt ${attempts + 1})`);
    await new Promise((r) => setTimeout(r, 10_000));
    resp = await request.post(`${API_URL}/api/auth/login`, {
      data: { email: EMAIL, password: PASSWORD },
      headers: { "Content-Type": "application/json" },
      failOnStatusCode: false,
    });
    attempts++;
  }
  if (!resp.ok()) {
    throw new Error(`API login failed ${resp.status()}: ${await resp.text()}`);
  }
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
}

async function verifyPage(
  page: Page,
  request: APIRequestContext,
  route: string,
  shotSubdir: string,
): Promise<void> {
  const SHOT_DIR = path.join(SHOT_ROOT, shotSubdir);
  ensureDir(SHOT_DIR);

  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const failedRequests: FailedRequest[] = [];

  page.on("pageerror", (err) => {
    pageErrors.push(err.message);
    console.error(`[${route}][PAGE ERROR]`, err.message);
  });
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      consoleErrors.push(msg.text());
      console.error(`[${route}][CONSOLE ERROR]`, msg.text().slice(0, 300));
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
    console.error(`[${route}][REQ FAILED]`, req.method(), req.url(), f?.errorText);
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
      console.error(`[${route}][HTTP ERROR]`, s, resp.request().method(), resp.url());
    }
  });

  await apiLoginAndInject(page, request);

  // Desktop
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`${BASE_URL}${route}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(6000);

  // Spinner check
  const spinnerCount = await page.locator('[role="progressbar"], .spinner, [aria-busy="true"]').count();
  console.log(`[${route}] spinner-like count after 6s:`, spinnerCount);

  // Look for drop zone / file input / table
  const fileInputCount = await page.locator('input[type="file"]').count();
  const dropZoneCount = await page.locator('[class*="drop"], [class*="Drop"], [data-testid*="drop"]').count();
  const tableCount = await page.locator('table, [role="table"], [role="grid"]').count();
  const rowCount = await page.locator('[role="row"], tbody tr').count();
  const emptyStateCount = await page.getByText(/no\s+(files|documents|uploads|results)|empty|nothing/i).count();
  console.log(`[${route}] file-input:${fileInputCount} drop:${dropZoneCount} table:${tableCount} rows:${rowCount} empty:${emptyStateCount}`);

  await page.screenshot({
    path: path.join(SHOT_DIR, "01-desktop-top.png"),
    fullPage: false,
  });
  await page.screenshot({
    path: path.join(SHOT_DIR, "02-desktop-fullpage.png"),
    fullPage: true,
  });

  // Capture page heading text for context
  const h1 = await page.locator("h1, h2").first().textContent().catch(() => "");
  console.log(`[${route}] heading:`, (h1 || "").trim().slice(0, 120));

  // Mobile
  await page.setViewportSize({ width: 414, height: 896 });
  await page.goto(`${BASE_URL}${route}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(5000);

  await page.screenshot({
    path: path.join(SHOT_DIR, "03-mobile-top.png"),
    fullPage: false,
  });
  await page.screenshot({
    path: path.join(SHOT_DIR, "04-mobile-fullpage.png"),
    fullPage: true,
  });

  const horizOverflow = await page.evaluate(() => {
    const docW = document.documentElement.scrollWidth;
    const winW = window.innerWidth;
    return { docW, winW, overflow: docW - winW };
  });
  console.log(`[${route}] mobile horizontal overflow:`, JSON.stringify(horizOverflow));

  console.log(`\n========= SUMMARY ${route} =========`);
  console.log("Console errors:", consoleErrors.length);
  consoleErrors.slice(0, 15).forEach((e, i) => console.log(`  [CE ${i}] ${e.slice(0, 250)}`));
  console.log("Page errors:", pageErrors.length);
  pageErrors.slice(0, 15).forEach((e, i) => console.log(`  [PE ${i}] ${e.slice(0, 250)}`));
  console.log("Failed requests:", failedRequests.length);
  failedRequests.slice(0, 25).forEach((r, i) =>
    console.log(`  [REQ ${i}] ${r.method} ${r.status ?? "ERR"} ${r.statusText} ${r.url}`)
  );
  console.log(`Mobile overflow px: ${horizOverflow.overflow}`);
  console.log(`==================================\n`);
}

test.describe("/uploads + /documents verification", () => {
  test("verify /uploads", async ({ page, request }) => {
    await verifyPage(page, request, "/uploads", "uploads");
  });

  test("verify /documents", async ({ page, request }) => {
    await verifyPage(page, request, "/documents", "documents");
  });
});
