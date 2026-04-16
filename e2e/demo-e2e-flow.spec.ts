/**
 * RAF Intelligence — Full E2E Demo Flow
 *
 * Creates patient in OpenEMR, adds clinical data via FHIR API,
 * triggers sync, verifies in RAF Intelligence, captures screenshots.
 *
 * Usage:
 *   PLAYWRIGHT_BASE_URL=https://raf.comercioit.com \
 *   npx playwright test demo-e2e-flow.spec.ts --project=chromium --headed
 */

import { test, expect, Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

// ── Config ────────────────────────────────────────────────────────────
const OPENEMR_URL = "https://openemr.ehrservicedesk.com";
const OPENEMR_USER = "admin";
const OPENEMR_PASS = "Healthcare@Admin2026";

const FHIR_CLIENT_ID = "HiOgcn8AuldnXty63EF54oktQl9xslbr9TW3wb64Y9w";
const FHIR_CLIENT_SECRET =
  "NXK-FRBTYi2g2F2a4_GPjoM8QCd_6OSfD-v6v0u_-FMON-4NK6bd0TN1JY5LXLUpbO-6APERtJSS58M9tdRjhQ";

const RAF_API = "https://raf-api.comercioit.com";
const RAF_URL = "https://raf.comercioit.com";
const RAF_USER = "admin@raf.health";
const RAF_PASS = "Admin@123";

const SCREENSHOTS_DIR = path.join(__dirname, "demo-screenshots");
let step = 0;

// ── Helpers ───────────────────────────────────────────────────────────
async function shot(page: Page, name: string) {
  step++;
  const filename = `${String(step).padStart(2, "0")}_${name}.png`;
  await page.screenshot({ path: path.join(SCREENSHOTS_DIR, filename) });
  console.log(`  📸 ${filename}`);
}

async function shotFull(page: Page, name: string) {
  step++;
  const filename = `${String(step).padStart(2, "0")}_${name}.png`;
  await page.screenshot({ path: path.join(SCREENSHOTS_DIR, filename), fullPage: true });
  console.log(`  📸 ${filename} (full)`);
}

async function getFhirToken(): Promise<string> {
  const res = await fetch(`${OPENEMR_URL}/oauth2/default/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "password",
      client_id: FHIR_CLIENT_ID,
      client_secret: FHIR_CLIENT_SECRET,
      username: OPENEMR_USER,
      password: OPENEMR_PASS,
      user_role: "users",
      scope: "openid api:fhir user/Patient.read user/Patient.write user/Condition.read user/Condition.write user/Encounter.read user/Encounter.write user/Observation.read user/Observation.write user/MedicationRequest.read user/MedicationRequest.write user/AllergyIntolerance.read user/AllergyIntolerance.write user/Immunization.read user/Immunization.write",
    }),
  });
  const data = await res.json();
  if (!data.access_token) throw new Error(`FHIR token failed: ${JSON.stringify(data)}`);
  return data.access_token;
}

async function getRafToken(): Promise<string> {
  const res = await fetch(`${RAF_API}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: RAF_USER, password: RAF_PASS }),
  });
  const data = await res.json();
  return data.access_token;
}

async function fhirPost(token: string, resource: string, body: object): Promise<any> {
  const res = await fetch(`${OPENEMR_URL}/apis/default/fhir/${resource}`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/fhir+json" },
    body: JSON.stringify(body),
  });
  return res.json();
}

// ── Test ──────────────────────────────────────────────────────────────
test.describe("RAF Intelligence Full E2E Demo", () => {
  test.setTimeout(600_000); // 10 min

  test.beforeAll(() => {
    fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
    for (const f of fs.readdirSync(SCREENSHOTS_DIR)) {
      if (f.endsWith(".png")) fs.unlinkSync(path.join(SCREENSHOTS_DIR, f));
    }
  });

  test("Complete flow: OpenEMR patient → FHIR sync → AI analysis → RAF scoring", async ({
    browser,
  }) => {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 900 },
      ignoreHTTPSErrors: true,
    });
    const page = await context.newPage();

    // ══════════════════════════════════════════════════════════════
    // PART 1: OpenEMR Login
    // ══════════════════════════════════════════════════════════════
    console.log("\n🏥 PART 1: OpenEMR Login\n");

    await page.goto(`${OPENEMR_URL}/interface/login/login.php?site=default`);
    await page.waitForLoadState("networkidle");
    await shot(page, "openemr_login_page");

    await page.locator('#authUser').fill(OPENEMR_USER);
    await page.locator('#clearPass').fill(OPENEMR_PASS);
    await shot(page, "openemr_login_filled");

    await page.locator('#login-button').click();
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(3000);
    await shot(page, "openemr_dashboard");

    // ══════════════════════════════════════════════════════════════
    // PART 2: Create Patient in OpenEMR UI
    // ══════════════════════════════════════════════════════════════
    console.log("\n👤 PART 2: Creating Patient — Maria Elena Rodriguez\n");

    // Navigate to new patient form
    await page.goto(`${OPENEMR_URL}/interface/new/new_comprehensive.php`, {
      waitUntil: "networkidle",
    });
    await page.waitForTimeout(2000);
    await shot(page, "openemr_new_patient_form");

    // Fill patient demographics using exact IDs from OpenEMR form
    await page.locator('#form_fname').fill("Maria");
    await page.locator('#form_mname').fill("Elena");
    await page.locator('#form_lname').fill("Rodriguez");
    console.log("  ✅ Name: Maria Elena Rodriguez");

    // DOB — use evaluate to bypass datepicker widget
    await page.evaluate(() => {
      const dob = document.getElementById('form_DOB') as HTMLInputElement;
      if (dob) { dob.value = '1958-03-15'; dob.dispatchEvent(new Event('change')); }
    });
    console.log("  ✅ DOB: 1958-03-15");

    // Birth Sex
    await page.locator('#form_sex').selectOption('Female');
    console.log("  ✅ Sex: Female");

    // SSN & External ID
    await page.locator('#form_ss').fill("999-88-7777");
    await page.locator('#form_pubpid').fill("RAF-DEMO-2026");
    console.log("  ✅ SSN & External ID filled");

    await shot(page, "openemr_patient_demographics_filled");

    // Expand Contact section (collapsed by default)
    await page.locator('button:has-text("Contact")').click();
    await page.waitForTimeout(500);

    // Fill address & contact
    await page.locator('#form_street').fill("4521 Palm Beach Blvd");
    await page.locator('#form_city').fill("Miami");
    await page.locator('#form_postal_code').fill("33137");
    await page.locator('#form_phone_home').fill("(305) 555-0142");
    await page.locator('#form_email').fill("maria.rodriguez@example.com");

    // State dropdown
    try { await page.locator('#form_state').selectOption('FL'); } catch {
      try { await page.locator('#form_state').selectOption({ label: 'Florida' }); } catch {}
    }
    console.log("  ✅ Address & Contact filled");
    await shot(page, "openemr_patient_contact_filled");

    // Scroll to bottom and take full form screenshot
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    await page.waitForTimeout(500);
    await shotFull(page, "openemr_patient_form_complete");

    // Click "Create New Patient"
    await page.locator('#create').click();
    await page.waitForTimeout(4000);
    console.log("  ✅ Patient creation submitted");

    // Handle confirmation dialog if it appears
    try {
      const confirmBtn = page.locator('button:has-text("Confirm"), button:has-text("Yes"), button:has-text("OK")').first();
      if (await confirmBtn.isVisible({ timeout: 3000 })) {
        await confirmBtn.click();
        await page.waitForTimeout(2000);
      }
    } catch {}

    await shot(page, "openemr_patient_created");

    // ══════════════════════════════════════════════════════════════
    // PART 3: Add Clinical Data via FHIR API
    // ══════════════════════════════════════════════════════════════
    console.log("\n🩺 PART 3: Adding Clinical Data via FHIR API\n");

    const fhirToken = await getFhirToken();
    console.log("  ✅ FHIR token obtained");

    // Find patient
    const patSearchRes = await fetch(
      `${OPENEMR_URL}/apis/default/fhir/Patient?family=Rodriguez&given=Maria`,
      { headers: { Authorization: `Bearer ${fhirToken}` } }
    );
    const patSearch = await patSearchRes.json();
    let patientId = patSearch.entry?.[patSearch.entry.length - 1]?.resource?.id;
    console.log(`  Patient FHIR ID: ${patientId}`);

    if (!patientId) {
      // Try broader search
      const allPats = await fetch(
        `${OPENEMR_URL}/apis/default/fhir/Patient?_count=50`,
        { headers: { Authorization: `Bearer ${fhirToken}` } }
      );
      const allPatsData = await allPats.json();
      console.log(`  Total patients: ${allPatsData.total || allPatsData.entry?.length}`);
      // Get the last one (most recently created)
      const entries = allPatsData.entry || [];
      if (entries.length > 0) {
        patientId = entries[entries.length - 1].resource.id;
        const name = entries[entries.length - 1].resource.name?.[0];
        console.log(`  Using latest patient: ${name?.given?.[0]} ${name?.family} (${patientId})`);
      }
    }

    if (!patientId) {
      console.log("  ❌ No patient found — skipping FHIR data creation");
    } else {
      // ── 3a: Conditions ──
      console.log("\n  📋 Adding ICD-10 Conditions:");
      const conditions = [
        { code: "E11.9", display: "Type 2 diabetes mellitus without complications" },
        { code: "I50.9", display: "Heart failure, unspecified" },
        { code: "J44.1", display: "COPD with acute exacerbation" },
        { code: "F32.1", display: "Major depressive disorder, single episode, moderate" },
        { code: "E66.01", display: "Morbid obesity due to excess calories" },
        { code: "N18.3", display: "Chronic kidney disease, stage 3" },
        { code: "I10", display: "Essential hypertension" },
        { code: "E78.5", display: "Dyslipidemia, unspecified" },
      ];

      let conditionsCreated = 0;
      for (const cond of conditions) {
        const result = await fhirPost(fhirToken, "Condition", {
          resourceType: "Condition",
          clinicalStatus: {
            coding: [{ system: "http://terminology.hl7.org/CodeSystem/condition-clinical", code: "active" }],
          },
          verificationStatus: {
            coding: [{ system: "http://terminology.hl7.org/CodeSystem/condition-ver-status", code: "confirmed" }],
          },
          category: [{
            coding: [{ system: "http://terminology.hl7.org/CodeSystem/condition-category", code: "encounter-diagnosis" }],
          }],
          code: {
            coding: [{ system: "http://hl7.org/fhir/sid/icd-10-cm", code: cond.code, display: cond.display }],
            text: cond.display,
          },
          subject: { reference: `Patient/${patientId}` },
          onsetDateTime: "2025-06-15",
          recordedDate: "2026-04-10",
        });
        if (result.id) {
          conditionsCreated++;
          console.log(`    ✅ ${cond.code} — ${cond.display}`);
        } else {
          console.log(`    ❌ ${cond.code} — ${JSON.stringify(result).substring(0, 120)}`);
        }
      }
      console.log(`  Total conditions created: ${conditionsCreated}/${conditions.length}`);

      // ── 3b: Encounter ──
      console.log("\n  📋 Adding Encounter:");
      const encResult = await fhirPost(fhirToken, "Encounter", {
        resourceType: "Encounter",
        status: "finished",
        class: { system: "http://terminology.hl7.org/CodeSystem/v3-ActCode", code: "AMB", display: "ambulatory" },
        type: [{
          coding: [{ system: "http://snomed.info/sct", code: "185349003", display: "Encounter for check up" }],
          text: "Annual Wellness Visit",
        }],
        subject: { reference: `Patient/${patientId}` },
        period: { start: "2026-04-10", end: "2026-04-10" },
        reasonCode: [{ text: "Annual Wellness Visit - Comprehensive Assessment" }],
      });
      console.log(`    Encounter: ${encResult.id ? "✅ Created" : "❌ " + JSON.stringify(encResult).substring(0, 120)}`);

      // ── 3c: Medications ──
      console.log("\n  💊 Adding Medications:");
      const meds = [
        { code: "860975", display: "Metformin 1000mg", dosage: "1000 mg twice daily" },
        { code: "314076", display: "Lisinopril 20mg", dosage: "20 mg once daily" },
        { code: "310429", display: "Furosemide 40mg", dosage: "40 mg once daily" },
        { code: "312938", display: "Sertraline 100mg", dosage: "100 mg once daily" },
        { code: "1232186", display: "Tiotropium 18mcg inhaler", dosage: "18 mcg inhaled once daily" },
      ];
      for (const med of meds) {
        const result = await fhirPost(fhirToken, "MedicationRequest", {
          resourceType: "MedicationRequest",
          status: "active",
          intent: "order",
          medicationCodeableConcept: {
            coding: [{ system: "http://www.nlm.nih.gov/research/umls/rxnorm", code: med.code, display: med.display }],
            text: med.display,
          },
          subject: { reference: `Patient/${patientId}` },
          authoredOn: "2026-04-10",
          dosageInstruction: [{ text: med.dosage }],
        });
        console.log(`    ${med.display}: ${result.id ? "✅" : "❌ " + JSON.stringify(result).substring(0, 100)}`);
      }

      // ── 3d: Lab Results (Observations) ──
      console.log("\n  🔬 Adding Lab Results:");
      const labs = [
        { code: "4548-4", display: "Hemoglobin A1c", value: 8.2, unit: "%" },
        { code: "33914-3", display: "eGFR", value: 45, unit: "mL/min/1.73m2" },
        { code: "30934-4", display: "BNP", value: 450, unit: "pg/mL" },
        { code: "2089-1", display: "LDL Cholesterol", value: 145, unit: "mg/dL" },
        { code: "39156-5", display: "BMI", value: 42.1, unit: "kg/m2" },
        { code: "2160-0", display: "Creatinine", value: 1.8, unit: "mg/dL" },
      ];
      for (const lab of labs) {
        const result = await fhirPost(fhirToken, "Observation", {
          resourceType: "Observation",
          status: "final",
          category: [{
            coding: [{ system: "http://terminology.hl7.org/CodeSystem/observation-category", code: "laboratory" }],
          }],
          code: {
            coding: [{ system: "http://loinc.org", code: lab.code, display: lab.display }],
            text: lab.display,
          },
          subject: { reference: `Patient/${patientId}` },
          effectiveDateTime: "2026-04-10T09:30:00Z",
          valueQuantity: { value: lab.value, unit: lab.unit, system: "http://unitsofmeasure.org" },
        });
        console.log(`    ${lab.display} = ${lab.value} ${lab.unit}: ${result.id ? "✅" : "❌ " + JSON.stringify(result).substring(0, 100)}`);
      }

      // ── 3e: Allergies ──
      console.log("\n  ⚠️ Adding Allergies:");
      const allergies = [
        { substance: "Penicillin", code: "7980", criticality: "high", reaction: "Anaphylaxis" },
        { substance: "Sulfonamides", code: "10205", criticality: "low", reaction: "Skin rash" },
      ];
      for (const a of allergies) {
        const result = await fhirPost(fhirToken, "AllergyIntolerance", {
          resourceType: "AllergyIntolerance",
          clinicalStatus: { coding: [{ system: "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical", code: "active" }] },
          verificationStatus: { coding: [{ system: "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification", code: "confirmed" }] },
          type: "allergy",
          category: ["medication"],
          criticality: a.criticality,
          code: {
            coding: [{ system: "http://www.nlm.nih.gov/research/umls/rxnorm", code: a.code, display: a.substance }],
            text: a.substance,
          },
          patient: { reference: `Patient/${patientId}` },
          recordedDate: "2026-04-10",
        });
        console.log(`    ${a.substance}: ${result.id ? "✅" : "❌ " + JSON.stringify(result).substring(0, 100)}`);
      }

      // ── 3f: Immunizations ──
      console.log("\n  💉 Adding Immunizations:");
      const imms = [
        { code: "213", display: "COVID-19 vaccine", date: "2026-01-15" },
        { code: "197", display: "Influenza vaccine", date: "2025-10-01" },
      ];
      for (const imm of imms) {
        const result = await fhirPost(fhirToken, "Immunization", {
          resourceType: "Immunization",
          status: "completed",
          vaccineCode: { coding: [{ system: "http://hl7.org/fhir/sid/cvx", code: imm.code, display: imm.display }], text: imm.display },
          patient: { reference: `Patient/${patientId}` },
          occurrenceDateTime: imm.date,
          primarySource: true,
        });
        console.log(`    ${imm.display}: ${result.id ? "✅" : "❌ " + JSON.stringify(result).substring(0, 100)}`);
      }
    }

    // ── Screenshot: View patient in OpenEMR with all data ──
    // Navigate to patient summary to see everything
    await page.goto(`${OPENEMR_URL}/interface/patient_file/summary/demographics.php`, {
      waitUntil: "networkidle",
    });
    await page.waitForTimeout(2000);
    await shotFull(page, "openemr_patient_with_all_data");

    // Verify via FHIR what data exists
    console.log("\n  ✅ Verifying data in FHIR:");
    const verifyResources = ["Condition", "Encounter", "MedicationRequest", "Observation", "AllergyIntolerance", "Immunization"];
    for (const res of verifyResources) {
      try {
        const r = await fetch(
          `${OPENEMR_URL}/apis/default/fhir/${res}?patient=${patientId}`,
          { headers: { Authorization: `Bearer ${fhirToken}` } }
        );
        const d = await r.json();
        console.log(`    ${res}: ${d.total ?? d.entry?.length ?? 0} records`);
      } catch (e) {
        console.log(`    ${res}: ❌ ${e}`);
      }
    }

    // ══════════════════════════════════════════════════════════════
    // PART 4: RAF Intelligence — Login & Verify Settings
    // ══════════════════════════════════════════════════════════════
    console.log("\n🧠 PART 4: RAF Intelligence — Login\n");

    await page.goto(`${RAF_URL}/login`);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(2000);
    await shot(page, "raf_login_page");

    await page.locator('input[type="email"], input[name="email"]').first().fill(RAF_USER);
    await page.locator('input[type="password"], input[name="password"]').first().fill(RAF_PASS);
    await shot(page, "raf_login_filled");

    await page.locator('button[type="submit"]').first().click();
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(4000);
    await shot(page, "raf_dashboard_after_login");

    // ══════════════════════════════════════════════════════════════
    // PART 5: Check Pipeline Configuration (AI Enabled)
    // ══════════════════════════════════════════════════════════════
    console.log("\n⚙️ PART 5: Pipeline Configuration\n");

    // Try different possible URLs for configuration
    for (const configPath of ["/configuration", "/settings", "/pipeline", "/admin/settings"]) {
      try {
        await page.goto(`${RAF_URL}${configPath}`, { waitUntil: "networkidle", timeout: 8000 });
        await page.waitForTimeout(2000);
        const title = await page.title();
        const content = await page.textContent("body");
        if (content && content.length > 100 && !content.includes("404")) {
          await shot(page, `raf_config_${configPath.replace(/\//g, "_")}`);
          console.log(`  ✅ Config page found at ${configPath}`);
          break;
        }
      } catch {}
    }

    // ══════════════════════════════════════════════════════════════
    // PART 6: Check EMR Connection
    // ══════════════════════════════════════════════════════════════
    console.log("\n🔗 PART 6: EMR Connection\n");

    for (const emrPath of ["/emr-config", "/emr", "/connections", "/integrations"]) {
      try {
        await page.goto(`${RAF_URL}${emrPath}`, { waitUntil: "networkidle", timeout: 8000 });
        await page.waitForTimeout(2000);
        const content = await page.textContent("body");
        if (content && content.length > 100 && !content.includes("404")) {
          await shot(page, `raf_emr_connection`);
          console.log(`  ✅ EMR config found at ${emrPath}`);
          break;
        }
      } catch {}
    }

    // ══════════════════════════════════════════════════════════════
    // PART 7: Trigger FHIR Sync
    // ══════════════════════════════════════════════════════════════
    console.log("\n🔄 PART 7: Triggering FHIR Sync\n");

    const rafToken = await getRafToken();

    const syncRes = await fetch(`${RAF_API}/api/emr/connections/9/sync?sync_type=full`, {
      method: "POST",
      headers: { Authorization: `Bearer ${rafToken}` },
    });
    const syncData = await syncRes.json();
    console.log(`  Sync triggered: ${JSON.stringify(syncData).substring(0, 200)}`);

    // Poll for sync completion
    let syncComplete = false;
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 10000));
      try {
        const statusRes = await fetch(`${RAF_API}/api/emr/connections/9/sync/history?limit=1`, {
          headers: { Authorization: `Bearer ${rafToken}` },
        });
        const statusData = await statusRes.json();
        const latest = statusData.history?.[0] || statusData[0];
        const status = latest?.status || latest?.sync_status || "unknown";
        console.log(`  Poll ${i + 1}/30: ${status}`);

        if (status === "completed" || status === "success") {
          syncComplete = true;
          console.log(`  ✅ Sync completed! Details: ${JSON.stringify(latest).substring(0, 300)}`);
          break;
        }
        if (status === "failed") {
          console.log(`  ❌ Sync failed: ${JSON.stringify(latest).substring(0, 300)}`);
          break;
        }
      } catch (e) {
        console.log(`  Poll error: ${e}`);
      }
    }

    // Wait a bit for pipeline chain to process (AI analysis, RAF calc, etc.)
    if (syncComplete) {
      console.log("  ⏳ Waiting 60s for AI pipeline to process...");
      await new Promise((r) => setTimeout(r, 60000));
    }

    // ══════════════════════════════════════════════════════════════
    // PART 8: RAF Intelligence — View Patients
    // ══════════════════════════════════════════════════════════════
    console.log("\n👥 PART 8: View Patients in RAF\n");

    await page.goto(`${RAF_URL}/patients`, { waitUntil: "networkidle" });
    await page.waitForTimeout(3000);
    await shot(page, "raf_patients_list");

    // Search for Rodriguez
    try {
      const search = page.locator('input[placeholder*="earch"], input[type="search"]').first();
      if (await search.isVisible({ timeout: 3000 })) {
        await search.fill("Rodriguez");
        await page.waitForTimeout(2000);
        await shot(page, "raf_patient_search_rodriguez");
      }
    } catch {}

    // Click on the patient
    try {
      const row = page.locator('tr:has-text("Rodriguez"), [class*="row"]:has-text("Rodriguez"), a:has-text("Rodriguez")').first();
      if (await row.isVisible({ timeout: 5000 })) {
        await row.click();
        await page.waitForLoadState("networkidle");
        await page.waitForTimeout(3000);
        await shot(page, "raf_patient_detail");

        // Scroll for more detail
        await page.evaluate(() => window.scrollBy(0, 600));
        await page.waitForTimeout(1000);
        await shot(page, "raf_patient_detail_conditions");

        await page.evaluate(() => window.scrollBy(0, 600));
        await page.waitForTimeout(1000);
        await shot(page, "raf_patient_detail_more");
      }
    } catch (e) {
      console.log(`  ⚠️ Patient click: ${e}`);
    }

    // ══════════════════════════════════════════════════════════════
    // PART 9: RAF Dashboard & Analytics
    // ══════════════════════════════════════════════════════════════
    console.log("\n📊 PART 9: Dashboard & Analytics\n");

    await page.goto(`${RAF_URL}/dashboard`, { waitUntil: "networkidle" });
    await page.waitForTimeout(3000);
    await shot(page, "raf_dashboard_overview");

    // Try analysis page
    for (const analysisPath of ["/analysis", "/ai-analysis", "/encounters"]) {
      try {
        await page.goto(`${RAF_URL}${analysisPath}`, { waitUntil: "networkidle", timeout: 8000 });
        await page.waitForTimeout(2000);
        const content = await page.textContent("body");
        if (content && content.length > 200 && !content.includes("404")) {
          await shot(page, "raf_analysis_results");
          console.log(`  ✅ Analysis page at ${analysisPath}`);
          break;
        }
      } catch {}
    }

    // ══════════════════════════════════════════════════════════════
    // PART 10: Suspects Page
    // ══════════════════════════════════════════════════════════════
    console.log("\n🔍 PART 10: Suspects\n");

    for (const suspPath of ["/suspects", "/suspect-conditions"]) {
      try {
        await page.goto(`${RAF_URL}${suspPath}`, { waitUntil: "networkidle", timeout: 8000 });
        await page.waitForTimeout(2000);
        const content = await page.textContent("body");
        if (content && content.length > 200 && !content.includes("404")) {
          await shot(page, "raf_suspects");
          break;
        }
      } catch {}
    }

    // ══════════════════════════════════════════════════════════════
    // PART 11: Care Gaps
    // ══════════════════════════════════════════════════════════════
    console.log("\n📝 PART 11: Care Gaps\n");

    for (const gapPath of ["/care-gaps", "/gaps", "/worklist"]) {
      try {
        await page.goto(`${RAF_URL}${gapPath}`, { waitUntil: "networkidle", timeout: 8000 });
        await page.waitForTimeout(2000);
        const content = await page.textContent("body");
        if (content && content.length > 200 && !content.includes("404")) {
          await shot(page, "raf_care_gaps");
          break;
        }
      } catch {}
    }

    // ══════════════════════════════════════════════════════════════
    // PART 12: Provider Worklist
    // ══════════════════════════════════════════════════════════════
    console.log("\n📋 PART 12: Provider Worklist\n");

    for (const wlPath of ["/worklists", "/provider-worklist", "/coder-worklist"]) {
      try {
        await page.goto(`${RAF_URL}${wlPath}`, { waitUntil: "networkidle", timeout: 8000 });
        await page.waitForTimeout(2000);
        const content = await page.textContent("body");
        if (content && content.length > 200 && !content.includes("404")) {
          await shot(page, `raf_worklist`);
          break;
        }
      } catch {}
    }

    // ══════════════════════════════════════════════════════════════
    // PART 13: API Verification — Get hard data
    // ══════════════════════════════════════════════════════════════
    console.log("\n📊 PART 13: API Data Verification\n");

    const freshToken = await getRafToken();

    // Check patients
    const patsRes = await fetch(`${RAF_API}/api/patients?search=Rodriguez`, {
      headers: { Authorization: `Bearer ${freshToken}` },
    });
    const patsData = await patsRes.json();
    console.log(`  Patients matching 'Rodriguez': ${JSON.stringify(patsData).substring(0, 300)}`);

    // Check RAF scores
    const scoresRes = await fetch(`${RAF_API}/api/raf/scores?limit=5`, {
      headers: { Authorization: `Bearer ${freshToken}` },
    });
    const scoresData = await scoresRes.json();
    console.log(`  RAF Scores: ${JSON.stringify(scoresData).substring(0, 300)}`);

    // Check suspects
    const suspectsRes = await fetch(`${RAF_API}/api/suspects?limit=5`, {
      headers: { Authorization: `Bearer ${freshToken}` },
    });
    const suspectsData = await suspectsRes.json();
    console.log(`  Suspects: ${JSON.stringify(suspectsData).substring(0, 300)}`);

    // Check pipeline run status
    const pipelineRes = await fetch(`${RAF_API}/api/pipeline/status`, {
      headers: { Authorization: `Bearer ${freshToken}` },
    });
    const pipelineData = await pipelineRes.json();
    console.log(`  Pipeline: ${JSON.stringify(pipelineData).substring(0, 300)}`);

    // ══════════════════════════════════════════════════════════════
    // PART 14: Final Dashboard Screenshot
    // ══════════════════════════════════════════════════════════════
    console.log("\n🏁 PART 14: Final Dashboard\n");

    await page.goto(`${RAF_URL}/dashboard`, { waitUntil: "networkidle" });
    await page.waitForTimeout(3000);
    await shotFull(page, "raf_final_dashboard");

    // ═══════════════════════════════════════════════════════════════
    console.log("\n" + "═".repeat(60));
    console.log(`  📸 Total screenshots: ${step}`);
    console.log(`  📁 Location: e2e/demo-screenshots/`);
    console.log("═".repeat(60) + "\n");

    await context.close();
  });
});
