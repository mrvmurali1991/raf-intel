/**
 * RAF Intelligence — Final Demo Screenshots
 * Captures all pages of OpenEMR and RAF Intelligence for client demo
 */
import { chromium } from "playwright";
import * as fs from "fs";
import * as path from "path";

const OPENEMR_URL = "https://openemr.ehrservicedesk.com";
const RAF_URL = "https://raf.comercioit.com";
const DIR = path.join(__dirname, "demo-screenshots");
let step = 0;

async function shot(page: any, name: string) {
  step++;
  const f = `${String(step).padStart(2, "0")}_${name}.png`;
  await page.screenshot({ path: path.join(DIR, f) });
  console.log(`  📸 ${f}`);
}

async function shotFull(page: any, name: string) {
  step++;
  const f = `${String(step).padStart(2, "0")}_${name}.png`;
  await page.screenshot({ path: path.join(DIR, f), fullPage: true });
  console.log(`  📸 ${f} (full)`);
}

(async () => {
  // Clean up old screenshots
  fs.mkdirSync(DIR, { recursive: true });
  for (const f of fs.readdirSync(DIR)) {
    if (f.endsWith(".png")) fs.unlinkSync(path.join(DIR, f));
  }

  const browser = await chromium.launch({ headless: false });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, ignoreHTTPSErrors: true });
  const page = await ctx.newPage();

  // ═══════════════════════════════════════════════════════════
  // SECTION 1: OpenEMR — Login
  // ═══════════════════════════════════════════════════════════
  console.log("\n🏥 SECTION 1: OpenEMR — Login\n");

  await page.goto(`${OPENEMR_URL}/interface/login/login.php?site=default`);
  await page.waitForTimeout(3000);
  await shot(page, "openemr_login_page");

  await page.locator("#authUser").fill("admin");
  await page.locator("#clearPass").fill("Healthcare@Admin2026");
  await shot(page, "openemr_login_filled");

  await page.locator("#login-button").click();
  await page.waitForTimeout(4000);
  await shot(page, "openemr_dashboard");

  // ═══════════════════════════════════════════════════════════
  // SECTION 2: OpenEMR — Create Patient
  // ═══════════════════════════════════════════════════════════
  console.log("\n👤 SECTION 2: OpenEMR — Create Patient\n");

  await page.goto(`${OPENEMR_URL}/interface/new/new_comprehensive.php`);
  await page.waitForTimeout(3000);
  await shot(page, "openemr_new_patient_form");

  // Fill demographics
  await page.locator("#form_fname").fill("Maria");
  await page.locator("#form_mname").fill("Elena");
  await page.locator("#form_lname").fill("Rodriguez");
  await page.evaluate(() => {
    const d = document.getElementById("form_DOB") as HTMLInputElement;
    if (d) { d.value = "1958-03-15"; d.dispatchEvent(new Event("change")); }
  });
  await page.locator("#form_sex").selectOption("Female");
  await page.locator("#form_ss").fill("999-88-7777");
  await page.locator("#form_pubpid").fill("RAF-DEMO-2026");
  await shot(page, "openemr_patient_demographics");

  // Expand Contact & fill address
  await page.locator('button:has-text("Contact")').click();
  await page.waitForTimeout(500);
  await page.locator("#form_street").fill("4521 Palm Beach Blvd");
  await page.locator("#form_city").fill("Miami");
  await page.locator("#form_postal_code").fill("33137");
  await page.locator("#form_phone_home").fill("(305) 555-0142");
  await page.locator("#form_email").fill("maria.rodriguez@example.com");
  try { await page.locator("#form_state").selectOption("FL"); } catch {}
  await shot(page, "openemr_patient_contact");

  // Submit
  await page.locator("#create").click();
  await page.waitForTimeout(5000);
  // Handle confirm dialog
  try {
    const c = page.locator('button:has-text("Confirm"), button:has-text("OK")').first();
    if (await c.isVisible({ timeout: 3000 })) { await c.click(); await page.waitForTimeout(3000); }
  } catch {}
  await shot(page, "openemr_patient_created");

  // ═══════════════════════════════════════════════════════════
  // SECTION 3: OpenEMR — View Existing Patient with Data
  // ═══════════════════════════════════════════════════════════
  console.log("\n📋 SECTION 3: OpenEMR — Existing Patient Data\n");

  // Search for a patient with conditions
  const searchBar = page.locator('input[placeholder="Search by any demographics"]');
  if (await searchBar.isVisible({ timeout: 3000 })) {
    await searchBar.fill("Abeyta");
    await searchBar.press("Enter");
    await page.waitForTimeout(3000);
    await shot(page, "openemr_search_abeyta");

    try {
      await page.locator('td:has-text("Abeyta"), a:has-text("Abeyta")').first().click();
      await page.waitForTimeout(3000);
    } catch {}
  }

  // Patient summary
  await page.goto(`${OPENEMR_URL}/interface/patient_file/summary/demographics.php`);
  await page.waitForTimeout(3000);
  await shotFull(page, "openemr_patient_summary_abeyta");

  // ═══════════════════════════════════════════════════════════
  // SECTION 4: RAF Intelligence — Login
  // ═══════════════════════════════════════════════════════════
  console.log("\n🧠 SECTION 4: RAF Intelligence — Login\n");

  await page.goto(`${RAF_URL}/login`);
  await page.waitForTimeout(4000);
  await shot(page, "raf_login_page");

  await page.locator('input[type="email"]').first().fill("admin@raf.health");
  await page.locator('input[type="password"]').first().fill("Admin@123");
  await shot(page, "raf_login_filled");

  await page.locator('button[type="submit"]').first().click();
  await page.waitForTimeout(8000);

  // Skip setup wizard
  try {
    const skip = page.locator('button:has-text("Skip")');
    if (await skip.isVisible({ timeout: 5000 })) {
      await skip.click();
      await page.waitForTimeout(5000);
      console.log("  ✅ Skipped setup wizard");
    }
  } catch {}

  await shot(page, "raf_after_login");

  // ═══════════════════════════════════════════════════════════
  // SECTION 5: RAF — Dashboard
  // ═══════════════════════════════════════════════════════════
  console.log("\n📊 SECTION 5: RAF Dashboard\n");

  await page.goto(`${RAF_URL}/dashboard`);
  await page.waitForTimeout(6000);
  await shot(page, "raf_dashboard");
  await page.evaluate(() => window.scrollBy(0, 500));
  await page.waitForTimeout(1000);
  await shot(page, "raf_dashboard_scrolled");

  // ═══════════════════════════════════════════════════════════
  // SECTION 6: RAF — Patient Population
  // ═══════════════════════════════════════════════════════════
  console.log("\n👥 SECTION 6: Patient Population\n");

  await page.goto(`${RAF_URL}/patients`);
  await page.waitForTimeout(6000);
  await shot(page, "raf_patients_list");

  // ═══════════════════════════════════════════════════════════
  // SECTION 7: RAF — Patient Detail (High RAF)
  // ═══════════════════════════════════════════════════════════
  console.log("\n🔍 SECTION 7: Patient Detail\n");

  // Click on a patient with RAF score
  try {
    const abeytaRow = page.locator('tr:has-text("ABEYTA"), td:has-text("ABEYTA")').first();
    if (await abeytaRow.isVisible({ timeout: 5000 })) {
      await abeytaRow.click();
      await page.waitForTimeout(6000);
      await shot(page, "raf_patient_detail_abeyta");

      await page.evaluate(() => window.scrollBy(0, 500));
      await page.waitForTimeout(1000);
      await shot(page, "raf_patient_conditions");

      await page.evaluate(() => window.scrollBy(0, 500));
      await page.waitForTimeout(1000);
      await shot(page, "raf_patient_hcc_details");
    }
  } catch (e) {
    console.log(`  ⚠️ Patient detail: ${e}`);
  }

  // ═══════════════════════════════════════════════════════════
  // SECTION 8: RAF — Search Rodriguez
  // ═══════════════════════════════════════════════════════════
  console.log("\n🔎 SECTION 8: Search Rodriguez\n");

  await page.goto(`${RAF_URL}/patients`);
  await page.waitForTimeout(6000);
  try {
    const search = page.locator('input[placeholder*="earch"], input[type="search"]').first();
    if (await search.isVisible({ timeout: 5000 })) {
      await search.fill("Rodriguez");
      await page.waitForTimeout(3000);
      await shot(page, "raf_search_rodriguez");
    }
  } catch {}

  // ═══════════════════════════════════════════════════════════
  // SECTION 9: RAF — Clinical Analysis
  // ═══════════════════════════════════════════════════════════
  console.log("\n🤖 SECTION 9: Clinical Analysis\n");

  await page.goto(`${RAF_URL}/clinical-analysis`);
  await page.waitForTimeout(6000);
  await shot(page, "raf_clinical_analysis");

  // ═══════════════════════════════════════════════════════════
  // SECTION 10: RAF — Documents
  // ═══════════════════════════════════════════════════════════
  console.log("\n📄 SECTION 10: Documents\n");

  await page.goto(`${RAF_URL}/documents`);
  await page.waitForTimeout(6000);
  await shot(page, "raf_documents");

  // ═══════════════════════════════════════════════════════════
  // SECTION 11: RAF — Suspects
  // ═══════════════════════════════════════════════════════════
  console.log("\n🔍 SECTION 11: Suspects\n");

  await page.goto(`${RAF_URL}/suspects`);
  await page.waitForTimeout(6000);
  await shot(page, "raf_suspects");

  // ═══════════════════════════════════════════════════════════
  // SECTION 12: RAF — Recapture Gaps
  // ═══════════════════════════════════════════════════════════
  console.log("\n📝 SECTION 12: Recapture Gaps\n");

  await page.goto(`${RAF_URL}/recapture-gaps`);
  await page.waitForTimeout(6000);
  await shot(page, "raf_recapture_gaps");

  // ═══════════════════════════════════════════════════════════
  // SECTION 13: RAF — Prospective
  // ═══════════════════════════════════════════════════════════
  console.log("\n🔮 SECTION 13: Prospective\n");

  await page.goto(`${RAF_URL}/prospective`);
  await page.waitForTimeout(6000);
  await shot(page, "raf_prospective");

  // ═══════════════════════════════════════════════════════════
  // SECTION 14: RAF — Review Queue
  // ═══════════════════════════════════════════════════════════
  console.log("\n📋 SECTION 14: Review Queue\n");

  await page.goto(`${RAF_URL}/review-queue`);
  await page.waitForTimeout(6000);
  await shot(page, "raf_review_queue");

  // ═══════════════════════════════════════════════════════════
  // SECTION 15: RAF — HCC Crosswalk
  // ═══════════════════════════════════════════════════════════
  console.log("\n🔄 SECTION 15: HCC Crosswalk\n");

  await page.goto(`${RAF_URL}/hcc-crosswalk`);
  await page.waitForTimeout(6000);
  await shot(page, "raf_hcc_crosswalk");

  // ═══════════════════════════════════════════════════════════
  // SECTION 16: RAF — Claims
  // ═══════════════════════════════════════════════════════════
  console.log("\n💰 SECTION 16: Claims\n");

  await page.goto(`${RAF_URL}/claims`);
  await page.waitForTimeout(6000);
  await shot(page, "raf_claims");

  // ═══════════════════════════════════════════════════════════
  // SECTION 17: RAF — Pipeline Demo
  // ═══════════════════════════════════════════════════════════
  console.log("\n⚡ SECTION 17: Pipeline Demo\n");

  await page.goto(`${RAF_URL}/pipeline-demo`);
  await page.waitForTimeout(6000);
  await shot(page, "raf_pipeline_demo");

  // ═══════════════════════════════════════════════════════════
  // SECTION 18: RAF — EMR Connected
  // ═══════════════════════════════════════════════════════════
  console.log("\n🔗 SECTION 18: EMR Connected\n");

  await page.goto(`${RAF_URL}/emr-config`);
  await page.waitForTimeout(6000);
  await shot(page, "raf_emr_connected");

  // ═══════════════════════════════════════════════════════════
  // SECTION 19: RAF — Batch Analysis
  // ═══════════════════════════════════════════════════════════
  console.log("\n📊 SECTION 19: Batch Analysis\n");

  await page.goto(`${RAF_URL}/batch-analysis`);
  await page.waitForTimeout(6000);
  await shot(page, "raf_batch_analysis");

  // ═══════════════════════════════════════════════════════════
  // DONE
  // ═══════════════════════════════════════════════════════════
  console.log("\n" + "═".repeat(50));
  console.log(`  📸 Total: ${step} screenshots`);
  console.log(`  📁 Location: e2e/demo-screenshots/`);
  console.log("═".repeat(50) + "\n");

  await browser.close();
})();
