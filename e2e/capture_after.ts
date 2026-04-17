/**
 * Capture just a fresh AFTER screenshot of RAF patient 855
 * and update the demo after.json.
 */
import { chromium } from "playwright";
import * as fs from "fs";
import * as path from "path";

const RAF_UI = "https://raf.comercioit.com";
const RAF_API = "https://raf-api.comercioit.com";
const RAF_USER = "admin@raf.health";
const RAF_PASS = "Admin@123";
const PID = 855;
const DIR = "/Users/murali/Desktop/raf-intelligence/e2e/inbox-demo-screenshots";

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    ignoreHTTPSErrors: true,
  });
  const page = await ctx.newPage();

  await page.goto(`${RAF_UI}/login`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2000);
  await page.locator('input[type="email"]').first().fill(RAF_USER);
  await page.locator('input[type="password"]').first().fill(RAF_PASS);
  await page.locator('button[type="submit"]').first().click();
  await page.waitForTimeout(5000);
  try {
    const skip = page.locator('button:has-text("Skip")').first();
    if (await skip.isVisible({ timeout: 2000 })) {
      await skip.click();
      await page.waitForTimeout(2000);
    }
  } catch {}

  await page.goto(`${RAF_UI}/patients/${PID}`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(6000);

  await page.screenshot({
    path: path.join(DIR, "11_raf_after_patient_detail.png"),
    fullPage: true,
  });

  // Pull current score from API
  const login = await fetch(`${RAF_API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: RAF_USER, password: RAF_PASS }),
  }).then((r) => r.json());
  const token = login.access_token;
  const after = await fetch(`${RAF_API}/api/raf/scores/${PID}`, {
    headers: { Authorization: `Bearer ${token}` },
  }).then((r) => r.json());

  fs.writeFileSync(path.join(DIR, "after.json"), JSON.stringify(after, null, 2));
  console.log("AFTER:", after.raf_score, "HCCs:", after.hcc_count);
  console.log("screenshot saved");
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
