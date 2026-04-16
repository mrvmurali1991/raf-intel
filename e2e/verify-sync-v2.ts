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

const FHIR_CLIENT_ID = "AGl5Lx0OhB7oTEfiR2W1TZjAlb7BZSOGeE8jf95v88E";
const FHIR_CLIENT_SECRET = "WOkNYQJHMz0dnrHOUmJqKjQ4NJGTfCFaYQf_bCPa4H_P72SuF_A4LBM_kc3CVzuGGY4wBE6m2a8-WnzDfPHf1Q";

const SS_DIR = path.join(__dirname, "screenshots-final");
fs.mkdirSync(SS_DIR, { recursive: true });

let idx = 0;
function ss(name: string) {
  idx++;
  return path.join(SS_DIR, `${String(idx).padStart(2, "0")}_${name}.png`);
}

async function getFhirToken(): Promise<string> {
  const resp = await fetch(`${OPENEMR_URL}/oauth2/default/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "password",
      client_id: FHIR_CLIENT_ID,
      client_secret: FHIR_CLIENT_SECRET,
      username: OPENEMR_USER,
      password: OPENEMR_PASS,
      user_role: "users",
      scope: "openid api:fhir user/Patient.read",
    }),
  });
  const data = await resp.json();
  return data.access_token || "";
}

(async () => {
  const browser = await chromium.launch({ headless: true });

  // ── Step 1: OpenEMR Login ──
  console.log("Step 1: OpenEMR login");
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

  // Search for Eleanor
  try {
    const searchInput = emrPage.locator('#anySearchBox, input[name="patient_search"]');
    if (await searchInput.count() > 0) {
      await searchInput.first().fill("Whitfield");
      await emrPage.waitForTimeout(2000);
      await emrPage.screenshot({ path: ss("openemr_search_whitfield"), fullPage: true });
    }
  } catch {
    await emrPage.screenshot({ path: ss("openemr_dashboard_alt"), fullPage: true });
  }
  await emrPage.close();

  // ── Step 2: FHIR API proof (authenticated) ──
  console.log("Step 2: FHIR API verification (authenticated)");
  const fhirToken = await getFhirToken();
  console.log("  FHIR token:", fhirToken ? "obtained" : "FAILED");

  if (fhirToken) {
    const fhirResp = await fetch(
      `${OPENEMR_URL}/apis/default/fhir/Patient/a18cd1dc-9054-4be1-8b1d-36d3cc16aa83`,
      { headers: { Authorization: `Bearer ${fhirToken}` } }
    );
    const fhirData = await fhirResp.json();
    fs.writeFileSync(path.join(SS_DIR, "fhir_patient_raw.json"), JSON.stringify(fhirData, null, 2));

    // Render JSON in browser for screenshot
    const jsonPage = await browser.newPage({ viewport: { width: 1400, height: 900 } });
    await jsonPage.setContent(`
      <html><body style="background:#1e1e1e;color:#d4d4d4;font-family:monospace;padding:20px;">
        <h2 style="color:#4ec9b0;">FHIR Patient Resource — Eleanor Grace Whitfield</h2>
        <p style="color:#9cdcfe;">GET ${OPENEMR_URL}/apis/default/fhir/Patient/a18cd1dc-9054-4be1-8b1d-36d3cc16aa83</p>
        <pre style="font-size:13px;line-height:1.4;">${JSON.stringify(fhirData, null, 2).replace(/</g, "&lt;")}</pre>
      </body></html>
    `);
    await jsonPage.screenshot({ path: ss("fhir_patient_resource"), fullPage: true });
    await jsonPage.close();
  } else {
    // Fallback: empty screenshot
    const p = await browser.newPage({ viewport: { width: 1400, height: 900 } });
    await p.setContent("<h1>FHIR token acquisition failed</h1>");
    await p.screenshot({ path: ss("fhir_patient_resource"), fullPage: true });
    await p.close();
  }

  // ── Step 3: RAF Intelligence Login ──
  console.log("Step 3: RAF Intelligence login");
  const rafPage = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  await rafPage.goto(RAF_UI, { waitUntil: "domcontentloaded", timeout: 60000 });
  await rafPage.waitForTimeout(3000);
  await rafPage.screenshot({ path: ss("raf_login_page"), fullPage: true });

  // Fill login
  try {
    await rafPage.fill('input[type="email"], input[name="email"], input[placeholder*="mail"]', RAF_USER, { timeout: 5000 });
    await rafPage.fill('input[type="password"], input[name="password"]', RAF_PASS, { timeout: 5000 });
    await rafPage.screenshot({ path: ss("raf_login_filled"), fullPage: true });
    await rafPage.click('button[type="submit"]');
    await rafPage.waitForTimeout(5000);
  } catch {
    console.log("  Login form issue");
  }
  await rafPage.screenshot({ path: ss("raf_after_login"), fullPage: true });

  // Dismiss any onboarding modal
  console.log("  Dismissing onboarding modal if present...");
  try {
    // Try common close/dismiss patterns
    const closeBtn = rafPage.locator('button:has-text("Skip"), button:has-text("Close"), button:has-text("Dismiss"), button:has-text("Later"), button[aria-label="Close"], .modal-close, [data-dismiss="modal"]');
    if (await closeBtn.count() > 0) {
      await closeBtn.first().click();
      await rafPage.waitForTimeout(2000);
      console.log("  Modal dismissed");
    }
    // Also try clicking outside modal / pressing Escape
    await rafPage.keyboard.press("Escape");
    await rafPage.waitForTimeout(1000);
  } catch {
    console.log("  No modal found");
  }
  await rafPage.screenshot({ path: ss("raf_dashboard"), fullPage: true });

  // ── Step 4: Patient list ──
  console.log("Step 4: Patient list");
  await rafPage.goto(`${RAF_UI}/patients`, { waitUntil: "domcontentloaded", timeout: 60000 });
  await rafPage.waitForTimeout(5000);

  // Dismiss modal again if it reappears
  try {
    await rafPage.keyboard.press("Escape");
    await rafPage.waitForTimeout(1000);
    const closeBtn = rafPage.locator('button:has-text("Skip"), button:has-text("Close"), button:has-text("Later"), button[aria-label="Close"]');
    if (await closeBtn.count() > 0) {
      await closeBtn.first().click();
      await rafPage.waitForTimeout(1000);
    }
  } catch {}

  await rafPage.screenshot({ path: ss("raf_patients_list"), fullPage: true });

  // Search
  try {
    const searchBox = rafPage.locator('input[placeholder*="earch"], input[type="search"]');
    if (await searchBox.count() > 0) {
      await searchBox.first().fill("Whitfield");
      await rafPage.waitForTimeout(3000);
      await rafPage.screenshot({ path: ss("raf_search_whitfield"), fullPage: true });
    } else {
      await rafPage.screenshot({ path: ss("raf_patients_nosearch"), fullPage: true });
    }
  } catch {
    await rafPage.screenshot({ path: ss("raf_patients_fallback"), fullPage: true });
  }

  // ── Step 5: Patient detail ──
  console.log("Step 5: Patient detail");
  await rafPage.goto(`${RAF_UI}/patients/1262`, { waitUntil: "domcontentloaded", timeout: 60000 });
  await rafPage.waitForTimeout(5000);

  // Dismiss modal
  try {
    await rafPage.keyboard.press("Escape");
    await rafPage.waitForTimeout(1000);
    const closeBtn = rafPage.locator('button:has-text("Skip"), button:has-text("Close"), button:has-text("Later"), button[aria-label="Close"]');
    if (await closeBtn.count() > 0) {
      await closeBtn.first().click();
      await rafPage.waitForTimeout(1000);
    }
  } catch {}

  await rafPage.screenshot({ path: ss("raf_patient_detail"), fullPage: true });

  // Scroll down for more data
  await rafPage.evaluate(() => window.scrollBy(0, 600));
  await rafPage.waitForTimeout(1000);
  await rafPage.screenshot({ path: ss("raf_patient_detail_scrolled"), fullPage: true });

  // ── Step 6: API verification ──
  console.log("Step 6: API data verification");
  const loginResp = await (await fetch(`${RAF_API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: RAF_USER, password: RAF_PASS }),
  })).json();
  const token = loginResp.access_token || loginResp.token;
  console.log("  RAF token:", token ? "yes" : "no");

  if (token) {
    const patResp = await (await fetch(`${RAF_API}/api/patients/1262`, {
      headers: { Authorization: `Bearer ${token}` },
    })).json();
    fs.writeFileSync(path.join(SS_DIR, "api_patient.json"), JSON.stringify(patResp, null, 2));

    // Render API response as screenshot
    const apiPage = await browser.newPage({ viewport: { width: 1400, height: 900 } });
    await apiPage.setContent(`
      <html><body style="background:#1e1e1e;color:#d4d4d4;font-family:monospace;padding:20px;">
        <h2 style="color:#4ec9b0;">RAF Intelligence API — Patient #1262</h2>
        <p style="color:#9cdcfe;">GET ${RAF_API}/api/patients/1262</p>
        <pre style="font-size:13px;line-height:1.4;">${JSON.stringify(patResp, null, 2).replace(/</g, "&lt;")}</pre>
      </body></html>
    `);
    await apiPage.screenshot({ path: ss("raf_api_response"), fullPage: true });
    await apiPage.close();
  }

  await rafPage.close();
  await browser.close();
  console.log("\nDone! Screenshots in:", SS_DIR);
})();
