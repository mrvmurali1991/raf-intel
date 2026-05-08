/**
 * /forecast page end-to-end verification spec.
 *
 * Run with:
 *   cd frontend && BASE_URL=http://localhost:3444 \
 *     npx playwright test tests/demo/verify10-forecast.spec.ts --reporter=line
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

const SHOT_DIR = path.resolve(__dirname, "../../demo-shots/iter8-forecast");

function ensureDir(d: string) {
  fs.mkdirSync(d, { recursive: true });
}

interface FailedRequest {
  url: string;
  status: number | null;
  statusText: string;
  method: string;
}

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
  return accessToken;
}

test.describe("/forecast verification", () => {
  test.setTimeout(120000);

  test("verify forecast page end-to-end", async ({ page, request }) => {
    ensureDir(SHOT_DIR);

    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    const failedRequests: FailedRequest[] = [];
    const forecastCalls: { url: string; status: number; method: string }[] = [];

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
    });
    page.on("response", (resp) => {
      const s = resp.status();
      const u = resp.url();
      if (u.includes("/api/forecast")) {
        forecastCalls.push({ url: u, status: s, method: resp.request().method() });
      }
      if (s >= 400) {
        if (isNoiseRequest(u)) return;
        failedRequests.push({
          url: u,
          status: s,
          statusText: resp.statusText(),
          method: resp.request().method(),
        });
        console.error("[HTTP ERROR]", s, resp.request().method(), u);
      }
    });

    console.log("[1] API login + cookie injection");
    await apiLoginAndInject(page, request);

    // ---------- Desktop ----------
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`${BASE_URL}/forecast`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(6000);

    console.log("[2] URL after nav:", page.url());

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

    // Check for key forecast content
    const sections = [
      { name: "header", regex: /RAF Financial Forecast/i, file: "03-header.png" },
      { name: "metrics", regex: /Suspect Lift|Projected|Current/i, file: "04-metrics.png" },
      { name: "chart", regex: /Top Suspects|HCC/i, file: "05-chart.png" },
    ];

    const sectionFound: Record<string, boolean> = {};
    for (const s of sections) {
      const loc = page.getByText(s.regex).first();
      try {
        const cnt = await loc.count();
        sectionFound[s.name] = cnt > 0;
        if (cnt > 0) {
          await loc.scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => null);
          await page.waitForTimeout(300);
          const box = await loc.boundingBox().catch(() => null);
          if (box) {
            await page.screenshot({
              path: path.join(SHOT_DIR, s.file),
              clip: {
                x: 0,
                y: Math.max(0, box.y - 40),
                width: 1440,
                height: 500,
              },
            });
          }
          console.log(`[section] ${s.name}: FOUND`);
        } else {
          console.log(`[section] ${s.name}: NOT FOUND`);
        }
      } catch (e) {
        sectionFound[s.name] = false;
        console.log(`[section] ${s.name}: error ${(e as Error).message}`);
      }
    }

    // Try a few patient IDs
    const pidsToTry = [3, 4, 5, 17];
    for (const pid of pidsToTry) {
      const input = page.locator('#pid');
      if ((await input.count()) === 0) break;
      await input.fill(String(pid));
      await page.waitForTimeout(2000);
    }
    await page.screenshot({
      path: path.join(SHOT_DIR, "06-after-pid-changes.png"),
      fullPage: true,
    });

    // Spinner check — should not be present after 6s
    const spinnerCount = await page.locator('[class*="animate-spin"]').count();
    const calculatingText = await page.getByText(/Calculating financial forecast/i).count();
    console.log("[spinners] count:", spinnerCount, " calculating msgs:", calculatingText);

    // Recharts SVG check
    const svgCount = await page.locator('svg.recharts-surface').count();
    console.log("[charts] recharts svg count:", svgCount);

    // ---------- Mobile ----------
    await page.setViewportSize({ width: 414, height: 896 });
    await page.goto(`${BASE_URL}/forecast`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(5000);

    await page.screenshot({
      path: path.join(SHOT_DIR, "07-mobile-top.png"),
      fullPage: false,
    });
    await page.screenshot({
      path: path.join(SHOT_DIR, "08-mobile-fullpage.png"),
      fullPage: true,
    });

    const horizOverflow = await page.evaluate(() => {
      const docW = document.documentElement.scrollWidth;
      const winW = window.innerWidth;
      return { docW, winW, overflow: docW - winW };
    });
    console.log("[mobile] horizontal overflow:", JSON.stringify(horizOverflow));

    console.log("\n========= SUMMARY =========");
    console.log("Console errors:", consoleErrors.length);
    consoleErrors.slice(0, 10).forEach((e, i) => console.log(`  [CE ${i}] ${e.slice(0, 200)}`));
    console.log("Page errors:", pageErrors.length);
    pageErrors.slice(0, 10).forEach((e, i) => console.log(`  [PE ${i}] ${e.slice(0, 200)}`));
    console.log("Failed requests:", failedRequests.length);
    failedRequests.slice(0, 25).forEach((r, i) =>
      console.log(`  [REQ ${i}] ${r.method} ${r.status ?? "ERR"} ${r.statusText} ${r.url}`)
    );
    console.log("Forecast API calls:", forecastCalls.length);
    forecastCalls.slice(0, 30).forEach((r, i) =>
      console.log(`  [FC ${i}] ${r.method} ${r.status} ${r.url}`)
    );
    console.log("Sections found:", JSON.stringify(sectionFound));
    console.log("Spinner count:", spinnerCount, " Calculating msgs:", calculatingText);
    console.log("Recharts SVG count:", svgCount);
    console.log("Mobile overflow px:", horizOverflow.overflow);
    console.log("===========================");

    expect(page.url()).toContain("/forecast");
  });
});
