import { chromium, Frame, Page } from "playwright";
import * as path from "path";
import * as fs from "fs";

const OPENEMR_URL = "https://openemr.ehrservicedesk.com";
const OPENEMR_USER = "admin";
const OPENEMR_PASS = "Healthcare@Admin2026";
const OPENEMR_CLIENT_ID = "AGl5Lx0OhB7oTEfiR2W1TZjAlb7BZSOGeE8jf95v88E";
const RAF_API = "https://raf-api.comercioit.com";
const RAF_UI = "https://raf.comercioit.com";
const RAF_USER = "admin@raf.health";
const RAF_PASS = "Admin@123";

// Eleanor Whitfield was already created via FHIR API — PID 107, UUID a18cd1dc-9054-4be1-8b1d-36d3cc16aa83
const FHIR_ID = "a18cd1dc-9054-4be1-8b1d-36d3cc16aa83";
const PATIENT_NAME = "Eleanor Whitfield";

const SS_DIR = path.join(__dirname, "screenshots");
if (!fs.existsSync(SS_DIR)) fs.mkdirSync(SS_DIR, { recursive: true });

let idx = 0;
function ss(name: string) { idx++; return path.join(SS_DIR, `${String(idx).padStart(2, "0")}_${name}.png`); }
async function sleep(ms: number) { return new Promise(r => setTimeout(r, ms)); }

async function main() {
  const timestamps: Record<string, string> = {};

  console.log("═══════════════════════════════════════════════════════");
  console.log("  E2E FHIR SYNC VERIFICATION: Eleanor Grace Whitfield");
  console.log("═══════════════════════════════════════════════════════\n");
  console.log("Patient FHIR ID:", FHIR_ID);
  console.log("Patient was created via FHIR API at 2026-04-15T14:04:43Z\n");

  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, ignoreHTTPSErrors: true });
  const page = await ctx.newPage();
  page.setDefaultTimeout(30000);
  page.on("dialog", async d => { console.log("  Dialog:", d.message()); await d.accept(); });

  // ─── STEP 1: Login to OpenEMR & find Eleanor ───
  console.log("STEP 1: Login to OpenEMR & open patient...");
  await page.goto(`${OPENEMR_URL}/interface/login/login.php?site=default`, { waitUntil: "networkidle" });
  await page.screenshot({ path: ss("openemr_login"), fullPage: true });
  await page.fill('input[name="authUser"]', OPENEMR_USER);
  await page.fill('input[name="clearPass"]', OPENEMR_PASS);
  await page.click('button[type="submit"]');
  await page.waitForLoadState("networkidle");
  await sleep(5000);
  await page.screenshot({ path: ss("openemr_dashboard"), fullPage: true });
  console.log("  ✓ Logged in");

  // Search for Eleanor
  const searchBox = page.locator('#anySearchBox');
  if (await searchBox.count() > 0) {
    await searchBox.fill("Whitfield");
    await page.keyboard.press("Enter");
    await sleep(4000);
    await page.screenshot({ path: ss("openemr_search_whitfield"), fullPage: true });
    console.log("  ✓ Searched for Whitfield");
  }

  // Find patient in the new.php frame
  let npFrame = page.frames().find(f => f.url().includes("/new/new.php"));
  if (npFrame) {
    // Click on the patient name in search results
    const patientLink = npFrame.locator('a:has-text("Whitfield"), td:has-text("Whitfield")').first();
    if (await patientLink.isVisible({ timeout: 5000 }).catch(() => false)) {
      await patientLink.click();
      await sleep(5000);
      console.log("  ✓ Selected patient from search");
    }
  }

  await page.screenshot({ path: ss("openemr_patient_context"), fullPage: true });

  // Log all frames
  for (const f of page.frames()) {
    if (!f.url().includes("about:blank")) {
      console.log("  Frame:", f.url().substring(0, 90));
    }
  }

  // ─── STEP 2: Screenshot Demographics ───
  console.log("\nSTEP 2: Screenshot patient demographics...");
  let demoFrame = page.frames().find(f => f.url().includes("demographics") || f.url().includes("patient_file/summary"));
  if (demoFrame) {
    await page.screenshot({ path: ss("openemr_demographics"), fullPage: true });
    try {
      await demoFrame.evaluate(() => window.scrollBy(0, 500));
      await sleep(500);
    } catch {}
    await page.screenshot({ path: ss("openemr_demographics_scroll"), fullPage: true });
    console.log("  ✓ Demographics captured");
  } else {
    console.log("  ⚠ Demographics frame not found");
    await page.screenshot({ path: ss("openemr_no_demographics"), fullPage: true });
  }

  // ─── STEP 3: Create Encounter via UI ───
  console.log("\nSTEP 3: Create encounter...");

  // Try to find "Create Visit" button in the summary page
  let encCreated = false;
  for (const f of page.frames()) {
    try {
      // Look for "Create Visit" or "New Encounter"
      const createVisit = f.locator('a:has-text("Create Visit"), button:has-text("Create Visit"), a:has-text("New Encounter")');
      if (await createVisit.count() > 0) {
        await createVisit.first().click();
        await sleep(4000);
        encCreated = true;
        console.log("  ✓ Clicked Create Visit");
        break;
      }
    } catch {}
  }

  if (!encCreated) {
    // Try the + button at top
    try {
      const plusBtn = page.locator('#new0, .fa-plus').first();
      if (await plusBtn.count() > 0) {
        await plusBtn.click();
        await sleep(2000);
      }
    } catch {}
    console.log("  Trying alternate approach to create encounter...");
  }

  await page.screenshot({ path: ss("encounter_creation"), fullPage: true });

  // Fill encounter form if found
  for (const f of page.frames()) {
    try {
      const reasonField = f.locator('textarea[name="reason"], input[name="reason"]');
      if (await reasonField.count() > 0) {
        await reasonField.fill("Annual Wellness Visit - Comprehensive RAF assessment");

        // Provider select
        const providerSel = f.locator('select[name="provider_id"]');
        if (await providerSel.count() > 0) {
          try { await providerSel.selectOption({ index: 1 }); } catch {}
        }

        // Facility select
        const facilSel = f.locator('select[name="facility_id"]');
        if (await facilSel.count() > 0) {
          try { await facilSel.selectOption({ index: 1 }); } catch {}
        }

        await page.screenshot({ path: ss("encounter_form_filled"), fullPage: true });

        // Save
        const saveBtn = f.locator('button:has-text("Save"), input[type="submit"]');
        if (await saveBtn.count() > 0) {
          await saveBtn.first().click();
          await sleep(4000);
          timestamps.encounterCreated = new Date().toISOString();
          console.log("  ✓ Encounter saved");
        }
        break;
      }
    } catch {}
  }
  await page.screenshot({ path: ss("after_encounter"), fullPage: true });

  // ─── STEP 4: Add Vitals ───
  console.log("\nSTEP 4: Add vitals...");

  // Look for Vitals link
  for (const f of page.frames()) {
    try {
      const vitalsLink = f.locator('a:has-text("Vitals")');
      if (await vitalsLink.count() > 0) {
        await vitalsLink.first().click();
        await sleep(3000);
        console.log("  ✓ Opened Vitals form");
        break;
      }
    } catch {}
  }
  await page.screenshot({ path: ss("vitals_page"), fullPage: true });

  // Fill vitals
  for (const f of page.frames()) {
    try {
      const bpsField = f.locator('input[name="form_bps"], input#bps');
      if (await bpsField.count() > 0) {
        const vitalsMap: Record<string, string> = {
          "form_bps": "138", "form_bpd": "88",
          "form_pulse": "78", "form_respiration": "18",
          "form_temperature": "98.6",
          "form_weight": "172", "form_height": "65",
          "form_oxygen_saturation": "97",
        };
        for (const [name, val] of Object.entries(vitalsMap)) {
          const field = f.locator(`input[name="${name}"], input#${name.replace("form_", "")}`);
          if (await field.count() > 0) {
            try { await field.fill(val); } catch {
              await f.evaluate(([n, v]) => {
                const el = document.querySelector(`input[name="${n}"]`) as HTMLInputElement;
                if (el) el.value = v;
              }, [name, val]);
            }
          }
        }
        await page.screenshot({ path: ss("vitals_filled"), fullPage: true });
        console.log("  ✓ Vitals filled");

        const saveBtn = f.locator('button:has-text("Save"), input[value="Save Vitals"], input[type="submit"]');
        if (await saveBtn.count() > 0) {
          await saveBtn.first().click();
          await sleep(3000);
          timestamps.vitalsSaved = new Date().toISOString();
          console.log("  ✓ Vitals saved");
        }
        break;
      }
    } catch (e) {
      console.log("  vitals error:", e);
    }
  }
  await page.screenshot({ path: ss("after_vitals"), fullPage: true });

  // ─── STEP 5: Add Issues (Diagnoses) ───
  console.log("\nSTEP 5: Add medical issues (diagnoses)...");

  // Try to find Issues section
  for (const f of page.frames()) {
    try {
      const issuesLink = f.locator('a:has-text("Issues"), a:has-text("Medical Problem")');
      if (await issuesLink.count() > 0) {
        await issuesLink.first().click();
        await sleep(3000);
        console.log("  ✓ Opened Issues page");
        break;
      }
    } catch {}
  }
  await page.screenshot({ path: ss("issues_page"), fullPage: true });

  // ─── STEP 6: Final OpenEMR screenshot ───
  console.log("\nSTEP 6: Final OpenEMR patient view...");
  // Go back to demographics
  for (const f of page.frames()) {
    try {
      const demoLink = f.locator('a:has-text("Demographics")').first();
      if (await demoLink.isVisible({ timeout: 3000 }).catch(() => false)) {
        await demoLink.click();
        await sleep(3000);
        break;
      }
    } catch {}
  }
  await page.screenshot({ path: ss("final_openemr_view"), fullPage: true });

  // ─── STEP 7: Trigger FHIR Sync ───
  console.log("\nSTEP 7: Trigger FHIR sync in RAF...");
  timestamps.syncTriggered = new Date().toISOString();

  const rafToken = ((await (await fetch(`${RAF_API}/api/auth/login`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: RAF_USER, password: RAF_PASS }),
  })).json()) as any).access_token;

  // Trigger sync via EMR connection
  const syncResp = await fetch(`${RAF_API}/api/emr/connections/9/sync`, {
    method: "POST",
    headers: { Authorization: `Bearer ${rafToken}`, "Content-Type": "application/json" },
  });
  const syncResult = await syncResp.json() as any;
  console.log("  Sync:", syncResp.status, JSON.stringify(syncResult).substring(0, 200));

  // Wait for sync
  console.log("\nSTEP 8: Waiting for patient to appear in RAF...");
  let foundPid: number | null = null;

  for (let i = 1; i <= 18; i++) {
    await sleep(10000);
    process.stdout.write(` [${i * 10}s]`);
    try {
      const resp = await fetch(`${RAF_API}/api/patients?search=Whitfield`, {
        headers: { Authorization: `Bearer ${rafToken}` },
      });
      if (resp.ok) {
        const data = await resp.json() as any;
        const list = data.patients || data.data || [];
        const match = (Array.isArray(list) ? list : []).find(
          (p: any) => (p.lname || "").toLowerCase() === "whitfield"
        );
        if (match) {
          foundPid = match.pid || match.id;
          timestamps.patientFoundInRAF = new Date().toISOString();
          const delay = (new Date(timestamps.patientFoundInRAF).getTime() - new Date(timestamps.syncTriggered).getTime()) / 1000;
          console.log(`\n  ✓ FOUND! PID=${foundPid} | Sync delay: ${delay.toFixed(0)}s`);
          break;
        }
      }
    } catch {}
  }

  if (!foundPid) {
    console.log("\n  ⚠ Not found after 3 min. Checking server directly...");
    // Check if the FHIR sync created the fhir_patients row but not the patients row
    // Try getting all patients
    try {
      const allResp = await fetch(`${RAF_API}/api/patients`, {
        headers: { Authorization: `Bearer ${rafToken}` },
      });
      if (allResp.ok) {
        const allData = await allResp.json() as any;
        const total = allData.total || allData.count || (allData.patients || []).length;
        console.log("  Total patients in RAF:", total);
      }
    } catch {}
  }

  // ─── STEP 9: RAF UI Verification ───
  console.log("\nSTEP 9: RAF Intelligence UI verification...");
  await page.goto(`${RAF_UI}/login`, { waitUntil: "load", timeout: 20000 });
  await sleep(2000);
  try { await page.locator('input[type="email"]').first().fill(RAF_USER); } catch {}
  try { await page.locator('input[type="password"]').first().fill(RAF_PASS); } catch {}
  await page.screenshot({ path: ss("raf_login"), fullPage: true });
  try { await page.locator('button[type="submit"]').first().click(); } catch {}
  await sleep(5000);
  await page.screenshot({ path: ss("raf_dashboard"), fullPage: true });

  try {
    await page.goto(`${RAF_UI}/patients`, { waitUntil: "load", timeout: 15000 });
    await sleep(5000);
    await page.screenshot({ path: ss("raf_patients"), fullPage: true });

    const searchInput = page.locator('input[placeholder*="earch" i]').first();
    if (await searchInput.count() > 0) {
      await searchInput.fill("Whitfield");
      await sleep(3000);
      await page.screenshot({ path: ss("raf_search_whitfield"), fullPage: true });
    }

    const row = page.locator('text=Whitfield').first();
    if (await row.isVisible({ timeout: 5000 }).catch(() => false)) {
      await row.click();
      await sleep(5000);
      await page.screenshot({ path: ss("raf_patient_profile"), fullPage: true });
      for (let s = 1; s <= 4; s++) {
        await page.evaluate(y => window.scrollTo(0, y), s * 400);
        await sleep(600);
        await page.screenshot({ path: ss(`raf_patient_profile_s${s}`), fullPage: true });
      }
      console.log("  ✓ Patient profile captured");
    } else {
      console.log("  ⚠ Patient not in list");
      await page.screenshot({ path: ss("raf_patient_not_in_list"), fullPage: true });
    }
  } catch (e) {
    console.log("  UI error:", e);
  }

  // ─── STEP 10: API Verification ───
  console.log("\nSTEP 10: API data check...");
  if (foundPid) {
    for (const ep of ["comprehensive-profile", "encounters", "diagnoses", "medications"]) {
      try {
        const r = await fetch(`${RAF_API}/api/patients/${foundPid}/${ep}`, {
          headers: { Authorization: `Bearer ${rafToken}` },
        });
        if (r.ok) {
          const d = await r.json();
          fs.writeFileSync(path.join(SS_DIR, `api_${ep.replace(/-/g, "_")}.json`), JSON.stringify(d, null, 2));
          console.log(`  ✓ ${ep}: ${JSON.stringify(d).length} bytes`);
        }
      } catch {}
    }
  }

  // Summary
  console.log("\n╔════════════════════════════════════════════════╗");
  console.log("║         E2E FHIR SYNC VERIFICATION            ║");
  console.log("╠════════════════════════════════════════════════╣");
  console.log(`║ Patient : Eleanor Grace Whitfield`);
  console.log(`║ DOB     : 1952-07-14   Sex: Female`);
  console.log(`║ Address : 742 Evergreen Terrace, Springfield IL`);
  console.log(`║ FHIR ID : ${FHIR_ID}`);
  console.log(`║ RAF PID : ${foundPid || "NOT SYNCED"}`);
  for (const [k, v] of Object.entries(timestamps)) {
    console.log(`║ ${k}: ${v}`);
  }
  if (timestamps.patientFoundInRAF && timestamps.syncTriggered) {
    const d = (new Date(timestamps.patientFoundInRAF).getTime() - new Date(timestamps.syncTriggered).getTime()) / 1000;
    console.log(`║ ── SYNC DELAY: ${d.toFixed(0)} seconds ──`);
  }
  console.log("╚════════════════════════════════════════════════╝");

  fs.writeFileSync(path.join(SS_DIR, "summary.json"), JSON.stringify({
    patient: { name: "Eleanor Grace Whitfield", dob: "1952-07-14", sex: "Female", fhirId: FHIR_ID },
    timestamps, rafPid: foundPid,
    screenshots: fs.readdirSync(SS_DIR).filter(f => f.endsWith(".png")).sort(),
  }, null, 2));

  await browser.close();
  console.log("\n=== COMPLETE ===");
}

main().catch(console.error);
