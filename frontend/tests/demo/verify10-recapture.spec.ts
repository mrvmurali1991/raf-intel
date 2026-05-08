/**
 * /recapture page end-to-end verification spec.
 *
 * Run with:
 *   cd frontend && BASE_URL=http://localhost:3444 \
 *     npx playwright test tests/demo/verify10-recapture.spec.ts --reporter=line
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

const SHOT_DIR = path.resolve(__dirname, "../../demo-shots/iter3-07-recapture");

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

test.describe("/recapture verification", () => {
  test.setTimeout(120000);

  test("verify recapture page end-to-end", async ({ page, request }) => {
    ensureDir(SHOT_DIR);

    const consoleErrors: string[] = [];
    const pageErrors: string[] = [];
    const failedRequests: FailedRequest[] = [];
    const recaptureCalls: { url: string; status: number; method: string }[] = [];

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
      if (u.includes("/api/recapture") || u.includes("/api/cfo") || u.includes("/api/bonus")) {
        recaptureCalls.push({ url: u, status: s, method: resp.request().method() });
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
    await page.goto(`${BASE_URL}/recapture`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(8000);

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

    // Try to capture each major section by scrolling and screenshotting
    const sections = [
      { name: "gaps", regex: /Recapture|Care Gaps|Coding Gaps|Total Gaps/i, file: "03-gaps.png" },
      { name: "velocity", regex: /Velocity|Closure Rate|Recapture Velocity/i, file: "04-velocity.png" },
      { name: "cfo", regex: /CFO|Executive Summary|Revenue Forecast/i, file: "05-cfo.png" },
      { name: "bonus", regex: /Bonus|Leaderboard|Coder Earnings/i, file: "06-bonus.png" },
      { name: "decay", regex: /Decay|Time Decay|Aging/i, file: "07-decay.png" },
    ];

    const sectionFound: Record<string, boolean> = {};
    for (const s of sections) {
      const loc = page.getByText(s.regex).first();
      try {
        const cnt = await loc.count();
        sectionFound[s.name] = cnt > 0;
        if (cnt > 0) {
          await loc.scrollIntoViewIfNeeded({ timeout: 5000 }).catch(() => null);
          await page.waitForTimeout(400);
          const box = await loc.boundingBox().catch(() => null);
          if (box) {
            await page.screenshot({
              path: path.join(SHOT_DIR, s.file),
              clip: {
                x: 0,
                y: Math.max(0, box.y - 40),
                width: 1440,
                height: 600,
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

    // Spinner check — main spinners should not be present after 8s
    const spinnerCount = await page.locator('[class*="animate-spin"]').count();
    console.log("[spinners] count:", spinnerCount);

    // ---------- Mobile ----------
    await page.setViewportSize({ width: 414, height: 896 });
    await page.goto(`${BASE_URL}/recapture`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(6000);

    await page.screenshot({
      path: path.join(SHOT_DIR, "08-mobile-top.png"),
      fullPage: false,
    });
    await page.screenshot({
      path: path.join(SHOT_DIR, "09-mobile-fullpage.png"),
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
    console.log("Recapture API calls:", recaptureCalls.length);
    recaptureCalls.slice(0, 30).forEach((r, i) =>
      console.log(`  [RC ${i}] ${r.method} ${r.status} ${r.url}`)
    );
    console.log("Sections found:", JSON.stringify(sectionFound));
    console.log("Mobile overflow px:", horizOverflow.overflow);
    console.log("===========================");

    expect(page.url()).toContain("/recapture");
  });
});
