import { test, expect } from "@playwright/test";

test.use({ baseURL: "http://localhost:3001" });

test("enterprise onboarding flow: wizard → demo connect → dashboard", async ({ page }) => {
  // Login
  await page.goto("/login");
  await page.waitForSelector('input[type="email"]', { state: "visible", timeout: 30_000 });
  await page.fill('input[type="email"]', "admin@raf.health");
  await page.fill('input[type="password"]', "admin123");
  await page.click('button[type="submit"]');
  await page.waitForResponse((r) => r.url().includes("/api/auth/login") && r.status() === 200);
  await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 30_000 });

  // Reset onboarding to trigger wizard
  await page.evaluate(() => localStorage.removeItem("raf_onboarding_complete"));
  await page.reload();
  await page.waitForTimeout(3000);

  // Step 0: Splash screen
  await page.screenshot({ path: "test-results/onboard-step0-splash.png", fullPage: true });
  console.log("Step 0: Splash");

  // Click "Get Started"
  const getStarted = page.locator("button", { hasText: "Get Started" });
  if (await getStarted.isVisible()) {
    await getStarted.click();
    await page.waitForTimeout(500);

    // Step 1: Role selection
    await page.screenshot({ path: "test-results/onboard-step1-role.png", fullPage: true });
    console.log("Step 1: Role selection");

    // Click Continue
    const continueBtn = page.locator("button", { hasText: "Continue" });
    await continueBtn.click();
    await page.waitForTimeout(1000);

    // Step 2: EMR connection
    await page.screenshot({ path: "test-results/onboard-step2-emr.png", fullPage: true });
    console.log("Step 2: EMR vendors");

    // Click "Try Demo Mode"
    const demoCard = page.locator("text=Try Demo Mode");
    if (await demoCard.isVisible()) {
      await demoCard.click();
      await page.waitForTimeout(500);

      // Demo confirmation screen
      await page.screenshot({ path: "test-results/onboard-step2-demo-confirm.png", fullPage: true });
      console.log("Step 2b: Demo confirmation");

      // Click "Yes, Connect Demo"
      const confirmDemo = page.locator("button", { hasText: "Yes, Connect Demo" });
      await confirmDemo.click();
      await page.waitForTimeout(5000);

      // Should show success
      await page.screenshot({ path: "test-results/onboard-step2-success.png", fullPage: true });
      console.log("Step 2c: Connection success");

      // Click "See Your Data"
      const seeData = page.locator("button", { hasText: "See Your Data" });
      if (await seeData.isVisible()) {
        await seeData.click();
        await page.waitForTimeout(2000);

        // Step 3: Data preview
        await page.screenshot({ path: "test-results/onboard-step3-preview.png", fullPage: true });
        console.log("Step 3: Data preview");

        // Click Continue
        const cont3 = page.locator("button", { hasText: "Continue" });
        if (await cont3.isVisible()) {
          await cont3.click();
          await page.waitForTimeout(500);

          // Step 4: Ready
          await page.screenshot({ path: "test-results/onboard-step4-ready.png", fullPage: true });
          console.log("Step 4: Ready");

          // Click "Go to Dashboard"
          const goToDash = page.locator("button", { hasText: "Go to Dashboard" });
          await goToDash.click();
          await page.waitForTimeout(3000);

          // Final dashboard
          await page.screenshot({ path: "test-results/onboard-final-dashboard.png", fullPage: true });
          console.log("Final: Dashboard with data");
        }
      }
    }
  } else {
    console.log("Wizard not showing — capturing current state");
    await page.screenshot({ path: "test-results/onboard-no-wizard.png", fullPage: true });
  }
});
