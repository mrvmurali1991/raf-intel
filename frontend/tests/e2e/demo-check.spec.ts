import { test } from "@playwright/test";
test.use({ baseURL: "http://localhost:3001" });
test("demo 404s", async ({ page }) => {
  page.on("response", (r) => {
    if (r.status() === 404 && r.url().includes(":8500")) {
      console.log(`404: ${r.request().method()} ${r.url().replace(/.*:8500/, "")}`);
    }
  });
  await page.goto("/login");
  await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 30_000 });
  await page.fill('input[type="email"]', "admin@raf.health");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button[type="submit"]');
  await page.waitForResponse((r) => r.url().includes("/api/auth/login") && r.status() === 200);
  await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 30_000 });
  await page.evaluate(() => localStorage.setItem("raf_onboarding_complete", "true"));
  await page.waitForTimeout(1000);
  await page.locator('a[href="/demo"]').last().click();
  await page.waitForTimeout(5000);
});
