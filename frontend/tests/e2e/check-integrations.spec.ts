import { test } from "@playwright/test";

test.use({ baseURL: "http://localhost:3001" });

test("check integrations page", async ({ page }) => {
  await page.goto("/login");
  await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 30_000 });
  await page.fill('input[type="email"]', "admin@raf.health");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button[type="submit"]');
  await page.waitForResponse((r) => r.url().includes("/api/auth/login") && r.status() === 200);
  await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 30_000 });
  await page.evaluate(() => localStorage.setItem("raf_onboarding_complete", "true"));
  await page.waitForTimeout(1000);

  await page.locator('a[href="/integrations"]').last().click();
  await page.waitForURL("**/integrations", { timeout: 10_000 });
  await page.waitForTimeout(3000);

  await page.screenshot({ path: "test-results/integrations-page.png", fullPage: true });

  const text = await page.locator("body").innerText();
  console.log("=== Page Text ===");
  console.log(text.substring(0, 2000));
});
