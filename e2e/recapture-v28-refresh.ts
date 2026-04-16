/**
 * Re-capture V28 HCC screenshots after suspect HCC fix
 * (E66.01 -> HCC 48, F32.1 -> HCC 155)
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
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    ignoreHTTPSErrors: true,
  });
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
    if (await skip.isVisible({ timeout: 3000 })) {
      await skip.click();
      await page.waitForTimeout(3000);
    }
  } catch {}

  const captures = [
    { path: "/", file: "12_raf_dashboard.png" },
    { path: "/patients/860", file: "14_raf_patient_lisa_suspects.png" },
    { path: "/patients/855", file: "15_raf_patient_rodriguez_suspects.png" },
    { path: "/suspects", file: "18_raf_suspects.png" },
    { path: "/recapture", file: "19_raf_recapture_gaps.png" },
  ];

  for (const c of captures) {
    try {
      await page.goto(`${RAF_URL}${c.path}`, {
        waitUntil: "domcontentloaded",
        timeout: 20000,
      });
      await page.waitForTimeout(7000);
      // If patient detail, try clicking Suspects tab
      if (c.path.startsWith("/patients/")) {
        try {
          const suspectsTab = page.locator(
            'button:has-text("Suspects"), a:has-text("Suspects"), [role="tab"]:has-text("Suspects")'
          ).first();
          if (await suspectsTab.isVisible({ timeout: 2000 })) {
            await suspectsTab.click();
            await page.waitForTimeout(3000);
          }
        } catch {}
      }
      await shot(page, c.file);
    } catch (e) {
      console.log(`⚠️ ${c.path}: ${e}`);
    }
  }

  await browser.close();
  console.log("✅ Done");
})();
