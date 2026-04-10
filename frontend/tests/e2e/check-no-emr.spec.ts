import { test } from "@playwright/test";

test.use({ baseURL: "http://localhost:3001" });

test("pages show empty when no EMR connected", async ({ page }) => {
  // Login
  await page.goto("/login");
  await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 30_000 });
  await page.fill('input[type="email"]', "admin@raf.health");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button[type="submit"]');
  await page.waitForResponse((r) => r.url().includes("/api/auth/login") && r.status() === 200);
  await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 30_000 });
  await page.evaluate(() => localStorage.setItem("raf_onboarding_complete", "true"));
  await page.waitForTimeout(2000);

  // Check Dashboard
  await page.screenshot({ path: "test-results/no-emr-dashboard.png", fullPage: true });
  const dashText = await page.locator("body").innerText();
  console.log("=== Dashboard ===");
  console.log(dashText.substring(0, 800));

  // Check Patients page
  await page.locator('a[href="/patients"]').last().click();
  await page.waitForURL("**/patients", { timeout: 10_000 });
  await page.waitForTimeout(2000);
  await page.screenshot({ path: "test-results/no-emr-patients.png", fullPage: true });
  const patText = await page.locator("body").innerText();
  console.log("\n=== Patients ===");
  console.log(patText.substring(0, 800));

  // Check Prospective page
  await page.locator('a[href="/prospective"]').last().click();
  await page.waitForURL("**/prospective", { timeout: 10_000 });
  await page.waitForTimeout(2000);
  await page.screenshot({ path: "test-results/no-emr-prospective.png", fullPage: true });
  const prosText = await page.locator("body").innerText();
  console.log("\n=== Prospective ===");
  console.log(prosText.substring(0, 800));
});
