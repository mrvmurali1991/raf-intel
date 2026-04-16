import { chromium } from "playwright";
import * as path from "path";

const RAF_URL = "https://raf.comercioit.com";
const DIR = path.join(__dirname, "demo-screenshots");

(async () => {
  const browser = await chromium.launch({ headless: false });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, ignoreHTTPSErrors: true });
  const page = await ctx.newPage();

  await page.goto(`${RAF_URL}/login`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3000);
  await page.locator('input[type="email"]').first().fill("admin@raf.health");
  await page.locator('input[type="password"]').first().fill("Admin@123");
  await page.locator('button[type="submit"]').first().click();
  await page.waitForTimeout(6000);
  try {
    const skip = page.locator('button:has-text("Skip")');
    if (await skip.isVisible({ timeout: 3000 })) { await skip.click(); await page.waitForTimeout(3000); }
  } catch {}

  await page.goto(`${RAF_URL}/suspects`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(6000);
  await page.screenshot({ path: path.join(DIR, "18_raf_suspects.png") });
  console.log("📸 18_raf_suspects.png");
  await page.evaluate(() => window.scrollBy(0, 400));
  await page.waitForTimeout(1500);
  await page.screenshot({ path: path.join(DIR, "18b_raf_suspects_scrolled.png") });
  console.log("📸 18b_raf_suspects_scrolled.png");

  await browser.close();
})();
