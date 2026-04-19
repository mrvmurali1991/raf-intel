import { test, expect } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

test.use({ baseURL: "http://localhost:3000" });

const OUT_DIR = "test-results/raf-central";

test.beforeAll(() => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
});

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 30_000 });
  await page.fill('input[type="email"]', "admin@raf.health");
  await page.fill('input[type="password"]', "Admin@123");
  await page.click('button[type="submit"]');
  await page.waitForResponse((r) => r.url().includes("/api/auth/login") && r.status() === 200);
  await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 30_000 });
  await page.evaluate(() => localStorage.setItem("raf_onboarding_complete", "true"));
}

test("RAF Central tab — desktop + mobile screenshots", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });

  // Desktop width
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);

  await page.goto("/patients/1?tab=rafcentral", { waitUntil: "domcontentloaded" });
  // Some background polling keeps networkidle from firing — use a fixed settle.
  await page.waitForTimeout(4000);

  await page.screenshot({
    path: path.join(OUT_DIR, "01-desktop-rafcentral.png"),
    fullPage: true,
  });

  // Expand the three default-collapsed sections by clicking their headers
  for (const label of ["HCC Recapture", "Audit Readiness", "Financial Impact"]) {
    const btn = page.getByRole("button", { name: new RegExp(`^${label}`) }).first();
    if (await btn.isVisible().catch(() => false)) {
      await btn.click().catch(() => {});
    }
  }
  await page.waitForTimeout(800);
  await page.screenshot({
    path: path.join(OUT_DIR, "02-desktop-rafcentral-expanded.png"),
    fullPage: true,
  });

  // Open ExplainPanel via "Why?" button on first suspect card
  const whyBtn = page.getByRole("button", { name: /Why\?/i }).first();
  if (await whyBtn.isVisible().catch(() => false)) {
    await whyBtn.click().catch(() => {});
    await page.waitForTimeout(1500);
    await page.screenshot({
      path: path.join(OUT_DIR, "05-desktop-explain-panel.png"),
      fullPage: false,
    });
    await page.keyboard.press("Escape").catch(() => {});
    await page.waitForTimeout(400);
  }

  // Dismiss any stray modal/overlay before mobile
  await page.keyboard.press("Escape").catch(() => {});
  await page.waitForTimeout(300);

  // Mobile width — navigate fresh, press Escape to close any overlay
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/patients/1?tab=rafcentral", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2500);
  await page.keyboard.press("Escape").catch(() => {});
  await page.waitForTimeout(500);
  await page.screenshot({
    path: path.join(OUT_DIR, "03-mobile-rafcentral.png"),
    fullPage: true,
  });

  // Narrow viewport (640px) — still below lg (1024), mobile drawer model
  await page.setViewportSize({ width: 640, height: 900 });
  await page.goto("/patients/1?tab=rafcentral", { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2500);
  await page.keyboard.press("Escape").catch(() => {});
  await page.waitForTimeout(500);
  await page.screenshot({
    path: path.join(OUT_DIR, "04-narrow-metrics-strip.png"),
    fullPage: true,
  });

  // Verify the RAF Intelligence header exists (not strictly visible — may be clipped by viewport)
  const header = page.getByText(/RAF INTELLIGENCE/i).first();
  expect(await header.count()).toBeGreaterThan(0);

  if (errors.length > 0) {
    console.log("=== Console errors ===");
    errors.slice(0, 10).forEach((e) => console.log("  ", e.substring(0, 300)));
  } else {
    console.log("=== No console errors ===");
  }
});
