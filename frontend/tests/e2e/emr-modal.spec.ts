import { test, expect } from "@playwright/test";

test.use({ baseURL: "http://localhost:3001" });

test("emr vendor cards show names", async ({ page }) => {
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

  // Go to EMR Config
  await page.locator('a[href="/emr-config"]').last().click();
  await page.waitForURL("**/emr-config", { timeout: 10_000 });
  await page.waitForTimeout(2000);

  // Click "Add EMR Connection"
  await page.getByText("Add EMR Connection").click();
  await page.waitForTimeout(2000);

  // Screenshot the modal
  await page.screenshot({ path: "test-results/emr-vendor-modal.png", fullPage: true });

  // Log vendor card text
  const modalText = await page.locator("body").innerText();
  const vendorSection = modalText.substring(modalText.indexOf("Select Vendor"), modalText.indexOf("Select Vendor") + 600);
  console.log("=== Vendor Section ===");
  console.log(vendorSection);
});
