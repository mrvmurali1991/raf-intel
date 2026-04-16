import { chromium } from "playwright";
import * as path from "path";
import * as fs from "fs";

const OPENEMR_URL = "https://openemr.ehrservicedesk.com";
const OPENEMR_USER = "admin";
const OPENEMR_PASS = "Healthcare@Admin2026";

const RAF_API = "https://raf-api.comercioit.com";
const RAF_UI = "https://raf.comercioit.com";
const RAF_USER = "admin@raf.health";
const RAF_PASS = "Admin@123";

const SS_DIR = path.join(__dirname, "screenshots-final");
fs.mkdirSync(SS_DIR, { recursive: true });

let idx = 0;
function ss(name: string) {
  idx++;
  return path.join(SS_DIR, `${String(idx).padStart(2, "0")}_${name}.png`);
}

(async () => {
  const browser = await chromium.launch({ headless: true });

  // ── Step 1: OpenEMR – show Eleanor exists ──
  console.log("Step 1: OpenEMR login and patient verification");
  const emrPage = await browser.newPage({ viewport: { width: 1400, height: 900 } });

  await emrPage.goto(`${OPENEMR_URL}/interface/login/login.php?site=default`, {
    waitUntil: "networkidle", timeout: 30000,
  });
  await emrPage.fill('input[name="authUser"]', OPENEMR_USER);
  await emrPage.fill('input[name="clearPass"]', OPENEMR_PASS);
  await emrPage.screenshot({ path: ss("openemr_login"), fullPage: true });
  await emrPage.click('button[type="submit"]');
  await emrPage.waitForLoadState("networkidle", { timeout: 30000 });
  await emrPage.waitForTimeout(3000);
  await emrPage.screenshot({ path: ss("openemr_dashboard"), fullPage: true });

  // Search for Eleanor via top patient search
  try {
    const searchInput = emrPage.locator('#anySearchBox, input[name="patient_search"], #search_globals');
    if (await searchInput.count() > 0) {
      await searchInput.first().fill("Whitfield");
      await emrPage.waitForTimeout(2000);
      await emrPage.screenshot({ path: ss("openemr_search_whitfield"), fullPage: true });
    }
  } catch {
    console.log("  Search box not found, taking dashboard screenshot instead");
    await emrPage.screenshot({ path: ss("openemr_no_search"), fullPage: true });
  }

  // ── Step 1b: FHIR API proof ──
  console.log("Step 1b: FHIR API verification");
  const apiPage = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  // Show the FHIR Patient resource directly
  await apiPage.goto(
    `${OPENEMR_URL}/apis/default/fhir/Patient/a18cd1dc-9054-4be1-8b1d-36d3cc16aa83`,
    { waitUntil: "networkidle", timeout: 30000 }
  );
  await apiPage.waitForTimeout(2000);
  await apiPage.screenshot({ path: ss("fhir_patient_resource"), fullPage: true });
  await apiPage.close();

  await emrPage.close();

  // ── Step 2: RAF Intelligence – Login ──
  console.log("Step 2: RAF Intelligence login");
  const rafPage = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  await rafPage.goto(RAF_UI, { waitUntil: "networkidle", timeout: 30000 });
  await rafPage.waitForTimeout(2000);
  await rafPage.screenshot({ path: ss("raf_login_page"), fullPage: true });

  // Fill login
  try {
    await rafPage.fill('input[type="email"], input[name="email"], input[placeholder*="mail"]', RAF_USER, { timeout: 5000 });
    await rafPage.fill('input[type="password"], input[name="password"]', RAF_PASS, { timeout: 5000 });
    await rafPage.screenshot({ path: ss("raf_login_filled"), fullPage: true });
    await rafPage.click('button[type="submit"]');
    await rafPage.waitForLoadState("networkidle", { timeout: 15000 });
    await rafPage.waitForTimeout(3000);
  } catch {
    console.log("  Login form not standard, trying alternative selectors");
  }
  await rafPage.screenshot({ path: ss("raf_dashboard"), fullPage: true });

  // ── Step 3: Navigate to patients ──
  console.log("Step 3: Patient list");
  await rafPage.goto(`${RAF_UI}/patients`, { waitUntil: "domcontentloaded", timeout: 60000 });
  await rafPage.waitForTimeout(5000);
  await rafPage.screenshot({ path: ss("raf_patients_list"), fullPage: true });

  // Search for Eleanor
  try {
    const searchBox = rafPage.locator('input[placeholder*="earch"], input[type="search"]');
    if (await searchBox.count() > 0) {
      await searchBox.first().fill("Whitfield");
      await rafPage.waitForTimeout(3000);
      await rafPage.screenshot({ path: ss("raf_search_whitfield"), fullPage: true });
    }
  } catch {
    console.log("  Search not available");
  }

  // ── Step 4: Patient detail ──
  console.log("Step 4: Patient detail page");
  await rafPage.goto(`${RAF_UI}/patients/1262`, { waitUntil: "domcontentloaded", timeout: 60000 });
  await rafPage.waitForTimeout(5000);
  await rafPage.screenshot({ path: ss("raf_patient_detail"), fullPage: true });

  // ── Step 5: API verification ──
  console.log("Step 5: API data verification");
  const apiVerifyPage = await browser.newPage({ viewport: { width: 1400, height: 900 } });

  // Get auth token
  const loginResp = await (await fetch(`${RAF_API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: RAF_USER, password: RAF_PASS }),
  })).json();
  const token = loginResp.access_token || loginResp.token;
  console.log("  Got auth token:", token ? "yes" : "no");

  if (token) {
    // Patient API
    const patResp = await (await fetch(`${RAF_API}/api/patients/1262`, {
      headers: { Authorization: `Bearer ${token}` },
    })).json();
    fs.writeFileSync(path.join(SS_DIR, "api_patient.json"), JSON.stringify(patResp, null, 2));
    console.log("  Patient API response saved");

    // EMR connections
    const connResp = await (await fetch(`${RAF_API}/api/emr/connections`, {
      headers: { Authorization: `Bearer ${token}` },
    })).json();
    fs.writeFileSync(path.join(SS_DIR, "api_connections.json"), JSON.stringify(connResp, null, 2));

    // FHIR sync status
    const syncResp = await (await fetch(`${RAF_API}/api/fhir/connections`, {
      headers: { Authorization: `Bearer ${token}` },
    })).json();
    fs.writeFileSync(path.join(SS_DIR, "api_fhir_connections.json"), JSON.stringify(syncResp, null, 2));
  }

  await apiVerifyPage.close();
  await rafPage.close();
  await browser.close();

  console.log("\nDone! Screenshots in:", SS_DIR);
})();
