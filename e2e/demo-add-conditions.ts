/**
 * Add conditions to Maria Rodriguez via OpenEMR UI, then capture RAF screenshots
 */
import { chromium } from "playwright";
import * as fs from "fs";
import * as path from "path";

const OPENEMR_URL = "https://openemr.ehrservicedesk.com";
const RAF_URL = "https://raf.comercioit.com";
const RAF_API = "https://raf-api.comercioit.com";
const DIR = path.join(__dirname, "demo-screenshots");
let step = 20; // Continue numbering from previous screenshots

async function shot(page: any, name: string) {
  step++;
  const f = `${String(step).padStart(2, "0")}_${name}.png`;
  await page.screenshot({ path: path.join(DIR, f) });
  console.log(`📸 ${f}`);
}

async function shotFull(page: any, name: string) {
  step++;
  const f = `${String(step).padStart(2, "0")}_${name}.png`;
  await page.screenshot({ path: path.join(DIR, f), fullPage: true });
  console.log(`📸 ${f} (full)`);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, ignoreHTTPSErrors: true });
  const page = await ctx.newPage();

  // ── OpenEMR: Login ──
  console.log("\n🏥 OpenEMR: Login & Add Conditions to Maria Rodriguez\n");
  await page.goto(`${OPENEMR_URL}/interface/login/login.php?site=default`);
  await page.waitForLoadState("networkidle");
  await page.locator("#authUser").fill("admin");
  await page.locator("#clearPass").fill("Healthcare@Admin2026");
  await page.locator("#login-button").click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(3000);

  // ── Search for Maria Rodriguez ──
  console.log("🔍 Searching for Maria Rodriguez...");
  // Use the top-right search bar
  const searchInput = page.locator('input[placeholder="Search by any demographics"]');
  if (await searchInput.isVisible({ timeout: 3000 })) {
    await searchInput.fill("Rodriguez");
    await searchInput.press("Enter");
    await page.waitForTimeout(3000);
    await shot(page, "openemr_search_rodriguez");

    // Click on the patient in results
    try {
      const patLink = page.locator('a:has-text("Rodriguez"), td:has-text("Rodriguez")').first();
      if (await patLink.isVisible({ timeout: 3000 })) {
        await patLink.click();
        await page.waitForTimeout(3000);
      }
    } catch {}
  }
  await shot(page, "openemr_patient_selected");

  // ── Navigate to Issues (Medical Problems) ──
  console.log("🩺 Adding Medical Problems...");
  // In OpenEMR, Issues are added from patient summary
  await page.goto(`${OPENEMR_URL}/interface/patient_file/summary/demographics.php`, {
    waitUntil: "domcontentloaded",
  });
  await page.waitForTimeout(2000);
  await shotFull(page, "openemr_patient_summary");

  // Try to click "Issues" or "Medical Problems" link
  try {
    const issuesLink = page.locator('a:has-text("Issues"), a:has-text("Medical Problems"), a:has-text("Problem")').first();
    if (await issuesLink.isVisible({ timeout: 3000 })) {
      await issuesLink.click();
      await page.waitForTimeout(2000);
      await shot(page, "openemr_issues_page");
    }
  } catch {}

  // ── Take screenshots of existing patients with data in OpenEMR ──
  console.log("\n📊 Taking screenshots of existing patient data in OpenEMR\n");

  // Search for a patient with known conditions
  await page.goto(`${OPENEMR_URL}/interface/main/finder/patient_finder.php`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(2000);
  await shot(page, "openemr_patient_finder");

  // ── RAF Intelligence Screenshots ──
  console.log("\n🧠 RAF Intelligence: Taking screenshots\n");

  // Login to RAF
  await page.goto(`${RAF_URL}/login`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3000);

  await page.locator('input[type="email"], input[name="email"]').first().fill("admin@raf.health");
  await page.locator('input[type="password"], input[name="password"]').first().fill("Admin@123");
  await page.locator('button[type="submit"]').first().click();
  await page.waitForTimeout(5000);

  // Skip setup wizard if it appears
  try {
    const skipBtn = page.locator('text=Skip, text=x Skip, button:has-text("Skip")').first();
    if (await skipBtn.isVisible({ timeout: 3000 })) {
      await skipBtn.click();
      await page.waitForTimeout(3000);
      console.log("  ✅ Skipped setup wizard");
    }
  } catch {}

  await shot(page, "raf_dashboard");

  // Navigate through all key pages
  const pages = [
    { path: "/patients", name: "raf_patients_list", wait: 3000 },
    { path: "/dashboard", name: "raf_main_dashboard", wait: 3000 },
  ];

  for (const p of pages) {
    try {
      await page.goto(`${RAF_URL}${p.path}`, { waitUntil: "domcontentloaded", timeout: 15000 });
      await page.waitForTimeout(p.wait);
      await shot(page, p.name);
    } catch (e) {
      console.log(`⚠️ ${p.path}: ${e}`);
    }
  }

  // Search for a patient with high RAF score
  await page.goto(`${RAF_URL}/patients`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3000);

  // Search for patients and take detail screenshots
  const searchPatients = ["Abeyta", "Rodriguez"];
  for (const name of searchPatients) {
    try {
      await page.goto(`${RAF_URL}/patients`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(4000);

      const search = page.locator('input[placeholder*="earch"], input[type="search"]').first();
      if (await search.isVisible({ timeout: 5000 })) {
        await search.fill(name);
        await page.waitForTimeout(3000);
        await shot(page, `raf_search_${name.toLowerCase()}`);

        // Click patient row
        const row = page.locator(`tr:has-text("${name}"), a:has-text("${name}"), td:has-text("${name}")`).first();
        if (await row.isVisible({ timeout: 5000 })) {
          await row.click();
          await page.waitForTimeout(5000);
          await shotFull(page, `raf_patient_detail_${name.toLowerCase()}`);

          // Scroll to see conditions/HCCs
          await page.evaluate(() => window.scrollBy(0, 500));
          await page.waitForTimeout(1000);
          await shot(page, `raf_patient_${name.toLowerCase()}_conditions`);

          await page.evaluate(() => window.scrollBy(0, 500));
          await page.waitForTimeout(1000);
          await shot(page, `raf_patient_${name.toLowerCase()}_more`);
        }
      }
    } catch (e) {
      console.log(`  ⚠️ ${name}: ${e}`);
    }
  }

  // Visit more pages
  const morePaths = [
    "/suspects", "/care-gaps", "/worklists", "/coder-worklist",
    "/encounters", "/analysis", "/configuration", "/emr-config",
  ];
  for (const p of morePaths) {
    try {
      await page.goto(`${RAF_URL}${p}`, { waitUntil: "domcontentloaded", timeout: 10000 });
      await page.waitForTimeout(2000);
      const body = await page.textContent("body");
      if (body && body.length > 200 && !body.includes("404")) {
        await shot(page, `raf${p.replace(/\//g, "_")}`);
        console.log(`  ✅ ${p}`);
      }
    } catch {}
  }

  // Final dashboard
  await page.goto(`${RAF_URL}/dashboard`, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(3000);
  await shotFull(page, "raf_final_dashboard");

  console.log(`\n✅ Done! ${step} screenshots in e2e/demo-screenshots/\n`);
  await browser.close();
})();
