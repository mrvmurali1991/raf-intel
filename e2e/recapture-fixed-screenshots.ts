/**
 * Re-capture 404 screenshots with correct routes
 */
import { chromium } from "playwright";
import * as path from "path";

const RAF_URL = "https://raf.comercioit.com";
const DIR = path.join(__dirname, "demo-screenshots");

async function shot(page: any, filename: string) {
  await page.screenshot({ path: path.join(DIR, filename) });
  console.log(`📸 ${filename}`);
}

(async () => {
  const browser = await chromium.launch({ headless: false });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, ignoreHTTPSErrors: true });
  const page = await ctx.newPage();

  // Login
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

  const captures = [
    { path: "/", file: "12_raf_dashboard.png", scroll: 0 },
    { path: "/", file: "13_raf_dashboard_scrolled.png", scroll: 500 },
    { path: "/analysis", file: "16_raf_clinical_analysis.png", scroll: 0 },
    { path: "/recapture", file: "19_raf_recapture_gaps.png", scroll: 0 },
    { path: "/quality", file: "21_raf_review_queue.png", scroll: 0 },
    { path: "/crosswalk", file: "22_raf_hcc_crosswalk.png", scroll: 0 },
    { path: "/demo", file: "24_raf_pipeline_demo.png", scroll: 0 },
    { path: "/batch", file: "26_raf_batch_analysis.png", scroll: 0 },
    { path: "/uploads", file: "32_raf_data_uploads.png", scroll: 0 },
    { path: "/recapture", file: "33_raf_recapture_gaps_detail.png", scroll: 500 },
  ];

  for (const c of captures) {
    try {
      await page.goto(`${RAF_URL}${c.path}`, { waitUntil: "domcontentloaded", timeout: 15000 });
      await page.waitForTimeout(5000);
      if (c.scroll) { await page.evaluate((s) => window.scrollBy(0, s), c.scroll); await page.waitForTimeout(1500); }
      await shot(page, c.file);
    } catch (e) {
      console.log(`⚠️ ${c.path}: ${e}`);
    }
  }

  await browser.close();
  console.log("✅ Done");
})();
