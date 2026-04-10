import { test, expect } from "@playwright/test";

test.use({ baseURL: "http://localhost:3001" });

test("emr-config page loads correctly", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });

  const apiCalls: string[] = [];
  page.on("response", (r) => {
    if (r.url().includes(":8500")) {
      apiCalls.push(`${r.status()} ${r.request().method()} ${r.url().replace(/.*:8500/, "")}`);
    }
  });

  // Login
  await page.goto("/login");
  await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 30_000 });
  await page.fill('input[type="email"]', "admin@raf.health");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button[type="submit"]');

  // Wait for the login API to return, then wait for redirect away from /login
  await page.waitForResponse((r) => r.url().includes("/api/auth/login") && r.status() === 200);
  // window.location.href = "/" triggers a full page load
  await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 30_000 });
  await page.evaluate(() => localStorage.setItem("raf_onboarding_complete", "true"));

  // Wait for dashboard to load
  await page.waitForTimeout(3000);
  console.log("=== After login URL ===", page.url());
  console.log("=== API calls ===");
  apiCalls.forEach((c) => console.log("  ", c));

  // Navigate to EMR Config
  await page.locator('a[href="/emr-config"]').last().click();
  await page.waitForURL("**/emr-config", { timeout: 10_000 });
  await page.waitForTimeout(3000);

  await page.screenshot({ path: "test-results/emr-config.png", fullPage: true });

  const mainText = await page.locator("#main-content").innerText();
  console.log("=== EMR Config (first 800 chars) ===");
  console.log(mainText.substring(0, 800));

  if (errors.length > 0) {
    console.log("=== Console errors ===");
    errors.forEach((e) => console.log("  ERROR:", e.substring(0, 200)));
  } else {
    console.log("=== No console errors ===");
  }

  expect(page.url()).toContain("/emr-config");
});
