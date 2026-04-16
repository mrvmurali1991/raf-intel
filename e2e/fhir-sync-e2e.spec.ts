import { test, expect, Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

const OPENEMR_URL = "https://openemr.ehrservicedesk.com";
const OPENEMR_USER = "admin";
const OPENEMR_PASS = "Healthcare@Admin2026";

const RAF_API = "https://raf-api.comercioit.com";
const RAF_UI = "https://raf.comercioit.com";
const RAF_USER = "admin@raf.health";
const RAF_PASS = "Admin@123";

const SCREENSHOT_DIR = path.join(__dirname, "screenshots");

// Test patient data — unique name to avoid conflicts
const PATIENT = {
  fname: "Eleanor",
  mname: "Grace",
  lname: "Whitfield",
  dob: "1952-07-14",
  sex: "Female",
  ssn: "555-44-3322",
  street: "742 Evergreen Terrace",
  city: "Springfield",
  state: "Illinois",
  zip: "62704",
  phone: "(555) 867-5309",
  email: "eleanor.whitfield@testpatient.com",
  race: "White",
  ethnicity: "Not Hispanic or Latino",
};

// Diagnosis codes to add
const DIAGNOSES = [
  { code: "E11.9", desc: "Type 2 diabetes mellitus without complications" },
  { code: "I10", desc: "Essential (primary) hypertension" },
  { code: "E78.5", desc: "Hyperlipidemia, unspecified" },
];

const VITALS = {
  bps: "138",
  bpd: "88",
  pulse: "78",
  respiration: "18",
  temp_f: "98.6",
  weight_lbs: "172",
  height_in: "65",
  oxygen_saturation: "97",
};

let screenshotIdx = 0;
function ssPath(name: string): string {
  screenshotIdx++;
  const padded = String(screenshotIdx).padStart(2, "0");
  return path.join(SCREENSHOT_DIR, `${padded}_${name}.png`);
}

test.describe.serial("FHIR Sync E2E Verification", () => {
  test.setTimeout(300_000); // 5 minutes total

  test("Step 1: Login to External OpenEMR", async ({ page }) => {
    await page.goto(`${OPENEMR_URL}/interface/login/login.php?site=default`, {
      waitUntil: "networkidle",
      timeout: 30000,
    });
    await page.screenshot({ path: ssPath("openemr_login_page"), fullPage: true });

    // Fill login form
    await page.fill('input[name="authUser"]', OPENEMR_USER);
    await page.fill('input[name="clearPass"]', OPENEMR_PASS);
    await page.screenshot({ path: ssPath("openemr_login_filled"), fullPage: true });

    await page.click('button[type="submit"]');
    await page.waitForLoadState("networkidle", { timeout: 30000 });
    await page.waitForTimeout(3000);
    await page.screenshot({ path: ssPath("openemr_dashboard"), fullPage: true });
  });

  test("Step 2: Create New Patient with Full Demographics", async ({ page }) => {
    // Login first
    await page.goto(`${OPENEMR_URL}/interface/login/login.php?site=default`, {
      waitUntil: "networkidle",
      timeout: 30000,
    });
    await page.fill('input[name="authUser"]', OPENEMR_USER);
    await page.fill('input[name="clearPass"]', OPENEMR_PASS);
    await page.click('button[type="submit"]');
    await page.waitForLoadState("networkidle", { timeout: 30000 });
    await page.waitForTimeout(3000);

    // Navigate to new patient
    // Try the direct URL for adding a new patient
    await page.goto(
      `${OPENEMR_URL}/interface/new/new.php`,
      { waitUntil: "networkidle", timeout: 30000 }
    );
    await page.waitForTimeout(2000);
    await page.screenshot({ path: ssPath("openemr_new_patient_page"), fullPage: true });

    // Check if we're in an iframe situation — OpenEMR uses frames
    // Let's try the main interface approach
    await page.goto(
      `${OPENEMR_URL}/interface/main/main_screen.php?auth=login&site=default`,
      { waitUntil: "networkidle", timeout: 30000 }
    );
    await page.waitForTimeout(3000);

    // Look for the Patient menu or New Patient link
    // OpenEMR typically uses a left nav or top menu
    const frame = page.frames().find((f) => f.url().includes("main_screen") || f.url().includes("left_nav"));

    // Try clicking Patient > New Patient in the navigation
    // First let's see what's on the page
    await page.screenshot({ path: ssPath("openemr_main_screen"), fullPage: true });

    // Try direct new patient URL in the main content frame
    await page.goto(
      `${OPENEMR_URL}/interface/new/new.php?autoloaded=1&calession=1`,
      { waitUntil: "networkidle", timeout: 30000 }
    );
    await page.waitForTimeout(2000);
    await page.screenshot({ path: ssPath("openemr_new_patient_form"), fullPage: true });
  });
});
